"""Three real Product turns with a local scripted Provider; no paid model."""
import json
import os
import time
import httpx
import psycopg
from psycopg.rows import dict_row

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"
assert os.environ.get("BYQ_BACKEND_URL") == "http://backend:8000"
owner = "ci-recovery-context"
goals = ["合成验收：沪深300近三年普通动量双均线，每周调仓，先研究凯利仓位管理。", "继续", "改为中证500，只讨论方案，不执行研究。"]
with httpx.Client(timeout=15) as client:
    existing = os.environ.get("RECOVERY_RESUME_SESSION")
    first_phase = int(os.environ.get("RECOVERY_RESUME_PHASE", "2")) if existing else 1
    if not existing:
        client.post("http://backend:8000/v1/users", headers={"x-byq-actor-role": "admin"}, json={
            "username": owner, "display_name": "Synthetic recovery", "password": "ci-recovery-only", "role": "user"}).raise_for_status()
    client.post("http://gateway:8100/api/product/auth/login", json={"username": owner, "password": "ci-recovery-only"}).raise_for_status()
    if existing:
        session = existing
    else:
        created = client.post("http://gateway:8100/v1/agent/sessions")
        created.raise_for_status()
        session = created.json()["session_id"]
    for phase, goal in enumerate(goals, 1):
        if phase < first_phase:
            continue
        if phase > 1 and not (existing and phase == first_phase):
            client.post("http://byq-f7-provider:8801/control", json={"phase": phase}).raise_for_status()
        if phase == 2:
            client.post(f"http://gateway:8100/v1/agent/sessions/{session}/resume").raise_for_status()
        accepted = client.post(f"http://gateway:8100/v1/agent/sessions/{session}/turns", json={"content": goal})
        accepted.raise_for_status()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            reply = client.get(f"http://gateway:8100/v1/agent/sessions/{session}")
            reply.raise_for_status()
            events = reply.json().get("events", [])
            failed = [e for e in events if e["kind"] == "session.failed"]
            results = [e for e in events if e["kind"] == "session.result"]
            if len(failed) == 1 and len(results) == phase - 1:
                break
            time.sleep(0.3)
        else:
            print(json.dumps(client.get("http://byq-f7-provider:8801/status").json()), flush=True)
            raise AssertionError(f"phase {phase} did not reach expected terminal count")
        assert failed[0]["payload"].get("code") == "domain-correction-stopped"
        assert not any(key in json.dumps(events) for key in ("request_sha256", "input_sha256", "raw_arguments"))
        status = client.get("http://byq-f7-provider:8801/status").json()
        assert status["calls"] == {1: 4, 2: 3, 3: 1}[phase], status
        assert not any("FAILED" in check for check in status["checks"]), status
        print(json.dumps({"phase": phase, "conversation": session, "provider": status}), flush=True)
        if phase > 1:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                saved = client.get(f"http://gateway:8100/v1/agent/sessions/{session}").json()
                if len([m for m in saved.get("messages", []) if m["role"] == "assistant"]) == phase - 1:
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("public answer was not durably delivered")
    with psycopg.connect("postgresql://byq_app:byq-app-dev@postgres:5432/byq_domain", row_factory=dict_row) as db:
        db.execute("SET TRANSACTION READ ONLY")
        tasks = db.execute("SELECT task_id,status,objective FROM research_tasks WHERE owner_principal=%s", (owner,)).fetchall()
        assert len(tasks) == 1 and tasks[0]["objective"] == goals[0] and tasks[0]["status"] == "planned", tasks
        assert db.execute("SELECT count(*) AS n FROM artifacts a JOIN research_tasks t USING(task_id) WHERE t.owner_principal=%s", (owner,)).fetchone()["n"] == 0
        runs = db.execute("SELECT status FROM agent_runs WHERE owner_principal=%s", (owner,)).fetchall()
        assert runs == [{"status": "failed"}], runs
    assert status["total"] == 8 and len(status["checks"]) == 4
    print("PASS three roots: original objective retained, exact task discovered, new goal delivered; one planned task, no artifacts", flush=True)
