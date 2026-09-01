from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as backend_main
from app.main import _ml_pool_market_scope, app
from tests.test_ml_strategy import valid_strategy
from tests.workspace_helpers import trusted_agent_context


client = TestClient(app)


def test_index_ml_pool_freezes_same_index_as_universe_and_benchmark() -> None:
    declared, membership_mode = _ml_pool_market_scope(
        {"pool_type": "index"},
        {"provenance": {"index_symbol": "000300.SH"}},
    )
    assert membership_mode == "point_in_time"
    assert declared == {"index_universe": "000300.SH", "benchmark": "000300.SH"}

    fixed, fixed_mode = _ml_pool_market_scope({"pool_type": "custom"}, {})
    assert fixed == {} and fixed_mode == "fixed_snapshot"


def test_ml_capabilities_and_workspace_are_closed_safe_projections() -> None:
    headers = trusted_agent_context("ml-capability-owner")
    capabilities = client.get("/v1/research/ml/capabilities", headers=headers)
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["schema_version"] == "ml-capabilities.v1"
    assert body["capabilities"][0]["learner"]["kind"] == "lightgbm_regression"
    assert "xgboost" not in capabilities.text.lower()
    workspace = client.get("/v1/research/ml/workspace", headers=headers)
    assert workspace.status_code == 200
    assert workspace.json()["schema_version"] == "ml-agent-workspace.v1"
    assert workspace.json()["prediction_available_via_agent"] is True
    assert workspace.json()["prediction_runs"] == []
    assert "object_reference" not in workspace.text and "rows" not in workspace.text


def test_ml_workspace_and_prediction_pages_never_materialise_large_rows() -> None:
    headers = trusted_agent_context("ml-bounded-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-bounded-owner", "title": "Bounded ML", "objective": "Page rows",
        "trace_id": "trace-ml-bounded", "idempotency_key": "task-ml-bounded",
    }).json()
    artifact = backend_main.research_store.create_artifact({
        "task_id": task["task_id"], "kind": "ml_prediction_snapshot",
        "content": {"schema_version": "ml-prediction-snapshot.v1", "rows": [
            {"session": "2026-01-02", "rank": 1, "symbol": "000001.SZ", "score": 0.9, "private": "drop"},
            {"session": "2026-01-02", "rank": 2, "symbol": "000002.SZ", "score": 0.8},
            {"session": "2026-01-03", "rank": 1, "symbol": "000001.SZ", "score": 0.7},
        ]},
        "lineage": [], "trace_id": "trace-ml-bounded", "idempotency_key": "artifact-ml-bounded",
    })
    projected = backend_main.research_store.list_ml_workspace_artifacts(
        owner_principal="ml-bounded-owner", workspace_id=headers["x-byq-workspace-id"],
    )
    assert projected[0]["artifact_id"] == artifact["artifact_id"]
    assert "rows" not in projected[0]["content"]
    page = backend_main.research_store.list_ml_prediction_rows(
        artifact_id=str(artifact["artifact_id"]), owner_principal="ml-bounded-owner",
        workspace_id=headers["x-byq-workspace-id"], query="000001", limit=1, offset=1,
    )
    assert page == {
        "rows": [{"session": "2026-01-03", "rank": 1, "symbol": "000001.SZ", "score": 0.7}],
        "total": 2,
    }


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


def test_ml_training_requires_separate_human_strategy_approval() -> None:
    headers = trusted_agent_context("ml-training-approval-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-training-approval-owner", "title": "ML approval",
        "objective": "Require approval", "trace_id": "trace-ml-training-approval",
        "idempotency_key": "task-ml-training-approval",
    }).json()
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": valid_strategy(),
        "trace_id": "trace-ml-training-approval", "idempotency_key": "version-ml-training-approval",
    }).json()
    response = client.post("/v1/research/ml/training-runs", headers=headers, json={
        "task_id": task["task_id"],
        "ml_strategy_artifact_id": version["artifact"]["artifact_id"],
        "stock_pool_snapshot_id": "snapshot_not_reached",
        "trace_id": "trace-ml-training-approval",
        "idempotency_key": "training-ml-training-approval",
    })
    assert response.status_code == 422
    assert "explicit human approval" in response.text


def test_ml_training_read_is_workspace_scoped_and_returns_safe_not_found() -> None:
    response = client.get(
        "/v1/research/ml/training-runs/mlrun_missing",
        headers=trusted_agent_context("ml-api-reader"),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "ML training run not found"}
