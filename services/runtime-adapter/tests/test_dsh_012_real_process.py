from __future__ import annotations

import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

import pytest
from deepseek_harness.errors import JsonRpcError, TransportClosedError

from app.runtime import RuntimeAdapter, SessionStatus
from pathlib import Path


pytestmark = pytest.mark.skipif(
    version("deepseek-harness-sdk") != "0.1.2rc1"
    or os.environ.get("BYQ_DSH_REAL_PROCESS_TEST") != "1",
    reason="requires the isolated 0.1.2 candidate stack and real BYQ MCP",
)


@pytest.mark.parametrize("route,model", [
    ("opencode-go-chat", "deepseek-v4-pro"),
    ("opencode-go-responses", "gpt-5.6-luna"),
    ("opencode-go-messages", "minimax-m3"),
])
def test_go_routing_headers_on_official_protocol_and_permanent_rejection(monkeypatch, tmp_path, route, model):
    """Actual pinned binary and production-derived profile, loopback provider only."""
    captured = []
    class Mcp(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            if "id" not in body:
                self.send_response(202)
                self.end_headers()
                return
            result = ({"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                "serverInfo": {"name": "synthetic", "version": "1"}}
                if body.get("method") == "initialize" else {"tools": []})
            encoded = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    class Rejection(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            captured.append((self.headers.get("x-opencode-session"), self.headers.get("user-agent")))
            body = b'{"error":{"message":"synthetic invalid request","type":"invalid_request_error"}}'
            self.send_response(400)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Rejection)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    mcp = ThreadingHTTPServer(("127.0.0.1", 0), Mcp)
    mcp_thread = threading.Thread(target=mcp.serve_forever, daemon=True)
    mcp_thread.start()
    monkeypatch.setenv("BYQ_MCP_URL", f"http://127.0.0.1:{mcp.server_port}/mcp/v1")
    monkeypatch.setenv("BYQ_MCP_TOKEN", "synthetic-only")
    adapter = None
    try:
        source = Path(os.environ["BYQ_DSH_COMPOSITION"]).read_text()
        assert source.count("x-opencode-session:") == 3
        patch = tmp_path / "provider-wire.yml"
        patch.write_text(source.replace("https://opencode.ai/zen/go/v1", f"http://127.0.0.1:{server.server_port}/v1"))
        adapter = RuntimeAdapter()
        adapter._composition = patch
        monkeypatch.setattr(adapter, "_resolve_model", lambda *args, **kwargs: {
            "provider": route, "model": model, "api_key": "synthetic-only"})
        session_id = "go-wire-" + uuid.uuid4().hex
        adapter.create_session(session_id, "synthetic-provider-trace", "synthetic-owner", "synthetic-workspace")
        record = adapter._get(session_id)
        adapter.submit_prompt(session_id, "Synthetic provider rejection check only.")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            # State and terminal event are published under the same session lock.
            # An unlocked active_run read can see the state before history is appended.
            with record.lock:
                if record.active_run is None:
                    break
            time.sleep(0.02)
        assert record.active_run is None
        assert record.status == SessionStatus.FAILED
        assert len(captured) == 1, "a permanent 400 must not be retried"
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "beyondquant:provider-session:" + session_id))
        assert captured[0][0] == expected
        assert captured[0][1] and "python" not in captured[0][1].lower()
        failures = [event["payload"] for event in record.history if event["kind"] == "session.failed"]
        assert failures, "terminal failure must be published before run completion is observed"
        assert failures[-1]["code"] == "model-request-rejected"
        assert failures[-1]["retryable"] is False
        assert "synthetic invalid request" not in json.dumps(record.history)
    finally:
        if adapter is not None:
            adapter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        mcp.shutdown()
        mcp.server_close()
        mcp_thread.join(timeout=2)


