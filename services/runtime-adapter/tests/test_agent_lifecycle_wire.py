"""Opt-in synthetic Backend/MCP and official-process test; paid mode is separately gated."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import uvicorn

from app.runtime import RuntimeAdapter

pytestmark = pytest.mark.skipif(os.environ.get("BYQ_LIFECYCLE_WIRE_TEST") != "1",
                              reason="requires synthetic Backend/MCP and read-only Gateway source")


@pytest.mark.parametrize("outcome", ["completed", "cancelled", pytest.param("paid", marks=pytest.mark.skipif(
    os.environ.get("BYQ_LIFECYCLE_PAID_TEST") != "1", reason="separate bounded paid authorization required"))])
def test_official_registration_gateway_collector_terminal_ack_retry_same_boot(monkeypatch, tmp_path, outcome):
    paid_key = os.environ.get("BYQ_LIFECYCLE_PAID_KEY", "").strip().strip('"').strip("'")
    paid = outcome == "paid"
    if paid:
        assert paid_key, "bounded paid test credential unavailable"
        outcome = "completed"
    source = Path(os.environ["BYQ_LIFECYCLE_GATEWAY_SOURCE"])
    spec = importlib.util.spec_from_file_location("wire_gateway", source / "__init__.py",
                                                submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["wire_gateway"] = module
    spec.loader.exec_module(module)
    from wire_gateway import main as gateway
    from wire_gateway.trace_store import TraceStore
    from app import main as runtime_http

    backend = os.environ["BYQ_BACKEND_URL"]
    owner = "wire-" + uuid.uuid4().hex[:16]
    password = "synthetic-wire-password"
    response = httpx.post(backend + "/v1/users", headers={"x-byq-actor-role": "admin"},
                          json={"username": owner, "password": password, "display_name": "Synthetic lifecycle"})
    response.raise_for_status()
    login = httpx.post(backend + "/v1/auth/login", json={"username": owner, "password": password})
    login.raise_for_status()
    workspace = login.json()["workspace"]["workspace_id"]
    session_id, trace_id = "wire-" + uuid.uuid4().hex, "trace-" + uuid.uuid4().hex
    headers = {"x-byq-owner-principal": owner, "x-byq-actor-principal": owner, "x-byq-workspace-id": workspace}
    catalog = httpx.post(backend + "/v1/product/conversations", headers=headers,
                         json={"runtime_session_id": session_id, "trace_id": trace_id})
    catalog.raise_for_status()
    conversation_id = catalog.json()["conversation"]["conversation_id"]
    allow_answer = threading.Event()
    tool_results = []
    paid_calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["content-length"])))
            results = [item for item in request["messages"] if item.get("role") == "tool"]
            if paid:
                if len(paid_calls) >= 2:
                    self.send_error(429, "synthetic evaluation request budget exhausted")
                    return
                paid_calls.append(1)
                name = "mcp__byq__byq_agent_run_start"
                request["tools"] = [tool for tool in request.get("tools", []) if tool["function"]["name"] == name]
                request["tool_choice"] = "none" if results else {"type": "function", "function": {"name": name}}
                request["stream"] = False
                request.pop("stream_options", None)
                request["thinking"] = {"type": "disabled"}
                request["max_tokens"] = 512
                response = httpx.post("https://api.deepseek.com/chat/completions", json=request,
                    headers={"authorization": "Bearer " + paid_key}, timeout=45)
                if response.status_code != 200:
                    self.send_error(502, "bounded paid evaluation provider rejected request")
                    return
                choice = response.json()["choices"][0]
                message = choice["message"]
                if not results:
                    calls = message.get("tool_calls", [])
                    if (len(calls) != 1 or calls[0]["function"]["name"] != name
                            or json.loads(calls[0]["function"]["arguments"]) != {
                                "role_id": "quant_orchestrator", "idempotency_key": "original-wire-key"}):
                        self.send_error(502, "paid evaluation failed exact synthetic tool guard")
                        return
                    delta = {"tool_calls": [{**calls[0], "index": 0}]}
                else:
                    if message.get("tool_calls"):
                        self.send_error(502, "paid evaluation cannot execute another tool")
                        return
                    delta = {"content": message.get("content") or ""}
            elif results:
                tool_results.extend(results)
                if outcome == "cancelled":
                    allow_answer.wait(20)
                delta = {"content": "合成验收完成"}
            else:
                delta = {"tool_calls": [{"index": 0, "id": "wire-registration", "type": "function", "function": {
                    "name": "mcp__byq__byq_agent_run_start", "arguments": json.dumps({
                        "role_id": "quant_orchestrator", "idempotency_key": "original-wire-key"})}}]}
            chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if results else "tool_calls"}]}]
            body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-local-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{provider.server_port}")
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "")
    adapter = RuntimeAdapter()
    monkeypatch.setattr(runtime_http, "adapter", adapter)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(runtime_http.app, log_level="error"))
    http_thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    http_thread.start()
    monkeypatch.setattr(gateway, "RUNTIME_ADAPTER_URL", f"http://127.0.0.1:{sock.getsockname()[1]}")
    monkeypatch.setattr(gateway, "BACKEND_URL", backend)
    traces = TraceStore(tmp_path)
    monkeypatch.setattr(gateway, "trace_store", traces)
    monkeypatch.setattr(gateway, "_register_answer_delivery", lambda _: None)
    monkeypatch.setattr(gateway, "product_sessions", gateway.ProductSessionRegistry())
    original_adapter_post = gateway._adapter_post
    original_backend_authority_request = gateway._backend_runtime_authority_request
    terminal_ack_attempts = []
    backend_root_closes = []
    terminal_events = []
    lost_ack_response = threading.Event()
    terminal_send_completed = threading.Event()

    def lose_first_ack_response_after_commit(path, *, payload=None, timeout=20.0):
        reply = original_adapter_post(path, payload=payload, timeout=timeout)
        if path.endswith("/terminal-receipt"):
            terminal_ack_attempts.append((path, payload, gateway._adapter_authority()["boot_id"]))
            if not paid and len(terminal_ack_attempts) == 1:
                # The real Adapter commits the exact receipt before this synthetic
                # transport drops the first response. Gateway must retry only that
                # receipt under the same still-current Adapter boot.
                lost_ack_response.set()
                from fastapi import HTTPException
                raise HTTPException(status_code=503, detail="synthetic committed ACK response lost")
        return reply

    def record_backend_root_close(method, path, payload=None, scope=None):
        reply = original_backend_authority_request(method, path, payload, scope)
        if path.startswith("/internal/runtime-authority/roots/") and path.endswith("/close"):
            backend_root_closes.append((method, path, payload, reply))
        return reply

    original_send_agent_lifecycle = gateway._send_agent_lifecycle

    def observe_lifecycle_send(context, event, *, expected_boot_id=None):
        if event["outcome"] != "active":
            terminal_events.append((event, expected_boot_id))
        reply = original_send_agent_lifecycle(context, event, expected_boot_id=expected_boot_id)
        if event["outcome"] != "active":
            terminal_send_completed.set()
        return reply

    monkeypatch.setattr(gateway, "_adapter_post", lose_first_ack_response_after_commit)
    monkeypatch.setattr(gateway, "_backend_runtime_authority_request", record_backend_root_close)
    monkeypatch.setattr(gateway, "_send_agent_lifecycle", observe_lifecycle_send)
    collector = None
    session = None
    try:
        adapter.create_session(session_id, trace_id, owner, workspace)
        session = gateway.ProductSession(conversation_id, session_id, trace_id,
                                         gateway.Principal(subject=owner), workspace,
                                         boot_id=adapter.boot_id)
        gateway.product_sessions.add(session)
        collector = threading.Thread(target=gateway._collect_trace, args=(session,), daemon=True)
        collector.start()
        adapter.submit_prompt(session_id, "仅做合成接口核查：调用 byq_agent_run_start，参数必须且只能是 "
            '{"role_id":"quant_orchestrator","idempotency_key":"original-wire-key"}。'
            "随后仅根据回执用一句话说明注册状态。禁止其他工具、研究、训练、回测和数据访问。")
        record = adapter._get(session_id)
        context = {**headers, "x-byq-actor-principal": f"byq-product-agent-{session_id}",
                   "x-byq-session-id": session_id, "x-byq-trace-id": trace_id,
                   "x-byq-dsh-run-id": record.runtime_generation}
        receipt_url = backend + "/v1/agents/runs/registration-receipt?idempotency_key=original-wire-key"
        deadline = time.monotonic() + (100 if paid else 30)
        while time.monotonic() < deadline:
            response = httpx.get(receipt_url, headers=context)
            if response.status_code == 200 and response.json()["run"]["status"] in {"active", "completed"}:
                break
            time.sleep(0.05)
        else:
            pytest.fail("official MCP registration never bound to the observed root")
        if outcome == "cancelled":
            adapter.cancel_session(session_id, "hard")
            allow_answer.set()
        if not paid:
            assert lost_ack_response.wait(20)
            assert httpx.get(receipt_url, headers=context).json()["run"]["status"] == outcome
        assert terminal_send_completed.wait(60 if paid else 20)
        assert httpx.get(receipt_url, headers=context).json()["run"]["status"] == outcome
        expected_ack_count = 1 if paid else 2
        assert len(terminal_events) == 1
        terminal_event, expected_boot_id = terminal_events[0]
        assert terminal_event["outcome"] == outcome
        assert expected_boot_id == adapter.boot_id
        receipt = gateway.lifecycle_receipt(terminal_event)
        assert len(backend_root_closes) == 1
        close_method, close_path, close_payload, closed = backend_root_closes[0]
        assert close_method == "POST"
        assert close_path == f"/internal/runtime-authority/roots/{terminal_event['root_run_id']}/close"
        assert close_payload == {
            "schema_version": gateway.RUNTIME_ROOT_CLOSE_SCHEMA,
            "boot_id": adapter.boot_id,
            "sequence": terminal_event["sequence"],
            "outcome": outcome,
            "event_sha256": receipt["event_sha256"],
        }
        assert closed == {"receipt": receipt}
        assert len(terminal_ack_attempts) == expected_ack_count
        expected_ack = (f"/internal/runtime/sessions/{session_id}/terminal-receipt",
                        closed, expected_boot_id)
        assert terminal_ack_attempts == [expected_ack] * expected_ack_count
        assert not record.pending_terminal_receipts
        assert not list(tmp_path.glob("*.lifecycle.json"))
        result = httpx.get(receipt_url, headers=context).json()["run"]
        assert result["root_run_id"] == terminal_event["root_run_id"]
        assert result["status"] == outcome
        if paid:
            assert len(paid_calls) == 2
    finally:
        allow_answer.set()
        if session is not None:
            session.released = True
        adapter.close()
        server.should_exit = True
        http_thread.join(5)
        if collector:
            collector.join(5)
        provider.shutdown()
        provider.server_close()
        provider_thread.join(2)
        sock.close()
