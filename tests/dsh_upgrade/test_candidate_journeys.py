"""Real 0.1.2rc1 DSH delegate journeys with a deterministic provider.

Run only inside the isolated candidate image with a live BYQ MCP. The provider
controls model output, but DSH loads the real profile, creates the real child
agent and executes the real MCP tool.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

import pytest

try:
    from app.runtime import RuntimeAdapter, SessionStatus
except ImportError:
    pytest.skip("Runtime Adapter application is not installed", allow_module_level=True)


pytestmark = pytest.mark.skipif(
    version("deepseek-harness-sdk") != "0.1.2rc1"
    or os.environ.get("BYQ_DSH_REAL_PROCESS_TEST") != "1",
    reason="requires the isolated 0.1.2 candidate image and live BYQ MCP",
)

DELEGATE_FORBIDDEN = {
    "byq_delegate_market_research": "mcp__byq__byq_factor_compute",
    "byq_delegate_factor_research": "web_search",
    "byq_delegate_strategy_research": "mcp__byq__byq_backtest_task_execute",
    "byq_delegate_backtest_analysis": "mcp__byq__byq_strategy_version_create",
    "byq_delegate_ml_research": "mcp__byq__byq_web_evidence_create",
}
ALL_DELEGATES = frozenset(DELEGATE_FORBIDDEN)
CONTEXT_TOOL = "mcp__byq__byq_agent_context"


def _event_stream(*payloads: dict[str, object]) -> bytes:
    body = "".join(
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n" for payload in payloads
    )
    return (body + "data: [DONE]\n\n").encode()


def _text_response(text: str) -> bytes:
    return _event_stream(
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
        {
            "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _tool_response(name: str, call_id: str, arguments: dict[str, object] | None = None) -> bytes:
    return _event_stream(
        {
            "choices": [{
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "tool_calls": [{
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments or {}, separators=(",", ":")),
                        },
                    }],
                },
                "finish_reason": None,
            }],
        },
        {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


class DelegateProvider(BaseHTTPRequestHandler):
    target = ""
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        self.__class__.requests.append(request)
        tools = {
            item["function"]["name"]
            for item in request.get("tools", [])
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        }
        messages = request.get("messages", [])
        has_tool_result = any(
            isinstance(item, dict) and item.get("role") == "tool" for item in messages
        )
        if self.target in tools:
            payload = _text_response("root-ok") if has_tool_result else _tool_response(
                self.target,
                "call_delegate",
                {
                    "prompt": "read the trusted BYQ context",
                    "description": "bounded qualification probe",
                },
            )
        else:
            assert CONTEXT_TOOL in tools
            assert not ALL_DELEGATES.intersection(tools)
            assert DELEGATE_FORBIDDEN[self.target] not in tools
            payload = _text_response("child-ok") if has_tool_result else _tool_response(
                CONTEXT_TOOL, "call_context"
            )
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *args: object) -> None:
        return


@pytest.mark.parametrize("delegate", sorted(ALL_DELEGATES))
def test_each_delegate_executes_its_real_mcp_ceiling(
    delegate: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    DelegateProvider.target = delegate
    DelegateProvider.requests.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), DelegateProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "u5-scripted-test-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    adapter = RuntimeAdapter()
    session_id = f"u5-{uuid.uuid4().hex}"
    try:
        assert adapter.create_session(session_id, f"u5-{delegate}")["status"] == SessionStatus.READY
        adapter.submit_prompt(session_id, f"invoke {delegate}")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if adapter.describe_session(adapter._get(session_id))["status"] != SessionStatus.RUNNING:
                break
            time.sleep(0.05)
        record = adapter._get(session_id)
        assert record.status == SessionStatus.IDLE, {
            "history": record.history[-30:],
            "stderr": list(record.harness.client._stderr_lines)[-80:],
        }
        assert len(DelegateProvider.requests) == 4
        assert any(
            CONTEXT_TOOL in {
                item["function"]["name"]
                for item in request.get("tools", [])
                if isinstance(item, dict) and isinstance(item.get("function"), dict)
            }
            and any(
                isinstance(message, dict)
                and message.get("role") == "tool"
                and "beyondquant-mcp" in json.dumps(message)
                for message in request.get("messages", [])
            )
            for request in DelegateProvider.requests
        )
        public = [event for event in record.history if event["kind"] == "agent.output.delta"]
        assert "".join(event["payload"]["delta"] for event in public) == "root-ok"
        assert "child-ok" not in json.dumps(public, ensure_ascii=False)
    finally:
        try:
            record = adapter._get(session_id)
            if record.status in SessionStatus.ACTIVE_PROMPT:
                adapter.cancel_session(session_id, "hard")
            else:
                adapter.release_session(session_id)
        except KeyError:
            pass
        adapter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
