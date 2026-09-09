"""Original-key recovery for the derived signal-backed backtest task."""
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.signal_producer import SignalJobStore, SignalProducerPersistenceError
from test_backtest_api import _create_strategy_chain, _fresh_harness
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")
PATH = "/v1/research/backtest-tasks/reconcile"


def setup_creation(monkeypatch, tmp_path):
    research, backtests, _, client = _fresh_harness(monkeypatch, tmp_path)
    jobs = SignalJobStore()
    monkeypatch.setattr(main, "signal_job_store", jobs)
    chain = _create_strategy_chain(client, key="task-receipt")
    pool = client.post("/v1/paper/pools", json={"name": "Receipt pool", "pool_type": "custom", "symbols": ["000001.SZ"]}).json()["pool"]
    main.security_master_store._execute("""INSERT INTO security_master_snapshots
        (snapshot_id,provider,endpoint,dataset_id,request_fingerprint,statuses_json,row_count,retrieved_at,requested_by)
        VALUES ('sms_receipt','tushare','stock_basic','fixture','fixture','["L"]',1,now(),'test')""")
    main.security_master_store._execute("""INSERT INTO security_master_snapshot_members
        (snapshot_id,symbol,local_symbol,name,exchange,list_status,list_date,asset_type,content_sha256)
        VALUES ('sms_receipt','000001.SZ','000001','Fixture','SZSE','L','19910101','stock','fixture')""")
    payload = {"task_id": chain["task"]["task_id"], "strategy_version_artifact_id": chain["version"]["artifact"]["artifact_id"],
        "stock_pool_snapshot_id": pool["snapshot"]["snapshot_id"], "start_date": "2026-01-05", "end_date": "2026-01-06",
        "idempotency_key": "original/key &中文"}
    return research, backtests, jobs, client, payload


@pytest.mark.parametrize("creation_path", ["/v1/research/backtest-tasks", "/v1/research/signal-producer/jobs"])
def test_late_commit_and_fresh_process_receipt(monkeypatch, tmp_path, creation_path):
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    params = {k: payload[k] for k in ("task_id", "idempotency_key")}
    unknown = client.get(PATH, params=params)
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["status"] == "outcome_unknown" and "receipt" not in unknown.json()
    body = payload if creation_path.endswith("backtest-tasks") else {**payload, "trace_id": client.headers["x-byq-trace-id"]}
    created = client.post(creation_path, json=body)
    assert created.status_code == 202, created.text
    task = (created.json()["task"] if creation_path.endswith("backtest-tasks")
            else main._backtest_task_view(created.json()["job"], owner_principal="product-user"))
    original_id = task["backtest_task_id"]
    signal_id = task["references"]["signal_producer_job_id"]
    assert task["phase"] == "waiting_for_data"
    other = _create_strategy_chain(client, key="other-task-receipt")
    for selector in ({**params, "task_id": other["task"]["task_id"]}, {**params, "idempotency_key": "different"}):
        assert client.get(PATH, params=selector).json()["status"] == "outcome_unknown"
    jobs.close()
    replacement = SignalJobStore()
    monkeypatch.setattr(main, "signal_job_store", replacement)
    def forbidden(*args, **kwargs):
        pytest.fail("receipt lookup must not prepare, repair, list, create or project the full task")
    for name in ("create", "create_waiting", "get", "list_jobs", "list_waiting", "claim_next"):
        monkeypatch.setattr(replacement, name, forbidden)
    for name in ("_prepare_signal_producer", "_backtest_task_view", "_approved_strategy_artifact"):
        monkeypatch.setattr(main, name, forbidden)
    monkeypatch.setattr(main.market_automation_store, "request_data_repair", forbidden)
    for _ in range(2):
        result = client.get(PATH, params=params)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "confirmed"
        assert result.json()["receipt"] == {"backtest_task_id": original_id,
            "signal_producer_job_id": signal_id, "signal_status": "waiting_for_data"}
        assert "preparation" not in result.text and "request_hash" not in result.text
    args = {**params, "trusted_owner": "product-user", "trusted_workspace": client.headers["x-byq-workspace-id"]}
    program = "import json,sys; from app.signal_producer import SignalJobStore; s=SignalJobStore(); print(json.dumps(s.find_submission(**json.loads(sys.argv[1])))); s.close()"
    fresh = subprocess.run([sys.executable, "-c", program, json.dumps(args)], check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(fresh.stdout)["job_id"] == signal_id
    with monkeypatch.context() as outage:
        def unavailable(*args, **kwargs):
            raise SignalProducerPersistenceError("private synthetic detail")
        outage.setattr(replacement, "_fetch_one", unavailable)
        failed = client.get(PATH, params=params)
        assert failed.status_code == 503 and "private synthetic" not in failed.text
    foreign = trusted_agent_context("receipt-other")
    assert client.get(PATH, params=params, headers=foreign).status_code == 404
    assert client.get(PATH, params=params, headers={**dict(client.headers), "x-byq-workspace-id": foreign["x-byq-workspace-id"]}).status_code == 401
    with TestClient(main.app) as anonymous:
        assert anonymous.get(PATH, params=params).status_code == 401
    user = next(u for u in main.user_store.list_users(actor_role="admin")["users"] if u["username"] == "product-user")
    main.user_store.disable_user(user["user_id"], actor_role="admin")
    assert client.get(PATH, params=params).status_code == 401
    replacement.close()
    backtests.close()
    research.close()


@pytest.mark.parametrize("selector", [{}, {"task_id": "bad", "idempotency_key": "key"},
    {"idempotency_key": "key"}, {"task_id": "task_" + "a" * 32}])
def test_invalid_selector(monkeypatch, tmp_path, selector):
    research, backtests, _, client = _fresh_harness(monkeypatch, tmp_path)
    assert client.get(PATH, params=selector).status_code == 422
    backtests.close()
    research.close()


@pytest.mark.parametrize("key", ["", " ", "x" * 129])
def test_invalid_key(monkeypatch, tmp_path, key):
    research, backtests, _, client = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(client, key="invalid-receipt")
    assert client.get(PATH, params={"task_id": chain["task"]["task_id"], "idempotency_key": key}).status_code == 422
    backtests.close()
    research.close()
