from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context




pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

def task_body() -> dict[str, object]:
    return {
        "owner_principal": "product-user",
        "title": "API research task",
        "objective": "Exercise the Backend domain contract.",
        "trace_id": "byq-trace-api-1",
        "idempotency_key": "api-task-1",
    }


def _owner_headers(principal: str = "product-user") -> dict[str, str]:
    return trusted_agent_context(
        principal, trace_id=f"byq-trace-{principal}", session_id=f"byq-session-{principal}",
        dsh_run_id=f"byq-run-{principal}",
    )


def test_research_api_exposes_normalized_persistent_entity_flow(monkeypatch) -> None:
    owner_headers = _owner_headers("product-user")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    client.headers.update(owner_headers)

    created = client.post("/v1/research/tasks", json=task_body())
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "planned"
    task_id = task["task_id"]

    fetched = client.get(f"/v1/research/tasks/{task_id}")
    assert fetched.status_code == 200
    detail = fetched.json()
    handoff = detail.pop("handoff")
    assert detail == task
    assert handoff["schema_version"] == "research-task-handoff.v1"
    assert handoff["task_id"] == task_id
    assert handoff["task_status"] == task["status"]
    assert handoff["objective"] == task["objective"]
    assert handoff["state"] == "blocked"
    assert handoff["reason"] == "conversation_binding_missing"
    assert handoff["references"] == []
    assert handoff["has_more"] is False

    hidden = client.get(
        f"/v1/research/tasks/{task_id}",
        headers=_owner_headers("other-user"),
    )
    assert hidden.status_code == 404

    transition = client.post(
        f"/v1/research/tasks/{task_id}/transitions",
        json={"target_status": "running", "idempotency_key": "api-transition-1"},
    )
    assert transition.status_code == 200
    assert transition.json()["status"] == "running"

    invalid = client.post(
        f"/v1/research/tasks/{task_id}/transitions",
        json={"target_status": "completed", "idempotency_key": "api-transition-2", "sql": "no"},
    )
    assert invalid.status_code == 422
    store.close()


def test_research_api_maps_idempotency_and_transition_conflicts(monkeypatch) -> None:
    owner_headers = _owner_headers("product-user")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    client.headers.update(owner_headers)

    created = client.post("/v1/research/tasks", json=task_body()).json()
    conflict = client.post(
        "/v1/research/tasks",
        json={**task_body(), "objective": "different"},
    )
    assert conflict.status_code == 409

    task_id = created["task_id"]
    missing = client.get("/v1/research/tasks/task_00000000000000000000000000000000")
    assert missing.status_code == 404
    invalid_transition = client.post(
        f"/v1/research/tasks/{task_id}/transitions",
        json={"target_status": "completed", "idempotency_key": "api-transition-invalid"},
    )
    assert invalid_transition.status_code == 409
    store.close()


def test_research_task_creation_rejects_owner_spoofing(monkeypatch) -> None:
    other_headers = _owner_headers("other-user")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)

    response = client.post(
        "/v1/research/tasks",
        headers=other_headers,
        json=task_body(),
    )

    assert response.status_code == 422
    assert store.list_tasks(owner_principal="product-user")["tasks"] == []
    store.close()


@pytest.mark.parametrize("operation", ["task_transition", "experiment_create", "experiment_transition", "artifact_create", "artifact_transition"])
def test_all_generic_research_writes_require_the_resource_owner(monkeypatch, operation) -> None:
    from tests.test_research import experiment_payload
    owner = _owner_headers("product-user")
    other = _owner_headers("other-user")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    try:
        task = store.create_task(task_body())
        experiment = store.create_experiment(experiment_payload(task["task_id"]))
        artifact_body = {"task_id": task["task_id"], "kind": "evidence", "content": {"synthetic": True},
                         "lineage": [], "trace_id": "scope-test", "idempotency_key": "scope-artifact"}
        artifact = store.create_artifact(artifact_body)
        transition = {"target_status": "running", "idempotency_key": "scope-transition"}
        paths = {
            "task_transition": (f"/v1/research/tasks/{task['task_id']}/transitions", transition),
            "experiment_create": ("/v1/research/experiments", experiment_payload(task["task_id"], idempotency_key="scope-experiment-new")),
            "experiment_transition": (f"/v1/research/experiments/{experiment['experiment_id']}/transitions", transition),
            "artifact_create": ("/v1/research/artifacts", {**artifact_body, "idempotency_key": "scope-artifact-new"}),
            "artifact_transition": (f"/v1/research/artifacts/{artifact['artifact_id']}/transitions", {**transition, "target_status": "validated"}),
        }
        path, payload = paths[operation]
        client = TestClient(main.app)
        assert client.post(path, headers=other, json=payload).status_code == 404
        assert client.post(path, json=payload).status_code == 401
        assert client.post(path, headers=owner, json=payload).status_code in {200, 201}
    finally:
        store.close()


