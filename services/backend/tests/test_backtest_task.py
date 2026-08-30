from app.backtest_task import (
    project_backtest_task,
    signal_job_id_from_task,
    task_id_from_signal_job,
)


def base(**overrides):
    values = {
        "research_task_id": "task_abc",
        "strategy_version_artifact_id": "artifact_version",
        "approval_artifact_id": "artifact_approval",
        "stock_pool_snapshot_id": "snapshot_abc",
        "readiness": {"state": "ready"},
    }
    values.update(overrides)
    return values


def test_task_identity_is_reversible_and_bounded_to_signal_job():
    signal = "signaljob_0123456789abcdef0123456789abcdef"
    task = task_id_from_signal_job(signal)
    assert task == "backtesttask_0123456789abcdef0123456789abcdef"
    assert signal_job_id_from_task(task) == signal


def test_prepare_is_read_only_and_reports_missing_approval():
    task = project_backtest_task(**base(approval_artifact_id=None))
    assert task["phase"] == "prepared"
    assert task["backtest_task_id"] is None
    assert task["actions"] == {"can_create": False, "can_execute": False, "can_cancel": False}
    assert task["blockers"][0]["code"] == "approval_required"


def test_signal_and_backtest_states_are_derived_not_duplicated():
    signal = {
        "job_id": "signaljob_0123456789abcdef0123456789abcdef",
        "status": "completed",
        "result_artifact_id": "artifact_snapshot",
        "attempt_count": 1,
    }
    ready = project_backtest_task(**base(signal_job=signal))
    assert ready["phase"] == "ready_to_execute"
    assert ready["actions"]["can_execute"] is True

    completed = project_backtest_task(**base(
        signal_job=signal,
        backtest_job={
            "job_id": "backtest_0123456789abcdef0123456789abcdef",
            "status": "completed",
            "attempts": 1,
            "max_attempts": 2,
            "result_artifact_id": "artifact_result",
            "summary": {"total_return": "0.12"},
        },
    ))
    assert completed["phase"] == "completed"
    assert completed["references"]["result_artifact_id"] == "artifact_result"
    assert completed["next_action"] == "review_result"


def test_running_signal_job_never_claims_unsafe_cancellation():
    task = project_backtest_task(**base(signal_job={
        "job_id": "signaljob_0123456789abcdef0123456789abcdef",
        "status": "running",
        "attempt_count": 1,
    }))
    assert task["phase"] == "producing_signals"
    assert task["actions"]["can_cancel"] is False
