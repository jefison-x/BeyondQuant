#!/usr/bin/env python3
"""Exceptional explicit lifecycle-journal executor re-anchor (ADR-0079).

ADR-0079 replaced the boot-bound lease with a stable executor identity and a
monotonic epoch, so normal process/container restart and host reboot never make
a journal stale. This operator tool is now the EXCEPTIONAL repair path only:

  * legacy v3 boot-bound journals that must be adopted onto the stable identity;
  * executor identity corruption or disaster recovery;
  * an explicit takeover that advanced the epoch and fenced old-epoch journals.

It rewrites ONLY the executor binding (``executor_identity``/``executor_epoch``
and the derived ``lease_identity``) and leaves the journal's sequence, events,
prompts, terminal acknowledgements, private call evidence and context untouched.
Legacy v3 journals are migrated to v4 in the same step.

Invariants:
  * Audit-first: without ``--apply`` nothing is mutated.
  * Explicit selection: ``--apply`` requires one or more ``--session-id`` (or
    ``--session-file`` lines); there is no implicit mass re-anchor.
  * Fail closed: only boot-stale (``stale``) and stable (``stable``) journals are
    repairable. An ``active`` (live owner), ``current`` (no-op), ``unprovable``
    or ``archived`` selection aborts the whole run before any mutation. The
    stored lease observed during inventory must still match at apply time, so a
    concurrently changed lease is never blind-overwritten.
  * Reversible: an ``audit.json`` plus ``manifest.json`` record every old and new
    lease identity and both journal sha256 values; the per-session audit is also
    committed beside the journal by the adapter.
  * No deletion, no domain mutation: this tool never removes files and never
    writes business/database rows.
  * Idempotent: re-running after a completed re-anchor is a no-op.

The Gateway stores no lease-bound state: ``TraceStore`` is keyed by session id
and ordered by ``sequence``, and the lifecycle delivery ledger stores only a
cursor over those sequences. Re-anchoring preserves the sequence, so no Gateway
cursor or ledger needs to be refreshed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/runtime-adapter"))

import archive_stale_sessions as archive  # noqa: E402  (read-only inventory)
from app.lifecycle_journal import (  # noqa: E402
    JournalBusy,
    LeaseReanchorConflict,
    LifecycleJournal,
)


SCHEMA_VERSION = "byq-session-lease-reanchor.v1"
DEFAULT_ARCHIVE_NAME = "byq-lease-reanchor"
TIMESTAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z")
MUTABLE = "stale"
STABLE = "stable"
NOOP = "current"


class ReanchorError(RuntimeError):
    """The re-lease cannot proceed safely."""


def read_selection(session_ids: list[str], session_files: list[Path]) -> list[str]:
    """Return the explicit, de-duplicated session selection in stable order."""

    selected: list[str] = []
    for session_id in session_ids:
        if session_id not in selected:
            selected.append(session_id)
    for session_file in session_files:
        for raw in Path(session_file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line not in selected:
                selected.append(line)
    return selected


def load_boot_id() -> str:
    try:
        return archive.read_boot_id()
    except archive.ArchiveError as exc:  # pragma: no cover - mirrors inventory
        raise ReanchorError(str(exc)) from exc


def inventory(
    session_ids: list[str],
    *,
    session_root: Path,
    trace_root: Path,
    boot_id: str,
    archive_name: str,
) -> list[dict]:
    """Read-only inventory. Enumerates every session when none is selected."""

    evidence_root = session_root / "byq-lifecycle-evidence"
    if not evidence_root.is_dir():
        raise ReanchorError(f"lifecycle evidence root not found: {evidence_root}")
    if session_ids:
        return [
            archive.inventory_session(
                session_id, evidence_root=evidence_root, session_root=session_root,
                trace_root=trace_root, boot_id=boot_id,
            )
            for session_id in session_ids
        ]
    return archive.enumerate_sessions(
        session_root=session_root, trace_root=trace_root, boot_id=boot_id,
        archive_name=archive_name,
    )


def plan(entries: list[dict]) -> list[dict]:
    """Pure selection check. Aborts before any mutation on an unsafe class."""

    unsafe = [
        entry for entry in entries
        if entry["classification"] not in {MUTABLE, STABLE, NOOP}
    ]
    if unsafe:
        detail = "; ".join(
            f"{entry['session_id']}={entry['classification']} ({entry['reason']})"
            for entry in unsafe
        )
        raise ReanchorError(f"refusing to re-lease sessions that are not repairable: {detail}")
    return [entry for entry in entries if entry["classification"] in {MUTABLE, STABLE}]


def apply_reanchor(entries: list[dict], session_root: Path) -> tuple[list[dict], list[str]]:
    """Re-anchor exactly the repairable entries via the adapter primitive.

    A per-session failure is recorded as ``error`` (never a blind overwrite) and
    reported so the operator re-runs; already-current sessions are idempotent.
    """

    evidence_root = session_root / "byq-lifecycle-evidence"
    results: list[dict] = []
    failures: list[str] = []
    for entry in entries:
        try:
            result = LifecycleJournal.reanchor_lease(
                evidence_root, entry["session_id"],
                expected_stored_lease=entry["stored_lease_identity"],
            )
        except (FileNotFoundError, JournalBusy, LeaseReanchorConflict, OSError, ValueError) as exc:
            failures.append(entry["session_id"])
            result = {"status": "error", "error": type(exc).__name__,
                      "previous_lease_identity": entry["stored_lease_identity"],
                      "current_lease_identity": entry["current_lease_identity"],
                      "previous_journal_sha256": None, "journal_sha256": None,
                      "audit_path": None, "changed": False}
        results.append({
            "session_id": entry["session_id"],
            **result,
            "owner": entry.get("owner"),
            "workspace_id": entry.get("workspace_id"),
            "conversation": entry.get("conversation"),
            "conversation_lookup": entry.get("conversation_lookup", "not_configured"),
            "trace_path": entry.get("trace_path"),
        })
    return results, failures


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_outputs(
    output_root: Path, *, results: list[dict],
    boot_id: str, timestamp: str, session_root: Path, trace_root: Path,
) -> dict:
    manifest_path = output_root / "manifest.json"
    if output_root.exists():
        raise ReanchorError(
            f"output directory {output_root} already exists; refusing to overwrite")

    audit = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": timestamp,
        "boot_id": boot_id,
        "session_root": str(session_root),
        "trace_root": str(trace_root),
        "sessions": results,
        "database_rows_modified": False,
        "production_data_deleted": False,
        "reversible": True,
        "gateway_lease_binding": "none",
        "gateway_note": (
            "TraceStore is keyed by session id and ordered by sequence; the "
            "lifecycle delivery ledger stores only a cursor over those "
            "sequences. Re-leasing preserves sequence, so no Gateway cursor, "
            "ledger or trace file requires refreshing."
        ),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": timestamp,
        "boot_id": boot_id,
        "session_root": str(session_root),
        "trace_root": str(trace_root),
        "output_root": str(output_root),
        "database_rows_modified": False,
        "production_data_deleted": False,
        "reversible": True,
        "sessions": [
            {
                "session_id": result["session_id"],
                "status": result["status"],
                "previous_lease_identity": result["previous_lease_identity"],
                "current_lease_identity": result["current_lease_identity"],
                "previous_journal_sha256": result["previous_journal_sha256"],
                "journal_sha256": result["journal_sha256"],
                "audit_path": result["audit_path"],
                "owner": result.get("owner"),
                "workspace_id": result.get("workspace_id"),
                "conversation": result.get("conversation"),
                "conversation_lookup": result.get("conversation_lookup", "not_configured"),
            }
            for result in results
        ],
    }
    _write_json(output_root / "audit.json", audit)
    _write_json(manifest_path, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="rewrite the stable executor binding (default: audit only)")
    parser.add_argument("--session-root", type=Path,
                        default=Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions")))
    parser.add_argument("--trace-root", type=Path,
                        default=Path(os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces")))
    parser.add_argument("--session-id", action="append", default=[],
                        help="explicit session id to re-lease; repeatable")
    parser.add_argument("--session-file", action="append", type=Path, default=[],
                        help="file of session ids, one per line; repeatable")
    parser.add_argument("--archive-name", default=DEFAULT_ARCHIVE_NAME)
    parser.add_argument("--timestamp", default=None,
                        help="output timestamp (default: current UTC, YYYYMMDDTHHMMSSZ)")
    args = parser.parse_args(argv)

    if archive.SESSION_ID.fullmatch(args.archive_name) is None:
        parser.error("--archive-name must be an archive-safe identifier")
    session_root = args.session_root.expanduser().resolve()
    trace_root = args.trace_root.expanduser().resolve()
    if not session_root.is_dir():
        parser.error(f"--session-root is not a directory: {session_root}")
    for session_file in args.session_file:
        if not session_file.is_file():
            parser.error(f"--session-file is not a file: {session_file}")

    selected = read_selection(args.session_id, args.session_file)
    if args.apply and not selected:
        parser.error("--apply requires explicit --session-id or --session-file selection")
    timestamp = args.timestamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if TIMESTAMP.fullmatch(timestamp) is None:
        parser.error("--timestamp must match YYYYMMDDTHHMMSSZ")

    try:
        boot_id = load_boot_id()
        entries = inventory(
            selected, session_root=session_root, trace_root=trace_root,
            boot_id=boot_id, archive_name=args.archive_name,
        )
        repairable = plan(entries)
    except (ReanchorError, archive.ArchiveError) as exc:
        print(json.dumps({"error": str(exc), "database_rows_modified": False}))
        return 2

    summary = {
        "mode": "apply" if args.apply else "audit",
        "boot_id": boot_id,
        "session_root": str(session_root),
        "trace_root": str(trace_root),
        "gateway_lease_binding": "none",
        "database_rows_modified": False,
        "counts": {
            "selected": len(entries),
            "repairable": len(repairable),
            "stale": sum(1 for e in entries if e["classification"] == MUTABLE),
            "current": sum(1 for e in entries if e["classification"] == NOOP),
            "stable": sum(1 for e in entries if e["classification"] == STABLE),
            "unprovable": sum(1 for e in entries if e["classification"] == "unprovable"),
            "archived": sum(1 for e in entries if e["classification"] == "archived"),
        },
        "sessions": entries,
    }
    if not args.apply:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    output_root = session_root / args.archive_name / timestamp
    manifest_path = output_root / "manifest.json"
    if output_root.exists():
        if not manifest_path.is_file():
            print(json.dumps({
                "error": f"output directory {output_root} exists without a manifest; refusing to overwrite",
                "database_rows_modified": False,
            }))
            return 2
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary["mode"] = "already_reanchored"
        summary["output_root"] = str(output_root)
        summary["manifest"] = str(manifest_path)
        summary["results"] = manifest.get("sessions", [])
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    try:
        results, failures = apply_reanchor(repairable, session_root)
        manifest = write_outputs(
            output_root, results=results, boot_id=boot_id, timestamp=timestamp,
            session_root=session_root, trace_root=trace_root,
        )
    except (ReanchorError, archive.ArchiveError, OSError) as exc:
        print(json.dumps({"error": str(exc), "database_rows_modified": False}))
        return 2

    summary["mode"] = "reanchored" if not failures else "partial"
    summary["output_root"] = str(output_root)
    summary["audit"] = str(output_root / "audit.json")
    summary["manifest"] = str(output_root / "manifest.json")
    summary["failures"] = failures
    summary["results"] = manifest.get("sessions", [])
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
