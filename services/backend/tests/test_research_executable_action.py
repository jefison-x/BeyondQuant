"""ADR-0085 P0: Backend-derived executable identity for a domain event."""

from __future__ import annotations

import pytest

from packages.contracts.research_executable_action import (
    NEXT_ACTIONS,
    SCHEMA_VERSION,
    derive_executable_action,
)


def _projection(**overrides: object) -> dict:
    projection = {
        "schema_version": "backtest-task.v1",
        "backtest_task_id": "backtesttask_" + "a" * 32,
        "phase": "ready_to_execute",
        "next_action": "execute",
        "actions": {"can_create": False, "can_execute": True, "can_cancel": True},
        "references": {
            "research_task_id": "task_" + "b" * 32,
            "strategy_version_artifact_id": "artifact_" + "c" * 32,
            "approval_artifact_id": "artifact_" + "d" * 32,
            "stock_pool_snapshot_id": "stock_pool_snapshot_" + "e" * 64,
            "signal_producer_job_id": "signaljob_" + "f" * 32,
            "signal_snapshot_artifact_id": "artifact_" + "0" * 32,
            "backtest_job_id": None,
            "result_artifact_id": None,
        },
        "blockers": [],
    }
    projection.update(overrides)
    return projection


def test_executable_action_uses_the_authoritative_task_identity() -> None:
    executable = derive_executable_action(_projection())
    assert executable["schema_version"] == SCHEMA_VERSION
    assert executable["backtest_task_id"] == "backtesttask_" + "a" * 32
    assert executable["phase"] == "ready_to_execute"
    assert executable["next_action"] == "execute"
    assert executable["next_action"] in NEXT_ACTIONS
    assert executable["references"]["signal_producer_job_id"] == "signaljob_" + "f" * 32
    assert executable["expected_postcondition"] == "backtest_job_queued"


def test_executable_action_requires_the_backend_projection_schema() -> None:
    with pytest.raises(ValueError):
        derive_executable_action({"schema_version": "made-up.v1", "next_action": "execute"})
    with pytest.raises(ValueError):
        derive_executable_action(_projection(next_action="invent_a_new_action"))


def test_executable_action_reports_an_approval_requirement_only_with_a_blocker() -> None:
    blocked = derive_executable_action(_projection(
        next_action="create",
        phase="prepared",
        blockers=[{"code": "approval_required", "message": "审批"}],
    ))
    assert blocked["approval_required"] is True
    assert blocked["approval"] == {
        "required": True,
        "action": "backtest_task_create",
        "resource": blocked["references"]["strategy_version_artifact_id"],
    }
    # Without the authoritative approval blocker no approval is implied.
    open_task = derive_executable_action(_projection(next_action="create", phase="prepared"))
    assert open_task["approval_required"] is False
    assert open_task["approval"] is None
