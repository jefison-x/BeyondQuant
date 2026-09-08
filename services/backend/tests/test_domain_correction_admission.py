from concurrent.futures import ThreadPoolExecutor

import pytest

from app.agent_research import AgentConflict, AgentResearchStore
from app.domain_call_admission import DomainValidationRejected
from app.research import ResearchStore
from packages.contracts.domain_call_admission import request_evidence
from tests.test_domain_call_evidence import observed, pytestmark
from tests.test_agent_run_lifecycle import apply


def request(observed, key, script, *, sequence, prove=True):
    store, evidence, scope, _ = observed
    payload = {"task_id": evidence["task_id"], "agent_run_id": evidence["agent_run_id"],
               "idempotency_key": key, "strategy": {"script": script}}
    if prove:
        proof = {**evidence, **request_evidence(evidence["action"], payload, trace_id=scope["trusted_trace_id"]),
                 "sequence": sequence}
        store.consume_domain_call_evidence(proof, **scope)
    context = {key: value for key, value in scope.items() if key != "conversation_id"}
    return payload, {**context, "trusted_generation": evidence["generation"], "trusted_root": evidence["root_run_id"]}


def claim(observed, key="call", script="bad", sequence=2, prove=True):
    payload, context = request(observed, key, script, sequence=sequence, prove=prove)
    return observed[0].claim_domain_call("byq_strategy_validate", payload, **context)


def invalid(connection):
    raise DomainValidationRejected("synthetic code detail that must not persist")


def test_missing_proof_and_late_delivery_do_not_execute(observed):
    store = observed[0]
    assert claim(observed, prove=False) == {"state": "blocked", "reason": "call_evidence_pending"}
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_claims")["n"] == 0
    payload, ctx = request(observed, "call", "bad", sequence=2)
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_claims")["n"] == 0
    assert store.claim_domain_call("byq_strategy_validate", payload, **ctx)["state"] == "claimed"


def test_failed_input_new_key_never_runs_and_one_repair_survives_restart(observed):
    store = observed[0]
    first = claim(observed)
    failure = store.execute_domain_call(first, invalid)
    assert failure["state"] == "correctable_failure"
    assert claim(observed, sequence=3) == failure
    assert claim(observed, key="changed-key", sequence=4) == {"state": "blocked", "reason": "unchanged_failed_input"}
    repair = claim(observed, key="repair", script="changed", sequence=5)
    assert store.execute_domain_call(repair, lambda conn: {"validated": True})["state"] == "succeeded"
    reopened = AgentResearchStore()
    try:
        payload, context = request(observed, "third", "third input", sequence=6)
        assert reopened.claim_domain_call("byq_strategy_validate", payload, **context) == {
            "state": "blocked", "reason": "correction_budget_exhausted"}
    finally:
        reopened.close()


def test_second_failure_cannot_reset_budget_and_same_key_changed_input_conflicts(observed):
    store = observed[0]
    store.execute_domain_call(claim(observed), invalid)
    store.execute_domain_call(claim(observed, "repair", "changed", sequence=3), invalid)
    assert claim(observed, "third", "third", sequence=4)["reason"] == "correction_budget_exhausted"
    with pytest.raises(AgentConflict):
        claim(observed, "repair", "different again", sequence=5)


@pytest.mark.parametrize("crash", [False, True])
def test_claim_or_execution_crash_keeps_unknown_and_never_refunds(observed, crash):
    store = observed[0]
    first = claim(observed)
    if crash:
        def fail(connection):
            raise RuntimeError("synthetic crash")
        with pytest.raises(RuntimeError):
            store.execute_domain_call(first, fail)
    assert claim(observed, sequence=3) == {"state": "unknown"}
    assert claim(observed, "new-key", "new input", sequence=4)["reason"] == "prior_call_outcome_unknown"


def test_normal_successes_do_not_debit_repair(observed):
    store = observed[0]
    for sequence in (2, 3, 4):
        value = claim(observed, str(sequence), str(sequence), sequence=sequence)
        assert store.execute_domain_call(value, lambda conn: {"validated": True})["state"] == "succeeded"
    row = store._fetch_one("SELECT * FROM agent_domain_correction_buckets")
    assert row["failed_input_sha256"] is None and row["repair_used"] is False


def test_concurrent_repairs_only_claim_one_changed_input(observed):
    store = observed[0]
    store.execute_domain_call(claim(observed), invalid)
    requests = [request(observed, f"repair-{n}", f"changed-{n}", sequence=n + 3) for n in range(2)]
    def take(value):
        local = AgentResearchStore()
        try:
            return local.claim_domain_call("byq_strategy_validate", value[0], **value[1])
        finally:
            local.close()
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(take, requests))
    assert sorted(result["state"] for result in results) == ["blocked", "claimed"]
    assert store._fetch_one("SELECT repair_used FROM agent_domain_correction_buckets")["repair_used"] is True


