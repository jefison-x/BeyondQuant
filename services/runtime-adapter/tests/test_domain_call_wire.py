"""Official-process identity probe, loopback only; no domain or paid Provider."""
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

import pytest

from app.runtime import RuntimeAdapter, SessionStatus


pytestmark = pytest.mark.skipif(
    os.environ.get("BYQ_DOMAIN_CALL_WIRE_TEST") != "1" or version("deepseek-harness-sdk") != "0.1.2rc1",
    reason="explicit loopback official-process identity qualification",
)


@pytest.mark.parametrize("action", ["byq_strategy_validate", "byq_ml_strategy_create"])
def test_same_generation_wire_identity_across_roots(monkeypatch, action):
    calls, observations, requests = [], [], []
    arguments = {"task_id": "task_synthetic", "agent_run_id": "agent_synthetic",
                 "idempotency_key": "synthetic-same-key", "strategy": {"label": "合成"}}

    class Mcp(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            method = body.get("method")
            if "id" not in body:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "synthetic-identity-probe", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": action, "description": "Synthetic identity observation only",
                                     "inputSchema": {"type": "object", "additionalProperties": True}}]}
            elif method == "tools/call":
                calls.append({"body": body, "headers": {key: value for key, value in self.headers.items()
                              if key.lower().startswith("x-byq-")}})
                result = {"content": [{"type": "text", "text": "Synthetic rejection; no domain write"}], "isError": True}
            else:
                result = {}
            encoded = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            requests.append(body)
            if len(requests) > 4:
                self.send_error(429, "synthetic request cap")
                return
            calling = len(requests) % 2 == 1
            delta = {"tool_calls": [{"index": 0, "id": "model-call-reused", "type": "function", "function": {
                "name": "mcp__byq__" + action, "arguments": json.dumps(arguments)}}]} if calling else {"content": "合成结束"}
            chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if calling else "stop"}]}]
            encoded = ("".join(f"data: {json.dumps(item)}\n\n" for item in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    mcp = ThreadingHTTPServer(("127.0.0.1", 0), Mcp)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (mcp, provider)]
    for thread in threads:
        thread.start()
    monkeypatch.setenv("BYQ_MCP_URL", f"http://127.0.0.1:{mcp.server_port}/mcp/v1")
    monkeypatch.setenv("BYQ_MCP_TOKEN", "synthetic-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{provider.server_port}")
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "")
    adapter = RuntimeAdapter()
    original = adapter._on_notification

    def observe(record, notification, **kwargs):
        payload = getattr(notification, "payload", {})
        event = payload.get("event", {})
        if event.get("type") == "tool/call":
            observations.append({"root": kwargs["source_run"].run_id, "data": event.get("data"),
                                 "session": payload.get("sessionId")})
        original(record, notification, **kwargs)

    adapter._on_notification = observe
    session = "identity-" + uuid.uuid4().hex
    try:
        adapter.create_session(session, "synthetic-trace", "synthetic-owner", "synthetic-workspace")
        record = adapter._get(session)
        generation = record.runtime_generation
        for index in range(2):
            root = adapter.submit_prompt(session, f"Synthetic observation {index}")
            deadline = time.monotonic() + 20
            while record.active_run is not None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert record.status == SessionStatus.IDLE
            adapter.acknowledge_terminal(session, record.terminal_receipts[root])
        assert len(calls) == len(observations) == 2
        assert observations[0]["root"] != observations[1]["root"]
        assert record.runtime_generation == generation
        assert all(call["body"]["params"]["arguments"] == arguments for call in calls)
        assert calls[0]["headers"] == calls[1]["headers"]
        assert all(set(call["body"]["params"]) == {"name", "arguments"} for call in calls)
        assert calls[0]["body"]["id"] != calls[1]["body"]["id"]
        assert all(item["data"]["callId"] == "model-call-reused" for item in observations)
        assert [item["data"]["turn"] for item in observations] == [1, 2]
        # The MCP request counter is not present in the official tool/call
        # observation. Neither counter arithmetic nor model callId is proof.
        assert all("id" not in item["data"] for item in observations)
    finally:
        adapter.close()
        for server in (mcp, provider):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
