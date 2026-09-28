from __future__ import annotations

import pytest

from app.business_job import project_business_job


def test_backtest_projection_keeps_stable_job_and_artifact_identity() -> None:
    result = project_business_job("BACKTEST", {
        "job_id": "backtest_1", "workspace_id": "workspace_1", "status": "completed",
        "input_manifest_id": "manifest_1", "result_artifact_id": "artifact_1",
        "created_at": "created", "started_at": "started", "finished_at": "finished",
        "request_json": {"secret": "never project"}, "worker_id": "internal",
    })
    assert result == {
        "job_id": "backtest_1", "workspace_id": "workspace_1", "type": "BACKTEST",
        "status": "SUCCEEDED", "progress": 100, "input_ref": "manifest_1",
        "result_ref": "artifact_1", "error": None,
        "created_at": "created", "started_at": "started", "finished_at": "finished",
    }


def test_training_waiting_for_data_is_queued_without_fabricated_progress() -> None:
    result = project_business_job("TRAINING", {
        "training_run_id": "mlrun_1", "workspace_id": "workspace_1",
        "status": "waiting_for_data", "input_sha256": None,
        "model_artifact_id": None, "worker_id": "internal",
    })
    assert result["job_id"] == "mlrun_1"
    assert result["status"] == "QUEUED"
    assert result["progress"] is None
    assert result["result_ref"] is None
    assert "worker_id" not in result


@pytest.mark.parametrize("kind,row", [
    ("BACKTEST", {"job_id": "backtest_1", "workspace_id": "w", "status": "unrecognized"}),
    ("TRAINING", {"training_run_id": "mlrun_1", "status": "queued"}),
    ("OPTIMIZATION", {"job_id": "optim_1", "workspace_id": "w", "status": "queued"}),
])
def test_projection_rejects_unsupported_or_unowned_state(kind: str, row: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        project_business_job(kind, row)
