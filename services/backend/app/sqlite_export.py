"""Read-only SQLite domain export for the ADR-0016 SQLite -> PostgreSQL migration.

The export is strictly read-only (``mode=ro``): the Community / legacy SQLite
file is never modified. It produces canonical, JSON-serializable row data plus a
deterministic manifest (row counts + fingerprints) used by the import and
post-import verification steps. This module is also the ADR-0013-style
"read-only export -> validation -> manifest" head of the pipeline.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

from .db import Engine  # noqa: F401  (re-exported for convenience)


SCHEMA_VERSION = "1"

# Every BYQ domain table in the single SQLite domain database. Column names and
# table names match the PostgreSQL store DDLs exactly (ADR-0016 translations).
DOMAIN_TABLES: list[str] = [
    "research_tasks",
    "experiments",
    "artifacts",
    "research_transitions",
    "agent_runs",
    "agent_audit",
    "agent_approvals",
    "learning_runs",
    "learning_iterations",
    "evaluation_signals",
    "lessons",
    "learning_history",
    "engineering_tasks",
    "engineering_history",
    "paper_accounts",
    "stock_pools",
    "paper_positions",
    "paper_orders",
    "paper_fills",
    "users",
    "auth_sessions",
    "user_agent_policy",
    "backtest_jobs",
]

# Columns that were stored as JSON TEXT in SQLite and become JSONB in PG.
JSON_COLUMNS: set[tuple[str, str]] = {
    ("stock_pools", "weights_json"),
    ("stock_pools", "symbols_json"),
    ("stock_pools", "provenance_json"),
    ("backtest_jobs", "request_json"),
    ("backtest_jobs", "input_manifest_json"),
    ("backtest_jobs", "result_reference_json"),
    ("backtest_jobs", "summary_json"),
    ("agent_audit", "detail_json"),
    ("engineering_tasks", "architecture_evidence_json"),
    ("learning_runs", "budget_json"),
    ("learning_runs", "stopping_rules_json"),
    ("learning_runs", "lineage_json"),
    ("learning_iterations", "feedback_json"),
    ("learning_iterations", "source_refs_json"),
    ("learning_iterations", "result_refs_json"),
    ("evaluation_signals", "lineage_json"),
    ("lessons", "content_json"),
    ("lessons", "evidence_json"),
    ("lessons", "validation_json"),
    ("experiments", "input_snapshot"),
    ("artifacts", "content"),
    ("artifacts", "lineage"),
    ("research_transitions", "result_json"),
}

# Columns stored as INTEGER 0/1 in SQLite and BOOLEAN in PG.
BOOLEAN_COLUMNS: set[tuple[str, str]] = {
    ("user_agent_policy", "automation_enabled"),
    ("user_agent_policy", "paused"),
    ("engineering_tasks", "self_review"),
}

# Child-table foreign keys (child column -> parent table/column). Used to
# quarantine orphaned rows instead of letting the PostgreSQL FK constraint fail
# the whole migration. Nullable child values (e.g. artifacts.experiment_id) are
# skipped.
FOREIGN_KEYS: dict[str, list[tuple[str, str, str]]] = {
    "auth_sessions": [("user_id", "users", "user_id")],
    "experiments": [("task_id", "research_tasks", "task_id")],
    "artifacts": [
        ("task_id", "research_tasks", "task_id"),
        ("experiment_id", "experiments", "experiment_id"),
    ],
    "agent_audit": [("run_id", "agent_runs", "run_id")],
    "agent_approvals": [("run_id", "agent_runs", "run_id")],
    "learning_iterations": [("learning_run_id", "learning_runs", "learning_run_id")],
    "engineering_history": [("task_id", "engineering_tasks", "task_id")],
}


_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+_[0-9a-f]{32}$")
_PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_SYMBOL_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")

_ID_COLUMNS = {
    "task_id", "experiment_id", "artifact_id", "run_id", "audit_id", "approval_id",
    "learning_run_id", "iteration_id", "signal_id", "lesson_id", "history_id",
    "account_id", "pool_id", "order_id", "fill_id", "user_id", "job_id",
    "parent_run_id", "source_artifact_id",
}
_TIMESTAMP_COLUMNS = {
    "created_at", "updated_at", "last_login_at", "password_changed_at", "expires_at",
    "finished_at", "last_buy_date",
}


def export_sqlite(sqlite_path: str | Path) -> dict[str, Any]:
    """Read-only export of every domain table to canonical JSON-serializable data.

    Returns ``{"schema_version", "source", "tables": {table: {"columns", "rows"}}}``.
    Raises ``ExportError`` if the file cannot be opened read-only.
    """
    path = Path(sqlite_path).expanduser().resolve()
    uri = f"file:{path}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        raise ExportError(f"cannot open SQLite database read-only: {error}") from error
    try:
        connection.row_factory = sqlite3.Row
        tables: dict[str, Any] = {}
        for table in DOMAIN_TABLES:
            if not _table_exists(connection, table):
                continue
            columns = [
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            ]
            rows = [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"').fetchall()]
            tables[table] = {"columns": columns, "rows": rows}
        return {
            "schema_version": SCHEMA_VERSION,
            "source": {"engine": "sqlite", "path": str(path), "read_only": True},
            "tables": tables,
        }
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


class ExportError(RuntimeError):
    pass


class ValidationError(ValueError):
    pass


def _valid_id(value: object, *, column: str) -> bool:
    return isinstance(value, str) and bool(_ID_PATTERN.fullmatch(value)) and column in _ID_COLUMNS


def _valid_principal(value: object) -> bool:
    return isinstance(value, str) and bool(_PRINCIPAL_PATTERN.fullmatch(value))


def _valid_symbol(value: object) -> bool:
    return isinstance(value, str) and bool(_SYMBOL_PATTERN.fullmatch(value))


def _valid_trade_date(value: object) -> bool:
    return isinstance(value, str) and bool(_TRADE_DATE_PATTERN.fullmatch(value))


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_PATTERN.fullmatch(value))


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _valid_timestamp(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        from datetime import datetime
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _valid_json_text(value: object, *, table: str, column: str) -> bool:
    if value is None:
        return (table, column) not in JSON_COLUMNS
    if not isinstance(value, str):
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, (dict, list))


def _valid_symbols_json(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(parsed, list)
        and bool(parsed)
        and all(isinstance(item, str) and bool(_SYMBOL_PATTERN.fullmatch(item)) for item in parsed)
    )


def validate_row(table: str, row: dict[str, Any]) -> list[str]:
    """Return a list of validation problems for one exported row (empty = valid)."""
    problems: list[str] = []
    for column, value in row.items():
        if column in _ID_COLUMNS:
            if value is not None and not _valid_id(value, column=column):
                problems.append(f"{table}.{column}: invalid id")
        elif column in {"owner_principal", "actor_principal", "decision_by", "reviewer_principal"}:
            if value is not None and not _valid_principal(value):
                problems.append(f"{table}.{column}: invalid principal")
        elif column == "symbol":
            if value is not None and not _valid_symbol(value):
                problems.append(f"{table}.symbol: invalid canonical symbol")
        elif column == "trade_date":
            if value is not None and not _valid_trade_date(value):
                problems.append(f"{table}.trade_date: invalid YYYYMMDD date")
        elif column == "content_sha256":
            if value is not None and not _valid_sha256(value):
                problems.append(f"{table}.content_sha256: invalid SHA-256")
        elif column in _TIMESTAMP_COLUMNS:
            if not _valid_timestamp(value):
                problems.append(f"{table}.{column}: invalid ISO timestamp")
        elif (table, column) in JSON_COLUMNS:
            if (table, column) == ("stock_pools", "symbols_json") and not _valid_symbols_json(value):
                problems.append(f"{table}.symbols_json: invalid canonical symbol list")
            elif not _valid_json_text(value, table=table, column=column):
                problems.append(f"{table}.{column}: invalid JSON content")
        elif column in {"cash", "price", "fees", "tax", "cash_delta", "value", "quantity",
                         "attempts", "max_attempts", "sequence", "iteration_index",
                         "attempt", "max_auto_executions_per_hour", "max_auto_failures_per_hour",
                         "draft_pr_number", "preferences_version", "row_count"}:
            if value is not None and not _finite_number(value):
                problems.append(f"{table}.{column}: non-finite number")
    return problems


def _key_set(valid_tables: dict[str, Any], table: str, column: str) -> set[Any]:
    data = valid_tables.get(table)
    if not data:
        return set()
    return {row.get(column) for row in data["rows"] if row.get(column) is not None}


def quarantine_orphans(valid_tables: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove child rows whose FK parent is absent from the valid export.

    Returns ``(cleaned_tables, quarantined_orphans)``. Orphans are reported and
    never silently repaired or inserted (they would violate the PG FK).
    """
    cleaned: dict[str, Any] = {
        table: {"columns": data["columns"], "rows": list(data["rows"])}
        for table, data in valid_tables.items()
    }
    quarantined: dict[str, Any] = {}
    for table, fks in FOREIGN_KEYS.items():
        data = valid_tables.get(table)
        if not data:
            continue
        keep: list[dict[str, Any]] = []
        bad: list[dict[str, Any]] = []
        for row in data["rows"]:
            orphaned = False
            for child_col, parent_table, parent_col in fks:
                value = row.get(child_col)
                if value is None:
                    continue
                if value not in _key_set(valid_tables, parent_table, parent_col):
                    bad.append({
                        "row": row,
                        "problems": [f"{table}.{child_col}: orphaned reference to {parent_table}.{parent_col}"],
                    })
                    orphaned = True
                    break
            if not orphaned:
                keep.append(row)
        if keep:
            cleaned[table] = {"columns": data["columns"], "rows": keep}
        if bad:
            quarantined[table] = bad
    return cleaned, quarantined


