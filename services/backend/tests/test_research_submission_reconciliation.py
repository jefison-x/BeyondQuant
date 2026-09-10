"""Exact durable receipts; no list inference or replayed writes."""
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context
from tests.test_research import snapshot

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")
PATH = "/v1/research/submissions/reconcile"


@pytest.mark.parametrize("kind", ["research_task", "experiment", "artifact"])
def test_exact_receipt_unknown_then_commit_and_restart(monkeypatch, kind):
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    context = trusted_agent_context("receipt-owner")
    client = TestClient(main.app)
    client.headers.update(context)
    key = "original-receipt-key"
    task_payload = {"owner_principal": "receipt-owner", "title": "Receipt test",
                    "objective": "Recover the original result", "trace_id": "trace-test", "idempotency_key": key}
    params = {"entity_type": kind, "idempotency_key": key}
    if kind != "research_task":
        task = client.post("/v1/research/tasks", json={**task_payload, "idempotency_key": "parent"}).json()
        params["task_id"] = task["task_id"]
    unknown = client.get(PATH, params=params)
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["status"] == "outcome_unknown"
    assert "entity" not in unknown.json()
    if kind == "research_task":
        response = client.post("/v1/research/tasks", json=task_payload)
        id_field = "task_id"
    elif kind == "experiment":
        response = client.post("/v1/research/experiments", json={"task_id": task["task_id"], "name": "Original experiment",
            "input_snapshot": snapshot(), "trace_id": "trace-test", "idempotency_key": key})
        id_field = "experiment_id"
    else:
        response = client.post("/v1/research/artifacts", json={"task_id": task["task_id"], "kind": "evidence",
            "content": {"summary": "original evidence"}, "lineage": [], "trace_id": "trace-test", "idempotency_key": key})
        id_field = "artifact_id"
    assert response.status_code == 201, response.text
    committed = response.json()
    if kind != "research_task":
        other_task = client.post("/v1/research/tasks", json={**task_payload, "idempotency_key": "other-parent"}).json()
        scoped = client.get(PATH, params={**params, "task_id": other_task["task_id"]})
        assert scoped.status_code == 200 and scoped.json()["status"] == "outcome_unknown"
    other_key = client.get(PATH, params={**params, "idempotency_key": "different-key"})
    assert other_key.status_code == 200 and other_key.json()["status"] == "outcome_unknown"
    store.close()
    replacement = ResearchStore()
    monkeypatch.setattr(main, "research_store", replacement)
    # Any fallback to create/list is a regression, even if it returns the same ID.
    def forbidden(*args, **kwargs):
        pytest.fail("reconciliation must not create or search a list")
    for name in ("create_task", "create_experiment", "create_artifact", "list_tasks", "list_experiments", "list_artifacts"):
        monkeypatch.setattr(replacement, name, forbidden)
    for _ in range(2):
        confirmed = client.get(PATH, params=params)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "confirmed"
        assert confirmed.json()["entity"][id_field] == committed[id_field]
        assert confirmed.json()["entity"] == committed
        assert "request_hash" not in confirmed.text
    foreign = trusted_agent_context("receipt-other")
    rejected = client.get(PATH, params=params, headers=foreign)
    if kind == "research_task":
        assert rejected.status_code == 200 and rejected.json()["status"] == "outcome_unknown"
    else:
        assert rejected.status_code == 404
    assert committed[id_field] not in rejected.text
    with TestClient(main.app) as anonymous:
        assert anonymous.get(PATH, params=params).status_code == 401
    mismatched = client.get(PATH, params=params, headers={**context, "x-byq-workspace-id": foreign["x-byq-workspace-id"]})
    assert mismatched.status_code == 401
    user = next(user for user in main.user_store.list_users(actor_role="admin")["users"]
                if user["username"] == "receipt-owner")
    main.user_store.disable_user(user["user_id"], actor_role="admin")
    disabled = client.get(PATH, params=params)
    assert disabled.status_code == 401
    assert committed[id_field] not in disabled.text
    replacement.close()


@pytest.mark.parametrize("params", [
    {"entity_type": "unknown", "idempotency_key": "key"},
    {"entity_type": "research_task", "idempotency_key": " "},
    {"entity_type": "research_task", "idempotency_key": "x" * 129},
    {"entity_type": "research_task", "idempotency_key": "key", "task_id": "wrong"},
    {"entity_type": "experiment", "idempotency_key": "key"},
    {"entity_type": "artifact", "idempotency_key": "key"},
])
def test_invalid_receipt_selector(monkeypatch, params):
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    with TestClient(main.app) as client:
        response = client.get(PATH, params=params, headers=trusted_agent_context("receipt-owner"))
        assert response.status_code == 422, response.text
    store.close()
