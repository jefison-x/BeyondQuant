from __future__ import annotations

from app.db import connect, execute, fetch_one, run_ddl
from app.research import ResearchStore


def test_shared_sql_layer_bootstrap_and_crud(byq_test_engine) -> None:
    engine = byq_test_engine
    with engine.begin() as connection:
        run_ddl(connection, ResearchStore.SCHEMA_DDL)

    with connect(engine) as connection:
        execute(
            connection,
            """
            INSERT INTO research_tasks
                (task_id, owner_principal, title, objective, status, trace_id,
                 idempotency_key, request_hash, created_at, updated_at, version)
            VALUES
                (:task_id, :owner, :title, :objective, 'planned', :trace,
                 :key, :hash, now(), now(), 1)
            ON CONFLICT (task_id) DO NOTHING
            """,
            {
                "task_id": "task_pg_foundation",
                "owner": "pg-test-user",
                "title": "PG foundation",
                "objective": "verify shared SQL layer",
                "trace": "byq-pg-foundation",
                "key": "pg-foundation-key",
                "hash": "0" * 64,
            },
        )
        connection.commit()

        row = fetch_one(
            connection,
            "SELECT task_id, owner_principal, title, created_at FROM research_tasks WHERE task_id = :task_id",
            {"task_id": "task_pg_foundation"},
        )
    assert row is not None
    assert row["owner_principal"] == "pg-test-user"
    assert row["title"] == "PG foundation"
    # Row normalization: TIMESTAMPTZ is returned as an ISO-8601 string.
    assert isinstance(row["created_at"], str)