class ScriptedProvider(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append(body)
        payloads = [
            {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": "候选运行正常"}, "finish_reason": None}]},
            {
                "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 6},
            },
        ]
        encoded = "".join(
            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n" for payload in payloads
        ) + "data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(encoded.encode())))
        self.end_headers()
        self.wfile.write(encoded.encode())

    def log_message(self, _format: str, *args: object) -> None:
        return


@pytest.mark.parametrize("tool_name,arguments", [
    ("byq_agent_run_start", {"role_id": "quant_orchestrator", "idempotency_key": "synthetic-registration-probe"}),
    *[(name, arguments) for name in ("byq_strategy_validate", "byq_ml_strategy_create")
      for arguments in (
          {},
          {"task_id": "synthetic-task", "idempotency_key": "synthetic-domain-probe",
           "strategy": {"nested": {"中文": [None, True, 1, 1.25, "合成\\n测试"]}}},
          {"task_id": "synthetic-task", "idempotency_key": "synthetic-domain-large",
           "strategy": {"script": "合成" * 25000}},
      )],
])
def test_official_registration_notification_has_exact_request_identity(monkeypatch, tool_name, arguments) -> None:
    """Observation-only probe: no owner, invalid domain schemas, no authorized write.

    This proves transport fidelity, not admission, accounting, or native loop stop.
    """

    class RegistrationProvider(ScriptedProvider):
        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            has_result = any(item.get("role") == "tool" for item in body.get("messages", []))
            delta = {"content": "合成接口核查完成"} if has_result else {
                "tool_calls": [{"index": 0, "id": "synthetic-registration-call", "type": "function",
                                "function": {"name": "mcp__byq__" + tool_name,
                                             "arguments": json.dumps(arguments)}}],
            }
            chunks = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if has_result else "tool_calls"}]},
            ]
            encoded = ("".join(f"data: {json.dumps(item)}\n\n" for item in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), RegistrationProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "scripted-test-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    adapter = RuntimeAdapter()
    captured = []
    observations = []
    original = adapter._on_notification

    def capture(record, notification, **kwargs):
        payload = getattr(notification, "payload", {})
        event = payload.get("event", {})
        if event.get("type") == "tool/call":
            captured.append(event.get("data", {}))
            observations.append(adapter._compatibility.observe(notification, root_session_id=record.runtime_session_id))
        original(record, notification, **kwargs)

    adapter._on_notification = capture
    session_id = f"binding-probe-{uuid.uuid4().hex}"
    try:
        adapter.create_session(session_id, "binding-probe-trace")
        adapter.submit_prompt(session_id, "合成接口核查，不执行研究")
        record = adapter._get(session_id)
        deadline = time.monotonic() + 20
        while (record.status == SessionStatus.RUNNING or record.process_closing) and time.monotonic() < deadline:
            time.sleep(0.05)
        if adapter._root_scoped and tool_name != "byq_agent_run_start":
            assert record.status == SessionStatus.FAILED
            assert any(event["payload"].get("code") == "domain-call-reference-unproven" for event in record.history)
            assert record.process_closed
        else:
            assert record.status == SessionStatus.IDLE
        calls = [item for item in captured if item.get("name") == "mcp__byq__" + tool_name]
        assert len(calls) == 1
        assert isinstance(calls[0].get("arguments"), str)
        assert json.loads(calls[0]["arguments"]) == arguments
        expected_keys = [arguments["idempotency_key"]] if tool_name == "byq_agent_run_start" else []
        assert [item.registration_key for item in observations if item.registration_key] == expected_keys
    finally:
        adapter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("current", ["继续", "沪深300近三年周频双均线，凯利仓位", "改为中证500近一年月频研究"])
def test_real_generation_recovery_preserves_subject_and_current_input(monkeypatch, current):
    """Real process + MCP, scripted model; asserts transport, not model reasoning."""
    ScriptedProvider.requests.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "scripted-test-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    subject = "沪深300近三年周频双均线，凯利仓位"
    session_id = f"r2-{uuid.uuid4().hex}"
    recovery = {
        "schema_version": "conversation-recovery.v2", "session_id": session_id,
        "trace_id": "r2-trace", "status": "resolved",
        "unanswered_turn": {"message_id": "original-request", "content": subject},
        "failure": {"sequence": 9, "run_id": "failed-run", "code": "runtime-subagent-timeout"},
    }
    adapter = RuntimeAdapter()
    try:
        adapter.create_session(session_id, "r2-trace", initial_sequence=9, conversation_recovery=recovery)
        record = adapter._get(session_id)
        assert record.runtime_session_id != session_id
        adapter.submit_prompt(session_id, current, idempotency_key="persisted-current-message")
        deadline = time.monotonic() + 20
        while record.status == SessionStatus.RUNNING and time.monotonic() < deadline:
            time.sleep(0.05)
        assert record.status == SessionStatus.IDLE
        assert len(ScriptedProvider.requests) == 1
        messages = ScriptedProvider.requests[0]["messages"]
        wire = json.dumps(messages, ensure_ascii=False)
        assert wire.count(subject) == 1
        assert "runtime-subagent-timeout" in wire
        assert "BYQ_TASK_RECOVERY" in wire
        if current != subject:
            assert current in wire
        assert record.pending_conversation_recovery is None
    finally:
        adapter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_candidate_mcp_auth_failure_blocks_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "u4-invalid-mcp-token-must-not-leak"
    monkeypatch.setenv("BYQ_MCP_TOKEN", sentinel)
    adapter = RuntimeAdapter()
    try:
        with pytest.raises((JsonRpcError, TransportClosedError, TimeoutError)) as failure:
            adapter.create_session(f"u4-auth-{uuid.uuid4().hex}", "u4-auth-failure")
        assert sentinel not in str(failure.value)
        assert adapter._sessions == {}
    finally:
        adapter.close()


def test_candidate_real_process_initializes_mcp_and_exposes_only_product_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ScriptedProvider.requests.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "scripted-test-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    adapter = RuntimeAdapter()
    raw_diagnostics: list[dict[str, object]] = []
    original_notification_handler = adapter._on_notification

    def capture_notification(record: object, notification: object, **kwargs: object) -> None:
        payload = getattr(notification, "payload", None)
        event = payload.get("event") if isinstance(payload, dict) else None
        if isinstance(event, dict) and event.get("type") in {"step/end", "turn/end", "error"}:
            raw_diagnostics.append(event)
        original_notification_handler(record, notification, **kwargs)

    adapter._on_notification = capture_notification  # type: ignore[method-assign]
    session_id = f"u4-real-{uuid.uuid4().hex}"
    try:
        assert adapter.create_session(session_id, "u4-real-process")["status"] == SessionStatus.READY
        adapter.submit_prompt(session_id, "只回复候选运行正常")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if adapter.describe_session(adapter._get(session_id))["status"] != SessionStatus.RUNNING:
                break
            time.sleep(0.05)
        final_status = adapter.describe_session(adapter._get(session_id))["status"]
        record = adapter._get(session_id)
        diagnostics = {
            "history": record.history[-20:],
            "raw_runtime_events": raw_diagnostics[-20:],
            "stderr": list(record.harness.client._stderr_lines)[-80:],
        }
        assert final_status == SessionStatus.IDLE, json.dumps(
            diagnostics, ensure_ascii=False, indent=2,
        )
        assert len(ScriptedProvider.requests) == 1
        request = ScriptedProvider.requests[0]
        tool_names = {
            tool["function"]["name"]
            for tool in request.get("tools", [])
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }
        delegates = {
            "byq_delegate_market_research", "byq_delegate_factor_research",
            "byq_delegate_strategy_research", "byq_delegate_backtest_analysis",
            "byq_delegate_ml_research",
        }
        assert delegates <= tool_names
        assert any(name.startswith("mcp__byq__") for name in tool_names)
        assert not tool_names.intersection({
            "bash", "pwsh", "jobs", "fs", "fs_search", "str_replace_editor",
            "subagent", "subagent_fork", "workflow", "todo_write", "goal", "ralph",
            "web_fetch", "list_agents", "send_message",
        })
        messages = request.get("messages")
        assert isinstance(messages, list)
        assert "Asia/Shanghai" in json.dumps(messages, ensure_ascii=False)
        public = [
            event for event in adapter._get(session_id).history
            if event["kind"] == "agent.output.delta"
        ]
        assert "".join(event["payload"]["delta"] for event in public) == "候选运行正常"
    finally:
        try:
            if adapter.describe_session(adapter._get(session_id))["status"] in SessionStatus.ACTIVE_PROMPT:
                adapter.cancel_session(session_id, "hard")
            else:
                adapter.release_session(session_id)
        except KeyError:
            pass
        adapter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
