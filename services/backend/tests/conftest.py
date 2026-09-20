"""Shared PostgreSQL test harness for BYQ backend tests (ADR-0016 Stage 1+).

Guards:
- Tests that need PostgreSQL skip with a clear message when ``BYQ_DATABASE_URL``
  is unset (same spirit as the original ``test_db.py``).
- Any configured URL whose database name is not ``byq_domain_test`` is refused,
  so the shared test schema is never reset on the application database.

The autouse fixture resets the shared PostgreSQL test schema before the first
database access of every test and runs the DDL of every store registered here.
The reset is deferred until a test actually opens a database connection, so
pure-logic tests that never touch persistence do not pay for a schema rebuild.
The registry grows as stores migrate (Stage 4: + Research (all eight stores registered).
"""

from __future__ import annotations

import os
import threading
import time

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

import app.db as _db_module
from app.agent_research import AgentResearchStore
from app.backtest import BacktestJobStore
from app.db import run_ddl
from app.credentials import CredentialStore
from app.conversation_catalog import ConversationCatalogStore
from app.data_sync import DataSyncStore
from app.data_demand import DataDemandStore
from app.engineering import EngineeringTaskStore
from app.learning_loop import LearningLoopStore
from app.market_data import MarketDataStore
from app.market_automation import MarketAutomationStore
from app.market_readiness import MarketReadinessStore
from app.ml_training import MLTrainingRunStore
from app.ml_prediction import MLPredictionRunStore
from app.operations import OperationsStore
from app.paper_trading import PaperTradingStore
from app.product_feedback import ProductFeedbackStore
from app.research import ResearchStore
from app.security_master import SecurityMasterStore
from app.signal_producer import SignalJobStore
from app.stock_pool_producer import StockPoolProducerStore
from app.user_auth import UserAuthStore
from app.user_policy import UserPolicyStore
from app.workspace_tenancy import WorkspaceTenancyStore


TEST_DB_NAME = "byq_domain_test"

# Registered store DDL; grows as stores migrate (ADR-0016 stages).
REGISTERED_SCHEMA_DDL: list[str] = [
    *ConversationCatalogStore.SCHEMA_DDL,
    *UserAuthStore.SCHEMA_DDL,
    *ProductFeedbackStore.SCHEMA_DDL,
    *CredentialStore.SCHEMA_DDL,
    *DataSyncStore.SCHEMA_DDL,
    *DataDemandStore.SCHEMA_DDL,
    *SecurityMasterStore.SCHEMA_DDL,
    *UserPolicyStore.SCHEMA_DDL,
    *PaperTradingStore.SCHEMA_DDL,
    *StockPoolProducerStore.SCHEMA_DDL,
    *BacktestJobStore.SCHEMA_DDL,
    *AgentResearchStore.SCHEMA_DDL,
    *EngineeringTaskStore.SCHEMA_DDL,
    *LearningLoopStore.SCHEMA_DDL,
    *ResearchStore.SCHEMA_DDL,
    *MarketDataStore.SCHEMA_DDL,
    *MarketAutomationStore.SCHEMA_DDL,
    *MarketReadinessStore.SCHEMA_DDL,
    *SignalJobStore.SCHEMA_DDL,
    *MLTrainingRunStore.SCHEMA_DDL,
    *MLPredictionRunStore.SCHEMA_DDL,
    *OperationsStore.SCHEMA_DDL,
    *WorkspaceTenancyStore.SCHEMA_DDL,
]


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


# --- lazy schema reset -------------------------------------------------------
#
# The reset is triggered by the first database connection checkout of each test
# (``engine_connect`` fires on every ``Engine.connect()``/``Engine.begin()``).
# Tests that never touch persistence never open a connection and therefore never
# pay for the schema rebuild. Every store and helper obtains its engine through
# ``app.db.create_db_engine``, so instrumenting that single factory covers all
# production and test database access paths.

_ORIGINAL_CREATE_DB_ENGINE = _db_module.create_db_engine
_reset_lock = threading.Lock()
_test_active = False
_reset_done = False

SCHEMA_RESET_STATS = {"count": 0, "seconds": 0.0}
STORE_BOOTSTRAP_STATS = {"count": 0, "seconds": 0.0}


def _reset_schema(url: str) -> None:
    engine = _ORIGINAL_CREATE_DB_ENGINE(url)
    try:
        with engine.connect() as connection:
            autocommit = connection.execution_options(isolation_level="AUTOCOMMIT")
            autocommit.execute(text("DROP SCHEMA public CASCADE"))
            autocommit.execute(text("CREATE SCHEMA public"))
            run_ddl(autocommit, REGISTERED_SCHEMA_DDL)
    finally:
        engine.dispose()


def _maybe_reset_schema() -> None:
    global _reset_done
    if not _test_active or _reset_done:
        return
    with _reset_lock:
        if not _test_active or _reset_done:
            return
        url = _require_test_database_url()
        if url is None:
            _reset_done = True
            return
        started = time.perf_counter()
        _reset_schema(url)
        SCHEMA_RESET_STATS["count"] += 1
        SCHEMA_RESET_STATS["seconds"] += time.perf_counter() - started
        _reset_done = True


