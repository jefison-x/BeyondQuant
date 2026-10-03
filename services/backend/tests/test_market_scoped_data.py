from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.data_provider import AdjustmentFactor
from app.market_automation import MarketAutomationConflict, MarketAutomationStore
from app.market_readiness import MarketReadinessStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)

SOURCE_BUNDLE_SHA256 = "b6208258fc9725d56e2fa78b7f1c31b460d5bce9b0fd26a32178549246237eab"


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _provider_provenance(endpoint: str, trade_date: str) -> dict[str, object]:
    return {
        "provider": "tushare",
        "endpoint": endpoint,
        "request_fingerprint": _hash({"endpoint": endpoint, "trade_date": trade_date}),
        "retrieved_at": "2024-06-01T01:00:00+00:00",
        "cache_hit": False,
        "row_count": 1,
    }


def _factor(symbol: str, trade_date: str, factor: float = 1.0) -> dict[str, object]:
    provenance = _provider_provenance("adj_factor", trade_date)
    canonical = {
        "symbol": symbol,
        "trade_date": trade_date,
        "adj_factor": factor,
        "data_source": "tushare",
        "provenance": provenance,
    }
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "adj_factor": factor,
        "data_source": "tushare",
        "provenance_json": provenance,
        "content_sha256": _hash(canonical),
    }


def _action(symbol: str, trade_date: str) -> dict[str, object]:
    provenance = _provider_provenance("dividend", trade_date)
    canonical = {
        "symbol": symbol,
        "end_date": "20231231",
        "announcement_date": "20240101",
        "implementation_announcement_date": "20240102",
        "record_date": "20240101",
        "ex_date": trade_date,
        "pay_date": None,
        "share_listing_date": None,
        "cash_dividend_per_share": 0.1,
        "cash_dividend_gross": 0.1,
        "share_ratio": 0.0,
        "data_source": "tushare",
        "provenance": provenance,
    }
    return {
        **{key: value for key, value in canonical.items() if key != "provenance"},
        "provenance_json": provenance,
        "content_sha256": _hash(canonical),
    }


def _source_completeness(trade_date: str) -> dict[str, object]:
    # These are source-wide figures from the verified source proof. They must
    # remain attestation metadata and must never become target scoped counts.
    return {
        "trade_date": trade_date,
        "adjustment_complete": True,
        "corporate_actions_complete": True,
        "factor_row_count": 5_364,
        "corporate_action_row_count": 17,
        # This original global digest is not derivable from one-symbol rows.
        "content_sha256": hashlib.sha256(f"source-global-{trade_date}".encode()).hexdigest(),
        "provenance_json": {
            "adjustment_factors": _provider_provenance("adj_factor", trade_date),
            "corporate_actions": _provider_provenance("dividend", trade_date),
        },
        "verified_at": "2024-06-01T01:01:00+00:00",
    }


def _calendar_rows(
    dates: list[str], *, open_dates: set[str] | None = None, fingerprint: str | None = None,
) -> list[dict[str, object]]:
    opens = set(dates) if open_dates is None else open_dates
    fingerprint = fingerprint or _hash("calendar-fingerprint")
    previous_open: str | None = None
    rows: list[dict[str, object]] = []
    for trade_date in dates:
        is_open = trade_date in opens
        canonical = {
            "trade_date": trade_date,
            "exchange": "SSE",
            "is_open": is_open,
            "previous_open_date": previous_open,
        }
        rows.append({
            **canonical,
            "data_source": "tushare",
            "request_fingerprint": fingerprint,
            "retrieved_at": "2024-06-01T00:00:00+00:00",
            "content_sha256": _hash(canonical),
            "updated_at": "2024-06-01T00:00:00+00:00",
        })
        if is_open:
            previous_open = trade_date
    return rows


def _import_calendar(dates: list[str]) -> MarketAutomationStore:
    store = MarketAutomationStore()
    store.import_verified_logical_calendar(
        sessions=_calendar_rows(dates),
        start_date=dates[0],
        end_date=dates[-1],
        source_bundle_sha256=SOURCE_BUNDLE_SHA256,
    )
    return store


def _seed_target_calendar_for_readiness(store: MarketReadinessStore, dates: list[str]) -> None:
    """Keep scoped-supplement RED independent from the separate calendar importer."""
    for row in _calendar_rows(dates):
        store._execute("""INSERT INTO market_trading_sessions
            (trade_date,exchange,is_open,previous_open_date,data_source,request_fingerprint,
             retrieved_at,content_sha256,updated_at)
            VALUES (:trade_date,:exchange,:is_open,:previous_open_date,:data_source,
                    :request_fingerprint,:retrieved_at,:content_sha256,:updated_at)""", row)


