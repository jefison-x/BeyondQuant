"""ADR-0085 P0: Backend-derived executable identity for a domain event.

A data-ready continuation must hand the model (or the deterministic reducer) an
already-resolved next action instead of a natural-language "re-read the task and
continue" prompt. The model must never re-derive a ``backtest_task_id``, rebuild
create parameters or invent an idempotency key.

This contract wraps the existing ``backtest-task.v1`` projection produced by
``services/backend/app/backtest_task.py`` (single source of truth) into a closed,
enumerable action descriptor:

* exact ``backtest_task_id``;
* ``phase`` and an ENUM ``next_action``;
* the exact resource ``references``;
* whether a further approval is required, and for which action/resource;
* the expected postcondition of executing the action.

It adds no new state and does not replace ``project_backtest_task``; it is a
framework-neutral translation layer usable by both the Backend reducer and any
future plan-driven consumer.
"""

from __future__ import annotations

SCHEMA_VERSION = "research-executable-action.v1"

# Closed action enum. A new value requires a contract update, never free text.
NEXT_ACTIONS = frozenset({
    "create",
    "wait",
    "execute",
    "review_result",
    "review_failure",
    "create_new_task",
    "resolve_blockers",
})

_ACTION_POSTCONDITIONS = {
    "create": "backtest_task_created",
    "wait": "signal_job_completed_with_validated_snapshot",
    "execute": "backtest_job_queued",
    "review_result": "backtest_result_reviewed",
    "review_failure": "backtest_failure_reviewed",
    "create_new_task": "new_backtest_task_created",
    "resolve_blockers": "blockers_resolved",
}

_ACTION_APPROVAL = {
    "create": ("backtest_task_create", "strategy_version_artifact_id"),
    "execute": ("backtest_execute", "backtest_task_id"),
}


def derive_executable_action(projection: dict[str, object]) -> dict[str, object]:
    """Translate a ``backtest-task.v1`` projection into a closed action.

    ``projection`` MUST be the output of ``project_backtest_task`` so the
    ``backtest_task_id``/``phase``/``next_action``/``references`` are the
    Backend's authoritative values, never model- or caller-supplied.
    """

    if not isinstance(projection, dict):
        raise ValueError("executable action requires a backtest-task projection")
    if projection.get("schema_version") != "backtest-task.v1":
        raise ValueError("executable action requires a backtest-task.v1 projection")
    next_action = projection.get("next_action")
    if next_action not in NEXT_ACTIONS:
        raise ValueError("backtest-task projection has an unknown next_action")
    references = projection.get("references")
    if not isinstance(references, dict):
        raise ValueError("backtest-task projection references are invalid")
    blockers = projection.get("blockers")
    blockers = blockers if isinstance(blockers, list) else []
    approval_blocked = any(
        isinstance(blocker, dict) and blocker.get("code") == "approval_required"
        for blocker in blockers
    )
    approval = None
    if next_action in _ACTION_APPROVAL:
        action, resource_field = _ACTION_APPROVAL[next_action]
        resource = (projection.get("backtest_task_id") if resource_field == "backtest_task_id"
                    else references.get(resource_field))
        if approval_blocked and isinstance(resource, str):
            approval = {"required": True, "action": action, "resource": resource}
    return {
        "schema_version": SCHEMA_VERSION,
        "backtest_task_id": projection.get("backtest_task_id"),
        "phase": projection.get("phase"),
        "next_action": next_action,
        "references": {
            key: references.get(key) for key in (
                "research_task_id", "strategy_version_artifact_id", "approval_artifact_id",
                "stock_pool_snapshot_id", "signal_producer_job_id",
                "signal_snapshot_artifact_id", "backtest_job_id", "result_artifact_id",
            )
        },
        "approval_required": approval_blocked,
        "approval": approval,
        "expected_postcondition": _ACTION_POSTCONDITIONS[next_action],
    }


def executable_action_from_projection(projection: dict[str, object]) -> dict[str, object]:
    """Alias kept explicit for call sites that read like the contract name."""
    return derive_executable_action(projection)
