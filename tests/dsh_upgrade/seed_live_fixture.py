#!/usr/bin/env python3
"""Seed one small completed synthetic backtest for the isolated U5 user."""

from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from app import main
from app.backtest import membership_fingerprint
from tests.workspace_helpers import trusted_agent_context


OWNER = os.environ.get("BYQ_U5_USERNAME", "u5-admin")
SYMBOL = "000001.SZ"


def require(response, status: int = 200) -> dict[str, object]:
    if response.status_code != status:
        raise AssertionError(f"fixture request failed with {response.status_code}: {response.text}")
    value = response.json()
    if not isinstance(value, dict):
        raise AssertionError("fixture response was not an object")
    return value


def main_seed() -> None:
    client = TestClient(main.app)
    client.headers.update(trusted_agent_context(OWNER, trace_id="u5-live-fixture"))
    strategy = {
        "strategy_id": "U5SyntheticMomentum",
        "name": "U5 synthetic momentum",
        "category": "momentum",
        "description": "Synthetic qualification fixture; not production research.",
        "parameters": {"lookback": 1},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}",
    }
    task = require(client.post("/v1/research/tasks", json={
        "owner_principal": OWNER,
        "title": "U5 TEST small backtest",
        "objective": "Synthetic DSH qualification only.",
        "trace_id": "u5-live-fixture",
        "idempotency_key": "u5-live-task",
    }), 201)
    validated = require(client.post("/v1/research/strategies/validate", json={
        "task_id": task["task_id"], "strategy": strategy,
        "trace_id": "u5-live-fixture", "idempotency_key": "u5-live-validate",
    }), 201)
    version = require(client.post("/v1/research/strategies/versions", json={
        "task_id": task["task_id"],
        "draft_artifact_id": validated["artifact"]["artifact_id"],
        "trace_id": "u5-live-fixture", "idempotency_key": "u5-live-version",
    }), 201)
    approval = require(client.post("/v1/research/strategies/approvals", json={
        "task_id": task["task_id"],
        "strategy_version_artifact_id": version["artifact"]["artifact_id"],
        "reviewer_principal": OWNER, "decision": "approved",
        "rationale": "Approve isolated synthetic fixture.",
        "trace_id": "u5-live-fixture", "idempotency_key": "u5-live-approval",
    }), 201)
    bars = [
        {"symbol": SYMBOL, "trade_date": "2026-01-05", "open": 10, "high": 10.2, "low": 9.9, "close": 10.1},
        {"symbol": SYMBOL, "trade_date": "2026-01-06", "open": 10.1, "high": 10.7, "low": 10, "close": 10.6},
        {"symbol": SYMBOL, "trade_date": "2026-01-07", "open": 10.6, "high": 10.9, "low": 10.4, "close": 10.8},
    ]
    submitted = require(client.post("/v1/research/backtests", json={
        "name": "U5 TEST completed small backtest",
        "task_id": task["task_id"],
        "strategy_version_artifact_id": version["artifact"]["artifact_id"],
        "approval_artifact_id": approval["artifact"]["artifact_id"],
        "trace_id": "u5-live-fixture", "idempotency_key": "u5-live-backtest",
        "universe": {
            "universe_id": "u5-test", "version_id": "u5-test-v1",
            "membership_fingerprint": membership_fingerprint([SYMBOL]), "symbols": [SYMBOL],
        },
        "bars": bars,
        "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
        "execution": {"initial_capital": 100000, "commission_rate": 0.0003,
                      "stamp_tax_rate": 0.001, "lot_size": 100},
    }), 202)["job"]
    completed = require(client.post(f"/v1/research/backtests/{submitted['job_id']}/run"))["job"]
    if completed.get("status") != "completed":
        raise AssertionError(f"synthetic backtest did not complete: {completed.get('status')}")
    print(json.dumps({
        "schema_version": "dsh-u5-live-fixture.v1",
        "owner": OWNER,
        "backtest_job_id": completed["job_id"],
        "status": completed["status"],
        "synthetic": True,
    }, sort_keys=True))


if __name__ == "__main__":
    main_seed()