def test_generic_artifact_api_cannot_forge_domain_producer_results(monkeypatch) -> None:
    owner = _owner_headers("product-user")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    try:
        task = store.create_task(task_body())
        client = TestClient(main.app)
        for kind in ("strategy_draft", "strategy_version", "strategy_approval", "ml_strategy_version",
                     "ml_strategy_approval", "ml_model", "ml_model_bundle", "ml_regime_snapshot",
                     "ml_feature_snapshot", "ml_prediction_snapshot", "signal_snapshot", "backtest_result",
                     "factor_result", "web_research_evidence", " strategy_approval "):
            payload = {"task_id": task["task_id"], "kind": kind, "content": {"synthetic": True},
                       "lineage": [], "trace_id": "producer-test", "idempotency_key": f"producer-{kind.strip()}"}
            assert client.post("/v1/research/artifacts", headers=owner, json=payload).status_code == 403
            if kind == "web_research_evidence" or kind != kind.strip():
                continue
            # Trusted producer fixture, not a real approval/model/result.
            artifact = store.create_artifact(payload)
            assert client.post(f"/v1/research/artifacts/{artifact['artifact_id']}/transitions", headers=owner,
                               json={"target_status": "validated", "idempotency_key": "generic-validate"}).status_code == 403
            assert store.get_artifact(artifact["artifact_id"])["status"] == "draft"
    finally:
        store.close()


@pytest.mark.parametrize("reference_kind", ["research_task", "experiment", "artifact", "stock_pool_snapshot"])
def test_generic_artifact_lineage_rejects_foreign_objects(monkeypatch, reference_kind) -> None:
    from app.paper_trading import PaperTradingStore
    from tests.test_research import experiment_payload
    headers = _owner_headers()
    _owner_headers("other-user")
    store = ResearchStore()
    pools = PaperTradingStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task(task_body())
    other = store.create_task({**task_body(), "owner_principal": "other-user"})
    experiment = store.create_experiment(experiment_payload(other["task_id"]))
    artifact = store.create_artifact({"task_id": other["task_id"], "kind": "evidence", "content": {},
                                      "lineage": [], "trace_id": "foreign", "idempotency_key": "foreign-artifact"})
    pool = pools.create_pool({"name": "foreign synthetic pool", "symbols": ["000001.SZ"],
                              "provenance": {"source": "unit-test"}}, trusted_owner="other-user")
    references = {"research_task": other["task_id"], "experiment": experiment["experiment_id"],
                  "artifact": artifact["artifact_id"], "stock_pool_snapshot": pool["current_snapshot_id"]}
    response = TestClient(main.app).post("/v1/research/artifacts", headers=headers, json={
        "task_id": task["task_id"], "kind": "evidence", "content": {}, "trace_id": "lineage-test",
        "lineage": [{"kind": reference_kind, "id": references[reference_kind]}],
        "idempotency_key": "foreign-reference"})
    assert response.status_code == 404
    assert store._fetch_one("SELECT COUNT(*) AS count FROM artifacts WHERE task_id=:task",
                            {"task": task["task_id"]})["count"] == 0
    store.close()
    pools.close()


def test_generic_artifact_registers_pool_lineage_atomically(monkeypatch) -> None:
    from app.paper_trading import PaperTradingStore, PaperTradingConflict
    headers = _owner_headers()
    store = ResearchStore()
    pools = PaperTradingStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task(task_body())
    pool = pools.create_pool({"name": "synthetic lineage pool", "symbols": ["000001.SZ"],
                             "provenance": {"source": "unit-test"}}, trusted_owner="product-user")
    second_pool = pools.create_pool({"name": "second synthetic lineage pool", "symbols": ["000002.SZ"],
                                    "provenance": {"source": "unit-test"}}, trusted_owner="product-user")
    payload = {"task_id": task["task_id"], "kind": "evidence", "content": {}, "trace_id": "lineage-test",
               "lineage": [{"kind": "stock_pool_snapshot", "id": pool["current_snapshot_id"]},
                           {"kind": "stock_pool_snapshot", "id": second_pool["current_snapshot_id"]}],
               "idempotency_key": "atomic-reference"}
    client = TestClient(main.app)
    original = PaperTradingStore.record_pool_reference_in_transaction
    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise PaperTradingConflict("synthetic reference failure")
    monkeypatch.setattr(PaperTradingStore, "record_pool_reference_in_transaction", staticmethod(fail_after_insert))
    assert client.post("/v1/research/artifacts", headers=_owner_headers(), json=payload).status_code == 409
    assert store._fetch_one("SELECT COUNT(*) AS count FROM artifacts WHERE task_id=:task", {"task": task["task_id"]})["count"] == 0
    assert store._fetch_one("SELECT COUNT(*) AS count FROM stock_pool_domain_references", {})["count"] == 0
    monkeypatch.setattr(PaperTradingStore, "record_pool_reference_in_transaction", staticmethod(original))
    accepted = client.post("/v1/research/artifacts", headers=_owner_headers(), json=payload)
    assert accepted.status_code == 201
    assert client.post("/v1/research/artifacts", headers=_owner_headers(), json=payload).json() == accepted.json()
    references = store._execute("SELECT * FROM stock_pool_domain_references", {})
    assert len(references) == 2
    assert {ref["snapshot_id"] for ref in references} == {pool["current_snapshot_id"], second_pool["current_snapshot_id"]}
    store.close()
    pools.close()


