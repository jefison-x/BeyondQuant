from __future__ import annotations

from app.db import bootstrap_research_schema, connect, execute, fetch_one


def test_research_schema_bootstrap_and_crud(byq_test_engine) -> None:
    engine = byq_test_engine
    bootstrap_research_schema(engine)

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
            "SELECT task_id, owner_principal, title FROM research_tasks WHERE task_id = :task_id",
            {"task_id": "task_pg_foundation"},
        )
    assert row is not None
    assert row["owner_principal"] == "pg-test-user"
    assert row["title"] == "PG foundation"
