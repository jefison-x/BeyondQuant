from __future__ import annotations

import os

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.backtest import (
    BacktestConflict,
    BacktestJobStore,
    BacktestWorker,
    LocalObjectStore,
    ObjectIntegrityError,
    build_backtest_analysis,
    membership_fingerprint,
    normalize_backtest_request,
    run_native_backtest,
)
from app.research import ResearchStore
from app.strategy_artifact import prepare_strategy, strategy_version_content


SYMBOL = "000001.SZ"


def universe() -> dict[str, object]:
    symbols = [SYMBOL]
    return {
        "universe_id": "fixture-universe",
        "version_id": "universe-v1",
        "membership_fingerprint": membership_fingerprint(symbols),
        "symbols": symbols,
    }


def bars(*, day_two_open: float = 10.0, day_three_open: float = 10.0) -> list[dict[str, object]]:
    return [
        {"symbol": SYMBOL, "trade_date": "2026-01-05", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0},
        {"symbol": SYMBOL, "trade_date": "2026-01-06", "open": day_two_open, "high": day_two_open, "low": day_two_open, "close": day_two_open},
        {"symbol": SYMBOL, "trade_date": "2026-01-07", "open": day_three_open, "high": day_three_open, "low": day_three_open, "close": day_three_open},
    ]


def request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_id": "task_00000000000000000000000000000001",
        "strategy_version_artifact_id": "artifact_00000000000000000000000000000001",
        "approval_artifact_id": "artifact_00000000000000000000000000000002",
        "trace_id": "byq-trace-backtest-test",
        "idempotency_key": "backtest-test-1",
        "universe": universe(),
        "bars": bars(),
        "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
        "execution": {"initial_capital": 2_000.0, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
    }
    payload.update(overrides)
    return payload


def normalized(**overrides: object) -> dict[str, object]:
    payload = request(**overrides)
    return normalize_backtest_request(
        payload,
        strategy_version_artifact_id=payload["strategy_version_artifact_id"],
        approval_artifact_id=payload["approval_artifact_id"],
    )


def test_manifest_is_content_addressed_and_rejects_duplicate_or_bad_bars() -> None:
    first = normalized()
    second = normalized(bars=list(reversed(bars())))
    assert first["input_manifest_id"] == second["input_manifest_id"]

    with pytest.raises(ValueError, match="duplicate bar"):
        normalize_backtest_request(
            request(bars=bars() + [bars()[0]]),
            strategy_version_artifact_id=request()["strategy_version_artifact_id"],
            approval_artifact_id=request()["approval_artifact_id"],
        )

    invalid = bars()
    invalid[0]["high"] = 9.0
    with pytest.raises(ValueError, match="OHLC"):
        normalize_backtest_request(
            request(bars=invalid),
            strategy_version_artifact_id=request()["strategy_version_artifact_id"],
            approval_artifact_id=request()["approval_artifact_id"],
        )


