"""Idempotent PostgreSQL import + verification for the ADR-0016 migration.

Takes the canonical export produced by ``sqlite_export``, adapts SQLite types to
the PostgreSQL store translations (JSON TEXT -> JSONB objects, INTEGER 0/1 ->
BOOLEAN), imports rows with an explicit conflict policy (never last-write-wins),
and verifies row counts + fingerprints against the manifest.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.engine import Engine

from .db import execute, fetch_one, transaction
from .sqlite_export import (
    BOOLEAN_COLUMNS,
    JSON_COLUMNS,
    _canonical_bytes,
)


PRIMARY_KEYS: dict[str, list[str]] = {
    "research_tasks": ["task_id"],
    "experiments": ["experiment_id"],
    "artifacts": ["artifact_id"],
    "research_transitions": ["entity_type", "entity_id", "idempotency_key"],
    "agent_runs": ["run_id"],
    "agent_audit": ["audit_id"],
    "agent_approvals": ["approval_id"],
    "learning_runs": ["learning_run_id"],
    "learning_iterations": ["iteration_id"],
    "evaluation_signals": ["signal_id"],
    "lessons": ["lesson_id"],
    "learning_history": ["history_id"],
    "engineering_tasks": ["task_id"],
    "engineering_history": ["history_id"],
    "paper_accounts": ["account_id"],
    "stock_pools": ["pool_id"],
    "paper_positions": ["account_id", "symbol"],
    "paper_orders": ["order_id"],
    "paper_fills": ["fill_id"],
    "users": ["user_id"],
    "auth_sessions": ["session_id"],
    "user_agent_policy": ["owner_principal"],
    "backtest_jobs": ["job_id"],
}

# Conflict policy values (ADR-0016/ADR-0013; never last-write-wins).
KEEP_NEW = "KEEP_NEW"
VERIFY_EQUAL = "VERIFY_EQUAL"
REPORT_MISMATCH = "REPORT_MISMATCH"
CONFLICT_POLICIES = {KEEP_NEW, VERIFY_EQUAL, REPORT_MISMATCH}


class ImportError_(RuntimeError):
    pass


def adapt_value(table: str, column: str, value: Any) -> Any:
    """Adapt one SQLite value to the PostgreSQL column translation."""
    if (table, column) in JSON_COLUMNS:
        if value is None:
            return value
        if isinstance(value, str):
            return json.loads(value)
        return value
    if (table, column) in BOOLEAN_COLUMNS:
        if value is None:
            return None
        return bool(value)
    return value


def adapt_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    return {column: adapt_value(table, column, value) for column, value in row.items()}


def adapt_export(export: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of an export with every row adapted to the PG translations."""
    tables: dict[str, Any] = {}
    for table, data in export.get("tables", {}).items():
        tables[table] = {
            "columns": data["columns"],
            "rows": [adapt_row(table, row) for row in data["rows"]],
        }
    return {
        "schema_version": export.get("schema_version"),
        "source": export.get("source"),
        "tables": tables,
    }


def _existing_pks(connection: Any, table: str, pk_columns: list[str]) -> set[tuple[Any, ...]]:
    """Return the set of existing primary keys for a table."""
    rows = execute(connection, f'SELECT {", ".join(pk_columns)} FROM "{table}"')
    return {tuple(row[column] for column in pk_columns) for row in rows}


def _canonical_row(row: dict[str, Any]) -> bytes:
    return _canonical_bytes({key: row[key] for key in sorted(row)})


def _fetch_existing(connection: Any, table: str, pk_columns: list[str], pk: tuple[Any, ...]) -> dict[str, Any] | None:
    where = " AND ".join(f'"{column}" = :{column}' for column in pk_columns)
    params = {column: value for column, value in zip(pk_columns, pk)}
    return fetch_one(connection, f'SELECT * FROM "{table}" WHERE {where}', params)


