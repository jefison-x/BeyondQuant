"""BYQ authoritative step-safe business recovery (ADR-0084, #351 minimal design).

This module is the framework-neutral, closed contract for the recovery vertical
slice. It carries no DSH session/process/event schema and no database access. It
defines exactly the pure, testable decisions the Runtime Adapter, the Gateway and
the Backend share:

* a deterministic *trigger* / *attempt* identity so a concurrent or repeated
  recovery of the same fenced loss allocates exactly one bounded attempt;
* a closed ``recovery_attempt`` carrier (the only authority the Model/client may
  never mint) and its canonical recomputation;
* a canonical, snapshot-anchored session-global call closure digest;
* a closed per-action step-safety registry and the recovery-mode admission
  envelope (read-only only, or exact idempotent reuse of the original call);
* the corrected no-double-deduction budget decision (tri-state, fail closed).

Nothing here creates a store, a database row, a cross-Plane authority or a new
trust subject. The Backend keeps owning the in-row attempt aggregate; the Adapter
keeps owning the live executor epoch/generation; the Gateway only forwards the
closed carrier.
"""

from __future__ import annotations

import hashlib
import json
import re

from .domain_call_admission import ACTIONS

SCHEMA_VERSION = "business-recovery.v1"
RECOVERY_SNAPSHOT_VERSION = "recovery-snapshot.v1"
TRIGGER_DOMAIN = "recovery-trigger.v1:"
ATTEMPT_PREFIX = "recovery_"

# The hard business-recovery bound from the merged design; a rearm of the
# original reservation is not a new turn, and only `RECOVERY_ATTEMPT_MAX` fenced
# losses of the same reservation are ever rescheduled.
RECOVERY_ATTEMPT_MAX = 3

# Any new recovery *model run* (even a read-only-only envelope) consumes model
# tokens. The conservative per-call ceiling mirrored by the data-ready ledger and
# the runtime guard is the only qualified floor, so a known `R_available` below
# it is blocked. There is deliberately no read-only exemption.
MODEL_CALL_FLOOR = 1048576 + 8192

# Exactly the closed fields the Backend mints and the Adapter re-verifies. The
# client/model cannot add, drop or rename any of them.
RECOVERY_CARRIER_FIELDS = frozenset({
    "attempt_key", "ordinal", "trigger_key", "interrupted_run_id",
    "interrupted_generation", "containment_attempt", "interrupted_executor_epoch",
    "snapshot_tail_sequence", "snapshot_digest",
})

# Every call row that participates in the snapshot digest binds exactly these
# persisted evidence fields (plus the session/trace/tail at the top level).
RECOVERY_CALL_FIELDS = (
    "sequence", "root_run_id", "generation", "agent_run_id",
    "action", "idempotency_key", "request_sha256", "input_sha256",
)

_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_GENERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class RecoveryRejected(RuntimeError):
    """A recovery admission failed closed; no prompt may be submitted.

    ``code`` is a closed, machine-readable reason. ``paused`` distinguishes an
    unknown/unavailable authority (needs user confirmation) from a hard
    ``blocked`` authoritative denial.
    """

    def __init__(self, code: str, detail: str = "", *, paused: bool = True) -> None:
        super().__init__(detail or code)
        self.code = code
        self.paused = paused


