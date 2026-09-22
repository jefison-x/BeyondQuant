"""ADR-0085 P2: closed task/plan/event continuation ledger contract.

This module owns the framework-neutral, CLOSED event envelope and the
server-side deterministic reducer for the five authoritative continuation event
types that ADR-0085 §7 unifies:

    plan_approval, data_ready, backtest_completed, user_resume, recovery

It is BYQ Domain Workflow state, not a second generic agent harness. It holds no
DSH private context, hidden reasoning, tool state or session journal, and it
never starts or references a model turn.

Hard guarantees (all fail closed):

* the envelope is CLOSED: unknown keys, unknown event types, unknown versions and
  forbidden caller routing fields (``next_stage``/``next_action``/``status``/
  ``idempotency_key``/...) are rejected;
* the event binds owner/workspace/task_id, the exact ``plan_version`` and
  ``task_version``, its BYQ-minted identity/version, closed resource references,
  the expected postcondition and a deterministic idempotency ``request_hash``;
* the reducer derives the legal next stage/action/status ONLY from the current
  persisted plan and the authoritative facts supplied by BYQ server code. An
  external caller or model can never submit routing, object identity, a next
  action or an idempotency key;
* a stale/old event (plan or task version mismatch) can never advance the plan;
* ``user_resume``/``recovery`` can only re-derive the CURRENT exact plan action
  and its existing identity: they never create a task, replace an object or mint
  a new business identity.
"""

from __future__ import annotations

import hashlib
import json
import re

from .research_execution_plan import (
    APPROVAL_WAIT_STAGES,
    POSTCONDITIONS,
    RESOURCE_KINDS,
    STAGE_POSTCONDITION,
    validate_plan,
)

EVENT_SCHEMA_VERSION = "research-continuation-event.v1"
EVENT_VERSION = 1

EVENT_TYPES = frozenset({
    "plan_approval",
    "data_ready",
    "backtest_completed",
    "user_resume",
    "recovery",
})

EVENT_DECISIONS = frozenset({"approved", "rejected", "expired", "revoked"})

# Plan human-gate action -> the Agent approval action that authorizes it, and the
# exact inverse. ADR-0085 §3: a plan-bound human approval MUST bind the exact plan
# command (plan/task version, action, resource, parameter digest and BYQ
# idempotency key) at request time, not derive it after the decision.
PLAN_APPROVAL_ACTION = {
    "strategy_approve": "byq_strategy_approve",
    "backtest_task_create": "byq_backtest_task_create",
    "backtest_execute": "byq_backtest_task_execute",
}
AGENT_APPROVAL_PLAN_ACTION = {
    agent_action: plan_action for plan_action, agent_action in PLAN_APPROVAL_ACTION.items()
}

# Outcomes the reducer may return. Closed.
OUTCOMES = frozenset({"advance", "stay", "needs_attention", "retry_current_action"})

# Durable ledger statuses a reducer outcome maps to. ``retry_current_action``
# MUST map to a durable ``pending`` intent, never to a settled receipt: ADR-0085
# P2 forbids claiming a retry succeeded when no consumable command was persisted.
RESULT_STATUSES = frozenset({"advanced", "settled", "needs_attention", "pending"})

# Caller-supplied routing/identity fields that MUST NEVER appear on an event.
FORBIDDEN_EVENT_FIELDS = frozenset({
    "next_stage", "target_stage", "next_action", "target_action", "status",
    "target_status", "route", "routing", "idempotency_key", "business_identity",
    "object_id", "new_object_id", "plan", "conversation_id", "capabilities",
})

# Authoritative P0-style executable actions that data-ready may project. These
# come from BYQ's deterministic derivation, never from a model or caller.
_DATA_READY_ACTIONS = frozenset({"create", "wait", "execute", "review_result", "review_failure", "resolve_blockers"})

_TERMINAL_RESULTS = frozenset({"completed", "failed", "cancelled"})