def _instrument(engine: Engine) -> Engine:
    # Engines created before a test starts (for example the module-level stores
    # in ``app.main`` imported at collection time) only see the deferred reset
    # here, on their first connection checkout inside a test.
    event.listen(engine, "engine_connect", lambda _connection: _maybe_reset_schema())
    return engine


def _instrumented_create_db_engine(database_url: str | None = None) -> Engine:
    # An engine created inside a test is a reliable "database will be used"
    # signal: reset eagerly so store bootstrap DDL runs against a clean schema
    # and its timing is measured separately from the reset.
    _maybe_reset_schema()
    return _instrument(_ORIGINAL_CREATE_DB_ENGINE(database_url))


_db_module.create_db_engine = _instrumented_create_db_engine


original_bootstrap = _db_module.PgStoreMixin.bootstrap_schema


def _timed_bootstrap_schema(self) -> None:
    started = time.perf_counter()
    try:
        original_bootstrap(self)
    finally:
        STORE_BOOTSTRAP_STATS["count"] += 1
        STORE_BOOTSTRAP_STATS["seconds"] += time.perf_counter() - started


_db_module.PgStoreMixin.bootstrap_schema = _timed_bootstrap_schema


@pytest.fixture(scope="session")
def byq_test_engine():
    """Fresh engine against the isolated test database (used by test_db.py).

    A fresh engine is used (rather than a long-lived pooled engine) so that
    repeated ``DROP SCHEMA public CASCADE`` resets never reuse a stale pooled
    connection, which triggered PostgreSQL ``unexpected data beyond EOF``
    storage errors during ADR-0016 Stage 3 validation.
    """
    url = _require_test_database_url()
    if url is None:
        pytest.skip("BYQ_DATABASE_URL is not set; PostgreSQL-backed tests are skipped")
    engine = _instrumented_create_db_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def byq_schema_reset_stats() -> dict[str, float]:
    """Live counters for the deferred reset (used by isolation regression tests)."""
    return SCHEMA_RESET_STATS


@pytest.fixture
def byq_force_schema_reset():
    """Expose the exact reset primitive to isolation regression tests."""

    def _reset() -> None:
        url = _require_test_database_url()
        if url is not None:
            _reset_schema(url)

    return _reset


@pytest.fixture(autouse=True)
def _byq_reset_schema():
    """Arm the deferred, once-per-test schema reset (inert when unset).

    The actual ``DROP SCHEMA public CASCADE`` + full registered DDL runs on the
    first connection checkout of the test, so a pure-logic test that never opens
    a connection leaves the schema untouched. The reset still uses one fresh
    AUTOCOMMIT connection (ADR-0016 plan section 5.1) so it never reuses a
    pooled connection that previously dropped the schema.
    """
    url = _require_test_database_url()
    if url is None:
        yield
        return
    global _test_active, _reset_done
    with _reset_lock:
        _test_active = True
        _reset_done = False
    try:
        yield
    finally:
        with _reset_lock:
            _test_active = False
            _reset_done = False


def pytest_collection_modifyitems(session, config, items):
    """Deterministic fixed-seed order shuffling for isolation regression runs.

    Enabled only when ``BYQ_TEST_SHUFFLE_SEED`` is set, so the default suite
    order is unchanged. A shuffled run that still passes proves the deferred
    reset does not depend on the previous test leaving a clean schema.
    """
    seed = os.environ.get("BYQ_TEST_SHUFFLE_SEED")
    if not seed:
        return
    import random

    random.Random(int(seed)).shuffle(items)


_PHASE_SECONDS = {"setup": 0.0, "call": 0.0, "teardown": 0.0}
_PHASE_COUNTS = {"setup": 0, "call": 0, "teardown": 0}
_SESSION_STARTED = time.perf_counter()


def pytest_runtest_logreport(report):
    """Aggregate every test phase, not just the ``--durations`` top-N."""
    if report.when in _PHASE_SECONDS:
        _PHASE_SECONDS[report.when] += report.duration
        _PHASE_COUNTS[report.when] += 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    terminalreporter.write_line(
        "[byq-timing] pytest_setup=%.2f (n=%d) pytest_call=%.2f (n=%d) "
        "pytest_teardown=%.2f (n=%d) session_wall=%.2f"
        % (
            _PHASE_SECONDS["setup"],
            _PHASE_COUNTS["setup"],
            _PHASE_SECONDS["call"],
            _PHASE_COUNTS["call"],
            _PHASE_SECONDS["teardown"],
            _PHASE_COUNTS["teardown"],
            time.perf_counter() - _SESSION_STARTED,
        )
    )
    terminalreporter.write_line(
        "[byq-timing] schema_resets=%d schema_reset_seconds=%.2f "
        "store_bootstraps=%d store_bootstrap_seconds=%.2f"
        % (
            SCHEMA_RESET_STATS["count"],
            SCHEMA_RESET_STATS["seconds"],
            STORE_BOOTSTRAP_STATS["count"],
            STORE_BOOTSTRAP_STATS["seconds"],
        )
    )
