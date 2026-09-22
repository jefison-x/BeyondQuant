"""ADR-0085 P3: bounded research-judgment stage input and proposal contract.

This module is BYQ Domain Workflow, not a second generic agent harness. It holds
no DSH private context, hidden reasoning, tool state or session journal, and it
never starts a model turn by itself.

ADR-0085 §6 restricts a research-judgment turn to:

* a bounded projection of the current ``research-execution-plan.v1``;
* a bounded result/evidence summary for the current stage;
* the minimal read-only tool set allowed for that stage;
* ONE domain command that submits a bounded proposal/analysis/decision.

Hard guarantees (all fail closed):

* only a genuine research-judgment stage may start a model turn. Deterministic
  domain stages MUST use zero model calls;
* the stage input and the proposal are CLOSED schemas with explicit byte and
  item bounds. Unknown keys, oversized payloads and raw execution payloads
  (``bars_frame``/``date_index``/full signal snapshots/...) are rejected;
* the proposal may NEVER carry workflow routing, object identity, an approval,
  an idempotency key, a job route or recovery/continuation state. The reducer
  derives the exact next stage/action/status from the persisted plan and the
  proposal kind, never from a caller-supplied target;
* the default bound is two model calls per research stage. After the FIRST call
  or check, a missing durable-progress identity stops the stage as
  ``needs_attention/no_durable_progress`` instead of retrying, spawning
  subagents or consuming the historical eight-call budget.
"""

from __future__ import annotations

import hashlib
import json
import re

from .research_execution_plan import (
    MAX_ROUNDS,
    STAGE_POSTCONDITION,
    can_transition,
    validate_plan,
)

STAGE_INPUT_SCHEMA_VERSION = "research-stage-input.v1"
PROPOSAL_SCHEMA_VERSION = "research-proposal.v1"

# ONLY these stages require genuine research judgment and may start a model
# turn. Every other plan stage is a deterministic domain action.
JUDGMENT_STAGES = frozenset({
    "strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection",
})
JUDGMENT_ACTIONS = frozenset({
    "draft_strategy", "analyse_backtest_result", "compare_iterations", "select_best_iteration",
})

# Default per-stage model-call ceiling. ADR-0085 §6: the normal research
# judgment stage uses at most two model calls (one tool/submission action and
# one final bounded result). A named stage may raise this only with evidence.
DEFAULT_MAX_MODEL_CALLS_PER_STAGE = 2
STAGE_MODEL_CALL_LIMITS = {stage: DEFAULT_MAX_MODEL_CALLS_PER_STAGE for stage in JUDGMENT_STAGES}

# Closed proposal kinds per stage. A kind names the judgment only; it can never
# encode a routing target.
PROPOSAL_ESCALATE = "escalate"
STAGE_PROPOSAL_KINDS = {
    "strategy_draft": frozenset({"strategy_draft", PROPOSAL_ESCALATE}),
    "backtest_analysis": frozenset({"backtest_analysis", PROPOSAL_ESCALATE}),
    "iteration_comparison": frozenset({"select_iteration", "propose_revision", PROPOSAL_ESCALATE}),
    "final_selection": frozenset({"select_iteration", PROPOSAL_ESCALATE}),
}

REVISION_DIRECTIONS = frozenset({
    "tighten_risk", "reduce_turnover", "improve_robustness", "extend_evidence", "none",
})

# Explicit byte/item bounds. The stage input is never a full execution object.
STAGE_INPUT_MAX_BYTES = 65536
STAGE_INPUT_MAX_ITEMS = 64
PROPOSAL_MAX_BYTES = 16384
SHORT_TEXT_MAX = 400
TEXT_MAX = 2000
RATIONALE_MAX = 4000

# Closed evidence descriptor kinds a bounded stage input may carry. These are
# references/summaries, never raw rows.
EVIDENCE_KINDS = frozenset({
    "research_task", "conversation", "strategy_version", "strategy_approval",
    "stock_pool_snapshot", "signal_producer_job", "signal_snapshot", "backtest_task",
    "backtest_job", "backtest_result", "metric_summary", "plan_progress",
})

