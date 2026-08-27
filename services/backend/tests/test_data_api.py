from __future__ import annotations

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


def test_persisted_market_research_api_passes_bounded_payload(monkeypatch) -> None:
    monkeypatch.setattr(main, "market_readiness_store", FakeResearchStore())
    client = TestClient(main.app)

    valuation = client.post("/v1/data/research/valuation", json={
        "symbols": ["000001.SZ"], "trade_date": "20260825", "fields": ["pe_ttm", "pb"],
    })
    fundamentals = client.post("/v1/data/research/fundamentals", json={
        "symbols": ["000001.SZ"], "as_of_date": "20260825", "fields": ["roe"],
    })

    assert valuation.status_code == 200
    assert valuation.json()["request"]["trade_date"] == "20260825"
    assert fundamentals.status_code == 200
    assert fundamentals.json()["request"]["as_of_date"] == "20260825"

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
