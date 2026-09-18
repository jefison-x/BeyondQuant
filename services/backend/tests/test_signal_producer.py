from __future__ import annotations

import json
import os
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.backtest import (
    BacktestJobStore, LocalObjectStore, membership_fingerprint, signal_snapshot_content_sha256,
)
from app.backtest_task import task_id_from_signal_job
from app.market_data import MarketDataStore
from app.market_automation import MarketAutomationStore
from app.market_readiness import MarketReadinessStore
from app.paper_trading import PaperTradingStore
from app.research import ResearchStore
from app.security_master import SecurityMasterStore
from app.signal_producer import (
    CallableSandboxExecutor, SignalJobStore, SignalProducerCoordinator, prepare_signal_job_input,
    promote_waiting_signal_jobs,
)
from packages.contracts.bars_frame import frame_raw_rows, frame_research_rows
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


def _seed_ready_signal_fixture(monkeypatch, tmp_path) -> SimpleNamespace:
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
        json={"idempotency_key": "test-pool-104", "name": "Signal pool", "pool_type": "custom", "symbols": [SYMBOL]},
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
    return SimpleNamespace(
        research=research, paper=paper, market=market, jobs=jobs, readiness=readiness,
        automation=automation, securities=securities, backtests=backtests, client=client,
        task=task, version=version, pool=pool,
    )


