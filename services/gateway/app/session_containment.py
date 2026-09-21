"""ADR-0084 Product-visible containment and bounded business recovery.

The Gateway derives containment strictly from the normalized BYQ WorkflowTrace
and the durable adapter containment summary. It never reads a raw DSH event, a
DSH session id, or the business database directly. Business state (conversation,
authorization, approval, artifacts, jobs, receipts, budget, cancel) stays in the
Domain Plane; recovery only ever creates one bounded, auditable new attempt that
queries the exact receipt before any replay.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time

from packages.contracts.session_failure_containment import (
    ATTEMPTS_SCHEMA_VERSION,
    CONTAINMENT_VERSION,
    LOSS_CAUSES,
    RECOVERY_ATTEMPT_MAX,
    build_attempt,
    classify_recovery,
    ledger_has_open_attempt,
    validate_attempt_ledger,
)

TERMINAL_KINDS = frozenset({
    "session.result", "session.failed", "session.cancelled", "session.result.discarded",
})
COMPLETED = "session.result"
INTERRUPTED = "interrupted"
CANCELLED = "cancelled"


class RecoveryConflict(RuntimeError):
    """A recovery request conflicts with the one authoritative attempt."""


def _owned(events: object, session_id: str, trace_id: str) -> list[dict]:
    if not isinstance(events, list):
        return []
    return sorted(
        (event for event in events if isinstance(event, dict)
         and event.get("session_id") == session_id and event.get("trace_id") == trace_id
         # Only normalized BYQ projections; a raw DSH event is never a source.
         and event.get("source") in {"runtime-adapter", "byq-domain"}),
        key=lambda event: event.get("sequence", 0),
    )


def loss_from_trace(events: object, session_id: str, trace_id: str) -> dict:
    """Derive interruption and cancel state from normalized BYQ events only."""

    owned = _owned(events, session_id, trace_id)
    terminals = [event for event in owned if event.get("kind") in TERMINAL_KINDS]
    if not terminals:
        return {"status": "active", "interrupted": False, "cancelled": False,
                "interrupted_run_id": None, "last_terminal_sequence": None}
    last = terminals[-1]
    if last.get("kind") == COMPLETED:
        return {"status": "completed", "interrupted": False, "cancelled": False,
                "interrupted_run_id": None, "last_terminal_sequence": last.get("sequence")}
    cancelled = last.get("kind") == "session.cancelled"
    run_id = last.get("payload", {}).get("run_id") if isinstance(last.get("payload"), dict) else None
    return {
        "status": CANCELLED if cancelled else INTERRUPTED,
        "interrupted": not cancelled,
        "cancelled": cancelled,
        "interrupted_run_id": run_id if isinstance(run_id, str) else None,
        "last_terminal_sequence": last.get("sequence"),
    }


def project_containment(
    events: object,
    *,
    session_id: str,
    trace_id: str,
    conversation_id: str | None = None,
    adapter_containment: object = None,
    step: object = None,
    receipts: object = None,
    authorization_current: bool = True,
    owner_matches: bool = True,
    workspace_matches: bool = True,
    budget_available: bool = True,
    attempt_ledger: object = None,
) -> dict:
    """One fail-closed, framework-neutral containment + recovery projection.

    ``step`` may declare ``{"idempotent": bool, "result_verifiable": bool}``. An
    absent or unknown step is treated as *not* safe, so the recovery is paused
    for the user rather than auto-retried.
    """

    loss = loss_from_trace(events, session_id, trace_id)
    latest = None
    if isinstance(adapter_containment, dict) and adapter_containment.get("contained"):
        candidate = adapter_containment.get("latest")
        if isinstance(candidate, dict):
            latest = candidate
    loss_cause = (latest or {}).get("loss_cause")
    if not isinstance(loss_cause, str) or loss_cause not in LOSS_CAUSES:
        loss_cause = "runtime-loss" if loss["interrupted"] else None

    ledger = attempt_ledger if isinstance(attempt_ledger, dict) else None
    attempts = ledger.get("attempts") if ledger else []
    if not isinstance(attempts, list):
        attempts = []
    step_map = step if isinstance(step, dict) else {}
    receipt_map = receipts if isinstance(receipts, dict) else {}

    recovery = None
    if loss["interrupted"] or loss["cancelled"]:
        decision = classify_recovery(
            cancelled=loss["cancelled"],
            authorization_current=authorization_current,
            owner_matches=owner_matches,
            workspace_matches=workspace_matches,
            budget_available=budget_available,
            success_receipt_present=bool(receipt_map.get("success")),
            receipt_queryable=bool(receipt_map.get("queryable")),
            step_declared_idempotent=bool(step_map.get("idempotent")),
            step_result_verifiable=bool(step_map.get("result_verifiable")),
            attempt_in_progress=bool(ledger and ledger_has_open_attempt(ledger)),
            attempts_used=len(attempts),
            previous_run_id=loss["interrupted_run_id"],
        )
        recovery = decision.view()

    return {
        "schema_version": CONTAINMENT_VERSION,
        # Public conversation identity, never the internal runtime session id.
        "session_id": conversation_id or session_id,
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "status": loss["status"],
        "loss_cause": loss_cause,
        "interrupted_run_id": (latest or {}).get("interrupted_run_id") or loss["interrupted_run_id"],
        "recovery": recovery,
        "attempts": [
            {"attempt": row.get("attempt"), "previous_run_id": row.get("previous_run_id"),
             "new_run_id": row.get("new_run_id"), "state": row.get("state")}
            for row in attempts if isinstance(row, dict)
        ],
        "public_history_preserved": True,
        "max_attempts": RECOVERY_ATTEMPT_MAX,
    }


def empty_ledger(session_id: str) -> dict:
    return {"schema_version": ATTEMPTS_SCHEMA_VERSION, "session_id": session_id,
            "max_attempts": RECOVERY_ATTEMPT_MAX, "attempts": []}


class RecoveryAttemptStore:
    """Bounded, append-only, file-locked recovery attempt ledger.

    The exclusive file lock makes exactly one concurrent recovery request the
    authoritative attempt; every other request observes the open attempt and is
    rejected without producing a second one.
    """

    def __init__(self, root: Path, *, now=time.time) -> None:
        self.root = Path(root)
        self.now = now

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.recovery-attempts.json"

    def _lock(self, session_id: str):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return (self.root / f"{session_id}.recovery-attempts.lock").open("a")

    def read(self, session_id: str) -> dict:
        try:
            value = json.loads(self._path(session_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return empty_ledger(session_id)
        return validate_attempt_ledger(value)

    def _save(self, session_id: str, ledger: dict) -> None:
        validate_attempt_ledger(ledger)
        payload = json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode()
        directory = self.root
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".recovery-attempts-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self._path(session_id))
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def begin(self, session_id: str, *, previous_run_id: str | None, new_run_id: str,
              generation: str, idempotency_key: str) -> dict:
        import fcntl

        with self._lock(session_id) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = self.read(session_id)
            if ledger_has_open_attempt(ledger):
                raise RecoveryConflict("a recovery attempt is already in progress")
            attempt = len(ledger["attempts"]) + 1
            if attempt > RECOVERY_ATTEMPT_MAX:
                raise RecoveryConflict("recovery attempts are exhausted")
            chained_previous = (ledger["attempts"][-1]["new_run_id"]
                                if ledger["attempts"] else previous_run_id)
            row = build_attempt(
                attempt=attempt, previous_run_id=chained_previous, new_run_id=new_run_id,
                generation=generation, idempotency_key=idempotency_key,
                state="in_progress", created_at=self.now(),
            )
            ledger = {**ledger, "attempts": [*ledger["attempts"], row]}
            self._save(session_id, ledger)
            return ledger

    def settle(self, session_id: str, *, attempt: int, state: str) -> dict:
        import fcntl

        if state not in {"settled", "failed"}:
            raise ValueError("invalid recovery attempt settlement")
        with self._lock(session_id) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = self.read(session_id)
            rows = ledger["attempts"]
            if not rows or rows[-1]["attempt"] != attempt:
                raise RecoveryConflict("no matching open recovery attempt")
            rows = [*rows[:-1], {**rows[-1], "state": state}]
            ledger = {**ledger, "attempts": rows}
            self._save(session_id, ledger)
            return ledger

    def guard(self, session_id: str, *, previous_run_id: str | None, idempotency_key: str,
              submit) -> dict:
        """Serialize one recovery submission under the attempt lock.

        ``submit`` is called at most once, only while no attempt is open, and the
        resulting run identity is recorded as the authoritative new attempt
        before the lock is released. Concurrent callers therefore never produce
        a second attempt.
        """

        import fcntl

        with self._lock(session_id) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = self.read(session_id)
            if ledger_has_open_attempt(ledger):
                raise RecoveryConflict("a recovery attempt is already in progress")
            attempt = len(ledger["attempts"]) + 1
            if attempt > RECOVERY_ATTEMPT_MAX:
                raise RecoveryConflict("recovery attempts are exhausted")
            # Lineage is chained from the previous attempt, never forked.
            chained_previous = (ledger["attempts"][-1]["new_run_id"]
                                if ledger["attempts"] else previous_run_id)
            new_run_id = submit()
            row = build_attempt(
                attempt=attempt, previous_run_id=chained_previous, new_run_id=new_run_id,
                generation=new_run_id, idempotency_key=idempotency_key,
                state="in_progress", created_at=self.now(),
            )
            ledger = {**ledger, "attempts": [*ledger["attempts"], row]}
            self._save(session_id, ledger)
            return ledger
