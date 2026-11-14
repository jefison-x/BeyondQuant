from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.data_provider import DailyBar, DailyResult, Provenance


class FakeProvider:
    def __init__(self) -> None:
        self.requests = []

    def fetch_daily(self, request):
        self.requests.append(request)
        return DailyResult(
            bars=(
                DailyBar(
                    ts_code="000001.SZ",
                    trade_date="20240102",
                    open=10.0,
                    high=11.0,
                    low=9.0,
                    close=10.5,
                    pre_close=10.2,
                    change=0.3,
                    pct_chg=2.94,
                    vol=100.0,
                    amount=2000.0,
                ),
            ),
            provenance=Provenance(
                provider="tushare",
                endpoint="daily",
                request_fingerprint="fixture",
                retrieved_at="2026-08-15T00:00:00+00:00",
                cache_hit=False,
                row_count=1,
            ),
        )


def test_daily_api_exposes_normalized_bars_and_provenance(monkeypatch) -> None:
    fake = FakeProvider()
    monkeypatch.setattr(main, "data_provider", fake)

    response = TestClient(main.app).get(
        "/v1/data/daily",
        params={"ts_code": "000001.SZ", "trade_date": "20240102"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["close"] == 10.5
    assert response.json()["provenance"]["request_fingerprint"] == "fixture"
    assert fake.requests[0].ts_code == "000001.SZ"


def test_daily_api_rejects_unbounded_query(monkeypatch) -> None:
    monkeypatch.setattr(main, "data_provider", FakeProvider())

    response = TestClient(main.app).get("/v1/data/daily")

    assert response.status_code == 422
    assert "exact trade_date" in response.json()["detail"]


class FakeResearchStore:
    def research_valuation(self, **payload):
        return {"schema_version": "market-valuation-research.v1", "request": payload}

    def research_fundamentals(self, **payload):
        return {"schema_version": "market-fundamentals-research.v1", "request": payload}


class FakeMarketAutomationStore:
    def market_session_context(self):
        return {
            "schema_version": "market-session-context.v1",
            "current_date": "20260828",
            "current_session": {"state": "open", "calendar_verified": True},
            "latest_complete_session": {"trade_date": "20260827"},
            "live_provider_called": False,
        }


def test_persisted_market_research_api_passes_bounded_payload(monkeypatch) -> None:
    monkeypatch.setattr(main, "market_readiness_store", FakeResearchStore())
    monkeypatch.setattr(main, "market_automation_store", FakeMarketAutomationStore())
    client = TestClient(main.app)

    valuation = client.post("/v1/data/research/valuation", json={
        "symbols": ["000001.SZ"], "trade_date": "20260825", "fields": ["pe_ttm", "pb"],
    })
    fundamentals = client.post("/v1/data/research/fundamentals", json={
        "symbols": ["000001.SZ"], "as_of_date": "20260825", "fields": ["roe"],
    })
    session_context = client.get("/v1/data/research/session-context")

    assert valuation.status_code == 200
    assert valuation.json()["request"]["trade_date"] == "20260825"
    assert fundamentals.status_code == 200
    assert fundamentals.json()["request"]["as_of_date"] == "20260825"
    assert session_context.status_code == 200
    assert session_context.json()["latest_complete_session"]["trade_date"] == "20260827"
    assert session_context.json()["live_provider_called"] is False

    rejected = client.post("/v1/data/research/valuation", json={
        "symbols": ["000001.SZ"], "trade_date": "20260825", "fields": ["pb"],
        "provider_endpoint": "arbitrary",
    })
    assert rejected.status_code == 422
    assert "unsupported fields" in rejected.json()["detail"]


class FakeDailyResearchStore:
    def research_daily(self, request):
        normalized = request.normalized()
        return {
            "schema_version": "market-daily-research.v1",
            "data": [{"ts_code": normalized.ts_code, "trade_date": normalized.trade_date, "close": 10.5}],
            "provenance": {"source": "persisted_byq", "live_provider_called": False},
            "coverage": {"usable": True, "missing": []},
        }


def test_agent_daily_research_uses_durable_store_without_provider(monkeypatch) -> None:
    monkeypatch.setattr(main, "market_data_store", FakeDailyResearchStore())
    monkeypatch.setattr(
        main, "_resolved_tushare_provider",
        lambda: (_ for _ in ()).throw(AssertionError("provider must not be called")),
    )

    response = TestClient(main.app).post("/v1/data/research/daily", json={
        "ts_code": "000001.SZ", "trade_date": "20240102",
    })

    assert response.status_code == 200
    assert response.json()["provenance"] == {"source": "persisted_byq", "live_provider_called": False}
    assert response.json()["data"][0]["close"] == 10.5


class FakeSecurityMaster:
    def latest_snapshot(self):
        return {"snapshot_id": "security-master-fixture"}


class FakeReadinessStore(FakeResearchStore):
    def requirement(self, **payload):
        return {"schema_version": "fixture", **payload}

    def assess(self, requirement):
        return {
            "state": "partial", "required_session_count": 2, "required_cell_count": 4,
            "missing_count": 1, "calendar_complete": True,
            "missing": [{"symbol": "600036.SH", "trade_date": "20260825", "dataset": "stock_daily"}],
        }


def test_product_data_readiness_is_bounded_and_actionable(monkeypatch) -> None:
    monkeypatch.setattr(main, "security_master_store", FakeSecurityMaster())
    monkeypatch.setattr(main, "market_readiness_store", FakeReadinessStore())

    response = TestClient(main.app).post(
        "/v1/data-center/readiness",
        headers={"x-byq-actor-principal": "alice"},
        json={
            "symbols": ["000001.SZ", "600036.SH"], "start_date": "20260824",
            "end_date": "20260825", "use_case": "backtest",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "limited"
    assert body["datasets"] == [{"label": "日线行情", "state": "missing", "missing_count": 1}]
    assert body["issues"][0]["recommended_action"] == "前往数据同步补齐该范围"
    assert "stock_daily" not in str(body)

    rejected = TestClient(main.app).post(
        "/v1/data-center/readiness",
        headers={"x-byq-actor-principal": "alice"},
        json={"symbols": [], "start_date": "20260824", "end_date": "20260825"},
    )
    assert rejected.status_code == 422


def _research_preparation_fakes(monkeypatch, *, state: str = "partial"):
    class ReadinessStore:
        requirements = []

        def requirement(self, **payload):
            self.requirements.append(payload)
            return {"schema_version": "fixture", "requirement_sha256": "a" * 64, **payload}

        def assess(self, requirement):
            return {
                "state": state, "required_session_count": 1, "required_cell_count": 1,
                "missing_count": 0 if state == "ready" else 1,
                "calendar_complete": True,
                "missing": [] if state == "ready" else [
                    {"symbol": "000001.SZ", "trade_date": "20260825", "dataset": "stock_daily"},
                ],
            }

    class RepairStore:
        calls = []
        records = {}

        def get_data_repair_by_requirement(self, identity):
            return self.records.get(identity)

        def request_data_repair(self, *, requirement, requested_by, retry_terminal):
            self.calls.append({
                "requirement": requirement, "requested_by": requested_by,
                "retry_terminal": retry_terminal,
            })
            identity = requirement["requirement_sha256"]
            return self.records.setdefault(identity, {
                "request_id": "datarepair_fixture", "status": "queued",
            })

    readiness = ReadinessStore()
    repair = RepairStore()
    monkeypatch.setattr(main, "security_master_store", FakeSecurityMaster())
    monkeypatch.setattr(main, "market_readiness_store", readiness)
    monkeypatch.setattr(main, "market_automation_store", repair)
    return readiness, repair


def test_research_preparation_requires_admin_and_reuses_existing_repair(monkeypatch) -> None:
    _readiness, repair = _research_preparation_fakes(monkeypatch)
    client = TestClient(main.app)
    payload = {
        "symbols": [f"{number:06d}.SZ" for number in range(1, 21)],
        "start_date": "20240101", "end_date": "20240628", "use_case": "research",
        "data_requirements": {"daily_basic": ["pe_ttm"], "fundamentals": ["roe"]},
    }
    user = client.post("/v1/data-center/research-preparations", json=payload, headers={
        "x-byq-actor-principal": "alice", "x-byq-actor-role": "user",
    })
    assert user.status_code == 403
    assert repair.calls == []

    monkeypatch.setattr(main, "_resolved_tushare_provider", lambda: (object(), {"source": "fixture"}))
    admin_headers = {"x-byq-actor-principal": "admin", "x-byq-actor-role": "admin"}
    first = client.post("/v1/data-center/research-preparations", json=payload, headers=admin_headers)
    repeated = client.post("/v1/data-center/research-preparations", json=payload, headers=admin_headers)

    assert first.status_code == repeated.status_code == 200
    assert first.json() == {"request_id": "datarepair_fixture", "status": "queued"}
    assert repeated.json() == first.json()
    assert len(repair.calls) == 1
    assert all(call["retry_terminal"] is False for call in repair.calls)
    assert all(call["requested_by"] == "research-preparation:admin" for call in repair.calls)
    scope = repair.calls[0]["requirement"]
    assert len(scope["symbols"]) == 20
    assert scope["start_date"] == "20240101" and scope["end_date"] == "20240628"
    assert scope["data_requirements"] == {"daily_basic": ["pe_ttm"], "fundamentals": ["roe"]}


def test_ready_research_preparation_does_not_resolve_source_or_enqueue(monkeypatch) -> None:
    _readiness, repair = _research_preparation_fakes(monkeypatch, state="ready")
    monkeypatch.setattr(
        main, "_resolved_tushare_provider",
        lambda: (_ for _ in ()).throw(AssertionError("ready scope must not need a source")),
    )
    response = TestClient(main.app).post(
        "/v1/data-center/research-preparations",
        headers={"x-byq-actor-principal": "admin", "x-byq-actor-role": "admin"},
        json={"symbols": ["000001.SZ"], "start_date": "20260824", "end_date": "20260825"},
    )
    assert response.status_code == 200
    assert response.json() == {"request_id": None, "status": "ready"}
    assert repair.calls == []


def test_research_preparation_blocks_unconfigured_or_ambiguous_source(monkeypatch) -> None:
    from app.data_provider import ProviderCredentialsMissing

    _readiness, repair = _research_preparation_fakes(monkeypatch)
    monkeypatch.setattr(
        main, "_resolved_tushare_provider",
        lambda: (_ for _ in ()).throw(ProviderCredentialsMissing("provider detail must not leak")),
    )
    response = TestClient(main.app).post(
        "/v1/data-center/research-preparations",
        headers={"x-byq-actor-principal": "admin", "x-byq-actor-role": "admin"},
        json={"symbols": ["000001.SZ"], "start_date": "20260824", "end_date": "20260825"},
    )
    assert response.status_code == 409
    assert "Tushare" in response.json()["detail"]
    assert "provider detail" not in response.text
    assert repair.calls == []


@pytest.mark.parametrize("payload", [
    {"symbols": [f"{number:06d}.SZ" for number in range(1, 22)],
     "start_date": "20240101", "end_date": "20240101"},
    {"symbols": ["000001.SZ"], "start_date": "20240101", "end_date": "20240629"},
    {"symbols": ["000001.SZ"], "start_date": "20240101", "end_date": "20240101",
     "data_requirements": {"benchmark": "000300.SH"}},
    {"symbols": ["000001.SZ"], "start_date": "20240101", "end_date": "20240101",
     "data_requirements": {"daily_basic": ["unsupported_field"]}},
    {"symbols": ["000001.SZ"], "start_date": "20240101", "end_date": "20240101",
     "use_case": "backtest"},
])
def test_research_preparation_rejects_out_of_scope_requests(monkeypatch, payload) -> None:
    _readiness, repair = _research_preparation_fakes(monkeypatch)
    response = TestClient(main.app).post(
        "/v1/data-center/research-preparations",
        headers={"x-byq-actor-principal": "admin", "x-byq-actor-role": "admin"},
        json=payload,
    )
    assert response.status_code == 422
    assert repair.calls == []

@pytest.mark.parametrize(("sessions", "cells"), [(0, 0), (1, 0)])
def test_ready_preparation_requires_an_actual_research_scope(monkeypatch, sessions, cells):
    readiness, repair = _research_preparation_fakes(monkeypatch, state="ready")
    monkeypatch.setattr(readiness, "assess", lambda requirement: {
        "state": "ready", "required_session_count": sessions, "required_cell_count": cells,
        "calendar_complete": True,
    })
    response = TestClient(main.app).post(
        "/v1/data-center/research-preparations",
        headers={"x-byq-actor-principal": "admin", "x-byq-actor-role": "admin"},
        json={"symbols": ["000001.SZ"], "start_date": "20260824", "end_date": "20260824"},
    )
    assert response.status_code == 422
    assert "调整标的或日期" in response.json()["detail"]
    assert repair.calls == []
