"""BYQ session failure containment and business recovery (ADR-0084).

This module is the framework-neutral, closed contract for the current 0.9 hard
gate. It carries no DSH session, process, event or reasoning schema and no
database access. It only defines:

* how a lost execution owner deterministically terminates an incomplete run as
  ``interrupted`` while preserving durable business state;
* the generation/epoch/attempt fence every state-mutating writer must pass;
* the bounded, fail-closed recovery classification (safe retry vs receipt query
  vs user-visible pause) and the old-to-new attempt lineage.

The contract is intentionally free of side effects so both the Runtime Adapter
and the Gateway/Product API can share exactly one decision surface and tests can
break it with negative controls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONTAINMENT_VERSION = "session-failure-containment.v1"
ATTEMPTS_SCHEMA_VERSION = "session-recovery-attempts.v1"
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
# containment outcome.
TERMINAL_INTERRUPTED = "interrupted"
TERMINAL_KINDS = frozenset({"completed", "failed", "cancelled", "interrupted"})

RECOVERY_STATUSES = frozenset({"eligible", "settled", "paused", "blocked", "exhausted"})
RECOVERY_REASONS = frozenset({
    "idempotent_result_verifiable",
    "existing_success_receipt",
    "cancelled",
    "owner_workspace_mismatch",
    "authorization_revoked",
    "budget_exhausted",
    "non_idempotent_step",
    "unknown_side_effect",
    "receipt_absent",
    "receipt_unknown",
    "attempt_in_progress",
    "attempts_exhausted",
})

# Business state that MUST survive an execution loss. Containment that cannot
# attest every item is not containment; it is unreported business-state loss.
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


def _preserved(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(PRESERVED_FIELDS):
        raise ValueError("invalid preserved-shape")
    if any(value[field] is not True for field in PRESERVED_FIELDS):
        raise ValueError("business state must be attested as preserved")
    return {field: True for field in PRESERVED_FIELDS}


def validate_containment_record(value: object) -> dict:
    """Validate one closed loss/containment fact.

    ``interrupted_run_id`` may be absent only when no exact root was ever
    observed; ``interrupted_generation`` and ``executor_epoch`` are always
    recorded so the fence is auditable.
    """

    keys = {
        "schema_version", "conversation_id", "session_id", "trace_id",
        "owner_principal", "workspace_id", "loss_cause", "interrupted_run_id",
        "interrupted_generation", "executor_epoch", "attempt", "preserved", "recorded_at",
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
    if isinstance(value["recorded_at"], bool) or not isinstance(value["recorded_at"], (int, float)):
        raise ValueError("invalid containment timestamp")
    normalized = dict(value)
    normalized["preserved"] = _preserved(value["preserved"])
    return normalized


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
    """One bounded, explainable recovery decision.

    ``status`` is the closed public status; ``reason`` is the machine-readable
    cause; ``auto_retry`` is true only for an explicitly safe, result-verifiable
    step; ``requires_confirmation`` marks a user-visible pause.
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


