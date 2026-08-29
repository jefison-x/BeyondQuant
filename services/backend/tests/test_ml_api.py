from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.test_ml_strategy import valid_strategy
from tests.workspace_helpers import trusted_agent_context


client = TestClient(app)


def test_ml_strategy_version_and_human_approval_are_owner_scoped() -> None:
    headers = trusted_agent_context("ml-api-owner", actor="ml-api-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-api-owner", "title": "ML API", "objective": "Train",
        "trace_id": "trace-ml-api", "idempotency_key": "task-ml-api",
    })
    assert task.status_code == 201, task.text
    task_id = task.json()["task_id"]
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task_id, "strategy": valid_strategy(), "trace_id": "trace-ml-api",
        "idempotency_key": "version-ml-api",
    })
    assert version.status_code == 201, version.text
    artifact = version.json()["artifact"]
    assert artifact["kind"] == "ml_strategy_version" and artifact["status"] == "validated"
    approval = client.post("/v1/research/ml/strategies/approvals", headers=headers, json={
        "task_id": task_id, "ml_strategy_artifact_id": artifact["artifact_id"],
        "decision": "approved", "rationale": "reviewed", "trace_id": "trace-ml-api",
        "idempotency_key": "approval-ml-api",
    })
    assert approval.status_code == 201, approval.text
    assert approval.json()["approval"]["execution_authorized"] is True
    assert approval.json()["approval"]["reviewer_principal"] == "ml-api-owner"


def test_ml_strategy_endpoint_rejects_open_python_contract() -> None:
    headers = trusted_agent_context("ml-api-reject")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-api-reject", "title": "ML reject", "objective": "Reject",
        "trace_id": "trace-ml-reject", "idempotency_key": "task-ml-reject",
    }).json()
    strategy = valid_strategy()
    strategy["python"] = "import lightgbm"
    response = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": strategy, "trace_id": "trace-ml-reject",
        "idempotency_key": "version-ml-reject",
    })
    assert response.status_code == 422
    assert "unknown fields" in response.text


def test_ml_training_read_is_workspace_scoped_and_returns_safe_not_found() -> None:
    response = client.get(
        "/v1/research/ml/training-runs/mlrun_missing",
        headers=trusted_agent_context("ml-api-reader"),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "ML training run not found"}
