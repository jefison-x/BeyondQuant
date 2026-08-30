from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.backtest import BacktestJobStore, LocalObjectStore
from app.backtest_task import task_id_from_signal_job
from app.market_data import MarketDataStore
from app.market_automation import MarketAutomationStore
from app.market_readiness import MarketReadinessStore
from app.paper_trading import PaperTradingStore
from app.research import ResearchStore
from app.security_master import SecurityMasterStore
from app.signal_producer import (
    CallableSandboxExecutor, SignalJobStore, SignalProducerCoordinator, promote_waiting_signal_jobs,
)
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)

SYMBOL = "000001.SZ"


def _headers(owner: str) -> dict[str, str]:
    return trusted_agent_context(
        owner, trace_id=f"trace-{owner}", session_id=f"session-{owner}",
        dsh_run_id=f"run-{owner}",
    )


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


def test_product_request_freezes_inputs_and_coordinator_materializes_snapshot(monkeypatch, tmp_path) -> None:
    research = ResearchStore()
    paper = PaperTradingStore()
    market = MarketDataStore()
    jobs = SignalJobStore()
    readiness = MarketReadinessStore()
    automation = MarketAutomationStore()
    securities = SecurityMasterStore()
    backtests = BacktestJobStore()
    monkeypatch.setattr(main, "research_store", research)
    monkeypatch.setattr(main, "paper_store", paper)
    monkeypatch.setattr(main, "market_data_store", market)
    monkeypatch.setattr(main, "signal_job_store", jobs)
    monkeypatch.setattr(main, "market_readiness_store", readiness)
    monkeypatch.setattr(main, "market_automation_store", automation)
    monkeypatch.setattr(main, "security_master_store", securities)
    monkeypatch.setattr(main, "backtest_store", backtests)
    monkeypatch.setattr(main, "backtest_objects", LocalObjectStore(tmp_path / "backtest-objects"))
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
    securities._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,
         retrieved_at,requested_by) VALUES ('sms_fixture','tushare','stock_basic','dataset_fixture',
         'request_fixture','[\"L\"]',1,now(),'test')""")
    securities._execute("""INSERT INTO security_master_snapshot_members
        (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,asset_type,content_sha256)
        VALUES ('sms_fixture',:symbol,'000001','Fixture','SZSE','L','19910101','stock','member_sha')""",
        {"symbol": SYMBOL})
    automation._execute("""INSERT INTO market_trading_sessions
        (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
        VALUES ('20260105','SSE',TRUE,'tushare','cal',now(),'cal1',now()),
               ('20260106','SSE',TRUE,'tushare','cal',now(),'cal2',now())""")
    for date, close, previous in (("20260105", 10.0, 9.5), ("20260106", 11.0, 10.0)):
        readiness._execute("""INSERT INTO market_daily_status
            (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
             provenance_json,content_sha256,updated_at)
            VALUES (:symbol,:date,FALSE,:close,:up,:down,'tushare','{}',:sha,now())""",
            {"symbol": SYMBOL, "date": date, "close": previous, "up": close * 1.1,
             "down": close * .9, "sha": f"status-{date}"})
        readiness._execute("""INSERT INTO market_adjustment_factors
            (symbol,trade_date,adj_factor,data_source,provenance_json,content_sha256,updated_at)
            VALUES (:symbol,:date,1,'tushare','{}',:sha,now())""",
            {"symbol": SYMBOL, "date": date, "sha": f"factor-{date}"})
        readiness._execute("""INSERT INTO market_session_supplement_completeness
            (trade_date,adjustment_complete,corporate_actions_complete,factor_row_count,
             corporate_action_row_count,content_sha256,provenance_json,verified_at)
            VALUES (:date,TRUE,TRUE,1,0,:sha,'{}',now())""",
            {"date": date, "sha": f"supplement-{date}"})
    request = {
        "task_id": task["task_id"],
        "strategy_version_artifact_id": version["artifact"]["artifact_id"],
        "stock_pool_snapshot_id": pool["snapshot"]["snapshot_id"],
        "start_date": "2026-01-05", "end_date": "2026-01-06",
        "parameters": {"lookback": 2}, "execution": {"lot_size": 100, "max_runtime_seconds": 5},
        "order_quantity": 100, "trace_id": "signal-trace", "idempotency_key": "signal-job-1",
    }
    prepared = client.post(
        "/v1/research/backtest-tasks/prepare",
        json={key: value for key, value in request.items() if key not in {"trace_id", "idempotency_key"}},
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["task"]["phase"] == "prepared"
    assert prepared.json()["task"]["blockers"][0]["code"] == "approval_required"
    assert jobs.list_jobs(trusted_owner="signal-owner")["total"] == 0
    created = client.post("/v1/research/signal-producer/jobs", json=request)
    assert created.status_code == 202, created.text
    job = created.json()["job"]
    assert job["status"] == "waiting_for_data"
    assert job["readiness"]["state"] == "ready"
    assert jobs.claim_next() is None
    assert promote_waiting_signal_jobs(jobs, readiness) == 1
    job = jobs.get(job["job_id"], trusted_owner="signal-owner")
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
        assert set(payload["bars"][0]) <= {
            "symbol", "trade_date", "open", "high", "low", "close", "prev_close",
            "volume", "is_suspended", "up_limit", "down_limit",
        }
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

    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"],
            "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-reviewer",
            "decision": "approved",
            "trace_id": "signal-trace",
            "idempotency_key": "signal-approval-1",
        },
    )
    assert approval.status_code == 201, approval.text
    facade_id = task_id_from_signal_job(job["job_id"])
    facade = client.get(f"/v1/research/backtest-tasks/{facade_id}")
    assert facade.status_code == 200, facade.text
    assert facade.json()["task"]["phase"] == "ready_to_execute"
    assert "bars" not in facade.text and "signals" not in facade.text
    assert client.get(
        f"/v1/research/backtest-tasks/{facade_id}", headers=_headers("other-owner")
    ).status_code == 404
    executed = client.post(f"/v1/research/backtest-tasks/{facade_id}/execute")
    assert executed.status_code == 200, executed.text
    assert executed.json()["task"]["phase"] == "completed"
    assert executed.json()["task"]["references"]["result_artifact_id"]

    jobs.close()
    market.close()
    paper.close()
    research.close()
    backtests.close()