def classify_recovery(
    *,
    cancelled: bool,
    authorization_current: bool,
    owner_matches: bool,
    workspace_matches: bool,
    budget_available: bool,
    success_receipt_present: bool,
    receipt_queryable: bool,
    step_declared_idempotent: bool,
    step_result_verifiable: bool,
    attempt_in_progress: bool,
    attempts_used: int,
    max_attempts: int = RECOVERY_ATTEMPT_MAX,
    previous_run_id: str | None = None,
    attempt: int | None = None,
) -> RecoveryDecision:
    """Classify whether a lost incomplete run may create a new recovery attempt.

    Order is deliberate: hard invariants (cancel, identity, authorization,
    budget) first, then "already settled" so no side effect is replayed, then the
    conservative unknown-effect pause, then bounded auto retry.
    """

    for value, name in (
        (cancelled, "cancelled"), (authorization_current, "authorization_current"),
        (owner_matches, "owner_matches"), (workspace_matches, "workspace_matches"),
        (budget_available, "budget_available"), (success_receipt_present, "success_receipt_present"),
        (receipt_queryable, "receipt_queryable"), (step_declared_idempotent, "step_declared_idempotent"),
        (step_result_verifiable, "step_result_verifiable"), (attempt_in_progress, "attempt_in_progress"),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a bool")
    if type(attempts_used) is not int or type(max_attempts) is not int or not 0 <= attempts_used or max_attempts < 1:
        raise ValueError("invalid recovery attempt budget")

    if cancelled:
        return _blocked("cancelled")
    if not owner_matches or not workspace_matches:
        return _blocked("owner_workspace_mismatch")
    if not authorization_current:
        return _blocked("authorization_revoked")
    if not budget_available:
        return _blocked("budget_exhausted")
    if success_receipt_present:
        # The exact receipt proves the side effect already committed; never replay.
        return RecoveryDecision(status="settled", reason="existing_success_receipt")
    if not step_declared_idempotent or not step_result_verifiable:
        # A write/order/publish/paid/unknown-result step whose receipt is absent
        # or unqueryable is paused for the user; it is never auto-retried.
        if not step_declared_idempotent:
            reason = "non_idempotent_step"
        elif receipt_queryable:
            reason = "receipt_absent"
        else:
            reason = "receipt_unknown"
        return RecoveryDecision(status="paused", reason=reason, requires_confirmation=True)
    if attempt_in_progress:
        # Concurrent recovery requests converge on one authoritative attempt.
        return _blocked("attempt_in_progress")
    if attempts_used >= max_attempts:
        return RecoveryDecision(status="exhausted", reason="attempts_exhausted")
    lineage = {}
    if previous_run_id is not None:
        if not isinstance(previous_run_id, str) or _RUN.fullmatch(previous_run_id) is None:
            raise ValueError("invalid previous run identity")
        lineage["previous_run_id"] = previous_run_id
        lineage["attempt"] = attempts_used + 1 if attempt is None else attempt
    return RecoveryDecision(status="eligible", reason="idempotent_result_verifiable", auto_retry=True, lineage=lineage)


ATTEMPT_STATES = frozenset({"in_progress", "settled", "failed"})


def build_attempt(
    *,
    attempt: int,
    previous_run_id: str | None,
    new_run_id: str,
    generation: str,
    idempotency_key: str,
    state: str,
    created_at: float,
) -> dict:
    """Build one old-to-new lineage record for an authorized recovery attempt."""

    if type(attempt) is not int or not 1 <= attempt <= RECOVERY_ATTEMPT_MAX:
        raise ValueError("invalid recovery attempt number")
    if previous_run_id is not None and (not isinstance(previous_run_id, str) or _RUN.fullmatch(previous_run_id) is None):
        raise ValueError("invalid previous run identity")
    if not isinstance(new_run_id, str) or _RUN.fullmatch(new_run_id) is None:
        raise ValueError("invalid new run identity")
    if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
        raise ValueError("invalid recovery generation")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
        raise ValueError("invalid recovery idempotency key")
    if state not in ATTEMPT_STATES:
        raise ValueError("invalid recovery attempt state")
    if isinstance(created_at, bool) or not isinstance(created_at, (int, float)):
        raise ValueError("invalid recovery timestamp")
    return {
        "attempt": attempt,
        "previous_run_id": previous_run_id,
        "new_run_id": new_run_id,
        "generation": generation,
        "idempotency_key": idempotency_key,
        "state": state,
        "created_at": created_at,
    }


def validate_attempt_ledger(value: object) -> dict:
    """Validate the bounded, append-only recovery attempt ledger."""

    keys = {"schema_version", "session_id", "max_attempts", "attempts"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("invalid recovery attempt ledger")
    if value["schema_version"] != ATTEMPTS_SCHEMA_VERSION:
        raise ValueError("unsupported recovery attempt ledger schema")
    _identity(value["session_id"], "session_id")
    if value["max_attempts"] != RECOVERY_ATTEMPT_MAX:
        raise ValueError("recovery attempt ledger has an invalid bound")
    attempts = value["attempts"]
    if not isinstance(attempts, list) or len(attempts) > RECOVERY_ATTEMPT_MAX:
        raise ValueError("recovery attempt ledger is unbounded")
    expected = 1
    previous_new = None
    for index, row in enumerate(attempts):
        keys_row = {"attempt", "previous_run_id", "new_run_id", "generation",
                    "idempotency_key", "state", "created_at"}
        if not isinstance(row, dict) or set(row) != keys_row:
            raise ValueError("invalid recovery attempt record")
        if row["attempt"] != expected:
            raise ValueError("recovery attempts must be monotonic and gapless")
        if expected > 1 and row["previous_run_id"] != previous_new:
            raise ValueError("recovery attempt lineage must chain the previous new run")
        if row["state"] == "in_progress" and index != len(attempts) - 1:
            raise ValueError("only the newest recovery attempt may be in progress")
        build_attempt(**row)
        previous_new = row["new_run_id"]
        expected += 1
    return dict(value)


def ledger_has_open_attempt(ledger: object) -> bool:
    """True while the newest recovery attempt has no terminal settlement."""

    if not isinstance(ledger, dict):
        raise ValueError("invalid recovery attempt ledger")
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return False
    return attempts[-1].get("state") == "in_progress"
