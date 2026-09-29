"""Fresh BYQ 0.10 schema excludes one-time old-database migration state."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required",
)


def test_fresh_baseline_keeps_domain_facts_without_old_migration_tables(byq_test_engine) -> None:
    kept = (
        "users", "workspaces", "workspace_memberships", "workspace_reset_receipts",
        "research_tasks", "artifacts", "backtest_jobs", "ml_training_runs",
        "paper_accounts", "paper_orders", "paper_fills", "paper_ledger_entries",
        "stock_pools", "stock_pool_snapshots",
    )
    retired = (
        "workspace_migration_runs", "workspace_migration_quarantine",
        "paper_domain_migration_runs", "paper_domain_migration_quarantine",
        "stock_pool_migration_runs", "stock_pool_migration_quarantine",
    )
    with byq_test_engine.connect() as connection:
        for table in kept:
            assert connection.execute(text("SELECT to_regclass(:table)"), {"table": table}).scalar_one() is not None
        for table in retired:
            assert connection.execute(text("SELECT to_regclass(:table)"), {"table": table}).scalar_one() is None
        for table in ("research_tasks", "artifacts", "backtest_jobs", "paper_accounts"):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
