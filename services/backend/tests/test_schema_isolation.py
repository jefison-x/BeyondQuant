"""Isolation regression tests for the deferred per-test schema reset (CI-B).

These tests prove the optimization did not weaken isolation:

- registered migrations really run (migration-only columns exist);
- a committed write is visible on an independent connection, so multi-connection
  and commit semantics were not replaced by a global rollback;
- the deferred reset clears committed rows and restores the schema after a
  simulated failure;
- a pure-logic test that never opens a connection does not trigger a reset;
- a database-using test triggers the reset exactly once, and data written by one
  test is never visible to the next (also exercised under fixed-seed shuffling).
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.db import create_db_engine, execute, fetch_one, transaction

pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

_TABLE = "research_tasks"
_LEAK_MARKER = "cib-isolation-leak-marker"


def _insert_task(engine, task_id: str) -> None:
    with transaction(engine) as connection:
        execute(
            connection,
            """
            INSERT INTO research_tasks
                (task_id, owner_principal, title, objective, status, trace_id,
                 idempotency_key, request_hash, created_at, updated_at, version)
            VALUES
                (:task_id, 'isolation-user', 'isolation', 'isolation', 'planned',
                 'byq-ci-b-isolation', :key, :hash, now(), now(), 1)
            """,
            {"task_id": task_id, "key": f"key-{task_id}", "hash": "0" * 64},
        )


def test_registered_migrations_run_on_reset() -> None:
    engine = create_db_engine()
    try:
        with engine.connect() as connection:
            tables = {
                row["tablename"]
                for row in execute(
                    connection,
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
                )
            }
            # Migration-only columns added via ALTER TABLE ... ADD COLUMN IF NOT
            # EXISTS must be present, proving the full registered DDL ran.
            migration_columns = {
                (row["table_name"], row["column_name"])
                for row in execute(
                    connection,
                    """
                    SELECT table_name, column_name FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND ((table_name = 'agent_runs' AND column_name = 'root_run_id')
                        OR (table_name = 'ml_training_runs' AND column_name = 'preparation_claim')
                        OR (table_name = 'product_feedback_outbox' AND column_name = 'create_started')
                        OR (table_name = 'agent_approvals' AND column_name = 'continuation_status'))
                    """,
                )
            }
    finally:
        engine.dispose()
    assert {"research_tasks", "agent_runs", "backtest_jobs"} <= tables
    assert migration_columns == {
        ("agent_runs", "root_run_id"),
        ("ml_training_runs", "preparation_claim"),
        ("product_feedback_outbox", "create_started"),
        ("agent_approvals", "continuation_status"),
    }


def test_committed_write_is_visible_to_independent_connection() -> None:
    writer = create_db_engine()
    reader = create_db_engine()
    task_id = f"task-cib-visible-{uuid.uuid4().hex}"
    try:
        _insert_task(writer, task_id)
        with reader.connect() as connection:
            row = fetch_one(
                connection,
                "SELECT task_id FROM research_tasks WHERE task_id = :task_id",
                {"task_id": task_id},
            )
        assert row == {"task_id": task_id}
    finally:
        writer.dispose()
        reader.dispose()


def test_reset_clears_committed_rows_after_simulated_failure(byq_force_schema_reset) -> None:
    engine = create_db_engine()
    task_id = f"task-cib-dirty-{uuid.uuid4().hex}"
    try:
        _insert_task(engine, task_id)
        with engine.connect() as connection:
            assert fetch_one(
                connection,
                "SELECT task_id FROM research_tasks WHERE task_id = :task_id",
                {"task_id": task_id},
            )
    finally:
        engine.dispose()

    # Simulate the next test starting after a failure left committed rows: the
    # deferred reset must clear them and restore the schema.
    byq_force_schema_reset()

    verify = create_db_engine()
    try:
        with verify.connect() as connection:
            assert fetch_one(
                connection,
                "SELECT task_id FROM research_tasks WHERE task_id = :task_id",
                {"task_id": task_id},
            ) is None
            assert fetch_one(
                connection,
                "SELECT to_regclass('public.research_tasks') AS relation",
            ) == {"relation": "research_tasks"}
    finally:
        verify.dispose()


def test_pure_logic_test_does_not_open_a_connection_or_reset(byq_schema_reset_stats) -> None:
    before = byq_schema_reset_stats["count"]
    assert 2 + 2 == 4
    assert byq_schema_reset_stats["count"] == before


def test_database_access_resets_exactly_once_per_test(byq_schema_reset_stats) -> None:
    before = byq_schema_reset_stats["count"]
    engine = create_db_engine()
    try:
        with engine.connect() as first:
            execute(first, "SELECT 1")
        with engine.connect() as second:
            execute(second, "SELECT 1")
    finally:
        engine.dispose()
    assert byq_schema_reset_stats["count"] == before + 1


def test_first_writer_leaves_marker_row() -> None:
    engine = create_db_engine()
    try:
        _insert_task(engine, _LEAK_MARKER)
    finally:
        engine.dispose()


def test_second_test_never_sees_previous_row() -> None:
    engine = create_db_engine()
    try:
        with engine.connect() as connection:
            assert fetch_one(
                connection,
                "SELECT task_id FROM research_tasks WHERE task_id = :task_id",
                {"task_id": _LEAK_MARKER},
            ) is None
    finally:
        engine.dispose()
