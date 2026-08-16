from __future__ import annotations

import pytest

from app.paper_trading import PaperTradingForbidden, PaperTradingStore


def test_paper_trading_enforces_pool_lot_limit_and_cash(tmp_path) -> None:
    store = PaperTradingStore(tmp_path / "paper.sqlite3")
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


def test_paper_trading_blocks_suspension_and_t_plus_one(tmp_path) -> None:
    store = PaperTradingStore(tmp_path / "paper.sqlite3")
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