# Read-only tools a research-judgment stage may expose, per stage. A write tool
# (create/execute/approve) is never allowed.
STAGE_ALLOWED_TOOLS = {
    "strategy_draft": frozenset({"byq_agent_context", "byq_research_get", "byq_research_stage_input_get"}),
    "backtest_analysis": frozenset({
        "byq_agent_context", "byq_research_get", "byq_research_stage_input_get",
        "byq_backtest_task_get", "byq_backtest_analysis_get",
    }),
    "iteration_comparison": frozenset({
        "byq_agent_context", "byq_research_get", "byq_research_stage_input_get",
        "byq_backtest_task_get", "byq_backtest_analysis_get",
    }),
    "final_selection": frozenset({
        "byq_agent_context", "byq_research_get", "byq_research_stage_input_get",
        "byq_backtest_analysis_get",
    }),
}

# Raw execution-payload keys that MUST NEVER appear anywhere in a stage input or
# a proposal. The full signal snapshot/frame/index lists stay in the trusted
# Backend/Worker, not the research-judgment turn.
FORBIDDEN_RAW_KEYS = frozenset({
    "raw_signal_snapshot", "signal_snapshot_rows", "signal_rows", "signals",
    "bars_frame", "bar_frame", "bars", "frame", "raw_bars", "daily_bars",
    "symbol_index", "date_index", "index", "benchmark_series", "benchmark_rows",
    "feature_rows", "raw_features", "daily_returns", "equity_curve",
    "positions", "trades_frame", "corporate_actions", "full_event_log", "event_log",
})

# Caller routing/identity fields that MUST NEVER appear on a proposal. The
# reducer derives every one of these server-side.
FORBIDDEN_PROPOSAL_FIELDS = frozenset({
    "next_stage", "target_stage", "next_action", "target_action", "status",
    "target_status", "route", "routing", "idempotency_key", "business_identity",
    "object_id", "new_object_id", "plan", "conversation_id", "capabilities",
    "allowed_capabilities", "approval", "proposal_id", "event_id", "resource_id",
    "resource_kind", "selected_stage", "task_id_override",
})

# Closed outcome vocabulary, shared with the P2 continuation reducer.
OUTCOMES = frozenset({"advance", "stay", "needs_attention"})

# Durable stop reasons that are legal to persist for a research-judgment turn.
NO_DURABLE_PROGRESS = "no_durable_progress"
MODEL_CALL_LIMIT_EXCEEDED = "model_call_limit_exceeded"
INSUFFICIENT_EVIDENCE = "insufficient_evidence"
ESCALATION_REQUESTED = "escalation_requested"

_IDENTITY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_STAGE_INPUT_BASE_FIELDS = frozenset({
    "schema_version", "task_id", "plan_version", "task_version", "stage", "iteration",
    "status", "objective", "stage_instruction", "proposal_kinds", "evidence",
    "allowed_tools", "model_call_limit", "escalation_allowed",
})

_PROPOSAL_BASE_FIELDS = frozenset({
    "schema_version", "task_id", "plan_version", "task_version", "stage", "iteration",
    "proposal_kind", "evidence_sufficient", "escalate", "summary",
})
_PROPOSAL_OPTIONAL_FIELDS = frozenset({"selected_iteration", "revision_direction", "rationale"})


def stage_requires_model(stage: object) -> bool:
    """Whether a plan stage may start a research-judgment model turn."""

    if not isinstance(stage, str):
        return False
    return stage in JUDGMENT_STAGES


def action_requires_model(action: object) -> bool:
    if not isinstance(action, str):
        return False
    return action in JUDGMENT_ACTIONS


def stage_model_call_limit(stage: str) -> int:
    if stage not in JUDGMENT_STAGES:
        raise ValueError("a deterministic research stage requires zero model calls")
    return STAGE_MODEL_CALL_LIMITS[stage]


def assert_model_turn_allowed(stage: object) -> str:
    """Fail closed for a deterministic stage: it must use zero model calls."""

    if not stage_requires_model(stage):
        raise ValueError("a deterministic research stage must not start a model turn")
    return str(stage)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _text(value: object, field: str, *, maximum: int = TEXT_MAX, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise ValueError(f"research judgment {field} must be a string")
    if len(value) > maximum:
        raise ValueError(f"research judgment {field} exceeds {maximum} characters")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"research judgment {field} is invalid")
    return value


