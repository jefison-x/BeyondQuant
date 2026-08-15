from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore
from test_factor_research import factor_payload


def test_factor_endpoint_persists_factor_result_artifact(monkeypatch, tmp_path) -> None:
    store = ResearchStore(tmp_path / "factor.sqlite3")
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user",
            "title": "Factor task",
            "objective": "Compute a deterministic factor.",
            "trace_id": "byq-trace-factor-api",
            "idempotency_key": "factor-api-task-1",
        },
    ).json()

    request = {**factor_payload(), "task_id": task["task_id"], "idempotency_key": "factor-api-compute-1"}
    response = client.post("/v1/research/factors/compute", json=request)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["factor"]["reproducibility"] == "reproducible"
    assert body["artifact"]["kind"] == "factor_result"
    assert body["artifact"]["lineage"][-1]["kind"] == "factor_input"

    retry = client.post("/v1/research/factors/compute", json=request)
    assert retry.status_code == 201
    assert retry.json()["artifact"]["artifact_id"] == body["artifact"]["artifact_id"]
    store.close()
