"""BYQ-owned exact plan-approval and business-action contract.

Approval decisions bind one immutable plan command. This contract contains no
event envelope, replay ledger, Agent session, or Worker claim semantics.
"""

from __future__ import annotations

import hashlib
import json

from .research_execution_plan import STAGE_POSTCONDITION, validate_plan


PLAN_APPROVAL_ACTION = {
    "strategy_approve": "byq_strategy_approve",
    "backtest_task_create": "byq_backtest_task_create",
    "backtest_execute": "byq_backtest_task_execute",
    "create_paper_account": "byq_paper_account_create",
}
AGENT_APPROVAL_PLAN_ACTION = {
    agent_action: plan_action for plan_action, agent_action in PLAN_APPROVAL_ACTION.items()
}

PAPER_ACCOUNT_CREATE_ACTION = "create_paper_account"
PAPER_ACCOUNT_DEFAULT_CASH = "100000.0000"

_APPROVAL_TARGET = {
    "waiting_for_strategy_approval": (
        "strategy_approve", "strategy_version",
        "waiting_for_task_create_approval", "waiting",
        "backtest_task_create", "strategy_version",
    ),
    "waiting_for_task_create_approval": (
        "backtest_task_create", "strategy_version",
        "ready_to_create_backtest_task", "active",
        "backtest_task_create", "strategy_version",
    ),
    "waiting_for_task_execute_approval": (
        "backtest_execute", "backtest_task",
        "ready_to_execute_backtest_task", "active",
        "backtest_execute", "backtest_task",
    ),
    "waiting_for_paper_account_approval": (
        PAPER_ACCOUNT_CREATE_ACTION, "research_task",
        "ready_to_create_paper_account", "active",
        PAPER_ACCOUNT_CREATE_ACTION, "research_task",
    ),
}

_APPROVAL_BINDING_FIELDS = (
    "plan_task_id", "plan_workspace_id", "plan_version", "plan_task_version",
    "plan_action", "plan_resource_kind", "plan_resource_id", "plan_params_digest",
    "plan_idempotency_key",
)
_APPROVAL_BINDING_TEXT_FIELDS = (
    "plan_task_id", "plan_workspace_id", "plan_action", "plan_resource_kind",
    "plan_resource_id", "plan_params_digest", "plan_idempotency_key",
)


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, allow_nan=False,
                   sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def bound_approval(
    *, action: str, resource_kind: str, resource_id: str,
    plan_version: int, task_version: int, params_digest: str | None,
) -> dict[str, object]:
    approval: dict[str, object] = {
        "action": action, "resource_kind": resource_kind, "resource_id": resource_id,
        "plan_version": plan_version, "task_version": task_version,
    }
    if params_digest is not None:
        approval["params_digest"] = params_digest
    return approval


def paper_account_execution_parameters(plan: object) -> dict:
    verified = validate_plan(plan)
    return {
        "schema_version": "paper-account-create-command.v1",
        "action": PAPER_ACCOUNT_CREATE_ACTION,
        "resource_kind": "research_task",
        "resource_id": verified["task_id"],
        "name": f"research-paper-{verified['task_id'][-12:]}",
        "cash": PAPER_ACCOUNT_DEFAULT_CASH,
    }


def plan_command_digest(
    plan: object, *, action: str, resource_kind: str, resource_id: str,
) -> str:
    verified = validate_plan(plan)
    if action == PAPER_ACCOUNT_CREATE_ACTION:
        return _hash({
            "task_id": verified["task_id"],
            "action": action, "resource_kind": resource_kind, "resource_id": resource_id,
            "execution": paper_account_execution_parameters(verified),
            "references": verified["references"],
        })
    return _hash({
        "task_id": verified["task_id"],
        "plan_version": verified["plan_version"],
        "task_version": verified["task_version"],
        "action": action, "resource_kind": resource_kind, "resource_id": resource_id,
        "references": verified["references"],
    })


