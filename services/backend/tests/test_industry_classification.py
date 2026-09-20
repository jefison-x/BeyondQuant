from __future__ import annotations

import os

import pytest

from app.data_provider import (
    IndexClassify,
    IndexClassifyResult,
    IndexMember,
    IndexMemberAllResult,
    Provenance,
)
from app.industry_classification import (
    IndustryClassificationConflict,
    IndustryClassificationStore,
)
from app.pg_import import VERIFY_EQUAL


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def provenance(endpoint: str = "index_member_all") -> Provenance:
    return Provenance(
        provider="tushare", endpoint=endpoint, request_fingerprint="safe-fixture",
        retrieved_at="2026-09-20T00:00:00+00:00", cache_hit=False, row_count=1,
    )


def classify(
    index_code: str = "801050.SI", *, src: str = "SW2021", level: str = "L1",
    parent_code: str = "0",
) -> IndexClassify:
    return IndexClassify(src, index_code, "有色金属", parent_code, level, "110000", "1")


def member(
    ts_code: str = "601899.SH", *, l3_code: str = "850531.SI",
    in_date: str = "20080407", out_date: str | None = None, is_new: str = "Y",
) -> IndexMember:
    return IndexMember(
        "801050.SI", "有色金属", "801053.SI", "贵金属", l3_code, "黄金",
        ts_code, "紫金矿业", in_date, out_date, is_new,
    )


class FakeIndustryProvider:
    def __init__(self, *, classify_rows=None, member_rows=None) -> None:
        self.classify_rows = list(classify_rows or [])
        self.member_rows = list(member_rows or [])
        self.calls: list[object] = []

    def fetch_index_classify(self, request: object) -> IndexClassifyResult:
        normalized = request.normalized()
        self.calls.append(normalized)
        rows = [
            row for row in self.classify_rows
            if (normalized.src is None or row.src == normalized.src)
            and (normalized.level is None or row.level == normalized.level)
        ]
        return IndexClassifyResult(tuple(rows), provenance("index_classify"))

    def fetch_index_member_all(self, request: object) -> IndexMemberAllResult:
        normalized = request.normalized()
        self.calls.append(normalized)
        rows = [row for row in self.member_rows if row.is_new == normalized.is_new]
        return IndexMemberAllResult(tuple(rows), provenance("index_member_all"))


def import_classify(store: IndustryClassificationStore, rows, **kwargs):
    return store.import_classify_rows(rows, provenance=provenance("index_classify").as_dict(), **kwargs)


def import_members(store: IndustryClassificationStore, rows, **kwargs):
    return store.import_member_rows(rows, provenance=provenance().as_dict(), **kwargs)


def test_import_classify_is_idempotent_and_records_provenance() -> None:
    store = IndustryClassificationStore()
    first = import_classify(store, [classify(), classify("801040.SI")])
    assert first == {"inserted": 2, "updated": 0, "kept": 0, "reported": 0, "mismatches": []}
    replay = import_classify(store, [classify(), classify("801040.SI")])
    assert replay["inserted"] == 0 and replay["kept"] == 2

    stored = store._fetch_one(
        "SELECT * FROM market_index_classify WHERE src='SW2021' AND index_code='801050.SI'"
    )
    assert stored is not None and stored["level"] == "L1" and stored["content_sha256"]
    assert stored["provenance_json"]["endpoint"] == "index_classify"

    mismatch = import_classify(
        store, [IndexClassify("SW2021", "801050.SI", "改名", "0", "L1", "110000", "1")],
        conflict_policy=VERIFY_EQUAL,
    )
    assert mismatch["reported"] == 1 and mismatch["kept"] == 1
    assert store._fetch_one(
        "SELECT industry_name FROM market_index_classify WHERE src='SW2021' AND index_code='801050.SI'"
    )["industry_name"] == "有色金属"


def test_import_member_settles_open_interval_and_preserves_history() -> None:
    store = IndustryClassificationStore()
    first = import_members(store, [member()])
    assert first["inserted"] == 1

    settled = import_members(store, [member(out_date="20210729", is_new="N")])
    assert settled["updated"] == 1 and settled["inserted"] == 0
    stored = store._fetch_one(
        "SELECT * FROM market_index_member_all WHERE ts_code='601899.SH' AND l3_code='850531.SI'"
    )
    assert stored["out_date"] == "20210729" and stored["is_new"] == "N"

    replay = import_members(store, [member(out_date="20210729", is_new="N")])
    assert replay["kept"] == 1 and replay["updated"] == 0

    rewrite = import_members(store, [member(out_date="20200101", is_new="N")])
    assert rewrite["reported"] == 1 and rewrite["mismatches"][0]["reason"] == "settled_interval_rewrite_rejected"
    assert store._fetch_one(
        "SELECT out_date FROM market_index_member_all WHERE ts_code='601899.SH' AND l3_code='850531.SI'"
    )["out_date"] == "20210729"


