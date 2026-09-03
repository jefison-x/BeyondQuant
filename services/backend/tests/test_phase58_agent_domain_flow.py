from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent_research import AgentResearchStore
from app.paper_trading import PaperTradingStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_orchestrator_candidates_to_pool_to_validated_strategy_version(
    monkeypatch,
) -> None:
    agent_store = AgentResearchStore()
    paper_store = PaperTradingStore()
    research_store = ResearchStore()
    monkeypatch.setattr(main, "agent_store", agent_store)
    monkeypatch.setattr(main, "paper_store", paper_store)
    monkeypatch.setattr(main, "research_store", research_store)

    context = trusted_agent_context(
        "phase58-owner",
        trace_id="phase58-agent-domain-flow",
        session_id="phase58-session",
        dsh_run_id="phase58-dsh-run",
    )
    client = TestClient(main.app)
    client.headers.update(context)

    started = client.post(
        "/v1/agents/runs",
        json={"role_id": "quant_orchestrator", "idempotency_key": "phase58-run"},
    )
    assert started.status_code == 201, started.text
    run = started.json()["run"]
    assert run["role_version"] == "1.9.0"

    authorization = client.post(
        "/v1/agents/authorize",
        json={"run_id": run["run_id"], "action": "byq_pool_create"},
    )
    assert authorization.status_code == 200, authorization.text
    assert authorization.json()["authorization"]["decision"] == "allowed"

    created_pool = client.post(
        "/v1/paper/pools",
        json={
            "name": "Phase 58 银行候选池",
            "description": "Frozen candidates supported by current research evidence.",
            "pool_type": "custom",
            "symbols": ["600036.SH", "601166.SH"],
        },
    )
    assert created_pool.status_code == 201, created_pool.text
    pool = created_pool.json()["pool"]
    assert pool["owner_principal"] == "phase58-owner"
    assert pool["pool_type"] == "custom"
    assert pool["symbols"] == ["600036.SH", "601166.SH"]

    hidden_from_other_owner = client.get(
        f"/v1/paper/pools/{pool['pool_id']}",
        headers=trusted_agent_context("phase58-other-owner"),
    )
    assert hidden_from_other_owner.status_code == 404

    strategy_started = client.post(
        "/v1/agents/runs",
        json={
            "role_id": "strategy_researcher",
            "parent_run_id": run["run_id"],
            "idempotency_key": "phase58-strategy-run",
        },
    )
    assert strategy_started.status_code == 201, strategy_started.text
    strategy_run = strategy_started.json()["run"]
    assert strategy_run["role_version"] == "1.2.0"

    def authorize_strategy(action: str) -> None:
        response = client.post(
            "/v1/agents/authorize",
            json={"run_id": strategy_run["run_id"], "action": action},
        )
        assert response.status_code == 200, response.text
        assert response.json()["authorization"]["decision"] == "allowed"

    def audit_strategy(action: str, resource_type: str, resource_id: str) -> None:
        response = client.post(
            "/v1/agents/audit",
            json={
                "run_id": strategy_run["run_id"],
                "action": action,
                "outcome": "success",
                "resource_type": resource_type,
                "resource_id": resource_id,
            },
        )
        assert response.status_code == 200, response.text

    authorize_strategy("byq_research_task_create")

    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "phase58-owner",
            "title": "低回撤银行策略",
            "objective": "Use the frozen bank candidates to design a simple strategy.",
            "trace_id": "phase58-agent-domain-flow",
            "idempotency_key": "phase58-task",
        },
    )
    assert task.status_code == 201, task.text
    task_body = task.json()
    assert task_body["status"] == "planned"
    audit_strategy("byq_research_task_create", "research_task", task_body["task_id"])

    authorize_strategy("byq_strategy_validate")
    validated = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task_body["task_id"],
            "trace_id": "phase58-agent-domain-flow",
            "idempotency_key": "phase58-strategy-draft",
            "strategy": {
                "strategy_id": "LowDrawdownBank",
                "name": "低回撤银行策略",
                "category": "momentum",
                "parameters": {"lookback": 20},
                "data_requirements": {
                    "benchmark": "000300.SH",
                    "daily_basic": ["pe_ttm", "pb"],
                },
                "script": (
                    "class CustomStrategy:\n"
                    "    def generate_signals(self, data, parameters):\n"
                    "        return {}"
                ),
            },
        },
    )
    assert validated.status_code == 201, validated.text
    draft = validated.json()
    assert draft["validation"]["success"] is True
    assert draft["strategy"]["data_requirements"] == {
        "benchmark": "000300.SH",
        "daily_basic": ["pb", "pe_ttm"],
    }
    audit_strategy(
        "byq_strategy_validate", "strategy_draft", draft["artifact"]["artifact_id"]
    )

    authorize_strategy("byq_strategy_version_create")
    versioned = client.post(
        "/v1/research/strategies/versions",
        json={
            "task_id": task_body["task_id"],
            "draft_artifact_id": draft["artifact"]["artifact_id"],
            "trace_id": "phase58-agent-domain-flow",
            "idempotency_key": "phase58-strategy-version",
        },
    )
    assert versioned.status_code == 201, versioned.text
    assert versioned.json()["artifact"]["status"] == "validated"
    assert versioned.json()["artifact"]["owner_principal"] == "phase58-owner"
    audit_strategy(
        "byq_strategy_version_create",
        "strategy_version",
        versioned.json()["artifact"]["artifact_id"],
    )

    audit = client.get(f"/v1/agents/runs/{run['run_id']}/audit")
    assert audit.status_code == 200
    authorize_events = [
        event
        for event in audit.json()["events"]
        if event["action"] == "byq_pool_create"
    ]
    assert len(authorize_events) == 1
    assert authorize_events[0]["outcome"] == "authorized"

    strategy_audit = client.get(
        f"/v1/agents/runs/{strategy_run['run_id']}/audit"
    )
    assert strategy_audit.status_code == 200
    outcomes = [
        (event["action"], event["outcome"])
        for event in strategy_audit.json()["events"]
    ]
    assert outcomes == [
        ("byq_research_task_create", "authorized"),
        ("byq_research_task_create", "success"),
        ("byq_strategy_validate", "authorized"),
        ("byq_strategy_validate", "success"),
        ("byq_strategy_version_create", "authorized"),
        ("byq_strategy_version_create", "success"),
    ]

    agent_store.close()
    paper_store.close()
    research_store.close()
