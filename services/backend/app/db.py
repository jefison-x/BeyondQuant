"""Shared PostgreSQL SQL layer for BYQ domain stores (ADR-0016).

This module is the single connection/dialect path for every BYQ domain store.
Stores keep their public method names and return shapes; only the SQL backend
changes. SQLite is removed after all stores migrate (Stage 6).

Store-specific DDL lives in each store module (``SCHEMA_DDL`` +
``bootstrap_schema``); this module only provides the shared engine/connection
helpers and the small ``PgStoreMixin`` that makes the per-store rewrites
mechanical. It deliberately does NOT become a generic repository.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine


DEFAULT_DATABASE_URL = os.getenv(
    "BYQ_DATABASE_URL",
    "postgresql+psycopg://byq_app:byq-app-dev@localhost:5432/byq_domain",
)


def create_db_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or DEFAULT_DATABASE_URL, pool_pre_ping=True, future=True)


@contextmanager
def connect(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        yield connection


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Run one or more statements inside a single committed transaction.

    Commits on success and rolls back on exception, matching the implicit
    per-statement autocommit behaviour the SQLite stores relied on for single
    statements while giving atomicity to multi-statement flows.
    """
    with engine.begin() as connection:
        yield connection


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize DB driver types back to the previous SQLite-compatible shapes.

    - ``datetime``/``date`` -> ISO-8601 string (keeps string comparisons such as
      ``session_expires_at < now`` and API output byte-for-byte compatible);
    - ``Decimal`` -> ``float`` (money/price columns return JSON-safe numbers);
    - JSONB values already arrive as parsed ``dict``/``list`` (psycopg) and pass
      through unchanged;
    - ``bool`` and other scalars pass through.
    """
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            normalized[key] = value.isoformat()
        elif isinstance(value, date):
            normalized[key] = value.isoformat()
        elif isinstance(value, Decimal):
            normalized[key] = float(value)
        else:
            normalized[key] = value
    return normalized


def execute(connection: Connection, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result = connection.execute(text(sql), params or {})
    if not result.returns_rows:
        return []
    return [_normalize_row(dict(row)) for row in result.mappings().all()]


def fetch_one(connection: Connection, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = execute(connection, sql, params)
    return rows[0] if rows else None


def run_ddl(connection: Connection, statements: list[str]) -> None:
    for statement in statements:
        connection.execute(text(statement))


def ensure_column(connection: Connection, table: str, column: str, definition: str) -> None:
    """Idempotent column back-migration parity with the old SQLite stores."""
    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"))


class PgStoreMixin:
    """Small shared PostgreSQL engine/lock/query surface for BYQ domain stores.

    Not a generic repository: each store keeps its own validation, transitions,
    and invariants. The mixin only supplies engine lifecycle, a reentrant lock,
    and parameterized helpers that normalize rows to SQLite-compatible shapes.
    """

    SCHEMA_DDL: list[str] = []

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("BYQ_DATABASE_URL", DEFAULT_DATABASE_URL)
        self.engine = create_db_engine(self.database_url)
        self._lock = threading.RLock()
        self.bootstrap_schema()

    @classmethod
    def from_env(cls) -> "PgStoreMixin":
        return cls()

    def close(self) -> None:
        with self._lock:
            self.engine.dispose()

    def bootstrap_schema(self) -> None:
        with self.engine.begin() as connection:
            run_ddl(connection, self.SCHEMA_DDL)

    def _execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._lock, transaction(self.engine) as connection:
            return execute(connection, sql, params)

    def _fetch_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._lock, transaction(self.engine) as connection:
            return fetch_one(connection, sql, params)

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        with self._lock, transaction(self.engine) as connection:
            yield connection


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