def _reject_raw_keys(value: object, path: str = "value") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_RAW_KEYS:
                raise ValueError(f"research judgment payload contains a raw execution key at {path}.{key}")
            _reject_raw_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_raw_keys(child, f"{path}[{index}]")


def _bounded(value: object, *, maximum: int, field: str) -> None:
    if len(_canonical(value)) > maximum:
        raise ValueError(f"research judgment {field} exceeds {maximum} bytes")


def validate_stage_input(value: object) -> dict[str, object]:
    """Closed, bounded validation for one research-judgment stage input."""

    if not isinstance(value, dict):
        raise ValueError("research stage input must be an object")
    if set(value) != _STAGE_INPUT_BASE_FIELDS:
        unknown = sorted(set(value) - _STAGE_INPUT_BASE_FIELDS)
        missing = sorted(_STAGE_INPUT_BASE_FIELDS - set(value))
        raise ValueError(
            f"research stage input has invalid fields (unknown={unknown}, missing={missing})")
    if value["schema_version"] != STAGE_INPUT_SCHEMA_VERSION:
        raise ValueError("research stage input schema is invalid")
    _reject_raw_keys(value, "stage_input")
    stage = value["stage"]
    if not stage_requires_model(stage):
        raise ValueError("research stage input is only permitted for a research-judgment stage")
    for field in ("task_id",):
        if not isinstance(value[field], str) or _IDENTITY.fullmatch(value[field]) is None:
            raise ValueError(f"research stage input {field} is invalid")
    for field in ("plan_version", "task_version", "iteration", "model_call_limit"):
        number = value[field]
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ValueError(f"research stage input {field} is invalid")
    if value["status"] not in {"active", "waiting", "blocked"}:
        raise ValueError("research stage input status is invalid")
    _text(value["objective"], "objective", maximum=TEXT_MAX)
    _text(value["stage_instruction"], "stage_instruction", maximum=TEXT_MAX)
    if not isinstance(value["escalation_allowed"], bool):
        raise ValueError("research stage input escalation_allowed must be boolean")
    proposal_kinds = value["proposal_kinds"]
    if (not isinstance(proposal_kinds, list) or not proposal_kinds
            or any(kind not in STAGE_PROPOSAL_KINDS[stage] for kind in proposal_kinds)
            or len(set(proposal_kinds)) != len(proposal_kinds)):
        raise ValueError("research stage input proposal_kinds are invalid")
    tools = value["allowed_tools"]
    if (not isinstance(tools, list) or not tools
            or any(tool not in STAGE_ALLOWED_TOOLS[stage] for tool in tools)
            or len(set(tools)) != len(tools)):
        raise ValueError("research stage input allowed_tools are invalid")
    if not isinstance(value["evidence"], list) or len(value["evidence"]) > STAGE_INPUT_MAX_ITEMS:
        raise ValueError("research stage input evidence exceeds its item bound")
    for item in value["evidence"]:
        if not isinstance(item, dict) or set(item) != {"kind", "id", "summary"}:
            raise ValueError("research stage input evidence descriptor is invalid")
        if item["kind"] not in EVIDENCE_KINDS:
            raise ValueError("research stage input evidence kind is unknown")
        if not isinstance(item["id"], str) or _IDENTITY.fullmatch(item["id"]) is None:
            raise ValueError("research stage input evidence id is invalid")
        _text(item["summary"], "evidence.summary", maximum=SHORT_TEXT_MAX)
    if value["model_call_limit"] != stage_model_call_limit(stage):
        raise ValueError("research stage input model_call_limit does not match the stage bound")
    _bounded(value, maximum=STAGE_INPUT_MAX_BYTES, field="stage_input")
    return value