_BASE_FIELDS = frozenset({
    "schema_version", "event_id", "event_type", "event_version", "source_identity",
    "task_id", "owner_principal", "workspace_id", "plan_version", "task_version",
    "references", "expected_postcondition", "request_hash",
})

_IDENTITY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVENT_ID = re.compile(r"^continuation_event_[0-9a-f]{32}$")
_REFERENCE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# Approval gate stage -> (pending approval action, pending resource kind,
#                          target stage, target status,
#                          target approval action, target resource kind).
# The target approval is BYQ-minted for the target plan version; it is the
# requirement bound to the target stage, not a caller choice.
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
}


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def event_identity(*, event_type: str, source_identity: str, event_version: int) -> str:
    """BYQ-minted deterministic event id. The caller supplies a domain source
    identity (e.g. an artifact/job/approval id), never an arbitrary key."""

    if event_type not in EVENT_TYPES:
        raise ValueError("research continuation event type is unknown")
    if not isinstance(source_identity, str) or _IDENTITY.fullmatch(source_identity) is None:
        raise ValueError("research continuation event source identity is invalid")
    if event_version != EVENT_VERSION:
        raise ValueError("research continuation event version is unsupported")
    digest = hashlib.sha256(
        f"{event_type}\x00{source_identity}\x00{event_version}".encode()
    ).hexdigest()[:32]
    return f"continuation_event_{digest}"


def event_request_hash(event: dict[str, object]) -> str:
    """Deterministic idempotency identity over the authoritative event fields."""

    body = {key: event[key] for key in _BASE_FIELDS if key != "request_hash"}
    body["decision"] = event.get("decision")
    body["params_digest"] = event.get("params_digest")
    return _hash(body)


def validate_event(event: object) -> dict[str, object]:
    """Closed-schema validation. Unknown/missing keys fail closed."""

    if not isinstance(event, dict):
        raise ValueError("research continuation event must be an object")
    forbidden = sorted(set(event) & FORBIDDEN_EVENT_FIELDS)
    if forbidden:
        raise ValueError(f"research continuation event has forbidden caller routing fields: {forbidden}")
    event_type = event.get("event_type")
    if event_type not in EVENT_TYPES:
        raise ValueError("research continuation event type is unknown")
    extras: set[str] = set()
    if event_type == "plan_approval":
        extras = {"decision", "params_digest"}
    elif event_type in {"data_ready", "backtest_completed"}:
        extras = {"params_digest"}
    if set(event) not in (_BASE_FIELDS, _BASE_FIELDS | extras):
        unknown = sorted(set(event) - (_BASE_FIELDS | extras))
        missing = sorted(_BASE_FIELDS - set(event))
        raise ValueError(
            f"research continuation event has invalid fields (unknown={unknown}, missing={missing})")
    if event["schema_version"] != EVENT_SCHEMA_VERSION:
        raise ValueError("research continuation event schema is invalid")
    if event["event_version"] != EVENT_VERSION:
        raise ValueError("research continuation event version is unsupported")
    if not isinstance(event["event_id"], str) or _EVENT_ID.fullmatch(event["event_id"]) is None:
        raise ValueError("research continuation event id is invalid")
    if (not isinstance(event["source_identity"], str)
            or _IDENTITY.fullmatch(event["source_identity"]) is None):
        raise ValueError("research continuation event source identity is invalid")
    for field in ("task_id", "owner_principal", "workspace_id"):
        if not isinstance(event[field], str) or _IDENTITY.fullmatch(event[field]) is None:
            raise ValueError(f"research continuation event {field} is invalid")
    for field in ("plan_version", "task_version"):
        value = event[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"research continuation event {field} is invalid")
    _validate_references(event["references"])
    if event["expected_postcondition"] not in POSTCONDITIONS:
        raise ValueError("research continuation event expected_postcondition is unknown")
    if event_type == "plan_approval":
        if event.get("decision") not in EVENT_DECISIONS:
            raise ValueError("research continuation event decision is unknown")
        _require_digest(event.get("params_digest"))
    elif event_type in {"data_ready", "backtest_completed"}:
        _require_digest(event.get("params_digest"))
    if not isinstance(event["request_hash"], str) or _DIGEST.fullmatch(event["request_hash"]) is None:
        raise ValueError("research continuation event request_hash is invalid")
    if event_request_hash(event) != event["request_hash"]:
        raise ValueError("research continuation event request_hash does not bind its fields")
    return event


