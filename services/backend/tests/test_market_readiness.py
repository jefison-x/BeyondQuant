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


def test_declared_inputs_use_point_in_time_membership_and_announcement_effective_dates() -> None:
    store = MarketReadinessStore()
    store._execute("""INSERT INTO market_daily_bars
        (symbol,trade_date,open,high,low,close,adjust,asset_type,data_source,
         content_sha256,provenance_json,imported_at)
        VALUES ('000001.SZ','20240201',10,10,10,10,'none','stock','tushare','db1','{}',now()),
               ('000001.SZ','20240205',11,11,11,11,'none','stock','tushare','db2','{}',now())""")
    store._execute("""INSERT INTO market_daily_status
        (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
         provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20240201',FALSE,10,11,9,'tushare','{}','ds1',now()),
               ('000001.SZ','20240205',FALSE,10,12,10,'tushare','{}','ds2',now())""")
    store._execute("""INSERT INTO market_adjustment_factors
        (symbol,trade_date,adj_factor,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20240201',1,'tushare','{}','df1',now()),
               ('000001.SZ','20240205',1,'tushare','{}','df2',now())""")
    store._execute("""INSERT INTO market_daily_basic
        (symbol,trade_date,values_json,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20240201',:basic1,'tushare','{}','basic1',now()),
               ('000001.SZ','20240205',:basic2,'tushare','{}','basic2',now())""",
        {"basic1": '{"pe_ttm":9,"pb":1}', "basic2": '{"pe_ttm":10,"pb":1.1}'})
    store._execute("""INSERT INTO market_index_weights
        (index_symbol,constituent_symbol,snapshot_date,weight,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000300.SH','000001.SZ','20240131',1.5,'tushare','{}','w1',now()),
               ('000300.SH','600000.SH','20240205',1.5,'tushare','{}','w2',now())""")
    store._execute("""INSERT INTO market_financial_indicators
        (symbol,end_date,announcement_date,effective_date,values_json,update_flag,data_source,
         provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20231231','20240201','20240202',:fin1,'1','tushare','{}','fin1',now()),
               ('000001.SZ','20240331','20240205','20240206',:fin2,'1','tushare','{}','fin2',now())""",
        {"fin1": '{"roe":10}', "fin2": '{"roe":20}'})
    store._execute("""INSERT INTO market_index_daily
        (index_symbol,trade_date,open,high,low,close,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000300.SH','20240201',100,100,100,100,'tushare','{}','idx1',now()),
               ('000300.SH','20240205',101,101,101,101,'tushare','{}','idx2',now())""")
    requirement = {
        "schema_version": "market-data-requirement.v3", "symbols": ["000001.SZ"],
        "start_date": "20240201", "end_date": "20240205",
        "declared": {"benchmark": "000300.SH", "index_universe": "000300.SH",
                     "daily_basic": ["pe_ttm"], "fundamentals": ["roe"]},
    }

    ready = store.build_ready_input(requirement)

    assert [row["daily_basic__pe_ttm"] for row in ready["research_bars"]] == [9, 10]
    assert [row["is_universe_member"] for row in ready["research_bars"]] == [True, False]
    assert [row["fina_indicator__roe"] for row in ready["research_bars"]] == [None, 10]
    assert [row["close"] for row in ready["benchmark"]] == [100, 101]


def test_agent_valuation_read_requires_exact_complete_session_and_preserves_missing() -> None:
    store = MarketReadinessStore()
    store._execute("""INSERT INTO market_daily_basic
        (symbol,trade_date,values_json,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20260825',:values,'tushare','{}','valuation-row',now())""",
        {"values": '{"pe_ttm":6.5,"pb":0.7}'})
    store._execute("""INSERT INTO market_daily_basic_completeness
        (trade_date,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('20260825',1,'valuation-dataset','{}',now())""")

    result = store.research_valuation(
        symbols=["600000.SH", "000001.SZ"], trade_date="2026-08-25",
        fields=["pe_ttm", "pb"],
    )

    assert result["trade_date"] == "20260825"
    assert result["rows"] == [{
        "symbol": "000001.SZ", "trade_date": "20260825",
        "values": {"pe_ttm": 6.5, "pb": 0.7}, "data_source": "tushare",
        "content_sha256": "valuation-row",
    }]
    assert result["coverage"]["complete"] is True
    assert result["coverage"]["usable"] is False
    assert result["coverage"]["missing_symbols"] == ["600000.SH"]


def test_agent_fundamental_read_obeys_next_day_visibility_and_completeness() -> None:
    store = MarketReadinessStore()
    store._execute("""INSERT INTO market_financial_indicators
        (symbol,end_date,announcement_date,effective_date,values_json,update_flag,data_source,
         provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20250331','20250430','20250501',:old,'1','tushare','{}','fin-old',now()),
               ('000001.SZ','20250630','20250825','20250826',:new,'1','tushare','{}','fin-new',now())""",
        {"old": '{"roe":8.0,"netprofit_yoy":3.0}', "new": '{"roe":18.0,"netprofit_yoy":30.0}'})
    store._execute("""INSERT INTO market_financial_indicator_completeness
        (symbol,report_start_date,report_end_date,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('000001.SZ','20250101','20250630',2,'fin-dataset','{}',now())""")

    before = store.research_fundamentals(
        symbols=["000001.SZ"], as_of_date="20250825", fields=["roe", "netprofit_yoy"],
    )
    after = store.research_fundamentals(
        symbols=["000001.SZ"], as_of_date="20250826", fields=["roe", "netprofit_yoy"],
    )

    assert before["coverage"]["usable"] is True
    assert before["rows"][0]["report_period"] == "20250331"
    assert before["rows"][0]["values"]["roe"] == 8.0
    assert after["rows"][0]["report_period"] == "20250630"
    assert after["rows"][0]["announcement_date"] == "20250825"
    assert after["rows"][0]["effective_date"] == "20250826"


def test_agent_research_read_rejects_unbounded_or_unknown_input() -> None:
    store = MarketReadinessStore()
    with pytest.raises(ValueError, match="20 entries"):
        store.research_valuation(
            symbols=[f"{index:06d}.SZ" for index in range(21)],
            trade_date="20260825", fields=["pb"],
        )
    with pytest.raises(ValueError, match="unsupported"):
        store.research_fundamentals(
            symbols=["000001.SZ"], as_of_date="20260825", fields=["future_profit"],
        )
    with pytest.raises(ValueError, match="canonical"):
        store.research_valuation(
            symbols=["600000.SZ"], trade_date="20260825", fields=["pb"],
        )


def test_agent_research_marks_null_requested_fields_unusable() -> None:
    store = MarketReadinessStore()
    store._execute("""INSERT INTO market_daily_basic
        (symbol,trade_date,values_json,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000001.SZ','20260825',:values,'tushare','{}','valuation-null',now())""",
        {"values": '{"pe_ttm":6.5,"pb":null}'})
    store._execute("""INSERT INTO market_daily_basic_completeness
        (trade_date,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('20260825',1,'valuation-null-dataset','{}',now())""")

    result = store.research_valuation(
        symbols=["000001.SZ"], trade_date="20260825", fields=["pe_ttm", "pb"],
    )

    assert result["coverage"]["usable"] is False
    assert result["coverage"]["missing_fields"] == [{"symbol": "000001.SZ", "fields": ["pb"]}]
