from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.paper_trading import PaperTradingStore


def test_paper_ledger_endpoint_derives_cash_flow(monkeypatch, tmp_path) -> None:
    store = PaperTradingStore(tmp_path / "paper.sqlite3")
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
    assert ledger[0]["cash_delta"] == -1000.0

    denied = client.get(
        f"/v1/paper/accounts/{account['account_id']}/ledger",
        headers={**headers, "x-byq-owner-principal": "other-user"},
    )
    assert denied.status_code == 403
    store.close()
