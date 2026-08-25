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
    assert assessment["missing"][0]["dataset"] == "trading_status"
    assert assessment["ready_input_sha256"] is None
