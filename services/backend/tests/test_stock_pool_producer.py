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
        store._execute("""INSERT INTO market_index_weight_snapshots
            (index_symbol,snapshot_date,member_count,weight_sum,content_sha256,provenance_json,status,verified_at)
            VALUES ('000300.SH',:date,2,'100',:hash,:provenance,'verified',now())""",
            {"date": snapshot_date, "hash": identity, "provenance": {"provider": "tushare"}})


def test_index_pool_materialization_is_point_in_time_idempotent_and_owner_scoped() -> None:
    alice_headers = trusted_agent_context("alice-index")
    bob_headers = trusted_agent_context("bob-index")
    paper = PaperTradingStore()
    store = StockPoolProducerStore(paper_store=paper)
    _seed_index(store)

    catalog = store.list_index_catalog()
    available = [item for item in catalog["indices"] if item["selectable"]]
    assert [item["index_symbol"] for item in available] == ["000300.SH"]
    assert available[0]["latest_snapshot_date"] == "20240201"
    assert catalog["total"] == 6
    past = store.list_index_catalog(requested_as_of="20240131")
    assert next(item for item in past["indices"] if item["index_symbol"] == "000300.SH")["latest_snapshot_date"] == "20240102"
    assert store.list_index_catalog(requested_as_of="20230101")["available_total"] == 0

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
    assert store.reconcile_index_creation("create-index-1", trusted_owner="alice-index",
                                         trusted_workspace=alice_headers["x-byq-workspace-id"])["pool"]["pool_id"] == created["pool"]["pool_id"]
    with pytest.raises(StockPoolProducerNotFound):
        store.reconcile_index_creation("create-index-1", trusted_owner="bob-index",
                                       trusted_workspace=alice_headers["x-byq-workspace-id"])

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


def test_index_catalog_rejects_month_only_evidence_without_verified_snapshot() -> None:
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
    catalog = store.list_index_catalog()
    csi300 = next(item for item in catalog["indices"] if item["index_symbol"] == "000300.SH")
    assert csi300["selectable"] is False
    with pytest.raises(StockPoolProducerNotFound, match="no validated index weights"):
        store.create_index_pool(
            {"index_symbol": "000300.SH", "requested_as_of": "20240131", "idempotency_key": "bad-create"},
            trusted_owner="invalid-index", trusted_workspace=headers["x-byq-workspace-id"],
        )
    store.close()
    paper.close()


def test_historical_index_pool_never_follows_later_constituents() -> None:
    from datetime import datetime, timezone
    from app.stock_pool_producer import StockPoolProducerConflict
    headers = trusted_agent_context("historical-index")
    store = StockPoolProducerStore()
    _seed_index(store)
    context = {"trusted_owner": "historical-index", "trusted_workspace": headers["x-byq-workspace-id"]}
    payload = {"index_symbol": "000300.SH", "requested_as_of": "20240131",
               "tracking_mode": "historical_snapshot", "idempotency_key": "historical-index-once"}
    created = store.create_index_pool(payload, **context)
    claim = store.claim_next_run(worker_id="historical-worker")
    assert claim is not None
    store.materialize_claimed_index(claim, worker_id="historical-worker")
    before = store.paper_store.get_pool(created["pool"]["pool_id"], trusted_owner="historical-index")
    assert before["snapshot"]["effective_trade_date"] == "20240102"
    readiness = store.get_readiness(before["pool_id"], **context)
    assert readiness["state"] == "current"
    assert readiness["source_snapshot_date"] == "20240102"
    assert store.enqueue_validated_index_refreshes(now=datetime(2024, 3, 1, tzinfo=timezone.utc)) == 0
    with pytest.raises(StockPoolProducerConflict):
        store.enqueue_index_refresh(created["pool"]["pool_id"],
            {"requested_as_of": "20240215", "idempotency_key": "wrong-historical-refresh"}, **context)
    assert store.create_index_pool(payload, **context)["pool"]["pool_id"] == before["pool_id"]
    with pytest.raises(StockPoolProducerConflict):
        store.create_index_pool({**payload, "tracking_mode": "follow_index"}, **context)
    assert store.paper_store.get_pool(before["pool_id"], trusted_owner="historical-index")["current_snapshot_id"] == before["current_snapshot_id"]
    store.close()


def test_validated_index_import_compensation_is_bounded_restart_safe_and_frozen() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    headers = trusted_agent_context("index-compensation")
    store = StockPoolProducerStore()
    _seed_index(store)
    pools = []
    try:
        for number in range(3):
            result = store.create_index_pool(
                {"index_symbol": "000300.SH", "requested_as_of": "20240131", "idempotency_key": f"compensate-{number}"},
                trusted_owner="index-compensation", trusted_workspace=headers["x-byq-workspace-id"],
            )
            claimed = store.claim_next_run(worker_id="synthetic")
            store.materialize_claimed_index(claimed, worker_id="synthetic")
            pools.append(result["pool"]["pool_id"])
        frozen = store.paper_store.get_pool(pools[0], trusted_owner="index-compensation")["current_snapshot_id"]
        readiness = store.get_readiness(pools[0], trusted_owner="index-compensation", trusted_workspace=headers["x-byq-workspace-id"])
        assert readiness["state"] == "stale"
        assert readiness["source_snapshot_date"] == "20240201"
        assert readiness["current_snapshot_date"] == "20240102"
        # Inactive pools are not scheduled, even if their definition remains active.
        store._execute("UPDATE stock_pools SET status='inactive' WHERE pool_id=:id", {"id": pools[2]})
        january = datetime(2024, 1, 31, tzinfo=timezone.utc)
        february = datetime(2024, 2, 2, tzinfo=timezone.utc)
        assert store.enqueue_validated_index_refreshes(now=january) == 0
        assert store.enqueue_validated_index_refreshes(now=february, limit=1) == 1
        restarted = StockPoolProducerStore()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda item: item.enqueue_validated_index_refreshes(now=february),
                                            [store, restarted]))
            assert sum(results) == 1
            assert restarted.enqueue_validated_index_refreshes(now=february) == 0
            for _ in range(2):
                claimed = restarted.claim_next_run(worker_id="synthetic")
                assert claimed is not None
                assert restarted.materialize_claimed_index(claimed, worker_id="synthetic")["status"] == "succeeded"
            assert restarted.enqueue_validated_index_refreshes(now=january) == 0
            assert restarted.enqueue_validated_index_refreshes(now=february) == 0
            for pool in pools[:2]:
                assert restarted.paper_store.get_pool(pool, trusted_owner="index-compensation")["snapshot"]["effective_trade_date"] == "20240201"
                assert restarted.get_readiness(pool, trusted_owner="index-compensation", trusted_workspace=headers["x-byq-workspace-id"])["state"] == "current"
            historical = restarted.paper_store.get_pool_snapshot(frozen, trusted_owner="index-compensation")
            assert historical["effective_trade_date"] == "20240102"
        finally:
            restarted.close()
    finally:
        store.close()