def _require_digest(value: object) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("research continuation event params_digest is invalid")


def _validate_references(value: object) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("research continuation event references must be a non-empty object")
    for key, reference in value.items():
        if key not in RESOURCE_KINDS:
            raise ValueError(f"research continuation event reference kind is unknown: {key}")
        if not isinstance(reference, dict) or set(reference) != {key}:
            raise ValueError("research continuation event reference must be a closed kind/id pair")
        identity = reference[key]
        if not isinstance(identity, str) or _REFERENCE_ID.fullmatch(identity) is None:
            raise ValueError("research continuation event reference id is invalid")


def bound_approval(
    *, action: str, resource_kind: str, resource_id: str,
    plan_version: int, task_version: int, params_digest: str | None,
) -> dict[str, object]:
    """Build the exact BYQ-bound approval requirement for a target plan version."""

    approval: dict[str, object] = {
        "action": action, "resource_kind": resource_kind, "resource_id": resource_id,
        "plan_version": plan_version, "task_version": task_version,
    }
    if params_digest is not None:
        approval["params_digest"] = params_digest
    return approval


def default_expected_postcondition(
    *, plan: dict, event_type: str, next_action: str | None = None,
) -> str:
    """The postcondition the reducer will require for this event.

    Server code uses this to build the closed event envelope before hashing; the
    reducer independently re-derives and verifies it, so a wrong value fails
    closed rather than advancing.
    """

    if event_type == "plan_approval":
        stage = plan["stage"]
        if stage not in _APPROVAL_TARGET:
            return plan["expected_postcondition"]
        return STAGE_POSTCONDITION[_APPROVAL_TARGET[stage][2]]
    if event_type == "data_ready":
        if next_action == "execute":
            return "backtest_execute_approval_requested"
        return plan["expected_postcondition"]
    if event_type == "backtest_completed":
        return STAGE_POSTCONDITION["backtest_analysis"]
    return plan["expected_postcondition"]


def _merge_references(current: dict, override: object) -> dict:
    merged = dict(current)
    if isinstance(override, dict):
        merged.update(override)
    return merged


def _reference_id(references: dict, kind: str) -> str | None:
    reference = references.get(kind)
    if isinstance(reference, dict) and isinstance(reference.get(kind), str):
        return reference[kind]
    return None


def _decision(
    outcome: str, reason: str, *, plan: dict, next_stage: str | None = None,
    status: str | None = None, expected_postcondition: str | None = None,
    references: dict | None = None, approval: dict | None = None,
    retry_action: str | None = None, retry_identity: str | None = None,
) -> dict[str, object]:
    if outcome not in OUTCOMES:
        raise ValueError("research continuation decision outcome is unknown")
    return {
        "outcome": outcome,
        "reason": reason,
        "next_stage": next_stage,
        "status": status,
        "expected_postcondition": expected_postcondition,
        "references": references if references is not None else plan["references"],
        "approval": approval,
        "retry_action": retry_action,
        "retry_identity": retry_identity,
    }


