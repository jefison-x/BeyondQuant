from __future__ import annotations

import os

import pytest

from app.data_provider import (
    IndexDailyBasic,
    IndexDailyBasicResult,
    ProviderProtocolError,
    Provenance,
)
from app.index_indicators import (
    VALUE_FIELDS,
    IndexIndicatorConflict,
    IndexIndicatorStore,
)
from app.pg_import import VERIFY_EQUAL


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def provenance() -> Provenance:
    return Provenance(
        provider="tushare", endpoint="index_dailybasic", request_fingerprint="safe-fixture",
        retrieved_at="2026-09-20T00:00:00+00:00", cache_hit=False, row_count=1,
    )


def row(index_symbol: str = "000300.SH", trade_date: str = "20240102", **overrides: object) -> IndexDailyBasic:
    values: dict[str, float | None] = {field: 1.0 for field in VALUE_FIELDS}
    values.update({"total_mv": 3.0e13, "pe": 11.2})
    values.update(overrides)
    return IndexDailyBasic(index_symbol, trade_date, values)


class FakeIndexProvider:
    def __init__(self, rows: list[IndexDailyBasic], *, error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.requests: list[object] = []

    def fetch_index_daily_basic(self, request: object) -> IndexDailyBasicResult:
        normalized = request.normalized()
        self.requests.append(normalized)
        if self.error is not None:
            raise self.error
        selected = [
            item for item in self.rows
            if item.ts_code == normalized.ts_code
            and normalized.start_date <= item.trade_date <= normalized.end_date
        ]
        return IndexDailyBasicResult(tuple(selected), provenance())


def import_fixture(store: IndexIndicatorStore, rows: list[IndexDailyBasic], index_symbol: str = "000300.SH"):
    return store.import_rows(index_symbol, rows, provenance=provenance().as_dict())


def test_import_is_idempotent_and_records_units_and_provenance() -> None:
    store = IndexIndicatorStore()
    first = import_fixture(store, [row(trade_date="20240102"), row(trade_date="20240103")])
    assert first == {"inserted": 2, "kept": 0, "reported": 0, "mismatches": []}

    replay = import_fixture(store, [row(trade_date="20240102"), row(trade_date="20240103")])
    assert replay == {"inserted": 0, "kept": 2, "reported": 0, "mismatches": []}
    assert store.latest_trade_date("000300.SH") == "20240103"

    stored = store._fetch_one(
        "SELECT * FROM market_index_daily_basic WHERE index_symbol='000300.SH' AND trade_date='20240102'"
    )
    assert stored is not None
    assert stored["pe"] == 11.2
    assert stored["total_mv"] == 3.0e13
    assert stored["units_json"] == {
        "total_mv": "cny", "float_mv": "cny", "total_share": "share", "float_share": "share",
        "free_share": "share", "turnover_rate": "percent", "turnover_rate_f": "percent",
        "pe": "ratio", "pe_ttm": "ratio", "pb": "ratio",
    }
    assert stored["data_source"] == "tushare"
    assert stored["provenance_json"]["endpoint"] == "index_dailybasic"
    assert stored["content_sha256"]


def test_import_verify_equal_reports_mismatch_without_overwrite() -> None:
    store = IndexIndicatorStore()
    import_fixture(store, [row(trade_date="20240102")])
    report = store.import_rows(
        "000300.SH", [row(trade_date="20240102", pe=99.9)],
        provenance=provenance().as_dict(), conflict_policy=VERIFY_EQUAL,
    )
    assert report["inserted"] == 0 and report["kept"] == 1 and report["reported"] == 1
    stored = store._fetch_one(
        "SELECT pe FROM market_index_daily_basic WHERE index_symbol='000300.SH' AND trade_date='20240102'"
    )
    assert stored is not None and stored["pe"] == 11.2


def test_import_rejects_mismatched_duplicate_or_nonfinite_rows() -> None:
    store = IndexIndicatorStore()
    with pytest.raises(ProviderProtocolError, match="another index"):
        import_fixture(store, [row(index_symbol="000905.SH")])
    with pytest.raises(ProviderProtocolError, match="duplicate"):
        import_fixture(store, [row(trade_date="20240102"), row(trade_date="20240102")])
    with pytest.raises(ProviderProtocolError, match="non-finite"):
        import_fixture(store, [row(trade_date="20240102", pe=float("inf"))])
    with pytest.raises(ValueError, match="conflict_policy"):
        store.import_rows(
            "000300.SH", [row()], provenance=provenance().as_dict(), conflict_policy="last_write_wins",
        )
    with pytest.raises(ValueError, match="invalid format"):
        import_fixture(store, [row()], index_symbol="BADCODE")


def test_incremental_sync_is_idempotent_and_resumes_after_latest() -> None:
    store = IndexIndicatorStore()
    rows = [row(trade_date="20240102"), row(trade_date="20240103")]
    provider = FakeIndexProvider(rows)
    job, created = store.create_sync_job({
        "index_symbol": "000300.SH", "mode": "incremental",
        "start_date": "20240102", "end_date": "20240103", "idempotency_key": "index-sync-1",
    }, actor="tester")
    assert created is True
    finished = store.run_sync_job(job["job_id"], provider_factory=lambda: provider)
    assert finished["status"] == "completed"
    assert finished["rows_inserted"] == 2 and finished["effective_start_date"] == "20240102"
    assert len(provider.requests) == 1

    resumed, _ = store.create_sync_job({
        "index_symbol": "000300.SH", "mode": "incremental",
        "start_date": "20240102", "end_date": "20240103", "idempotency_key": "index-sync-2",
    }, actor="tester")
    already = store.run_sync_job(resumed["job_id"], provider_factory=lambda: provider)
    assert already["status"] == "completed"
    assert already["rows_inserted"] == 0 and already["rows_kept"] == 0
    assert len(provider.requests) == 1  # no redundant provider pull

    replay, _ = store.create_sync_job({
        "index_symbol": "000300.SH", "mode": "range",
        "start_date": "20240102", "end_date": "20240103", "idempotency_key": "index-sync-3",
    }, actor="tester")
    replayed = store.run_sync_job(replay["job_id"], provider_factory=lambda: provider)
    assert replayed["rows_inserted"] == 0 and replayed["rows_kept"] == 2
    assert len(provider.requests) == 2


def test_terminal_rerun_does_not_refetch_or_reinsert() -> None:
    store = IndexIndicatorStore()
    provider = FakeIndexProvider([row(trade_date="20240102"), row(trade_date="20240103")])
    job, _ = store.create_sync_job({
        "index_symbol": "000300.SH", "mode": "incremental",
        "start_date": "20240102", "end_date": "20240103", "idempotency_key": "terminal-rerun-1",
    }, actor="tester")
    finished = store.run_sync_job(job["job_id"], provider_factory=lambda: provider)
    assert finished["status"] == "completed" and finished["rows_inserted"] == 2

    fingerprint_before = store.persisted_fingerprint("000300.SH")
    calls_before = len(provider.requests)
    terminal = store.run_sync_job(job["job_id"], provider_factory=lambda: provider)
    calls_after = len(provider.requests)
    fingerprint_after = store.persisted_fingerprint("000300.SH")

    # No refetch and no reinsert: the terminal rerun short-circuits before the
    # provider and before any import, so the persisted digest is unchanged.
    assert calls_after - calls_before == 0
    assert terminal["job_id"] == job["job_id"]
    assert terminal["status"] == finished["status"] == "completed"
    assert fingerprint_after == fingerprint_before
    assert fingerprint_after["row_count"] == 2
    # The rerun reports the first run's *cumulative* persisted counters. It must
    # not be read as a rerun insertion delta (e.g. 2 fresh inserts).
    assert terminal["rows_inserted"] == finished["rows_inserted"] == 2
    assert terminal["rows_inserted"] != calls_after - calls_before


def test_persisted_fingerprint_is_sensitive_to_real_writes() -> None:
    store = IndexIndicatorStore()
    before = store.persisted_fingerprint()
    import_fixture(store, [row(trade_date="20240102")])
    after = store.persisted_fingerprint()
    assert before != after
    assert before["row_count"] == 0 and after["row_count"] == 1
    per_index = store.persisted_fingerprint("000300.SH")
    assert per_index == after
    assert store.persisted_fingerprint("000905.SH")["content_sha256"] != per_index["content_sha256"]


def test_sync_idempotency_key_reuse_and_conflict() -> None:
    store = IndexIndicatorStore()
    payload = {
        "index_symbol": "000300.SH", "mode": "range",
        "start_date": "20240102", "end_date": "20240105", "idempotency_key": "index-key",
    }
    job, created = store.create_sync_job(dict(payload), actor="tester")
    assert created is True
    again, created_again = store.create_sync_job(dict(payload), actor="tester")
    assert created_again is False and again["job_id"] == job["job_id"]
    with pytest.raises(IndexIndicatorConflict, match="reused"):
        store.create_sync_job({**payload, "index_symbol": "000905.SH"}, actor="tester")
    with pytest.raises(ValueError, match="idempotency_key"):
        store.create_sync_job({**payload, "idempotency_key": "bad key!"}, actor="tester")

    failed = store.run_sync_job(
        job["job_id"], provider_factory=lambda: FakeIndexProvider([], error=ProviderProtocolError("boom")),
    )
    assert failed["status"] == "failed"

    def exploding_factory():
        raise AssertionError("terminal jobs must not call the provider again")

    terminal = store.run_sync_job(job["job_id"], provider_factory=exploding_factory)
    assert terminal["status"] == "failed"


def test_readiness_is_derived_from_store_and_fails_closed() -> None:
    store = IndexIndicatorStore()
    store._execute("""INSERT INTO market_trading_sessions
        (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
        VALUES ('20240102','SSE',TRUE,'tushare','cal',now(),'cal2',now()),
               ('20240103','SSE',TRUE,'tushare','cal',now(),'cal3',now()),
               ('20240104','SSE',TRUE,'tushare','cal',now(),'cal4',now())""")
    import_fixture(store, [row(trade_date="20240102"), row(trade_date="20240103")])

    ready = store.readiness(
        index_symbols=["000300.SH"], start_date="20240102", end_date="20240103", fields=["pe", "total_mv"],
    )
    assert ready["coverage"]["usable"] is True
    assert ready["coverage"]["calendar_verified"] is True
    assert len(ready["rows"]) == 2
    assert ready["units"] == {"pe": "ratio", "total_mv": "cny"}

    gap = store.readiness(
        index_symbols=["000300.SH"], start_date="20240102", end_date="20240104", fields=["pe"],
    )
    assert gap["coverage"]["usable"] is False
    assert gap["coverage"]["missing"] == [
        {"index_symbol": "000300.SH", "trade_date": "20240104", "reason": "index_daily_basic_unavailable"}
    ]

    import_fixture(store, [row(trade_date="20240104", pb=None)])
    nulled = store.readiness(
        index_symbols=["000300.SH"], start_date="20240102", end_date="20240104", fields=["pb"],
    )
    assert nulled["coverage"]["usable"] is False
    assert nulled["coverage"]["missing_fields"] == [
        {"index_symbol": "000300.SH", "trade_date": "20240104", "fields": ["pb"]}
    ]

    with pytest.raises(ValueError, match="unsupported"):
        store.readiness(index_symbols=["000300.SH"], start_date="20240102", end_date="20240103", fields=["close"])
    with pytest.raises(ValueError, match="unique"):
        store.readiness(index_symbols=["000300.SH", "000300.SH"], start_date="20240102", end_date="20240103", fields=["pe"])


def test_readiness_without_calendar_is_not_verified() -> None:
    store = IndexIndicatorStore()
    import_fixture(store, [row(trade_date="20240102")])
    result = store.readiness(
        index_symbols=["000300.SH"], start_date="20240102", end_date="20240102", fields=["pe"],
    )
    assert result["coverage"]["calendar_verified"] is False
    assert result["coverage"]["usable"] is False


def test_market_readiness_integrates_index_valuation_evidence() -> None:
    from app.market_readiness import MarketReadinessStore

    store = MarketReadinessStore()
    store._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,
         retrieved_at,requested_by) VALUES ('sms_ready','tushare','stock_basic','ready_dataset',
         'ready_request','[\"L\"]',1,now(),'test')""")
    store._execute("""INSERT INTO security_master_snapshot_members
        (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,asset_type,content_sha256)
        VALUES ('sms_ready','000001.SZ','000001','Fixture','SZSE','L','20240102','stock','member')""")
    store._execute("""INSERT INTO market_trading_sessions
        (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
        VALUES ('20240102','SSE',TRUE,'tushare','cal',now(),'cal2',now()),
               ('20240103','SSE',TRUE,'tushare','cal',now(),'cal3',now())""")
    store._execute("""INSERT INTO market_daily_bars
        (symbol,trade_date,open,high,low,close,adjust,asset_type,data_source,
         content_sha256,provenance_json,imported_at)
        VALUES ('000001.SZ','20240102',10,11,9,10,'none','stock','tushare','bar2','{}',now())""")
    store._execute("""INSERT INTO market_daily_status
        (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
         provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20240102',FALSE,9.5,11,9,'tushare','{}','status2',now()),
               ('000001.SZ','20240103',TRUE,NULL,NULL,NULL,'tushare','{}','status3',now())""")
    store._execute("""INSERT INTO market_adjustment_factors
        (symbol,trade_date,adj_factor,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20240102',1.0,'tushare','{}','factor2',now())""")
    store._execute("""INSERT INTO market_session_supplement_completeness
        (trade_date,adjustment_complete,corporate_actions_complete,factor_row_count,
         corporate_action_row_count,content_sha256,provenance_json,verified_at)
        VALUES ('20240102',TRUE,TRUE,1,0,'supp2','{}',now()),
               ('20240103',TRUE,TRUE,0,0,'supp3','{}',now())""")
    valuation = IndexIndicatorStore()
    valuation.import_rows(
        "000300.SH", [row(trade_date="20240102"), row(trade_date="20240103")],
        provenance=provenance().as_dict(),
    )
    requirement = store.requirement(
        symbols=["000001.SZ"], start_date="2024-01-02", end_date="2024-01-03",
        membership_fingerprint="a" * 64, security_master_snapshot_id="sms_ready",
        data_requirements={"index_valuation": {"index_symbol": "000300.SH", "fields": ["pe", "total_mv"]}},
    )

    ready = store.assess(requirement)
    assert ready["state"] == "ready"
    assert ready["ready_input_sha256"]

    store._execute("DELETE FROM market_index_daily_basic WHERE index_symbol='000300.SH' AND trade_date='20240103'")
    degraded = store.assess(requirement)
    assert degraded["state"] == "partial"
    assert degraded["missing_by_dataset"]["index_daily_basic"] == 1

    valuation.import_rows(
        "000300.SH", [row(trade_date="20240103", pe=None)], provenance=provenance().as_dict(),
    )
    nulled = store.assess(requirement)
    assert nulled["missing_by_dataset"]["index_daily_basic_fields"] == 1

    with pytest.raises(ValueError, match="unsupported field"):
        store.assess(store.requirement(
            symbols=["000001.SZ"], start_date="2024-01-02", end_date="2024-01-03",
            membership_fingerprint="a" * 64, security_master_snapshot_id="sms_ready",
            data_requirements={"index_valuation": {"index_symbol": "000300.SH", "fields": ["close"]}},
        ))


def test_coverage_reflects_persisted_rows_without_a_provider_call() -> None:
    store = IndexIndicatorStore()
    assert store.coverage()["quality"] == "empty"
    import_fixture(store, [row(trade_date="20240102"), row(trade_date="20240103")])
    import_fixture(store, [row(index_symbol="000905.SH", trade_date="20240102")], index_symbol="000905.SH")

    coverage = store.coverage()
    assert coverage["quality"] == "observed"
    assert coverage["row_count"] == 3
    assert coverage["index_count"] == 2
    assert coverage["date_min"] == "20240102" and coverage["date_max"] == "20240103"
    assert coverage["completeness_claimed"] is False
    assert {group["index_symbol"] for group in coverage["groups"]} == {"000300.SH", "000905.SH"}
