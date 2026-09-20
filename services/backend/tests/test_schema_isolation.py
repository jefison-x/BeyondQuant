"""Isolation regression tests for the deferred per-test schema reset (CI-B).

These tests prove the optimization did not weaken isolation:

- registered migrations really run (migration-only columns exist);
- a committed write is visible on an independent connection, so multi-connection
  and commit semantics were not replaced by a global rollback;
- a case that commits dirty rows and dynamic objects **and then really fails**
  is followed by a case that recovers through the normal autouse/first-access
  path, with no manual reset anywhere (bounded nested pytest subprocesses);
- a deterministic write-then-read scenario holds across the test boundary in
  more than one suite position, and each reader asserts that its writer really
  ran first (the pollution precondition), so the evidence cannot be inverted;
- a pure-logic test that never opens a connection does not trigger a reset;
- a database-using test triggers the reset exactly once.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.db import create_db_engine, execute, fetch_one, transaction

pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_CONFTEST_SOURCE = Path(__file__).with_name("conftest.py").read_text()

# Shared prelude for the generated nested modules. The generated modules never
# import or call the schema-reset primitive: recovery must come only from the
# normal autouse fixture + first-access path in the copied conftest.
_NESTED_PRELUDE = '''
from sqlalchemy import text
from app.db import create_db_engine, execute, fetch_one, transaction

STATE = {}


def _insert(engine, task_id):
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
            {"task_id": task_id, "key": "key-" + task_id, "hash": "0" * 64},
        )


def _make_dynamic(engine, name):
    with transaction(engine) as connection:
        connection.execute(text("CREATE TABLE " + name + " (id integer primary key)"))
        connection.execute(text("CREATE INDEX " + name + "_ix ON " + name + " (id)"))


def _assert_clean(engine, task_id, dynamic_name):
    with engine.connect() as connection:
        assert fetch_one(
            connection,
            "SELECT task_id FROM research_tasks WHERE task_id = :task_id",
            {"task_id": task_id},
        ) is None
        assert fetch_one(
            connection,
            "SELECT to_regclass(:relation) AS relation",
            {"relation": "public." + dynamic_name},
        ) == {"relation": None}
        assert fetch_one(
            connection,
            "SELECT to_regclass('public.research_tasks') AS relation",
        ) == {"relation": "research_tasks"}
'''

_FAIL_THEN_RECOVER = (
    _NESTED_PRELUDE
    + '''
def test_writer_commits_dirty_state_then_really_fails():
    engine = create_db_engine()
    try:
        _insert(engine, "cib-fail-marker")
        _make_dynamic(engine, "cib_fail_probe")
    finally:
        engine.dispose()
    STATE["writer_ran"] = True
    raise AssertionError("intentional failure after committing dirty rows and a dynamic table")


def test_reader_recovers_automatically_after_failure():
    assert STATE.get("writer_ran") is True, "pollution precondition: writer must run first"
    engine = create_db_engine()
    try:
        _assert_clean(engine, "cib-fail-marker", "cib_fail_probe")
    finally:
        engine.dispose()
'''
)


def _write_then_read_module(tag: str, *, noise_before: int, noise_between: int, noise_after: int) -> str:
    """Deterministic module whose writer always precedes its reader."""
    parts = [_NESTED_PRELUDE]
    for index in range(noise_before):
        parts.append(f"def test_noise_before_{tag}_{index}():\n    assert 1 + 1 == 2\n")
    parts.append(
        f'''
def test_writer_{tag}():
    engine = create_db_engine()
    try:
        _insert(engine, "cib-marker-{tag}")
        _make_dynamic(engine, "cib_probe_{tag}")
    finally:
        engine.dispose()
    STATE["writer_{tag}"] = True
'''
    )
    for index in range(noise_between):
        parts.append(f"def test_noise_between_{tag}_{index}():\n    assert 2 + 2 == 4\n")
    parts.append(
        f'''
def test_reader_{tag}():
    assert STATE.get("writer_{tag}") is True, "pollution precondition: writer must run first"
    engine = create_db_engine()
    try:
        _assert_clean(engine, "cib-marker-{tag}", "cib_probe_{tag}")
    finally:
        engine.dispose()
'''
    )
    for index in range(noise_after):
        parts.append(f"def test_noise_after_{tag}_{index}():\n    assert 3 + 3 == 6\n")
    return "\n".join(parts)


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


def _run_nested_pytest(tmp_path: Path, name: str, source: str, timeout: int = 300) -> tuple[int, str]:
    """Run a bounded nested pytest in a fresh rootdir with the copied conftest.

    ``BYQ_TEST_SHUFFLE_SEED`` is cleared so the nested order is always the
    deterministic definition order; the suite-level shuffle must not be able to
    invert the write-then-read precondition.
    """
    root = tmp_path / name
    root.mkdir()
    (root / "conftest.py").write_text(_CONFTEST_SOURCE)
    (root / "test_nested_isolation.py").write_text(source)
    env = dict(os.environ)
    env.pop("BYQ_TEST_SHUFFLE_SEED", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(_BACKEND_ROOT), env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_nested_isolation.py"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout + completed.stderr


def _count(output: str, label: str) -> int:
    match = re.search(rf"(\d+) {label}\b", output)
    return int(match.group(1)) if match else 0


def _schema_resets(output: str) -> int:
    match = re.search(r"schema_resets=(\d+)", output)
    assert match is not None, f"missing [byq-timing] summary:\n{output}"
    return int(match.group(1))


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
    task_id = f"task-cib-visible-{os.urandom(8).hex()}"
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


def test_intentional_failure_then_automatic_recovery_subprocess(tmp_path) -> None:
    """First case really fails after committing dirt; next case auto-recovers.

    There is no manual reset in the generated module, so a passing reader proves
    the normal autouse/first-access path cleaned up the failed case's rows and
    dynamic table. ``schema_resets=2`` proves exactly one automatic reset ran per
    case (and therefore that no manual reset was substituted).
    """
    returncode, output = _run_nested_pytest(tmp_path, "failure", _FAIL_THEN_RECOVER)
    assert returncode != 0, output
    assert _count(output, "failed") == 1, output
    assert _count(output, "passed") == 1, output
    assert _schema_resets(output) == 2, output


def test_write_then_read_scenario_in_two_order_variations(tmp_path) -> None:
    """Deterministic writer-before-reader evidence in two suite positions.

    Each reader asserts its own writer ran first, so an inverted order would be a
    loud failure rather than vacuous evidence. The surrounding noise tests change
    the pair's position in the suite while preserving that precondition.
    """
    variants = {
        "early": _write_then_read_module("early", noise_before=0, noise_between=0, noise_after=0),
        "late": _write_then_read_module("late", noise_before=1, noise_between=1, noise_after=1),
    }
    expected_passed = {"early": 2, "late": 5}
    for name, source in variants.items():
        returncode, output = _run_nested_pytest(tmp_path, name, source)
        assert returncode == 0, output
        assert _count(output, "failed") == 0, output
        assert _count(output, "passed") == expected_passed[name], output
        assert _schema_resets(output) == 2, output


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
