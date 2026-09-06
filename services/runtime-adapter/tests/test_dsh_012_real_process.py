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


pytestmark = pytest.mark.skipif(
    version("deepseek-harness-sdk") != "0.1.2rc1"
    or os.environ.get("BYQ_DSH_REAL_PROCESS_TEST") != "1",
    reason="requires the isolated 0.1.2 candidate stack and real BYQ MCP",
)


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
