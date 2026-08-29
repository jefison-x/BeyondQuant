from __future__ import annotations

import json
import os

import pytest

from app.paper_trading import PaperTradingConflict, PaperTradingForbidden, PaperTradingNotFound, PaperTradingStore


def test_cross_owner_account_lookup_does_not_reveal_existence() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "Alice private", "cash": 100000}, trusted_owner="alice")
    account_id = account["account_id"]

    for lookup in (
        lambda: store.get_account(account_id, trusted_owner="bob"),
        lambda: store.list_orders(account_id, trusted_owner="bob"),
        lambda: store.list_positions(account_id, trusted_owner="bob"),
        lambda: store.list_fills(account_id, trusted_owner="bob"),
        lambda: store.export_bundle(account_id, trusted_owner="bob"),
    ):
        with pytest.raises(PaperTradingNotFound, match="paper account not found"):
            lookup()
    store.close()


def test_account_delete_is_owner_scoped_tombstone_and_keeps_audit_history() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "可删除账户", "cash": 100000}, trusted_owner="alice")
    account_id = account["account_id"]
    payload = {"expected_version": account["version"], "idempotency_key": "delete-account-1", "reason": "用户清理"}

    with pytest.raises(PaperTradingNotFound):
        store.delete_account(account_id, payload, trusted_owner="bob", trusted_actor="bob")
    result = store.delete_account(account_id, payload, trusted_owner="alice", trusted_actor="alice")
    assert result == {"account_id": account_id, "deleted": True}
    assert store.delete_account(account_id, payload, trusted_owner="alice", trusted_actor="alice") == result
    assert store.list_accounts(trusted_owner="alice") == {"accounts": []}
    with pytest.raises(PaperTradingNotFound):
        store.get_account(account_id, trusted_owner="alice")
    audit = store._fetch_one(
        "SELECT * FROM paper_account_audit WHERE account_id = :account_id AND action = 'account_deleted'",
        {"account_id": account_id},
    )
    assert audit is not None
    assert audit["details_json"]["previous_name"] == "可删除账户"
    recreated = store.create_account({"name": "可删除账户", "cash": 50000}, trusted_owner="alice")
    assert recreated["account_id"] != account_id
    store.close()


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_paper_trading_enforces_pool_lot_limit_and_cash() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "sim", "cash": 100000}, trusted_owner="alice")
    pool = store.create_pool(
        {"name": "p1", "symbols": ["000001.SZ"], "provenance": {"source": "unit-test"}},
        trusted_owner="alice",
    )
    blocked_lot = store.submit_order(
        {
            "account_id": account["account_id"],
            "pool_id": pool["pool_id"],
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 1,
            "price": 10,
            "trade_date": "20240102",
            "idempotency_key": "lot",
        },
        trusted_owner="alice",
    )
    assert blocked_lot["status"] == "blocked"
    assert blocked_lot["blocked_reason"] == "lot_size"

    blocked_cash = store.submit_order(
        {
            "account_id": account["account_id"],
            "pool_id": pool["pool_id"],
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 10000,
            "trade_date": "20240102",
            "idempotency_key": "cash",
        },
        trusted_owner="alice",
    )
    assert blocked_cash["blocked_reason"] == "insufficient_cash"

    filled = store.submit_order(
        {
            "account_id": account["account_id"],
            "pool_id": pool["pool_id"],
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "trade_date": "20240102",
            "idempotency_key": "buy",
        },
        trusted_owner="alice",
    )
    assert filled["status"] == "filled"
    store.close()


def test_paper_trading_blocks_suspension_and_t_plus_one() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "sim", "cash": 100000}, trusted_owner="alice")
    pool = store.create_pool({"name": "p1", "symbols": ["000001.SZ"]}, trusted_owner="alice")
    suspended = store.submit_order(
        {
            "account_id": account["account_id"],
            "pool_id": pool["pool_id"],
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "trade_date": "20240102",
            "is_suspended": True,
            "idempotency_key": "suspended",
        },
        trusted_owner="alice",
    )
    assert suspended["blocked_reason"] == "suspended"

    store.submit_order(
        {
            "account_id": account["account_id"],
            "pool_id": pool["pool_id"],
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "trade_date": "20240102",
            "idempotency_key": "buy1",
        },
        trusted_owner="alice",
    )
    same_day_sell = store.submit_order(
        {
            "account_id": account["account_id"],
            "pool_id": pool["pool_id"],
            "symbol": "000001.SZ",
            "side": "sell",
            "quantity": 100,
            "price": 11,
            "trade_date": "20240102",
            "idempotency_key": "sell-same",
        },
        trusted_owner="alice",
    )
    assert same_day_sell["blocked_reason"] == "t_plus_one"
    store.close()