def test_task_cannot_be_completed_from_a_model_turn_without_evidence(monkeypatch) -> None:
    headers = _owner_headers()
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task(task_body())
    store.transition("research_task", task["task_id"], "running", "start-research")
    response = TestClient(main.app).post(f"/v1/research/tasks/{task['task_id']}/transitions", headers=headers,
        json={"target_status": "completed", "idempotency_key": "model-turn-done"})
    assert response.status_code == 409
    assert store.get_task(task["task_id"])["status"] == "running"
    store.close()


def test_task_checkpoint_survives_restart_and_requires_exact_completion_evidence(monkeypatch) -> None:
    headers = _owner_headers()
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task(task_body())
    artifact = store.create_artifact({"task_id": task["task_id"], "kind": "research_report", "content": {"synthetic": True},
                                      "lineage": [], "trace_id": "checkpoint", "idempotency_key": "checkpoint-report"})
    progress = {"schema_version": "research-progress.v1", "stage": "research", "next_action": "review_report",
                "blocked_reason": None, "linked_objects": [{"kind": "artifact", "id": artifact["artifact_id"]}],
                "completion_evidence": []}
    payload = {"target_status": "running", "idempotency_key": "checkpoint-running", "progress": progress}
    path = f"/v1/research/tasks/{task['task_id']}/transitions"
    client = TestClient(main.app)
    accepted = client.post(path, headers=headers, json=payload)
    assert accepted.status_code == 200
    assert accepted.json()["progress"] == progress
    store.close()
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    assert store.get_task(task["task_id"])["progress"] == progress
    assert client.post(path, headers=headers, json=payload).json() == accepted.json()
    complete = {**payload, "target_status": "completed", "idempotency_key": "checkpoint-complete",
                "progress": {**progress, "stage": "completed", "next_action": None,
                             "completion_evidence": [artifact["artifact_id"]]}}
    assert client.post(path, headers=headers, json=complete).status_code == 409
    store.transition("artifact", artifact["artifact_id"], "validated", "review-report")
    from tests.test_research import experiment_payload
    unfinished = store.create_experiment(experiment_payload(task["task_id"]))
    assert client.post(path, headers=headers, json=complete).status_code == 409
    store.transition("experiment", unfinished["experiment_id"], "cancelled", "stop-unused-experiment")
    assert client.post(path, headers=headers, json=complete).status_code == 200
    changed = {**complete, "idempotency_key": "rewrite-terminal", "progress": {**progress, "stage": "research"}}
    assert client.post(path, headers=headers, json=changed).status_code == 409
    store.close()


def test_task_checkpoint_rejects_wrong_task_and_malformed_stage(monkeypatch) -> None:
    headers = _owner_headers()
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task(task_body())
    other = store.create_task({**task_body(), "idempotency_key": "other-same-owner-task"})
    artifact = store.create_artifact({"task_id": other["task_id"], "kind": "evidence", "content": {},
        "lineage": [], "trace_id": "checkpoint", "idempotency_key": "other-task-artifact"})
    progress = {"schema_version": "research-progress.v1", "stage": "research", "next_action": "review_report",
        "blocked_reason": None, "linked_objects": [{"kind": "artifact", "id": artifact["artifact_id"]}],
        "completion_evidence": []}
    client = TestClient(main.app)
    path = f"/v1/research/tasks/{task['task_id']}/transitions"
    payload = {"target_status": "running", "idempotency_key": "wrong-task-checkpoint", "progress": progress}
    assert client.post(path, headers=headers, json=payload).status_code == 404
    assert client.post(path, headers=headers, json={**payload, "progress": {**progress, "stage": []}}).status_code == 422
    assert store.get_task(task["task_id"])["status"] == "planned"
    assert store.get_task(task["task_id"])["progress"] is None
    store.close()
