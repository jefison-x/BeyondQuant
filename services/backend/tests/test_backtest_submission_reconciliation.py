"""Backtest receipts use original durable identity, never replay or list inference."""
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.backtest import BacktestJobStore, BacktestNotFound, BacktestStorageError
from test_backtest_api import _create_strategy_chain, _fresh_harness, _snapshot_input
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")
PATH = "/v1/research/backtests/reconcile"


def test_original_receipt_late_commit_reconnect_and_process_read(monkeypatch, tmp_path):
    store, jobs, _, client = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(client, key="receipt")
    task_id = chain["task"]["task_id"]
    params = {"task_id": task_id, "idempotency_key": "original/key &中文"}
    unknown = client.get(PATH, params=params)
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["status"] == "outcome_unknown" and "job" not in unknown.json()
    created = client.post("/v1/research/backtests", json={**_snapshot_input(), **params,
        "strategy_version_artifact_id": chain["version"]["artifact"]["artifact_id"],
        "approval_artifact_id": chain["approval"]["artifact"]["artifact_id"], "trace_id": "byq-trace-receipt"})
    assert created.status_code == 202, created.text
    job_id = created.json()["job"]["job_id"]
    expected = client.get(f"/v1/research/backtests/{job_id}/summary").json()["job"]
    other = _create_strategy_chain(client, key="other-receipt")
    for selector in ({**params, "task_id": other["task"]["task_id"]}, {**params, "idempotency_key": "other"}):
        assert client.get(PATH, params=selector).json()["status"] == "outcome_unknown"
    jobs.close()
    replacement = BacktestJobStore()
    monkeypatch.setattr(main, "backtest_store", replacement)
    def forbidden(*args, **kwargs):
        pytest.fail("receipt read must not load full input, create, list or execute")
    for name in ("create", "get", "list_backtests", "list_backtest_summaries", "get_input_manifest"):
        monkeypatch.setattr(replacement, name, forbidden)
    monkeypatch.setattr(main, "_validated_backtest_request", forbidden)
    monkeypatch.setattr(main, "BacktestWorker", forbidden)
    for _ in range(2):
        response = client.get(PATH, params=params)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "confirmed"
        assert response.json()["job"] == expected
        assert expected["status"] == "queued"
        assert "input_manifest" not in response.json()["job"]
        assert "request_hash" not in response.text
    # A fresh interpreter reads the same committed row; no in-memory receipt cache.
    args = {**params, "trusted_owner": "product-user", "trusted_workspace": client.headers["x-byq-workspace-id"]}
    program = "import json,sys; from app.backtest import BacktestJobStore, BacktestNotFound, BacktestStorageError; s=BacktestJobStore(); print(json.dumps(s.reconcile_submission(**json.loads(sys.argv[1])))); s.close()"
    child = subprocess.run([sys.executable, "-c", program, json.dumps(args)], check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(child.stdout)["job"] == expected
    with monkeypatch.context() as race:
        def deleted(*args, **kwargs):
            raise BacktestNotFound("synthetic concurrent deletion")
        race.setattr(replacement, "get_backtest_summary", deleted)
        lost = client.get(PATH, params=params)
        assert lost.status_code == 200 and lost.json()["status"] == "outcome_unknown"
        assert "job" not in lost.json()
    with monkeypatch.context() as outage:
        def unavailable(*args, **kwargs):
            raise BacktestStorageError("synthetic private storage detail")
        outage.setattr(replacement, "_fetch_one", unavailable)
        failed = client.get(PATH, params=params)
        assert failed.status_code == 503
        assert "private storage" not in failed.text
        assert "confirmed" not in failed.text
    foreign = trusted_agent_context("other-user")
    assert client.get(PATH, params=params, headers=foreign).status_code == 404
    mixed = {**dict(client.headers), "x-byq-workspace-id": foreign["x-byq-workspace-id"]}
    assert client.get(PATH, params=params, headers=mixed).status_code == 401
    with TestClient(main.app) as anonymous:
        assert anonymous.get(PATH, params=params).status_code == 401
    user = next(u for u in main.user_store.list_users(actor_role="admin")["users"] if u["username"] == "product-user")
    main.user_store.disable_user(user["user_id"], actor_role="admin")
    assert client.get(PATH, params=params).status_code == 401
    replacement.close()
    store.close()


@pytest.mark.parametrize("selector", [{}, {"task_id": "bad", "idempotency_key": "key"},
    {"task_id": "task_" + "a" * 32}, {"idempotency_key": "key"}])
def test_invalid_selector(monkeypatch, tmp_path, selector):
    store, jobs, _, client = _fresh_harness(monkeypatch, tmp_path)
    assert client.get(PATH, params=selector).status_code == 422
    jobs.close()
    store.close()


@pytest.mark.parametrize("key", ["", " ", "x" * 129])
def test_invalid_key(monkeypatch, tmp_path, key):
    store, jobs, _, client = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(client, key="bad-key")
    assert client.get(PATH, params={"task_id": chain["task"]["task_id"], "idempotency_key": key}).status_code == 422
    jobs.close()
    store.close()
