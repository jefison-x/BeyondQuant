"""ADR-0084 authoritative business-recovery admission for the Runtime Adapter.

This module implements the Adapter half of the #351 minimal design:

* it derives the fixed, session-global snapshot ``{tail, digest, idle}`` from the
  real, append-only BYQ lifecycle journal (no DSH state, no business database);
* it re-verifies the closed Backend-minted ``recovery_attempt`` carrier
  (shape, trigger/attempt identity, durable containment, snapshot anchoring);
* it performs the validate-then-atomic-compare-and-start inside the Adapter's
  ``record.lock`` admission boundary, so a new root/call appearing between the
  evidence review and the re-dispatch fails closed instead of being overwritten.

It creates no store, no authority and no trust subject. The live target
epoch/generation are read from the Adapter's own authoritative record at
admission; the Backend never pretends to know them.
"""

from __future__ import annotations

from packages.contracts import business_recovery as contract

from . import containment


def snapshot_from_state(state: dict) -> dict:
    """Fixed snapshot of the session-global call evidence + open-root idle flag."""

    context = state["context"]
    calls = list(state.get("calls") or [])
    tail = len(calls)
    digest = contract.canonical_snapshot_digest(
        session_id=context["session_id"], trace_id=context["trace_id"],
        tail_sequence=tail, calls=calls)
    return {
        "schema_version": contract.RECOVERY_SNAPSHOT_VERSION,
        "tail_sequence": tail,
        "digest": digest,
        "idle": state.get("open_root") is None,
        "calls": calls,
    }


def match_containment(carrier: dict, records: object) -> dict:
    """Require one durable containment fact exactly matching the source loss."""

    for record in records or []:
        if (record.get("interrupted_run_id") == carrier["interrupted_run_id"]
                and record.get("interrupted_generation") == carrier["interrupted_generation"]
                and record.get("attempt") == carrier["containment_attempt"]
                and record.get("executor_epoch") == carrier["interrupted_executor_epoch"]):
            return record
    raise contract.RecoveryRejected(
        "containment_mismatch",
        "no durable containment record matches this recovery source loss", paused=False)


def read_containment(evidence_root, session_id: str) -> list[dict]:
    """Read the fenced containment ledger; unreadable/corrupt fails closed."""

    try:
        return containment.read(evidence_root, session_id)
    except (OSError, ValueError, containment.ContainmentConflict) as exc:
        raise contract.RecoveryRejected(
            "containment_unreadable", "durable containment evidence is unavailable") from exc


def verify_carrier(carrier: object, *, reservation_id: str, evidence_root, session_id: str) -> dict:
    """Full fail-closed carrier verification (no admission / no install yet)."""

    verified = contract.verify_carrier_identity(carrier, reservation_id=reservation_id)
    records = read_containment(evidence_root, session_id)
    match_containment(verified, records)
    return verified


def verify_snapshot_against_state(carrier: dict, state: dict) -> dict:
    """Atomically compare the CURRENT snapshot with the carrier's anchored one."""

    snapshot = snapshot_from_state(state)
    return contract.verify_snapshot_closure(
        session_id=state["context"]["session_id"], trace_id=state["context"]["trace_id"],
        expected_tail_sequence=carrier["snapshot_tail_sequence"],
        expected_digest=carrier["snapshot_digest"],
        calls=snapshot["calls"], more=False, idle=snapshot["idle"])


def admission_precheck(
    *, journal_state: dict, carrier: object, reservation_id: str, evidence_root, session_id: str,
) -> dict:
    """Validate the carrier and the CURRENT snapshot; never mutates the record.

    Called while the Adapter holds ``record.lock`` and before any new
    root/generation is installed, which closes the check-then-start TOCTOU.
    """

    verified = verify_carrier(
        carrier, reservation_id=reservation_id, evidence_root=evidence_root, session_id=session_id)
    verify_snapshot_against_state(verified, journal_state)
    return verified


def accepted_receipt(
    carrier: dict, *, reservation_id: str, run_id: str,
    target_executor_epoch: int, target_generation: str,
) -> dict:
    """The accepted target receipt the Backend persists in its aggregate."""

    return contract.accepted_receipt(
        carrier, reservation_id=reservation_id, run_id=run_id,
        target_executor_epoch=target_executor_epoch, target_generation=target_generation)


def assert_target_current(*, receipt: dict, live_executor_epoch: int, live_generation: str) -> None:
    """Reject a stale/old target receipt or a mismatched target epoch/generation."""

    contract.assert_target_current(
        receipt=receipt, live_executor_epoch=live_executor_epoch, live_generation=live_generation)
