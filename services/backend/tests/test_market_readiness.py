from __future__ import annotations

import os

import pytest

from app.market_readiness import MarketReadinessStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)


def test_lifecycle_and_suspension_evidence_define_ready_cells() -> None:
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
    requirement = store.requirement(
        symbols=["000001.SZ"], start_date="2024-01-02", end_date="2024-01-03",
        membership_fingerprint="a" * 64, security_master_snapshot_id="sms_ready",
    )

    assessment = store.assess(requirement)

    assert assessment["state"] == "ready"
    assert assessment["required_cell_count"] == 2
    assert assessment["ready_input_sha256"]


def test_active_session_without_bar_and_limits_is_repairable_missing() -> None:
    store = MarketReadinessStore()
    store._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,
         retrieved_at,requested_by) VALUES ('sms_missing','tushare','stock_basic','missing_dataset',
         'missing_request','[\"L\"]',1,now(),'test')""")
    store._execute("""INSERT INTO security_master_snapshot_members
        (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,asset_type,content_sha256)
        VALUES ('sms_missing','000001.SZ','000001','Fixture','SZSE','L','20240101','stock','member')""")
    store._execute("""INSERT INTO market_trading_sessions
        (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
        VALUES ('20240102','SSE',TRUE,'tushare','cal',now(),'cal2',now())""")
    requirement = store.requirement(
        symbols=["000001.SZ"], start_date="20240102", end_date="20240102",
        membership_fingerprint="b" * 64, security_master_snapshot_id="sms_missing",
    )

    assessment = store.assess(requirement)

    assert assessment["state"] == "missing"
    assert assessment["missing_trade_dates"] == ["20240102"]
    assert {item["dataset"] for item in assessment["missing"]} == {"corporate_actions"}
    assert assessment["ready_input_sha256"] is None


def test_adjusted_research_view_preserves_raw_execution_and_freezes_actions() -> None:
    store = MarketReadinessStore()
    store._execute("""INSERT INTO market_daily_bars
        (symbol,trade_date,open,high,low,close,adjust,asset_type,data_source,
         content_sha256,provenance_json,imported_at)
        VALUES ('000001.SZ','20240102',10,10,10,10,'none','stock','tushare','b1','{}',now()),
               ('000001.SZ','20240103',5,5,5,5,'none','stock','tushare','b2','{}',now())""")
    store._execute("""INSERT INTO market_daily_status
        (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
         provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20240102',FALSE,10,11,9,'tushare','{}','s1',now()),
               ('000001.SZ','20240103',FALSE,5,5.5,4.5,'tushare','{}','s2',now())""")
    store._execute("""INSERT INTO market_adjustment_factors
        (symbol,trade_date,adj_factor,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20240102',1,'tushare','{}','f1',now()),
               ('000001.SZ','20240103',2,'tushare','{}','f2',now())""")
    store._execute("""INSERT INTO market_corporate_actions
        (symbol,end_date,ex_date,pay_date,share_listing_date,cash_dividend_per_share,
         cash_dividend_gross,share_ratio,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20231231','20240103','20240104','20240105',0.2,0.25,1,
                'tushare','{}','action1',now())""")
    requirement = {"symbols": ["000001.SZ"], "start_date": "20240102", "end_date": "20240103"}

    ready = store.build_ready_input(requirement)

    assert [row["close"] for row in ready["bars"]] == [10, 5]
    assert [row["close"] for row in ready["research_bars"]] == [5, 5]
    assert ready["corporate_actions"][0]["pay_date"] == "2024-01-04"
    assert ready["research_view_sha256"]
