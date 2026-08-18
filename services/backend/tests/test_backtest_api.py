from __future__ import annotations

import os

import os

import pytest

from fastapi.testclient import TestClient

from app import main
from app.backtest import (
    BacktestJobStore,
    LocalObjectStore,
    ObjectIntegrityError,
    membership_fingerprint,
)
from app.research import ResearchStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


SYMBOL = "000001.SZ"


def _strategy() -> dict[str, object]:
    return {
        "strategy_id": "MomentumStrategy",
        "name": "Momentum",
        "category": "momentum",
        "description": "A bounded strategy fixture.",
        "parameters": {"lookback": 20},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}",
    }


def test_backtest_submit_worker_and_get_flow(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", LocalObjectStore(tmp_path / "objects"))
    client = TestClient(main.app)

    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user", "title": "Backtest API", "objective": "Run native fixture",
            "trace_id": "byq-trace-backtest-api", "idempotency_key": "task-backtest-api",
        },
    ).json()
    draft = client.post(
        "/v1/research/strategies/validate",
        json={"task_id": task["task_id"], "strategy": _strategy(), "trace_id": task["trace_id"], "idempotency_key": "draft-backtest-api"},
    ).json()
    version = client.post(
        "/v1/research/strategies/versions",
        json={"task_id": task["task_id"], "draft_artifact_id": draft["artifact"]["artifact_id"], "trace_id": task["trace_id"], "idempotency_key": "version-backtest-api"},
    ).json()
    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner", "decision": "approved", "trace_id": task["trace_id"],
            "idempotency_key": "approval-backtest-api",
        },
    ).json()
    universe = {
        "universe_id": "fixture", "version_id": "fixture-v1",
        "membership_fingerprint": membership_fingerprint([SYMBOL]), "symbols": [SYMBOL],
    }
    bars = [
        {"symbol": SYMBOL, "trade_date": "2026-01-05", "open": 10, "high": 10, "low": 10, "close": 10},
        {"symbol": SYMBOL, "trade_date": "2026-01-06", "open": 10, "high": 10, "low": 10, "close": 10},
    ]
    submit = client.post(
        "/v1/research/backtests",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "approval_artifact_id": approval["artifact"]["artifact_id"], "trace_id": task["trace_id"],
            "idempotency_key": "backtest-api-1", "universe": universe, "bars": bars,
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
            "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
        },
    )
    assert submit.status_code == 202, submit.text
    job = submit.json()["job"]
    assert job["status"] == "queued"
    assert client.post(f"/v1/research/backtests/{job['job_id']}/run").json()["job"]["status"] == "completed"
    fetched = client.get(f"/v1/research/backtests/{job['job_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["job"]["result_artifact_id"].startswith("artifact_")
    result = client.get(
        f"/v1/research/backtests/{job['job_id']}/result",
        headers={
            "x-byq-owner-principal": "product-user",
            "x-byq-actor-principal": "product-user",
            "x-byq-trace-id": "byq-trace-backtest-api",
            "x-byq-session-id": "byq-session-backtest-api",
            "x-byq-dsh-run-id": "byq-run-backtest-api",
        },
    )
    assert result.status_code == 200
    result_body = result.json()
    assert result_body["job_id"] == job["job_id"]
    assert result_body["result"]["total_return"] == 0.0
    assert result_body["result"]["trade_count"] == 1
    assert result_body["result"]["equity_curve"][-1]["trade_date"] == "2026-01-06"
    assert result_body["result"]["daily_positions"][-1]["trade_date"] == "2026-01-06"
    assert result_body["result"]["daily_returns"][-1]["trade_date"] == "2026-01-06"
    assert result_body["result"]["logs"]
    assert result_body["result"]["strategy_version_artifact_id"] == version["artifact"]["artifact_id"]
    assert result_body["result"]["approval_artifact_id"] == approval["artifact"]["artifact_id"]

    denied = client.get(
        f"/v1/research/backtests/{job['job_id']}/result",
        headers={
            "x-byq-owner-principal": "other-user",
            "x-byq-actor-principal": "other-user",
            "x-byq-trace-id": "byq-trace-other",
            "x-byq-session-id": "byq-session-other",
            "x-byq-dsh-run-id": "byq-run-other",
        },
    )
    assert denied.status_code == 404
    listed = client.get(
        "/v1/research/backtests",
        headers={
            "x-byq-owner-principal": "product-user",
            "x-byq-actor-principal": "product-user",
            "x-byq-trace-id": "byq-trace-backtest-api",
            "x-byq-session-id": "byq-session-backtest-api",
            "x-byq-dsh-run-id": "byq-run-backtest-api",
        },
    )
    assert listed.status_code == 200
    assert listed.json()["backtests"][0]["job_id"] == job["job_id"]
    retry = client.post(
        "/v1/research/backtests",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "approval_artifact_id": approval["artifact"]["artifact_id"], "trace_id": task["trace_id"],
            "idempotency_key": "backtest-api-1", "universe": universe, "bars": bars,
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
            "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
        },
    )
    assert retry.status_code == 202
    assert retry.json()["job"]["job_id"] == job["job_id"]
    denied_delete = client.delete(
        f"/v1/research/backtests/{job['job_id']}",
        headers={
            "x-byq-owner-principal": "other-user",
            "x-byq-actor-principal": "other-user",
            "x-byq-trace-id": "byq-trace-other",
            "x-byq-session-id": "byq-session-other",
            "x-byq-dsh-run-id": "byq-run-other",
        },
    )
    assert denied_delete.status_code == 409
    deleted = client.delete(
        f"/v1/research/backtests/{job['job_id']}",
        headers={
            "x-byq-owner-principal": "product-user",
            "x-byq-actor-principal": "product-user",
            "x-byq-trace-id": "byq-trace-backtest-api",
            "x-byq-session-id": "byq-session-backtest-api",
            "x-byq-dsh-run-id": "byq-run-backtest-api",
        },
    )
    assert deleted.status_code == 200
    assert client.get(f"/v1/research/backtests/{job['job_id']}").status_code == 404

    store.close()
    jobs.close()


