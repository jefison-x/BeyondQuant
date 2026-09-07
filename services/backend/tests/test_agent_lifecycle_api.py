import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent_research import AgentResearchStore
from packages.contracts.agent_run_lifecycle import registration_fingerprint, lifecycle_receipt
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="requires isolated PostgreSQL")


def setup():
    ctx = trusted_agent_context("alice", actor="byq-product-agent-session-lifecycle",
                                session_id="session-lifecycle", trace_id="trace-lifecycle", dsh_run_id="generation-lifecycle")
    client = TestClient(main.app)
    consumer = {**ctx, "x-byq-actor-principal": "alice"}
    conversation = client.post("/v1/product/conversations", headers=consumer,
        json={"runtime_session_id": "session-lifecycle", "trace_id": "trace-lifecycle"}).json()["conversation"]
    digest = registration_fingerprint(*[ctx[f"x-byq-{name}"] for name in (
        "owner-principal", "workspace-id", "actor-principal", "trace-id", "session-id", "dsh-run-id")], "original-key")
    registration = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
                    "sequence": 1, "outcome": "active", "registration_fingerprint": digest}
    path = f"/internal/agent-lifecycle/{conversation['conversation_id']}"
    return client, ctx, consumer, registration, path


def consume(client, path, headers, event, **overrides):
    return client.post(path, headers=headers, json={"session_id": "session-lifecycle",
                       "trace_id": "trace-lifecycle", "event": event, **overrides})


def test_api_binds_pending_registration_closes_and_replays_exact_durable_receipt():
    client, ctx, consumer, registration, path = setup()
    run = client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "original-key"}).json()["run"]
    assert run["status"] == "pending_binding"
    assert "runtime_registration_fingerprint" not in run
    assert client.post("/v1/agents/authorize", headers=ctx,
        json={"run_id": run["run_id"], "action": "byq_factor_compute"}).status_code == 403
    assert consume(client, path, consumer, registration).json() == {"receipt": lifecycle_receipt(registration)}
    receipt_path = "/v1/agents/runs/registration-receipt?idempotency_key=original-key"
    assert client.get(receipt_path, headers=ctx).json()["run"]["status"] == "active"
    terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32, "sequence": 2, "outcome": "failed"}
    first = consume(client, path, consumer, terminal)
    assert first.status_code == 200
    assert first.json() == consume(client, path, consumer, terminal).json()
    assert client.get(receipt_path, headers=ctx).json()["run"]["status"] == "failed"
    store = AgentResearchStore()
    try:
        assert store._fetch_one("SELECT count(*) AS n FROM agent_runtime_receipts")["n"] == 2
    finally:
        store.close()
    assert consume(client, path, consumer, {**terminal, "outcome": "completed"}).status_code == 409
    assert client.get(receipt_path, headers={**ctx, "x-byq-dsh-run-id": "new-generation"}).status_code == 404
    assert consume(client, path, ctx, terminal).status_code == 403
    assert consume(client, path, consumer, terminal, trace_id="foreign").status_code == 422


def test_late_registration_after_terminal_never_becomes_active():
    client, ctx, consumer, registration, path = setup()
    terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32, "sequence": 2, "outcome": "cancelled"}
    assert consume(client, path, consumer, terminal).status_code == 200
    assert consume(client, path, consumer, registration).status_code == 200
    result = client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "original-key"})
    assert result.status_code == 201
    assert result.json()["run"]["status"] == "cancelled"


def test_receipt_and_terminal_roll_back_together(monkeypatch):
    client, ctx, consumer, registration, path = setup()
    consume(client, path, consumer, registration)
    client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "original-key"})
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(main.agent_store, "_record_runtime_binding_audit", fail)
    terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32, "sequence": 2, "outcome": "failed"}
    with pytest.raises(RuntimeError, match="synthetic audit"):
        consume(client, path, consumer, terminal)
    assert main.agent_store._fetch_one("SELECT count(*) AS n FROM agent_runtime_receipts")["n"] == 1
    assert main.agent_store._fetch_one("SELECT status FROM agent_runtime_turns")["status"] == "active"