def _seed_ready_market(
    store: MarketReadinessStore, *, symbols: list[str], dates: list[str], snapshot_id: str = "sms_scoped",
) -> dict[str, object]:
    store._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,
         retrieved_at,requested_by) VALUES (:snapshot,'tushare','stock_basic','dataset',
         'request','[\"L\"]',:count,now(),'test')""",
        {"snapshot": snapshot_id, "count": len(symbols)})
    for symbol in symbols:
        store._execute("""INSERT INTO security_master_snapshot_members
            (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,asset_type,content_sha256)
            VALUES (:snapshot,:symbol,:local,:name,:exchange,'L','20230101','stock',:sha)""",
            {"snapshot": snapshot_id, "symbol": symbol, "local": symbol[:6],
             "name": symbol, "exchange": "SZSE" if symbol.endswith("SZ") else "SSE",
             "sha": f"member-{symbol}"})
        for trade_date in dates:
            store._execute("""INSERT INTO market_daily_bars
                (symbol,trade_date,open,high,low,close,adjust,asset_type,data_source,
                 content_sha256,provenance_json,imported_at)
                VALUES (:symbol,:date,10,11,9,10,'none','stock','tushare',:sha,'{}',now())""",
                {"symbol": symbol, "date": trade_date, "sha": f"bar-{symbol}-{trade_date}"})
            store._execute("""INSERT INTO market_daily_status
                (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
                 provenance_json,content_sha256,updated_at)
                VALUES (:symbol,:date,FALSE,9.5,11,9,'tushare','{}',:sha,now())""",
                {"symbol": symbol, "date": trade_date, "sha": f"status-{symbol}-{trade_date}"})
    return store.requirement(
        symbols=symbols,
        start_date=dates[0],
        end_date=dates[-1],
        membership_fingerprint="a" * 64,
        security_master_snapshot_id=snapshot_id,
    )


def _scoped_import(
    store: MarketReadinessStore,
    *,
    symbol: str,
    dates: list[str],
    factors: list[dict[str, object]] | None = None,
    actions: list[dict[str, object]] | None = None,
    source_bundle_sha256: str = SOURCE_BUNDLE_SHA256,
) -> dict[str, object]:
    return store.import_scoped_market_supplements(
        symbol=symbol,
        start_date=dates[0],
        end_date=dates[-1],
        factors=factors if factors is not None else [_factor(symbol, date) for date in dates],
        actions=actions if actions is not None else [],
        source_completeness=[_source_completeness(date) for date in dates],
        source_bundle_sha256=source_bundle_sha256,
    )


def test_scoped_supplement_import_is_idempotent_and_never_claims_other_symbols() -> None:
    dates = ["20240102", "20240103"]
    readiness = MarketReadinessStore()
    _seed_target_calendar_for_readiness(readiness, dates)
    requirement = _seed_ready_market(
        readiness, symbols=["000001.SZ", "600000.SH"], dates=dates,
    )
    # Existing rows for the other symbol must survive a single-symbol import.
    for trade_date in dates:
        readiness._execute("""INSERT INTO market_adjustment_factors
            (symbol,trade_date,adj_factor,data_source,provenance_json,content_sha256,updated_at)
            VALUES ('600000.SH',:date,1,'tushare','{}',:sha,now())""",
            {"date": trade_date, "sha": f"other-factor-{trade_date}"})

    actions = [_action("000001.SZ", dates[0])]
    _scoped_import(readiness, symbol="000001.SZ", dates=dates, actions=actions)
    replay = _scoped_import(readiness, symbol="000001.SZ", dates=dates, actions=actions)

    assert replay["inserted_factor_count"] == 0
    assert readiness._execute("""SELECT trade_date,factor_row_count,corporate_action_row_count,
            source_completeness_json->>'factor_row_count' AS source_factor_count,
            source_completeness_json->>'corporate_action_row_count' AS source_action_count
        FROM market_symbol_supplement_completeness WHERE symbol='000001.SZ' ORDER BY trade_date""") == [
        {"trade_date": date, "factor_row_count": 1,
         "corporate_action_row_count": 1 if date == dates[0] else 0,
         "source_factor_count": "5364", "source_action_count": "17"}
        for date in dates
    ]
    assert readiness._execute("""SELECT COUNT(*) AS count FROM market_adjustment_factors
        WHERE symbol='600000.SH' AND trade_date BETWEEN :start AND :end""",
        {"start": dates[0], "end": dates[-1]}) == [{"count": 2}]

    single_symbol = readiness.requirement(
        symbols=["000001.SZ"], start_date=dates[0], end_date=dates[-1],
        membership_fingerprint="b" * 64, security_master_snapshot_id="sms_scoped",
    )
    scoped_ready = readiness.assess(single_symbol)
    assert scoped_ready["state"] == "ready"
    assert scoped_ready["ready_input_sha256"]

    readiness._execute("""UPDATE market_corporate_actions SET share_ratio=0.25
        WHERE symbol='000001.SZ' AND ex_date=:date""", {"date": dates[0]})
    changed_action = readiness.assess(single_symbol)
    assert changed_action["state"] != "ready"
    assert changed_action["ready_input_sha256"] is None

    multi_symbol = readiness.assess(requirement)
    assert multi_symbol["state"] != "ready"
    assert multi_symbol["ready_input_sha256"] is None
    assert any(item["symbol"] == "600000.SH" for item in multi_symbol["missing"])
    readiness.close()


def test_scoped_proof_is_rehashed_and_native_full_import_invalidates_it() -> None:
    date = "20240102"
    readiness = MarketReadinessStore()
    _seed_target_calendar_for_readiness(readiness, [date])
    requirement = _seed_ready_market(
        readiness, symbols=["000001.SZ"], dates=[date], snapshot_id="sms_rehash",
    )
    readiness._execute("""INSERT INTO market_session_supplement_completeness
        (trade_date,adjustment_complete,corporate_actions_complete,factor_row_count,
         corporate_action_row_count,content_sha256,provenance_json,verified_at)
        VALUES (:date,FALSE,FALSE,0,0,'incomplete-global','{}',now())""", {"date": date})
    _scoped_import(readiness, symbol="000001.SZ", dates=[date])

    scoped_ready = readiness.assess(requirement)
    assert scoped_ready["state"] == "ready"
    scoped_ready_sha256 = scoped_ready["ready_input_sha256"]
    readiness._execute("""UPDATE market_adjustment_factors SET adj_factor=2.0
        WHERE symbol='000001.SZ' AND trade_date=:date""", {"date": date})
    stale = readiness.assess(requirement)
    assert stale["state"] != "ready"
    assert stale["ready_input_sha256"] is None

    readiness.import_session_supplements(
        date,
        factors=[
            AdjustmentFactor("000001.SZ", date, 1.0),
            AdjustmentFactor("600000.SH", date, 1.0),
        ],
        actions=[],
        provenance={
            "adjustment_factors": _provider_provenance("adj_factor", date),
            "corporate_actions": _provider_provenance("dividend", date),
        },
    )
    assert readiness._fetch_one("""SELECT symbol FROM market_symbol_supplement_completeness
        WHERE symbol='000001.SZ' AND trade_date=:date""", {"date": date}) is None
    assert readiness._fetch_one("""SELECT factor_row_count,corporate_action_row_count
        FROM market_session_supplement_completeness WHERE trade_date=:date""",
        {"date": date}) == {"factor_row_count": 2, "corporate_action_row_count": 0}
    assert readiness._execute("SELECT symbol FROM market_adjustment_factors ORDER BY symbol") == [
        {"symbol": "000001.SZ"}, {"symbol": "600000.SH"},
    ]
    native_ready = readiness.assess(requirement)
    assert native_ready["state"] == "ready"
    assert native_ready["ready_input_sha256"] != scoped_ready_sha256
    readiness.close()


def test_scoped_import_rejects_hash_scope_and_conflicting_rewrites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    date = "20240102"
    raced_date = "20240103"
    readiness = MarketReadinessStore()
    _seed_target_calendar_for_readiness(readiness, [date, raced_date])
    _seed_ready_market(readiness, symbols=["000001.SZ"], dates=[date], snapshot_id="sms_conflict")
    original = _factor("000001.SZ", date, 1.0)

    with pytest.raises(ValueError, match="hash"):
        corrupt = dict(original, adj_factor=2.0)
        readiness.import_scoped_market_supplements(
            symbol="000001.SZ", start_date=date, end_date=date,
            factors=[corrupt], actions=[], source_completeness=[_source_completeness(date)],
            source_bundle_sha256=SOURCE_BUNDLE_SHA256,
        )
    with pytest.raises(ValueError, match="scope"):
        foreign = _factor("600000.SH", date)
        readiness.import_scoped_market_supplements(
            symbol="000001.SZ", start_date=date, end_date=date,
            factors=[foreign], actions=[], source_completeness=[_source_completeness(date)],
            source_bundle_sha256=SOURCE_BUNDLE_SHA256,
        )

    _scoped_import(readiness, symbol="000001.SZ", dates=[date])
    conflicting = _factor("000001.SZ", date, 2.0)
    with pytest.raises(ValueError, match="conflict"):
        _scoped_import(
            readiness, symbol="000001.SZ", dates=[date], factors=[conflicting],
            source_bundle_sha256="c" * 64,
        )
    assert readiness._fetch_one("""SELECT adj_factor FROM market_adjustment_factors
        WHERE symbol='000001.SZ' AND trade_date=:date""", {"date": date}) == {"adj_factor": 1.0}
    assert readiness._fetch_one("""SELECT COUNT(*) AS count FROM market_symbol_supplement_completeness
        WHERE symbol='000001.SZ' AND trade_date=:date""", {"date": date}) == {"count": 1}

    # Change the already-prevalidated calendar row immediately before the
    # import transaction. The importer must lock and recheck the exact rows
    # before inserting any factor or completeness proof.
    calendar_writer = MarketAutomationStore()
    original_transaction = readiness._transaction

    @contextmanager
    def change_calendar_before_transaction():
        calendar_writer._execute("""UPDATE market_trading_sessions SET is_open=FALSE
            WHERE trade_date=:date""", {"date": raced_date})
        with original_transaction() as connection:
            yield connection

    monkeypatch.setattr(readiness, "_transaction", change_calendar_before_transaction)
    try:
        with pytest.raises(ValueError, match="calendar changed"):
            _scoped_import(readiness, symbol="000001.SZ", dates=[raced_date])
    finally:
        calendar_writer.close()
    assert readiness._fetch_one("""SELECT symbol FROM market_adjustment_factors
        WHERE symbol='000001.SZ' AND trade_date=:date""", {"date": raced_date}) is None
    assert readiness._fetch_one("""SELECT symbol FROM market_symbol_supplement_completeness
        WHERE symbol='000001.SZ' AND trade_date=:date""", {"date": raced_date}) is None
    readiness.close()


def test_logical_calendar_is_providerless_exact_and_conflicts_are_atomic() -> None:
    dates = ["20240102", "20240103", "20240104"]
    first_rows = _calendar_rows(dates)
    store = MarketAutomationStore()
    imported = store.import_verified_logical_calendar(
        sessions=first_rows, start_date=dates[0], end_date=dates[-1],
        source_bundle_sha256=SOURCE_BUNDLE_SHA256,
    )
    assert imported["inserted_count"] == len(dates)
    replay = store.import_verified_logical_calendar(
        sessions=first_rows, start_date=dates[0], end_date=dates[-1],
        source_bundle_sha256=SOURCE_BUNDLE_SHA256,
    )
    assert replay["inserted_count"] == 0
    assert store._execute("""SELECT trade_date,exchange,is_open,previous_open_date,
            data_source,request_fingerprint,retrieved_at,content_sha256
        FROM market_trading_sessions ORDER BY trade_date""") == [
        {key: row[key] for key in (
            "trade_date", "exchange", "is_open", "previous_open_date", "data_source",
            "request_fingerprint", "retrieved_at", "content_sha256",
        )}
        for row in first_rows
    ]

    incomplete = first_rows[:-1]
    with pytest.raises(ValueError, match="complete date range"):
        store.import_verified_logical_calendar(
            sessions=incomplete, start_date=dates[0], end_date=dates[-1],
            source_bundle_sha256="d" * 64,
        )
    changed_rows = _calendar_rows(dates, fingerprint=_hash("different-source-fingerprint"))
    barrier = Barrier(2)

    def import_conflicting(rows: list[dict[str, object]], bundle_hash: str) -> str:
        writer = MarketAutomationStore()
        try:
            barrier.wait(timeout=10)
            try:
                writer.import_verified_logical_calendar(
                    sessions=rows, start_date=dates[0], end_date=dates[-1],
                    source_bundle_sha256=bundle_hash,
                )
                return "accepted"
            except MarketAutomationConflict:
                return "conflict"
        finally:
            writer.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(
            lambda args: import_conflicting(*args),
            [(first_rows, "e" * 64), (changed_rows, "f" * 64)],
        ))
    assert outcomes.count("conflict") == 1
    assert outcomes.count("accepted") == 1
    assert store._execute("SELECT request_fingerprint FROM market_trading_sessions") == [
        {"request_fingerprint": _hash("calendar-fingerprint")}
    ] * len(dates)
    store.close()
