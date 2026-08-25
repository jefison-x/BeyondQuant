from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import main
from app.credentials import CredentialCipher, CredentialStore
from app.data_provider import (
    DailyBar,
    DailyResult,
    Provenance,
    SecurityMasterResult,
    SecurityRecord,
    TradingCalendarResult,
    TradingSession,
)
from app.data_sync import DataSyncConflict, DataSyncStore
from app.market_automation import MarketAutomationConflict, MarketAutomationStore, run_scheduler_cycle
from app.market_data import MarketDataStore
from app.paper_trading import PaperTradingNotFound, PaperTradingStore
from app.security_master import SecurityMasterStore


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

    def fetch_security_master(self, request):
        request.normalized()
        records = (SecurityRecord(
            symbol="000001.SZ", local_symbol="000001", name="平安银行",
            area="深圳", industry="银行", market="主板", exchange="SZSE",
            list_status="L", list_date="19910403", delist_date=None, is_hs="S",
        ),)
        import hashlib
        import json
        dataset_id = hashlib.sha256(json.dumps(
            [item.as_dict() for item in records], ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        return SecurityMasterResult(
            records=records,
            provenance=Provenance(
                provider="tushare", endpoint="stock_basic", request_fingerprint="security-fixture",
                retrieved_at="2026-08-24T00:00:00+00:00", cache_hit=False, row_count=1,
            ),
            dataset_id=dataset_id,
            statuses=("L", "P", "D"),
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


def test_incremental_sync_starts_after_latest_persisted_bar() -> None:
    jobs = DataSyncStore()
    market = MarketDataStore()
    provider = FakeProvider()
    market.import_bars([{
        "symbol": "000001.SZ", "trade_date": "20240102", "open": 10.0,
        "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000.0,
        "amount": 10500.0, "adjust": "none", "asset_type": "stock",
        "data_source": "tushare", "volume_unit": "lots",
        "amount_unit": "thousand_cny", "provenance": {"fixture": True},
    }])
    created, _ = jobs.create_job(_payload(
        mode="incremental", start_date="20240101", end_date="20240102",
        idempotency_key="incremental-current",
    ), actor="admin")

    completed = jobs.run_job(created["job_id"], provider_factory=lambda: provider, market_store=market)

    assert completed["status"] == "completed"
    assert completed["symbol_results"][0]["message"] == "already_current"
    assert provider.requests == []
    jobs.close()
    market.close()


def test_orchestrated_job_public_projection_is_bounded() -> None:
    jobs = DataSyncStore()
    symbols = [f"{index:06d}.SZ" for index in range(501)]
    created, _ = jobs.create_job(_payload(
        symbols=symbols,
        selection={"type": "security_master", "snapshot_id": "snapshot_fixture"},
        idempotency_key="orchestrated-bounds",
    ), actor="admin")

    assert created["symbol_count"] == 501
    assert len(created["symbols"]) == 100
    assert created["symbols_truncated"] is True
    jobs.close()


def test_stock_pool_selection_uses_trusted_owner_and_freezes_snapshot(monkeypatch) -> None:
    paper = PaperTradingStore()
    pool = paper.create_pool(
        {"name": "Alice catalogue", "symbols": ["600000.SH", "000001.SZ"]},
        trusted_owner="alice",
    )
    snapshot = paper.get_pool_snapshot(pool["current_snapshot_id"], trusted_owner="alice")
    monkeypatch.setattr(main, "paper_store", paper)
    monkeypatch.setattr(
        main, "_required_agent_context",
        lambda _request: {"owner_principal": "bob", "workspace_id": "workspace_bob"},
    )
    payload = _payload(
        symbols=[],
        selection={"type": "stock_pool", "snapshot_id": pool["current_snapshot_id"]},
    )

    with pytest.raises(PaperTradingNotFound):
        main._resolved_daily_sync_payload(payload, object())

    monkeypatch.setattr(
        main, "_required_agent_context",
        lambda _request: {"owner_principal": "alice", "workspace_id": "workspace_alice"},
    )
    resolved = main._resolved_daily_sync_payload(payload, object())
    assert resolved["symbols"] == ["000001.SZ", "600000.SH"]
    assert resolved["selection"] == {
        "type": "stock_pool",
        "pool_id": pool["pool_id"],
        "snapshot_id": pool["current_snapshot_id"],
        "membership_fingerprint": snapshot["membership_fingerprint"],
    }
    paper.close()


def test_backend_data_center_routes_are_admin_scoped_and_secret_free(monkeypatch) -> None:
    credentials = CredentialStore(cipher=CredentialCipher.for_test({"test": bytes(range(32))}, "test"))
    jobs = DataSyncStore()
    securities = SecurityMasterStore()
    market = MarketDataStore()
    automation = MarketAutomationStore()
    provider = FakeProvider()
    monkeypatch.setattr(main, "credential_store", credentials)
    monkeypatch.setattr(main, "data_sync_store", jobs)
    monkeypatch.setattr(main, "security_master_store", securities)
    monkeypatch.setattr(main, "market_data_store", market)
    monkeypatch.setattr(main, "market_automation_store", automation)
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

    master = client.post(
        "/v1/data-sync/security-master/jobs",
        headers=admin,
        json={"idempotency_key": "security-http-1"},
    )
    assert master.status_code == 201
    assert master.json()["job"]["status"] == "queued"
    master_job = client.get(f"/v1/data-sync/security-master/jobs/{master.json()['job']['job_id']}", headers=admin)
    assert master_job.json()["job"]["status"] == "completed"
    catalogue = client.get("/v1/data-center/securities?query=平安&statuses=L", headers=admin)
    assert catalogue.status_code == 200
    assert catalogue.json()["securities"][0]["symbol"] == "000001.SZ"

    orchestrated = client.post("/v1/data-sync/jobs", headers=admin, json={
        "mode": "range",
        "selection": {"type": "security_master", "statuses": ["L"], "exchanges": ["SZSE"]},
        "start_date": "20240102",
        "end_date": "20240102",
        "idempotency_key": "security-selection-sync-1",
    })
    assert orchestrated.status_code == 201
    assert orchestrated.json()["job"]["symbol_count"] == 1
    assert orchestrated.json()["job"]["selection"]["snapshot_id"] == master_job.json()["job"]["snapshot_id"]

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
    assert status.json()["schema_version"] == "data-center.v3"
    assert status.json()["security_master"]["total"] == 1
    assert "phase39-secret-token" not in status.text
    config = client.put("/v1/data-sync/automation/config", headers=admin, json={
        "enabled": True, "schedule_time": "18:30", "catchup_days": 7,
        "security_master_enabled": True, "expected_version": 1,
        "idempotency_key": "automation-http-config-1",
    })
    assert config.status_code == 200
    assert config.json()["config"]["enabled"] is True
    run_now = client.post(
        "/v1/data-sync/automation/run-now", headers=admin,
        json={"idempotency_key": "automation-http-run-1"},
    )
    assert run_now.status_code == 202
    assert run_now.json()["run_request"]["status"] == "queued"
    denied_automation = client.put(
        "/v1/data-sync/automation/config",
        headers={"x-byq-actor-principal": "alice", "x-byq-actor-role": "user"},
        json={},
    )
    assert denied_automation.status_code == 403
    credentials.close()
    jobs.close()
    securities.close()
    market.close()
    automation.close()


class FakeAutomationProvider:
    def __init__(self) -> None:
        self.calendar_requests = []
        self.daily_requests = []

    def fetch_trading_calendar(self, request):
        normalized = request.normalized()
        self.calendar_requests.append(normalized)
        return TradingCalendarResult(
            sessions=(
                TradingSession("20260823", False, "20260821"),
                TradingSession("20260824", True, "20260821"),
                TradingSession("20260825", True, "20260824"),
            ),
            provenance=Provenance(
                provider="tushare", endpoint="trade_cal", request_fingerprint="calendar-fixture",
                retrieved_at="2026-08-25T10:31:00+00:00", cache_hit=False, row_count=3,
            ),
        )

    def fetch_daily(self, request):
        normalized = request.normalized()
        self.daily_requests.append(normalized)
        trade_date = str(normalized.trade_date)
        return DailyResult(
            bars=(
                DailyBar("000001.SZ", trade_date, 10, 11, 9, 10.5, 10, .5, 5, 100, 2000),
                DailyBar("600000.SH", trade_date, 8, 8.5, 7.8, 8.2, 8, .2, 2.5, 80, 1200),
            ),
            provenance=Provenance(
                provider="tushare", endpoint="daily", request_fingerprint=f"daily-{trade_date}",
                retrieved_at="2026-08-25T10:32:00+00:00", cache_hit=False, row_count=2,
            ),
        )


def test_daily_automation_uses_open_sessions_and_full_market_snapshots() -> None:
    automation = MarketAutomationStore()
    market = MarketDataStore()
    provider = FakeAutomationProvider()
    config = automation.get_config()
    updated = automation.update_config({
        "enabled": True,
        "schedule_time": "18:30",
        "catchup_days": 3,
        "security_master_enabled": True,
        "expected_version": config["version"],
        "idempotency_key": "automation-config-1",
    }, actor="admin")
    assert updated["timezone"] == "Asia/Shanghai"

    created = run_scheduler_cycle(
        automation,
        provider_factory=lambda: provider,
        worker_id="test-worker",
        now=datetime(2026, 8, 25, 18, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert [item["trade_date"] for item in created] == ["20260824", "20260825"]
    assert len(provider.calendar_requests) == 1
    assert run_scheduler_cycle(
        automation,
        provider_factory=lambda: provider,
        worker_id="test-worker",
        now=datetime(2026, 8, 25, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    ) == []
    assert len(provider.calendar_requests) == 1

    for expected_date in ("20260824", "20260825"):
        job = automation.claim_next_job(
            worker_id="test-worker",
            now=datetime(2026, 8, 25, 18, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        assert job is not None and job["trade_date"] == expected_date
        completed = automation.execute_job(job, provider=provider, market_store=market)
        assert completed["status"] == "completed"
        assert completed["rows_received"] == 2
    assert market.get_bar("000001.SZ", "20260825")["pre_close"] == 10
    status = automation.status()
    assert status["latest_complete_session"]["trade_date"] == "20260825"
    assert status["latest_complete_session"]["row_count"] == 2
    automation.close()
    market.close()


def test_daily_worker_defers_current_session_until_configured_close_time() -> None:
    automation = MarketAutomationStore()
    provider = FakeAutomationProvider()
    config = automation.get_config()
    automation.update_config({
        "enabled": True,
        "schedule_time": "18:30",
        "catchup_days": 1,
        "security_master_enabled": True,
        "expected_version": config["version"],
        "idempotency_key": "automation-current-session-cutoff",
    }, actor="admin")
    noon = datetime(2026, 8, 25, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    created = run_scheduler_cycle(
        automation, provider_factory=lambda: provider, worker_id="test-worker",
        now=noon, force=True,
    )

    assert [item["trade_date"] for item in created] == ["20260825"]
    assert automation.claim_next_job(worker_id="test-worker", now=noon) is None
    claimed = automation.claim_next_job(
        worker_id="test-worker",
        now=datetime(2026, 8, 25, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert claimed is not None
    assert claimed["trade_date"] == "20260825"
    assert claimed["attempts"] == 1
    automation.close()


def test_automation_config_is_versioned_and_idempotent() -> None:
    automation = MarketAutomationStore()
    payload = {
        "enabled": True, "schedule_time": "18:30", "catchup_days": 7,
        "security_master_enabled": True, "expected_version": 1,
        "idempotency_key": "automation-config-replay",
    }
    first = automation.update_config(payload, actor="admin")
    assert automation.update_config(payload, actor="admin") == first
    with pytest.raises(MarketAutomationConflict, match="version conflict"):
        automation.update_config({**payload, "idempotency_key": "automation-config-stale"}, actor="admin")
    automation.close()
