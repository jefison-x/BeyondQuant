"""Real API/DB submission invariants: no preparation replay or orphan reference."""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from app import main
from app.signal_producer import SignalJobStore, promote_waiting_signal_jobs
from test_backtest_task_reconciliation import setup_creation

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")
PATHS = ["/v1/research/backtest-tasks", "/v1/research/signal-producer/jobs"]


def body_for(path, payload):
    return payload if path.endswith("backtest-tasks") else {**payload, "trace_id": "original-trace"}


def identity(response):
    data = response.json()
    return data["job"]["job_id"] if "job" in data else data["task"]["references"]["signal_producer_job_id"]


@pytest.mark.parametrize("path", PATHS)
def test_persist_before_assessment_and_replay(monkeypatch, tmp_path, path):
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("submission must not assess/repair or replay preparation")
    monkeypatch.setattr(main.market_readiness_store, "assess", forbidden)
    monkeypatch.setattr(main.market_automation_store, "request_data_repair", forbidden)
    body = body_for(path, payload)
    response = client.post(path, json=body)
    assert response.status_code == 202, response.text
    job_id = identity(response)
    assert jobs._fetch_one("SELECT status FROM signal_producer_jobs WHERE job_id=:id", {"id": job_id})["status"] == "waiting_for_data"
    assert main.paper_store._fetch_one("SELECT reference_id FROM stock_pool_domain_references WHERE domain='signal_producer' AND reference_id=:id", {"id": job_id})
    jobs.close()
    replacement = SignalJobStore()
    monkeypatch.setattr(main, "signal_job_store", replacement)
    monkeypatch.setattr(main, "_prepare_signal_producer", forbidden)
    if "trace_id" in body:
        body["trace_id"] = "new-delivery-trace"
    repeated = client.post(path, json=body, headers={"x-byq-trace-id": "new-delivery-trace"})
    assert repeated.status_code == 202, repeated.text
    assert identity(repeated) == job_id
    conflict = client.post(path, json={**body, "order_quantity": 200})
    assert conflict.status_code == 409, conflict.text
    replacement.close()
    backtests.close()
    research.close()


@pytest.mark.parametrize("path", PATHS)
def test_reference_error_rolls_back_job(monkeypatch, tmp_path, path):
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    original = main.paper_store.record_pool_reference_in_transaction
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError("injected reference failure")
    monkeypatch.setattr(main.paper_store, "record_pool_reference_in_transaction", fail)
    response = client.post(path, json=body_for(path, payload))
    assert response.status_code == 422, response.text
    assert jobs._fetch_one("SELECT COUNT(*) AS n FROM signal_producer_jobs")["n"] == 0
    assert main.paper_store._fetch_one("SELECT COUNT(*) AS n FROM stock_pool_domain_references WHERE domain='signal_producer'")["n"] == 0
    assert main.market_automation_store._fetch_one("SELECT COUNT(*) AS n FROM market_data_repair_requests")["n"] == 0
    jobs.close()
    backtests.close()
    research.close()


def test_duplicate_concurrent_delivery_prepares_once(monkeypatch, tmp_path):
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    calls = []
    original = main._prepare_signal_producer
    def observed(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(main, "_prepare_signal_producer", observed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: client.post(PATHS[0], json=payload), range(2)))
    assert [r.status_code for r in results] == [202, 202]
    assert identity(results[0]) == identity(results[1])
    assert len(calls) == 1
    jobs.close()
    backtests.close()
    research.close()


