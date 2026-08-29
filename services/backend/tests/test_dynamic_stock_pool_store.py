from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.paper_trading import PaperTradingStore
from app.stock_pool_producer import StockPoolProducerStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set",
)


def _seed_dynamic_inputs(store: StockPoolProducerStore) -> None:
    store._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,
         quarantined_count,retrieved_at,requested_by,created_at)
        VALUES ('security-dynamic','tushare','stock_basic','security-dynamic-dataset','request-dynamic',
                :statuses,3,0,:retrieved,'test',:retrieved)""",
        {"statuses": ["L"], "retrieved": datetime(2024, 1, 1, tzinfo=timezone.utc)})
    for symbol, exchange, industry in (
        ("000001.SZ", "SZSE", "银行"), ("600000.SH", "SSE", "银行"), ("300750.SZ", "SZSE", "电池"),
    ):
        store._execute("""INSERT INTO security_master_snapshot_members
            (snapshot_id,symbol,local_symbol,name,area,industry,market,exchange,list_status,list_date,
             delist_date,is_hs,asset_type,content_sha256)
            VALUES ('security-dynamic',:symbol,substring(:symbol,1,6),:symbol,'深圳',:industry,'主板',
                    :exchange,'L','20000101',NULL,'N','stock',:hash)""",
            {"symbol": symbol, "industry": industry, "exchange": exchange, "hash": f"security-{symbol}"})
    for trade_date, previous in (("20240102", None), ("20240103", "20240102"), ("20240104", "20240103")):
        store._execute("""INSERT INTO market_trading_sessions
            (trade_date,exchange,is_open,previous_open_date,data_source,request_fingerprint,retrieved_at,
             content_sha256,updated_at) VALUES (:date,'SSE',TRUE,:previous,'tushare','calendar-request',
             now(),:hash,now())""", {"date": trade_date, "previous": previous, "hash": f"calendar-{trade_date}"})
    values = {
        "000001.SZ": {"pb": 1.4, "total_mv": 100.0},
        "600000.SH": {"pb": 1.2, "total_mv": 200.0},
        "300750.SZ": {"pb": 5.0, "total_mv": 500.0},
    }
    for symbol, document in values.items():
        store._execute("""INSERT INTO market_daily_basic
            (symbol,trade_date,values_json,data_source,provenance_json,content_sha256,updated_at)
            VALUES (:symbol,'20240103',:values,'tushare',:provenance,:hash,now())""",
            {"symbol": symbol, "values": document, "provenance": {"test": True}, "hash": f"basic-{symbol}"})
    store._execute("""INSERT INTO market_daily_basic_completeness
        (trade_date,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('20240103',3,'basic-complete',:provenance,now())""", {"provenance": {"test": True}})


def _rule(cadence: str = "manual") -> dict[str, object]:
    return {
        "schema_version": "dynamic-stock-pool-rule.v1",
        "base_universe": {"kind": "security_master"},
        "filters": [{"field": "daily_basic.pb", "operator": "lte", "value": 2}],
        "ranking": {"field": "daily_basic.total_mv", "direction": "desc"},
        "top_n": 2,
        "missing_policy": "exclude",
        "weight_mode": "equal_weight",
        "cadence": cadence,
    }


def test_dynamic_preview_materialization_waiting_and_schedule_are_point_in_time() -> None:
    headers = trusted_agent_context("dynamic-owner")
    paper = PaperTradingStore()
    store = StockPoolProducerStore(paper_store=paper)
    _seed_dynamic_inputs(store)
    preview = store.preview_dynamic_pool(
        {"rule": _rule(), "requested_as_of": "20240103"}, trusted_owner="dynamic-owner",
        trusted_workspace=headers["x-byq-workspace-id"],
    )
    assert preview["authoritative"] is False
    assert [item["symbol"] for item in preview["members"]] == ["600000.SH", "000001.SZ"]

    created = store.create_dynamic_pool(
        {"name": "低估值大市值", "rule": _rule("daily"), "requested_as_of": "20240103",
         "activate": True, "idempotency_key": "dynamic-create-1"},
        trusted_owner="dynamic-owner", trusted_workspace=headers["x-byq-workspace-id"],
    )
    claimed = store.claim_next_run(worker_id="dynamic-worker")
    assert claimed is not None
    completed = store.materialize_claimed(claimed, worker_id="dynamic-worker")
    assert completed["status"] == "succeeded"
    pool = paper.get_pool(created["pool"]["pool_id"], trusted_owner="dynamic-owner")
    assert pool["pool_type"] == "dynamic"
    assert [row["symbol"] for row in pool["snapshot"]["members"]] == ["000001.SZ", "600000.SH"]
    assert Decimal(pool["snapshot"]["weight_sum"]) == Decimal("1")
    assert pool["snapshot"]["provenance"]["evaluation_cutoff"] == "20240103"

    waiting = store.enqueue_dynamic_refresh(
        pool["pool_id"], {"requested_as_of": "20240104", "idempotency_key": "missing-basic"},
        trusted_owner="dynamic-owner", trusted_workspace=headers["x-byq-workspace-id"],
    )
    assert waiting["status"] == "queued"
    claimed = store.claim_next_run(worker_id="dynamic-worker")
    assert claimed is not None
    assert store.materialize_claimed(claimed, worker_id="dynamic-worker")["status"] == "waiting_for_data"
    assert paper.get_pool(pool["pool_id"], trusted_owner="dynamic-owner")["current_snapshot_id"] == pool["current_snapshot_id"]

    now = datetime(2024, 1, 4, 12, tzinfo=timezone.utc)
    assert store.enqueue_due_dynamic_runs(now=now) == 1
    assert store.enqueue_due_dynamic_runs(now=now) == 0
    stale = store.claim_next_run(worker_id="dynamic-worker")
    assert stale is not None
    store.update_dynamic_definition(
        pool["pool_id"], {"rule": _rule("daily"), "status": "paused", "expected_version": 1},
        trusted_owner="dynamic-owner", trusted_workspace=headers["x-byq-workspace-id"],
    )
    cancelled = store.materialize_claimed(stale, worker_id="dynamic-worker")
    assert cancelled["status"] == "cancelled"
    assert cancelled["error_code"] == "stale_definition"
    store.close()
    paper.close()