def validate_proposal(value: object) -> dict[str, object]:
    """Closed, bounded validation for one research-judgment proposal."""

    if not isinstance(value, dict):
        raise ValueError("research proposal must be an object")
    forbidden = sorted(set(value) & FORBIDDEN_PROPOSAL_FIELDS)
    if forbidden:
        raise ValueError(f"research proposal has forbidden caller routing/identity fields: {forbidden}")
    allowed = _PROPOSAL_BASE_FIELDS | _PROPOSAL_OPTIONAL_FIELDS
    if not _PROPOSAL_BASE_FIELDS <= set(value) or set(value) - allowed:
        unknown = sorted(set(value) - allowed)
        missing = sorted(_PROPOSAL_BASE_FIELDS - set(value))
        raise ValueError(
            f"research proposal has invalid fields (unknown={unknown}, missing={missing})")
    if value["schema_version"] != PROPOSAL_SCHEMA_VERSION:
        raise ValueError("research proposal schema is invalid")
    _reject_raw_keys(value, "proposal")
    stage = value["stage"]
    if not stage_requires_model(stage):
        raise ValueError("research proposal is only permitted for a research-judgment stage")
    if not isinstance(value["task_id"], str) or _IDENTITY.fullmatch(value["task_id"]) is None:
        raise ValueError("research proposal task_id is invalid")
    for field in ("plan_version", "task_version", "iteration"):
        number = value[field]
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ValueError(f"research proposal {field} is invalid")
    kind = value["proposal_kind"]
    if kind not in STAGE_PROPOSAL_KINDS[stage]:
        raise ValueError("research proposal kind is not valid for its stage")
    if not isinstance(value["evidence_sufficient"], bool) or not isinstance(value["escalate"], bool):
        raise ValueError("research proposal evidence_sufficient/escalate must be boolean")
    _text(value["summary"], "summary", maximum=TEXT_MAX)
    if "rationale" in value:
        _text(value["rationale"], "rationale", maximum=RATIONALE_MAX)
    if "selected_iteration" in value:
        selected = value["selected_iteration"]
        if not isinstance(selected, int) or isinstance(selected, bool) or not 1 <= selected <= MAX_ROUNDS:
            raise ValueError("research proposal selected_iteration is invalid")
    if "revision_direction" in value:
        if value["revision_direction"] not in REVISION_DIRECTIONS:
            raise ValueError("research proposal revision_direction is unknown")
    if kind == "select_iteration" and "selected_iteration" not in value:
        raise ValueError("a select_iteration proposal requires selected_iteration")
    if kind == "propose_revision" and "revision_direction" not in value:
        raise ValueError("a propose_revision proposal requires revision_direction")
    if kind == PROPOSAL_ESCALATE and value["escalate"] is not True:
        raise ValueError("an escalate proposal must set escalate=true")
    _bounded(value, maximum=PROPOSAL_MAX_BYTES, field="proposal")
    return value


def proposal_identity(proposal: object) -> str:
    """BYQ-minted, deterministic proposal identity.

    An external caller never supplies this and it is a pure function of the
    bound plan revision and the bounded proposal body, so a duplicate submission
    is detectably the same command.
    """

    verified = validate_proposal(proposal)
    digest = hashlib.sha256(_canonical(verified)).hexdigest()[:32]
    return f"research_proposal_{digest}"


def proposal_request_hash(proposal: object) -> str:
    verified = validate_proposal(proposal)
    return "sha256:" + hashlib.sha256(_canonical(verified)).hexdigest()


def stage_model_call_outcome(
    *, stage: object, calls_used: object, durable_progress_identity: object,
) -> dict[str, object]:
    """The deterministic progress fence for one research-judgment stage.

    ``calls_used`` counts the model calls already consumed INCLUDING the call that
    just returned. A missing durable-progress identity after the FIRST call stops
    the stage immediately as ``needs_attention/no_durable_progress``: the bound is
    not a retry budget.
    """

    assert_model_turn_allowed(stage)
    if not isinstance(calls_used, int) or isinstance(calls_used, bool) or calls_used < 1:
        raise ValueError("research stage model call count is invalid")
    if durable_progress_identity is not None:
        _digest(durable_progress_identity, "durable_progress_identity")
    limit = stage_model_call_limit(str(stage))
    progressed = durable_progress_identity is not None
    if calls_used > limit:
        return {
            "status": "stop", "outcome": "needs_attention", "reason": MODEL_CALL_LIMIT_EXCEEDED,
            "model_calls_used": calls_used, "model_calls_remaining": 0, "continue": False,
        }
    if calls_used == 1 and not progressed:
        return {
            "status": "stop", "outcome": "needs_attention", "reason": NO_DURABLE_PROGRESS,
            "model_calls_used": calls_used, "model_calls_remaining": limit - calls_used, "continue": False,
        }
    if calls_used >= limit:
        return {
            "status": "stop", "outcome": "advance", "reason": "stage_within_model_call_bound",
            "model_calls_used": calls_used, "model_calls_remaining": 0, "continue": False,
        }
    return {
        "status": "continue", "outcome": None, "reason": "durable_progress_observed",
        "model_calls_used": calls_used, "model_calls_remaining": limit - calls_used, "continue": True,
    }


