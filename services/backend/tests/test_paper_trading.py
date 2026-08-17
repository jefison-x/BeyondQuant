from __future__ import annotations

import os

import pytest

from app.paper_trading import PaperTradingForbidden, PaperTradingStore


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


def test_stock_pool_catalog_type_description_and_weights() -> None:
    store = PaperTradingStore()
    pool = store.create_pool(
        {
            "name": "沪深300增强",
            "pool_type": "index",
            "description": "指数股票池样例",
            "symbols": ["000001.SZ", "600000.SH"],
            "weights": {"000001.SZ": 0.6, "600000.SH": 0.4},
        },
        trusted_owner="alice",
    )
    assert pool["pool_type"] == "index"
    assert pool["description"] == "指数股票池样例"
    assert pool["weights"] == {"000001.SZ": 0.6, "600000.SH": 0.4}
    assert pool["version"] == "v1"

    listed = store.list_pools(trusted_owner="alice")["pools"]
    assert listed[0]["pool_type"] == "index"
    assert listed[0]["symbols"] == ["000001.SZ", "600000.SH"]

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
    store.close()