def test_paper_settlement_preserves_partial_t_plus_one_and_snapshot_immutability() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "partial-t1", "cash": 100000}, trusted_owner="alice")
    pool = store.create_pool({"name": "t1-pool", "symbols": ["000001.SZ"]}, trusted_owner="alice")
    store.submit_order({"account_id": account["account_id"], "pool_id": pool["pool_id"],
                        "symbol": "000001.SZ", "side": "buy", "quantity": 100,
                        "price": 10, "trade_date": "20240102", "idempotency_key": "t1-old"}, trusted_owner="alice")
    version = int(store.get_account(account["account_id"], trusted_owner="alice")["version"])
    snapshot = store.settle_account(account["account_id"], {
        "trade_date": "20240103", "expected_version": version,
        "idempotency_key": "settle-1", "marks": {"000001.SZ": 10.5},
    }, trusted_owner="alice", trusted_actor="alice")
    replay = store.settle_account(account["account_id"], {
        "trade_date": "20240103", "expected_version": version,
        "idempotency_key": "settle-1", "marks": {"000001.SZ": 10.5},
    }, trusted_owner="alice", trusted_actor="alice")
    assert replay["snapshot_id"] == snapshot["snapshot_id"]
    with pytest.raises(PaperTradingConflict):
        store.settle_account(account["account_id"], {
            "trade_date": "20240103", "expected_version": version,
            "idempotency_key": "settle-other", "marks": {"000001.SZ": 11},
        }, trusted_owner="alice", trusted_actor="alice")
    store.submit_order({"account_id": account["account_id"], "pool_id": pool["pool_id"],
                        "symbol": "000001.SZ", "side": "buy", "quantity": 100,
                        "price": 11, "trade_date": "20240103", "idempotency_key": "t1-new"}, trusted_owner="alice")
    position = store.list_positions(account["account_id"], trusted_owner="alice")["positions"][0]
    assert position["quantity"] == 200
    assert position["sellable_quantity"] == 100
    assert position["locked_quantity"] == 100
    sold = store.submit_order({"account_id": account["account_id"], "pool_id": pool["pool_id"],
                               "symbol": "000001.SZ", "side": "sell", "quantity": 100,
                               "price": 11, "trade_date": "20240103", "idempotency_key": "t1-sell-old"}, trusted_owner="alice")
    assert sold["status"] == "filled"
    blocked = store.submit_order({"account_id": account["account_id"], "pool_id": pool["pool_id"],
                                  "symbol": "000001.SZ", "side": "sell", "quantity": 100,
                                  "price": 11, "trade_date": "20240103", "idempotency_key": "t1-sell-new"}, trusted_owner="alice")
    assert blocked["blocked_reason"] == "t_plus_one"
    store.close()


