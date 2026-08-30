"""Derived backtest-task.v1 projection over existing BYQ domain jobs (ADR-0044)."""

from __future__ import annotations

import re
from typing import Any


SCHEMA_VERSION = "backtest-task.v1"
_SIGNAL_ID = re.compile(r"^signaljob_([0-9a-f]{32})$")
_TASK_ID = re.compile(r"^backtesttask_([0-9a-f]{32})$")
_ML_PREDICTION_ID = re.compile(r"^mlpred_([0-9a-f]{32})$")
_ML_TASK_ID = re.compile(r"^backtesttask_ml_([0-9a-f]{32})$")


def task_id_from_signal_job(signal_job_id: object) -> str:
    if not isinstance(signal_job_id, str):
        raise ValueError("signal job id is invalid")
    match = _SIGNAL_ID.fullmatch(signal_job_id)
    if match is None:
        raise ValueError("signal job id is invalid")
    return f"backtesttask_{match.group(1)}"


def signal_job_id_from_task(task_id: object) -> str:
    if not isinstance(task_id, str):
        raise ValueError("backtest task id is invalid")
    match = _TASK_ID.fullmatch(task_id)
    if match is None:
        raise ValueError("backtest task id is invalid")
    return f"signaljob_{match.group(1)}"


def task_id_from_ml_prediction(prediction_run_id: object) -> str:
    if not isinstance(prediction_run_id, str):
        raise ValueError("ML prediction run id is invalid")
    match = _ML_PREDICTION_ID.fullmatch(prediction_run_id)
    if match is None:
        raise ValueError("ML prediction run id is invalid")
    return f"backtesttask_ml_{match.group(1)}"


def ml_prediction_id_from_task(task_id: object) -> str:
    if not isinstance(task_id, str):
        raise ValueError("backtest task id is invalid")
    match = _ML_TASK_ID.fullmatch(task_id)
    if match is None:
        raise ValueError("backtest task is not ML-derived")
    return f"mlpred_{match.group(1)}"


def is_ml_backtest_task(task_id: object) -> bool:
    return isinstance(task_id, str) and _ML_TASK_ID.fullmatch(task_id) is not None


def _readiness_state(readiness: object) -> str:
    return str(readiness.get("state", "unknown")) if isinstance(readiness, dict) else "unknown"


def project_backtest_task(
    *,
    research_task_id: str,
    strategy_version_artifact_id: str,
    approval_artifact_id: str | None,
    stock_pool_snapshot_id: str,
    readiness: dict[str, object] | None,
    signal_job: dict[str, Any] | None = None,
    backtest_job: dict[str, Any] | None = None,
    backtest_task_id: str | None = None,
    signal_cancellable: bool = True,
) -> dict[str, object]:
    """Return a closed projection; status is never persisted independently."""
    signal_status = str(signal_job.get("status")) if signal_job else None
    backtest_status = str(backtest_job.get("status")) if backtest_job else None
    ready_state = _readiness_state(readiness)
    blockers: list[dict[str, str]] = []

    if approval_artifact_id is None:
        blockers.append({"code": "approval_required", "message": "策略版本尚未获得执行批准"})
    if ready_state != "ready" and signal_job is None:
        blockers.append({"code": "market_data_not_ready", "message": "行情输入尚未完整，创建任务后将进入补数等待"})

    if backtest_job is not None:
        phase = {
            "queued": "queued",
            "running": "running",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(backtest_status, "failed")
    elif signal_job is None:
        phase = "prepared"
    elif signal_status == "completed":
        phase = "ready_to_execute"
    elif signal_status == "waiting_for_data":
        phase = "waiting_for_data"
        blockers.append({"code": "market_data_not_ready", "message": "正在等待完整行情输入"})
    elif signal_status in {"queued", "running"}:
        phase = "producing_signals"
    elif signal_status == "cancelled":
        phase = "cancelled"
    else:
        phase = "failed"
        blockers.append({
            "code": str(signal_job.get("error_code") or "signal_production_failed"),
            "message": str(signal_job.get("error_detail") or "信号生成失败"),
        })

    task_id = backtest_task_id or (task_id_from_signal_job(signal_job["job_id"]) if signal_job else None)
    can_create = signal_job is None and approval_artifact_id is not None
    can_execute = phase in {"ready_to_execute", "queued"}
    can_cancel = signal_cancellable and (
        phase in {"waiting_for_data", "queued", "running"}
        or (phase == "producing_signals" and signal_status == "queued")
    )
    if backtest_job is not None and phase in {"queued", "running"}:
        can_cancel = True
    next_action = {
        "prepared": "create" if can_create else "resolve_blockers",
        "waiting_for_data": "wait",
        "producing_signals": "wait",
        "ready_to_execute": "execute",
        "queued": "execute",
        "running": "wait",
        "completed": "review_result",
        "failed": "review_failure",
        "cancelled": "create_new_task",
    }[phase]

    return {
        "schema_version": SCHEMA_VERSION,
        "backtest_task_id": task_id,
        "phase": phase,
        "next_action": next_action,
        "actions": {"can_create": can_create, "can_execute": can_execute, "can_cancel": can_cancel},
        "references": {
            "research_task_id": research_task_id,
            "strategy_version_artifact_id": strategy_version_artifact_id,
            "approval_artifact_id": approval_artifact_id,
            "stock_pool_snapshot_id": stock_pool_snapshot_id,
            "signal_producer_job_id": signal_job.get("job_id") if signal_job else None,
            "signal_snapshot_artifact_id": signal_job.get("result_artifact_id") if signal_job else None,
            "backtest_job_id": backtest_job.get("job_id") if backtest_job else None,
            "result_artifact_id": backtest_job.get("result_artifact_id") if backtest_job else None,
        },
        "market_readiness": readiness,
        "signal": None if signal_job is None else {
            "status": signal_status,
            "attempts": signal_job.get("attempt_count"),
            "error_code": signal_job.get("error_code"),
            "error_message": signal_job.get("error_detail"),
        },
        "backtest": None if backtest_job is None else {
            "status": backtest_status,
            "attempts": backtest_job.get("attempts"),
            "max_attempts": backtest_job.get("max_attempts"),
            "summary": backtest_job.get("summary"),
            "error_code": backtest_job.get("error_code"),
            "error_message": backtest_job.get("error_message"),
        },
        "blockers": blockers,
    }
