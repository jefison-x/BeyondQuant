#!/usr/bin/env python3
"""Audit terminal signal-producer jobs and record a reversible manifest.

``signal_producer_jobs`` rows in a terminal state (``failed``, ``completed`` or
``cancelled``) accumulate in production. BYQ has **no supported domain archive
status for these rows**: the only archive mechanism is the owner/workspace-scoped
ML-strategy lifecycle (ADR-0050), which applies to ``ml_strategy_version``
artifacts, not to signal/backtest task rows. This operator tool therefore never
mutates domain data.

* Audit (default): read-only enumeration of terminal jobs, joined to their
  ``research_tasks`` and ``product_conversations``, printed as a JSON manifest.
* ``--manifest-out``: additionally record that manifest to a caller-provided path.
* ``--apply``: persist the manifest under a timestamped archive root. This is the
  least invasive correct action available: it is reversible (delete the archive
  directory) and touches no business table.

The tool does NOT delete, update, re-status or hide any ``signal_producer_jobs``
or ``research_tasks`` row. Removing a terminal job from Product listings requires
a domain/agent action through BeyondQuant MCP (or a future Accepted ADR); an ops
script must not invent a domain status or write business tables directly.

Invariants:
  * Database access is read-only (``connection.read_only = True``).
  * Only ``SELECT`` statements are issued; no INSERT/UPDATE/DELETE/DDL ever.
  * Non-destructive and fail closed: a manifest is only written on explicit
    ``--apply``/``--manifest-out``; an existing archive directory without a
    manifest is refused.
  * Idempotent: re-running ``--apply`` for the same archive directory is a no-op.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys


SCHEMA_VERSION = "byq-terminal-signal-job-archive.v1"
DEFAULT_ARCHIVE_NAME = "byq-terminal-signal-jobs"
TERMINAL_STATUSES: tuple[str, ...] = ("failed", "completed", "cancelled")
TIMESTAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z")
CONVERSATION_LINK_SCHEMA = "terminal-signal-job.v1"

# Closed read-only projection. The status filter is parameterised, never
# interpolated, and the join is LEFT so orphaned tasks never disappear from the
# audit. No column or table name is taken from user input.
TERMINAL_JOBS_QUERY = """
SELECT j.job_id, j.owner_principal, j.status, j.task_id,
       t.title AS task_title, t.conversation_id,
       j.strategy_version_artifact_id, j.stock_pool_snapshot_id,
       j.result_artifact_id, j.error_code, j.attempt_count,
       j.created_at, j.started_at, j.finished_at, j.updated_at,
       c.title AS conversation_title, c.status AS conversation_status,
       c.message_count AS conversation_message_count