# Authoritative durable-progress evidence kinds. The caller names a durable BYQ
# record (or an explicit no-progress / plan-advance marker); it NEVER supplies a
# progress digest, so a fabricated digest cannot pass. The seam derives and binds
# the identity from the named persisted record.
PROGRESS_EVIDENCE_KINDS = frozenset({"none", "plan_advance", "artifact", "experiment", "backtest_job"})

# Exact durable-record id shape per evidence kind. A bare digest or any other
# string is not a durable record and fails closed here.
_EVIDENCE_ID_PATTERNS = {
    "artifact": re.compile(r"^artifact_[0-9a-f]{32}$"),
    "experiment": re.compile(r"^experiment_[0-9a-f]{32}$"),
    "backtest_job": re.compile(r"^backtest_[0-9a-f]{32}$"),
}

_STAGE_ADMISSION_FIELDS = frozenset({"call_identity"})
_STAGE_PROGRESS_FIELDS = frozenset({"call_identity", "durable_evidence"})


def validate_call_identity(value: object) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ValueError("research stage call identity is invalid")
    return value


def validate_stage_admission_request(value: object) -> dict[str, object]:
    """Closed admission request: the trusted caller supplies only its call identity.

    The 1-based call count is NEVER caller-supplied; the durable ledger derives it
    under the task-row lock and refuses a third admission.
    """

    if not isinstance(value, dict) or set(value) != _STAGE_ADMISSION_FIELDS:
        raise ValueError("research stage admission request has invalid fields")
    validate_call_identity(value["call_identity"])
    return value


def validate_progress_evidence(value: object) -> dict[str, object]:
    """Closed durable-evidence descriptor (never a caller digest)."""

    if not isinstance(value, dict) or "kind" not in value:
        raise ValueError("research progress evidence must be an object with a kind")
    kind = value["kind"]
    if kind not in PROGRESS_EVIDENCE_KINDS:
        raise ValueError("research progress evidence kind is unknown")
    if kind in {"none", "plan_advance"}:
        if set(value) != {"kind"}:
            raise ValueError("research progress evidence must be a closed kind")
    else:
        if set(value) != {"kind", "id"}:
            raise ValueError("research progress evidence must be a closed kind/id pair")
        identity = value["id"]
        if not isinstance(identity, str) or _EVIDENCE_ID_PATTERNS[kind].fullmatch(identity) is None:
            raise ValueError("research progress evidence id is not a durable record identity")
    _bounded(value, maximum=1024, field="progress_evidence")
    return value


