from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.credentials import CredentialCipher, CredentialStore
from app.data_provider import DailyBar, DailyResult, Provenance
from app.data_sync import DataSyncConflict, DataSyncStore
from app.market_data import MarketDataStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


class FakeProvider:
    def __init__(self) -> None:
        self.requests = []

    def fetch_daily(self, request):
        normalized = request.normalized()
        self.requests.append(normalized)
        return DailyResult(
            bars=(DailyBar(
                ts_code=str(normalized.ts_code), trade_date="20240102",
                open=10.0, high=11.0, low=9.5, close=10.5,
                pre_close=10.0, change=0.5, pct_chg=5.0,
                vol=1000.0, amount=10500.0,
            ),),
            provenance=Provenance(
                provider="tushare", endpoint="daily", request_fingerprint="safe-fixture",
                retrieved_at="2026-08-22T00:00:00+00:00", cache_hit=False, row_count=1,
            ),
        )


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mode": "range",
        "symbols": ["000001.SZ"],
        "start_date": "20240102",
        "end_date": "20240112",
        "idempotency_key": "sync-create-1",
    }
    payload.update(overrides)
    return payload


def test_sync_job_is_durable_idempotent_and_updates_coverage() -> None:
    jobs = DataSyncStore()
    market = MarketDataStore()
    provider = FakeProvider()
    created, is_new = jobs.create_job(_payload(), actor="admin")
    assert is_new is True
    assert created["status"] == "queued"

    completed = jobs.run_job(created["job_id"], provider_factory=lambda: provider, market_store=market)
    assert completed["status"] == "completed"
    assert completed["rows_received"] == 1
    assert completed["rows_inserted"] == 1
    assert completed["symbol_results"][0]["date_min"] == "20240102"
    assert market.get_bar("000001.SZ", "20240102")["data_source"] == "tushare"

    replay, is_new = jobs.create_job(_payload(), actor="admin")
    assert is_new is False
    assert replay["job_id"] == created["job_id"]
    coverage = jobs.coverage_audit()
    assert coverage["quality"] == "observed"
    assert coverage["completeness_claimed"] is False
    assert coverage["row_count"] == 1
    assert coverage["symbols"][0]["symbol"] == "000001.SZ"
    jobs.close()
    market.close()


def test_sync_job_rejects_unbounded_invalid_and_conflicting_requests() -> None:
    jobs = DataSyncStore()
    with pytest.raises(ValueError, match="366"):
        jobs.create_job(_payload(end_date="20260101"), actor="admin")
    with pytest.raises(ValueError, match="366"):
        jobs.create_job(
            _payload(start_date="20240101", end_date="20250101"),
            actor="admin",
        )
    with pytest.raises(ValueError, match="canonical"):
        jobs.create_job(_payload(symbols=["000001"]), actor="admin")
    jobs.create_job(_payload(), actor="admin")
    with pytest.raises(DataSyncConflict, match="reused"):
        jobs.create_job(_payload(symbols=["600000.SH"]), actor="admin")
    jobs.close()


def test_sync_rejects_provider_rows_outside_requested_range() -> None:
    jobs = DataSyncStore()
    market = MarketDataStore()
    provider = FakeProvider()
    created, _ = jobs.create_job(
        _payload(start_date="20240103", end_date="20240112"),
        actor="admin",
    )

    completed = jobs.run_job(
        created["job_id"],
        provider_factory=lambda: provider,
        market_store=market,
    )

    assert completed["status"] == "failed"
    assert completed["symbol_results"][0]["error_code"] == "provider_protocol_error"
    assert market.get_bar("000001.SZ", "20240102") is None
    jobs.close()
    market.close()


def test_backend_data_center_routes_are_admin_scoped_and_secret_free(monkeypatch) -> None:
    credentials = CredentialStore(cipher=CredentialCipher.for_test({"test": bytes(range(32))}, "test"))
    jobs = DataSyncStore()
    market = MarketDataStore()
    provider = FakeProvider()
    monkeypatch.setattr(main, "credential_store", credentials)
    monkeypatch.setattr(main, "data_sync_store", jobs)
    monkeypatch.setattr(main, "market_data_store", market)
    monkeypatch.setattr(main, "data_provider", provider)
    client = TestClient(main.app)
    admin = {"x-byq-actor-principal": "admin", "x-byq-actor-role": "admin"}

    created = client.post(
        "/v1/data-sources/tushare/credentials",
        headers=admin,
        json={"label": "系统 Tushare", "secret": "phase39-secret-token", "idempotency_key": "source-http-1"},
    )
    assert created.status_code == 201
    assert "phase39-secret-token" not in created.text
    denied = client.post(
        "/v1/data-sources/tushare/test",
        headers={"x-byq-actor-principal": "alice", "x-byq-actor-role": "user"},
        json={"symbol": "000001.SZ", "trade_date": "20240102"},
    )
    assert denied.status_code == 403
    tested = client.post(
        "/v1/data-sources/tushare/test",
        headers=admin,
        json={"symbol": "000001.SZ", "trade_date": "20240102"},
    )
    assert tested.status_code == 200
    assert tested.json()["test"]["status"] == "passed"

    synced = client.post("/v1/data-sync/jobs", headers=admin, json=_payload(idempotency_key="source-http-sync-1"))
    assert synced.status_code == 201
    assert synced.json()["job"]["status"] == "queued"
    completed = client.get(f"/v1/data-sync/jobs/{synced.json()['job']['job_id']}", headers=admin)
    assert completed.status_code == 200
    assert completed.json()["job"]["status"] == "completed"
    status = client.get("/v1/data-center/status", headers=admin)
    assert status.status_code == 200
    assert status.json()["source"]["credentials"][0]["masked"].endswith("oken")
    assert status.json()["coverage"]["row_count"] == 1
    assert "phase39-secret-token" not in status.text
    credentials.close()
    jobs.close()
    market.close()
