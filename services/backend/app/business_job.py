"""Small public projection of BYQ-owned long-compute jobs.

Specialized stores remain the authority. This module translates their existing
identities and states; it does not schedule work or persist another job record.
"""

from __future__ import annotations

from collections.abc import Mapping


_IDS = {"BACKTEST": "job_id", "TRAINING": "training_run_id"}
_STATUS = {
    "queued": "QUEUED",
    "waiting_for_data": "QUEUED",
    "running": "RUNNING",
    "completed": "SUCCEEDED",
    "succeeded": "SUCCEEDED",
    "failed": "FAILED",
    "cancelled": "CANCELLED",
}


def project_business_job(kind: str, row: Mapping[str, object]) -> dict[str, object]:
    """Expose one stable ID and closed state without leaking worker internals."""
    if kind not in _IDS:
        raise ValueError("unsupported business job type")
    identity = row.get(_IDS[kind])
    workspace = row.get("workspace_id")
    raw_status = row.get("status")
    if not isinstance(identity, str) or not identity or not isinstance(workspace, str) or not workspace:
        raise ValueError("business job identity or workspace is missing")
    if not isinstance(raw_status, str) or raw_status not in _STATUS:
        raise ValueError("business job status is unknown")
    status = _STATUS[raw_status]
    input_ref = row.get("input_manifest_id" if kind == "BACKTEST" else "input_sha256")
    result_ref = row.get("result_artifact_id" if kind == "BACKTEST" else "model_artifact_id")
    if input_ref is not None and not isinstance(input_ref, str):
        raise ValueError("business job input reference is invalid")
    if result_ref is not None and not isinstance(result_ref, str):
        raise ValueError("business job result reference is invalid")
    return {
        "job_id": identity,
        "workspace_id": workspace,
        "type": kind,
        "status": status,
        "progress": 100 if status == "SUCCEEDED" else None,
        "input_ref": input_ref,
        "result_ref": result_ref,
        "error": None if row.get("error_code") is None else {
            "code": row["error_code"],
            "message": row.get("error_message" if kind == "BACKTEST" else "error_detail"),
        },
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }
