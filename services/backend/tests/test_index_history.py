"""Focused contracts for bounded index-history readiness and cache reuse."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest

from app.data_provider import (
    IndexDailyBar,
    IndexDailyResult,
    Provenance,
    TradingCalendarResult,
    TradingSession,
)
from app.index_history import build_index_history_requirement, validate_index_history_requirement
from app.market_automation import MarketAutomationStore, sync_declared_inputs
from app.market_readiness import MarketReadinessStore


def test_index_history_requirement_normalizes_iso_and_freezes_supported_scope() -> None:
    iso = build_index_history_requirement(
        ["000905.SH", "000300.SH"], "2016-11-25", "2026-11-24",
    )
    compact = build_index_history_requirement(
        ["000300.SH", "000905.SH"], "20161125", "20261124",
    )

    assert iso == compact
    assert iso["kind"] == "index_history"
    assert iso["symbols"] == ["000300.SH", "000905.SH"]
    assert iso["start_date"] == "20161125"
    assert iso["end_date"] == "20261124"
    assert iso["declared"] == {}
    assert iso["datasets"] == ["trade_calendar", "index_daily"]
    assert validate_index_history_requirement(iso) == iso


@pytest.mark.parametrize(
    ("symbols", "start", "end"),
    [
        (["000001.SZ"], "2020-01-01", "2020-01-02"),
        (["000300.SH", "000300.SH"], "2020-01-01", "2020-01-02"),
        (["000300.SH"], "2020-01-01", "2030-01-02"),
        (["000300.SH"], "2020-02-30", "2020-03-01"),
        (["000300.SH"], "20200101", "20191231"),
    ],
)
def test_index_history_requirement_rejects_out_of_scope_values(symbols, start, end) -> None:
    with pytest.raises(ValueError):
        build_index_history_requirement(symbols, start, end)


def test_index_history_requirement_rejects_mutated_frozen_scope() -> None:
    requirement = build_index_history_requirement(["000300.SH"], "2039-01-01", "2039-01-03")
    requirement["end_date"] = "20390104"
    with pytest.raises(ValueError, match="frozen scope"):
        validate_index_history_requirement(requirement)


def _provenance(endpoint: str, seed: str, row_count: int) -> Provenance:
    return Provenance(
        provider="tushare", endpoint=endpoint,
        request_fingerprint=hashlib.sha256(seed.encode()).hexdigest(),
        retrieved_at="2039-01-04T12:00:00+00:00", cache_hit=False, row_count=row_count,
    )


class _IndexProvider:
    def __init__(self) -> None:
        self.index_calls: list[tuple[str, str, str]] = []
        self.calendar_calls: list[tuple[str, str]] = []
        self.closed_dates: set[str] = set()

    @staticmethod
    def _dates(start: str, end: str):
        first = date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
        last = date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:8]}")
        current = first
        while current <= last:
            yield current.strftime("%Y%m%d")
            current += timedelta(days=1)

    def fetch_trading_calendar(self, request) -> TradingCalendarResult:
        normalized = request.normalized()
        self.calendar_calls.append((normalized.start_date, normalized.end_date))
        sessions = []
        previous = None
        for trade_date in self._dates(normalized.start_date, normalized.end_date):
            opened = trade_date not in self.closed_dates
            sessions.append(TradingSession(trade_date, opened, previous))
            if opened:
                previous = trade_date
        return TradingCalendarResult(
            tuple(sessions), _provenance("trade_cal", f"calendar:{normalized.start_date}:{normalized.end_date}", len(sessions)),
        )

    def fetch_index_daily(self, symbol: str, start: str, end: str) -> IndexDailyResult:
        self.index_calls.append((symbol, start, end))
        bars = tuple(
            IndexDailyBar(
                symbol, trade_date, 100.0, 102.0, 99.0, 101.0, 100.0,
                1.0, 1.0, 1000.0, 100000.0,
            )
            for trade_date in self._dates(start, end)
        )
        return IndexDailyResult(
            bars, _provenance("index_daily", f"index:{symbol}:{start}:{end}", len(bars)),
        )


_requires_postgres = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set",
)


@_requires_postgres
def test_index_history_readiness_paging_and_exact_version() -> None:
    readiness = MarketReadinessStore()
    automation = MarketAutomationStore()
    provider = _IndexProvider()
    requirement = build_index_history_requirement(
        ["000905.SH", "000300.SH"], "2039-01-01", "2039-01-03",
    )
    try:
        automation.refresh_calendar(
            provider, start_date=requirement["start_date"], end_date=requirement["end_date"],
            only_missing=True,
        )
        sync_declared_inputs(requirement, provider=provider, readiness_store=readiness)
        assessment = readiness.assess(requirement)
        assert assessment["state"] == "ready"
        assert assessment["calendar_complete"] is True
        assert assessment["required_session_count"] == 3
        assert assessment["required_cell_count"] == 6
        assert assessment["missing_count"] == 0
        assert assessment["repair_plan"] == {"session_supplements": [], "full_sessions": []}

        first_page = readiness.index_history_query(requirement, limit=2)
        assert first_page["state"] == "ready"
        assert first_page["data_version"] == assessment["ready_input_sha256"]
        assert first_page["total"] == 6
        assert len(first_page["rows"]) == 2
        assert first_page["has_more"] is True
        assert len(first_page["symbol_summaries"]) == 2
        assert first_page["symbol_summaries"][0]["lowest_price"] == 99.0
        assert first_page["symbol_summaries"][0]["highest_price"] == 102.0

        next_page = readiness.index_history_query(
            requirement, offset=2, limit=2, data_version=first_page["data_version"],
        )
        assert next_page["state"] == "ready"
        assert len(next_page["rows"]) == 2
        with pytest.raises(ValueError, match="data_version is required"):
            readiness.index_history_query(requirement, offset=2, limit=2)

        stale = readiness.index_history_query(
            requirement, offset=2, limit=2, data_version="0" * 64,
        )
        assert stale["state"] == "version_changed"
        assert stale["rows"] == []
        assert stale["data_version"] is None

        provider.closed_dates.add("20390104")
        automation.refresh_calendar(provider, start_date="20390104", end_date="20390104", only_missing=True)
        closed = build_index_history_requirement(["000300.SH"], "2039-01-04", "2039-01-04")
        assert readiness.assess(closed)["state"] == "no_sessions"
        closed_page = readiness.index_history_query(closed)
        assert closed_page["state"] == "no_sessions"
        assert closed_page["data_version"] is None and closed_page["rows"] == []
    finally:
        readiness.close()
        automation.close()


@_requires_postgres
def test_overlapping_index_history_and_backtest_scopes_reuse_verified_cache() -> None:
    readiness = MarketReadinessStore()
    other_worker = MarketReadinessStore()
    automation = MarketAutomationStore()
    provider = _IndexProvider()
    first = build_index_history_requirement(["000300.SH"], "2039-01-01", "2039-01-02")
    overlap = build_index_history_requirement(["000300.SH"], "2039-01-02", "2039-01-03")
    try:
        automation.refresh_calendar(
            provider, start_date="20390101", end_date="20390103", only_missing=True,
        )
        sync_declared_inputs(first, provider=provider, readiness_store=readiness)
        assert provider.index_calls == [("000300.SH", "20390101", "20390102")]
        sync_declared_inputs(overlap, provider=provider, readiness_store=readiness)
        assert provider.index_calls == [
            ("000300.SH", "20390101", "20390102"),
            ("000300.SH", "20390103", "20390103"),
        ]
        sync_declared_inputs(overlap, provider=provider, readiness_store=readiness)
        assert len(provider.index_calls) == 2

        # The existing backtest declaration uses the same differential path.
        backtest = {"start_date": "20390101", "end_date": "20390103", "declared": {"benchmark": "000300.SH"}}
        sync_declared_inputs(backtest, provider=provider, readiness_store=readiness)
        assert len(provider.index_calls) == 2

        # Independent stores model different Data Worker processes and share the database lock.
        one = build_index_history_requirement(["000905.SH"], "2039-01-01", "2039-01-02")
        two = build_index_history_requirement(["000905.SH"], "2039-01-02", "2039-01-03")
        with ThreadPoolExecutor(2) as pool:
            jobs = [pool.submit(sync_declared_inputs, scope, provider=provider, readiness_store=store)
                    for scope, store in ((one, readiness), (two, other_worker))]
            assert sum(job.result()["index_history"] for job in jobs) == 3
        synced = [day for symbol, start, end in provider.index_calls if symbol == "000905.SH"
                  for day in provider._dates(start, end)]
        assert sorted(synced) == ["20390101", "20390102", "20390103"]
    finally:
        other_worker.close()
        readiness.close()
        automation.close()
