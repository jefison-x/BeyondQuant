"""Shared PostgreSQL test harness for BYQ backend tests (ADR-0016 Stage 1+).

Guards:
- Tests that need PostgreSQL skip with a clear message when ``BYQ_DATABASE_URL``
  is unset (same spirit as the original ``test_db.py``).
- Any configured URL whose database name is not ``byq_domain_test`` is refused,
  so the shared test schema is never reset on the application database.

The autouse fixture resets the shared PostgreSQL test schema before every test
and runs the DDL of every store registered here. The registry grows as stores
migrate (Stage 2: + PaperTrading, BacktestJob).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.backtest import BacktestJobStore
from app.db import create_db_engine, run_ddl
from app.paper_trading import PaperTradingStore
from app.user_auth import UserAuthStore
from app.user_policy import UserPolicyStore


TEST_DB_NAME = "byq_domain_test"

# Registered store DDL; grows as stores migrate (ADR-0016 stages).
REGISTERED_SCHEMA_DDL: list[str] = [
    *UserAuthStore.SCHEMA_DDL,
    *UserPolicyStore.SCHEMA_DDL,
    *PaperTradingStore.SCHEMA_DDL,
    *BacktestJobStore.SCHEMA_DDL,
]

_ENGINE_CACHE: dict[str, Engine] = {}


def _require_test_database_url() -> str | None:
    """Return ``BYQ_DATABASE_URL`` only when it targets the isolated test DB."""
    url = os.environ.get("BYQ_DATABASE_URL")
    if not url:
        return None
    if TEST_DB_NAME not in url:
        raise RuntimeError(
            f"BYQ_DATABASE_URL must target the {TEST_DB_NAME} database; "
            "refusing to reset any other database"
        )
    return url


def _test_engine() -> Engine | None:
    url = _require_test_database_url()
    if url is None:
        return None
    engine = _ENGINE_CACHE.get(url)
    if engine is None:
        engine = create_db_engine(url)
        _ENGINE_CACHE[url] = engine
    return engine


@pytest.fixture(scope="session")
def byq_test_engine():
    """Session-scoped engine against the isolated test database."""
    engine = _test_engine()
    if engine is None:
        pytest.skip("BYQ_DATABASE_URL is not set; PostgreSQL-backed tests are skipped")
    yield engine


@pytest.fixture(scope="session", autouse=True)
def _dispose_test_engines():
    yield
    for engine in _ENGINE_CACHE.values():
        engine.dispose()


@pytest.fixture(autouse=True)
def _byq_reset_schema():
    """Reset the shared PostgreSQL test schema before each test (inert when unset)."""
    engine = _test_engine()
    if engine is None:
        yield
        return
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        run_ddl(connection, REGISTERED_SCHEMA_DDL)
    yield
