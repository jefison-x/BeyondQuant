"""Opt-in synthetic HTTP/official-process test; no external model or market data."""
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

from app.runtime import RuntimeAdapter, SessionConflict

pytestmark = pytest.mark.skipif(os.environ.get("BYQ_LIFECYCLE_WIRE_TEST") != "1",
                              reason="requires synthetic Backend/MCP and read-only Gateway source")


@pytest.mark.parametrize("outcome", ["completed", "cancelled", pytest.param("paid", marks=pytest.mark.skipif(
    os.environ.get("BYQ_LIFECYCLE_PAID_TEST") != "1", reason="separate bounded paid authorization required"))])
def test_official_registration_gateway_http_delivery_and_restart(monkeypatch, tmp_path, outcome):
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
    from wire_gateway.agent_lifecycle_delivery import LifecycleDelivery
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
    lost_ack = threading.Event()
    blocked_ack = threading.Event()
    original_post = gateway._adapter_post
    def postpone_first_ack(path, **kwargs):
        if not paid and path.endswith("/terminal-receipt") and not blocked_ack.is_set():
            from fastapi import HTTPException
            blocked_ack.set()
            raise HTTPException(status_code=503, detail="synthetic terminal ack unavailable")
        return original_post(path, **kwargs)
    monkeypatch.setattr(gateway, "_adapter_post", postpone_first_ack)
    terminals = []
    def send(context, event):
        result = gateway._send_agent_lifecycle(context, event)
        if event["outcome"] != "active":
            terminals.append(event)
            if len(terminals) == 1:
                lost_ack.set()
                raise TimeoutError("synthetic response lost after committed terminal")
        return result
    delivery = LifecycleDelivery(tmp_path, traces, send)
    monkeypatch.setattr(gateway, "lifecycle_delivery", delivery)
    collector = None
    try:
        adapter.create_session(session_id, trace_id, owner, workspace)
        session = gateway.ProductSession(conversation_id, session_id, trace_id,
                                         gateway.Principal(subject=owner), workspace)
        delivery.register(session)
        delivery.start()
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
            assert blocked_ack.wait(20)
            assert httpx.get(receipt_url, headers=context).json()["run"]["status"] == outcome
            with pytest.raises(SessionConflict, match="cleanup"):
                adapter.submit_prompt(session_id, "must not execute before cleanup acknowledgement")
        assert lost_ack.wait(60 if paid else 20)
        assert httpx.get(receipt_url, headers=context).json()["run"]["status"] == outcome
        delivery.close()
        delivery = LifecycleDelivery(tmp_path, TraceStore(tmp_path), send)
        delivery.start()
        deadline = time.monotonic() + 10
        ledger = tmp_path / f"{session_id}.lifecycle.json"
        while time.monotonic() < deadline:
            if len(terminals) == 2 and json.loads(ledger.read_text())["pending"] == {}:
                break
            time.sleep(0.05)
        assert len(terminals) == 2
        assert terminals[0] == terminals[1]
        assert json.loads(ledger.read_text())["pending"] == {}
        result = httpx.get(receipt_url, headers=context).json()["run"]
        assert result["root_run_id"] == terminals[0]["root_run_id"]
        assert result["status"] == outcome
        assert not record.pending_terminal_receipts
        if paid:
            assert len(paid_calls) == 2
    finally:
        allow_answer.set()
        delivery.close()
        adapter.close()
        server.should_exit = True
        http_thread.join(5)
        if collector:
            collector.join(5)
        provider.shutdown()
        provider.server_close()
        provider_thread.join(2)
        sock.close()