def validate_stage_progress_request(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _STAGE_PROGRESS_FIELDS:
        raise ValueError("research stage progress request has invalid fields")
    validate_call_identity(value["call_identity"])
    validate_progress_evidence(value["durable_evidence"])
    return value


def validate_judgment_result_request(value: object) -> dict[str, object]:
    """Closed model result envelope for the trusted atomic result operation.

    It always carries the authoritative durable-evidence descriptor and may carry
    one closed proposal. It never carries a progress digest, a routing target, an
    identity or an idempotency key.
    """

    if not isinstance(value, dict) or not {"call_identity", "durable_evidence"} <= set(value):
        raise ValueError("research judgment result must carry call identity and evidence")
    if set(value) - {"call_identity", "durable_evidence", "proposal"}:
        unknown = sorted(set(value) - {"call_identity", "durable_evidence", "proposal"})
        raise ValueError(f"research judgment result has invalid fields (unknown={unknown})")
    validate_call_identity(value["call_identity"])
    validate_progress_evidence(value["durable_evidence"])
    if value.get("proposal") is not None:
        validate_proposal(value["proposal"])
    return value


def _decision(outcome: str, reason: str) -> dict[str, object]:
    if outcome not in OUTCOMES:
        raise ValueError("research judgment outcome is unknown")
    return {"outcome": outcome, "reason": reason}


def derive_proposal_commit(plan: object, proposal: object) -> dict[str, object]:
    """Derive the exact next plan state from the persisted plan and proposal.

    The target stage/status/postcondition is computed ENTIRELY server-side from
    the plan's current stage and the closed proposal kind. The proposal can never
    name a routing target, an object identity, an approval or an idempotency key.
    """

    verified_plan = validate_plan(plan)
    verified_proposal = validate_proposal(proposal)

    if verified_proposal["task_id"] != verified_plan["task_id"]:
        return _decision("needs_attention", "proposal_task_mismatch")
    if verified_proposal["plan_version"] != verified_plan["plan_version"]:
        return _decision("needs_attention", "stale_plan_version")
    if verified_proposal["task_version"] != verified_plan["task_version"]:
        return _decision("needs_attention", "stale_task_version")

    stage = verified_plan["stage"]
    if verified_proposal["stage"] != stage:
        return _decision("needs_attention", "proposal_stage_mismatch")
    if verified_proposal["iteration"] != verified_plan["iteration"]:
        return _decision("needs_attention", "proposal_iteration_mismatch")
    if not stage_requires_model(stage):
        return _decision("needs_attention", "proposal_for_deterministic_stage")

    if verified_proposal["escalate"] or verified_proposal["proposal_kind"] == PROPOSAL_ESCALATE:
        return _decision("needs_attention", ESCALATION_REQUESTED)
    if not verified_proposal["evidence_sufficient"]:
        return _decision("needs_attention", INSUFFICIENT_EVIDENCE)

    if stage == "strategy_draft":
        return _advance("waiting_for_strategy_approval", "waiting", "strategy_draft_committed")
    if stage == "backtest_analysis":
        return _advance("iteration_comparison", "active", "backtest_analysis_committed")
    if stage == "iteration_comparison":
        kind = verified_proposal["proposal_kind"]
        iteration = verified_plan["iteration"]
        if kind == "propose_revision":
            if iteration >= MAX_ROUNDS:
                return _decision("needs_attention", "revision_beyond_final_iteration")
            target = "waiting_for_task_create_approval"
            return _advance(target, "waiting", "revision_round_requested", iteration=iteration + 1)
        if kind == "select_iteration":
            selected = verified_proposal.get("selected_iteration")
            if not isinstance(selected, int) or not 1 <= selected <= iteration:
                return _decision("needs_attention", "selected_iteration_out_of_range")
            if iteration != MAX_ROUNDS:
                return _decision("needs_attention", "selection_requires_final_iteration")
            return _advance("final_selection", "active", "best_iteration_selected")
        return _decision("needs_attention", "proposal_kind_not_applicable")
    if stage == "final_selection":
        selected = verified_proposal.get("selected_iteration")
        if not isinstance(selected, int) or not 1 <= selected <= MAX_ROUNDS:
            return _decision("needs_attention", "selected_iteration_out_of_range")
        return _advance("completed", "completed", "research_completed")
    return _decision("needs_attention", "proposal_stage_not_applicable")


def _advance(stage: str, status: str, reason: str, *, iteration: int | None = None) -> dict[str, object]:
    return {
        "outcome": "advance", "reason": reason, "next_stage": stage, "status": status,
        "expected_postcondition": STAGE_POSTCONDITION[stage], "iteration": iteration,
    }


def assert_commit_is_legal(plan: object, decision: object) -> None:
    """Fail closed if a derived decision targets an illegal plan transition."""

    if not isinstance(decision, dict) or decision.get("outcome") != "advance":
        return
    verified_plan = validate_plan(plan)
    target = decision.get("next_stage")
    if not isinstance(target, str) or not can_transition(verified_plan["stage"], target):
        raise ValueError("research judgment decision targets an illegal plan transition")
