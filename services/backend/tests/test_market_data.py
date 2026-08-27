from __future__ import annotations

import os

import pytest

from app.market_data import MarketDataStore
from app.data_provider import DailyRequest
from app.pg_import import KEEP_NEW, VERIFY_EQUAL, REPORT_MISMATCH


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "000001.SZ",
        "trade_date": "20240102",
        "open": 10.0,
        "high": 11.0,
        "low": 9.8,
        "close": 10.5,
        "volume": 1000,
        "amount": 10500,
        "adjust": "none",
        "asset_type": "stock",
        "data_source": "tushare",
        "volume_unit": "lots",
        "amount_unit": "thousand_cny",
        "provenance": {"source": "unit-test"},
    }
    row.update(overrides)
    return row


def test_market_data_import_get_and_coverage() -> None:
    store = MarketDataStore()
    report = store.import_bars([_row()], conflict_policy=KEEP_NEW)
    assert report["inserted"] == 1
    bar = store.get_bar("000001.SZ", "20240102")
    assert bar is not None
    assert bar["close"] == 10.5
    assert bar["provenance"] == {"source": "unit-test"}
    coverage = store.coverage()
    assert coverage["groups"][0]["row_count"] == 1
    assert coverage["groups"][0]["data_source"] == "tushare"
    bars = store.list_bars(["000001.SZ"], "2024-01-01", "2024-01-31")
    assert [(item["symbol"], item["trade_date"]) for item in bars] == [("000001.SZ", "20240102")]
    store.close()


def test_market_data_import_is_idempotent_and_conflict_policy_holds() -> None:
    store = MarketDataStore()
    first = store.import_bars([_row()], conflict_policy=KEEP_NEW)
    assert first["inserted"] == 1
    second = store.import_bars([_row()], conflict_policy=KEEP_NEW)
    assert second["inserted"] == 0
    assert second["kept"] == 1

    changed = store.import_bars([_row(close=10.6)], conflict_policy=KEEP_NEW)
    assert changed["inserted"] == 0
    assert changed["reported"] == 0, "KEEP_NEW keeps the existing row silently"
    assert store.get_bar("000001.SZ", "20240102")["close"] == 10.5

    mismatch = store.import_bars([_row(close=10.6)], conflict_policy=VERIFY_EQUAL)
    assert len(mismatch["mismatches"]) == 1
    assert mismatch["mismatches"][0]["reason"] == "verify_equal_mismatch"

    reported = store.import_bars([_row(close=10.6)], conflict_policy=REPORT_MISMATCH)
    assert len(reported["mismatches"]) == 1
    store.close()


def test_daily_research_reads_only_durable_verified_source_without_provider() -> None:
    store = MarketDataStore()
    store._execute(
        """INSERT INTO market_trading_sessions
           (exchange,trade_date,is_open,previous_open_date,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
           VALUES ('SSE','20240102',TRUE,'20231229','tushare','fixture',now(),'calendar-hash',now())"""
    )
    store.import_bars([_row(pre_close=10.2)], conflict_policy=KEEP_NEW)

    result = store.research_daily(DailyRequest(ts_code="000001.SZ", trade_date="20240102"))

    assert result["provenance"]["source"] == "persisted_byq"
    assert result["provenance"]["live_provider_called"] is False
    assert result["coverage"]["usable"] is True
    assert result["data"][0]["close"] == 10.5
    store.close()
