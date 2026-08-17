from __future__ import annotations

import os
import sqlite3

import pytest
from sqlalchemy import text

from app.db import create_db_engine
from app.pg_import import (
    KEEP_NEW,
    REPORT_MISMATCH,
    VERIFY_EQUAL,
    adapt_export,
    import_to_pg,
    verify_import,
)
from app.sqlite_export import build_manifest, export_sqlite, quarantine_rows


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def _write_fixture(path, *, task_id: str = "0" * 32, title: str = "t") -> None:
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE research_tasks (
            task_id TEXT PRIMARY KEY, owner_principal TEXT NOT NULL,
            title TEXT NOT NULL, objective TEXT NOT NULL, status TEXT NOT NULL,
            trace_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, version INTEGER NOT NULL
        );
        CREATE TABLE user_agent_policy (
            owner_principal TEXT PRIMARY KEY, automation_enabled INTEGER NOT NULL DEFAULT 0,
            paused INTEGER NOT NULL DEFAULT 0, default_decision_mode TEXT NOT NULL DEFAULT 'manual',
            max_auto_executions_per_hour INTEGER NOT NULL DEFAULT 20,
            max_auto_failures_per_hour INTEGER NOT NULL DEFAULT 3, updated_at TEXT NOT NULL
        );
        CREATE TABLE stock_pools (
            pool_id TEXT PRIMARY KEY, owner_principal TEXT NOT NULL, name TEXT NOT NULL,
            pool_type TEXT NOT NULL, description TEXT, weights_json TEXT,
            symbols_json TEXT NOT NULL, version TEXT NOT NULL,
            provenance_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """
    )
    now = "2026-08-17T00:00:00+00:00"
    connection.execute(
        "INSERT INTO research_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (f"task_{task_id}", "product-user", title, "o", "planned", "trace-1", "k1", "h" * 64, now, now, 1),
    )
    connection.execute(
        "INSERT INTO user_agent_policy VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("product-user", 1, 0, "auto_deny", 20, 3, now),
    )
    connection.execute(
        "INSERT INTO stock_pools VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("stock_pool_" + task_id, "product-user", "p1", "custom", None,
         '{"000001.SZ": 1.0}', '["000001.SZ"]', "v1", '{"source": "unit-test"}', now),
    )
    connection.commit()
    connection.close()


def _valid_export(tmp_path, **kwargs) -> dict:
    path = tmp_path / "domain.sqlite3"
    _write_fixture(path, **kwargs)
    separated = quarantine_rows(export_sqlite(path))
    assert not separated["quarantined"]
    return separated["valid"]


def test_import_is_idempotent_and_verifies(byq_test_engine, tmp_path) -> None:
    export = _valid_export(tmp_path)
    manifest = build_manifest(adapt_export(export), source_sha256="0" * 64)
    first = import_to_pg(byq_test_engine, export, conflict_policy=KEEP_NEW)
    second = import_to_pg(byq_test_engine, export, conflict_policy=KEEP_NEW)
    assert first["tables"]["research_tasks"]["inserted"] == 1
    assert second["tables"]["research_tasks"]["inserted"] == 0, "re-import must not duplicate rows"
    assert second["tables"]["research_tasks"]["kept"] == 1
    checks = verify_import(byq_test_engine, export, manifest)
    assert all(checks[table]["ok"] and checks[table]["fingerprint_matches"] for table in checks)


def test_import_adapts_json_and_boolean_types(byq_test_engine, tmp_path) -> None:
    export = _valid_export(tmp_path)
    import_to_pg(byq_test_engine, export, conflict_policy=KEEP_NEW)
    with byq_test_engine.connect() as connection:
        connection.commit()
        pool = connection.execute(text("SELECT symbols_json FROM stock_pools")).mappings().all()[0]
        policy = connection.execute(text("SELECT automation_enabled FROM user_agent_policy")).mappings().all()[0]
    assert pool["symbols_json"] == ["000001.SZ"]
    assert policy["automation_enabled"] is True


def test_conflict_policies_never_overwrite_existing_rows(byq_test_engine, tmp_path) -> None:
    export = _valid_export(tmp_path)
    import_to_pg(byq_test_engine, export, conflict_policy=KEEP_NEW)
    # Same PK, different content (title "changed").
    changed = _valid_export(tmp_path, title="changed")

    keep = import_to_pg(byq_test_engine, changed, conflict_policy=KEEP_NEW)
    with byq_test_engine.connect() as connection:
        connection.commit()
        row = connection.execute(text("SELECT title FROM research_tasks WHERE task_id = :t"), {"t": "task_" + "0" * 32}).mappings().all()[0]
    assert row["title"] == "t", "KEEP_NEW must keep the existing (newer) row"

    equal = import_to_pg(byq_test_engine, changed, conflict_policy=VERIFY_EQUAL)
    assert len(equal["mismatches"]) >= 1, "VERIFY_EQUAL must report a content mismatch"

    report = import_to_pg(byq_test_engine, changed, conflict_policy=REPORT_MISMATCH)
    assert len(report["mismatches"]) >= 1, "REPORT_MISMATCH must report the conflict"
