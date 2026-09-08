"""Engineering-only negative HTTP replay; real MCP/Backend, synthetic data only."""
import json
import os
import time
import httpx
import psycopg
from psycopg.rows import dict_row

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"
assert os.environ.get("BYQ_BACKEND_URL") == "http://backend:8000"
OWNER = "ci-late-http"


def snapshot():
    with psycopg.connect("postgresql://byq_app:byq-app-dev@postgres:5432/byq_domain", row_factory=dict_row) as db:
        db.execute("SET TRANSACTION READ ONLY")
        roots = db.execute("SELECT root_run_id,status FROM agent_runtime_turns WHERE owner_principal=%s ORDER BY created_at", (OWNER,)).fetchall()
        proofs = db.execute("SELECT * FROM agent_domain_call_evidence WHERE owner_principal=%s ORDER BY sequence", (OWNER,)).fetchall()
        claims = db.execute("SELECT c.root_run_id,c.idempotency_key,c.status,c.result_json FROM agent_domain_call_claims c JOIN agent_domain_correction_buckets b USING(root_run_id,task_id,action) WHERE b.owner_principal=%s ORDER BY c.created_at", (OWNER,)).fetchall()
        artifacts = db.execute("SELECT count(*) AS n FROM artifacts a JOIN research_tasks t USING(task_id) WHERE t.owner_principal=%s", (OWNER,)).fetchone()["n"]
        buckets = db.execute("SELECT root_run_id,repair_used FROM agent_domain_correction_buckets WHERE owner_principal=%s ORDER BY root_run_id", (OWNER,)).fetchall()
    return roots, proofs, claims, artifacts, buckets


def wait_for(predicate, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("bounded synthetic condition did not arrive")


def call(client, proof, *, root=None, generation=None, changed=False):
    # Read only original synthetic evidence; do not manufacture or submit proofs.
    headers = {"authorization": "Bearer ci-mcp-test-only", "accept": "application/json, text/event-stream",
        "x-byq-owner-principal": OWNER, "x-byq-workspace-id": proof["workspace_id"],
        "x-byq-session-id": proof["session_id"], "x-byq-trace-id": proof["trace_id"],
        "x-byq-actor-principal": "byq-product-agent-" + proof["session_id"],
        "x-byq-root-run-id": root or proof["root_run_id"], "x-byq-dsh-run-id": generation or proof["generation"]}
    response = client.post("http://mcp:8300/mcp/v1", headers=headers, json={"jsonrpc": "2.0", "id": 1,
        "method": "tools/call", "params": {"name": "byq_strategy_validate", "arguments": {
            "task_id": proof["task_id"], "agent_run_id": proof["agent_run_id"],
            "idempotency_key": proof["idempotency_key"], "strategy": {"name": "unobserved-change"} if changed else {}}}})
    response.raise_for_status()
    if "text/event-stream" in response.headers.get("content-type", ""):
        messages = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        value = next(m for m in messages if m.get("id") == 1)
    else:
        value = response.json()
    encoded = json.dumps(value)
    for private in ("request_sha256", "input_sha256", "evidence_json", proof["root_run_id"], proof["generation"]):
        assert private not in encoded, "private identity leaked into public MCP response"
    return value


if os.environ.get("VERIFY_REPLAY_ONLY") == "1":
    before = snapshot()
    assert [r["status"] for r in before[0]] == ["failed", "cancelled"]
    assert len(before[1]) == len(before[2]) == 3 and before[3] == 0
    with httpx.Client(timeout=12) as client:
        original = call(client, before[1][0])
        assert "error" in original or original.get("result", {}).get("isError") is True
        assert call(client, before[1][-1]) == original
        assert client.get("http://byq-f7-provider:8801/status").json()["total"] == 8
    assert snapshot() == before
    print("PASS restart replay: two terminal roots, three unchanged claims, zero artifacts, eight provider calls", flush=True)
    raise SystemExit(0)


with httpx.Client(timeout=12) as client:
    client.post("http://backend:8000/v1/users", headers={"x-byq-actor-role": "admin"}, json={
        "username": OWNER, "password": "ci-late-http-only", "display_name": "Synthetic late HTTP", "role": "user"}).raise_for_status()
    client.post("http://gateway:8100/api/product/auth/login", json={"username": OWNER, "password": "ci-late-http-only"}).raise_for_status()
    created = client.post("http://gateway:8100/v1/agent/sessions")
    created.raise_for_status()
    session = created.json()["session_id"]
    base = f"http://gateway:8100/v1/agent/sessions/{session}"
    client.post(base + "/turns", json={"content": "合成请求隔离验收，不进行训练或回测。"}).raise_for_status()
    wait_for(lambda: len(snapshot()[2]) == 2 and snapshot()[0][0]["status"] == "failed")
    wait_for(lambda: client.get(base + "/lifecycle-delivery").json().get("state") == "up_to_date")
    client.post("http://byq-f7-provider:8801/control", json={"phase": 2}).raise_for_status()
    client.post(base + "/resume").raise_for_status()
    client.post(base + "/turns", json={"content": "继续本会话的合成隔离验收。"}).raise_for_status()
    wait_for(lambda: client.get("http://byq-f7-provider:8801/status").json()["waiting"])
    before = snapshot()
    roots, proofs, claims, artifacts, buckets = before
    assert [r["status"] for r in roots] == ["failed", "active"]
    assert len(proofs) == len(claims) == 3 and artifacts == 0
    old, new = proofs[0], proofs[-1]
    assert old["root_run_id"] != new["root_run_id"] and old["generation"] != new["generation"]
    original = call(client, old)
    assert "error" in original or original.get("result", {}).get("isError") is True
    assert call(client, old) == original
    for label, overrides in (
        ("old-body-new-root", {"root": new["root_run_id"]}),
        ("old-body-new-root-generation", {"root": new["root_run_id"], "generation": new["generation"]}),
        ("old-key-unobserved-change", {"changed": True}),
    ):
        rejected = call(client, old, **overrides)
        assert "call_evidence_pending" in json.dumps(rejected), label
        assert snapshot() == before, "negative replay changed authoritative state"
        print("PASS " + label, flush=True)
    assert call(client, new) == original  # same closed failure, separate root debit
    assert snapshot() == before
    client.post(base + "/cancel", json={"mode": "hard"}).raise_for_status()
    client.post("http://byq-f7-provider:8801/control", json={"release": True}).raise_for_status()
    wait_for(lambda: snapshot()[0][-1]["status"] == "cancelled")
    cancelled = snapshot()
    assert call(client, new) == original
    assert snapshot() == cancelled
    public = client.get(base)
    public.raise_for_status()
    assert any(e["kind"] == "session.failed" for e in public.json()["events"])
    assert not any(e["kind"] == "session.result" for e in public.json()["events"])
    assert client.get("http://byq-f7-provider:8801/status").json()["total"] == 8
    print(json.dumps({"status": "PASS", "conversation": session, "roots": [r["status"] for r in cancelled[0]],
        "claims": len(cancelled[2]), "artifacts": cancelled[3], "provider_calls": 8,
        "scope": "scripted strategy schema receipt replay and cancel; not all F7 races"}), flush=True)
