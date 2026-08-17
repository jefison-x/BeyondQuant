from __future__ import annotations

import hashlib
import sqlite3

from app.sqlite_export import (
    export_sqlite,
    quarantine_rows,
    build_manifest,
    validate_row,
    ExportError,
)


def _write_fixture(path) -> None:
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
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT,
            display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
            status TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, last_login_at TEXT, password_changed_at TEXT,
            preferences TEXT, default_prompt TEXT, preferences_version INTEGER NOT NULL DEFAULT 1
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
        ("task_" + "0" * 32, "product-user", "t", "o", "planned", "trace-1", "k1", "h" * 64, now, now, 1),
    )
    connection.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("user_" + "0" * 32, "alice", None, "Alice", "scrypt$x", "active", "user", now, now, None, None, None, None, 1),
    )
    connection.execute(
        "INSERT INTO user_agent_policy VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("product-user", 1, 0, "auto_deny", 20, 3, now),
    )
    connection.execute(
        "INSERT INTO stock_pools VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("stock_pool_" + "0" * 32, "product-user", "p1", "custom", None,
         '{}', '["000001.SZ"]', "v1", '{"source": "unit-test"}', now),
    )
    connection.commit()
    connection.close()


def test_export_is_read_only_and_canonical(tmp_path) -> None:
    path = tmp_path / "domain.sqlite3"
    _write_fixture(path)
    before = path.read_bytes()
    export = export_sqlite(path)
    after = path.read_bytes()
    assert before == after, "export must not modify the source SQLite file"
    assert export["schema_version"] == "1"
    assert export["source"]["read_only"] is True
    assert export["tables"]["research_tasks"]["rows"][0]["task_id"] == "task_" + "0" * 32
    assert export["tables"]["users"]["rows"][0]["username"] == "alice"
    # JSON columns remain raw TEXT in the export (adapted at import time).
    assert export["tables"]["stock_pools"]["rows"][0]["symbols_json"] == '["000001.SZ"]'


def test_missing_file_raises_read_only_export_error(tmp_path) -> None:
    try:
        export_sqlite(tmp_path / "missing.sqlite3")
    except ExportError:
        return
    raise AssertionError("export of a missing file must raise ExportError")


def test_validation_quarantines_invalid_rows(tmp_path) -> None:
    path = tmp_path / "domain.sqlite3"
    _write_fixture(path)
    connection = sqlite3.connect(path)
    now = "2026-08-17T00:00:00+00:00"
    connection.execute(
        "INSERT INTO research_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("task_" + "1" * 32, "product-user", "bad", "o", "planned", "trace-2", "k2", "h" * 64, now, now, 1),
    )
    connection.execute(
        "INSERT INTO stock_pools VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("stock_pool_" + "1" * 32, "product-user", "bad-symbol", "custom", None,
         '{}', '["NOT-A-SYMBOL"]', "v1", '{"source": "unit-test"}', now),
    )
    connection.commit()
    connection.close()

    separated = quarantine_rows(export_sqlite(path))
    assert "stock_pools" in separated["quarantined"], "invalid symbol row must be quarantined"
    valid_pools = separated["valid"]["tables"].get("stock_pools", {"rows": []})["rows"]
    assert len(valid_pools) == 1, "only the valid pool row should pass"
    assert "research_tasks" not in separated["quarantined"], "a well-formed extra task row should not be quarantined"


def test_validate_row_flags_bad_ids_and_dates() -> None:
    assert validate_row("research_tasks", {"task_id": "task_" + "z" * 32}) != []
    assert validate_row("research_tasks", {"task_id": "task_" + "0" * 32}) == []
    assert validate_row("research_tasks", {"created_at": "not-a-date"}) != []
    assert validate_row("paper_accounts", {"cash": float("nan")}) != []


def test_manifest_is_deterministic(tmp_path) -> None:
    path = tmp_path / "domain.sqlite3"
    _write_fixture(path)
    export = export_sqlite(path)
    first = build_manifest(export, source_sha256=hashlib.sha256(b"x").hexdigest())
    second = build_manifest(export_sqlite(path), source_sha256=hashlib.sha256(b"x").hexdigest())
    assert first == second
    assert first["tables"]["research_tasks"]["row_count"] == 1
    assert len(first["tables"]["research_tasks"]["fingerprint"]) == 64
