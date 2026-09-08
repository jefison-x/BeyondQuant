"""Synthetic real MCP crash while a Backend artifact transaction is in flight."""
import json
import os
import socket
import time

import httpx
import psycopg
from psycopg.rows import dict_row
from tests.test_strategy_artifact import strategy_payload
from tests.test_ml_strategy import valid_strategy

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"
action = os.environ["F7_ACTION"]
assert action in {"byq_strategy_validate", "byq_ml_strategy_create"}
owner = "ci-f7-loss-" + ("strategyvalid" if action == "byq_strategy_validate" else "mlqualified")
DSN = "postgresql://byq_app:byq-app-dev@postgres:5432/byq_domain"


def wait(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("bounded synthetic condition missing")


def query(sql, args=()):
    with psycopg.connect(DSN, row_factory=dict_row) as db:
        db.execute("SET TRANSACTION READ ONLY")
        return db.execute(sql, args).fetchall()


def disconnected():
    try:
        with socket.create_connection(("mcp", 8300), timeout=0.2):
            return False
    except OSError:
        return True


with httpx.Client(timeout=10) as client:
    if os.environ.get("VERIFY_REPLAY_ONLY") != "1":
        client.post("http://byq-f7-provider:8801/control", json={"owner": owner, "action": action}).raise_for_status()
        client.post("http://backend:8000/v1/users", headers={"x-byq-actor-role": "admin"}, json={
            "username": owner, "password": "ci-loss-test-only", "display_name": "Synthetic loss", "role": "user"}).raise_for_status()
        client.post("http://gateway:8100/api/product/auth/login", json={"username": owner, "password": "ci-loss-test-only"}).raise_for_status()
        response = client.post("http://gateway:8100/v1/agent/sessions")
        response.raise_for_status()
        session = response.json()["session_id"]
        client.post(f"http://gateway:8100/v1/agent/sessions/{session}/turns", json={
            "content": "合成传输中断验收，仅创建策略制品，不训练、不回测；未知结果不得自动重试。"}).raise_for_status()
        wait(lambda: client.get("http://byq-f7-provider:8801/status").json()["paused"])
        # Isolated Engineering fault injection only. No data/evidence mutation.
        with psycopg.connect(DSN) as lock:
            lock.execute("SET LOCAL statement_timeout='15s'")
            lock.execute("SET LOCAL idle_in_transaction_session_timeout='15s'")
            lock.execute("LOCK TABLE artifacts IN SHARE MODE")
            pid = lock.info.backend_pid
            client.post("http://byq-f7-provider:8801/release", json={"release": True}).raise_for_status()
            wait(lambda: query("SELECT pid FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))", (pid,)), 6)
            print("FAULT_READY " + owner, flush=True)
            # Host driver kills this scope's MCP only after actual DB contention.
            wait(disconnected, 6)
            lock.rollback()
        rows = wait(lambda: query("SELECT c.status FROM agent_domain_call_claims c JOIN agent_domain_correction_buckets b USING(root_run_id,task_id,action) WHERE b.owner_principal=%s AND c.status='succeeded'", (owner,)))
        assert len(rows) == 1
        print("COMMIT_AFTER_DISCONNECT " + owner, flush=True)
        raise SystemExit(0)

    proofs = query("SELECT * FROM agent_domain_call_evidence WHERE owner_principal=%s", (owner,))
    assert len(proofs) == 1
    proof = proofs[0]
    claims = query("SELECT c.result_json FROM agent_domain_call_claims c JOIN agent_domain_correction_buckets b USING(root_run_id,task_id,action) WHERE b.owner_principal=%s", (owner,))
    assert len(claims) == 1 and claims[0]["result_json"]["state"] == "succeeded"
    headers = {"authorization": "Bearer ci-mcp-test-only", "accept": "application/json, text/event-stream",
        "x-byq-owner-principal": owner, "x-byq-workspace-id": proof["workspace_id"],
        "x-byq-session-id": proof["session_id"], "x-byq-trace-id": proof["trace_id"],
        "x-byq-actor-principal": "byq-product-agent-" + proof["session_id"],
        "x-byq-root-run-id": proof["root_run_id"], "x-byq-dsh-run-id": proof["generation"]}
    payload = {"task_id": proof["task_id"], "agent_run_id": proof["agent_run_id"],
        "idempotency_key": "loss-valid-input",
        **({"trace_id": "model-not-authority"} if action == "byq_strategy_validate" else {}),
        "strategy": strategy_payload() if action == "byq_strategy_validate" else valid_strategy()}
    for _ in range(2):
        reply = client.post("http://mcp:8300/mcp/v1", headers=headers, json={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": action, "arguments": payload}})
        reply.raise_for_status()
        expected = claims[0]["result_json"]["result"]["artifact"]["artifact_id"]
        assert expected in reply.text, reply.text
        for private in ("request_sha256", "input_sha256", proof["root_run_id"], proof["generation"]):
            assert private not in reply.text
    assert query("SELECT count(*) AS n FROM artifacts a JOIN research_tasks t USING(task_id) WHERE t.owner_principal=%s", (owner,)) == [{"n": 1}]
    assert query("SELECT c.result_json FROM agent_domain_call_claims c JOIN agent_domain_correction_buckets b USING(root_run_id,task_id,action) WHERE b.owner_principal=%s", (owner,)) == claims
    print("PASS durable MCP replay after real disconnect " + owner, flush=True)
