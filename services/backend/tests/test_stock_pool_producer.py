from __future__ import annotations

import os
from decimal import Decimal

import pytest

from app.paper_trading import PaperTradingStore
from app.stock_pool_producer import StockPoolProducerNotFound, StockPoolProducerStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set",
)


def _seed_index(store: StockPoolProducerStore) -> None:
    for snapshot_date, weights, identity in (
        ("20240102", {"000001.SZ": 60.0, "600000.SH": 40.0}, "jan-hash"),
        ("20240201", {"300750.SZ": 55.0, "600000.SH": 45.0}, "feb-hash"),
    ):
        for symbol, weight in weights.items():
            store._execute("""INSERT INTO market_index_weights
                (index_symbol,constituent_symbol,snapshot_date,weight,data_source,provenance_json,
                 content_sha256,updated_at) VALUES
                ('000300.SH',:symbol,:date,:weight,'tushare',:provenance,:hash,now())""",
                {"symbol": symbol, "date": snapshot_date, "weight": weight,
                 "provenance": {"endpoint": "index_weight"}, "hash": f"{identity}-{symbol}"})
        store._execute("""INSERT INTO market_index_weight_completeness
            (index_symbol,period,row_count,content_sha256,provenance_json,verified_at)
            VALUES ('000300.SH',:period,2,:hash,:provenance,now())""",
            {"period": snapshot_date[:6], "hash": identity, "provenance": {"provider": "tushare"}})


def test_index_pool_materialization_is_point_in_time_idempotent_and_owner_scoped() -> None:
    alice_headers = trusted_agent_context("alice-index")
    bob_headers = trusted_agent_context("bob-index")
    paper = PaperTradingStore()
    store = StockPoolProducerStore(paper_store=paper)
    _seed_index(store)

    catalog = store.list_index_catalog()
    assert catalog["indices"][0]["index_symbol"] == "000300.SH"
    assert catalog["indices"][0]["latest_snapshot_date"] == "20240201"

    payload = {
        "index_symbol": "000300.SH", "name": "沪深300研究池",
        "requested_as_of": "20240131", "idempotency_key": "create-index-1",
    }
    created = store.create_index_pool(
        payload, trusted_owner="alice-index", trusted_workspace=alice_headers["x-byq-workspace-id"],
    )
    assert created["pool"]["pool_type"] == "index"
    assert created["pool"]["current_snapshot_id"] is None
    replay = store.create_index_pool(
        payload, trusted_owner="alice-index", trusted_workspace=alice_headers["x-byq-workspace-id"],
    )
    assert replay["pool"]["pool_id"] == created["pool"]["pool_id"]

    run = store.claim_next_run(worker_id="index-worker")
    assert run is not None
    completed = store.materialize_claimed_index(run, worker_id="index-worker")
    assert completed["status"] == "succeeded"
    assert completed["effective_trade_date"] == "20240102"
    pool = paper.get_pool(created["pool"]["pool_id"], trusted_owner="alice-index")
    assert [item["symbol"] for item in pool["snapshot"]["members"]] == ["000001.SZ", "600000.SH"]
    assert Decimal(pool["snapshot"]["weight_sum"]) == Decimal("1")
    assert pool["snapshot"]["provenance"]["source_weight_unit"] == "percent"

    with pytest.raises(StockPoolProducerNotFound):
        store.get_definition(
            pool["pool_id"], trusted_owner="bob-index", trusted_workspace=bob_headers["x-byq-workspace-id"],
        )

    newer = store.enqueue_index_refresh(
        pool["pool_id"], {"requested_as_of": "20240215", "idempotency_key": "refresh-feb"},
        trusted_owner="alice-index", trusted_workspace=alice_headers["x-byq-workspace-id"],
    )
    assert newer["status"] == "queued"
    claimed = store.claim_next_run(worker_id="index-worker")
    assert claimed is not None
    store.materialize_claimed_index(claimed, worker_id="index-worker")
    feb_pool = paper.get_pool(pool["pool_id"], trusted_owner="alice-index")
    assert feb_pool["snapshot"]["effective_trade_date"] == "20240201"

    older = store.enqueue_index_refresh(
        pool["pool_id"], {"requested_as_of": "20240131", "idempotency_key": "refresh-old"},
        trusted_owner="alice-index", trusted_workspace=alice_headers["x-byq-workspace-id"],
    )
    assert older["status"] == "queued"
    claimed = store.claim_next_run(worker_id="index-worker")
    assert claimed is not None
    store.materialize_claimed_index(claimed, worker_id="index-worker")
    assert paper.get_pool(pool["pool_id"], trusted_owner="alice-index")["snapshot"]["effective_trade_date"] == "20240201"
    assert paper.get_pool_as_of(pool["pool_id"], "20240131", trusted_owner="alice-index")["effective_trade_date"] == "20240102"
    store.close()
    paper.close()


def test_index_materialization_rejects_incomplete_percent_weights_without_snapshot() -> None:
    headers = trusted_agent_context("invalid-index")
    paper = PaperTradingStore()
    store = StockPoolProducerStore(paper_store=paper)
    store._execute("""INSERT INTO market_index_weights
        (index_symbol,constituent_symbol,snapshot_date,weight,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000300.SH','000001.SZ','20240102',50,'tushare',:provenance,'bad-row',now())""",
        {"provenance": {"provider": "tushare"}})
    store._execute("""INSERT INTO market_index_weight_completeness
        (index_symbol,period,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('000300.SH','202401',1,'bad-period',:provenance,now())""",
        {"provenance": {"provider": "tushare"}})
    created = store.create_index_pool(
        {"index_symbol": "000300.SH", "requested_as_of": "20240131", "idempotency_key": "bad-create"},
        trusted_owner="invalid-index", trusted_workspace=headers["x-byq-workspace-id"],
    )
    run = store.claim_next_run(worker_id="index-worker")
    assert run is not None
    failed = store.materialize_claimed_index(run, worker_id="index-worker")
    assert failed["status"] == "failed"
    assert paper.get_pool(created["pool"]["pool_id"], trusted_owner="invalid-index")["current_snapshot_id"] is None
    store.close()
    paper.close()
