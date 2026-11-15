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


@pytest.mark.parametrize(
    "calendar,bar_dates,suspended,symbol,verified,usable,reason",
    [
        ([("20240101", False), ("20240103", True)], ["20240103"], False,
         "000001.SZ", False, False, "calendar_incomplete"),
        ([("20240101", False), ("20240102", True), ("20240103", False)], ["20240102"], False,
         "000001.SZ", True, True, "complete"),
        ([("20240101", False), ("20240102", False), ("20240103", False)], [], False,
         "000001.SZ", True, False, "no_open_session"),
        ([("20240102", True)], [], False,
         "000001.SZ", True, False, "daily_bars_missing"),
        ([("20240102", True)], [], True,
         "000001.SZ", True, True, "complete"),
        ([("20240102", True)], ["20240102"], False,
         None, True, False, "symbol_universe_unverified"),
    ],
)
def test_daily_research_scope_and_calendar_completeness(
    calendar, bar_dates, suspended, symbol, verified, usable, reason,
) -> None:
    store = MarketDataStore()
    for date, is_open in calendar:
        store._execute("""INSERT INTO market_trading_sessions
            (exchange,trade_date,is_open,previous_open_date,data_source,request_fingerprint,
             retrieved_at,content_sha256,updated_at)
            VALUES ('SSE',:date,:is_open,NULL,'tushare','fixture',now(),:sha,now())""",
            {"date": date, "is_open": is_open, "sha": "calendar-" + date})
    for date in bar_dates:
        store.import_bars([_row(trade_date=date)], conflict_policy=KEEP_NEW)
    if suspended:
        store._execute("""INSERT INTO market_daily_status
            (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
             provenance_json,content_sha256,updated_at)
            VALUES ('000001.SZ','20240102',TRUE,10,11,9,'tushare','{}','suspended',now())""")
    start, end = calendar[0][0], calendar[-1][0]
    request = (DailyRequest(ts_code=symbol, start_date=start, end_date=end)
               if symbol else DailyRequest(trade_date=start))
    result = store.research_daily(request)
    coverage, scope = result["coverage"], result["evidence_scope"]
    assert coverage["calendar_verified"] is verified
    assert coverage["usable"] is usable
    assert coverage["reason"] == reason
    assert scope["requested_symbol"] == symbol
    assert scope["requested_start_date"] == start
    assert scope["requested_end_date"] == end
    assert scope["requested_range_checked"] is True
    assert scope["outside_requested_range_checked"] is False
    assert scope["returned_rows"] == len(bar_dates)
    assert scope["returned_date_min"] == (min(bar_dates) if bar_dates else None)
    assert scope["returned_date_max"] == (max(bar_dates) if bar_dates else None)
    if not verified:
        assert coverage["missing_calendar_dates"] == ["20240102"]
        assert coverage["missing_calendar_count"] == 1
        assert coverage["missing"] == []  # Not a known-open day; no fabricated bar gap.
    if reason == "daily_bars_missing":
        assert coverage["missing"] == [
            {"symbol": "000001.SZ", "trade_date": "20240102", "reason": "daily_bar_unavailable"}
        ]
    assert coverage["suspended_sessions"] == (["20240102"] if suspended else [])
    store.close()
