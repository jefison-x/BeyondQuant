"""ADR-0079 R2: bounded, BYQ-owned RuntimeGeneration history.

A durable AgentSession can outlive generation-1..N. The lifecycle journal stays
the execution-evidence record (ownership / root lifecycle / prompt identity /
terminal receipt / domain-call evidence / sequence) and MUST NOT grow a second
DSH session/context store. This ledger is deliberately narrower: it records only
the framework-neutral facts that a generation existed, which BYQ-owned epoch it
ran under, when it started/ended and with which root. It never stores a DSH
session id, prompt, reasoning, tool payload or secret.

The ledger is best effort: a failure to write it must never block or fail a
model run. Callers therefore treat write errors as non-fatal.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

LEDGER_SCHEMA_VERSION = "byq-runtime-generations.v1"
LEDGER_DIRECTORY = "generation-ledger"
MAX_GENERATIONS = 32
_KEYS = {"generation_id", "executor_epoch", "root_run_id", "state", "started_at", "ended_at"}


def _directory(evidence_root: Path) -> Path:
    return Path(evidence_root) / LEDGER_DIRECTORY


def path(evidence_root: Path, session_id: str) -> Path:
    return _directory(evidence_root) / f"{session_id}.json"


def read(evidence_root: Path, session_id: str) -> list[dict]:
    """Read the bounded generation history; corrupt/absent reads as empty."""

    try:
        raw = path(evidence_root, session_id).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if (not isinstance(value, dict) or value.get("schema_version") != LEDGER_SCHEMA_VERSION
            or not isinstance(value.get("generations"), list)):
        return []
    rows = []
    for item in value["generations"]:
        if isinstance(item, dict) and set(item) == _KEYS:
            rows.append(item)
    return rows[-MAX_GENERATIONS:]


def _write(evidence_root: Path, session_id: str, generations: list[dict]) -> None:
    directory = _directory(evidence_root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = path(evidence_root, session_id)
    payload = json.dumps(
        {"schema_version": LEDGER_SCHEMA_VERSION, "session_id": session_id,
         "generations": generations[-MAX_GENERATIONS:]},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    fd, name = tempfile.mkstemp(prefix=".generations-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def begin(evidence_root: Path, session_id: str, *, generation_id: str, executor_epoch: int,
          root_run_id: str | None, started_at: float) -> list[dict]:
    """Record a new generation; replacing the same id is idempotent."""

    generations = [row for row in read(evidence_root, session_id) if row["generation_id"] != generation_id]
    generations.append({
        "generation_id": generation_id,
        "executor_epoch": int(executor_epoch),
        "root_run_id": root_run_id,
        "state": "starting",
        "started_at": float(started_at),
        "ended_at": None,
    })
    _write(evidence_root, session_id, generations)
    return generations


def end(evidence_root: Path, session_id: str, *, generation_id: str, state: str,
        ended_at: float) -> list[dict] | None:
    """Mark one generation terminal; a missing generation is a no-op."""

    generations = read(evidence_root, session_id)
    changed = False
    for row in generations:
        if row["generation_id"] == generation_id and row["ended_at"] is None:
            row["state"] = state
            row["ended_at"] = float(ended_at)
            changed = True
    if changed:
        _write(evidence_root, session_id, generations)
        return generations
    return generations or None


def reconcile(evidence_root: Path, session_id: str, *, interrupted_generation: str | None,
              ended_at: float) -> list[dict]:
    """Close every open generation after a process restart.

    The generation named by the recovered lost open root is truthfully marked
    ``interrupted``; any other still-open generation is marked ``closed`` because
    its process is gone. The session identity and evidence are untouched.
    """

    generations = read(evidence_root, session_id)
    changed = False
    for row in generations:
        if row["ended_at"] is not None:
            continue
        row["state"] = "interrupted" if row["generation_id"] == interrupted_generation else "closed"
        row["ended_at"] = float(ended_at)
        changed = True
    if changed:
        _write(evidence_root, session_id, generations)
    return generations