def bind_command_digest(plan: object) -> dict[str, object]:
    verified = validate_plan(plan)
    approval = verified["approval"]
    if not isinstance(approval, dict):
        return verified
    digest = plan_command_digest(
        verified, action=approval["action"], resource_kind=approval["resource_kind"],
        resource_id=approval["resource_id"])
    return validate_plan({**verified, "approval": {**approval, "params_digest": digest}})


def plan_command_idempotency_key(
    plan: object, *, action: str, resource_kind: str, resource_id: str,
) -> str:
    digest = plan_command_digest(
        plan, action=action, resource_kind=resource_kind, resource_id=resource_id)
    return "plancmd_" + digest.removeprefix("sha256:")[:32]


def approval_plan_binding(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None
    for field in _APPROVAL_BINDING_FIELDS:
        value = row.get(field)
        if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
            return None
    for field in _APPROVAL_BINDING_TEXT_FIELDS:
        if not isinstance(row.get(field), str) or not row.get(field):
            return None
    return {
        "task_id": row["plan_task_id"], "workspace": row["plan_workspace_id"],
        "plan_version": row["plan_version"], "task_version": row["plan_task_version"],
        "action": row["plan_action"], "resource_kind": row["plan_resource_kind"],
        "resource_id": row["plan_resource_id"], "params_digest": row["plan_params_digest"],
        "idempotency_key": row["plan_idempotency_key"],
    }


def apply_approval_decision(
    plan: object, *, decision: str, action: str, resource_kind: str,
    resource_id: str, params_digest: str,
) -> dict[str, object]:
    """Derive a plan transition from the exact persisted approval facts."""

    verified = validate_plan(plan)
    if decision not in {"approved", "rejected"}:
        return {"outcome": "needs_attention", "reason": "approval_decision_unknown"}
    target = _APPROVAL_TARGET.get(verified["stage"])
    if target is None:
        return {"outcome": "needs_attention", "reason": "approval_action_not_applicable"}
    pending_action, pending_kind, next_stage, status, next_action, next_kind = target
    pending = verified.get("approval")
    if (not isinstance(pending, dict)
            or (action, resource_kind, resource_id)
               != (pending_action, pending_kind, pending.get("resource_id"))
            or pending.get("action") != pending_action
            or pending.get("resource_kind") != pending_kind):
        return {"outcome": "needs_attention", "reason": "approval_binding_mismatch"}
    if pending.get("params_digest") is not None and pending["params_digest"] != params_digest:
        return {"outcome": "needs_attention", "reason": "approval_params_digest_mismatch"}
    try:
        derived_digest = plan_command_digest(
            verified, action=action, resource_kind=resource_kind, resource_id=resource_id)
    except ValueError:
        return {"outcome": "needs_attention", "reason": "approval_command_invalid"}
    if derived_digest != params_digest:
        return {"outcome": "needs_attention", "reason": "approval_params_digest_mismatch"}
    reference = (verified["references"] or {}).get(next_kind)
    target_resource_id = reference.get(next_kind) if isinstance(reference, dict) else None
    if not isinstance(target_resource_id, str):
        return {"outcome": "needs_attention", "reason": "approval_resource_reference_missing"}
    if decision == "rejected":
        return {
            "outcome": "applied", "reason": "approval_rejected",
            "next_stage": verified["stage"], "status": verified["status"],
            "references": verified["references"], "approval": verified["approval"],
        }
    return {
        "outcome": "advance", "reason": "approval_approved", "next_stage": next_stage,
        "status": status, "expected_postcondition": STAGE_POSTCONDITION[next_stage],
        "references": verified["references"],
        "approval": bound_approval(
            action=next_action, resource_kind=next_kind, resource_id=target_resource_id,
            plan_version=verified["plan_version"] + 1, task_version=verified["task_version"],
            params_digest=None,
        ),
    }
