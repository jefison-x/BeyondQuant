from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore
from test_strategy_artifact import strategy_payload


def _task(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user",
            "title": "Strategy artifact task",
            "objective": "Validate and version a strategy artifact.",
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-api-task-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_strategy_draft_version_export_and_approval_flow(monkeypatch, tmp_path) -> None:
    store = ResearchStore(tmp_path / "strategy.sqlite3")
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    task = _task(client)

    draft_response = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"],
            "strategy": strategy_payload(),
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-draft-1",
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    assert draft["validation"]["success"] is True
    assert draft["artifact"]["kind"] == "strategy_draft"
    assert draft["artifact"]["status"] == "validated"

    version_request = {
        "task_id": task["task_id"],
        "draft_artifact_id": draft["artifact"]["artifact_id"],
        "trace_id": "byq-trace-strategy-api",
        "idempotency_key": "strategy-version-1",
    }
    version_response = client.post("/v1/research/strategies/versions", json=version_request)
    assert version_response.status_code == 201, version_response.text
    version = version_response.json()
    assert version["artifact"]["kind"] == "strategy_version"
    assert version["artifact"]["status"] == "validated"
    version_id = version["strategy_version"]["version_id"]

    retry = client.post(
        "/v1/research/strategies/versions",
        json={**version_request, "idempotency_key": "strategy-version-retry"},
    )
    assert retry.status_code == 201
    assert retry.json()["artifact"]["artifact_id"] == version["artifact"]["artifact_id"]

    exported = client.get(f"/v1/research/strategies/versions/{version['artifact']['artifact_id']}/export")
    assert exported.status_code == 200
    assert exported.json()["export"]["version_id"] == version_id
    assert "trace_id" not in exported.text

    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"],
            "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner",
            "decision": "approved",
            "rationale": "Static contract reviewed.",
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-approval-1",
        },
    )
    assert approval.status_code == 201, approval.text
    body = approval.json()
    assert body["approval"]["execution_authorized"] is True
    assert body["approval"]["execution_outcome"] == "not_started"
    assert body["artifact"]["kind"] == "strategy_approval"
    assert body["artifact"]["status"] == "validated"
    store.close()


def test_strategy_api_rejects_invalid_source_without_creating_artifact(monkeypatch, tmp_path) -> None:
    store = ResearchStore(tmp_path / "strategy.sqlite3")
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    task = _task(client)
    response = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"],
            "strategy": {**strategy_payload(), "script": "import os"},
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-draft-invalid",
        },
    )
    assert response.status_code == 422
    assert store._connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
    store.close()