def test_import_member_rejects_protocol_violations() -> None:
    store = IndustryClassificationStore()
    with pytest.raises(Exception, match="duplicate"):
        import_members(store, [member(), member()])
    with pytest.raises(Exception, match="out_date before in_date"):
        import_members(store, [member(in_date="20200101", out_date="20190101", is_new="N")])
    with pytest.raises(Exception, match="current index-member with an out_date"):
        import_members(store, [member(out_date="20200101", is_new="Y")])
    with pytest.raises(ValueError, match="conflict_policy"):
        store.import_member_rows([member()], provenance=provenance().as_dict(), conflict_policy="last_write_wins")


def test_membership_asof_reconstructs_point_in_time_without_backfill() -> None:
    store = IndustryClassificationStore()
    import_members(store, [
        member("000506.SZ", in_date="20150701", out_date="20180615", is_new="N"),
        member("601899.SH", in_date="20080407", out_date="20210729", is_new="N"),
        member("601020.SH", in_date="20210730", out_date=None, is_new="Y"),
    ])

    as_of_2018 = store.membership_asof(level="L3", code="850531.SI", as_of_date="20180101")
    assert {item["ts_code"] for item in as_of_2018["members"]} == {"000506.SZ", "601899.SH"}
    assert as_of_2018["current_snapshot_used"] is False

    as_of_2020 = store.membership_asof(level="L3", code="850531.SI", as_of_date="20200101")
    assert {item["ts_code"] for item in as_of_2020["members"]} == {"601899.SH"}

    as_of_2022 = store.membership_asof(level="L3", code="850531.SI", as_of_date="20220101")
    assert {item["ts_code"] for item in as_of_2022["members"]} == {"601020.SH"}

    # A current member must never be treated as a member before its in_date.
    early = store.membership_asof(level="L3", code="850531.SI", as_of_date="20200101")
    assert "601020.SH" not in {item["ts_code"] for item in early["members"]}
    assert store.membership_asof(level="L3", code="850531.SI", as_of_date="20180101")["member_count"] == 2

    with pytest.raises(ValueError, match="level"):
        store.membership_asof(level="L9", code="850531.SI", as_of_date="20200101")
    with pytest.raises(ValueError, match="code"):
        store.membership_asof(level="L3", code="BAD", as_of_date="20200101")
    with pytest.raises(ValueError, match="as_of_date"):
        store.membership_asof(level="L3", code="850531.SI", as_of_date="2020")


def test_readiness_fails_closed_on_missing_and_ambiguous_membership() -> None:
    store = IndustryClassificationStore()
    import_classify(store, [classify()])
    import_members(store, [
        member("000506.SZ", in_date="20150701"),
        member("601020.SH", in_date="20210730"),
    ])
    ready = store.readiness(symbols=["000506.SZ", "601020.SH"], as_of_date="20220101", level="L1")
    assert ready["coverage"]["usable"] is True
    assert ready["coverage"]["classify_present"] is True
    assert len(ready["memberships"]) == 2

    missing = store.readiness(symbols=["000506.SZ", "601899.SH"], as_of_date="20220101", level="L1")
    assert missing["coverage"]["usable"] is False
    assert missing["coverage"]["missing"] == [
        {"symbol": "601899.SH", "as_of_date": "20220101", "reason": "industry_membership_unavailable"}
    ]

    import_members(store, [member("000506.SZ", l3_code="850532.SI", in_date="20150701")])
    ambiguous = store.readiness(symbols=["000506.SZ"], as_of_date="20220101", level="L1")
    assert ambiguous["coverage"]["usable"] is False
    assert ambiguous["coverage"]["ambiguous"][0]["reason"] == "industry_membership_ambiguous"


def test_sync_member_job_is_incremental_and_terminal_rerun_is_a_noop() -> None:
    store = IndustryClassificationStore()
    provider = FakeIndustryProvider(member_rows=[
        member("601020.SH", in_date="20210730", is_new="Y"),
        member("601899.SH", in_date="20080407", out_date="20210729", is_new="N"),
    ])
    job, created = store.create_sync_job(
        {"kind": "member", "mode": "incremental", "selector": "all", "idempotency_key": "ind-sync-1"},
        actor="tester",
    )
    assert created is True
    finished = store.run_sync_job(job["job_id"], provider_factory=lambda: provider)
    assert finished["status"] == "completed"
    assert finished["rows_received"] == 2
    assert finished["rows_inserted"] == 2
    assert len(provider.calls) == 2  # one Y snapshot, one N snapshot

    fingerprint_before = store.persisted_fingerprint()
    terminal = store.run_sync_job(job["job_id"], provider_factory=lambda: (_ for _ in ()).throw(AssertionError("no refetch")))
    assert terminal["job_id"] == job["job_id"] and terminal["status"] == "completed"
    assert len(provider.calls) == 2
    assert store.persisted_fingerprint() == fingerprint_before

    resumed, _ = store.create_sync_job(
        {"kind": "member", "mode": "incremental", "selector": "all", "idempotency_key": "ind-sync-2"},
        actor="tester",
    )
    replayed = store.run_sync_job(resumed["job_id"], provider_factory=lambda: provider)
    assert replayed["rows_inserted"] == 0 and replayed["rows_kept"] == 2
    assert len(provider.calls) == 4


