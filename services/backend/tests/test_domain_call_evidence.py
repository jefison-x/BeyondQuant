import os
import json
import uuid

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
    payload = {"task_id": task["task_id"], "agent_run_id": run["run_id"],
               "idempotency_key": "validate"}
    payload["strategy"] = {"code": "synthetic invalid code"}
    evidence = {"schema_version": "domain-call-observed.v1", "sequence": 1,
        "root_run_id": "a" * 32, "generation": "generation-test", "call_id": "same-call",
        **request_evidence("byq_strategy_validate", payload, trace_id="trace-test")}
    scope = {"trusted_owner": "alice", "trusted_workspace": ctx["x-byq-workspace-id"],
        "trusted_session_id": "session-test", "trusted_trace_id": "trace-test",
        "trusted_boot_id": ctx["x-byq-runtime-boot-id"],
        "conversation_id": conversation["conversation_id"]}
    yield agents, evidence, scope, ctx
    agents.close()
    research.close()
    catalog.close()


def _seed_domain_evidence_history(store, evidence, scope, *, through_sequence):
    """Create valid retained evidence rows from a real accepted proof fixture."""
    rows = []
    for sequence in range(evidence["sequence"] + 1, through_sequence + 1):
        arguments = {
            "task_id": evidence["task_id"],
            "agent_run_id": evidence["agent_run_id"],
            "idempotency_key": f"retained-evidence-{sequence}-{uuid.uuid4().hex}",
            "strategy": {"code": f"SYNTHETIC_HISTORY_{sequence}"},
        }
        item = {
            "schema_version": "domain-call-observed.v1",
            "sequence": sequence,
            "root_run_id": evidence["root_run_id"],
            "generation": evidence["generation"],
            "call_id": f"retained-evidence-{sequence}-{uuid.uuid4().hex}",
            **request_evidence(evidence["action"], arguments, trace_id=scope["trusted_trace_id"]),
        }
        rows.append({
            "owner_principal": scope["trusted_owner"],
            "workspace_id": scope["trusted_workspace"],
            "session_id": scope["trusted_session_id"],
            "trace_id": scope["trusted_trace_id"],
            "sequence": sequence,
            "root_run_id": item["root_run_id"],
            "generation": item["generation"],
            "agent_run_id": item["agent_run_id"],
            "task_id": item["task_id"],
            "action": item["action"],
            "idempotency_key": item["idempotency_key"],
            "request_sha256": item["request_sha256"],
            "input_sha256": item["input_sha256"],
            "evidence_json": item,
            "receipt_json": call_evidence_receipt(item),
        })
    if rows:
        store._execute("""INSERT INTO agent_domain_call_evidence
            (owner_principal,workspace_id,session_id,trace_id,sequence,root_run_id,generation,
             agent_run_id,task_id,action,idempotency_key,request_sha256,input_sha256,evidence_json,receipt_json)
            SELECT seeded.owner_principal,seeded.workspace_id,seeded.session_id,seeded.trace_id,
             seeded.sequence,seeded.root_run_id,seeded.generation,seeded.agent_run_id,seeded.task_id,
             seeded.action,seeded.idempotency_key,seeded.request_sha256,seeded.input_sha256,
             seeded.evidence_json,seeded.receipt_json
            FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS seeded(
             owner_principal text,workspace_id text,session_id text,trace_id text,sequence bigint,
             root_run_id text,generation text,agent_run_id text,task_id text,action text,
             idempotency_key text,request_sha256 text,input_sha256 text,evidence_json jsonb,receipt_json jsonb)""",
            {"rows": json.dumps(rows, separators=(",", ":"), ensure_ascii=True, allow_nan=False)})