def _require_hex(value: object, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise RecoveryRejected("invalid_" + name, f"invalid {name}", paused=False)
    return value


def trigger_key(
    reservation_id: str,
    interrupted_run_id: str,
    interrupted_generation: str,
    containment_attempt: int,
    interrupted_executor_epoch: int,
) -> str:
    """Deterministic SOURCE loss identity; binds the interrupted epoch only."""

    for name, value, pattern in (
        ("reservation_id", reservation_id, re.compile(r"continuation_[0-9a-f]{32}")),
        ("interrupted_run_id", interrupted_run_id, _HEX32),
        ("interrupted_generation", interrupted_generation, _GENERATION),
    ):
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise RecoveryRejected("invalid_trigger_input", f"invalid {name}", paused=False)
    if type(containment_attempt) is not int or not 1 <= containment_attempt < 2 ** 63:
        raise RecoveryRejected("invalid_trigger_input", "invalid containment_attempt", paused=False)
    if type(interrupted_executor_epoch) is not int or not 1 <= interrupted_executor_epoch < 2 ** 63:
        raise RecoveryRejected("invalid_trigger_input", "invalid interrupted_executor_epoch", paused=False)
    material = (TRIGGER_DOMAIN + reservation_id + ":" + interrupted_run_id + ":"
                + interrupted_generation + ":" + str(containment_attempt) + ":"
                + str(interrupted_executor_epoch))
    return hashlib.sha256(material.encode()).hexdigest()


def attempt_key(trigger: str, ordinal: int) -> str:
    """Recomputable, auditable attempt identity from trigger + ordinal."""

    _require_hex(trigger, _HEX64, "trigger_key")
    if type(ordinal) is not int or not 1 <= ordinal <= RECOVERY_ATTEMPT_MAX:
        raise RecoveryRejected("invalid_ordinal", "invalid recovery ordinal", paused=False)
    digest = hashlib.sha256((trigger + ":" + str(ordinal)).encode()).hexdigest()
    return ATTEMPT_PREFIX + digest[:32]


def validate_recovery_carrier(value: object) -> dict:
    """Validate the closed Backend-minted carrier; never accept extra fields."""

    if not isinstance(value, dict) or set(value) != RECOVERY_CARRIER_FIELDS:
        raise RecoveryRejected("invalid_carrier", "invalid recovery carrier", paused=False)
    _require_hex(value["attempt_key"], re.compile(r"recovery_[0-9a-f]{32}"), "attempt_key")
    if type(value["ordinal"]) is not int or not 1 <= value["ordinal"] <= RECOVERY_ATTEMPT_MAX:
        raise RecoveryRejected("invalid_ordinal", "invalid recovery ordinal", paused=False)
    _require_hex(value["trigger_key"], _HEX64, "trigger_key")
    _require_hex(value["interrupted_run_id"], _HEX32, "interrupted_run_id")
    if not isinstance(value["interrupted_generation"], str) or _GENERATION.fullmatch(value["interrupted_generation"]) is None:
        raise RecoveryRejected("invalid_interrupted_generation", "invalid interrupted generation", paused=False)
    if type(value["containment_attempt"]) is not int or not 1 <= value["containment_attempt"] < 2 ** 63:
        raise RecoveryRejected("invalid_containment_attempt", "invalid containment attempt", paused=False)
    if type(value["interrupted_executor_epoch"]) is not int or not 1 <= value["interrupted_executor_epoch"] < 2 ** 63:
        raise RecoveryRejected("invalid_interrupted_epoch", "invalid interrupted executor epoch", paused=False)
    if type(value["snapshot_tail_sequence"]) is not int or not 0 <= value["snapshot_tail_sequence"] < 2 ** 63:
        raise RecoveryRejected("invalid_snapshot_tail", "invalid snapshot tail sequence", paused=False)
    _require_hex(value["snapshot_digest"], _HEX64, "snapshot_digest")
    return dict(value)


def verify_carrier_identity(value: object, *, reservation_id: str) -> dict:
    """Validate shape and recompute the trigger/attempt identity fail closed."""

    carrier = validate_recovery_carrier(value)
    recomputed_trigger = trigger_key(
        reservation_id, carrier["interrupted_run_id"], carrier["interrupted_generation"],
        carrier["containment_attempt"], carrier["interrupted_executor_epoch"])
    if recomputed_trigger != carrier["trigger_key"]:
        raise RecoveryRejected("trigger_key_mismatch", "recovery trigger does not match its source loss", paused=False)
    if attempt_key(carrier["trigger_key"], carrier["ordinal"]) != carrier["attempt_key"]:
        raise RecoveryRejected("attempt_key_mismatch", "recovery attempt key is not derivable", paused=False)
    return carrier


def _closed_call_row(row: object) -> dict:
    if not isinstance(row, dict) or not set(RECOVERY_CALL_FIELDS) <= set(row):
        raise RecoveryRejected("invalid_call_evidence", "invalid closed call row", paused=False)
    result = {}
    for name in RECOVERY_CALL_FIELDS:
        value = row[name]
        if name in {"sequence"}:
            if type(value) is not int or not 1 <= value < 2 ** 63:
                raise RecoveryRejected("invalid_call_evidence", "invalid call sequence", paused=False)
        elif name in {"request_sha256", "input_sha256"}:
            _require_hex(value, _HEX64, name)
        elif name == "root_run_id":
            _require_hex(value, _HEX32, name)
        elif not isinstance(value, str) or not value:
            raise RecoveryRejected("invalid_call_evidence", f"invalid {name}", paused=False)
        result[name] = value
    return result


def canonical_snapshot_digest(
    *, session_id: str, trace_id: str, tail_sequence: int, calls: object,
) -> str:
    """Canonical digest binding session + trace + tail + ordered closed call rows.

    The input is serialized with sorted keys and compact separators so the
    Adapter and the Backend compute byte-identical evidence from the persisted
    append-only rows.
    """

    if not isinstance(session_id, str) or not session_id:
        raise RecoveryRejected("invalid_snapshot_input", "invalid session", paused=False)
    if not isinstance(trace_id, str) or not trace_id:
        raise RecoveryRejected("invalid_snapshot_input", "invalid trace", paused=False)
    if type(tail_sequence) is not int or not 0 <= tail_sequence < 2 ** 63:
        raise RecoveryRejected("invalid_snapshot_input", "invalid tail", paused=False)
    if not isinstance(calls, list) or len(calls) != tail_sequence:
        raise RecoveryRejected("invalid_snapshot_input", "snapshot tail does not match its calls", paused=False)
    rows = [_closed_call_row(row) for row in calls]
    for index, row in enumerate(rows, 1):
        if row["sequence"] != index:
            raise RecoveryRejected("invalid_snapshot_input", "session-global call sequence is not contiguous", paused=False)
    payload = {
        "schema_version": RECOVERY_SNAPSHOT_VERSION,
        "session_id": session_id,
        "trace_id": trace_id,
        "tail_sequence": tail_sequence,
        "calls": rows,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_snapshot_closure(
    *, session_id: str, trace_id: str, expected_tail_sequence: int,
    expected_digest: str, calls: object, more: bool, idle: bool,
) -> dict:
    """Validate a fixed, closed snapshot exactly as the merged design requires.

    ``more`` must be false AND ``idle`` must be true: a final page alone does not
    prove the tail is closed under concurrent appends. Any change to the tail,
    digest or idle state fails closed to ``paused``.
    """

    if more is not False:
        raise RecoveryRejected("snapshot_pagination_incomplete", "snapshot pagination is incomplete")
    if idle is not True:
        raise RecoveryRejected("snapshot_not_idle", "a root turn is still open at the snapshot tail")
    digest = canonical_snapshot_digest(
        session_id=session_id, trace_id=trace_id,
        tail_sequence=expected_tail_sequence, calls=calls)
    if digest != expected_digest:
        raise RecoveryRejected("snapshot_digest_changed", "snapshot tail/digest changed")
    return {"tail_sequence": expected_tail_sequence, "digest": digest, "idle": True}


# Closed step-safety registry. Derived from the domain call admission action set
# so a new action cannot silently become recovery-eligible. ``may_produce_new_key``
# is conservative classification only; an action that may mint a new domain key is
# never automatically rescheduled (enabling that needs a separate Proposed ADR).
STEP_SAFETY = {
    "byq_strategy_validate": {
        "idempotent": True, "result_verifiable": True, "may_produce_new_key": False,
    },
    "byq_factor_compute": {
        "idempotent": True, "result_verifiable": True, "may_produce_new_key": False,
    },
    "byq_ml_strategy_create": {
        "idempotent": True, "result_verifiable": True, "may_produce_new_key": True,
    },
    "byq_strategy_version_create": {
        "idempotent": True, "result_verifiable": True, "may_produce_new_key": True,
    },
}
if set(STEP_SAFETY) != set(ACTIONS):
    raise ValueError("step-safety registry must cover the closed domain action set")


def admission_envelope(*, read_only: bool, replayed_calls: object, occurred_calls: object) -> dict:
    """Recovery-mode envelope: read-only only, or exact reuse of the original call.

    Receipt closure proves only the past; a replayed prompt as a fresh model run
    could still mint a new key. The envelope is therefore enforced against the
    lost root's authoritative occurred-call set and the closed registry.
    """

    if not isinstance(read_only, bool):
        raise RecoveryRejected("invalid_envelope", "read_only must be a bool", paused=False)
    replayed = list(replayed_calls or [])
    occurred = list(occurred_calls or [])
    reasons: list[str] = []
    original = {
        (row["action"], row["task_id"], row["idempotency_key"], row["request_sha256"], row["input_sha256"])
        for row in occurred if isinstance(row, dict) and "action" in row
    }
    for call in replayed:
        if not isinstance(call, dict):
            reasons.append("invalid_call")
            continue
        safety = STEP_SAFETY.get(call.get("action"))
        if safety is None:
            reasons.append("unknown_action")
        elif safety["may_produce_new_key"]:
            reasons.append("new_key_action:" + str(call.get("action")))
        elif not safety["idempotent"]:
            reasons.append("not_idempotent:" + str(call.get("action")))
        elif not safety["result_verifiable"]:
            reasons.append("not_result_verifiable:" + str(call.get("action")))
        else:
            identity = (call.get("action"), call.get("task_id"), call.get("idempotency_key"),
                        call.get("request_sha256"), call.get("input_sha256"))
            if identity not in original:
                reasons.append("not_original_call:" + str(call.get("action")))
    if reasons:
        return {"mode": "blocked", "eligible": False, "reasons": sorted(set(reasons))}
    if read_only:
        return {"mode": "read_only", "eligible": True, "reasons": []}
    if replayed:
        return {"mode": "exact_reuse", "eligible": True, "reasons": []}
    return {"mode": "blocked", "eligible": False, "reasons": ["no_replayable_work"]}


def budget_decision(
    *,
    permission_token_limit: int,
    other_settled: int,
    other_unresolved: int,
    r_token_limit: int,
    cum_exact: int | None,
    model_call_floor: int = MODEL_CALL_FLOOR,
    revoked: bool = False,
    expired: bool = False,
    blocked_reason: str | None = None,
    ordinal: int = 0,
    ordinal_max: int = RECOVERY_ATTEMPT_MAX,
    evidence_conflict: bool = False,
) -> dict:
    """Corrected tri-state budget decision; never double-deducts R's ceiling.

    ``cum_exact`` is the exact charge of the original attempt plus every
    reconciled recovery attempt, or ``None`` when any charge is unknown. Unknown
    cost is never zero and never refunded.
    """

    for value, name in (
        (permission_token_limit, "permission_token_limit"), (other_settled, "other_settled"),
        (other_unresolved, "other_unresolved"), (r_token_limit, "r_token_limit"),
        (model_call_floor, "model_call_floor"), (ordinal, "ordinal"), (ordinal_max, "ordinal_max"),
    ):
        if type(value) is not int or value < 0:
            raise RecoveryRejected("invalid_budget_input", f"invalid {name}", paused=False)
    if cum_exact is not None and (type(cum_exact) is not int or cum_exact < 0):
        raise RecoveryRejected("invalid_budget_input", "invalid cumulative charge", paused=False)

    def decision(name: str, reason: str, available: int | None = None) -> dict:
        return {"decision": name, "reason": reason, "r_available": available}

    if revoked:
        return decision("blocked", "permission_revoked")
    if expired:
        return decision("blocked", "permission_expired")
    if blocked_reason:
        return decision("blocked", "continuation_blocked_reason")
    if ordinal >= ordinal_max:
        return decision("blocked", "ordinal_cap")
    if evidence_conflict:
        return decision("blocked", "authoritative_evidence_conflict")
    if other_settled + other_unresolved + r_token_limit > permission_token_limit:
        return decision("blocked", "grant_invariant_violated")
    if cum_exact is None:
        return decision("paused", "unknown_attempt_charge")
    available = r_token_limit - cum_exact
    if available < 0:
        return decision("blocked", "settlement_exceeds_reservation")
    if available < model_call_floor:
        return decision("blocked", "below_model_call_floor")
    return decision("eligible", "known_headroom", available)


def carrier_fields(attempt: dict) -> dict:
    """Project a stored attempt aggregate onto the closed carrier subset."""

    return {name: attempt[name] for name in RECOVERY_CARRIER_FIELDS}


def accepted_receipt(
    carrier: dict, *, reservation_id: str, run_id: str,
    target_executor_epoch: int, target_generation: str,
) -> dict:
    """The accepted target receipt the Backend persists in its aggregate."""

    if type(target_executor_epoch) is not int or target_executor_epoch < 1:
        raise RecoveryRejected("invalid_target_epoch", "invalid live target epoch", paused=False)
    if not isinstance(target_generation, str) or not target_generation:
        raise RecoveryRejected("invalid_target_generation", "invalid live target generation", paused=False)
    if not isinstance(run_id, str) or _HEX32.fullmatch(run_id) is None:
        raise RecoveryRejected("invalid_target_run", "invalid target run identity", paused=False)
    return {
        "schema_version": "recovery-accepted-receipt.v1",
        "attempt_key": carrier["attempt_key"],
        "reservation_id": reservation_id,
        "ordinal": carrier["ordinal"],
        "run_id": run_id,
        "target_executor_epoch": target_executor_epoch,
        "target_generation": target_generation,
        "snapshot_tail_sequence": carrier["snapshot_tail_sequence"],
        "snapshot_digest": carrier["snapshot_digest"],
    }


def assert_target_current(*, receipt: dict, live_executor_epoch: int, live_generation: str) -> None:
    """Reject a stale/old target receipt or a mismatched target epoch/generation."""

    if not isinstance(receipt, dict):
        raise RecoveryRejected("invalid_target_receipt", "invalid target receipt", paused=False)
    if receipt.get("target_executor_epoch") != live_executor_epoch:
        raise RecoveryRejected(
            "stale_target_epoch", "target executor epoch is not the live epoch", paused=False)
    if receipt.get("target_generation") != live_generation:
        raise RecoveryRejected(
            "stale_target_generation", "target generation is not the live generation", paused=False)


def allocate_recovery_attempt(
    *,
    reservation_id: str,
    existing_attempts: object,
    interrupted_run_id: str,
    interrupted_generation: str,
    containment_attempt: int,
    interrupted_executor_epoch: int,
    snapshot_tail_sequence: int,
    snapshot_digest: str,
    ordinal_max: int = RECOVERY_ATTEMPT_MAX,
) -> tuple[dict, bool]:
    """Pure trigger-keyed allocation used under the Backend task-row lock.

    Returns ``(attempt, created)``. A concurrent/duplicate caller for the SAME
    trigger reuses the existing attempt and never raises the ordinal. The SAME
    trigger with a DIFFERENT snapshot is a conflict: it must not silently rewrite
    the existing attempt and must not consume another ordinal. Only a genuinely
    new fenced loss identity allocates the next ordinal, bounded by the cap.
    """

    attempts = list(existing_attempts or [])
    trigger = trigger_key(
        reservation_id, interrupted_run_id, interrupted_generation,
        containment_attempt, interrupted_executor_epoch)
    _require_hex(snapshot_digest, _HEX64, "snapshot_digest")
    if type(snapshot_tail_sequence) is not int or not 0 <= snapshot_tail_sequence < 2 ** 63:
        raise RecoveryRejected("invalid_snapshot_tail", "invalid snapshot tail sequence", paused=False)
    for attempt in attempts:
        if attempt.get("trigger_key") == trigger:
            if (attempt.get("snapshot_tail_sequence"), attempt.get("snapshot_digest")) != (
                    snapshot_tail_sequence, snapshot_digest):
                raise RecoveryRejected(
                    "snapshot_changed_for_existing_trigger",
                    "the same loss trigger cannot change its bound snapshot", paused=False)
            return dict(attempt), False
    ordinal = len(attempts) + 1
    if ordinal > ordinal_max:
        raise RecoveryRejected("ordinal_cap", "recovery attempt bound reached", paused=False)
    key = attempt_key(trigger, ordinal)
    attempt = {
        "attempt_key": key, "ordinal": ordinal, "trigger_key": trigger,
        "interrupted_run_id": interrupted_run_id,
        "interrupted_generation": interrupted_generation,
        "containment_attempt": containment_attempt,
        "interrupted_executor_epoch": interrupted_executor_epoch,
        "snapshot_tail_sequence": snapshot_tail_sequence,
        "snapshot_digest": snapshot_digest,
        "status": "reserved", "run_id": None,
        "target_executor_epoch": None, "target_generation": None,
        "charged_tokens": None,
    }
    return attempt, True