def test_paper_controls_order_detail_and_bundle_round_trip() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "bundle-source", "cash": 100000}, trusted_owner="alice")
    pool = store.create_pool({"name": "bundle-pool", "symbols": ["000001.SZ"]}, trusted_owner="alice")
    controls = store.get_controls(account["account_id"], trusted_owner="alice")
    updated = store.update_controls(account["account_id"], {
        "kill_switch_engaged": False, "kill_switch_reason": "limit",
        "max_order_notional": 500, "expected_version": controls["version"],
        "idempotency_key": "risk-1",
    }, trusted_owner="alice", trusted_actor="alice")
    assert updated["version"] == 2
    blocked = store.submit_order({"account_id": account["account_id"], "pool_id": pool["pool_id"],
                                  "symbol": "000001.SZ", "side": "buy", "quantity": 100,
                                  "price": 10, "trade_date": "20240102", "idempotency_key": "risk-order"}, trusted_owner="alice")
    assert blocked["blocked_reason"] == "risk_max_order_notional"
    detail = store.get_order(account["account_id"], blocked["order_id"], trusted_owner="alice")
    assert detail["risk_evaluation_json"]["result"] == "blocked"
    bundle = store.export_bundle(account["account_id"], trusted_owner="alice")
    def contains_float(value: object) -> bool:
        if isinstance(value, float):
            return True
        if isinstance(value, dict):
            return any(contains_float(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_float(item) for item in value)
        return False
    assert not contains_float(bundle)
    portable_bundle = json.loads(json.dumps(bundle))
    imported = store.import_bundle(portable_bundle, trusted_owner="alice", trusted_actor="alice")
    assert imported["account"]["account_id"] != account["account_id"]
    assert imported["account"]["owner_principal"] == "alice"
    tampered = json.loads(json.dumps(bundle, default=str))
    tampered["sections"]["account"]["cash"] = "999999.0000"
    with pytest.raises(ValueError, match="digest"):
        store.import_bundle(tampered, trusted_owner="alice", trusted_actor="alice")
    store.close()


def test_paper_v2_migration_manifest_is_repeatable() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "migration-current", "cash": 50000}, trusted_owner="alice")
    store.bootstrap_schema()
    store.bootstrap_schema()
    entries = store.list_ledger(account["account_id"], trusted_owner="alice")["ledger"]
    assert [item["entry_type"] for item in entries] == ["initial_funding"]
    run = store._fetch_one(
        "SELECT * FROM paper_domain_migration_runs WHERE migration_id = 'paper-execution-v2'"
    )
    assert run is not None
    assert run["source_count"] >= 1
    assert run["migrated_count"] >= 1
    assert len(run["manifest_sha256"]) == 64
    store.close()


def test_stock_pool_catalog_type_description_and_weights() -> None:
    store = PaperTradingStore()
    pool = store.create_pool(
        {
            "name": "沪深300增强",
            "pool_type": "custom",
            "description": "指数股票池样例",
            "symbols": ["000001.SZ", "600000.SH"],
            "weights": {"000001.SZ": 0.6, "600000.SH": 0.4},
        },
        trusted_owner="alice",
    )
    assert pool["pool_type"] == "custom"
    assert pool["description"] == "指数股票池样例"
    assert pool["weights"] == {"000001.SZ": "0.600000000000", "600000.SH": "0.400000000000"}
    assert pool["version"] == "v1"
    assert pool["status"] == "active"
    assert pool["current_snapshot_id"].startswith("stock_pool_snapshot_")

    listed = store.list_pools(trusted_owner="alice")["pools"]
    assert listed[0]["pool_type"] == "custom"
    assert listed[0]["member_count"] == 2

    with pytest.raises(ValueError):
        store.create_pool(
            {"name": "bad", "pool_type": "unknown", "symbols": ["000001.SZ"]},
            trusted_owner="alice",
        )
    with pytest.raises(ValueError):
        store.create_pool(
            {"name": "bad-weight", "symbols": ["000001.SZ"], "weights": {"600000.SH": 1}},
            trusted_owner="alice",
        )
    with pytest.raises(PaperTradingForbidden):
        store.create_pool(
            {"name": "fake-index", "pool_type": "index", "symbols": ["000001.SZ"]},
            trusted_owner="alice",
        )
    store.close()


