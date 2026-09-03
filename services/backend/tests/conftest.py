"""Shared PostgreSQL test harness for BYQ backend tests (ADR-0016 Stage 1+).

Guards:
- Tests that need PostgreSQL skip with a clear message when ``BYQ_DATABASE_URL``
  is unset (same spirit as the original ``test_db.py``).
- Any configured URL whose database name is not ``byq_domain_test`` is refused,
  so the shared test schema is never reset on the application database.

The autouse fixture resets the shared PostgreSQL test schema before every test
and runs the DDL of every store registered here. The registry grows as stores
migrate (Stage 4: + Research (all eight stores registered).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.agent_research import AgentResearchStore
from app.backtest import BacktestJobStore
from app.db import create_db_engine, run_ddl
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
    engine = create_db_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _byq_reset_schema():
    """Reset the shared PostgreSQL test schema before each test (inert when unset).

    Uses one fresh AUTOCOMMIT connection per test (ADR-0016 plan section 5.1),
    so the reset never reuses a pooled connection that previously dropped the
    schema. This avoids the PostgreSQL page-level error seen when reusing a
    long-lived engine across repeated DROP SCHEMA cycles.
    """
    url = _require_test_database_url()
    if url is None:
        yield
        return
    engine = create_db_engine(url)
    try:
        with engine.connect() as connection:
            autocommit = connection.execution_options(isolation_level="AUTOCOMMIT")
            autocommit.execute(text("DROP SCHEMA public CASCADE"))
            autocommit.execute(text("CREATE SCHEMA public"))
            run_ddl(autocommit, REGISTERED_SCHEMA_DDL)
        yield
    finally:
        engine.dispose()
