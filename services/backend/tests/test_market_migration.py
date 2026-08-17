from __future__ import annotations

import os

import pytest

from app.market_migration import migrate_market_data, migrate_market_data_from_snapshot
from app.pg_import import KEEP_NEW, VERIFY_EQUAL


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "symbol": "000001.SZ",
            "trade_date": "20240102",
            "data_source": "tushare",
            "adjust": "none",
            "asset_type": "stock",
            "open": 10.0,
            "high": 11.0,
            "low": 9.8,
            "close": 10.5,
            "volume": 1000,
            "amount": 10500,
            "volume_unit": "lots",
            "amount_unit": "thousand_cny",
        },
        {
            # BaoStock row -> must be rejected by the dry-run contract (DROP).
            "symbol": "000001.SZ",
            "trade_date": "20240103",
            "data_source": "baostock",
            "adjust": "none",
            "asset_type": "stock",
            "open": 10.0,
            "high": 11.0,
            "low": 9.8,
            "close": 10.5,
        },
        {
            # Malformed OHLC -> must be quarantined.
            "symbol": "000002.SZ",
            "trade_date": "20240104",
            "data_source": "tushare",
            "adjust": "none",
            "asset_type": "stock",
            "open": 10.0,
            "high": 9.0,
            "low": 9.8,
            "close": 10.5,
        },
    ]


def test_market_migration_validates_imports_and_verifies(byq_test_engine) -> None:
    report = migrate_market_data(
        byq_test_engine,
        _rows(),
        source_repository="BeyondQuant-community",
        source_table="market_data_daily",
        source_filter="data_source = tushare",
        target_dataset="daily_bars",
        conflict_policy=KEEP_NEW,
    )
    assert report["manifest"]["source_row_count"] == 3
    assert report["manifest"]["accepted_row_count"] == 1
    assert report["manifest"]["rejected_row_count"] == 2
    assert report["import"]["inserted"] == 1
    assert report["quarantine"], "BaoStock/malformed rows must be reported"
    assert report["verified"] is True


def test_market_migration_is_idempotent_and_conflict_policy_holds(byq_test_engine) -> None:
    snapshot = {
        "rows": [_rows()[0]],
        "source_repository": "BeyondQuant-community",
        "source_table": "market_data_daily",
        "source_filter": "data_source = tushare",
        "target_dataset": "daily_bars",
    }
    first = migrate_market_data_from_snapshot(byq_test_engine, snapshot, conflict_policy=KEEP_NEW)
    assert first["import"]["inserted"] == 1
    second = migrate_market_data_from_snapshot(byq_test_engine, snapshot, conflict_policy=KEEP_NEW)
    assert second["import"]["inserted"] == 0
    assert second["import"]["kept"] == 1
    assert second["verified"] is True

    # Same key, different amount -> VERIFY_EQUAL reports a mismatch, no overwrite.
    changed = {
        **snapshot,
        "rows": [{**_rows()[0], "amount": 99999}],
    }
    mismatch = migrate_market_data_from_snapshot(byq_test_engine, changed, conflict_policy=VERIFY_EQUAL)
    assert len(mismatch["import"]["mismatches"]) == 1
