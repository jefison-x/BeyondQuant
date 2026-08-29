from __future__ import annotations

import os

import pytest

from fastapi.testclient import TestClient

from app import main
from app.paper_trading import PaperTradingStore
from app.stock_pool_producer import StockPoolProducerStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_paper_ledger_endpoint_derives_cash_flow(monkeypatch) -> None:
    headers = trusted_agent_context(
        "product-user", trace_id="byq-trace-paper-api", session_id="byq-session-paper-api",
        dsh_run_id="byq-run-paper-api",
    )
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
    response = client.get(f"/v1/paper/accounts/{account['account_id']}/ledger", headers=headers)
    assert response.status_code == 200
    ledger = response.json()["ledger"]
    assert len(ledger) == 2
    fill_entry = next(item for item in ledger if item["entry_type"] == "fill")
    assert fill_entry["symbol"] == "000001.SZ"
    assert float(fill_entry["cash_delta"]) == -1005.0
    assert float(fill_entry["fees"]) == 5.0

    denied = client.get(
        f"/v1/paper/accounts/{account['account_id']}/ledger",
        headers=trusted_agent_context("other-user"),
    )
    assert denied.status_code == 404
    assert denied.json() == {"detail": "paper account not found"}
    store.close()


def test_paper_account_delete_endpoint_tombstones_owned_account(monkeypatch) -> None:
    headers = trusted_agent_context("product-user")
    store = PaperTradingStore()
    monkeypatch.setattr(main, "paper_store", store)
    client = TestClient(main.app)
    account = store.create_account({"name": "delete-api", "cash": 100_000}, trusted_owner="product-user")

    response = client.request("DELETE", f"/v1/paper/accounts/{account['account_id']}", headers=headers, json={
        "expected_version": account["version"], "idempotency_key": "delete-api-1", "reason": "用户删除",
    })
    assert response.status_code == 200
    assert response.json() == {"account_id": account["account_id"], "deleted": True}
    assert client.get(f"/v1/paper/accounts/{account['account_id']}", headers=headers).status_code == 404
    store.close()


def test_stock_pool_snapshot_and_lifecycle_api(monkeypatch) -> None:
    headers = trusted_agent_context(
        "product-user", trace_id="trace-pool", session_id="session-pool", dsh_run_id="browser"
    )
    store = PaperTradingStore()
    monkeypatch.setattr(main, "paper_store", store)
    client = TestClient(main.app)
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


def test_index_pool_product_boundary_enqueues_trusted_materialization(monkeypatch) -> None:
    headers = trusted_agent_context("index-api-user")
    other_headers = trusted_agent_context("index-api-other")
    paper = PaperTradingStore()
    producer = StockPoolProducerStore(paper_store=paper)
    producer._execute("""INSERT INTO market_index_weights
        (index_symbol,constituent_symbol,snapshot_date,weight,data_source,provenance_json,content_sha256,updated_at)
        VALUES ('000300.SH','000001.SZ','20240102',100,'tushare',:provenance,'api-row',now())""",
        {"provenance": {"provider": "tushare"}})
    producer._execute("""INSERT INTO market_index_weight_completeness
        (index_symbol,period,row_count,content_sha256,provenance_json,verified_at)
        VALUES ('000300.SH','202401',1,'api-period',:provenance,now())""",
        {"provenance": {"provider": "tushare"}})
    producer._execute("""INSERT INTO market_index_weight_snapshots
        (index_symbol,snapshot_date,member_count,weight_sum,content_sha256,provenance_json,status,verified_at)
        VALUES ('000300.SH','20240102',1,'100','api-snapshot',:provenance,'verified',now())""",
        {"provenance": {"provider": "tushare"}})
    monkeypatch.setattr(main, "paper_store", paper)
    monkeypatch.setattr(main, "stock_pool_producer_store", producer)
    client = TestClient(main.app)

    catalog = client.get("/v1/paper/index-pools/catalog", headers=headers)
    assert catalog.status_code == 200
    available = [item for item in catalog.json()["indices"] if item["selectable"]]
    assert [item["index_symbol"] for item in available] == ["000300.SH"]
    created = client.post("/v1/paper/index-pools", headers=headers, json={
        "index_symbol": "000300.SH", "requested_as_of": "20240131", "idempotency_key": "api-index-create",
    })
    assert created.status_code == 202
    body = created.json()
    assert body["pool"]["pool_type"] == "index"
    assert body["run"]["status"] == "queued"
    assert "workspace_id" not in body["run"]
    pool_id = body["pool"]["pool_id"]
    assert client.get(f"/v1/paper/pools/{pool_id}/producer", headers=other_headers).status_code == 404
    assert client.post("/v1/paper/index-pools", headers=headers, json={
        "index_symbol": "000300.SH", "requested_as_of": "20240131", "idempotency_key": "api-index-create",
        "provider": "browser-spoof",
    }).status_code == 422
    producer.close()
    paper.close()


def test_dynamic_pool_product_boundary_rejects_spoofed_and_open_rules(monkeypatch) -> None:
    headers = trusted_agent_context("dynamic-api-user")
    paper = PaperTradingStore()
    producer = StockPoolProducerStore(paper_store=paper)
    monkeypatch.setattr(main, "paper_store", paper)
    monkeypatch.setattr(main, "stock_pool_producer_store", producer)
    client = TestClient(main.app)
    rule = {
        "schema_version": "dynamic-stock-pool-rule.v1",
        "base_universe": {"kind": "security_master"}, "filters": [],
        "ranking": {"field": "daily_basic.total_mv", "direction": "desc"}, "top_n": 20,
        "missing_policy": "exclude", "weight_mode": "equal_weight", "cadence": "manual",
    }
    created = client.post("/v1/paper/dynamic-pools", headers=headers, json={
        "name": "动态大盘池", "rule": rule, "activate": False, "idempotency_key": "dynamic-api-1",
    })
    assert created.status_code == 202
    assert created.json()["pool"]["pool_type"] == "dynamic"
    assert created.json()["run"] is None
    pool_id = created.json()["pool"]["pool_id"]
    updated = client.put(f"/v1/paper/pools/{pool_id}/producer", headers=headers, json={
        "rule": rule, "status": "paused", "expected_version": 1,
    })
    assert updated.status_code == 200
    assert updated.json()["producer"]["version"] == 2
    assert client.post("/v1/paper/dynamic-pools", headers=headers, json={
        "name": "恶意规则", "rule": {**rule, "python": "open('/etc/passwd').read()"},
        "activate": False, "idempotency_key": "dynamic-api-2",
    }).status_code == 422
    assert client.post("/v1/paper/dynamic-pools", headers=headers, json={
        "name": "越权规则", "rule": rule, "activate": False, "idempotency_key": "dynamic-api-3",
        "owner_principal": "spoofed-owner",
    }).status_code == 401
    producer.close()
    paper.close()
