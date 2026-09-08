"""Disable only newly created synthetic owners before a real MCP call."""
import json
import os
import time

import httpx
import psycopg
from psycopg.rows import dict_row

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"
assert os.environ.get("BYQ_BACKEND_URL") == "http://backend:8000"


def read_state(owner):
    with psycopg.connect("postgresql://byq_app:byq-app-dev@postgres:5432/byq_domain", row_factory=dict_row) as db:
        db.execute("SET TRANSACTION READ ONLY")
        roots = db.execute("SELECT status FROM agent_runtime_turns WHERE owner_principal=%s", (owner,)).fetchall()
        runs = db.execute("SELECT status FROM agent_runs WHERE owner_principal=%s", (owner,)).fetchall()
        claims = db.execute("SELECT count(*) AS n FROM agent_domain_call_claims c JOIN agent_domain_correction_buckets b USING(root_run_id,task_id,action) WHERE b.owner_principal=%s", (owner,)).fetchone()["n"]
        artifacts = db.execute("SELECT count(*) AS n FROM artifacts a JOIN research_tasks t USING(task_id) WHERE t.owner_principal=%s", (owner,)).fetchone()["n"]
        tasks = db.execute("SELECT status FROM research_tasks WHERE owner_principal=%s", (owner,)).fetchall()
    return {"roots": roots, "runs": runs, "claims": claims, "artifacts": artifacts, "tasks": tasks}


for action, owner in (("byq_strategy_validate", "ci-f7-revoke-strategy"), ("byq_ml_strategy_create", "ci-f7-revoke-ml")):
    with httpx.Client(timeout=10) as client:
        client.post("http://byq-f7-provider:8801/control", json={"owner": owner, "action": action}).raise_for_status()
        created = client.post("http://backend:8000/v1/users", headers={"x-byq-actor-role": "admin"}, json={
            "username": owner, "password": "ci-f7-revoke-only", "display_name": "Synthetic revoke", "role": "user"})
        created.raise_for_status()
        user_id = created.json()["user"]["user_id"]
        client.post("http://gateway:8100/api/product/auth/login", json={"username": owner, "password": "ci-f7-revoke-only"}).raise_for_status()
        response = client.post("http://gateway:8100/v1/agent/sessions")
        response.raise_for_status()
        session = response.json()["session_id"]
        client.post(f"http://gateway:8100/v1/agent/sessions/{session}/turns", json={
            "content": "Synthetic revocation test only. No research execution or training."}).raise_for_status()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = client.get("http://byq-f7-provider:8801/status").json()
            if status["paused"]:
                break
            time.sleep(0.1)
        assert status["paused"] and status["calls"] == 3
        before = read_state(owner)
        assert before["roots"] == [{"status": "active"}] and before["claims"] == before["artifacts"] == 0
        disabled = client.post(f"http://backend:8000/v1/users/{user_id}/disable", headers={"x-byq-actor-role": "admin"})
        disabled.raise_for_status()
        assert disabled.json()["user"]["status"] == "disabled"
        client.post("http://byq-f7-provider:8801/release", json={"owner_disabled": True}).raise_for_status()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            after = read_state(owner)
            if after["roots"] and after["roots"][0]["status"] != "active":
                break
            time.sleep(0.25)
        status = client.get("http://byq-f7-provider:8801/status").json()
        print(json.dumps({"owner": owner, "conversation": session, "before": before, "after": after, "provider": status}), flush=True)
        assert after["claims"] == after["artifacts"] == 0
        assert len(after["roots"]) == len(after["runs"]) == 1
        assert after["roots"][0]["status"] != "active" and after["runs"][0]["status"] not in {"active", "pending_binding"}
        assert after["tasks"] == [{"status": "planned"}]
        assert status["calls"] == 4
        forbidden = client.post(f"http://gateway:8100/v1/agent/sessions/{session}/turns", json={"content": "must not run"})
        assert forbidden.status_code in {401, 403}
        assert client.get("http://byq-f7-provider:8801/status").json()["calls"] == 4
        print("PASS revoked identity before MCP " + action, flush=True)
with httpx.Client(timeout=5) as client:
    assert client.get("http://byq-f7-provider:8801/status").json()["total_calls"] == 8