def test_native_engine_executes_next_session_and_applies_sell_tax() -> None:
    payload = normalized(
        bars=bars(day_two_open=10.0, day_three_open=11.0),
        signals=[
            {"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100},
            {"symbol": SYMBOL, "trade_date": "2026-01-06", "side": "sell", "quantity": 100},
        ],
        execution={"initial_capital": 2_000.0, "commission_rate": 0, "stamp_tax_rate": 0.001, "lot_size": 100},
    )
    result = run_native_backtest(payload["manifest"])
    assert [trade["timestamp"] for trade in result["trades"]] == ["2026-01-06", "2026-01-07"]
    assert result["trades"][1]["tax"] == 1.1
    assert result["trades"][0]["quantity"] == 100
    assert result["reproducibility"] == "reproducible"


def test_native_engine_reports_frozen_benchmark_and_excess_return() -> None:
    payload = normalized(benchmark=[
        {"symbol": "000300.SH", "trade_date": "2026-01-05", "open": 100, "high": 100, "low": 100, "close": 100},
        {"symbol": "000300.SH", "trade_date": "2026-01-06", "open": 101, "high": 101, "low": 101, "close": 101},
        {"symbol": "000300.SH", "trade_date": "2026-01-07", "open": 102, "high": 102, "low": 102, "close": 102},
    ])

    result = run_native_backtest(payload["manifest"])

    assert result["benchmark_symbol"] == "000300.SH"
    assert result["benchmark_return"] == 0.02
    assert result["excess_return"] == result["total_return"] - 0.02
    assert [row["value"] for row in result["benchmark_curve"]] == [2000.0, 2020.0, 2040.0]


def test_agent_analysis_projects_cost_risk_and_bounded_evidence() -> None:
    result = {
        "final_value": 1_050.0, "total_return": 0.05, "benchmark_symbol": None,
        "benchmark_return": None, "excess_return": None, "max_drawdown": 0.1,
        "trade_count": 2, "blocked_trade_count": 2, "reproducibility": "reproducible",
        "trades": [
            {"symbol": SYMBOL, "order_type": "buy", "amount": 1_001.0,
             "commission": 1.0, "tax": 0.0},
            {"symbol": SYMBOL, "order_type": "sell", "amount": 999.0,
             "commission": 1.5, "tax": 2.0},
        ],
        "blocked_trades": [
            {"symbol": SYMBOL, "reason_code": "limit_up"},
            {"symbol": SYMBOL, "reason_code": "t_plus_one"},
        ],
        "daily_returns": [
            {"trade_date": "2026-01-05", "daily_return": 0.01},
            {"trade_date": "2026-01-06", "daily_return": -0.005},
            {"trade_date": "2026-01-07", "daily_return": 0.02},
        ],
        "equity_curve": [{"trade_date": "2026-01-05", "equity": 1_010.0}],
        "logs": [{"level": "info", "code": "backtest_completed"}],
    }
    summary = build_backtest_analysis(
        result,
        execution={"initial_capital": 1_000.0, "commission_rate": 0.0003,
                   "stamp_tax_rate": 0.001, "slippage_rate": 0.001, "lot_size": 100},
        feature_diagnostics={"coverage": {"usable_ratio": 0.8}, "excluded": {"warmup_or_missing": 2}},
    )["summary"]
    assert summary["benchmark_status"] == "not_frozen"
    assert summary["commission_total"] == 2.5
    assert summary["stamp_tax_total"] == 2.0
    assert summary["explicit_fee_total"] == 4.5
    assert summary["estimated_slippage_total"] == 2.0
    assert summary["transaction_cost_total"] == 6.5
    assert summary["transaction_cost_ratio"] == 0.0065
    assert summary["annualized_volatility"] is not None
    assert summary["sharpe_ratio"] is not None
    assert summary["calmar_ratio"] is not None
    assert summary["blocked_reason_counts"] == {"limit_up": 1, "t_plus_one": 1}
    assert summary["feature_diagnostics"]["excluded"]["warmup_or_missing"] == 2

    page = build_backtest_analysis(result, section="blocked_trades", limit=1, offset=1)["page"]
    assert page == {
        "items": [{"symbol": SYMBOL, "reason_code": "t_plus_one"}],
        "total": 2, "limit": 1, "offset": 1, "has_more": False,
    }
    assert build_backtest_analysis(result, section="logs")["page"]["items"] == [
        {"level": "info", "code": "backtest_completed"},
    ]
    frozen_without_rows = build_backtest_analysis({
        **result, "benchmark_symbol": "000300.SH", "benchmark_return": None,
    })["summary"]
    assert frozen_without_rows["benchmark_status"] == "frozen_without_aligned_rows"
    with pytest.raises(ValueError, match="section must be one of"):
        build_backtest_analysis(result, section="raw_object")


def test_native_engine_blocks_limit_up_and_suspension_with_stable_codes() -> None:
    limit = normalized(
        bars=bars(day_two_open=11.0),
        signals=[{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
    )
    limit_result = run_native_backtest(limit["manifest"])
    assert limit_result["trade_count"] == 0
    assert limit_result["blocked_trades"][0]["reason_code"] == "limit_up"

    suspended_bars = bars()
    suspended_bars[1]["is_suspended"] = True
    suspended = normalized(bars=suspended_bars)
    suspended_result = run_native_backtest(suspended["manifest"])
    assert suspended_result["blocked_trades"][0]["reason_code"] == "suspended"


def test_corporate_action_entitlement_settles_on_declared_dates() -> None:
    action_bars = [
        {"symbol": SYMBOL, "trade_date": f"2026-01-0{day}", "open": 10.0,
         "high": 10.0, "low": 10.0, "close": 10.0}
        for day in range(5, 10)
    ]
    payload = normalized(
        bars=action_bars,
        corporate_actions=[{
            "symbol": SYMBOL, "end_date": "2025-12-31", "record_date": "2026-01-06",
            "ex_date": "2026-01-07", "pay_date": "2026-01-08",
            "share_listing_date": "2026-01-09", "cash_dividend_per_share": 0.2,
            "cash_dividend_gross": 0.25, "share_ratio": 1.0,
        }],
    )

    result = run_native_backtest(payload["manifest"])

    positions = {row["trade_date"]: row["positions"] for row in result["daily_positions"]}
    assert positions["2026-01-08"][0]["quantity"] == 100
    assert positions["2026-01-09"][0]["quantity"] == 200
    messages = [row["message"] for row in result["logs"]]
    assert messages.index("corporate_action_entitlement") < messages.index("cash_dividend_settled")
    assert messages.index("cash_dividend_settled") < messages.index("stock_dividend_settled")
    assert result["equity_curve"][3]["cash"] == 1020.0


def test_corporate_actions_distinguish_reporting_periods_on_same_ex_date() -> None:
    payload = normalized(corporate_actions=[
        {"symbol": SYMBOL, "end_date": "2025-06-30", "ex_date": "2026-01-07"},
        {"symbol": SYMBOL, "end_date": "2025-12-31", "ex_date": "2026-01-07"},
    ])

    assert [row["end_date"] for row in payload["manifest"]["corporate_actions"]] == [
        "2025-06-30", "2025-12-31",
    ]


def test_prev_close_adjustment_requires_frozen_corporate_action_on_ex_date() -> None:
    adjusted_bars = bars()
    adjusted_bars[1]["prev_close"] = 9.8

    with pytest.raises(ValueError, match="prev_close is inconsistent"):
        normalized(bars=adjusted_bars)

    payload = normalized(
        bars=adjusted_bars,
        corporate_actions=[{
            "symbol": SYMBOL,
            "end_date": "2025-12-31",
            "ex_date": "2026-01-06",
            "cash_dividend_per_share": 0.2,
            "share_ratio": 0,
        }],
    )

    assert payload["manifest"]["bars"][1]["prev_close"] == 9.8


def test_prev_close_adjustment_accepts_a_frozen_factor_change_only() -> None:
    adjusted_bars = bars()
    adjusted_bars[0]["adjustment_factor"] = 1.0
    adjusted_bars[1]["adjustment_factor"] = 1.02
    adjusted_bars[1]["prev_close"] = 9.8
    adjusted_bars[2]["adjustment_factor"] = 1.02
    adjusted_bars[2]["prev_close"] = 9.8

    with pytest.raises(ValueError, match="prev_close is inconsistent"):
        normalized(bars=adjusted_bars)

    adjusted_bars[2]["prev_close"] = 10.0
    payload = normalized(bars=adjusted_bars)

    assert payload["manifest"]["bars"][1]["adjustment_factor"] == 1.02
    assert payload["manifest"]["bars"][1]["prev_close"] == 9.8


@pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)
def test_job_worker_is_idempotent_bounded_and_stores_result_by_reference(tmp_path) -> None:
    research = ResearchStore()
    task = research.create_task({
        "owner_principal": "product-user", "title": "Backtest", "objective": "Native fixture",
        "trace_id": "byq-trace-backtest-test", "idempotency_key": "task-backtest-1",
    })
    prepared = prepare_strategy({
        "strategy_id": "MomentumStrategy", "name": "Momentum", "category": "momentum",
        "source_type": "python_script",
        "script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}",
    })
    version = research.create_artifact({
        "task_id": task["task_id"], "kind": "strategy_version", "content": strategy_version_content(prepared),
        "lineage": [], "trace_id": task["trace_id"], "idempotency_key": "version-backtest-1",
    })
    version = research.transition("artifact", version["artifact_id"], "validated", "version-backtest-validate")
    approval = research.create_artifact({
        "task_id": task["task_id"], "kind": "strategy_approval", "content": {
            "strategy_version_artifact_id": version["artifact_id"], "decision": "approved",
            "execution_authorized": True, "execution_outcome": "not_started",
        }, "lineage": [{"kind": "artifact", "id": version["artifact_id"]}],
        "trace_id": task["trace_id"], "idempotency_key": "approval-backtest-1",
    })
    approval = research.transition("artifact", approval["artifact_id"], "validated", "approval-backtest-validate")
    payload = request(
        task_id=task["task_id"],
        strategy_version_artifact_id=version["artifact_id"],
        approval_artifact_id=approval["artifact_id"],
    )
    job_request = normalize_backtest_request(
        payload,
        strategy_version_artifact_id=version["artifact_id"],
        approval_artifact_id=approval["artifact_id"],
    )
    jobs = BacktestJobStore()
    job = jobs.create(job_request, owner_principal="product-user")
    assert jobs.create(job_request, owner_principal="product-user")["job_id"] == job["job_id"]
    with pytest.raises(BacktestConflict):
        jobs.create({**job_request, "idempotency_key": job_request["idempotency_key"], "manifest": {**job_request["manifest"], "signals": []}}, owner_principal="product-user")

    objects = LocalObjectStore(tmp_path / "objects")
    completed = BacktestWorker(jobs, research, objects).run_once(job["job_id"])
    assert completed["status"] == "completed"
    assert completed["result_reference"]["sha256"] == completed["result_reference"]["object_id"]
    result = json.loads(objects.get(completed["result_reference"]))
    assert result["input_manifest_id"] == job["input_manifest_id"]
    artifact = research.get_artifact(completed["result_artifact_id"])
    assert artifact["kind"] == "backtest_result"
    assert artifact["content"]["result_reference"]["sha256"] == completed["result_reference"]["sha256"]
    assert jobs.claim(job["job_id"]) is None

    # A worker process that disappears leaves a recoverable queued job.
    recovery_job_request = normalized(idempotency_key="backtest-recovery-1")
    recovery_job = jobs.create(recovery_job_request, owner_principal="product-user")
    assert jobs.claim(recovery_job["job_id"])["status"] == "running"
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    jobs._execute(
        "UPDATE backtest_jobs SET updated_at = :updated_at WHERE job_id = :job_id",
        {"updated_at": stale, "job_id": recovery_job["job_id"]},
    )
    assert jobs.requeue_stale(older_than_seconds=60) == 1
    assert jobs.get(recovery_job["job_id"])["status"] == "queued"

    object_reference = objects.put("backtest-results", b"immutable", media_type="application/json")
    assert objects.get(object_reference) == b"immutable"
    objects._path(object_reference["namespace"], object_reference["object_id"]).write_bytes(b"tampered")
    with pytest.raises(ObjectIntegrityError, match="integrity"):
        objects.get(object_reference)
    objects._path(object_reference["namespace"], object_reference["object_id"]).write_bytes(b"immutable")
    with pytest.raises(BacktestConflict):
        objects.delete_if_unreferenced(object_reference, live_references=[], actor_scope="owner-a", owner_scope="owner-b")
    assert not objects.delete_if_unreferenced(object_reference, live_references=[object_reference], actor_scope="owner", owner_scope="owner")
    assert objects.delete_if_unreferenced(object_reference, live_references=[], actor_scope="owner", owner_scope="owner")
    research.close()
    jobs.close()
