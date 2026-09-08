"""Opt-in real Adapter/DSH process death with synthetic Backend/MCP only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.lifecycle_journal import LifecycleJournal

pytestmark = pytest.mark.skipif(os.environ.get("BYQ_LIFECYCLE_WIRE_TEST") != "1", reason="requires isolated synthetic services")


@pytest.mark.parametrize("disabled", [False, True])
def test_killed_adapter_recovers_exact_run_without_another_model_call(monkeypatch, tmp_path, disabled):
    source = Path(os.environ["BYQ_LIFECYCLE_GATEWAY_SOURCE"])
    spec = importlib.util.spec_from_file_location("crash_gateway", source / "__init__.py", submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["crash_gateway"] = module
    spec.loader.exec_module(module)
    from crash_gateway import main as gateway
    from crash_gateway.agent_lifecycle_delivery import LifecycleDelivery
    from crash_gateway.trace_store import TraceStore
    backend = os.environ["BYQ_BACKEND_URL"]
    owner = "crash-" + uuid.uuid4().hex[:16]
    password = "synthetic-crash-password"
    created = httpx.post(backend + "/v1/users", headers={"x-byq-actor-role": "admin"},
        json={"username": owner, "password": password, "display_name": "Synthetic crash"})
    created.raise_for_status()
    user_id = created.json()["user"]["user_id"]
    login = httpx.post(backend + "/v1/auth/login", json={"username": owner, "password": password})
    login.raise_for_status()
    workspace = login.json()["workspace"]["workspace_id"]
    session, trace = "crash-" + uuid.uuid4().hex, "trace-" + uuid.uuid4().hex
    headers = {"x-byq-owner-principal": owner, "x-byq-actor-principal": owner, "x-byq-workspace-id": workspace}
    catalog = httpx.post(backend + "/v1/product/conversations", headers=headers,
        json={"runtime_session_id": session, "trace_id": trace})
    catalog.raise_for_status()
    conversation = catalog.json()["conversation"]["conversation_id"]
    release = threading.Event()
    waiting = threading.Event()
    calls = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(1)
            if len(calls) > 2:
                self.send_error(429, "synthetic request budget exhausted")
                return
            if any(m.get("role") == "tool" for m in request["messages"]):
                waiting.set()
                release.wait(45)
                delta = {"content": "Synthetic only"}
                finish = "stop"
            else:
                delta = {"tool_calls": [{"index": 0, "id": "synthetic-register", "type": "function", "function": {
                    "name": "mcp__byq__byq_agent_run_start", "arguments": json.dumps({
                        "role_id": "quant_orchestrator", "idempotency_key": "crash-original-key"})}}]}
                finish = "tool_calls"
            chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
            body = ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    runtime_url = f"http://127.0.0.1:{port}"
    runtime_root = tmp_path / "runtime"
    environment = {**os.environ, "DSH_SESSION_ROOT": str(runtime_root), "DEEPSEEK_API_KEY": "synthetic-local-only",
                   "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{provider.server_port}", "BYQ_CREDENTIAL_RESOLVER_TOKEN": ""}
    process = None
    def start():
        child = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
            "--port", str(port), "--log-level", "error"], env=environment, start_new_session=True)
        for _ in range(150):
            if child.poll() is not None:
                raise AssertionError("isolated runtime failed to start")
            try:
                if httpx.get(runtime_url + "/healthz", timeout=0.25).status_code == 200:
                    return child
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        child.kill()
        child.wait(5)
        raise AssertionError("runtime readiness timeout")
    def kill(child):
        if child is not None and child.poll() is None:
            # Exact process group created by this test; never discover/guess PIDs.
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(5)
    traces = TraceStore(tmp_path / "traces")
    monkeypatch.setattr(gateway, "trace_store", traces)
    monkeypatch.setattr(gateway, "RUNTIME_ADAPTER_URL", runtime_url)
    monkeypatch.setattr(gateway, "BACKEND_URL", backend)
    now = [time.time()]
    delivery = LifecycleDelivery(tmp_path / "traces", traces, gateway._send_agent_lifecycle,
                                 clock=lambda: now[0], recover=gateway._recover_agent_lifecycle)
    product = gateway.ProductSession(conversation, session, trace, gateway.Principal(subject=owner), workspace)
    collector = None
    try:
        process = start()
        response = httpx.post(runtime_url + "/internal/runtime/sessions", timeout=20,
            json={"session_id": session, "trace_id": trace, "owner_principal": owner, "workspace_id": workspace})
        response.raise_for_status()
        delivery.register(product)
        delivery.start()
        collector = threading.Thread(target=gateway._collect_trace, args=(product,), daemon=True)
        collector.start()
        prompt = "Synthetic registration only; no research or business execution."
        submitted = httpx.post(runtime_url + f"/internal/runtime/sessions/{session}/prompt",
                              json={"content": prompt, "idempotency_key": "original-crash-prompt"})
        submitted.raise_for_status()
        root_id = submitted.json()["run_id"]
        assert waiting.wait(20)
        state = LifecycleJournal.read(runtime_root / "byq-lifecycle-evidence" / f"{session}.json")
        assert state["open_root"]["root_run_id"] == root_id
        agent_headers = {**headers, "x-byq-actor-principal": f"byq-product-agent-{session}",
            "x-byq-session-id": session, "x-byq-trace-id": trace, "x-byq-dsh-run-id": state["open_root"]["generation"]}
        receipt_url = backend + "/v1/agents/runs/registration-receipt?idempotency_key=crash-original-key"
        assert httpx.get(receipt_url, headers=agent_headers).json()["run"]["status"] == "active"
        if disabled:
            response = httpx.post(backend + f"/v1/users/{user_id}/disable", headers={"x-byq-actor-role": "admin"})
            response.raise_for_status()
        kill(process)
        collector.join(5)
        delivery.close()
        process = start()  # same evidence volume, new Adapter; no session/model create
        now[0] += 31
        delivery = LifecycleDelivery(tmp_path / "traces", traces, gateway._send_agent_lifecycle,
                                     clock=lambda: now[0], recover=gateway._recover_agent_lifecycle)
        delivery.run_once()
        ledger = json.loads((tmp_path / "traces" / f"{session}.lifecycle.json").read_text())
        assert ledger["recovery_done"] is True
        assert ledger["pending"] == {}
        assert ledger["last_receipt"]["root_run_id"] == root_id
        recovered = [e for e in traces.read(session) if e["kind"] == "session.closed"]
        assert len(recovered) == 1 and recovered[0]["payload"]["run_id"] == root_id
        receipt = httpx.get(runtime_url + f"/internal/runtime/sessions/{session}/prompts/reconcile", params={
            "idempotency_key": "original-crash-prompt", "content_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
        assert receipt.json()["run_id"] == root_id
        if disabled:
            assert httpx.get(receipt_url, headers=agent_headers).status_code == 401
        else:
            assert httpx.get(receipt_url, headers=agent_headers).json()["run"]["status"] == "interrupted"
        now[0] += 31
        delivery.run_once()
        assert len(calls) == 2  # recovery did not call the Provider at all
    finally:
        delivery.close()
        kill(process)
        release.set()
        if collector:
            collector.join(5)
        provider.shutdown()
