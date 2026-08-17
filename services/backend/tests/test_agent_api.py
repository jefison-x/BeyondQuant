from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.agent_research import AgentResearchStore




pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

CONTEXT = {
    "x-byq-owner-principal": "alice",
    "x-byq-actor-principal": "alice",
    "x-byq-trace-id": "trace-agent-api-1",
    "x-byq-session-id": "session-agent-api-1",
    "x-byq-dsh-run-id": "dsh-run-agent-api-1",
}


def test_agent_api_uses_trusted_runtime_context_and_exposes_audit(monkeypatch, tmp_path) -> None:
    store = AgentResearchStore()
    monkeypatch.setattr(main, "agent_store", store)
    client = TestClient(main.app)

    started = client.post(
        "/v1/agents/runs",
        headers=CONTEXT,
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
        headers=CONTEXT,
        json={"run_id": run["run_id"], "action": "byq_factor_compute"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["authorization"]["decision"] == "allowed"

    denied_context = {**CONTEXT, "x-byq-owner-principal": "bob", "x-byq-actor-principal": "bob"}
    denied = client.post(
        "/v1/agents/authorize",
        headers=denied_context,
        json={"run_id": run["run_id"], "action": "byq_factor_compute"},
    )
    assert denied.status_code == 401

    audit = client.get(f"/v1/agents/runs/{run['run_id']}/audit", headers=CONTEXT)
    assert audit.status_code == 200
    assert audit.json()["events"][0]["run_id"] == run["run_id"]

    missing_audit_context = client.get(f"/v1/agents/runs/{run['run_id']}/audit")
    assert missing_audit_context.status_code == 401
    store.close()