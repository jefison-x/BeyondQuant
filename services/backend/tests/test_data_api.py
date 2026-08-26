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
