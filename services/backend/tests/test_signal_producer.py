from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.market_data import MarketDataStore
from app.paper_trading import PaperTradingStore
from app.research import ResearchStore
from app.signal_producer import CallableSandboxExecutor, SignalJobStore, SignalProducerCoordinator


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)

SYMBOL = "000001.SZ"


def _headers(owner: str) -> dict[str, str]:
    return {
        "x-byq-owner-principal": owner,
        "x-byq-actor-principal": owner,
        "x-byq-trace-id": f"trace-{owner}",
        "x-byq-session-id": f"session-{owner}",
        "x-byq-dsh-run-id": f"run-{owner}",
    }


def _strategy() -> dict[str, object]:
    return {
        "strategy_id": "SignalStrategy",
        "name": "Signal Strategy",
        "category": "momentum",
        "description": "Signal producer fixture",
        "parameters": {"lookback": 2},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": (
            "class CustomStrategy:\n"
            "    def generate_signals(self, data, parameters=None):\n"
            "        return {}\n"
        ),
    }


def _bar(trade_date: str, close: float) -> dict[str, object]:
    return {
        "symbol": SYMBOL, "trade_date": trade_date, "open": close, "high": close,
        "low": close, "close": close, "volume": 1000, "amount": close * 1000,
        "asset_type": "stock", "data_source": "tushare", "provenance": {"source": "fixture"},
    }


def test_product_request_freezes_inputs_and_coordinator_materializes_snapshot(monkeypatch) -> None:
    research = ResearchStore()
    paper = PaperTradingStore()
    market = MarketDataStore()
    jobs = SignalJobStore()
    monkeypatch.setattr(main, "research_store", research)
    monkeypatch.setattr(main, "paper_store", paper)
    monkeypatch.setattr(main, "market_data_store", market)
    monkeypatch.setattr(main, "signal_job_store", jobs)
    client = TestClient(main.app)
    client.headers.update(_headers("signal-owner"))

    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "signal-owner", "title": "Signal task", "objective": "Freeze and run",
            "trace_id": "signal-trace", "idempotency_key": "signal-task-1",
        },
    ).json()
    draft = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"], "strategy": _strategy(), "trace_id": "signal-trace",
            "idempotency_key": "signal-draft-1",
        },
    ).json()
    version = client.post(
        "/v1/research/strategies/versions",
        json={
            "task_id": task["task_id"], "draft_artifact_id": draft["artifact"]["artifact_id"],
            "trace_id": "signal-trace", "idempotency_key": "signal-version-1",
        },
    ).json()
    pool = client.post(
        "/v1/paper/pools",
        json={"name": "Signal pool", "pool_type": "custom", "symbols": [SYMBOL]},
    ).json()["pool"]
    market.import_bars([_bar("20260105", 10.0), _bar("20260106", 11.0)])
    request = {
        "task_id": task["task_id"],
        "strategy_version_artifact_id": version["artifact"]["artifact_id"],
        "stock_pool_snapshot_id": pool["snapshot"]["snapshot_id"],
        "start_date": "2026-01-05", "end_date": "2026-01-06",
        "parameters": {"lookback": 2}, "execution": {"lot_size": 100, "max_runtime_seconds": 5},
        "order_quantity": 100, "trace_id": "signal-trace", "idempotency_key": "signal-job-1",
    }
    created = client.post("/v1/research/signal-producer/jobs", json=request)
    assert created.status_code == 202, created.text
    job = created.json()["job"]
    assert job["status"] == "queued"
    assert job["input"] == {
        "schema_version": "signal-producer-job-v1", "profile": "byq-signal-python-v1",
        "runtime_lock": "python-3.13/pandas-2.3.3/numpy-2.3.3", "symbol_count": 1, "bar_count": 2,
    }
    assert "script" not in created.text
    retry = client.post("/v1/research/signal-producer/jobs", json=request)
    assert retry.json()["job"]["job_id"] == job["job_id"]
    assert client.get(
        f"/v1/research/signal-producer/jobs/{job['job_id']}", headers=_headers("other-owner")
    ).status_code == 404

    def fake_sandbox(payload: dict[str, object], timeout: float) -> dict[str, object]:
        assert timeout == 5.0
        assert "database" not in str(payload).lower()
        return {
            "schema_version": "byq-signal-sandbox-response-v1",
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-06", "signal": 1}],
        }

    completed = SignalProducerCoordinator(
        jobs, research, CallableSandboxExecutor(fake_sandbox)
    ).run_next()
    assert completed is not None
    assert completed["status"] == "completed"
    artifact = research.get_artifact(completed["result_artifact_id"])
    assert artifact["kind"] == "signal_snapshot"
    assert artifact["status"] == "validated"
    assert artifact["content"]["signals"] == [
        {"symbol": SYMBOL, "trade_date": "2026-01-06", "direction": 1, "quantity": 100}
    ]
    assert artifact["content"]["source"]["producer"] == "byq-signal-python-v1"

    jobs.close()
    market.close()
    paper.close()
    research.close()