def import_table(
    connection: Any,
    table: str,
    data: dict[str, Any],
    *,
    conflict_policy: str = KEEP_NEW,
) -> dict[str, Any]:
    """Import one table's exported rows with the given conflict policy.

    Returns ``{"inserted", "kept", "reported", "mismatches": [...]}``.
    """
    pk_columns = PRIMARY_KEYS.get(table)
    if pk_columns is None:
        raise ImportError_(f"no primary key registered for table {table}")
    columns = data["columns"]
    existing = _existing_pks(connection, table, pk_columns)
    inserted = 0
    kept = 0
    mismatches: list[dict[str, Any]] = []
    for row in data["rows"]:
        adapted = adapt_row(table, row)
        pk = tuple(adapted[column] for column in pk_columns)
        if pk in existing:
            if conflict_policy == VERIFY_EQUAL:
                existing_row = _fetch_existing(connection, table, pk_columns, pk)
                if existing_row is not None and _canonical_row({k: existing_row[k] for k in columns if k in existing_row}) != _canonical_row(adapted):
                    mismatches.append({"table": table, "primary_key": dict(zip(pk_columns, pk)), "reason": "verify_equal_mismatch"})
                kept += 1
            elif conflict_policy == REPORT_MISMATCH:
                mismatches.append({"table": table, "primary_key": dict(zip(pk_columns, pk)), "reason": "conflict_reported"})
                kept += 1
            else:  # KEEP_NEW
                kept += 1
            continue
        insert_columns = [column for column in columns if column in _table_columns(connection, table)]
        placeholders = ", ".join(f":{column}" for column in insert_columns)
        params = {column: adapted[column] for column in insert_columns}
        execute(
            connection,
            f'INSERT INTO "{table}" ({", ".join(insert_columns)}) VALUES ({placeholders})',
            params,
        )
        existing.add(pk)
        inserted += 1
    return {"inserted": inserted, "kept": kept, "reported": len(mismatches), "mismatches": mismatches}


_TABLE_COLUMN_CACHE: dict[str, set[str]] = {}


def _table_columns(connection: Any, table: str) -> set[str]:
    cached = _TABLE_COLUMN_CACHE.get(table)
    if cached is not None:
        return cached
    rows = execute(
        connection,
        "SELECT column_name FROM information_schema.columns WHERE table_name = :table",
        {"table": table},
    )
    columns = {row["column_name"] for row in rows}
    _TABLE_COLUMN_CACHE[table] = columns
    return columns


def import_to_pg(engine: Engine, export: dict[str, Any], *, conflict_policy: str = KEEP_NEW) -> dict[str, Any]:
    """Import every exported table; returns a per-table report + mismatch list."""
    if conflict_policy not in CONFLICT_POLICIES:
        raise ValueError(f"conflict_policy must be one of {sorted(CONFLICT_POLICIES)}")
    report: dict[str, Any] = {"tables": {}, "mismatches": []}
    with transaction(engine) as connection:
        for table, data in export.get("tables", {}).items():
            table_report = import_table(connection, table, data, conflict_policy=conflict_policy)
            report["tables"][table] = table_report
            report["mismatches"].extend(table_report["mismatches"])
    return report


def verify_import(engine: Engine, export: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Post-import verification: per-table row counts + sample fingerprints."""
    checks: dict[str, Any] = {}
    with transaction(engine) as connection:
        for table, data in export.get("tables", {}).items():
            pk_columns = PRIMARY_KEYS.get(table)
            expected = manifest["tables"][table]["row_count"]
            if pk_columns is None:
                checks[table] = {"ok": False, "reason": "no primary key registered"}
                continue
            rows = execute(connection, f'SELECT * FROM "{table}"')
            actual = len(rows)
            columns = data["columns"]
            restricted = [{k: r[k] for k in columns if k in r} for r in rows]
            ordered = sorted(restricted, key=_canonical_row)
            fingerprint = hashlib.sha256(_canonical_bytes(ordered)).hexdigest()
            checks[table] = {
                "ok": actual == expected,
                "expected_count": expected,
                "actual_count": actual,
                "fingerprint_matches": fingerprint == manifest["tables"][table]["fingerprint"],
            }
    return checks