def reduce_continuation_event(
    plan: object, event: object, *, facts: object,
) -> dict[str, object]:
    """Derive the legal next plan state from authoritative persisted facts.

    ``facts`` is a closed object supplied by BYQ server code (never a model or an
    external caller). It carries the authoritative derived values for the event
    type. The reducer NEVER accepts a caller-supplied next stage/action/status,
    object identity, idempotency key or routing.
    """

    verified_plan = validate_plan(plan)
    verified_event = validate_event(event)
    if not isinstance(facts, dict):
        raise ValueError("research continuation facts must be an object")
    if verified_event["event_type"] == "data_ready":
        _validate_facts(facts, {"backtest_task_id", "phase", "next_action", "signal_snapshot_id"},
                        optional=set())
    elif verified_event["event_type"] == "backtest_completed":
        _validate_facts(facts, {"backtest_job_id", "backtest_result_id", "terminal_status", "next_action"},
                        optional={"backtest_result_id"})
    else:
        _validate_facts(facts, set(), optional=set())

    if (verified_event["owner_principal"] != verified_plan["owner_principal"]
            or verified_event["workspace_id"] != verified_plan["workspace_id"]):
        raise ValueError("research continuation event owner/workspace does not match the plan")
    if verified_event["task_id"] != verified_plan["task_id"]:
        raise ValueError("research continuation event task does not match the plan")

    # Stale/old events can never advance a newer plan (ADR-0085 §1).
    if verified_event["plan_version"] != verified_plan["plan_version"]:
        return _decision("needs_attention", "stale_plan_version", plan=verified_plan)
    if verified_event["task_version"] != verified_plan["task_version"]:
        return _decision("needs_attention", "stale_task_version", plan=verified_plan)

    dispatch = {
        "plan_approval": _reduce_plan_approval,
        "data_ready": _reduce_data_ready,
        "backtest_completed": _reduce_backtest_completed,
        "user_resume": _reduce_user_resume,
        "recovery": _reduce_recovery,
    }
    return dispatch[verified_event["event_type"]](verified_plan, verified_event, facts)


def _validate_facts(facts: dict, required: set[str], *, optional: set[str]) -> None:
    unknown = sorted(set(facts) - required - optional)
    missing = sorted(required - set(facts))
    if unknown or missing:
        raise ValueError(
            f"research continuation facts have invalid fields (unknown={unknown}, missing={missing})")


def _reduce_plan_approval(plan: dict, event: dict, facts: dict) -> dict:
    stage = plan["stage"]
    if stage not in _APPROVAL_TARGET:
        return _decision("needs_attention", "approval_event_not_applicable", plan=plan)
    pending = plan["approval"]
    if not isinstance(pending, dict):
        return _decision("needs_attention", "no_pending_approval", plan=plan)
    if event["decision"] not in EVENT_DECISIONS:
        return _decision("needs_attention", "approval_decision_unknown", plan=plan)

    (pending_action, pending_kind, target_stage, status,
     approval_action, approval_kind) = _APPROVAL_TARGET[stage]
    if pending.get("action") != pending_action or pending.get("resource_kind") != pending_kind:
        return _decision("needs_attention", "approval_binding_mismatch", plan=plan)
    expected_postcondition = _target_postcondition(target_stage)
    if event["expected_postcondition"] != expected_postcondition:
        return _decision("needs_attention", "unexpected_postcondition", plan=plan)

    if event["decision"] == "rejected":
        return _decision("stay", "approval_rejected", plan=plan)
    if event["decision"] in {"expired", "revoked"}:
        return _decision("needs_attention", f"approval_{event['decision']}", plan=plan)

    # Approved: unlock the EXACT bound command for this precise plan version.
    resource_id = _reference_id(plan["references"], approval_kind)
    if resource_id is None:
        return _decision("needs_attention", "approval_resource_reference_missing", plan=plan)
    params_digest = event.get("params_digest")
    if pending.get("params_digest") is not None and pending.get("params_digest") != params_digest:
        return _decision("needs_attention", "approval_params_digest_mismatch", plan=plan)
    next_version = plan["plan_version"] + 1
    approval = bound_approval(
        action=approval_action, resource_kind=approval_kind, resource_id=resource_id,
        plan_version=next_version, task_version=plan["task_version"],
        params_digest=params_digest if params_digest is not None else pending.get("params_digest"))
    return _decision(
        "advance", "approval_approved", plan=plan, next_stage=target_stage, status=status,
        expected_postcondition=expected_postcondition,
        references=_merge_references(plan["references"], event["references"]),
        approval=approval, retry_identity=plan["idempotency_key"])