def test_sync_classify_job_persists_reference_rows() -> None:
    store = IndustryClassificationStore()
    provider = FakeIndustryProvider(classify_rows=[classify(), classify("801040.SI")])
    job, _ = store.create_sync_job(
        {"kind": "classify", "src": "SW2021", "idempotency_key": "ind-classify-1"}, actor="tester",
    )
    finished = store.run_sync_job(job["job_id"], provider_factory=lambda: provider)
    assert finished["status"] == "completed" and finished["rows_inserted"] == 2
    assert store.coverage()["classify"]["row_count"] == 2


def test_sync_idempotency_key_reuse_and_conflict() -> None:
    store = IndustryClassificationStore()
    payload = {"kind": "member", "mode": "incremental", "selector": "all", "idempotency_key": "ind-key"}
    job, created = store.create_sync_job(dict(payload), actor="tester")
    assert created is True
    again, created_again = store.create_sync_job(dict(payload), actor="tester")
    assert created_again is False and again["job_id"] == job["job_id"]
    with pytest.raises(IndustryClassificationConflict, match="reused"):
        store.create_sync_job({**payload, "selector": "000001.SZ"}, actor="tester")
    with pytest.raises(ValueError, match="idempotency_key"):
        store.create_sync_job({**payload, "idempotency_key": "bad key!"}, actor="tester")
    with pytest.raises(ValueError, match="unknown fields"):
        store.create_sync_job({**payload, "trade_date": "20200101"}, actor="tester")
    with pytest.raises(ValueError, match="selector_level"):
        store.create_sync_job(
            {"kind": "member", "selector": "801050.SI", "idempotency_key": "ind-key-2"}, actor="tester",
        )
    with pytest.raises(ValueError, match="kind"):
        store.create_sync_job({"kind": "price", "idempotency_key": "ind-key-3"}, actor="tester")


def test_coverage_reports_intervals_and_detects_overlaps() -> None:
    store = IndustryClassificationStore()
    assert store.coverage()["quality"] == "empty"
    import_classify(store, [
        classify("801050.SI"),
        classify("850531.SI", level="L3"),
        classify("850532.SI", level="L3"),
        classify("857831.SI", level="L3"),
    ])
    import_members(store, [
        member("000506.SZ", in_date="20150701", out_date="20180615", is_new="N"),
        member("601899.SH", in_date="20080407", out_date="20210729", is_new="N"),
        member("601020.SH", in_date="20210730", is_new="Y"),
    ])
    coverage = store.coverage()
    assert coverage["quality"] == "observed"
    assert coverage["classify"]["row_count"] == 4
    assert coverage["member"]["row_count"] == 3
    assert coverage["member"]["open_count"] == 1
    assert coverage["member"]["settled_count"] == 2
    assert coverage["member"]["overlap_pairs"] == 0
    assert coverage["completeness_claimed"] is False

    import_members(store, [member("000506.SZ", l3_code="850532.SI", in_date="20150101", is_new="Y")])
    overlapping = store.coverage()
    assert overlapping["member"]["overlap_pairs"] == 1
    assert overlapping["quality"] == "issues"


def test_market_readiness_integrates_industry_membership() -> None:
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
    industry = IndustryClassificationStore()
    import_classify(industry, [classify()])
    import_members(industry, [member("000001.SZ", l3_code="857831.SI", in_date="19910403", is_new="Y")])
    requirement = store.requirement(
        symbols=["000001.SZ"], start_date="2024-01-02", end_date="2024-01-03",
        membership_fingerprint="a" * 64, security_master_snapshot_id="sms_ready",
        data_requirements={"industry_membership": {"level": "L1"}},
    )

    ready = store.assess(requirement)
    assert ready["state"] == "ready"
    assert ready["ready_input_sha256"]

    store._execute("DELETE FROM market_index_member_all WHERE ts_code='000001.SZ'")
    degraded = store.assess(requirement)
    assert degraded["state"] == "missing"
    assert degraded["missing_by_dataset"]["industry_membership"] == 2

    with pytest.raises(ValueError, match="unsupported level"):
        store.assess(store.requirement(
            symbols=["000001.SZ"], start_date="2024-01-02", end_date="2024-01-03",
            membership_fingerprint="a" * 64, security_master_snapshot_id="sms_ready",
            data_requirements={"industry_membership": {"level": "L9"}},
        ))