def test_independent_connections_claim_once(monkeypatch, tmp_path):
    from threading import Barrier
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    stores = [SignalJobStore(), SignalJobStore(), SignalJobStore()]
    barrier = Barrier(len(stores))
    calls = []
    def prepare():
        calls.append(True)
        return main._prepare_signal_producer(payload, owner_principal="product-user", request_repair=False, assess_readiness=False)
    def submit(store):
        barrier.wait(timeout=10)
        return store.submit_waiting(
            command={k: v for k, v in payload.items() if k != "idempotency_key"}, purpose="backtest_task",
            trusted_owner="product-user", trusted_workspace=client.headers["x-byq-workspace-id"],
            trace_id="first-trace", idempotency_key=payload["idempotency_key"], prepare=prepare,
            record_reference=main.paper_store.record_pool_reference_in_transaction,
        )
    with ThreadPoolExecutor(max_workers=len(stores)) as executor:
        results = list(executor.map(submit, stores))
    assert len({r["job_id"] for r in results}) == 1
    assert len(calls) == 1
    assert all("submission_hash" not in r for r in results)
    assert jobs._fetch_one("SELECT COUNT(*) AS n FROM signal_producer_jobs")["n"] == 1
    for store in stores:
        store.close()
    jobs.close()
    backtests.close()
    research.close()


def test_worker_repairs_after_commit_without_rearming_terminal(monkeypatch, tmp_path):
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    created = client.post(PATHS[0], json=payload)
    assert created.status_code == 202, created.text
    automation = main.market_automation_store
    assert automation._fetch_one("SELECT COUNT(*) AS n FROM market_data_repair_requests")["n"] == 0
    assert promote_waiting_signal_jobs(jobs, main.market_readiness_store, automation) == 0
    first = automation._fetch_one("SELECT * FROM market_data_repair_requests")
    assert first and first["status"] == "queued"
    assert promote_waiting_signal_jobs(jobs, main.market_readiness_store, automation) == 0
    claimed = automation.claim_data_repair()
    assert claimed["request_id"] == first["request_id"]
    automation.complete_data_repair(first["request_id"], error="synthetic repair failure")
    assert promote_waiting_signal_jobs(jobs, main.market_readiness_store, automation) == 0
    preserved = automation._fetch_one("SELECT * FROM market_data_repair_requests")
    assert preserved["status"] == "failed" and preserved["request_id"] == first["request_id"]
    assert automation._fetch_one("SELECT COUNT(*) AS n FROM market_data_repair_requests")["n"] == 1
    user = next(u for u in main.user_store.list_users(actor_role="admin")["users"] if u["username"] == "product-user")
    main.user_store.disable_user(user["user_id"], actor_role="admin")
    def forbidden(*args, **kwargs):
        pytest.fail("disabled owner's waiting job must not assess or repair")
    monkeypatch.setattr(main.market_readiness_store, "assess", forbidden)
    monkeypatch.setattr(automation, "request_data_repair", forbidden)
    assert promote_waiting_signal_jobs(jobs, main.market_readiness_store, automation) == 0
    jobs.close()
    backtests.close()
    research.close()


def test_legacy_identity_is_not_guessed(monkeypatch, tmp_path):
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    created = client.post(PATHS[0], json=payload)
    assert created.status_code == 202
    jobs._execute("UPDATE signal_producer_jobs SET submission_hash=NULL WHERE job_id=:id", {"id": identity(created)})
    def forbidden(*args, **kwargs):
        pytest.fail("legacy receipt must not trigger preparation")
    monkeypatch.setattr(main, "_prepare_signal_producer", forbidden)
    assert client.post(PATHS[0], json=payload).status_code == 409
    receipt = client.get("/v1/research/backtest-tasks/reconcile", params={k: payload[k] for k in ("task_id", "idempotency_key")})
    assert receipt.status_code == 200 and receipt.json()["status"] == "confirmed"
    jobs.close()
    backtests.close()
    research.close()


def test_creation_purpose_cannot_bypass_approval(monkeypatch, tmp_path):
    research, backtests, jobs, client, payload = setup_creation(monkeypatch, tmp_path)
    created = client.post(PATHS[1], json=body_for(PATHS[1], payload))
    assert created.status_code == 202
    def forbidden(*args, **kwargs):
        pytest.fail("changed creation purpose must conflict before preparation")
    monkeypatch.setattr(main, "_prepare_signal_producer", forbidden)
    assert client.post(PATHS[0], json=payload).status_code == 409
    jobs.close()
    backtests.close()
    research.close()