def _target_postcondition(stage: str) -> str | None:
    return STAGE_POSTCONDITION[stage]


def _reduce_data_ready(plan: dict, event: dict, facts: dict) -> dict:
    if plan["stage"] != "waiting_for_data":
        return _decision("needs_attention", "data_ready_not_applicable", plan=plan)
    next_action = facts["next_action"]
    if next_action not in _DATA_READY_ACTIONS:
        return _decision("needs_attention", "data_ready_action_unknown", plan=plan)
    if _reference_id(event["references"], "backtest_task") != facts["backtest_task_id"]:
        return _decision("needs_attention", "data_ready_backtest_task_mismatch", plan=plan)
    if _reference_id(event["references"], "signal_snapshot") != facts["signal_snapshot_id"]:
        return _decision("needs_attention", "data_ready_snapshot_mismatch", plan=plan)
    # ADR-0085 §P2: the plan's durable ``signal_producer_job`` reference is the
    # authoritative observed binding. A late data-ready for another job can
    # never advance a plan already waiting on a different exact job.
    plan_job = _reference_id(plan["references"], "signal_producer_job")
    event_job = _reference_id(event["references"], "signal_producer_job")
    if plan_job is not None and event_job is not None and plan_job != event_job:
        return _decision("needs_attention", "data_ready_stale_signal_job", plan=plan)
    if next_action == "wait":
        return _decision("stay", "data_ready_not_yet_executable", plan=plan)
    if next_action != "execute":
        return _decision("needs_attention", "data_ready_unexpected_action", plan=plan)
    if event["expected_postcondition"] != "backtest_execute_approval_requested":
        return _decision("needs_attention", "unexpected_postcondition", plan=plan)
    resource_id = _reference_id(event["references"], "backtest_task")
    next_version = plan["plan_version"] + 1
    approval = bound_approval(
        action="backtest_execute", resource_kind="backtest_task", resource_id=resource_id,
        plan_version=next_version, task_version=plan["task_version"],
        params_digest=event.get("params_digest"))
    return _decision(
        "advance", "data_ready_executable", plan=plan,
        next_stage="waiting_for_task_execute_approval", status="waiting",
        expected_postcondition="backtest_execute_approval_requested",
        references=_merge_references(plan["references"], event["references"]),
        approval=approval, retry_identity=plan["idempotency_key"])


def _reduce_backtest_completed(plan: dict, event: dict, facts: dict) -> dict:
    if plan["stage"] != "waiting_for_backtest_job":
        return _decision("needs_attention", "backtest_completed_not_applicable", plan=plan)
    terminal_status = facts["terminal_status"]
    if terminal_status not in _TERMINAL_RESULTS:
        return _decision("needs_attention", "backtest_job_not_terminal", plan=plan)
    if _reference_id(event["references"], "backtest_job") != facts["backtest_job_id"]:
        return _decision("needs_attention", "backtest_job_mismatch", plan=plan)
    # ADR-0085 §P2: the plan's durable reference is the authoritative observed
    # job binding. An event for a DIFFERENT job of the same task can never
    # advance this plan, regardless of which job a worker selected by recency.
    plan_job = _reference_id(plan["references"], "backtest_job")
    event_job = _reference_id(event["references"], "backtest_job")
    if plan_job is not None and event_job is not None and plan_job != event_job:
        return _decision("needs_attention", "backtest_completed_stale_job", plan=plan)
    if terminal_status != "completed":
        return _decision("needs_attention", f"backtest_job_{terminal_status}", plan=plan)
    result_id = facts.get("backtest_result_id")
    if not isinstance(result_id, str) or _reference_id(event["references"], "backtest_result") != result_id:
        return _decision("needs_attention", "backtest_result_missing", plan=plan)
    postcondition = STAGE_POSTCONDITION["backtest_analysis"]
    if event["expected_postcondition"] != postcondition:
        return _decision("needs_attention", "unexpected_postcondition", plan=plan)
    return _decision(
        "advance", "backtest_completed", plan=plan, next_stage="backtest_analysis",
        status="active", expected_postcondition=postcondition,
        references=_merge_references(plan["references"], event["references"]),
        approval=None, retry_identity=plan["idempotency_key"])