FROM signal_producer_jobs j
LEFT JOIN research_tasks t ON t.task_id = j.task_id
LEFT JOIN product_conversations c ON c.conversation_id = t.conversation_id
WHERE j.status = ANY(%s)
{owner_clause}
ORDER BY j.updated_at, j.job_id
"""


class AuditError(RuntimeError):
    """The audit cannot proceed safely."""


def iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def validate_statuses(statuses: object) -> tuple[str, ...]:
    if not statuses:
        return TERMINAL_STATUSES
    if isinstance(statuses, str):
        requested = (statuses,)
    else:
        requested = tuple(statuses)
    unknown = sorted({str(item) for item in requested} - set(TERMINAL_STATUSES))
    if unknown:
        raise AuditError(f"unsupported status(es): {', '.join(unknown)}")
    return tuple(requested)


def build_query(*, owner: str | None = None) -> str:
    owner_clause = "  AND j.owner_principal = %s\n" if owner else ""
    return TERMINAL_JOBS_QUERY.format(owner_clause=owner_clause)


def build_entry(row: dict) -> dict:
    """Normalize one joined job row. Pure; no database access."""

    conversation_id = row.get("conversation_id")
    conversation = None
    if conversation_id is not None:
        conversation = {
            "conversation_id": conversation_id,
            "title": row.get("conversation_title"),
            "status": row.get("conversation_status"),
            "message_count": row.get("conversation_message_count"),
        }
    return {
        "schema_version": CONVERSATION_LINK_SCHEMA,
        "job_id": str(row["job_id"]),
        "owner_principal": row.get("owner_principal"),
        "status": row.get("status"),
        "task": {"task_id": row.get("task_id"), "title": row.get("task_title")},
        "conversation": conversation,
        "strategy_version_artifact_id": row.get("strategy_version_artifact_id"),
        "stock_pool_snapshot_id": row.get("stock_pool_snapshot_id"),
        "result_artifact_id": row.get("result_artifact_id"),
        "error_code": row.get("error_code"),
        "attempt_count": row.get("attempt_count"),
        "created_at": iso(row.get("created_at")),
        "started_at": iso(row.get("started_at")),
        "finished_at": iso(row.get("finished_at")),
        "updated_at": iso(row.get("updated_at")),
    }


def summarize(entries: list[dict]) -> dict:
    counts = {status: 0 for status in TERMINAL_STATUSES}
    linked = 0
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        if entry.get("conversation"):
            linked += 1
    return {
        "total": len(entries),
        "by_status": counts,
        "with_conversation": linked,
        "without_conversation": len(entries) - linked,
    }


def build_manifest(
    entries: list[dict], *, generated_at: str, database: str, owner: str | None,
) -> dict:
    """Build the reversible archive manifest. Pure; never touches the domain."""

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "database": database,
        "owner_filter": owner,
        "statuses": list(TERMINAL_STATUSES),
        "counts": summarize(entries),
        "database_rows_modified": False,
        "production_data_deleted": False,
        "domain_archive_mechanism": "unsupported_signal_jobs",
        "archive_requires_domain_action": True,
        "reversal": "delete this archive directory; no domain row was changed",
        "jobs": entries,
    }


def fetch_terminal_jobs(
    database_url: str, *, statuses: tuple[str, ...] = TERMINAL_STATUSES,
    owner: str | None = None,
) -> list[dict]:
    """Read-only enumeration. Never writes to the database."""

    if not database_url:
        raise AuditError("a database URL is required (--database-url or BYQ_DATABASE_URL)")
    chosen = validate_statuses(statuses)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise AuditError("psycopg is required to enumerate signal jobs") from exc
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    params: list[object] = [list(chosen)]
    if owner:
        params.append(owner)
    rows: list[dict] = []
    try:
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            connection.read_only = True
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(build_query(owner=owner), params)
                rows = list(cursor.fetchall())
    except Exception as exc:  # noqa: BLE001 - operator tool fails closed on any error
        raise AuditError(f"terminal-job audit failed; no data was modified: {type(exc).__name__}") from exc
    return [build_entry(row) for row in rows]


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(
    archive_root: Path, document: dict, *, timestamp: str,
) -> tuple[dict, str]:
    """Persist a reversible manifest. Idempotent; never mutates the database."""

    if TIMESTAMP.fullmatch(timestamp) is None:
        raise AuditError("timestamp must match YYYYMMDDTHHMMSSZ")
    target = Path(archive_root) / timestamp
    manifest_path = target / "manifest.json"
    if target.exists():
        if manifest_path.is_file():
            return json.loads(manifest_path.read_text(encoding="utf-8")), "already_archived"
        raise AuditError(f"archive directory {target} exists without a manifest; refusing to overwrite")
    target.mkdir(parents=True, mode=0o700)
    _write_json(manifest_path, document)
    return document, "manifest_written"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="persist the reversible manifest (default: audit only)")
    parser.add_argument("--archive-root", type=Path,
                        default=Path("/var/lib/byq/ops") / DEFAULT_ARCHIVE_NAME)
    parser.add_argument("--manifest-out", type=Path, default=None,
                        help="also record the audit manifest at this path")
    parser.add_argument("--timestamp", default=None,
                        help="archive timestamp (default: current UTC, YYYYMMDDTHHMMSSZ)")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--owner", default=None, help="optional owner_principal filter")
    parser.add_argument("--status", action="append", choices=TERMINAL_STATUSES, default=None,
                        help="restrict to a terminal status (repeatable)")
    args = parser.parse_args(argv)

    database_url = args.database_url
    if database_url and database_url.startswith("file:"):
        parser.error("--database-url must be a PostgreSQL DSN")
    if not database_url:
        import os
        database_url = os.environ.get("BYQ_DATABASE_URL")
    if not database_url:
        parser.error("--database-url or BYQ_DATABASE_URL is required")

    timestamp = args.timestamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if TIMESTAMP.fullmatch(timestamp) is None:
        parser.error("--timestamp must match YYYYMMDDTHHMMSSZ")
    statuses = validate_statuses(args.status) if args.status else TERMINAL_STATUSES

    try:
        entries = fetch_terminal_jobs(database_url, statuses=statuses, owner=args.owner)
    except AuditError as exc:
        print(json.dumps({"error": str(exc), "database_rows_modified": False}))
        return 2

    document = build_manifest(
        entries, generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        database="<redacted>", owner=args.owner,
    )
    summary = dict(document)
    summary["mode"] = "apply" if args.apply else "audit"

    if args.manifest_out is not None:
        try:
            args.manifest_out.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            _write_json(args.manifest_out, document)
        except OSError as exc:
            print(json.dumps({"error": f"cannot write manifest: {exc}",
                              "database_rows_modified": False}))
            return 2
        summary["manifest_out"] = str(args.manifest_out)

    if not args.apply:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    try:
        manifest, status = write_manifest(args.archive_root.expanduser().resolve(), document,
                                          timestamp=timestamp)
    except (AuditError, OSError) as exc:
        print(json.dumps({"error": str(exc), "database_rows_modified": False}))
        return 2
    summary["mode"] = status
    summary["archive_root"] = str(args.archive_root.expanduser().resolve() / timestamp)
    summary["manifest"] = str(args.archive_root.expanduser().resolve() / timestamp / "manifest.json")
    summary["jobs"] = len(manifest.get("jobs", []))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