def _owner_headers(principal: str) -> dict[str, str]:
    return {
        "x-byq-owner-principal": principal,
        "x-byq-actor-principal": principal,
        "x-byq-trace-id": f"byq-trace-{principal}",
        "x-byq-session-id": f"byq-session-{principal}",
        "x-byq-dsh-run-id": f"byq-run-{principal}",
    }


def _create_completed_backtest(client: TestClient, *, key: str) -> dict[str, object]:
    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user", "title": f"Backtest GC {key}",
            "objective": "Run native fixture", "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"task-{key}",
        },
    ).json()
    draft = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"], "strategy": _strategy(), "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"draft-{key}",
        },
    ).json()
    version = client.post(
        "/v1/research/strategies/versions",
        json={
            "task_id": task["task_id"], "draft_artifact_id": draft["artifact"]["artifact_id"],
            "trace_id": f"byq-trace-{key}", "idempotency_key": f"version-{key}",
        },
    ).json()
    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner", "decision": "approved", "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"approval-{key}",
        },
    ).json()
    universe = {
        "universe_id": "fixture", "version_id": "fixture-v1",
        "membership_fingerprint": membership_fingerprint([SYMBOL]), "symbols": [SYMBOL],
    }
    bars = [
        {"symbol": SYMBOL, "trade_date": "2026-01-05", "open": 10, "high": 10, "low": 10, "close": 10},
        {"symbol": SYMBOL, "trade_date": "2026-01-06", "open": 10, "high": 10, "low": 10, "close": 10},
    ]
    submit = client.post(
        "/v1/research/backtests",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "approval_artifact_id": approval["artifact"]["artifact_id"], "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"backtest-{key}", "universe": universe, "bars": bars,
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
            "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
        },
    )
    assert submit.status_code == 202, submit.text
    job = submit.json()["job"]
    assert client.post(f"/v1/research/backtests/{job['job_id']}/run").json()["job"]["status"] == "completed"
    return client.get(f"/v1/research/backtests/{job['job_id']}").json()["job"]


def test_backtest_delete_garbage_collects_orphan_result_object(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)

    job = _create_completed_backtest(client, key="gc-orphan")
    reference = job["result_reference"]
    assert objects.exists(reference)
    deleted = client.delete(f"/v1/research/backtests/{job['job_id']}", headers=_owner_headers("product-user"))
    assert deleted.status_code == 200
    assert not objects.exists(reference), "orphan result object must be garbage collected"
    store.close()
    jobs.close()


def test_backtest_delete_keeps_shared_result_object(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)

    job_a = _create_completed_backtest(client, key="gc-shared-a")
    job_b = _create_completed_backtest(client, key="gc-shared-b")
    reference = job_a["result_reference"]
    # Simulate content-addressed sharing: job B references the same result object.
    jobs._execute(
        "UPDATE backtest_jobs SET result_reference_json = :reference WHERE job_id = :job_id",
        {"reference": reference, "job_id": job_b["job_id"]},
    )
    assert objects.exists(reference)
    deleted_a = client.delete(f"/v1/research/backtests/{job_a['job_id']}", headers=_owner_headers("product-user"))
    assert deleted_a.status_code == 200
    assert objects.exists(reference), "shared result object must survive the first deletion"
    deleted_b = client.delete(f"/v1/research/backtests/{job_b['job_id']}", headers=_owner_headers("product-user"))
    assert deleted_b.status_code == 200
    assert not objects.exists(reference), "orphaned shared result object must be garbage collected"
    store.close()
    jobs.close()


def test_backtest_delete_survives_result_gc_failure(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)

    job = _create_completed_backtest(client, key="gc-failure")

    def _boom(*args: object, **kwargs: object) -> None:
        raise ObjectIntegrityError("simulated GC failure")

    monkeypatch.setattr(objects, "delete_if_unreferenced", _boom)
    deleted = client.delete(f"/v1/research/backtests/{job['job_id']}", headers=_owner_headers("product-user"))
    assert deleted.status_code == 200, "best-effort GC must never fail the DELETE request"
    assert client.get(f"/v1/research/backtests/{job['job_id']}").status_code == 404
    store.close()
    jobs.close()
