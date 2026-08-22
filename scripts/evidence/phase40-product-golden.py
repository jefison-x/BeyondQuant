#!/usr/bin/env python3
"""Run the Phase 40 no-mock Product API golden path against a fresh stack."""

from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request
import uuid


BASE_URL = os.environ.get("BYQ_GOLDEN_BASE_URL", "http://127.0.0.1:8710/api/product")


class ProductClient:
    def __init__(self, username: str, password: str) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        body = self.request("POST", "/auth/login", {"username": username, "password": password})
        if body.get("user", {}).get("username") != username:
            raise AssertionError("login returned the wrong user")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        expected_status: int | None = None,
    ) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {} if data is None else {"content-type": "application/json"}
        request = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=20) as response:
                status = response.status
                body = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            status = error.code
            body = json.loads(error.read().decode("utf-8") or "{}")
        if expected_status is not None and status != expected_status:
            raise AssertionError(f"{method} {path}: expected {expected_status}, got {status}: {body}")
        if expected_status is None and not 200 <= status < 300:
            raise AssertionError(f"{method} {path}: unexpected {status}: {body}")
        return body


def identity(prefix: str) -> str:
    return f"p40-{prefix}-{uuid.uuid4().hex}"


def main() -> None:
    owner = ProductClient(
        os.environ.get("BYQ_GOLDEN_OWNER_USERNAME", "p40admin"),
        os.environ.get("BYQ_GOLDEN_OWNER_PASSWORD", "P40AdminPass123"),
    )
    other = ProductClient(
        os.environ.get("BYQ_GOLDEN_OTHER_USERNAME", "p40user"),
        os.environ.get("BYQ_GOLDEN_OTHER_PASSWORD", "P40UserPass123"),
    )

    task = owner.request(
        "POST", "/research/tasks",
        {"title": "Phase 40 golden strategy", "objective": "Run the isolated signal-to-backtest path."},
    )
    task_id = str(task["task_id"])
    pool = owner.request(
        "POST", "/paper/pools",
        {"name": "Phase 40 golden pool", "pool_type": "custom", "symbols": ["000001.SZ"]},
    )["pool"]
    pool_id = str(pool["pool_id"])
    snapshot_id = str(pool["snapshot"]["snapshot_id"])

    source = (
        "import pandas as pd\n"
        "class CustomStrategy:\n"
        "    def generate_signals(self, data, parameters=None):\n"
        "        result = {}\n"
        "        for symbol in data.index.get_level_values('symbol').unique():\n"
        "            closes = data.xs(symbol, level='symbol')['close']\n"
        "            result[str(symbol)] = (closes > closes.shift(1)).fillna(False).astype(int)\n"
        "        return result\n"
    )
    strategy = {
        "strategy_id": "Phase40GoldenMomentum",
        "name": "Phase 40 Golden Momentum",
        "category": "momentum",
        "description": "Deterministic isolated Pandas signal producer evidence.",
        "parameters": {"lookback": 1},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": source,
    }
    common = {"task_id": task_id, "strategy": strategy}
    owner.request(
        "POST", "/strategies/drafts",
        {**common, "trace_id": identity("draft"), "idempotency_key": identity("draft")},
    )
    validated = owner.request(
        "POST", "/strategies/validate",
        {**common, "trace_id": identity("validate"), "idempotency_key": identity("validate")},
    )
    draft_id = str(validated["artifact"]["artifact_id"])
    version = owner.request(
        "POST", "/strategies/versions",
        {"task_id": task_id, "draft_artifact_id": draft_id,
         "trace_id": identity("version"), "idempotency_key": identity("version")},
    )
    version_id = str(version["artifact"]["artifact_id"])
    approval = owner.request(
        "POST", "/strategies/approvals",
        {"task_id": task_id, "strategy_version_artifact_id": version_id,
         "decision": "approved", "rationale": "Phase 40 golden-path owner approval.",
         "trace_id": identity("approval"), "idempotency_key": identity("approval")},
    )
    approval_id = str(approval["artifact"]["artifact_id"])

    produced = owner.request(
        "POST", "/signal-producer/jobs",
        {"task_id": task_id, "strategy_version_artifact_id": version_id,
         "stock_pool_snapshot_id": snapshot_id, "start_date": "2026-01-05",
         "end_date": "2026-01-07", "parameters": {"lookback": 1},
         "execution": {"initial_capital": 100000, "commission_rate": 0.0003,
                       "stamp_tax_rate": 0.001, "slippage_rate": 0, "lot_size": 100,
                       "max_positions": 10, "a_share_rules": True,
                       "max_runtime_seconds": 10, "max_attempts": 2},
         "order_quantity": 100, "trace_id": identity("signal"),
         "idempotency_key": identity("signal")},
    )
    signal_job_id = str(produced["job"]["job_id"])
    signal_job = produced["job"]
    for _ in range(30):
        if signal_job.get("status") in {"completed", "failed"}:
            break
        time.sleep(1)
        signal_job = owner.request("GET", f"/signal-producer/jobs/{signal_job_id}")["job"]
    if signal_job.get("status") != "completed":
        raise AssertionError(f"signal job did not complete: {signal_job}")
    signal_artifact_id = str(signal_job["result_artifact_id"])

    backtest = owner.request(
        "POST", "/backtests",
        {"task_id": task_id, "strategy_version_artifact_id": version_id,
         "approval_artifact_id": approval_id,
         "signal_snapshot_artifact_id": signal_artifact_id,
         "trace_id": identity("backtest"), "idempotency_key": identity("backtest")},
    )
    backtest_job_id = str(backtest["job"]["job_id"])
    completed = owner.request("POST", f"/backtests/{backtest_job_id}/run")["job"]
    if completed.get("status") != "completed":
        raise AssertionError(f"backtest did not complete: {completed}")
    result = owner.request("GET", f"/backtests/{backtest_job_id}/result")["result"]

    other.request("GET", f"/research/tasks/{task_id}", expected_status=404)
    other.request("GET", f"/paper/pools/{pool_id}", expected_status=404)
    other.request("GET", f"/signal-producer/jobs/{signal_job_id}", expected_status=404)
    other_strategies = other.request("GET", "/strategies")
    other_backtests = other.request("GET", "/backtests")
    if other_strategies.get("total") != 0 or other_backtests.get("backtests") != []:
        raise AssertionError("secondary user observed owner-scoped research data")

    print(json.dumps({
        "schema_version": "phase-40-product-golden-v1", "status": "passed",
        "product_api": BASE_URL,
        "owner_flow": {"task_id": task_id, "pool_id": pool_id,
                       "strategy_version_artifact_id": version_id,
                       "approval_artifact_id": approval_id, "signal_job_id": signal_job_id,
                       "signal_snapshot_artifact_id": signal_artifact_id,
                       "backtest_job_id": backtest_job_id,
                       "backtest_status": completed["status"],
                       "trade_count": result.get("trade_count")},
        "secondary_user": {"task_get": 404, "pool_get": 404, "signal_job_get": 404,
                           "strategy_total": 0, "backtest_total": 0},
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
