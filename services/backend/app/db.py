"""Shared PostgreSQL SQL layer for BYQ domain stores (ADR-0016).

This module is the single connection/dialect path for every BYQ domain store.
Stores keep their public method names and return shapes; only the SQL backend
changes. SQLite is removed after all stores migrate.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine


DEFAULT_DATABASE_URL = os.getenv(
    "BYQ_DATABASE_URL",
    "postgresql+psycopg://byq_app:byq-app-dev@localhost:5432/byq_domain",
)


def create_db_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or DEFAULT_DATABASE_URL, pool_pre_ping=True, future=True)


def connect(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        yield connection


def execute(connection: Connection, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result = connection.execute(text(sql), params or {})
    rows = result.mappings().all()
    return [dict(row) for row in rows]


def fetch_one(connection: Connection, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = execute(connection, sql, params)
    return rows[0] if rows else None


def run_ddl(connection: Connection, statements: list[str]) -> None:
    for statement in statements:
        connection.execute(text(statement))


RESEARCH_SCHEMA_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS research_tasks (
        task_id TEXT PRIMARY KEY,
        owner_principal TEXT NOT NULL,
        title TEXT NOT NULL,
        objective TEXT NOT NULL,
        status TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        version INTEGER NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS research_tasks_idempotency
        ON research_tasks(owner_principal, idempotency_key)
    """,
    """
    CREATE TABLE IF NOT EXISTS experiments (
        experiment_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        owner_principal TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        version INTEGER NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS experiments_idempotency
        ON experiments(owner_principal, idempotency_key)
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        artifact_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        experiment_id TEXT,
        owner_principal TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        content JSONB NOT NULL,
        content_sha256 TEXT NOT NULL,
        lineage JSONB NOT NULL,
        trace_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        version INTEGER NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS artifacts_idempotency
        ON artifacts(owner_principal, idempotency_key)
    """,
    """
    CREATE INDEX IF NOT EXISTS artifacts_kind_idx ON artifacts(kind)
    """,
    """
    CREATE TABLE IF NOT EXISTS research_transitions (
        transition_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        owner_principal TEXT NOT NULL,
        from_status TEXT NOT NULL,
        to_status TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
]


def bootstrap_research_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        run_ddl(connection, RESEARCH_SCHEMA_DDL)
