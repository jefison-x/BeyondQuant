#!/usr/bin/env python3
"""Archive runtime sessions whose lifecycle-journal lease predates this boot.

A lifecycle journal stores ``lease_identity = sha256(boot_id:st_dev:st_ino:token)``
where ``boot_id`` is ``/proc/sys/kernel/random/boot_id``. Because ``boot_id``
changes on every host reboot, a session written before a reboot can never be
re-claimed. The runtime-adapter surfaces that as an explicit ``409
stale_session_lease``; this operator tool removes the stale evidence from the
live roots without deleting anything.

Invariants:
  * Audit-first: without ``--apply`` nothing is mutated.
  * Reversible: files are MOVED into a timestamped archive tree and an archive
    manifest records every original path plus per-file sha256.
  * No domain mutation: ``product_conversations`` is read only. This tool never
    deletes or updates database rows.
  * Fail closed: malformed evidence is classified ``unprovable`` and never
    archived; an existing archive directory is never overwritten.
  * Idempotent: re-running after a completed archive is a no-op.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys


SCHEMA_VERSION = "byq-stale-session-archive.v1"
DEFAULT_ARCHIVE_NAME = "byq-stale-session-archive"
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
LEASE_HEX = re.compile(r"[0-9a-f]{64}")
TOKEN_HEX = re.compile(r"[0-9a-f]{32}")
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
JOURNAL_SCHEMA_VERSIONS = frozenset({
    "byq-lifecycle-journal.v1", "byq-lifecycle-journal.v2", "byq-lifecycle-journal.v3",
    "byq-lifecycle-journal.v4",
})
STABLE_EXECUTOR_KEYS = frozenset({"executor_identity", "executor_epoch"})
CONVERSATION_QUERY = (
    "SELECT conversation_id, owner_principal, title, status, message_count, created_at, updated_at "
    "FROM product_conversations WHERE runtime_session_id = %s"
)


class ArchiveError(RuntimeError):
    """The archive cannot proceed safely."""


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_boot_id(path: Path = BOOT_ID_PATH) -> str:
    try:
        value = Path(path).read_text(encoding="ascii").strip()
    except OSError as exc:
        raise ArchiveError(f"cannot read boot identity: {exc}") from exc
    if not value:
        raise ArchiveError("boot identity is empty")
    return value


def compute_lease_identity(boot_id: str, st_dev: int, st_ino: int, token: str) -> str:
    return hashlib.sha256(f"{boot_id}:{st_dev}:{st_ino}:{token}".encode()).hexdigest()


def read_journal_state(path: Path) -> dict:
    """Read and integrity-check a lifecycle journal without importing the adapter."""

    raw = Path(path).read_bytes()
    if len(raw) > MAX_JOURNAL_BYTES:
        raise ArchiveError("journal exceeds the recovery bound")
    envelope = json.loads(raw)
    if (not isinstance(envelope, dict)
            or set(envelope) != {"schema_version", "state", "sha256"}
            or envelope["schema_version"] not in JOURNAL_SCHEMA_VERSIONS):
        raise ArchiveError("invalid journal envelope")
    state = envelope["state"]
    if not isinstance(state, dict):
        raise ArchiveError("invalid journal state")
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    if envelope["sha256"] != hashlib.sha256(encoded).hexdigest():
        raise ArchiveError("journal integrity mismatch")
    return state


def lock_evidence(path: Path) -> dict | None:
    """Return the persisted owner token and lock inode identity, else None."""

    target = Path(path)
    if target.is_symlink():
        raise ArchiveError("owner lock cannot be a symlink")
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        stat = os.fstat(fd)
        token = os.read(fd, 128).decode("ascii", "replace").strip()
    finally:
        os.close(fd)
    return {"token": token, "st_dev": stat.st_dev, "st_ino": stat.st_ino}


def lock_is_held(path: Path) -> bool:
    target = Path(path)
    if target.is_symlink():
        raise ArchiveError("owner lock cannot be a symlink")
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def classify_lease(stored_identity: object, current_identity: object, *, lock_held: bool = False) -> str:
    if lock_held:
        return "active"
    if not isinstance(stored_identity, str) or LEASE_HEX.fullmatch(stored_identity) is None:
        return "unprovable"
    if not isinstance(current_identity, str) or LEASE_HEX.fullmatch(current_identity) is None:
        return "unprovable"
    return "current" if stored_identity == current_identity else "stale"


def _contained(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def inventory_session(
    session_id: str,
    *,
    evidence_root: Path,
    session_root: Path,
    trace_root: Path,
    boot_id: str,
    archived_ids: frozenset[str] = frozenset(),
) -> dict:
    """Classify one session from its journal and owner lock. Read-only."""

    entry: dict = {
        "session_id": session_id,
        "classification": "unprovable",
        "reason": "",
        "owner": None,
        "workspace_id": None,
        "trace_id": None,
        "journal_sequence": None,
        "stored_lease_identity": None,
        "current_lease_identity": None,
        "session_dir": None,
        "trace_path": None,
        "conversation": None,
    }
    if SESSION_ID.fullmatch(session_id) is None:
        entry["reason"] = "session id is not archive-safe"
        return entry
    if session_id in archived_ids:
        entry["classification"] = "archived"
        entry["reason"] = "session is already present in the archive root"
        return entry
    journal_path = evidence_root / f"{session_id}.json"
    lock_path = evidence_root / f"{session_id}.lock"
    entry["journal_path"] = str(journal_path)
    entry["lock_path"] = str(lock_path) if lock_path.exists() else None
    try:
        state = read_journal_state(journal_path)
    except FileNotFoundError:
        entry["reason"] = "journal disappeared during inventory"
        return entry
    except (OSError, ValueError, ArchiveError) as exc:
        entry["reason"] = f"journal unreadable: {exc}"
        return entry
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    entry["owner"] = context.get("owner")
    entry["workspace_id"] = context.get("workspace_id")
    entry["trace_id"] = context.get("trace_id")
    entry["journal_sequence"] = state.get("sequence")
    entry["stored_lease_identity"] = state.get("lease_identity")
    try:
        evidence = lock_evidence(lock_path)
    except ArchiveError as exc:
        entry["reason"] = str(exc)
        return entry
    if evidence is None:
        entry["reason"] = "owner lock identity is missing"
        return entry
    if TOKEN_HEX.fullmatch(evidence["token"]) is None:
        entry["reason"] = "owner lock token is invalid"
        return entry
    # ADR-0079: a v4 journal carries a stable, boot-independent executor lease.
    # It can never become boot-stale, so it is never a boot-reboot archive
    # candidate; only an explicit takeover or repair changes its identity.
    if STABLE_EXECUTOR_KEYS <= set(state):
        entry["current_lease_identity"] = entry["stored_lease_identity"]
        if lock_is_held(lock_path):
            entry["classification"] = "active"
            entry["reason"] = "stable executor lease owner lock is currently held by a live process"
        else:
            entry["classification"] = "stable"
            entry["reason"] = "stable executor lease is reboot-independent (ADR-0079)"
    else:
        entry["current_lease_identity"] = compute_lease_identity(
            boot_id, evidence["st_dev"], evidence["st_ino"], evidence["token"],
        )
        entry["classification"] = classify_lease(
            entry["stored_lease_identity"], entry["current_lease_identity"],
            lock_held=lock_is_held(lock_path),
        )
        if entry["classification"] == "stale":
            entry["reason"] = (
                "stored lease identity does not match the current boot identity "
                "(host reboot changed /proc/sys/kernel/random/boot_id)"
            )
        elif entry["classification"] == "current":
            entry["reason"] = "lease identity matches the current boot"
        elif entry["classification"] == "active":
            entry["reason"] = "owner lock is currently held by a live process"
    candidate_dir = session_root / session_id
    if candidate_dir.is_dir() and not candidate_dir.is_symlink() and _contained(candidate_dir, session_root):
        entry["session_dir"] = str(candidate_dir)
    candidate_trace = trace_root / f"{session_id}.ndjson"
    if candidate_trace.is_file() and not candidate_trace.is_symlink() and _contained(candidate_trace, trace_root):
        entry["trace_path"] = str(candidate_trace)
    return entry


def load_conversations(database_url: str | None, session_ids: list[str]) -> tuple[dict, str]:
    """Read-only conversation lookup. Never writes domain rows."""

    if not database_url:
        return {}, "not_configured"
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise ArchiveError("psycopg is required for --database-url lookups") from exc
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    conversations: dict = {}
    try:
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                for session_id in session_ids:
                    cursor.execute(CONVERSATION_QUERY, (session_id,))
                    row = cursor.fetchone()
                    if row is None:
                        continue
                    conversations[session_id] = {
                        "conversation_id": row[0],
                        "owner_principal": row[1],
                        "title": row[2],
                        "status": row[3],
                        "message_count": row[4],
                        "created_at": str(row[5]),
                        "updated_at": str(row[6]),
                    }
    except Exception as exc:  # noqa: BLE001 - operator tool fails closed on any lookup error
        raise ArchiveError(f"conversation lookup failed; no files were moved: {type(exc).__name__}") from exc
    return conversations, "read_only"


def attach_conversations(entries: list[dict], conversations: dict, database_status: str) -> None:
    for entry in entries:
        entry["conversation"] = conversations.get(entry["session_id"])
        entry["conversation_lookup"] = database_status


def plan_archive(
    entries: list[dict], *, archive_root: Path, gateway_archive_root: Path,
) -> list[dict]:
    """Pure move plan for stale sessions. No filesystem mutation."""

    moves: list[dict] = []
    for entry in entries:
        if entry["classification"] != "stale":
            continue
        session_id = entry["session_id"]
        session_archive = archive_root / session_id
        if entry.get("journal_path"):
            moves.append({
                "kind": "journal", "session_id": session_id,
                "source": entry["journal_path"],
                "destination": str(session_archive / "byq-lifecycle-evidence" / f"{session_id}.json"),
            })
        if entry.get("lock_path"):
            moves.append({
                "kind": "lock", "session_id": session_id,
                "source": entry["lock_path"],
                "destination": str(session_archive / "byq-lifecycle-evidence" / f"{session_id}.lock"),
            })
        if entry.get("session_dir"):
            moves.append({
                "kind": "session_dir", "session_id": session_id,
                "source": entry["session_dir"],
                "destination": str(session_archive / "dsh-session"),
            })
        if entry.get("trace_path"):
            moves.append({
                "kind": "trace", "session_id": session_id,
                "source": entry["trace_path"],
                "destination": str(gateway_archive_root / f"{session_id}.ndjson"),
            })
    return moves


def _file_record(path: Path) -> dict:
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def apply_archive(
    entries: list[dict], moves: list[dict], *,
    archive_root: Path, boot_id: str, timestamp: str,
    session_root: Path, trace_root: Path,
) -> tuple[dict, str]:
    """Move stale evidence into the archive and write the reversible manifest."""

    manifest_path = archive_root / "manifest.json"
    if archive_root.exists():
        if manifest_path.is_file():
            return json.loads(manifest_path.read_text(encoding="utf-8")), "already_archived"
        raise ArchiveError(
            f"archive directory {archive_root} exists without a manifest; refusing to overwrite",
        )
    # Pre-flight: every source must exist exactly once and stay under its root.
    seen: set[str] = set()
    for move in moves:
        source = Path(move["source"])
        if move["source"] in seen:
            raise ArchiveError(f"duplicate archive source: {move['source']}")
        seen.add(move["source"])
        if not source.exists():
            raise ArchiveError(f"archive source disappeared: {move['source']}")
        root = session_root if move["kind"] != "trace" else trace_root
        if not _contained(source, root):
            raise ArchiveError(f"archive source escapes its root: {move['source']}")
        if Path(move["destination"]).exists():
            raise ArchiveError(f"archive destination already exists: {move['destination']}")
    archive_root.mkdir(parents=True, mode=0o700)
    for move in moves:
        Path(move["destination"]).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": timestamp,
        "boot_id": boot_id,
        "session_root": str(session_root),
        "trace_root": str(trace_root),
        "archive_root": str(archive_root),
        "moves": moves,
    }
    (archive_root / "plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files: list[dict] = []
    for move in moves:
        source = Path(move["source"])
        destination = Path(move["destination"])
        if move["kind"] == "session_dir":
            shutil.move(str(source), str(destination))
            for archived in sorted(destination.rglob("*")):
                if archived.is_file():
                    files.append({
                        "session_id": move["session_id"],
                        "kind": move["kind"],
                        "original_path": str(source / archived.relative_to(destination)),
                        "archived_path": str(archived),
                        **_file_record(archived),
                    })
        else:
            moved = shutil.move(str(source), str(destination))
            archived = Path(moved)
            files.append({
                "session_id": move["session_id"],
                "kind": move["kind"],
                "original_path": move["source"],
                "archived_path": str(archived),
                **_file_record(archived),
            })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": timestamp,
        "boot_id": boot_id,
        "session_root": str(session_root),
        "trace_root": str(trace_root),
        "archive_root": str(archive_root),
        "database_rows_modified": False,
        "production_data_deleted": False,
        "reversible": True,
        "sessions": [
            {
                "session_id": entry["session_id"],
                "reason": entry["reason"],
                "stored_lease_identity": entry["stored_lease_identity"],
                "current_lease_identity": entry["current_lease_identity"],
                "owner": entry["owner"],
                "workspace_id": entry["workspace_id"],
                "conversation": entry["conversation"],
                "conversation_lookup": entry.get("conversation_lookup", "not_configured"),
            }
            for entry in entries
            if entry["classification"] == "stale"
        ],
        "files": files,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest, "archived"


def enumerate_sessions(
    *, session_root: Path, trace_root: Path, boot_id: str,
    archive_name: str,
) -> list[dict]:
    evidence_root = session_root / "byq-lifecycle-evidence"
    if not evidence_root.is_dir():
        raise ArchiveError(f"lifecycle evidence root not found: {evidence_root}")
    archived_ids: set[str] = set()
    for base in (session_root / archive_name, trace_root / archive_name):
        if base.is_dir():
            for archived in base.glob("*/*"):
                if archived.is_dir() and not archived.is_symlink():
                    archived_ids.add(archived.name)
    entries = []
    for journal in sorted(evidence_root.glob("*.json")):
        entries.append(inventory_session(
            journal.stem,
            evidence_root=evidence_root,
            session_root=session_root,
            trace_root=trace_root,
            boot_id=boot_id,
            archived_ids=frozenset(archived_ids),
        ))
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="move stale evidence into the archive (default: audit only)")
    parser.add_argument("--session-root", type=Path,
                        default=Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions")))
    parser.add_argument("--trace-root", type=Path,
                        default=Path(os.environ.get("BYQ_WORKFLOW_TRACE_ROOT", "/tmp/byq-workflow-traces")))
    parser.add_argument("--archive-name", default=DEFAULT_ARCHIVE_NAME)
    parser.add_argument("--timestamp", default=None,
                        help="archive timestamp (default: current UTC, YYYYMMDDTHHMMSSZ)")
    parser.add_argument("--database-url", default=os.environ.get("BYQ_DATABASE_URL"))
    args = parser.parse_args(argv)

    if SESSION_ID.fullmatch(args.archive_name) is None:
        parser.error("--archive-name must be an archive-safe identifier")
    session_root = args.session_root.expanduser().resolve()
    trace_root = args.trace_root.expanduser().resolve()
    if not session_root.is_dir():
        parser.error(f"--session-root is not a directory: {session_root}")
    if not trace_root.is_dir():
        parser.error(f"--trace-root is not a directory: {trace_root}")
    boot_id = read_boot_id()
    timestamp = args.timestamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", timestamp) is None:
        parser.error("--timestamp must match YYYYMMDDTHHMMSSZ")

    entries = enumerate_sessions(
        session_root=session_root, trace_root=trace_root, boot_id=boot_id,
        archive_name=args.archive_name,
    )
    try:
        conversations, database_status = load_conversations(
            args.database_url, [entry["session_id"] for entry in entries],
        )
    except ArchiveError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    attach_conversations(entries, conversations, database_status)

    stale = [entry for entry in entries if entry["classification"] == "stale"]
    summary = {
        "mode": "apply" if args.apply else "audit",
        "boot_id": boot_id,
        "session_root": str(session_root),
        "trace_root": str(trace_root),
        "database_lookup": database_status,
        "counts": {
            "total": len(entries),
            "stale": len(stale),
            "current": sum(1 for e in entries if e["classification"] == "current"),
            "stable": sum(1 for e in entries if e["classification"] == "stable"),
            "active": sum(1 for e in entries if e["classification"] == "active"),
            "unprovable": sum(1 for e in entries if e["classification"] == "unprovable"),
            "archived": sum(1 for e in entries if e["classification"] == "archived"),
        },
        "sessions": entries,
        "database_rows_modified": False,
    }

    if not args.apply:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    archive_root = session_root / args.archive_name / timestamp
    gateway_archive_root = trace_root / args.archive_name / timestamp
    moves = plan_archive(entries, archive_root=archive_root, gateway_archive_root=gateway_archive_root)
    try:
        manifest, status = apply_archive(
            entries, moves, archive_root=archive_root, boot_id=boot_id,
            timestamp=timestamp, session_root=session_root, trace_root=trace_root,
        )
    except (ArchiveError, OSError) as exc:
        print(json.dumps({"error": str(exc), "database_rows_modified": False}))
        return 2
    summary["mode"] = status
    summary["archive_root"] = str(archive_root)
    summary["gateway_archive_root"] = str(gateway_archive_root)
    summary["manifest"] = str(archive_root / "manifest.json")
    summary["moved_files"] = len(manifest.get("files", []))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