def _retry_decision(plan: dict, reason: str) -> dict:
    if plan["stage"] == "completed" or plan["status"] in {"completed", "cancelled"}:
        return _decision("needs_attention", "terminal_plan_cannot_resume", plan=plan)
    return _decision(
        "retry_current_action", reason, plan=plan,
        retry_action=plan["next_action"], retry_identity=plan["idempotency_key"])


def _reduce_user_resume(plan: dict, event: dict, facts: dict) -> dict:
    return _retry_decision(plan, "user_resume_retry_current_action")


def _reduce_recovery(plan: dict, event: dict, facts: dict) -> dict:
    # Recovery may only retry the current exact plan action. A human gate still
    # requires its human decision, so it stays waiting.
    if plan["stage"] in APPROVAL_WAIT_STAGES:
        return _decision("stay", "recovery_waiting_for_human_decision", plan=plan)
    return _retry_decision(plan, "recovery_retry_current_action")


def plan_command_digest(
    plan: object, *, action: str, resource_kind: str, resource_id: str,
) -> str:
    """BYQ-derived digest of one exact plan command.

    It binds the immutable task identity, the exact plan/task revision the
    command belongs to, the action and its exact resource, and every persisted
    plan reference. Server code derives it; an external caller never supplies
    it, so an approval can never be pinned to a caller-chosen parameter set.
    """

    verified = validate_plan(plan)
    return _hash({
        "task_id": verified["task_id"],
        "plan_version": verified["plan_version"],
        "task_version": verified["task_version"],
        "action": action, "resource_kind": resource_kind, "resource_id": resource_id,
        "references": verified["references"],
    })


def bind_command_digest(plan: object) -> dict[str, object]:
    """Stamp the exact command digest onto a plan's bound approval requirement.

    The digest is computed from the plan's OWN persisted command, so the
    persisted plan always carries a server-derived parameter binding rather than
    a caller value. Plans without an approval requirement are returned as is.
    """

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
    """BYQ-minted idempotency key for one exact plan command.

    It is a pure function of the plan command digest, so it is version- and
    parameter-bound and can never be supplied by an external caller.
    """

    digest = plan_command_digest(
        plan, action=action, resource_kind=resource_kind, resource_id=resource_id)
    return "plancmd_" + digest.removeprefix("sha256:")[:32]


# The persisted plan-command binding columns on an ``agent_approvals`` row. They
# are minted TOGETHER at approval request time; a partial or absent set is not a
# binding (fail closed).
_APPROVAL_BINDING_FIELDS = (
    "plan_task_id", "plan_workspace_id", "plan_version", "plan_task_version",
    "plan_action", "plan_resource_kind", "plan_resource_id", "plan_params_digest",
    "plan_idempotency_key",
)
_APPROVAL_BINDING_TEXT_FIELDS = (
    "plan_task_id", "plan_workspace_id", "plan_action", "plan_resource_kind",
    "plan_resource_id", "plan_params_digest", "plan_idempotency_key",
)


def approval_plan_binding(row: object) -> dict | None:
    """Extract a persisted plan-command binding from an approval row mapping.

    Pure function shared by the approval store (which mints the binding) and the
    continuation ledger (which consumes it). A partial, absent or malformed
    binding returns ``None`` so the caller fails closed.
    """

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


def event_result_status(outcome: str) -> str:
    """Map a reducer outcome to the durable ledger status.

    A ``retry_current_action`` is a durable PENDING intent that still needs to
    be consumed: it is never reported as settled.
    """

    if outcome not in OUTCOMES:
        raise ValueError("research continuation decision outcome is unknown")
    return {
        "advance": "advanced",
        "stay": "settled",
        "needs_attention": "needs_attention",
        "retry_current_action": "pending",
    }[outcome]
