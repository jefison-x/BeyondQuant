"""ADR-0085 P1: framework-neutral domain execution plan.

This is BYQ Domain Workflow state, not a second generic agent harness. It holds
no DSH private context, hidden reasoning, tool state or session journal.

The vocabulary below is derived INDEPENDENTLY from the ordinary-strategy
three-round backtest chain that ADR-0085 §1-2 closes over. The key separation
ADR-0085 requires is:

* ``waiting_for_*_approval`` stages are HUMAN GATES: the plan is waiting, the
  only action is ``request_*_approval``/``wait``, NO write capability is
  exposed, and no model/agent may approve.
* after an exact bound approval EVENT, the plan enters a separate READY stage
  whose deterministic action performs the already-approved write.

Guarantees enforced here:

* the schema is CLOSED: unknown/extra keys are rejected;
* stages/statuses/actions/capabilities/resource-kinds/prerequisites/
  postconditions are closed enums, never free text;
* each stage has exactly one legal status set and one legal action;
* only legal stage transitions are accepted;
* references/prerequisites/postconditions are closed structures;
* pending approval requirements bind action + resource kind/id (+ plan/task
  version), and never carry an execution write capability;
* compare-and-swap checks the versions INSIDE the supplied plan. The atomic
  stale/replay guarantee across persisted rows belongs to the store's
  transactional CAS (tested with the store), not to this pure function.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = "research-execution-plan.v1"

# --------------------------------------------------------------------------- #
# Closed vocabulary
# --------------------------------------------------------------------------- #

# HUMAN GATE stages (no write capability, no model approval) vs READY stages
# where the already-approved deterministic action is executed.
STAGES = frozenset({
    "strategy_draft",
    "waiting_for_strategy_approval",
    "ready_to_create_backtest_task",
    "waiting_for_task_create_approval",
    "waiting_for_data",
    "waiting_for_task_execute_approval",
    "ready_to_execute_backtest_task",
    "waiting_for_backtest_job",
    "backtest_analysis",
    "iteration_comparison",
    "final_selection",
    "needs_attention",
    "completed",
})

# Human-gate stages: the plan is waiting on a human decision. These must never
# expose an execution write capability.
APPROVAL_WAIT_STAGES = frozenset({
    "waiting_for_strategy_approval",
    "waiting_for_task_create_approval",
    "waiting_for_task_execute_approval",
})

READY_STAGES = frozenset({
    "ready_to_create_backtest_task",
    "ready_to_execute_backtest_task",
})

ACTION_STAGES = frozenset({
    "strategy_draft", "waiting_for_data", "waiting_for_backtest_job",
    "backtest_analysis", "iteration_comparison", "final_selection",
})

STATUSES = frozenset({"active", "waiting", "blocked", "completed", "cancelled"})

NEXT_ACTIONS = frozenset({
    "draft_strategy",
    "request_strategy_approval",
    "create_backtest_task",
    "wait_for_data",
    "execute_backtest_task_approval_wait",
    "execute_backtest_task",
    "wait_for_backtest_job",
    "analyse_backtest_result",
    "compare_iterations",
    "select_best_iteration",
    "resolve_blockers",
    "notify_user",
    "cancel_research",
})

ITERATIONS = frozenset({1, 2, 3})
MAX_ROUNDS = 3

# Closed resource kinds that may appear in plan references / approvals.
RESOURCE_KINDS = frozenset({
    "research_task", "conversation", "strategy_version", "strategy_approval",
    "stock_pool_snapshot", "signal_producer_job", "signal_snapshot",
    "backtest_task", "backtest_job", "backtest_result", "ml_prediction",
})

# Closed prerequisites: exact domain facts that must already hold.
PREREQUISITES = frozenset({
    "strategy_draft_validated",
    "strategy_version_approved",
    "strategy_version_validated",
    "backtest_task_create_approved",
    "backtest_task_prepared",
    "signal_snapshot_validated",
    "backtest_task_execute_approved",
    "backtest_job_terminal",
    "backtest_result_available",
    "iteration_analysis_complete",
    "previous_iteration_settled",
})

# Closed expected postconditions: the exact domain fact the action must create.
POSTCONDITIONS = frozenset({
    "strategy_draft_created",
    "strategy_approval_requested",
    "strategy_version_approved",
    "backtest_task_created",
    "backtest_task_prepared",
    "signal_job_completed_with_validated_snapshot",
    "backtest_execute_approval_requested",
    "backtest_job_queued",
    # ADR-0085 P2 additive: ``waiting_for_backtest_job`` already declares this
    # exact postcondition in its stage spec; it was missing from the closed set.
    "backtest_result_available",
    "backtest_result_analysed",
    "iteration_compared",
    "next_round_task_create_approval_requested",
    "best_iteration_selected",
    "blocks_resolved_or_confirmed",
    "user_notified",
    "research_cancelled",
})

# The P0 ``research-executable-action.v1`` action -> P1 action, ONLY where the
# meaning is exactly the same. Explicit, never a compatibility alias.
P0_ACTION_EQUIVALENTS = {
    "create": "create_backtest_task",
    "wait": "wait_for_data",
    "execute": "execute_backtest_task",
    "review_result": "analyse_backtest_result",
    "review_failure": "resolve_blockers",
    "resolve_blockers": "resolve_blockers",
}

# Exact minimum capability per action. A human-gate wait action exposes NO write
# capability; an execution READY action exposes only its own write tool.
ACTION_CAPABILITIES = {
    "draft_strategy": frozenset({"byq_research_get", "byq_strategy_version_create"}),
    # Human gate: agent may only read; it may NOT approve.
    "request_strategy_approval": frozenset({"byq_research_get"}),
    "create_backtest_task": frozenset({"byq_research_get", "byq_backtest_task_create"}),
    "wait_for_data": frozenset({"byq_research_get", "byq_backtest_task_get"}),
    # Human gate: agent may only read; it may NOT execute.
    "execute_backtest_task_approval_wait": frozenset({"byq_research_get"}),
    "execute_backtest_task": frozenset({"byq_research_get", "byq_backtest_task_execute"}),
    "wait_for_backtest_job": frozenset({"byq_research_get", "byq_backtest_task_get"}),
    "analyse_backtest_result": frozenset({"byq_research_get", "byq_backtest_analysis_get"}),
    "compare_iterations": frozenset({"byq_research_get", "byq_backtest_task_get"}),
    "select_best_iteration": frozenset({"byq_research_get"}),
    "resolve_blockers": frozenset({"byq_research_get"}),
    "notify_user": frozenset(),
    "cancel_research": frozenset({"byq_research_get"}),
}

# Actions requiring a bound human approval, keyed by the READY action.
ACTION_APPROVAL = {
    "create_backtest_task": {"action": "backtest_task_create",
                             "resource_kind": "strategy_version"},
    "execute_backtest_task": {"action": "backtest_execute",
                              "resource_kind": "backtest_task"},
}

# Actions that are deterministic domain actions and must NEVER start a model
# turn (ADR-0085 §2.1).
DETERMINISTIC_ACTIONS = frozenset({
    "create_backtest_task", "wait_for_data", "execute_backtest_task",
    "wait_for_backtest_job", "resolve_blockers", "notify_user", "cancel_research",
})

# Stage -> (single legal action, legal status set, allowed prerequisite set,
#           exact expected postcondition, bound-approval requirement or None).
_STAGE_SPEC: dict[str, dict[str, object]] = {
    "strategy_draft": {
        "action": "draft_strategy", "statuses": {"active"},
        "prerequisites": set(), "postcondition": "strategy_draft_created",
        "approval": None,
    },
    "waiting_for_strategy_approval": {
        "action": "request_strategy_approval", "statuses": {"waiting"},
        "prerequisites": {"strategy_draft_validated"},
        "postcondition": "strategy_approval_requested",
        "approval": {"action": "strategy_approve", "resource_kind": "strategy_version"},
    },
    "ready_to_create_backtest_task": {
        "action": "create_backtest_task", "statuses": {"active"},
        "prerequisites": {"strategy_version_approved"},
        "postcondition": "backtest_task_created",
        "approval": {"action": "backtest_task_create", "resource_kind": "strategy_version"},
    },
    "waiting_for_task_create_approval": {
        "action": "request_strategy_approval", "statuses": {"waiting"},
        "prerequisites": {"strategy_version_approved"},
        "postcondition": "next_round_task_create_approval_requested",
        "approval": {"action": "backtest_task_create", "resource_kind": "strategy_version"},
    },
    "waiting_for_data": {
        "action": "wait_for_data", "statuses": {"waiting"},
        "prerequisites": {"backtest_task_prepared"},
        "postcondition": "signal_job_completed_with_validated_snapshot",
        "approval": None,
    },
    "waiting_for_task_execute_approval": {
        "action": "execute_backtest_task_approval_wait", "statuses": {"waiting"},
        "prerequisites": {"signal_snapshot_validated"},
        "postcondition": "backtest_execute_approval_requested",
        "approval": {"action": "backtest_execute", "resource_kind": "backtest_task"},
    },
    "ready_to_execute_backtest_task": {
        "action": "execute_backtest_task", "statuses": {"active"},
        "prerequisites": {"backtest_task_execute_approved"},
        "postcondition": "backtest_job_queued",
        "approval": {"action": "backtest_execute", "resource_kind": "backtest_task"},
    },
    "waiting_for_backtest_job": {
        "action": "wait_for_backtest_job", "statuses": {"waiting"},
        "prerequisites": {"backtest_job_terminal"},
        "postcondition": "backtest_result_available",
        "approval": None,
    },
    "backtest_analysis": {
        "action": "analyse_backtest_result", "statuses": {"active"},
        "prerequisites": {"backtest_result_available"},
        "postcondition": "backtest_result_analysed",
        "approval": None,
    },
    "iteration_comparison": {
        "action": "compare_iterations", "statuses": {"active"},
        "prerequisites": {"iteration_analysis_complete"},
        "postcondition": "iteration_compared",
        "approval": None,
    },
    "final_selection": {
        "action": "select_best_iteration", "statuses": {"active"},
        "prerequisites": {"previous_iteration_settled"},
        "postcondition": "best_iteration_selected",
        "approval": None,
    },
    "needs_attention": {
        "action": "resolve_blockers", "statuses": {"blocked"},
        "prerequisites": set(), "postcondition": "blocks_resolved_or_confirmed",
        "approval": None,
    },
    "completed": {
        "action": "notify_user", "statuses": {"completed", "cancelled"},
        "prerequisites": set(), "postcondition": "user_notified",
        "approval": None,
    },
}

# Cancellation is a terminal transition available from any non-terminal stage.
CANCEL_STAGE = "completed"
CANCEL_STATUS = "cancelled"
CANCEL_ACTION = "cancel_research"
CANCEL_POSTCONDITION = "research_cancelled"

# Legal stage transitions. Human-gate stages lead to a separate READY stage.
_TRANSITIONS = {
    "strategy_draft": {"waiting_for_strategy_approval", "needs_attention", "completed"},
    # ADR-0085 P2 additive edges: every high-impact write (task create and task
    # execute) keeps its OWN human gate instead of collapsing the strategy gate
    # straight into a write-ready stage. The original
    # ``waiting_for_strategy_approval -> ready_to_create_backtest_task`` edge is
    # retained for backward compatibility but the deterministic reducer never
    # uses it: it routes through the explicit create gate. These are additive
    # edges only, so the P1 transitions and tests are unchanged.
    "waiting_for_strategy_approval": {
        "ready_to_create_backtest_task", "waiting_for_task_create_approval",
        "needs_attention", "completed",
    },
    "ready_to_create_backtest_task": {"waiting_for_data", "needs_attention", "completed"},
    "waiting_for_task_create_approval": {
        "ready_to_create_backtest_task", "waiting_for_data", "needs_attention", "completed",
    },
    "waiting_for_data": {
        "waiting_for_task_execute_approval", "ready_to_execute_backtest_task",
        "needs_attention", "completed",
    },
    "waiting_for_task_execute_approval": {
        "ready_to_execute_backtest_task", "needs_attention", "completed",
    },
    "ready_to_execute_backtest_task": {"waiting_for_backtest_job", "needs_attention", "completed"},
    "waiting_for_backtest_job": {"backtest_analysis", "needs_attention", "completed"},
    "backtest_analysis": {"iteration_comparison", "needs_attention", "completed"},
    "iteration_comparison": {
        "waiting_for_task_create_approval", "final_selection", "needs_attention", "completed",
    },
    "final_selection": {"completed", "needs_attention"},
    "needs_attention": {
        "strategy_draft", "waiting_for_strategy_approval",
        "ready_to_create_backtest_task", "waiting_for_task_create_approval",
        "waiting_for_data", "waiting_for_task_execute_approval",
        "ready_to_execute_backtest_task", "waiting_for_backtest_job",
        "backtest_analysis", "iteration_comparison",
    },
    "completed": set(),
}

# Public stage -> single legal action table (derived from the stage spec).
STAGE_ACTION = {stage: spec["action"] for stage, spec in _STAGE_SPEC.items()}

# Public stage -> exact expected postcondition (ADR-0085 P2 read-only helper).
STAGE_POSTCONDITION = {stage: spec["postcondition"] for stage, spec in _STAGE_SPEC.items()}

# Public stage -> bound human-approval requirement or None (ADR-0085 P3 helper).
# A proposal commit derives the target stage's approval requirement itself; an
# external caller never supplies the action/resource/version binding.
STAGE_APPROVAL_REQUIREMENT = {
    stage: (dict(spec["approval"]) if isinstance(spec["approval"], dict) else None)
    for stage, spec in _STAGE_SPEC.items()
}

# The single non-cancelled status a stage defaults to when a plan is built
# directly at that stage (legacy adoption). A stage whose legal set is only
# ``{completed, cancelled}`` defaults to ``completed``; every other stage has
# exactly one legal status.
STAGE_STATUS = {
    stage: next(iter(sorted(set(spec["statuses"]) - {"cancelled"})), "active")
    for stage, spec in _STAGE_SPEC.items()
}

_REQUIRED_FIELDS = frozenset({
    "schema_version", "task_id", "plan_version", "task_version",
    "owner_principal", "workspace_id", "conversation_id",
    "stage", "iteration", "status", "next_action",
    "references", "prerequisites", "expected_postcondition",
    "approval", "idempotency_key", "allowed_capabilities",
    "last_progress_identity",
})

_IDENTITY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REFERENCE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def can_transition(current_stage: str, next_stage: str) -> bool:
    return next_stage in _TRANSITIONS.get(current_stage, set())


def assert_transition(current_stage: str, next_stage: str) -> None:
    if current_stage not in STAGES or next_stage not in STAGES:
        raise ValueError("research execution plan stage is unknown")
    if not can_transition(current_stage, next_stage):
        raise ValueError(
            f"illegal research execution plan transition: {current_stage} -> {next_stage}")


def _validate_references(value: object) -> None:
    """Closed references: {resource_kind: {kind-appropriate exact id}}."""

    if not isinstance(value, dict):
        raise ValueError("research execution plan references must be an object")
    for key, reference in value.items():
        if key not in RESOURCE_KINDS:
            raise ValueError(f"research execution plan reference kind is unknown: {key}")
        if not isinstance(reference, dict) or set(reference) != {key}:
            raise ValueError("research execution plan reference must be a closed kind/id pair")
        identity = reference[key]
        if not isinstance(identity, str) or _REFERENCE_ID.fullmatch(identity) is None:
            raise ValueError("research execution plan reference id is invalid")


def _validate_prerequisites(value: object) -> None:
    if not isinstance(value, list) or any(item not in PREREQUISITES for item in value):
        raise ValueError("research execution plan prerequisites are not closed enum values")
    if len(set(value)) != len(value):
        raise ValueError("research execution plan prerequisites contain duplicates")


def _validate_approval(
    value: object, *, plan: dict[str, object], spec_approval: object, next_action: str,
) -> None:
    required = spec_approval if isinstance(spec_approval, dict) else ACTION_APPROVAL.get(next_action)
    if required is None:
        if value is not None:
            raise ValueError("research execution plan approval is not permitted for its action")
        return
    # ADR-0085 P2 additive field: an approval may carry a BYQ-computed
    # ``params_digest`` binding the exact action parameters. It is optional for
    # backward compatibility (P1 plans carry the five-field shape) but when
    # present it MUST be a closed sha256 digest.
    base_fields = {"action", "resource_kind", "resource_id", "plan_version", "task_version"}
    if (not isinstance(value, dict) or set(value) not in (base_fields, base_fields | {"params_digest"})):
        raise ValueError("research execution plan approval requirement is invalid")
    if "params_digest" in value and (
            not isinstance(value["params_digest"], str)
            or _DIGEST.fullmatch(value["params_digest"]) is None):
        raise ValueError("research execution plan approval params_digest is invalid")
    if value["resource_kind"] not in RESOURCE_KINDS:
        raise ValueError("research execution plan approval resource kind is unknown")
    if value["action"] != required["action"] or value["resource_kind"] != required["resource_kind"]:
        raise ValueError("research execution plan approval does not match its action")
    if (not isinstance(value["resource_id"], str)
            or _REFERENCE_ID.fullmatch(value["resource_id"]) is None):
        raise ValueError("research execution plan approval resource id is invalid")
    for field in ("plan_version", "task_version"):
        if not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 1:
            raise ValueError(f"research execution plan approval {field} is invalid")
    # The approval is bound to THIS plan version and task version, so a stale or
    # future approval can never authorize a different plan revision.
    if value["plan_version"] != plan["plan_version"]:
        raise ValueError("research execution plan approval plan_version does not match the plan")
    if value["task_version"] != plan["task_version"]:
        raise ValueError("research execution plan approval task_version does not match the plan")
    # The approved resource id must be exactly the plan's reference for that kind.
    references = plan["references"] if isinstance(plan.get("references"), dict) else {}
    reference = references.get(required["resource_kind"])
    if (not isinstance(reference, dict)
            or reference.get(required["resource_kind"]) != value["resource_id"]):
        raise ValueError("research execution plan approval resource is not bound to its reference")


def validate_plan(plan: object) -> dict[str, object]:
    """Closed-schema validation. Unknown or missing keys fail closed."""

    if not isinstance(plan, dict):
        raise ValueError("research execution plan must be an object")
    if set(plan) != _REQUIRED_FIELDS:
        unknown = sorted(set(plan) - _REQUIRED_FIELDS)
        missing = sorted(_REQUIRED_FIELDS - set(plan))
        raise ValueError(
            f"research execution plan has invalid fields (unknown={unknown}, missing={missing})")
    if plan["schema_version"] != SCHEMA_VERSION:
        raise ValueError("research execution plan schema is invalid")

    for field in ("task_id", "owner_principal", "workspace_id", "conversation_id"):
        if not isinstance(plan[field], str) or _IDENTITY.fullmatch(plan[field]) is None:
            raise ValueError(f"research execution plan {field} is invalid")
    for field in ("plan_version", "task_version"):
        value = plan[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"research execution plan {field} must be a positive integer")

    stage = plan["stage"]
    if stage not in STAGES:
        raise ValueError("research execution plan stage is unknown")
    spec = _STAGE_SPEC[stage] if stage != CANCEL_STAGE else None

    status = plan["status"]
    if status not in STATUSES:
        raise ValueError("research execution plan status is unknown")
    if stage == CANCEL_STAGE:
        # completed stage carries either completed or cancelled, both terminal.
        if status not in {"completed", "cancelled"}:
            raise ValueError("a terminal plan stage requires a terminal status")
    elif status not in spec["statuses"]:
        raise ValueError(f"research execution plan status {status} is invalid for stage {stage}")

    action = plan["next_action"]
    if action not in NEXT_ACTIONS:
        raise ValueError("research execution plan next_action is unknown")
    if stage == CANCEL_STAGE and status == "cancelled":
        if action != CANCEL_ACTION:
            raise ValueError("a cancelled plan must carry the cancel action")
        expected_postcondition = CANCEL_POSTCONDITION
        expected_prerequisites: object = []
    else:
        if action != spec["action"]:
            raise ValueError("research execution plan next_action does not match its stage")
        expected_postcondition = spec["postcondition"]
        expected_prerequisites = sorted(spec["prerequisites"])

    iteration = plan["iteration"]
    if iteration not in ITERATIONS:
        raise ValueError("research execution plan iteration must be 1..3")
    if stage == "final_selection" and iteration != MAX_ROUNDS:
        raise ValueError("final selection requires the final iteration")

    _validate_references(plan["references"])
    _validate_prerequisites(plan["prerequisites"])
    if sorted(plan["prerequisites"]) != expected_prerequisites:
        raise ValueError("research execution plan prerequisites do not match its stage")
    if plan["expected_postcondition"] != expected_postcondition:
        raise ValueError("research execution plan expected_postcondition does not match its stage")

    _validate_approval(plan["approval"], plan=plan,
                       spec_approval=spec["approval"] if spec else None, next_action=action)

    if not isinstance(plan["idempotency_key"], str) or not plan["idempotency_key"]:
        raise ValueError("research execution plan idempotency_key is invalid")

    capabilities = plan["allowed_capabilities"]
    if (not isinstance(capabilities, list)
            or any(not isinstance(item, str) for item in capabilities)):
        raise ValueError("research execution plan allowed_capabilities are invalid")
    expected_capabilities = ACTION_CAPABILITIES[action]
    if set(capabilities) != set(expected_capabilities):
        raise ValueError("research execution plan capabilities do not match its action")
    if stage in APPROVAL_WAIT_STAGES and any(
            capability.endswith(("_create", "_execute", "_approve"))
            for capability in capabilities):
        raise ValueError("a human approval gate must not expose a write capability")

    if plan["last_progress_identity"] is not None and (
            not isinstance(plan["last_progress_identity"], str)
            or _DIGEST.fullmatch(plan["last_progress_identity"]) is None):
        raise ValueError("research execution plan progress identity is invalid")
    return plan


def is_deterministic_action(action: str) -> bool:
    if action not in NEXT_ACTIONS:
        raise ValueError("research execution plan action is unknown")
    return action in DETERMINISTIC_ACTIONS


def new_plan(
    *, task_id: str, owner_principal: str, workspace_id: str, conversation_id: str,
    task_version: int, idempotency_key: str, references: dict[str, object] | None = None,
    iteration: int = 1, last_progress_identity: str | None = None,
) -> dict[str, object]:
    """Create the initial plan (version 1) at ``strategy_draft``."""

    stage = "strategy_draft"
    plan = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "plan_version": 1,
        "task_version": task_version,
        "owner_principal": owner_principal,
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "stage": stage,
        "iteration": iteration,
        "status": "active",
        "next_action": _STAGE_SPEC[stage]["action"],
        "references": references if references is not None else {
            "research_task": {_kind_key("research_task"): task_id},
            "conversation": {_kind_key("conversation"): conversation_id},
        },
        "prerequisites": sorted(_STAGE_SPEC[stage]["prerequisites"]),
        "expected_postcondition": _STAGE_SPEC[stage]["postcondition"],
        "approval": None,
        "idempotency_key": idempotency_key,
        "allowed_capabilities": sorted(ACTION_CAPABILITIES[_STAGE_SPEC[stage]["action"]]),
        "last_progress_identity": last_progress_identity,
    }
    return validate_plan(plan)


def plan_at_stage(
    *, task_id: str, owner_principal: str, workspace_id: str, conversation_id: str,
    task_version: int, stage: str, idempotency_key: str,
    references: dict[str, object] | None = None, iteration: int = 1,
    approval: dict[str, object] | None = None,
    last_progress_identity: str | None = None,
) -> dict[str, object]:
    """Build a validated version-1 plan at an explicit legal stage.

    This is only for adopting an already-existing legacy task whose stage maps
    UNIQUELY (ADR-0085 §Migration). It never invents a next action: the stage's
    single legal action, prerequisite set and expected postcondition are used.
    A write-ready stage still requires its exact bound approval; without it the
    caller must fall back to ``needs_attention`` rather than guess.
    """

    if stage not in STAGES:
        raise ValueError("research execution plan stage is unknown")
    if stage == CANCEL_STAGE:
        action = _STAGE_SPEC[CANCEL_STAGE]["action"]
        postcondition = _STAGE_SPEC[CANCEL_STAGE]["postcondition"]
        prerequisites: list[str] = []
        required_approval: object = None
    else:
        spec = _STAGE_SPEC[stage]
        action = spec["action"]
        postcondition = spec["postcondition"]
        prerequisites = sorted(spec["prerequisites"])
        required_approval = spec["approval"]
    if required_approval is not None and approval is None:
        raise ValueError("research execution plan stage requires its bound approval")
    plan = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "plan_version": 1,
        "task_version": task_version,
        "owner_principal": owner_principal,
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "stage": stage,
        "iteration": iteration,
        "status": STAGE_STATUS[stage],
        "next_action": action,
        "references": references if references is not None else {
            "research_task": {_kind_key("research_task"): task_id},
            "conversation": {_kind_key("conversation"): conversation_id},
        },
        "prerequisites": prerequisites,
        "expected_postcondition": postcondition,
        "approval": approval,
        "idempotency_key": idempotency_key,
        "allowed_capabilities": sorted(ACTION_CAPABILITIES[action]),
        "last_progress_identity": last_progress_identity,
    }
    return validate_plan(plan)


def _kind_key(kind: str) -> str:
    return kind


def advance(
    plan: object,
    *,
    expected_plan_version: int,
    expected_task_version: int,
    next_stage: str,
    iteration: int,
    status: str,
    expected_postcondition: str,
    idempotency_key: str,
    references: dict[str, object] | None = None,
    prerequisites: list[str] | None = None,
    approval: dict[str, object] | None = None,
    last_progress_identity: str | None,
) -> dict[str, object]:
    """Compare-and-swap plan advance.

    This validates the versions INSIDE the supplied plan. The atomic guarantee
    that a persisted row has not advanced underneath the caller is provided by
    the store's transactional CAS, not by this pure function.
    """

    current = validate_plan(plan)
    if current["plan_version"] != expected_plan_version:
        raise ValueError("research execution plan version is stale")
    if current["task_version"] != expected_task_version:
        raise ValueError("research execution task version is stale")
    assert_transition(str(current["stage"]), next_stage)

    stage = current["stage"]
    action = current["next_action"]
    if next_stage == "iteration_comparison" and iteration != current["iteration"]:
        raise ValueError("iteration comparison must keep the current iteration")
    if stage == "iteration_comparison" and next_stage == "waiting_for_task_create_approval":
        if iteration != current["iteration"] + 1 or iteration > MAX_ROUNDS:
            raise ValueError("the next round must advance the iteration by exactly one")
    if next_stage == "final_selection" and iteration != MAX_ROUNDS:
        raise ValueError("final selection requires the final iteration")

    next_spec = _STAGE_SPEC[next_stage]
    if status not in next_spec["statuses"]:
        raise ValueError(f"research execution plan status {status} is invalid for stage {next_stage}")
    if next_stage == CANCEL_STAGE:
        terminal_status = CANCEL_STATUS if status == CANCEL_STATUS else "completed"
        advanced = {
            **current,
            "plan_version": current["plan_version"] + 1,
            "stage": CANCEL_STAGE, "iteration": iteration, "status": terminal_status,
            "next_action": CANCEL_ACTION if terminal_status == "cancelled" else _STAGE_SPEC[CANCEL_STAGE]["action"],
            "references": references if references is not None else current["references"],
            "prerequisites": [],
            "expected_postcondition": CANCEL_POSTCONDITION if terminal_status == "cancelled"
            else _STAGE_SPEC[CANCEL_STAGE]["postcondition"],
            "approval": None,
            "idempotency_key": idempotency_key,
            "allowed_capabilities": sorted(ACTION_CAPABILITIES[
                CANCEL_ACTION if terminal_status == "cancelled" else _STAGE_SPEC[CANCEL_STAGE]["action"]]),
            "last_progress_identity": last_progress_identity,
        }
        return validate_plan(advanced)

    expected_prereqs = sorted(next_spec["prerequisites"])
    chosen_prereqs = expected_prereqs if prerequisites is None else sorted(prerequisites)
    if chosen_prereqs != expected_prereqs:
        raise ValueError("research execution plan prerequisites do not match its stage")
    if expected_postcondition != next_spec["postcondition"]:
        raise ValueError("research execution plan expected_postcondition does not match its stage")

    advanced = {
        **current,
        "plan_version": current["plan_version"] + 1,
        "stage": next_stage, "iteration": iteration, "status": status,
        "next_action": next_spec["action"],
        "references": references if references is not None else current["references"],
        "prerequisites": chosen_prereqs,
        "expected_postcondition": expected_postcondition,
        "approval": approval,
        "idempotency_key": idempotency_key,
        "allowed_capabilities": sorted(ACTION_CAPABILITIES[next_spec["action"]]),
        "last_progress_identity": last_progress_identity,
    }
    return validate_plan(advanced)


def classify_legacy_task(
    *, task_terminal: bool, stage_hint: str | None, next_action_hint: str | None,
    has_unique_plan_object: bool,
) -> dict[str, object]:
    """Decide whether an existing task can be migrated to a plan.

    ADR-0085: a task that cannot be mapped UNIQUELY enters ``needs_attention``.
    This never guesses a stage from free text.
    """

    if task_terminal:
        return {"status": "needs_attention", "reason": "task_terminal_requires_review"}
    if not has_unique_plan_object:
        return {"status": "needs_attention", "reason": "no_unique_current_plan_object"}
    if not isinstance(stage_hint, str) or stage_hint not in STAGES:
        return {"status": "needs_attention", "reason": "stage_is_not_a_closed_plan_stage"}
    if not isinstance(next_action_hint, str) or next_action_hint not in NEXT_ACTIONS:
        return {"status": "needs_attention", "reason": "next_action_is_not_a_closed_plan_action"}
    if stage_hint == CANCEL_STAGE:
        return {"status": "needs_attention", "reason": "terminal_or_blocked_requires_review"}
    if _STAGE_SPEC[stage_hint]["action"] != next_action_hint:
        return {"status": "needs_attention", "reason": "stage_and_action_disagree"}
    if stage_hint == "needs_attention":
        return {"status": "needs_attention", "reason": "terminal_or_blocked_requires_review"}
    return {"status": "migratable", "reason": "unique_closed_stage_and_action"}