def test_stock_pool_snapshots_are_immutable_idempotent_and_lifecycle_safe() -> None:
    store = PaperTradingStore()
    pool = store.create_pool(
        {"name": "核心池", "symbols": ["600000.SH", "000001.SZ"], "definition": {"industry": ["银行"]}},
        trusted_owner="alice",
    )
    first_id = pool["current_snapshot_id"]
    first = store.get_pool_snapshot(first_id, trusted_owner="alice")
    assert [item["symbol"] for item in first["members"]] == ["000001.SZ", "600000.SH"]

    request = {
        "expected_current_snapshot_id": first_id,
        "idempotency_key": "pool-edit-1",
        "symbols": ["000001.SZ", "300750.SZ"],
        "weights": {"000001.SZ": "0.25", "300750.SZ": "0.75"},
        "definition": {"industry": ["银行", "电池"]},
    }
    second = store.replace_pool_snapshot(pool["pool_id"], request, trusted_owner="alice")
    assert second["version_number"] == 2
    assert second["snapshot_id"] != first_id
    assert store.replace_pool_snapshot(pool["pool_id"], request, trusted_owner="alice")["snapshot_id"] == second["snapshot_id"]
    assert store.get_pool_snapshot(first_id, trusted_owner="alice")["members"] == first["members"]

    with pytest.raises(PaperTradingConflict):
        store.replace_pool_snapshot(pool["pool_id"], {**request, "idempotency_key": "pool-edit-2"}, trusted_owner="alice")
    with pytest.raises(ValueError):
        store.replace_pool_snapshot(pool["pool_id"], {
            "expected_current_snapshot_id": second["snapshot_id"], "idempotency_key": "bad-weight",
            "symbols": ["000001.SZ", "300750.SZ"], "weights": {"000001.SZ": "0.4"},
        }, trusted_owner="alice")

    renamed = store.update_pool_metadata(pool["pool_id"], {
        "name": "核心池重命名", "description": "仅目录变更", "expected_metadata_version": 1,
    }, trusted_owner="alice")
    assert renamed["current_snapshot_id"] == second["snapshot_id"]
    inactive = store.set_pool_lifecycle(pool["pool_id"], {
        "status": "inactive", "reason": "pause", "idempotency_key": "life-1",
    }, trusted_owner="alice", trusted_actor="alice")
    assert inactive["status"] == "inactive"
    with pytest.raises(PaperTradingConflict):
        store.record_pool_reference(second["snapshot_id"], domain="research", reference_id="artifact_1", trusted_owner="alice")
    assert len(store.list_pool_snapshots(pool["pool_id"], trusted_owner="alice")["snapshots"]) == 2
    store.close()


def test_index_pool_as_of_has_no_lookahead_and_requires_tushare_provenance() -> None:
    store = PaperTradingStore()
    common = {
        "name": "沪深300",
        "pool_type": "index",
        "weights": {"000001.SZ": "1"},
        "provenance": {
            "index_symbol": "000300.SH", "provider": "tushare", "dataset_id": "index-20240102",
            "source_weight_unit": "fraction", "normalization_contract": "index-weight-v1",
        },
        "symbols": ["000001.SZ"], "effective_trade_date": "20240102",
    }
    pool = store.create_trusted_pool(common, trusted_owner="alice")
    later = {**common, "symbols": ["600000.SH"], "weights": {"600000.SH": "1"}, "effective_trade_date": "20240201",
             "provenance": {**common["provenance"], "dataset_id": "index-20240201"}}
    store.append_trusted_pool_snapshot(pool["pool_id"], later, trusted_owner="alice")
    january = store.get_pool_as_of(pool["pool_id"], "20240131", trusted_owner="alice")
    february = store.get_pool_as_of(pool["pool_id"], "20240201", trusted_owner="alice")
    assert january["members"][0]["symbol"] == "000001.SZ"
    assert february["members"][0]["symbol"] == "600000.SH"
    with pytest.raises(PaperTradingNotFound):
        store.get_pool_as_of(pool["pool_id"], "20240101", trusted_owner="alice")
    store.close()


def test_paper_order_freezes_stock_pool_snapshot_reference() -> None:
    store = PaperTradingStore()
    account = store.create_account({"name": "snapshot-account", "cash": 100000}, trusted_owner="alice")
    pool = store.create_pool({"name": "p1", "symbols": ["000001.SZ"]}, trusted_owner="alice")
    order = store.submit_order({
        "account_id": account["account_id"], "pool_id": pool["pool_id"], "symbol": "000001.SZ",
        "side": "buy", "quantity": 100, "price": 10, "trade_date": "20240102", "idempotency_key": "freeze-1",
    }, trusted_owner="alice")
    assert order["stock_pool_snapshot_id"] == pool["current_snapshot_id"]
    store.replace_pool_snapshot(pool["pool_id"], {
        "expected_current_snapshot_id": pool["current_snapshot_id"], "idempotency_key": "freeze-edit",
        "symbols": ["600000.SH"],
    }, trusted_owner="alice")
    references = store.pool_references(pool["pool_id"], trusted_owner="alice")["references"]
    assert references[0]["snapshot_id"] == order["stock_pool_snapshot_id"]
    assert store.get_pool_snapshot(order["stock_pool_snapshot_id"], trusted_owner="alice")["members"][0]["symbol"] == "000001.SZ"
    store.close()