def test_artifact_and_success_receipt_commit_or_rollback_together(observed):
    store, evidence, _, _ = observed
    research = ResearchStore()
    try:
        def write(connection):
            artifact = research.create_artifact({"task_id": evidence["task_id"], "kind": "strategy_draft",
                "content": {"synthetic": True}, "lineage": [], "trace_id": "trace-test", "idempotency_key": "atomic"},
                _connection=connection)
            return research.transition("artifact", artifact["artifact_id"], "validated", "atomic-transition", _connection=connection)
        def crash(connection):
            write(connection)
            raise RuntimeError("synthetic receipt failure")
        with pytest.raises(RuntimeError):
            store.execute_domain_call(claim(observed), crash)
        assert store._fetch_one("SELECT count(*) AS n FROM artifacts")["n"] == 0
        assert store._fetch_one("SELECT count(*) AS n FROM research_transitions")["n"] == 0
    finally:
        research.close()


def test_terminal_between_claim_and_execution_prevents_write_but_not_receipt_replay(observed):
    store, _, _, ctx = observed
    first = claim(observed)
    apply(store, ctx, "a" * 32, outcome="cancelled", sequence=5)
    calls = []
    with pytest.raises(AgentConflict):
        store.execute_domain_call(first, lambda conn: calls.append(True))
    assert calls == []
    assert claim(observed, sequence=3) == {"state": "unknown"}


@pytest.mark.parametrize("action,path", [
    ("byq_strategy_validate", "/v1/research/strategies/validate"),
    ("byq_ml_strategy_create", "/v1/research/ml/strategies/versions"),
])
def test_real_domain_api_requires_proof_and_replays_atomic_success(observed, action, path):
    from fastapi.testclient import TestClient
    from app import main
    from test_strategy_artifact import strategy_payload
    from tests.test_ml_strategy import valid_strategy
    store, evidence, scope, ctx = observed
    headers = {**ctx, "x-byq-root-run-id": evidence["root_run_id"]}
    if action == "byq_ml_strategy_create":
        from tests.test_agent_run_lifecycle import start
        apply(store, ctx, evidence["root_run_id"], key="ml-agent", sequence=2)
        ml_run = start(store, ctx, "ml-agent", role_id="ml_researcher")
        evidence = {**evidence, "agent_run_id": ml_run["run_id"]}
    payload = {"task_id": evidence["task_id"], "agent_run_id": evidence["agent_run_id"],
        "trace_id": "model-trace-ignored", "idempotency_key": "actual-validation",
        "strategy": strategy_payload() if action == "byq_strategy_validate" else valid_strategy()}
    client = TestClient(main.app)
    pending = client.post(path, json=payload, headers=headers)
    assert pending.status_code == 425, pending.text
    proof = {**evidence, **request_evidence(action, payload, trace_id="trace-test"), "sequence": 2}
    store.consume_domain_call_evidence(proof, **scope)
    reply = client.post(path, json=payload, headers=headers)
    assert reply.status_code == 201, reply.text
    assert reply.json()["artifact"]["status"] == "validated"
    assert client.post(path, json=payload, headers=headers).json() == reply.json()
    assert store._fetch_one("SELECT count(*) AS n FROM artifacts")["n"] == 1
    assert store._fetch_one("SELECT status FROM agent_domain_call_claims")["status"] == "succeeded"
    # Unproven roots receive only the same pre-execution pending response;
    # they neither discover foreign registrations nor execute another write.
    assert client.post(path, json=payload, headers={**headers, "x-byq-root-run-id": "b" * 32}).status_code == 425
    assert store._fetch_one("SELECT count(*) AS n FROM artifacts")["n"] == 1


def test_schema_rejection_debits_without_artifact_or_domain_validation(observed, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    store, evidence, scope, ctx = observed
    payload, _ = request(observed, "schema-failure", "invalid", sequence=2)
    calls = []
    monkeypatch.setattr(main, "prepare_strategy", lambda *args: calls.append(True))
    reply = TestClient(main.app).post("/internal/domain-validation/schema-rejection",
        json={"action": "byq_strategy_validate", "arguments": payload},
        headers={**ctx, "x-byq-root-run-id": evidence["root_run_id"]})
    assert reply.status_code == 422, reply.text
    assert reply.json()["detail"]["state"] == "correctable_failure"
    assert calls == []
    assert store._fetch_one("SELECT count(*) AS n FROM artifacts")["n"] == 0
    assert store._fetch_one("SELECT failed_input_sha256 FROM agent_domain_correction_buckets")["failed_input_sha256"]


def test_child_or_role_change_cannot_reset_failed_input_bucket(observed):
    from tests.test_agent_run_lifecycle import start
    store, evidence, scope, ctx = observed
    store.execute_domain_call(claim(observed), invalid)
    apply(store, ctx, evidence["root_run_id"], key="child", sequence=3)
    child = start(store, ctx, "child", role_id="strategy_researcher", parent_run_id=evidence["agent_run_id"])
    payload, context = request(observed, "child-key", "bad", sequence=3, prove=False)
    payload["agent_run_id"] = child["run_id"]
    proof = {**evidence, **request_evidence(evidence["action"], payload, trace_id="trace-test"), "sequence": 3}
    store.consume_domain_call_evidence(proof, **scope)
    assert store.claim_domain_call(evidence["action"], payload, **context)["reason"] == "unchanged_failed_input"
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_correction_buckets")["n"] == 1


def test_private_replay_cannot_change_catalog_binding(observed):
    from app.agent_research import AgentUnauthorized
    store, evidence, scope, _ = observed
    store.consume_domain_call_evidence(evidence, **scope)
    with pytest.raises(AgentUnauthorized):
        store.consume_domain_call_evidence(evidence, **{**scope, "conversation_id": "conversation_foreign"})
