import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

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


def disable_identity(part):
    statements = {
        "user": "UPDATE users SET status='disabled' WHERE username='alice'",
        "workspace": "UPDATE workspaces SET status='disabled' WHERE owner_user_id IN (SELECT user_id FROM users WHERE username='alice')",
        "membership": "UPDATE workspace_memberships SET status='disabled' WHERE user_id IN (SELECT user_id FROM users WHERE username='alice')",
    }
    with main.agent_store.engine.begin() as connection:
        connection.execute(text(statements[part]))


@pytest.mark.parametrize("part", ["user", "workspace", "membership"])
@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled", "interrupted"])
def test_disabled_identity_only_allows_existing_bound_terminal_cleanup(part, outcome):
    client, ctx, consumer, registration, path = setup()
    assert consume(client, path, consumer, registration).status_code == 200
    run = client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "original-key"}).json()["run"]
    disable_identity(part)
    assert consume(client, path, consumer, registration).status_code == 401
    assert client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "new-key"}).status_code in (401, 403)
    assert client.get("/v1/agents/runs/registration-receipt?idempotency_key=original-key",
                      headers=ctx).status_code in (401, 403)
    assert client.get("/v1/product/conversations", headers=consumer).status_code == 401
    assert client.post("/v1/agents/authorize", headers=ctx,
        json={"run_id": run["run_id"], "action": "byq_factor_compute"}).status_code in (401, 403)
    terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
                "sequence": 2, "outcome": outcome}
    assert consume(client, path, consumer, {**terminal, "root_run_id": "b" * 32}).status_code == 401
    assert consume(client, path, consumer, terminal, trace_id="foreign").status_code == 422
    assert consume(client, path, ctx, terminal).status_code == 403
    result = consume(client, path, consumer, terminal)
    assert result.status_code == 200, result.text
    assert result.json() == {"receipt": lifecycle_receipt(terminal)}
    assert consume(client, path, consumer, terminal).json() == result.json()
    saved = main.agent_store._fetch_one("SELECT * FROM agent_runs")
    assert saved["status"] == outcome
    assert saved["version"] == run["version"] + 1
    assert main.agent_store._fetch_one("SELECT count(*) AS n FROM agent_runtime_receipts")["n"] == 2
    assert main.agent_store._fetch_one("SELECT count(*) AS n FROM agent_approvals")["n"] == 0
    assert main.agent_store._fetch_one("SELECT count(*) AS n FROM research_tasks")["n"] == 0


@pytest.mark.parametrize("part", ["user", "workspace", "membership"])
def test_disabled_cleanup_rollback_and_database_guards(part, monkeypatch):
    client, ctx, consumer, registration, path = setup()
    foreign = trusted_agent_context("bob")
    assert consume(client, path, consumer, registration).status_code == 200
    client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "original-key"})
    disable_identity(part)
    terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
                "sequence": 2, "outcome": "failed"}
    original = main.agent_store._record_runtime_binding_audit
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic disabled audit failure")
    monkeypatch.setattr(main.agent_store, "_record_runtime_binding_audit", fail)
    with pytest.raises(RuntimeError, match="synthetic disabled"):
        consume(client, path, consumer, terminal)
    assert main.agent_store._fetch_one("SELECT status FROM agent_runs")["status"] == "active"
    assert main.agent_store._fetch_one("SELECT status FROM agent_runtime_turns")["status"] == "active"
    assert main.agent_store._fetch_one("SELECT count(*) AS n FROM agent_runtime_receipts")["n"] == 1
    with pytest.raises(DBAPIError):
        with main.agent_store.engine.begin() as connection:
            connection.execute(text("UPDATE agent_runs SET owner_principal='bob',workspace_id=:workspace"),
                               {"workspace": foreign["x-byq-workspace-id"]})
    # Even with terminal root proof, unrelated run mutations and arbitrary audit
    # writes remain denied by PostgreSQL, not merely by HTTP validation.
    for mutation in ["actor_principal='forged'", "trace_id='forged'", "version=version+2"]:
        with pytest.raises(DBAPIError):
            with main.agent_store.engine.begin() as connection:
                connection.execute(text("UPDATE agent_runtime_turns SET status='failed',terminal_sequence=2"))
                assignments = "status='failed'," + ("version=version+1," if not mutation.startswith("version") else "") + mutation
                connection.execute(text("UPDATE agent_runs SET " + assignments))
    monkeypatch.setattr(main.agent_store, "_record_runtime_binding_audit", original)
    assert consume(client, path, consumer, terminal).status_code == 200
    for mutation in ["action='forged'", "detail_json='{}'::jsonb", "actor_principal='forged'"]:
        with pytest.raises(DBAPIError):
            with main.agent_store.engine.begin() as connection:
                connection.execute(text("UPDATE agent_audit SET " + mutation))
    run = main.agent_store._fetch_one("SELECT * FROM agent_runs")
    with pytest.raises(DBAPIError):
        with main.agent_store._transaction() as connection:
            main.agent_store._record_audit_row(run, action="runtime_turn_binding", outcome="failed",
                resource_type="runtime_turn", resource_id="a" * 32,
                detail={"root_run_id": "a" * 32, "terminal_sequence": 999}, connection=connection)


def test_disabled_unbound_run_is_not_guessed_or_registered():
    client, ctx, consumer, registration, path = setup()
    client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "original-key"})
    disable_identity("user")
    assert consume(client, path, consumer, registration).status_code == 401
    terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
                "sequence": 2, "outcome": "interrupted"}
    assert consume(client, path, consumer, terminal).status_code == 401
    assert main.agent_store._fetch_one("SELECT status FROM agent_runs")["status"] == "pending_binding"
    assert main.agent_store._fetch_one("SELECT count(*) AS n FROM agent_runtime_turns")["n"] == 0


def test_cleanup_requires_existing_membership_and_exact_catalog_owner():
    client, ctx, consumer, registration, path = setup()
    assert consume(client, path, consumer, registration).status_code == 200
    client.post("/v1/agents/runs", headers=ctx,
        json={"role_id": "quant_orchestrator", "idempotency_key": "original-key"})
    foreign = trusted_agent_context("bob")
    terminal = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
                "sequence": 2, "outcome": "interrupted"}
    assert consume(client, path, foreign, terminal).status_code == 404
    assert consume(client, path, {**consumer, "x-byq-workspace-id": foreign["x-byq-workspace-id"]},
                   terminal).status_code == 422
    disable_identity("user")
    with main.agent_store.engine.begin() as connection:
        connection.execute(text("DELETE FROM workspace_memberships WHERE workspace_id=:workspace"),
                           {"workspace": ctx["x-byq-workspace-id"]})
    assert consume(client, path, consumer, terminal).status_code == 401
    assert main.agent_store._fetch_one("SELECT status FROM agent_runs")["status"] == "active"
    assert main.agent_store._fetch_one("SELECT count(*) AS n FROM agent_runtime_receipts")["n"] == 1


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
