from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.agent_research import AgentResearchStore
from tests.workspace_helpers import trusted_agent_context




pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

def test_agent_api_uses_trusted_runtime_context_and_exposes_audit(monkeypatch, tmp_path) -> None:
    context = trusted_agent_context(
        "alice", trace_id="trace-agent-api-1", session_id="session-agent-api-1",
        dsh_run_id="dsh-run-agent-api-1",
    )
    store = AgentResearchStore()
    monkeypatch.setattr(main, "agent_store", store)
    client = TestClient(main.app)

    started = client.post(
        "/v1/agents/runs",
        headers=context,
        json={"role_id": "quant_orchestrator", "idempotency_key": "api-agent-run-1"},
    )
    assert started.status_code == 201, started.text
    run = started.json()["run"]
    assert run["owner_principal"] == "alice"
    assert run["session_id"] == "session-agent-api-1"
    assert "request_hash" not in run

    missing_context = client.post(
        "/v1/agents/authorize",
        json={"run_id": run["run_id"], "action": "byq_factor_compute"},
    )
    assert missing_context.status_code == 401

    authorized = client.post(
        "/v1/agents/authorize",
        headers=context,
        json={"run_id": run["run_id"], "action": "byq_factor_compute"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["authorization"]["decision"] == "allowed"

    denied_context = trusted_agent_context("bob")
    denied = client.post(
        "/v1/agents/authorize",
        headers=denied_context,
        json={"run_id": run["run_id"], "action": "byq_factor_compute"},
    )
    assert denied.status_code == 401

    forged_context = {
        **context,
        "x-byq-workspace-id": denied_context["x-byq-workspace-id"],
    }
    forged = client.get(f"/v1/agents/runs/{run['run_id']}/audit", headers=forged_context)
    assert forged.status_code == 401

    audit = client.get(f"/v1/agents/runs/{run['run_id']}/audit", headers=context)
    assert audit.status_code == 200
    assert audit.json()["events"][0]["run_id"] == run["run_id"]

    missing_audit_context = client.get(f"/v1/agents/runs/{run['run_id']}/audit")
    assert missing_audit_context.status_code == 401
    store.close()
