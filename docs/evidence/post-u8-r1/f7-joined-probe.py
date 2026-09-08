"""Real Product/MCP/Backend journey against a non-forwarding test provider."""
import json
import os
import time
import httpx

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"
assert os.environ.get("BYQ_BACKEND_URL") == "http://backend:8000"

for action, owner in (("byq_strategy_validate", "ci-f7-joined-strategy"), ("byq_ml_strategy_create", "ci-f7-joined-ml")):
    with httpx.Client(timeout=15) as client:
        client.post("http://byq-f7-provider:8801/control", json={"action": action, "owner": owner}).raise_for_status()
        client.post("http://backend:8000/v1/users", headers={"x-byq-actor-role": "admin"},
            json={"username": owner, "display_name": "F7 joined synthetic", "password": "ci-f7-joined-only", "role": "user"}).raise_for_status()
        client.post("http://gateway:8100/api/product/auth/login",
            json={"username": owner, "password": "ci-f7-joined-only"}).raise_for_status()
        created = client.post("http://gateway:8100/v1/agent/sessions")
        created.raise_for_status()
        session = created.json()["session_id"]
        turn = client.post(f"http://gateway:8100/v1/agent/sessions/{session}/turns",
            json={"content": "Synthetic F7 joined schema-stop test only; no training or external provider."})
        turn.raise_for_status()
        deadline = time.monotonic() + 60
        events = []
        while time.monotonic() < deadline:
            replay = client.get(f"http://gateway:8100/v1/agent/sessions/{session}")
            replay.raise_for_status()
            events = replay.json().get("events", [])
            if any(event["kind"] == "session.failed" for event in events):
                break
            time.sleep(0.5)
        summary = client.get("http://byq-f7-provider:8801/status").json()
        codes = [event["payload"].get("code") for event in events if event["kind"] == "session.failed"]
        print(json.dumps({"action": action, "owner": owner, "conversation_id": session,
            "codes": codes, "provider": summary}, ensure_ascii=False), flush=True)
        assert codes == ["domain-correction-stopped"]
        assert 4 <= summary["calls"] <= 5
        assert [item.get("tool") for item in summary["steps"][:4]] == ["byq_agent_run_start", "byq_research_task_create", action, action]
        assert not any(event["kind"] == "session.result" for event in events)
        assert not any(field in json.dumps(events) for field in ("request_sha256", "input_sha256", "raw_arguments"))
        print("PASS joined schema-stop " + action, flush=True)