def quarantine_rows(export: dict[str, Any]) -> dict[str, Any]:
    """Split exported rows into valid rows and quarantined rows (never silently repaired).

    Invalid rows and FK orphans are quarantined and reported. Returns
    ``{"valid": <export-structure>, "quarantined": {table: [problem rows]}}``.
    """
    valid: dict[str, Any] = {}
    quarantined: dict[str, Any] = {}
    for table, data in export.get("tables", {}).items():
        valid_rows: list[dict[str, Any]] = []
        bad_rows: list[dict[str, Any]] = []
        for row in data["rows"]:
            problems = validate_row(table, row)
            if problems:
                bad_rows.append({"row": row, "problems": problems})
            else:
                valid_rows.append(row)
        if valid_rows:
            valid[table] = {"columns": data["columns"], "rows": valid_rows}
        if bad_rows:
            quarantined[table] = bad_rows
    cleaned, orphans = quarantine_orphans(valid)
    for table, rows in orphans.items():
        quarantined.setdefault(table, []).extend(rows)
    return {
        "valid": {
            "schema_version": export.get("schema_version"),
            "source": export.get("source"),
            "tables": cleaned,
        },
        "quarantined": quarantined,
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_manifest(export: dict[str, Any], *, source_sha256: str | None = None) -> dict[str, Any]:
    """Deterministic per-table manifest (row counts + content fingerprints).

    Rows are sorted by their canonical form before hashing so the fingerprint is
    independent of source row order and matches the PostgreSQL verification step.
    """
    tables: dict[str, Any] = {}
    for table, data in export.get("tables", {}).items():
        ordered = sorted(data["rows"], key=_canonical_bytes)
        fingerprint = hashlib.sha256(_canonical_bytes(ordered)).hexdigest()
        tables[table] = {"row_count": len(data["rows"]), "fingerprint": fingerprint}
    return {
        "schema_version": SCHEMA_VERSION,
        "tables": tables,
        "source_sha256": source_sha256,
    }
