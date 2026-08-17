from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore




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


def test_research_api_exposes_normalized_persistent_entity_flow(monkeypatch) -> None:
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)

    created = client.post("/v1/research/tasks", json=task_body())
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "planned"
    task_id = task["task_id"]

    fetched = client.get(f"/v1/research/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json() == task

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
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)

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