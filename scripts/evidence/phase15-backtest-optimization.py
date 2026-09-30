#!/usr/bin/env python3
"""Fresh-workspace Product API proof for two Backtests and one OptimizationJob.

Run only against a scoped, disposable BYQ development stack. Input bars are
explicitly synthetic; this proves Product/Worker/Artifact flow, not market data.
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import re
import secrets
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


scope = os.environ.get("BYQ_DEV_SCOPE", "")
origin = os.environ.get("BYQ_REAL_BASE_URL", "").rstrip("/")
parsed = urlsplit(origin)
if not re.fullmatch(r"byq-dev-[0-9a-f]{10}", scope):
    raise SystemExit("isolated BYQ development scope required")
if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
    raise SystemExit("dynamic loopback Gateway origin required")
username = os.environ["BYQ_E2E_ADMIN_USERNAME"]
password = os.environ["BYQ_E2E_ADMIN_PASSWORD"]
run_key = "phase15-b-" + secrets.token_hex(5)
client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method: str, path: str, payload: dict[str, object] | None = None, *, expected: int = 200) -> dict[str, object]:
    request = Request(
        origin + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"content-type": "application/json"}, method=method,
    )
    try:
        with client.open(request, timeout=30) as response:
            value = json.load(response)
            if response.status != expected or not isinstance(value, dict):
                raise AssertionError(f"unexpected Product response for {path}: {response.status}")
            return value
    except HTTPError as error:
        raise AssertionError(f"Product request failed for {path}: HTTP {error.code}") from error


def wait_for(path: str, job_id: str, *, timeout: int = 120) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = call("GET", path)["job"]
        if not isinstance(job, dict) or job.get("job_id") != job_id:
            raise AssertionError("Product returned a different Job")
        status = str(job.get("status", ""))
        if status in {"completed", "SUCCEEDED"}:
            return job
        if status in {"failed", "cancelled", "FAILED", "CANCELLED"}:
            raise AssertionError(f"Job {job_id} ended {status}: {job.get('error_code')}")
        time.sleep(2)
    raise AssertionError(f"Job {job_id} did not finish in {timeout}s")


call("POST", "/api/auth/login", {"username": username, "password": password})
workspace_id = call("GET", "/api/auth/me")["workspace"]["workspace_id"]
task = call("POST", "/api/product/research/tasks", {
    "title": "Phase 15 synthetic parameter comparison",
    "objective": "Compare two versions of the same strategy using independent worker Jobs.",
}, expected=201)
if task.get("workspace_id") != workspace_id:
    raise AssertionError("ResearchTask escaped the authenticated Workspace")
task_id, trace = str(task["task_id"]), str(task["trace_id"])
symbol = "000001.SZ"
fingerprint = hashlib.sha256(json.dumps([symbol], separators=(",", ":")).encode()).hexdigest()
bars = [
    {"symbol": symbol, "trade_date": date, "open": close, "high": close, "low": close, "close": close}
    for date, close in (("2026-01-05", 10), ("2026-01-06", 10.2), ("2026-01-07", 10.5))
]
candidates: list[dict[str, object]] = []

for lookback in (2, 3):
    key = f"{run_key}-{lookback}"
    strategy = {
        "strategy_id": "Phase15Momentum", "name": "Phase 15 Momentum", "category": "momentum",
        "description": "Synthetic isolated development fixture",
        "parameters": {"lookback": lookback},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}",
    }
    draft = call("POST", "/api/product/strategies/validate", {
        "task_id": task_id, "strategy": strategy, "trace_id": trace,
        "idempotency_key": key + "-draft",
    }, expected=201)["artifact"]
    version = call("POST", "/api/product/strategies/versions", {
        "task_id": task_id, "draft_artifact_id": draft["artifact_id"], "trace_id": trace,
        "idempotency_key": key + "-version",
    }, expected=201)["artifact"]
    approval = call("POST", "/api/product/strategies/approvals", {
        "task_id": task_id, "strategy_version_artifact_id": version["artifact_id"],
        "decision": "approved", "trace_id": trace,
        "idempotency_key": key + "-approval",
    }, expected=201)["artifact"]
    submitted = call("POST", "/api/product/backtests", {
        "name": f"Phase 15 synthetic backtest {lookback}",
        "task_id": task_id, "strategy_version_artifact_id": version["artifact_id"],
        "approval_artifact_id": approval["artifact_id"], "trace_id": trace,
        "idempotency_key": key + "-job",
        "universe": {"universe_id": "phase15-synthetic", "version_id": "phase15-v1",
                     "membership_fingerprint": fingerprint, "symbols": [symbol]},
        "bars": bars,
        "signals": [{"symbol": symbol, "trade_date": "2026-01-05", "side": "buy", "quantity": 100 * lookback}],
        "execution": {"initial_capital": 10000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
    }, expected=202)
    backtest_id = str(submitted["job"]["job_id"])
    call("POST", f"/api/product/backtests/{backtest_id}/run", {})
    completed = wait_for(f"/api/product/backtests/{backtest_id}", backtest_id)
    artifact_id = completed.get("result_artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.startswith("artifact_"):
        raise AssertionError("completed BacktestJob has no result Artifact")
    if call("GET", f"/api/product/backtests/{backtest_id}/result").get("job_id") != backtest_id:
        raise AssertionError("Backtest result does not match its Job")
    candidates.append({"backtest_job_id": backtest_id, "parameters": {"lookback": lookback}})

submitted = call("POST", "/api/product/optimization-jobs", {
    "task_id": task_id, "idempotency_key": run_key + "-comparison",
    "objective": "total_return", "candidates": candidates,
}, expected=202)
optimization_id = str(submitted["job"]["job_id"])
completed = wait_for(f"/api/product/optimization-jobs/{optimization_id}", optimization_id)
comparison_id = completed.get("result_artifact_id")
artifacts = call("GET", "/api/product/research/artifacts").get("artifacts")
matching = [] if not isinstance(artifacts, list) else [
    item for item in artifacts if isinstance(item, dict)
    and item.get("artifact_id") == comparison_id
    and item.get("kind") == "optimization_comparison"
]
if len(matching) != 1:
    raise AssertionError("Product Artifact list has no exact comparison result")
artifact = matching[0]
content = artifact.get("content")
if (artifact.get("status") != "validated" or artifact.get("workspace_id") != workspace_id
        or not isinstance(content, dict)
        or content.get("schema_version") != "optimization-comparison.v1"
        or content.get("optimization_job_id") != optimization_id
        or content.get("reran_backtests") is not False
        or not isinstance(content.get("ranking"), list)
        or len(content["ranking"]) != 2
        or {row.get("backtest_job_id") for row in content.get("ranking", []) if isinstance(row, dict)}
        != {item["backtest_job_id"] for item in candidates}
        or content.get("candidate_count") != 2):
    raise AssertionError("comparison Artifact ranking, ownership or provenance is invalid")
print(json.dumps({"result": "PASS", "workspace_id": workspace_id, "task_id": task_id,
                  "backtest_job_ids": [item["backtest_job_id"] for item in candidates],
                  "optimization_job_id": optimization_id, "comparison_artifact_id": comparison_id}))
