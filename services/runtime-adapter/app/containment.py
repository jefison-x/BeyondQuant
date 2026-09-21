"""ADR-0084 BYQ-owned containment evidence; never business state or DSH state.

When an execution owner is lost, the affected incomplete run must be terminated
as ``interrupted`` deterministically, and that fact must be auditable. This is a
bounded, fenced, BYQ-owned evidence ledger -- analogous to the generation ledger.
It stores no DSH session id, prompt, reasoning, tool payload or secret, and it is
never the authority for business state (conversation, authorization, approval,
artifacts, jobs, receipts, budget, cancel) which remains in the Domain Plane.

Every write is fenced by the authoritative executor epoch and by the
generation/attempt the loss belongs to, so an old-generation writer, a late
terminal settlement, a duplicate settlement or a terminal-reopen attempt fails
closed and cannot overwrite a newer generation's containment record.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from packages.contracts.session_failure_containment import (
    BOUNDARY_INVARIANT,
    CONTAINMENT_VERSION,
    FencedWrite,
    assert_terminal_settlement,
    validate_containment_record,
)

from . import executor_identity
from .executor_identity import ExecutorIdentity, ExecutorIdentityError

CONTAINMENT_DIRECTORY = "containment"
MAX_CONTAINMENT_RECORDS = 32


class ContainmentConflict(ValueError):
    """Containment evidence is unreadable, conflicting or cannot be attested."""


def _directory(evidence_root: Path) -> Path:
    return Path(evidence_root) / CONTAINMENT_DIRECTORY


def path(evidence_root: Path, session_id: str) -> Path:
    return _directory(evidence_root) / f"{session_id}.json"


def read(evidence_root: Path, session_id: str) -> list[dict]:
    """Read the bounded containment history; corruption fails closed."""

    target = path(evidence_root, session_id)
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ContainmentConflict(f"containment evidence is unreadable: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContainmentConflict("containment evidence is not valid JSON") from exc
    if (not isinstance(value, dict) or value.get("schema_version") != CONTAINMENT_VERSION
            or not isinstance(value.get("records"), list)):
        raise ContainmentConflict("containment evidence has an invalid schema")
    records = []
    for item in value["records"]:
        try:
            records.append(validate_containment_record(item))
        except ValueError as exc:
            raise ContainmentConflict("containment evidence has an invalid record") from exc
    return records[-MAX_CONTAINMENT_RECORDS:]


def _persist(evidence_root: Path, session_id: str, records: list[dict]) -> None:
    directory = _directory(evidence_root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = path(evidence_root, session_id)
    payload = json.dumps(
        {"schema_version": CONTAINMENT_VERSION, "session_id": session_id,
         "records": records[-MAX_CONTAINMENT_RECORDS:]},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    fd, name = tempfile.mkstemp(prefix=".containment-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def record_loss(
    evidence_root: Path,
    *,
    context: dict,
    executor: ExecutorIdentity | None,
    loss_cause: str,
    interrupted_run_id: str | None,
    interrupted_generation: str,
    attempt: int,
    recorded_at: float,
) -> list[dict]:
    """Persist one fenced loss/containment fact.

    Fails closed (``FencedWrite``) when the caller's executor epoch is stale, when
    the generation/attempt is behind the authoritative record, or when this
    attempt already has a terminal. An identical re-observation is an idempotent
    no-op so a retried containment does not fabricate a second fact.
    """

    evidence_root = Path(evidence_root)
    identity = executor if executor is not None else executor_identity.resolve(evidence_root)
    record = validate_containment_record({
        "schema_version": CONTAINMENT_VERSION,
        "conversation_id": context.get("conversation_id"),
        "session_id": context["session_id"],
        "trace_id": context["trace_id"],
        "owner_principal": context["owner"],
        "workspace_id": context["workspace_id"],
        "loss_cause": loss_cause,
        "interrupted_run_id": interrupted_run_id,
        "interrupted_generation": interrupted_generation,
        "executor_epoch": identity.executor_epoch,
        "attempt": attempt,
        # Boundary assertion only: the execution boundary does not modify durable
        # business state. This is not observed business evidence; the Gateway and
        # Domain independently verify actual preservation.
        "boundary_invariant": BOUNDARY_INVARIANT,
        "recorded_at": recorded_at,
    })
    with executor_identity.epoch_lock(evidence_root, exclusive=False):
        # Hold the epoch shared lock across fence-check and persistence so an
        # explicit takeover can never complete in the window between them.
        executor_identity.assert_write_allowed_locked(
            evidence_root, identity.deployment_id, identity.executor_epoch)
        records = read(evidence_root, context["session_id"])
        existing = next((item for item in records if item["attempt"] == attempt), None)
        if existing is not None:
            comparable = {key: value for key, value in record.items() if key != "recorded_at"}
            stored = {key: value for key, value in existing.items() if key != "recorded_at"}
            if stored == comparable:
                return records
            raise FencedWrite("containment attempt already has a terminal settlement")
        settled = {item["attempt"]: "interrupted" for item in records}
        assert_terminal_settlement(settled=settled, write_attempt=attempt, write_terminal="interrupted")
        records.append(record)
        _persist(evidence_root, context["session_id"], records)
        return records


def latest(evidence_root: Path, session_id: str) -> dict | None:
    records = read(evidence_root, session_id)
    return records[-1] if records else None