@pytest.fixture(params=["byq_strategy_validate", "byq_strategy_version_create"])
def action_observed(observed, request):
    store, evidence, scope, ctx = observed
    if request.param == "byq_strategy_version_create":
        evidence = {**evidence, **request_evidence(request.param, {
            "task_id": evidence["task_id"], "agent_run_id": evidence["agent_run_id"],
            "idempotency_key": "validate", "draft_artifact_id": "draft_synthetic",
        }, trace_id="trace-test")}
    return store, evidence, scope, ctx

def test_exact_evidence_is_durable_idempotent_and_not_an_artifact(action_observed):
    store, evidence, scope, ctx = action_observed
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
def test_unproven_reference_cannot_create_evidence(action_observed, changed):
    store, evidence, scope, _ = action_observed
    with pytest.raises((AgentConflict, AgentUnauthorized)):
        store.consume_domain_call_evidence({**evidence, **changed}, **scope)
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_evidence")["n"] == 0


@pytest.mark.parametrize("changed", [
    {"trusted_session_id": "foreign-session"}, {"trusted_trace_id": "foreign-trace"},
    {"conversation_id": "conversation_foreign"},
])
def test_foreign_scope_cannot_import_proof(action_observed, changed):
    store, evidence, scope, _ = action_observed
    with pytest.raises(AgentUnauthorized):
        store.consume_domain_call_evidence(evidence, **{**scope, **changed})


def test_private_endpoint_requires_catalog_actor_and_closed_owned_context(action_observed):
    from fastapi.testclient import TestClient
    from app import main
    _, evidence, scope, ctx = action_observed
    client = TestClient(main.app)
    path = "/internal/domain-call-evidence/" + scope["conversation_id"]
    payload = {"session_id": "session-test", "trace_id": "trace-test", "event": evidence}
    assert client.post(path, json=payload, headers=ctx).status_code == 403
    headers = {**ctx, "x-byq-actor-principal": "alice"}
    assert client.post(path, json={**payload, "extra": True}, headers=headers).status_code == 422
    reply = client.post(path, json=payload, headers=headers)
    assert reply.status_code == 200, reply.text
    assert reply.json() == {"receipt": call_evidence_receipt(evidence)}


def test_foreign_owner_workspace_and_root_cannot_reuse_observation(action_observed):
    store, evidence, scope, _ = action_observed
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


def test_legacy_consume_accepts_exact_session_evidence_sequence_1025(observed):
    store, evidence, scope, _ = observed
    first_receipt = store.consume_domain_call_evidence(evidence, **scope)
    assert first_receipt == call_evidence_receipt(evidence)
    _seed_domain_evidence_history(store, evidence, scope, through_sequence=1024)

    arguments = {
        "task_id": evidence["task_id"],
        "agent_run_id": evidence["agent_run_id"],
        "idempotency_key": f"legacy-after-history-{uuid.uuid4().hex}",
        "strategy": {"code": "VALID_AFTER_RETAINED_HISTORY"},
    }
    next_evidence = {
        "schema_version": "domain-call-observed.v1",
        "sequence": 1025,
        "root_run_id": evidence["root_run_id"],
        "generation": evidence["generation"],
        "call_id": f"legacy-after-history-{uuid.uuid4().hex}",
        **request_evidence(evidence["action"], arguments, trace_id=scope["trusted_trace_id"]),
    }
    expected_receipt = call_evidence_receipt(next_evidence)
    assert store.consume_domain_call_evidence(next_evidence, **scope) == expected_receipt
    assert store.consume_domain_call_evidence(next_evidence, **scope) == expected_receipt
    with pytest.raises(AgentConflict, match="sequence conflicts"):
        store.consume_domain_call_evidence({**next_evidence, "call_id": "changed-call"}, **scope)
    persisted = store._fetch_one("""SELECT sequence,receipt_json FROM agent_domain_call_evidence
        WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session
          AND sequence=1025""", {"owner": scope["trusted_owner"], "workspace": scope["trusted_workspace"],
        "session": scope["trusted_session_id"]})
    assert persisted == {"sequence": 1025, "receipt_json": expected_receipt}
