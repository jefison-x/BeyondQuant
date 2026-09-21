"""BYQ session failure containment and business recovery (ADR-0084).

This module is the framework-neutral, closed contract for the current 0.9 hard
gate. It carries no DSH session, process, event or reasoning schema and no
database access. It defines only:

* how a lost execution owner deterministically terminates an incomplete run as
  ``interrupted`` while the execution boundary does not modify durable business
  state;
* the generation/epoch/attempt fence every state-mutating writer must pass;
* a bounded, fail-closed recovery *classification* (safe retry vs receipt query
  vs user-visible pause).

There is deliberately **no** attempt-creation or automatic-resubmission model
here. Automatic rescheduling requires server-side authoritative action/workflow
step-safety and budget metadata; when that metadata is absent, unavailable or
ambiguous the classification fails closed to ``paused`` and no new prompt may be
submitted. The contract is free of side effects so both the Runtime Adapter and
the Gateway/Product API share exactly one decision surface and tests can break
it with negative controls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONTAINMENT_VERSION = "session-failure-containment.v1"
PRESERVATION_SCHEMA_VERSION = "session-containment-preservation.v1"
RECOVERY_ATTEMPT_MAX = 3

# How the execution owner of an incomplete run was lost. Exhaustive and closed:
# an unknown cause is a programming error, never a silent "completed".
LOSS_CAUSES = frozenset({
    "parent-loss",
    "runtime-loss",
    "executor-loss",
    "lease-expired",
    "heartbeat-expired",
    "process-restart",
})

# A lost incomplete run may only become ``interrupted``. ``completed`` is never a
# containment outcome. The other terminal kinds keep their ordinary meaning.
TERMINAL_INTERRUPTED = "interrupted"
TERMINAL_KINDS = frozenset({"completed", "failed", "cancelled", "interrupted", "discarded", "closed"})

RECOVERY_STATUSES = frozenset({"eligible", "settled", "paused", "blocked"})
RECOVERY_REASONS = frozenset({
    "idempotent_result_verifiable",
    "existing_success_receipt",
    "cancelled",
    "owner_workspace_mismatch",
    "authorization_revoked",
    "budget_exhausted",
    "authority_unavailable",
    "step_safety_unavailable",
    "non_idempotent_step",
    "unknown_side_effect",
    "receipt_absent",
    "receipt_unknown",
})

# The execution boundary asserts it does not modify these durable business
# states. This is a boundary contract, NOT evidence that any state survived: the
# Gateway/Domain must independently verify actual before/after state.
BOUNDARY_INVARIANT = "execution-boundary-does-not-modify-business-state.v1"
PRESERVED_FIELDS = (
    "conversation",
    "durable_job",
    "authorization",
    "approval",
    "artifact",
    "workflow_trace",
    "idempotency_keys",
    "budget",
    "cancel_state",
    "audit_chain",
)
PRESERVATION_STATES = frozenset({"preserved", "unknown", "unavailable"})

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_RUN = re.compile(r"[0-9a-f]{32}")
_GENERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class FencedWrite(RuntimeError):
    """A state-mutating write lost the generation/epoch/attempt race.

    Old-generation writers, late terminal settlements, duplicate settlements and
    terminal-run reopen attempts MUST fail closed with this error and MUST NOT
    overwrite a newer generation's state.
    """


def _identity(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"invalid {field_name}")
    return value


def validate_loss_cause(value: object) -> str:
    if not isinstance(value, str) or value not in LOSS_CAUSES:
        raise ValueError("invalid loss cause")
    return value


def validate_containment_record(value: object) -> dict:
    """Validate one closed loss/containment fact.

    ``interrupted_run_id`` may be absent only when no exact root was ever
    observed; ``interrupted_generation`` and ``executor_epoch`` are always
    recorded so the fence is auditable. ``boundary_invariant`` is the execution
    boundary's non-modification assertion, not observed business evidence.
    """

    keys = {
        "schema_version", "conversation_id", "session_id", "trace_id",
        "owner_principal", "workspace_id", "loss_cause", "interrupted_run_id",
        "interrupted_generation", "executor_epoch", "attempt", "boundary_invariant", "recorded_at",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("invalid containment record")
    if value["schema_version"] != CONTAINMENT_VERSION:
        raise ValueError("unsupported containment schema")
    conversation_id = value["conversation_id"]
    if conversation_id is not None:
        _identity(conversation_id, "conversation_id")
    for name in ("session_id", "trace_id"):
        _identity(value[name], name)
    for name in ("owner_principal", "workspace_id"):
        if not isinstance(value[name], str) or not 1 <= len(value[name]) <= 128:
            raise ValueError("invalid containment owner/workspace")
    validate_loss_cause(value["loss_cause"])
    run = value["interrupted_run_id"]
    if run is not None and (not isinstance(run, str) or _RUN.fullmatch(run) is None):
        raise ValueError("invalid interrupted run identity")
    if not isinstance(value["interrupted_generation"], str) or not value["interrupted_generation"]:
        raise ValueError("invalid interrupted generation")
    if type(value["executor_epoch"]) is not int or not 1 <= value["executor_epoch"] < 2 ** 63:
        raise ValueError("invalid containment executor epoch")
    if type(value["attempt"]) is not int or not 1 <= value["attempt"] < 2 ** 63:
        raise ValueError("invalid containment attempt")
    if value["boundary_invariant"] != BOUNDARY_INVARIANT:
        raise ValueError("invalid containment boundary invariant")
    if isinstance(value["recorded_at"], bool) or not isinstance(value["recorded_at"], (int, float)):
        raise ValueError("invalid containment timestamp")
    return dict(value)


def validate_preservation(value: object) -> dict:
    """Validate the Gateway/Domain actual before/after preservation projection."""

    keys = {"schema_version", "states", "boundary_invariant", "boundary_verified", "sources"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("invalid preservation projection")
    if value["schema_version"] != PRESERVATION_SCHEMA_VERSION:
        raise ValueError("unsupported preservation schema")
    states = value["states"]
    if not isinstance(states, dict) or set(states) != set(PRESERVED_FIELDS):
        raise ValueError("invalid preservation shape")
    if any(state not in PRESERVATION_STATES for state in states.values()):
        raise ValueError("invalid preservation state")
    if value["boundary_invariant"] != BOUNDARY_INVARIANT:
        raise ValueError("invalid preservation boundary invariant")
    if value["boundary_verified"] is not False:
        # The boundary assertion is never self-verified; only observed state can
        # be presented as preserved.
        raise ValueError("boundary invariant cannot be self-verified")
    if not isinstance(value["sources"], dict) or not value["sources"]:
        raise ValueError("preservation projection requires authoritative sources")
    for field_name, state in states.items():
        if state == "preserved" and field_name not in value["sources"]:
            raise ValueError("a preserved field requires an authoritative source")
    return dict(value)


def assert_generation_fenced(
    *,
    authoritative_epoch: int,
    authoritative_generation: str,
    write_epoch: int,
    write_generation: str,
) -> None:
    """Fail closed unless the writer is the current generation and epoch."""

    if type(authoritative_epoch) is not int or type(write_epoch) is not int:
        raise ValueError("generation fence requires integer epochs")
    if not isinstance(authoritative_generation, str) or not _GENERATION.fullmatch(authoritative_generation):
        raise ValueError("invalid authoritative generation")
    if not isinstance(write_generation, str) or not _GENERATION.fullmatch(write_generation):
        raise ValueError("invalid write generation")
    if write_epoch != authoritative_epoch:
        raise FencedWrite("executor epoch changed; writer is fenced")
    if write_generation != authoritative_generation:
        raise FencedWrite("stale generation; writer is fenced")


def assert_fenced(
    *,
    authoritative_epoch: int,
    authoritative_generation: str,
    authoritative_attempt: int,
    write_epoch: int,
    write_generation: str,
    write_attempt: int,
) -> None:
    """Fail closed unless the writer is the current generation/epoch/attempt."""

    if type(authoritative_attempt) is not int or type(write_attempt) is not int:
        raise ValueError("generation fence requires integer attempt")
    assert_generation_fenced(
        authoritative_epoch=authoritative_epoch,
        authoritative_generation=authoritative_generation,
        write_epoch=write_epoch,
        write_generation=write_generation,
    )
    if write_attempt != authoritative_attempt:
        raise FencedWrite("stale or duplicate attempt; writer is fenced")


def assert_terminal_settlement(*, settled: object, write_attempt: int, write_terminal: str) -> None:
    """Reject late, duplicate and terminal-reopen settlements.

    ``settled`` maps an attempt number to the terminal kind already persisted for
    that attempt. Re-settling the same attempt (duplicate or reopen) and
    settling behind the highest persisted attempt both fail closed.
    """

    if not isinstance(settled, dict) or type(write_attempt) is not int or write_attempt < 1:
        raise ValueError("invalid terminal settlement state")
    if write_terminal not in TERMINAL_KINDS:
        raise ValueError("invalid terminal kind")
    for attempt, terminal in settled.items():
        if type(attempt) is not int or attempt < 1 or terminal not in TERMINAL_KINDS:
            raise ValueError("invalid settled terminal state")
        if attempt == write_attempt:
            raise FencedWrite("attempt already has a terminal settlement")
    if settled and write_attempt < max(settled):
        raise FencedWrite("late settlement behind the authoritative attempt")


@dataclass(frozen=True)
class RecoveryDecision:
    """One bounded, explainable recovery classification.

    ``status`` is the closed public status; ``reason`` is the machine-readable
    cause; ``auto_retry`` is true only for an explicitly safe, result-verifiable
    step whose authority and budget are independently verified.
    """

    status: str
    reason: str
    auto_retry: bool = False
    requires_confirmation: bool = False
    lineage: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in RECOVERY_STATUSES:
            raise ValueError("invalid recovery status")
        if self.reason not in RECOVERY_REASONS:
            raise ValueError("invalid recovery reason")
        if self.auto_retry and self.status != "eligible":
            raise ValueError("auto retry only applies to an eligible recovery")
        if self.requires_confirmation and self.status != "paused":
            raise ValueError("confirmation pause only applies to a paused recovery")

    def view(self) -> dict:
        return {
            "schema_version": CONTAINMENT_VERSION,
            "status": self.status,
            "reason": self.reason,
            "auto_retry": self.auto_retry,
            "requires_confirmation": self.requires_confirmation,
            "lineage": dict(self.lineage),
        }


def _blocked(reason: str) -> RecoveryDecision:
    return RecoveryDecision(status="blocked", reason=reason)


def _paused(reason: str) -> RecoveryDecision:
    return RecoveryDecision(status="paused", reason=reason, requires_confirmation=True)


def classify_recovery(
    *,
    cancelled: bool,
    authorization_current: bool | None,
    owner_matches: bool | None,
    workspace_matches: bool | None,
    budget_available: bool | None,
    success_receipt_present: bool,
    receipt_queryable: bool,
    step_declared_idempotent: bool,
    step_result_verifiable: bool,
    previous_run_id: str | None = None,
) -> RecoveryDecision:
    """Classify whether a lost incomplete run may create a new recovery attempt.

    Authority inputs are tri-state. ``False`` is an authoritative denial and
    blocks recovery; ``None`` is *unknown/unavailable* and pauses for the user
    (it is never treated as allowed). Only a fully verified authority plus a
    contract-declared idempotent and result-verifiable step may be ``eligible``.
    """

    for value, name in (
        (cancelled, "cancelled"), (success_receipt_present, "success_receipt_present"),
        (receipt_queryable, "receipt_queryable"), (step_declared_idempotent, "step_declared_idempotent"),
        (step_result_verifiable, "step_result_verifiable"),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a bool")
    for value, name in (
        (authorization_current, "authorization_current"), (owner_matches, "owner_matches"),
        (workspace_matches, "workspace_matches"), (budget_available, "budget_available"),
    ):
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{name} must be a bool or None")

    if cancelled:
        return _blocked("cancelled")
    if owner_matches is False or workspace_matches is False:
        return _blocked("owner_workspace_mismatch")
    if authorization_current is False:
        return _blocked("authorization_revoked")
    if budget_available is False:
        return _blocked("budget_exhausted")
    if (authorization_current is None or owner_matches is None
            or workspace_matches is None or budget_available is None):
        # Unverifiable authority is never treated as permission.
        return _paused("authority_unavailable")
    if success_receipt_present:
        # The exact receipt proves the side effect already committed; never replay.
        return RecoveryDecision(status="settled", reason="existing_success_receipt")
    if not step_declared_idempotent or not step_result_verifiable:
        # A write/order/publish/paid/unknown-result step whose receipt is absent
        # or unqueryable is paused for the user; it is never auto-retried.
        if not step_declared_idempotent:
            return _paused("non_idempotent_step")
        return _paused("receipt_absent" if receipt_queryable else "receipt_unknown")
    lineage = {}
    if previous_run_id is not None:
        if not isinstance(previous_run_id, str) or _RUN.fullmatch(previous_run_id) is None:
            raise ValueError("invalid previous run identity")
        lineage["previous_run_id"] = previous_run_id
    return RecoveryDecision(status="eligible", reason="idempotent_result_verifiable",
                            auto_retry=True, lineage=lineage)
