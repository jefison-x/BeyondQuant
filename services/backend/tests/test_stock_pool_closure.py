from __future__ import annotations

import os

import pytest

from app.paper_trading import PaperTradingNotFound, PaperTradingStore
from app.stock_pool_producer import StockPoolProducerStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set")


def test_snapshot_diff_is_owner_scoped_and_deterministic() -> None:
    store = PaperTradingStore()
    pool = store.create_pool({"name": "diff", "symbols": ["000001.SZ", "600000.SH"]}, trusted_owner="diff-owner")
    second = store.replace_pool_snapshot(pool["pool_id"], {
        "expected_current_snapshot_id": pool["current_snapshot_id"],
        "symbols": ["000001.SZ", "300750.SZ"],
        "weights": {"000001.SZ": "0.4", "300750.SZ": "0.6"},
        "idempotency_key": "phase69-diff",
    }, trusted_owner="diff-owner")
    result = store.diff_pool_snapshots(
        pool["pool_id"], pool["current_snapshot_id"], second["snapshot_id"], trusted_owner="diff-owner",
    )
    assert result["added"] == [{"symbol": "300750.SZ", "weight": "0.600000000000"}]
    assert result["removed"] == [{"symbol": "600000.SH", "weight": None}]
    assert result["weight_changed"] == [{"symbol": "000001.SZ", "from_weight": None, "to_weight": "0.400000000000"}]
    with pytest.raises(PaperTradingNotFound):
        store.diff_pool_snapshots(pool["pool_id"], pool["current_snapshot_id"], second["snapshot_id"], trusted_owner="other")
    store.close()


def test_imported_producer_is_inactive_and_requires_revalidation() -> None:
    context = trusted_agent_context("import-owner")
    paper = PaperTradingStore()
    producers = StockPoolProducerStore(paper_store=paper)
    imported = producers.import_inactive_definition({
        "name": "Imported CSI 300", "description": "portable intent", "producer_kind": "index",
        "definition": {"index_symbol": "000300.SH", "dataset_contract": "untrusted",
                       "refresh_policy": "anything", "weight_mode": "anything"},
    }, trusted_owner="import-owner", trusted_workspace=context["x-byq-workspace-id"])
    assert imported["pool"]["status"] == "inactive"
    assert imported["pool"]["current_snapshot_id"] is None
    assert imported["producer"]["status"] == "draft"
    assert imported["producer"]["definition"]["dataset_contract"] == "market-index-weights-v1"
    readiness = producers.get_readiness(
        imported["pool"]["pool_id"], trusted_owner="import-owner",
        trusted_workspace=context["x-byq-workspace-id"],
    )
    assert readiness["state"] == "paused"
    producers.close()
    paper.close()
