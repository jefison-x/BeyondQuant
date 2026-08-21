from __future__ import annotations

import os

import pytest

from fastapi.testclient import TestClient

from app import main
from app.paper_trading import PaperTradingStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_paper_ledger_endpoint_derives_cash_flow(monkeypatch) -> None:
    store = PaperTradingStore()
    monkeypatch.setattr(main, "paper_store", store)
    client = TestClient(main.app)

    account = store.create_account({"name": "sim", "cash": 100_000}, trusted_owner="product-user")
    pool = store.create_pool({"name": "p1", "symbols": ["000001.SZ"]}, trusted_owner="product-user")
    store.submit_order(
        {
            "account_id": account["account_id"],
            "pool_id": pool["pool_id"],
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "trade_date": "20240102",
            "idempotency_key": "buy-1",
        },
        trusted_owner="product-user",
    )
    headers = {
        "x-byq-owner-principal": "product-user",
        "x-byq-actor-principal": "product-user",
        "x-byq-trace-id": "byq-trace-paper-api",
        "x-byq-session-id": "byq-session-paper-api",
        "x-byq-dsh-run-id": "byq-run-paper-api",
    }
    response = client.get(f"/v1/paper/accounts/{account['account_id']}/ledger", headers=headers)
    assert response.status_code == 200
    ledger = response.json()["ledger"]
    assert len(ledger) == 1
    assert ledger[0]["symbol"] == "000001.SZ"
    assert ledger[0]["cash_delta"] == -1005.0
    assert ledger[0]["fees"] == 5.0

    denied = client.get(
        f"/v1/paper/accounts/{account['account_id']}/ledger",
        headers={**headers, "x-byq-owner-principal": "other-user"},
    )
    assert denied.status_code == 403
    store.close()


def test_stock_pool_snapshot_and_lifecycle_api(monkeypatch) -> None:
    store = PaperTradingStore()
    monkeypatch.setattr(main, "paper_store", store)
    client = TestClient(main.app)
    headers = {
        "x-byq-owner-principal": "product-user", "x-byq-actor-principal": "product-user",
        "x-byq-trace-id": "trace-pool", "x-byq-session-id": "session-pool", "x-byq-dsh-run-id": "browser",
    }
    created = client.post("/v1/paper/pools", headers=headers, json={"name": "核心池", "symbols": ["000001.SZ"]})
    assert created.status_code == 201
    pool = created.json()["pool"]
    replaced = client.put(f"/v1/paper/pools/{pool['pool_id']}/snapshot", headers=headers, json={
        "expected_current_snapshot_id": pool["current_snapshot_id"], "idempotency_key": "api-edit-1",
        "symbols": ["600000.SH"],
    })
    assert replaced.status_code == 200
    assert replaced.json()["snapshot"]["version_number"] == 2
    history = client.get(f"/v1/paper/pools/{pool['pool_id']}/snapshots", headers=headers)
    assert [item["version_number"] for item in history.json()["snapshots"]] == [2, 1]
    inactive = client.patch(f"/v1/paper/pools/{pool['pool_id']}/lifecycle", headers=headers, json={
        "status": "inactive", "reason": "api pause", "idempotency_key": "api-life-1",
    })
    assert inactive.json()["pool"]["status"] == "inactive"
    store.close()
