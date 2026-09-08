"""Actual official runtime/MCP/Backend safe diagnostic and native-stop check."""
import json
import os
import time
import httpx
import psycopg
from psycopg.rows import dict_row

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"


def inspect(owner):
    with psycopg.connect("postgresql://byq_app:byq-app-dev@postgres:5432/byq_domain", row_factory=dict_row) as db:
        db.execute("SET TRANSACTION READ ONLY")
        roots = db.execute("SELECT status FROM agent_runtime_turns WHERE owner_principal=%s", (owner,)).fetchall()
        claims = db.execute("SELECT c.status,c.result_json FROM agent_domain_call_claims c JOIN agent_domain_correction_buckets b USING(root_run_id,task_id,action) WHERE b.owner_principal=%s ORDER BY c.created_at", (owner,)).fetchall()
        artifacts = db.execute("SELECT count(*) AS n FROM artifacts a JOIN research_tasks t USING(task_id) WHERE t.owner_principal=%s", (owner,)).fetchone()["n"]
        runs = db.execute("SELECT status FROM agent_runs WHERE owner_principal=%s", (owner,)).fetchall()
    return roots, claims, artifacts, runs


for action, owner, field in (
    ("byq_strategy_validate", "ci-f7-diagnostic-strategy", "strategy.script"),
    ("byq_ml_strategy_create", "ci-f7-diagnostic-ml", "split.train.start"),
):
    with httpx.Client(timeout=10) as client:
        if os.environ.get("VERIFY_ONLY") != "1":
            client.post("http://byq-f7-provider:8801/control", json={"owner": owner, "action": action}).raise_for_status()
            client.post("http://backend:8000/v1/users", headers={"x-byq-actor-role": "admin"}, json={
                "username": owner, "password": "ci-diagnostic-only", "display_name": "Synthetic diagnostic", "role": "user"}).raise_for_status()
            client.post("http://gateway:8100/api/product/auth/login", json={"username": owner, "password": "ci-diagnostic-only"}).raise_for_status()
            created = client.post("http://gateway:8100/v1/agent/sessions")
            created.raise_for_status()
            session = created.json()["session_id"]
            base = f"http://gateway:8100/v1/agent/sessions/{session}"
            client.post(base + "/turns", json={"content": "合成校验错误验收：最多修正一次，仍失败则停止；不训练、不回测。"}).raise_for_status()
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                value = inspect(owner)
                if value[0] == [{"status": "failed"}]:
                    break
                time.sleep(0.2)
            state = client.get("http://byq-f7-provider:8801/status").json()
            assert state["calls"] == 4 and state["hint_observed"] is True, state
            public = client.get(base)
            public.raise_for_status()
            encoded = json.dumps(public.json())
            assert "domain-correction-stopped" in encoded
            assert "synthetic_private_module" not in encoded
            assert "request_sha256" not in encoded and "input_sha256" not in encoded
            assert not any(e["kind"] == "session.result" for e in public.json()["events"])
            print("PUBLIC_STOP " + session, flush=True)
        roots, claims, artifacts, runs = inspect(owner)
        assert roots == runs == [{"status": "failed"}]
        assert len(claims) == 2 and artifacts == 0
        assert [c["result_json"]["reason"] for c in claims] == ["domain_validation_failed", "correction_failed"]
        assert all(c["status"] == "correctable_failure" and c["result_json"]["validation"]["field"] == field for c in claims)
        assert "synthetic_private_module" not in json.dumps(claims)
        print("PASS safe field receipt + native stop " + owner, flush=True)
with httpx.Client(timeout=5) as client:
    assert client.get("http://byq-f7-provider:8801/status").json()["total"] == 8
