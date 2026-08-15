from __future__ import annotations

import pytest

from app.agent_research import (
    AgentForbidden,
    AgentResearchStore,
    ROLE_BY_ID,
    role_catalog,
)


def start(store: AgentResearchStore, **overrides: object) -> dict[str, object]:
    payload = {
        "owner_principal": "alice",
        "actor_principal": "alice",
        "role_id": "quant_orchestrator",
        "trace_id": "trace-agent-1",
        "session_id": "session-agent-1",
        "dsh_run_id": "dsh-run-agent-1",
        "idempotency_key": "agent-run-1",
    }
    payload.update(overrides)
    return store.start_run(payload)


def test_role_catalog_is_versioned_and_has_explicit_least_privilege() -> None:
    roles = role_catalog()
    assert {role["role_id"] for role in roles} == {
        "quant_orchestrator",
        "market_researcher",
        "factor_researcher",
        "strategy_researcher",
        "backtest_analyst",
    }
    strategy_tools = set(ROLE_BY_ID["strategy_researcher"].allowed_tools)
    assert "byq_strategy_validate" in strategy_tools
    assert "byq_strategy_approve" not in strategy_tools
    assert "byq_backtest_run" not in strategy_tools


def test_runs_are_owner_scoped_idempotent_and_delegation_is_allowlisted(tmp_path) -> None:
    store = AgentResearchStore(tmp_path / "agent.sqlite3")
    parent = start(store)
    same = start(store)
    assert same["run_id"] == parent["run_id"]

    child = start(
        store,
        role_id="market_researcher",
        parent_run_id=parent["run_id"],
        idempotency_key="agent-run-child-1",
    )
    assert child["role_id"] == "market_researcher"

    with pytest.raises(AgentForbidden):
        start(
            store,
            role_id="backtest_analyst",
            parent_run_id=child["run_id"],
            idempotency_key="agent-run-child-2",
        )
    store.close()


def test_authorization_approval_and_audit_keep_execution_separate(tmp_path) -> None:
    store = AgentResearchStore(tmp_path / "agent.sqlite3")
    run = start(store)

    allowed = store.authorize({"run_id": run["run_id"], "action": "byq_factor_compute"})
    assert allowed["decision"] == "allowed"
    pending = store.create_approval(
        {
            "run_id": run["run_id"],
            "action": "byq_backtest_run",
            "reason": "Run the reviewed deterministic job.",
            "idempotency_key": "approval-1",
        }
    )
    assert pending["status"] == "pending"

    with pytest.raises(AgentForbidden, match="self-approve"):
        store.decide_approval(
            {"approval_id": pending["approval_id"], "decision": "approved"},
            trusted_actor="alice",
        )
    approved = store.decide_approval(
        {
            "approval_id": pending["approval_id"],
            "decision": "approved",
            "rationale": "Human review completed.",
        },
        trusted_owner="alice",
        trusted_actor="human-reviewer",
    )
    assert approved["status"] == "approved"
    assert approved["execution_outcome"] == "authorized"

    audit = store.record_audit(
        {
            "run_id": run["run_id"],
            "action": "byq_backtest_run",
            "outcome": "completed",
            "resource_type": "backtest_job",
            "resource_id": "job-1",
            "detail": {"result_ref": "artifact-result-1"},
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert audit["outcome"] == "completed"
    with pytest.raises(ValueError, match="credential"):
        store.record_audit(
            {
                "run_id": run["run_id"],
                "action": "byq_backtest_run",
                "outcome": "failed",
                "detail": {"nested": [{"api-key": "must-not-be-recorded"}]},
            },
            trusted_owner="alice",
            trusted_actor="alice",
        )
    listed = store.list_audit(run["run_id"], trusted_owner="alice")
    assert [event["outcome"] for event in listed["events"]][-1] == "completed"
    store.close()
