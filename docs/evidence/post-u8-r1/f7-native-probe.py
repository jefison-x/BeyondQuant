"""Real Product -> native siblings -> MCP -> persistent BYQ admission."""
import json
import os
import time

import httpx
import psycopg
from psycopg.rows import dict_row

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"
assert os.environ.get("BYQ_BACKEND_URL") == "http://backend:8000"


def verify_database(owner, *, report=True):
    with psycopg.connect("postgresql://byq_app:byq-app-dev@postgres:5432/byq_domain", row_factory=dict_row) as db:
        db.execute("SET TRANSACTION READ ONLY")
        proofs = db.execute("SELECT root_run_id,input_sha256,agent_run_id FROM agent_domain_call_evidence WHERE owner_principal=%s", (owner,)).fetchall()
        claims = db.execute("SELECT c.status FROM agent_domain_call_claims c JOIN agent_domain_correction_buckets b USING(root_run_id,task_id,action) WHERE b.owner_principal=%s", (owner,)).fetchall()
        buckets = db.execute("SELECT repair_used FROM agent_domain_correction_buckets WHERE owner_principal=%s", (owner,)).fetchall()
        runs = db.execute("SELECT role_id,status FROM agent_runs WHERE owner_principal=%s ORDER BY created_at", (owner,)).fetchall()
        tasks = db.execute("SELECT task_id,status FROM research_tasks WHERE owner_principal=%s", (owner,)).fetchall()
        artifacts = db.execute("SELECT count(*) AS n FROM artifacts a JOIN research_tasks t USING(task_id) WHERE t.owner_principal=%s", (owner,)).fetchone()["n"]
        conversation = db.execute("SELECT conversation_id FROM product_conversations WHERE owner_principal=%s", (owner,)).fetchone()
    summary = {"owner": owner, "proofs": len(proofs), "claims": claims, "buckets": buckets, "runs": runs,
               "task_states": [task["status"] for task in tasks], "artifacts": artifacts}
    if report:
        print(json.dumps(summary), flush=True)
    assert len(proofs) == 2
    assert len({proof["root_run_id"] for proof in proofs}) == 1
    assert len({proof["input_sha256"] for proof in proofs}) == 1
    assert len({proof["agent_run_id"] for proof in proofs}) == 2
    assert claims == [{"status": "correctable_failure"}]
    assert buckets == [{"repair_used": False}]
    # Existing AgentRun contract closes root-bound authorization records at
    # root termination. A child text response is not domain success evidence.
    assert len(runs) == 3 and all(run["status"] == "failed" for run in runs)
    assert len(tasks) == 1 and tasks[0]["status"] == "planned" and artifacts == 0
    return conversation["conversation_id"]


restart_only = os.environ.get("F7_VERIFY_RESTART") == "1"
for action, owner in (("byq_strategy_validate", "ci-f7-native-strategy"), ("byq_ml_strategy_create", "ci-f7-native-ml")):
    with httpx.Client(timeout=15) as client:
        existing = restart_only or (os.environ.get("F7_RESUME_AFTER_STRATEGY") == "1" and action == "byq_strategy_validate")
        if not existing:
            client.post("http://byq-f7-provider:8801/control", json={"action": action, "owner": owner}).raise_for_status()
            client.post("http://backend:8000/v1/users", headers={"x-byq-actor-role": "admin"}, json={
                "username": owner, "display_name": "F7 native synthetic", "password": "ci-f7-native-only", "role": "user"}).raise_for_status()
        client.post("http://gateway:8100/api/product/auth/login", json={"username": owner, "password": "ci-f7-native-only"}).raise_for_status()
        if existing:
            session = verify_database(owner)
        else:
            created = client.post("http://gateway:8100/v1/agent/sessions")
            created.raise_for_status()
            session = created.json()["session_id"]
            accepted = client.post(f"http://gateway:8100/v1/agent/sessions/{session}/turns", json={
                "content": "Synthetic sibling admission test only. No research execution, training, or external Provider."})
            accepted.raise_for_status()
        deadline = time.monotonic() + 60
        events = []
        while time.monotonic() < deadline:
            reply = client.get(f"http://gateway:8100/v1/agent/sessions/{session}")
            reply.raise_for_status()
            events = reply.json().get("events", [])
            if any(event["kind"] == "session.failed" for event in events):
                break
            time.sleep(0.5)
        status = client.get("http://byq-f7-provider:8801/status").json()
        codes = [event["payload"].get("code") for event in events if event["kind"] == "session.failed"]
        print(json.dumps({"action": action, "conversation": session, "codes": codes, "provider": status}), flush=True)
        assert codes == ["domain-correction-stopped"]
        assert not any(event["kind"] == "session.result" for event in events)
        assert not any(field in json.dumps(events) for field in ("request_sha256", "input_sha256", "raw_arguments"))
        activities = {event["payload"]["activity_id"]: event["payload"]["state"]
                      for event in events if event["kind"] == "agent.activity"}
        assert sorted(activities.values()) == ["completed", "completed", "failed", "failed"]
        assert status["calls"] == 9 and status["root_calls"] == 4 and status["children"] == {"1": 3, "2": 2}
        if not existing:
            for attempt in range(30):
                try:
                    verify_database(owner, report=False)
                    verify_database(owner)
                    break
                except AssertionError:
                    if attempt == 29:
                        verify_database(owner)
                        raise
                    time.sleep(0.25)
        print("PASS native siblings " + action + (" after restart" if restart_only else ""), flush=True)
with httpx.Client(timeout=5) as client:
    assert client.get("http://byq-f7-provider:8801/status").json()["total_calls"] == 18
