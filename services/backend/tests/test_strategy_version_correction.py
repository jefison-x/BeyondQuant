"""Version admission uses real PostgreSQL and HTTP; no model or provider."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent_research import AgentResearchStore
from packages.contracts.domain_call_admission import request_evidence
from tests.test_domain_call_evidence import observed, pytestmark
from test_strategy_artifact import strategy_payload


@pytest.mark.parametrize("crash_before_transition", [False, True])
def test_version_schema_repair_commits_original_receipt_and_survives_restart(observed, monkeypatch, crash_before_transition):
    store, evidence, scope, ctx = observed
    monkeypatch.setattr(main, "agent_store", store)
    client = TestClient(main.app)
    human = {**ctx, "x-byq-actor-principal": "alice"}
    draft = client.post("/v1/research/strategies/validate", headers=human, json={
        "task_id": evidence["task_id"], "trace_id": "trace-test", "idempotency_key": "human-draft",
        "strategy": strategy_payload(),
    })
    assert draft.status_code == 201, draft.text
    assert store._fetch_one("SELECT count(*) AS n FROM agent_domain_call_claims")["n"] == 0
    payload = {"task_id": evidence["task_id"], "agent_run_id": evidence["agent_run_id"],
               "trace_id": "trace-test", "idempotency_key": "version",
               "draft_artifact_id": draft.json()["artifact"]["artifact_id"]}
    headers = {**ctx, "x-byq-root-run-id": evidence["root_run_id"]}
    path = "/v1/research/strategies/versions"
    assert client.post(path, headers=headers, json=payload).status_code == 425
    action = "byq_strategy_version_create"
    def prove(data, sequence):
        store.consume_domain_call_evidence({**evidence,
            **request_evidence(action, data, trace_id="trace-test"), "sequence": sequence}, **scope)
    invalid = {**payload, "draft_artifact_id": 42, "idempotency_key": "schema-invalid"}
    prove(invalid, 2)
    rejected = client.post("/internal/domain-validation/schema-rejection", headers=headers,
                           json={"action": action, "arguments": invalid})
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["state"] == "correctable_failure"
    prove(payload, 3)
    if crash_before_transition:
        original_transition = main.research_store.transition
        def crash(*args, **kwargs):
            raise RuntimeError("synthetic failure after version insertion")
        monkeypatch.setattr(main.research_store, "transition", crash)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            client.post(path, headers=headers, json=payload)
        monkeypatch.setattr(main.research_store, "transition", original_transition)
        assert store._fetch_one("SELECT count(*) AS n FROM artifacts WHERE kind='strategy_version'")["n"] == 0
        unknown = client.post(path, headers=headers, json=payload)
        assert unknown.status_code == 409, unknown.text
        assert unknown.json()["detail"]["state"] == "unknown"
        return
    created = client.post(path, headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["artifact"]["status"] == "validated"
    reopened = AgentResearchStore()
    monkeypatch.setattr(main, "agent_store", reopened)
    try:
        replay = client.post(path, headers=headers, json=payload)
        assert replay.status_code == 201 and replay.json() == created.json()
        assert store._fetch_one("SELECT count(*) AS n FROM artifacts WHERE kind='strategy_version'")["n"] == 1
        third = {**payload, "idempotency_key": "third", "draft_artifact_id": "different"}
        prove(third, 4)
        blocked = client.post(path, headers=headers, json=third)
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["reason"] == "correction_budget_exhausted"
    finally:
        reopened.close()


def test_version_repairs_are_atomic_and_do_not_share_other_action_evidence(observed):
    from concurrent.futures import ThreadPoolExecutor
    from app.domain_call_admission import DomainValidationRejected
    from app.agent_research import AgentConflict
    store, event, scope, _ = observed
    context = {key: value for key, value in scope.items() if key != "conversation_id"}
    context.update(trusted_generation=event["generation"], trusted_root=event["root_run_id"])
    action = "byq_strategy_version_create"
    base = {"task_id": event["task_id"], "agent_run_id": event["agent_run_id"],
            "idempotency_key": "same-key", "draft_artifact_id": 42}
    def prove(name, payload, sequence):
        store.consume_domain_call_evidence({**event,
            **request_evidence(name, payload, trace_id="trace-test"), "sequence": sequence}, **scope)
    # A proven validate call with the same original task/run/key cannot admit a version.
    other = {key: value for key, value in base.items() if key != "draft_artifact_id"}
    other["strategy"] = {"script": "invalid"}
    prove("byq_strategy_validate", other, 2)
    assert store.claim_domain_call(action, base, **context)["reason"] == "call_evidence_pending"
    prove(action, base, 3)
    first = store.claim_domain_call(action, base, **context)
    def reject(connection):
        raise DomainValidationRejected("synthetic SDK rejection")
    assert store.execute_domain_call(first, reject)["state"] == "correctable_failure"
    # Failure in version creation does not consume validation's separate allowance.
    other_claim = store.claim_domain_call("byq_strategy_validate", other, **context)
    assert other_claim["state"] == "claimed"
    assert store.execute_domain_call(other_claim, lambda connection: {"synthetic": True})["state"] == "succeeded"
    repairs = [{**base, "idempotency_key": f"repair-{index}", "draft_artifact_id": f"draft-{index}"}
               for index in range(2)]
    for index, repair in enumerate(repairs):
        prove(action, repair, 4 + index)
    def claim(payload):
        local = AgentResearchStore()
        try:
            return local.claim_domain_call(action, payload, **context)
        finally:
            local.close()
    with ThreadPoolExecutor(2) as executor:
        outcomes = list(executor.map(claim, repairs))
    assert sorted(result["state"] for result in outcomes) == ["blocked", "claimed"]
    winner_index = next(index for index, result in enumerate(outcomes) if result["state"] == "claimed")
    winner = repairs[winner_index]
    assert store.execute_domain_call(outcomes[winner_index], reject) == {
        "state": "correctable_failure", "reason": "correction_failed"}
    changed_same_key = {**winner, "draft_artifact_id": "third-draft"}
    prove(action, changed_same_key, 6)
    with pytest.raises(AgentConflict):
        store.claim_domain_call(action, changed_same_key, **context)
    third = {**changed_same_key, "idempotency_key": "third"}
    prove(action, third, 7)
    assert store.claim_domain_call(action, third, **context)["reason"] == "correction_budget_exhausted"
    assert store._fetch_one("SELECT count(*) AS n FROM artifacts")["n"] == 0