def test_product_request_freezes_inputs_and_coordinator_materializes_snapshot(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    research, paper, market = fixture.research, fixture.paper, fixture.market
    jobs, readiness = fixture.jobs, fixture.readiness
    client, task, version, pool = fixture.client, fixture.task, fixture.version, fixture.pool
    backtests = fixture.backtests
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
    assert job["readiness"]["state"] == "unknown"
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
        assert payload["bars"]["schema_version"] == "bars_frame.v1"
        assert payload["bars"]["basis"] == "research"
        rows = frame_research_rows(payload["bars"])
        assert set(rows[0]) <= {
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
            "reviewer_principal": "signal-owner",
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


def test_promote_waiting_signal_jobs_fails_over_cap_job_and_continues(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    client, jobs, readiness = fixture.client, fixture.jobs, fixture.readiness
    automation, task, version, pool = fixture.automation, fixture.task, fixture.version, fixture.pool

    symbols = [f"{index:06d}.SZ" for index in range(2000)]
    over_cap = readiness.requirement(
        symbols=symbols, start_date="2026-03-01", end_date="2026-03-31",
        membership_fingerprint="over-cap-fixture", security_master_snapshot_id="sms_fixture",
    )
    for day in range(1, 27):
        trade_date = f"202603{day:02d}"
        automation._execute("""INSERT INTO market_trading_sessions
            (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
            VALUES (:date,'SSE',TRUE,'tushare','cal-over',now(),:sha,now())""",
            {"date": trade_date, "sha": f"cal-over-{trade_date}"})
    with pytest.raises(ValueError, match="symbol-session cells"):
        readiness.assess(over_cap)

    offending = jobs.create_waiting(
        owner_principal="signal-owner", task_id=task["task_id"], experiment_id=None,
        strategy_version_artifact_id=version["artifact"]["artifact_id"],
        stock_pool_snapshot_id=pool["snapshot"]["snapshot_id"],
        preparation={"strategy_version_artifact_id": str(version["artifact"]["artifact_id"])},
        requirement=over_cap, readiness={"state": "unknown", "missing": []},
        trace_id="signal-trace", idempotency_key="signal-job-over-cap",
    )
    jobs._execute("UPDATE signal_producer_jobs SET created_at=:early WHERE job_id=:id",
                  {"early": "2000-01-01T00:00:00+00:00", "id": offending["job_id"]})

    valid = client.post("/v1/research/signal-producer/jobs", json={
        "task_id": task["task_id"],
        "strategy_version_artifact_id": version["artifact"]["artifact_id"],
        "stock_pool_snapshot_id": pool["snapshot"]["snapshot_id"],
        "start_date": "2026-01-05", "end_date": "2026-01-06",
        "parameters": {"lookback": 2}, "execution": {"lot_size": 100, "max_runtime_seconds": 5},
        "order_quantity": 100, "trace_id": "signal-trace", "idempotency_key": "signal-job-valid",
    })
    assert valid.status_code == 202, valid.text
    valid_job_id = valid.json()["job"]["job_id"]

    assert promote_waiting_signal_jobs(jobs, readiness) == 1

    rejected = jobs.get(offending["job_id"], trusted_owner="signal-owner")
    assert rejected["status"] == "failed"
    assert rejected["error_code"] == "market_requirement_exceeded"
    assert rejected["error_detail"]
    promoted = jobs.get(valid_job_id, trusted_owner="signal-owner")
    assert promoted["status"] == "queued"

    jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()


def _create_symbol_pool(
    fixture: SimpleNamespace, *, symbols: list[str], key: str, delist_date: str | None = None,
) -> str:
    pool = fixture.client.post("/v1/paper/pools", json={
        "idempotency_key": key, "name": f"Pool {key}", "pool_type": "custom", "symbols": symbols,
    }).json()["pool"]
    fixture.securities._execute(
        """INSERT INTO security_master_snapshot_members
           (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,delist_date,
            asset_type,content_sha256)
           SELECT 'sms_fixture', symbol, split_part(symbol,'.',1), 'Fixture', 'SZSE', 'L',
                  '19910101', :delist_date, 'stock', 'member-' || symbol
           FROM jsonb_array_elements_text(:symbols) AS t(symbol)
           ON CONFLICT (snapshot_id, symbol) DO NOTHING""",
        {"symbols": symbols, "delist_date": delist_date},
    )
    return str(pool["snapshot"]["snapshot_id"])


def _seed_sparse_open_sessions(fixture: SimpleNamespace, *, start: date, end: date, step_days: int) -> int:
    count, cursor = 0, start
    while cursor <= end:
        trade_date = cursor.strftime("%Y%m%d")
        fixture.automation._execute(
            """INSERT INTO market_trading_sessions
               (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
               VALUES (:date,'SSE',TRUE,'tushare','plan-cal',now(),:sha,now())
               ON CONFLICT (trade_date) DO NOTHING""",
            {"date": trade_date, "sha": f"plan-cal-{trade_date}"},
        )
        count += 1
        cursor += timedelta(days=step_days)
    return count


def _seed_calendar_window(
    fixture: SimpleNamespace, *, start: date, end: date, open_dates: set[date],
) -> None:
    cursor = start
    while cursor <= end:
        trade_date = cursor.strftime("%Y%m%d")
        fixture.automation._execute(
            """INSERT INTO market_trading_sessions
               (trade_date,exchange,is_open,data_source,request_fingerprint,retrieved_at,content_sha256,updated_at)
               VALUES (:date,'SSE',:open,'tushare','window-cal',now(),:sha,now())
               ON CONFLICT (trade_date) DO UPDATE SET is_open=EXCLUDED.is_open""",
            {"date": trade_date, "open": cursor in open_dates, "sha": f"window-cal-{trade_date}"},
        )
        cursor += timedelta(days=1)


def _seed_ready_cells(fixture: SimpleNamespace, *, symbols: list[str], open_dates: set[date]) -> None:
    for session in sorted(open_dates):
        trade_date = session.strftime("%Y%m%d")
        fixture.readiness._execute(
            """INSERT INTO market_session_supplement_completeness
               (trade_date,adjustment_complete,corporate_actions_complete,factor_row_count,
                corporate_action_row_count,content_sha256,provenance_json,verified_at)
               VALUES (:date,TRUE,TRUE,:n,0,:sha,'{}',now())""",
            {"date": trade_date, "n": len(symbols), "sha": f"supplement-{trade_date}"},
        )
        for symbol in symbols:
            close = 10.0
            fixture.readiness._execute(
                """INSERT INTO market_daily_status
                   (symbol,trade_date,is_suspended,pre_close,up_limit,down_limit,data_source,
                    provenance_json,content_sha256,updated_at)
                   VALUES (:symbol,:date,FALSE,:pre,:up,:down,'tushare','{}',:sha,now())""",
                {"symbol": symbol, "date": trade_date, "pre": close - 0.5, "up": close * 1.1,
                 "down": close * .9, "sha": f"status-{symbol}-{trade_date}"},
            )
            fixture.readiness._execute(
                """INSERT INTO market_adjustment_factors
                   (symbol,trade_date,adj_factor,data_source,provenance_json,content_sha256,updated_at)
                   VALUES (:symbol,:date,1,'tushare','{}',:sha,now())""",
                {"symbol": symbol, "date": trade_date, "sha": f"factor-{symbol}-{trade_date}"},
            )
            fixture.market.import_bars([{
                "symbol": symbol, "trade_date": trade_date, "open": close, "high": close,
                "low": close, "close": close, "volume": 1000, "amount": close * 1000,
                "asset_type": "stock", "data_source": "tushare", "provenance": {"source": "fixture"},
            }])


def _signal_request(
    fixture: SimpleNamespace, *, snapshot_id: str, start: str, end: str, key: str,
) -> dict[str, object]:
    return {
        "task_id": fixture.task["task_id"],
        "strategy_version_artifact_id": fixture.version["artifact"]["artifact_id"],
        "stock_pool_snapshot_id": snapshot_id,
        "start_date": start, "end_date": end,
        "parameters": {"lookback": 2}, "execution": {"lot_size": 100, "max_runtime_seconds": 5},
        "order_quantity": 100, "trace_id": "signal-trace", "idempotency_key": key,
    }


def test_aggregate_scope_over_cell_bound_partitions_and_prepare_succeeds(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    symbols = [f"{index:06d}.SZ" for index in range(1, 301)]
    snapshot_id = _create_symbol_pool(fixture, symbols=symbols, key="over-cap-plan-pool")
    session_count = _seed_sparse_open_sessions(
        fixture, start=date(2023, 9, 18), end=date(2026, 9, 17), step_days=6,
    )
    assert len(symbols) * session_count > 50_000

    request = _signal_request(
        fixture, snapshot_id=snapshot_id,
        start="2023-09-18", end="2026-09-17", key="over-cap-plan-job",
    )
    prepared = main._prepare_signal_producer(
        {key: value for key, value in request.items() if key != "idempotency_key"},
        owner_principal="signal-owner", request_repair=False,
    )
    plan = prepared["requirement_plan"]
    assert 1 < len(prepared["requirements"]) <= 32
    assert plan["partition_count"] == len(prepared["requirements"])
    assert plan["requirement_plan_sha256"]
    assert prepared["readiness"]["partition_count"] == plan["partition_count"]
    assert prepared["readiness"]["state"] != "ready"
    with pytest.raises(ValueError, match="symbol-session cells"):
        fixture.readiness.assess(prepared["requirement"])

    repeated = main._prepare_signal_producer(
        {key: value for key, value in request.items() if key != "idempotency_key"},
        owner_principal="signal-owner", request_repair=False,
    )
    assert repeated["requirement_plan"]["requirement_plan_sha256"] == plan["requirement_plan_sha256"]
    assert repeated["requirements"] == prepared["requirements"]

    response = fixture.client.post("/v1/research/backtest-tasks/prepare", json={
        key: value for key, value in request.items() if key not in {"trace_id", "idempotency_key"}
    })
    assert response.status_code == 200, response.text
    readiness = response.json()["task"]["market_readiness"]
    assert readiness["partition_count"] == plan["partition_count"]
    assert readiness["state"] != "ready"

    fixture.jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()


def test_partitioned_job_repairs_each_not_ready_partition_without_promoting(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    symbols = ["600000.SH", "600001.SH"]
    snapshot_id = _create_symbol_pool(fixture, symbols=symbols, key="partition-repair-pool")
    first_open = {date(2026, 2, 2), date(2026, 2, 3)}
    _seed_calendar_window(fixture, start=date(2026, 1, 1), end=date(2026, 6, 29), open_dates=first_open)
    _seed_ready_cells(fixture, symbols=symbols, open_dates=first_open)

    created = fixture.client.post("/v1/research/signal-producer/jobs", json=_signal_request(
        fixture, snapshot_id=snapshot_id, start="2026-01-01", end="2026-09-30", key="partition-repair-job",
    ))
    assert created.status_code == 202, created.text
    job = created.json()["job"]
    assert job["requirement_plan"]["partition_count"] == 2

    assert promote_waiting_signal_jobs(fixture.jobs, fixture.readiness, fixture.automation) == 0

    job = fixture.jobs.get(job["job_id"], trusted_owner="signal-owner")
    assert job["status"] == "waiting_for_data"
    assert job["readiness"]["state"] != "ready"
    assert job["readiness"]["partition_count"] == 2
    repairs = fixture.automation._execute("SELECT requirement_json FROM market_data_repair_requests")
    assert len(repairs) == 1
    assert str(repairs[0]["requirement_json"]["start_date"]) == "20260630"

    fixture.jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()


def test_partitioned_job_promotes_only_after_all_partitions_are_ready(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    symbols = ["600010.SH", "600011.SH"]
    snapshot_id = _create_symbol_pool(fixture, symbols=symbols, key="partition-ready-pool")
    first_open = {date(2026, 2, 2), date(2026, 2, 3)}
    second_open = {date(2026, 7, 1), date(2026, 7, 2)}
    open_dates = first_open | second_open
    _seed_calendar_window(
        fixture, start=date(2026, 1, 1), end=date(2026, 9, 30), open_dates=open_dates,
    )
    _seed_ready_cells(fixture, symbols=symbols, open_dates=open_dates)

    created = fixture.client.post("/v1/research/signal-producer/jobs", json=_signal_request(
        fixture, snapshot_id=snapshot_id, start="2026-01-01", end="2026-09-30", key="partition-ready-job",
    ))
    assert created.status_code == 202, created.text
    job = created.json()["job"]
    plan = job["requirement_plan"]
    assert plan["partition_count"] == 2

    assert promote_waiting_signal_jobs(fixture.jobs, fixture.readiness) == 1
    job = fixture.jobs.get(job["job_id"], trusted_owner="signal-owner")
    assert job["status"] == "queued"
    assert job["readiness"]["state"] == "ready"
    assert job["readiness"]["ready_partitions"] == 2

    document = fixture.jobs._fetch_one(
        "SELECT input_json FROM signal_producer_jobs WHERE job_id=:id", {"id": job["job_id"]}
    )["input_json"]
    assert "bars_frame" in document
    assert "bars" not in document and "research_bars" not in document
    raw_rows = frame_raw_rows(document["bars_frame"])
    bar_dates = {bar["trade_date"] for bar in raw_rows}
    assert bar_dates == {
        "2026-02-02", "2026-02-03", "2026-07-01", "2026-07-02",
    }
    assert len(document["bars_frame"]["research_fields"]) == len(document["bars_frame"]["bars_fields"])
    assert document["data_readiness"]["requirement_plan_sha256"] == plan["requirement_plan_sha256"]
    assert document["data_readiness"]["ready_input_sha256"] == job["readiness"]["ready_input_sha256"]
    expected = fixture.readiness.build_partitioned_ready_input(plan["requirements"])
    assert document["data_readiness"]["research_view_sha256"] == expected["research_view_sha256"]

    fixture.jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()


def test_partitioned_job_with_mid_window_delisting_promotes(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    symbols = ["600020.SH", "600021.SH"]
    snapshot_id = _create_symbol_pool(
        fixture, symbols=symbols, key="partition-delist-pool", delist_date="20260630",
    )
    first_open = {date(2026, 2, 2), date(2026, 2, 3)}
    delist_open = {date(2026, 6, 30)}
    _seed_calendar_window(
        fixture, start=date(2026, 1, 1), end=date(2026, 9, 30),
        open_dates=first_open | delist_open,
    )
    _seed_ready_cells(fixture, symbols=symbols, open_dates=first_open)
    fixture.readiness._execute(
        """INSERT INTO market_session_supplement_completeness
           (trade_date,adjustment_complete,corporate_actions_complete,factor_row_count,
            corporate_action_row_count,content_sha256,provenance_json,verified_at)
           VALUES ('20260630',TRUE,TRUE,0,0,'supplement-delist','{}',now())"""
    )

    created = fixture.client.post("/v1/research/signal-producer/jobs", json=_signal_request(
        fixture, snapshot_id=snapshot_id, start="2026-01-01", end="2026-09-30",
        key="partition-delist-job",
    ))
    assert created.status_code == 202, created.text
    job = created.json()["job"]
    assert job["requirement_plan"]["partition_count"] == 2

    assert promote_waiting_signal_jobs(fixture.jobs, fixture.readiness) == 1

    job = fixture.jobs.get(job["job_id"], trusted_owner="signal-owner")
    assert job["status"] == "queued"
    assert job["readiness"]["state"] == "ready"
    assert job["readiness"]["ready_partitions"] == 2

    fixture.jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()


def test_prepare_signal_job_input_is_deterministic_and_content_addressed() -> None:
    def build(*, reverse: bool) -> dict[str, object]:
        rows = [
            (f"{symbol:06d}.SZ", f"2026-01-{session:02d}")
            for symbol in range(3) for session in range(1, 5)
        ]
        if reverse:
            rows = list(reversed(rows))
        bars: list[dict[str, object]] = []
        research: list[dict[str, object]] = []
        multipliers: list[float] = []
        for index, (symbol, trade_date) in enumerate(rows):
            close = round(10.0 + int(symbol[:6]) + int(trade_date[-2:]) * 0.1, 2)
            raw = {
                "symbol": symbol, "trade_date": trade_date, "open": close, "high": close,
                "low": close, "close": close, "prev_close": close, "volume": 1000,
                "is_suspended": False, "up_limit": round(close * 1.1, 2),
                "down_limit": round(close * 0.9, 2),
            }
            factor = 1.05
            adjusted = dict(raw)
            for field in ("open", "high", "low", "close", "prev_close", "up_limit", "down_limit"):
                adjusted[field] = round(float(adjusted[field]) * factor, 8)
            bars.append(raw)
            research.append(adjusted)
            multipliers.append(factor)
        return prepare_signal_job_input(
            strategy_version_artifact_id="artifact_strategy_1", strategy_version_id="version_1",
            source_fingerprint="f" * 64,
            script="class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}\n",
            stock_pool_snapshot_id="pool_snapshot_1", stock_pool_id="pool_1",
            membership_fingerprint="m" * 64, symbols=sorted({row[0] for row in rows}),
            bars=bars, parameters={"lookback": 2},
            execution={"lot_size": 100, "max_runtime_seconds": 5}, order_quantity=100,
            research_bars=research, research_multipliers=multipliers,
        )

    first = build(reverse=False)
    second = build(reverse=True)
    assert first["input_sha256"] == second["input_sha256"]


def test_columnar_document_yields_identical_snapshot_identity_to_legacy_rows() -> None:
    bars = [
        {
            "symbol": SYMBOL, "trade_date": trade_date, "open": close, "high": close,
            "low": close, "close": close, "prev_close": previous, "volume": 1000,
            "is_suspended": False, "up_limit": round(close * 1.1, 2),
            "down_limit": round(close * 0.9, 2),
        }
        for trade_date, close, previous in (("2026-01-05", 10.0, 10.0), ("2026-01-06", 11.0, 10.0))
    ]
    multipliers = [1.0, 1.0]
    research = [dict(row) for row in bars]
    document = prepare_signal_job_input(
        strategy_version_artifact_id="artifact_" + "a" * 32, strategy_version_id="version_1",
        source_fingerprint="f" * 64,
        script="class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}\n",
        stock_pool_snapshot_id="pool_snapshot_1", stock_pool_id="pool_1",
        membership_fingerprint=membership_fingerprint([SYMBOL]), symbols=[SYMBOL], bars=bars,
        parameters={"lookback": 2}, execution={"lot_size": 100, "max_runtime_seconds": 5},
        order_quantity=100, research_bars=research, research_multipliers=multipliers,
    )
    legacy = dict(document)
    legacy.pop("bars_frame")
    legacy["bars"] = bars
    legacy["research_bars"] = research

    def executor(payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
        return {
            "schema_version": "byq-signal-sandbox-response-v1",
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-06", "signal": 1}],
        }

    coordinator = SignalProducerCoordinator(None, None, CallableSandboxExecutor(executor))
    columnar_snapshot = coordinator._produce({"input": document})
    legacy_snapshot = coordinator._produce({"input": legacy})
    assert signal_snapshot_content_sha256(columnar_snapshot) == signal_snapshot_content_sha256(legacy_snapshot)


def _large_ready_input(
    symbols: int = 300, sessions: int = 727, *, limits: bool = True,
) -> dict[str, object]:
    bars: list[dict[str, object]] = []
    research: list[dict[str, object]] = []
    multipliers: list[float] = []
    for symbol_index in range(symbols):
        symbol = f"{symbol_index:06d}.SZ"
        previous = 10.0
        for session in range(sessions):
            trade_date = (date(2023, 1, 2) + timedelta(days=session)).isoformat()
            close = 10.0
            raw: dict[str, object] = {
                "symbol": symbol, "trade_date": trade_date, "open": close, "high": close,
                "low": close, "close": close, "prev_close": previous, "volume": 0,
                "is_suspended": False,
            }
            if limits:
                raw["up_limit"] = round(close * 1.1, 2)
                raw["down_limit"] = round(close * 0.9, 2)
            bars.append(raw)
            research.append(dict(raw))
            multipliers.append(1.0)
            previous = close
    return {
        "bars": bars, "research_bars": research, "research_multipliers": multipliers,
        "research_view_sha256": "r" * 64, "corporate_actions": [], "benchmark": [], "declared": {},
    }


def test_promotion_builds_columnar_frame_without_size_failure(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    request = _signal_request(
        fixture, snapshot_id=fixture.pool["snapshot"]["snapshot_id"],
        start="2026-01-05", end="2026-01-06", key="large-frame-job",
    )
    created = fixture.client.post("/v1/research/signal-producer/jobs", json=request)
    assert created.status_code == 202, created.text
    job_id = created.json()["job"]["job_id"]

    large = _large_ready_input()
    monkeypatch.setattr(
        fixture.readiness, "assess",
        lambda requirement: {"state": "ready", "ready_input_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        fixture.readiness, "build_ready_input", lambda requirement, **kwargs: large,
    )

    assert promote_waiting_signal_jobs(fixture.jobs, fixture.readiness) == 1
    job = fixture.jobs.get(job_id, trusted_owner="signal-owner")
    assert job["status"] == "queued"
    assert job["input"]["bar_count"] == 300 * 727

    document = fixture.jobs._fetch_one(
        "SELECT input_json FROM signal_producer_jobs WHERE job_id=:id", {"id": job_id}
    )["input_json"]
    assert document["bars_frame"]["schema_version"] == "bars_frame.v1"
    assert "bars" not in document and "research_bars" not in document
    assert len(frame_raw_rows(document["bars_frame"])) == 300 * 727
    encoded = json.dumps(
        document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert len(encoded) < 32 * 1024 * 1024
    print(f"\npromoted job document={len(encoded) / 1024 / 1024:.2f}MiB")

    fixture.jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()


def test_promoted_aggregate_job_produces_snapshot_beyond_retired_bound(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    symbols = [f"{index:06d}.SZ" for index in range(300)]
    snapshot_id = _create_symbol_pool(fixture, symbols=symbols, key="aggregate-produce-pool")
    created = fixture.client.post("/v1/research/signal-producer/jobs", json=_signal_request(
        fixture, snapshot_id=snapshot_id, start="2026-01-05", end="2026-01-06",
        key="aggregate-produce-job",
    ))
    assert created.status_code == 202, created.text
    job_id = created.json()["job"]["job_id"]

    large = _large_ready_input(limits=False)
    monkeypatch.setattr(
        fixture.readiness, "assess",
        lambda requirement: {"state": "ready", "ready_input_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        fixture.readiness, "build_ready_input", lambda requirement, **kwargs: large,
    )
    monkeypatch.setattr(
        fixture.readiness, "build_partitioned_ready_input", lambda requirements, **kwargs: large,
    )
    assert promote_waiting_signal_jobs(fixture.jobs, fixture.readiness) == 1

    def executor(payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
        return {
            "schema_version": "byq-signal-sandbox-response-v1",
            "signals": [{"symbol": symbols[0], "trade_date": "2023-01-02", "signal": 1}],
        }

    completed = SignalProducerCoordinator(
        fixture.jobs, fixture.research, CallableSandboxExecutor(executor)
    ).run_next()
    assert completed is not None and completed["status"] == "completed", completed
    artifact = fixture.research.get_artifact(completed["result_artifact_id"])
    assert len(artifact["content"]["bars"]) == 300 * 727
    assert artifact["content"]["signals"][0]["symbol"] == symbols[0]

    fixture.jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()


def test_job_without_plan_keeps_single_requirement_behaviour(monkeypatch, tmp_path) -> None:
    fixture = _seed_ready_signal_fixture(monkeypatch, tmp_path)
    request = _signal_request(
        fixture, snapshot_id=fixture.pool["snapshot"]["snapshot_id"],
        start="2026-01-05", end="2026-01-06", key="legacy-no-plan-job",
    )
    prepared = main._prepare_signal_producer(
        {key: value for key, value in request.items() if key != "idempotency_key"},
        owner_principal="signal-owner", request_repair=False, assess_readiness=False,
    )
    job = fixture.jobs.create_waiting(
        owner_principal="signal-owner", task_id=prepared["task"]["task_id"], experiment_id=None,
        strategy_version_artifact_id=prepared["version"]["artifact_id"],
        stock_pool_snapshot_id=prepared["pool_snapshot"]["snapshot_id"],
        preparation=prepared["preparation"], requirement=prepared["requirement"],
        readiness={"state": "unknown", "missing": []},
        trace_id="signal-trace", idempotency_key="legacy-no-plan-job",
    )
    assert job["requirement_plan"] is None

    assert promote_waiting_signal_jobs(fixture.jobs, fixture.readiness) == 1
    job = fixture.jobs.get(job["job_id"], trusted_owner="signal-owner")
    assert job["status"] == "queued"
    assert job["readiness"]["state"] == "ready"
    document = fixture.jobs._fetch_one(
        "SELECT input_json FROM signal_producer_jobs WHERE job_id=:id", {"id": job["job_id"]}
    )["input_json"]
    assert document["data_readiness"]["requirement_sha256"] == prepared["requirement"]["requirement_sha256"]
    assert "requirement_plan_sha256" not in document["data_readiness"]

    fixture.jobs.close()
    fixture.market.close()
    fixture.paper.close()
    fixture.research.close()
    fixture.backtests.close()
