"""Synthetic normalized outcome fixture, isolated CI Gateway only; no model."""
import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from app.trace_store import TraceStore

assert os.environ.get("BYQ_PRODUCT_TOKEN") == "ci-product-test-only"
assert os.environ.get("BYQ_BACKEND_URL") == "http://backend:8000"
owner = "ci-f7-browser"
with httpx.Client(base_url="http://backend:8000", timeout=10) as client:
    created_user = client.post("/v1/users", headers={"x-byq-actor-role": "admin"},
        json={"username": owner, "display_name": "F7 合成页面核查", "password": "ci-f7-browser-only", "role": "user"})
    created_user.raise_for_status()
    reply = client.post("/v1/auth/login", json={"username": owner, "password": "ci-f7-browser-only"})
    reply.raise_for_status()
    login = reply.json()
    workspace = login["workspace"]["workspace_id"]
    client.headers.update({"x-byq-owner-principal": owner, "x-byq-actor-principal": owner,
                           "x-byq-workspace-id": workspace})
    session = "f7-browser-" + uuid.uuid4().hex
    trace = "f7-browser-trace"
    created = client.post("/v1/product/conversations", json={"runtime_session_id": session, "trace_id": trace})
    created.raise_for_status()
    conversation = created.json()["conversation"]["conversation_id"]
    traces = TraceStore(os.environ["BYQ_WORKFLOW_TRACE_ROOT"])
    for index, code in enumerate(("domain-correction-stopped", "domain-call-reference-unproven", "domain-call-retention-bound")):
        message = client.post(f"/v1/product/conversations/{conversation}/messages",
            json={"role": "user", "content": f"合成 F7 页面核查 {index + 1}：请展示本轮停止原因。"})
        message.raise_for_status()
        root = uuid.uuid4().hex
        timestamp = datetime.now(timezone.utc).isoformat()
        for sequence, kind, payload in ((index * 2 + 1, "session.started", {"run_id": root}),
            (index * 2 + 2, "session.failed", {"run_id": root, "code": code, "retryable": False})):
            traces.append({"session_id": session, "trace_id": trace, "sequence": sequence,
                "timestamp": timestamp, "kind": kind, "source": "runtime-adapter", "payload": payload})
    client.post("/v1/auth/logout", json={"session_id": login["session_id"]}).raise_for_status()
print(json.dumps({"conversation_id": conversation, "synthetic": True, "model_calls": 0}))
