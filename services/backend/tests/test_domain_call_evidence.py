import os

import pytest

from app.agent_research import AgentConflict, AgentResearchStore, AgentUnauthorized
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from packages.contracts.domain_call_admission import call_evidence_receipt, request_evidence
from tests.test_agent_run_lifecycle import apply, start
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="requires isolated PostgreSQL")


@pytest.fixture
def observed():
    ctx = trusted_agent_context("alice", actor="byq-product-agent-session-test", dsh_run_id="generation-test")
    catalog, research, agents = ConversationCatalogStore(), ResearchStore(), AgentResearchStore()
    conversation = catalog.create("alice", "session-test", "trace-test")
    task = research.create_task({"owner_principal": "alice", "title": "Synthetic strategy",
        "objective": "Synthetic bounded validation", "trace_id": "trace-test", "idempotency_key": "task"},
        trusted_context={key.removeprefix("x-byq-").replace("-", "_"): value for key, value in ctx.items()})
    apply(agents, ctx, "a" * 32, key="agent")
    run = start(agents, ctx, "agent")
    evidence = {"schema_version": "domain-call-observed.v1", "sequence": 1,
        "root_run_id": "a" * 32, "generation": "generation-test", "call_id": "same-call",
        **request_evidence("byq_strategy_validate", {"task_id": task["task_id"], "agent_run_id": run["run_id"],
            "idempotency_key": "validate", "strategy": {"code": "synthetic invalid code"}}, trace_id="trace-test")}
    scope = {"trusted_owner": "alice", "trusted_workspace": ctx["x-byq-workspace-id"],
        "trusted_session_id": "session-test", "trusted_trace_id": "trace-test",
        "conversation_id": conversation["conversation_id"]}
    yield agents, evidence, scope, ctx
    agents.close()
    research.close()
    catalog.close()


def test_exact_evidence_is_durable_idempotent_and_not_an_artifact(observed):
    store, evidence, scope, ctx = observed
    receipt = store.consume_domain_call_evidence(evidence, **scope)
    assert receipt == call_evidence_receipt(evidence)
    assert store._fetch_one("SELECT count(*) AS n FROM artifacts")["n"] == 0
    store.close()
    reopened = AgentResearchStore()
    try:
        assert reopened.consume_domain_call_evidence(evidence, **scope) == receipt
        with pytest.raises(AgentConflict):
            reopened.consume_domain_call_evidence({**evidence, "call_id": "changed"}, **scope)
        # Terminal arrival may precede proof delivery: record evidence only,
        # never reopen the run or execute anything.
        apply(reopened, ctx, "a" * 32, outcome="completed", sequence=3)
        late = {**evidence, "sequence": 2}
        assert reopened.consume_domain_call_evidence(late, **scope) == call_evidence_receipt(late)
        assert start(reopened, ctx, "agent")["status"] == "completed"
    finally:
        reopened.close()


@pytest.mark.parametrize("changed", [
    {"generation": "foreign"}, {"agent_run_id": "agentrun_missing"},
    {"task_id": "task_missing"}, {"root_run_id": "b" * 32},
])
def test_unproven_reference_cannot_create_evidence(observed, changed):
    store, evidence, scope, _ = observed
    with pytest.raises((AgentConflict, AgentUnauthorized)):
        store.consume_domain_call_evidence({**evidence, **changed}, **scope)
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_evidence")["n"] == 0


@pytest.mark.parametrize("changed", [
    {"trusted_session_id": "foreign-session"}, {"trusted_trace_id": "foreign-trace"},
    {"conversation_id": "conversation_foreign"},
])
def test_foreign_scope_cannot_import_proof(observed, changed):
    store, evidence, scope, _ = observed
    with pytest.raises(AgentUnauthorized):
        store.consume_domain_call_evidence(evidence, **{**scope, **changed})


def test_private_endpoint_requires_catalog_actor_and_closed_owned_context(observed):
    from fastapi.testclient import TestClient
    from app import main
    _, evidence, scope, ctx = observed
    client = TestClient(main.app)
    path = "/internal/domain-call-evidence/" + scope["conversation_id"]
    payload = {"session_id": "session-test", "trace_id": "trace-test", "event": evidence}
    assert client.post(path, json=payload, headers=ctx).status_code == 403
    headers = {**ctx, "x-byq-actor-principal": "alice"}
    assert client.post(path, json={**payload, "extra": True}, headers=headers).status_code == 422
    reply = client.post(path, json=payload, headers=headers)
    assert reply.status_code == 200, reply.text
    assert reply.json() == {"receipt": call_evidence_receipt(evidence)}


def test_foreign_owner_workspace_and_root_cannot_reuse_observation(observed):
    store, evidence, scope, _ = observed
    bob = trusted_agent_context("bob", actor="byq-product-agent-session-bob", session_id="session-bob",
        trace_id="trace-bob", dsh_run_id="generation-bob")
    apply(store, bob, "b" * 32, key="bob-agent")
    start(store, bob, "bob-agent")
    for root in ("a" * 32, "b" * 32):
        with pytest.raises(AgentUnauthorized):
            store.consume_domain_call_evidence({**evidence, "root_run_id": root}, **{**scope,
                "trusted_owner": "bob", "trusted_workspace": bob["x-byq-workspace-id"],
                "trusted_session_id": "session-bob", "trusted_trace_id": "trace-bob"})
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_evidence")["n"] == 0
