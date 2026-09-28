"""Opt-in real-process qualification for the pinned DSH foreground delegate.

Run inside the locked 0.1.5rc1 candidate image with
``BYQ_DSH_REAL_PROCESS_TEST=1``. The test uses only loopback synthetic services.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

import pytest


OPT_IN = os.environ.get("BYQ_DSH_REAL_PROCESS_TEST") == "1"
DELEGATE_TOOL = "byq_delegate_market_research"


def _product_mcp_tools(composition: Path) -> list[str]:
    names = set()
    for line in composition.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*-\s+mcp__byq__(?P<name>[A-Za-z0-9_]+)\s*$", line)
        if match:
            names.add(match.group("name"))
    if not names:
        raise AssertionError("locked Product composition has no BYQ MCP tools")
    return sorted(names)


def _sse(payloads: list[dict]) -> bytes:
    body = "".join(f"data: {json.dumps(item, separators=(',', ':'))}\n\n" for item in payloads)
    return (body + "data: [DONE]\n\n").encode()


def _servers(composition: Path, *, block_child: bool = False):
    state = {
        "mcp_methods": [],
        "mcp_calls": [],
        "provider_requests": [],
        "block_child": block_child,
        "child_request_started": threading.Event(),
        "child_response_release": threading.Event(),
        "child_response_finished": threading.Event(),
        "child_response_written": None,
        "notifications": [],
        "condition": threading.Condition(),
    }

    class McpHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            state["mcp_methods"].append(body.get("method"))
            if "id" not in body:
                self.send_response(202)
                self.end_headers()
                return
            method = body.get("method")
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "byq-loopback-qualification", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{
                    "name": name,
                    "description": "loopback synthetic Product capability",
                    "inputSchema": {"type": "object", "properties": {
                        "idempotency_key": {"type": "string"}}},
                } for name in _product_mcp_tools(composition)]}
            elif method == "tools/call":
                state["mcp_calls"].append(body.get("params"))
                result = {"content": [{"type": "text", "text": json.dumps({"status": "ok"})}]}
            else:
                result = {"tools": []}
            encoded = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    class ProviderHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            messages = body.get("messages", [])
            has_tool_result = any(item.get("role") == "tool" for item in messages)
            tool_names = {
                item["function"]["name"]
                for item in body.get("tools", [])
                if isinstance(item, dict) and isinstance(item.get("function"), dict)
                and isinstance(item["function"].get("name"), str)
            }
            state["provider_requests"].append({"tool_names": sorted(tool_names),
                                               "has_tool_result": has_tool_result})
            is_child_request = not has_tool_result and DELEGATE_TOOL not in tool_names
            if DELEGATE_TOOL in tool_names and not has_tool_result:
                payloads = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {"tool_calls": [{
                        "index": 0, "id": "byq-foreground-child-call", "type": "function",
                        "function": {"name": DELEGATE_TOOL,
                                     "arguments": json.dumps({"description": "synthetic qualification",
                                                              "prompt": "Return the fixed synthetic child answer."})},
                    }]}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                ]
            elif not has_tool_result:
                state["child_request_started"].set()
                if state["block_child"]:
                    state["child_response_release"].wait(timeout=25)
                payloads = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {"content": "Synthetic child research complete."},
                                  "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 3, "completion_tokens": 4}},
                ]
            else:
                payloads = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {"content": "Synthetic root answer."},
                                  "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 5, "completion_tokens": 6}},
                ]
            encoded = _sse(payloads)
            try:
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                if is_child_request:
                    state["child_response_written"] = True
            except OSError:
                if is_child_request:
                    state["child_response_written"] = False
            finally:
                if is_child_request:
                    state["child_response_finished"].set()

    mcp = ThreadingHTTPServer(("127.0.0.1", 0), McpHandler)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    mcp.daemon_threads = True
    provider.daemon_threads = True
    threads = [threading.Thread(target=server.serve_forever, daemon=True)
               for server in (mcp, provider)]
    for thread in threads:
        thread.start()
    return state, mcp, provider, threads


def _wait_for(predicate, *, timeout: float, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(message)


@pytest.mark.skipif(not OPT_IN, reason="requires the isolated DSH 0.1.5rc1 candidate image")
def test_locked_product_foreground_delegate_starts_and_finishes_real_child(monkeypatch, tmp_path):
    assert version("deepseek-harness-sdk") == "0.1.5rc1"
    assert version("deepseek-harness-runtime-bin") == "0.1.5rc1"
    assert os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE") == "dsh-0.1.5rc1"
    assert os.environ.get("BYQ_DSH_PROCESS_OWNERSHIP") == "root-turn"
    composition = Path(os.environ.get("BYQ_DSH_COMPOSITION", "/opt/byq/profiles/byq-product.patch.yml"))
    assert composition == Path("/opt/byq/profiles/byq-product.patch.yml")
    assert Path(os.environ.get("BYQ_DSH_COMPOSITION_IDENTITY",
                              "/opt/byq/profiles/byq-product.identity.json")) == Path(
                                  "/opt/byq/profiles/byq-product.identity.json")

    state, mcp, provider, server_threads = _servers(composition)
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "dsh-sessions"))
    monkeypatch.setenv("BYQ_MCP_URL", f"http://127.0.0.1:{mcp.server_port}/mcp/v1")
    monkeypatch.setenv("BYQ_MCP_TOKEN", "synthetic-loopback-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-loopback-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{provider.server_port}")

    from app.runtime import RuntimeAdapter, SessionStatus

    adapter = RuntimeAdapter()
    try:
        readiness = adapter.readiness()
        assert readiness["runtime_adapter"] == "ready"
        assert readiness["process_ownership"] == "one-per-root-turn"
        assert readiness["composition"] == str(composition)
        assert readiness["plugin_profile"] == "byq-product-candidate"
        composition_text = Path(readiness["composition"]).read_text(encoding="utf-8")
        assert f"toolName: {DELEGATE_TOOL}" in composition_text
        assert _product_mcp_tools(composition)

        original_on_notification = adapter._on_notification

        def observe_notification(record, notification, **kwargs):
            method = getattr(notification, "method", None)
            payload = getattr(notification, "payload", None)
            if method in {"subagent.started", "subagent.finished"} and isinstance(payload, dict):
                with state["condition"]:
                    state["notifications"].append((method, dict(payload)))
                    state["condition"].notify_all()
            original_on_notification(record, notification, **kwargs)

        adapter._on_notification = observe_notification

        suffix = uuid.uuid4().hex
        session_id = "dsh015-child-" + suffix
        trace_id = "trace-" + suffix
        adapter.create_session(session_id, trace_id, "qualification-owner", "workspace-qualification")
        root_run_id = adapter.submit_prompt(session_id, "Run the synthetic delegated market research turn.")
        record = adapter._get(session_id)
        _wait_for(lambda: record.status == SessionStatus.IDLE, timeout=45,
                  message="locked Product foreground delegate did not finish")

        assert state["child_request_started"].is_set(), "the real child never reached the loopback provider"
        assert state["mcp_methods"].count("initialize") >= 1
        assert state["mcp_methods"].count("tools/list") >= 1
        assert any(DELEGATE_TOOL in request["tool_names"] and not request["has_tool_result"]
                   for request in state["provider_requests"]), "root did not see the Product delegate tool"
        assert any(request["has_tool_result"] for request in state["provider_requests"]), (
            "root did not receive the foreground child result")

        # The SDK's real notifications are retained only in this test capture;
        # the public trace remains a normalized Product lifecycle projection.
        with state["condition"]:
            notifications = list(state["notifications"])
        started = [payload for method, payload in notifications if method == "subagent.started"]
        finished = [payload for method, payload in notifications if method == "subagent.finished"]
        assert len(started) == len(finished) == 1
        assert started[0]["childSessionId"] == finished[0]["childSessionId"]
        assert started[0]["parentSessionId"] == finished[0]["parentSessionId"] == record.runtime_session_id
        assert record.process_closed is True, "the owned root DSH harness was not closed after the turn"
        terminals = [event for event in record.history
                     if event["kind"] in {"session.result", "session.failed", "session.cancelled"}
                     and event["payload"].get("run_id") == root_run_id]
        assert [event["kind"] for event in terminals] == ["session.result"]
        assert not any(event["kind"].startswith("subagent.") for event in record.history)
        assert state["mcp_calls"] == []
    finally:
        adapter.close()
        for server in (mcp, provider):
            server.shutdown()
            server.server_close()
        for thread in server_threads:
            thread.join(timeout=2)


@pytest.mark.parametrize("abort_mode", ["timeout", "hard_cancel"])
@pytest.mark.skipif(not OPT_IN, reason="requires the isolated DSH 0.1.5rc1 candidate image")
def test_blocked_foreground_child_cannot_publish_late_success(monkeypatch, tmp_path, abort_mode):
    assert version("deepseek-harness-sdk") == "0.1.5rc1"
    assert version("deepseek-harness-runtime-bin") == "0.1.5rc1"
    composition = Path(os.environ.get("BYQ_DSH_COMPOSITION", "/opt/byq/profiles/byq-product.patch.yml"))
    assert composition == Path("/opt/byq/profiles/byq-product.patch.yml")

    state, mcp, provider, server_threads = _servers(composition, block_child=True)
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "dsh-sessions"))
    monkeypatch.setenv("BYQ_MCP_URL", f"http://127.0.0.1:{mcp.server_port}/mcp/v1")
    monkeypatch.setenv("BYQ_MCP_TOKEN", "synthetic-loopback-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-loopback-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{provider.server_port}")
    monkeypatch.setenv("BYQ_DSH_SUBAGENT_TIMEOUT_SECONDS", "1" if abort_mode == "timeout" else "30")
    monkeypatch.setenv("BYQ_DSH_NO_PROGRESS_TIMEOUT_SECONDS", "2")

    from app.runtime import RuntimeAdapter, SessionStatus

    adapter = RuntimeAdapter()
    try:
        assert adapter.readiness()["plugin_profile"] == "byq-product-candidate"
        record_notifications = state["notifications"]
        original_on_notification = adapter._on_notification

        def observe_notification(record, notification, **kwargs):
            method = getattr(notification, "method", None)
            payload = getattr(notification, "payload", None)
            if method in {"subagent.started", "subagent.finished"} and isinstance(payload, dict):
                with state["condition"]:
                    record_notifications.append((method, dict(payload)))
                    state["condition"].notify_all()
            original_on_notification(record, notification, **kwargs)

        adapter._on_notification = observe_notification
        suffix = uuid.uuid4().hex
        session_id = "dsh015-blocked-child-" + suffix
        adapter.create_session(session_id, "trace-" + suffix, "qualification-owner", "workspace-qualification")
        run_id = adapter.submit_prompt(session_id, "Run the synthetic delegated market research turn.")
        record = adapter._get(session_id)
        assert state["child_request_started"].wait(timeout=20), "the real child never reached the blocked provider"
        with state["condition"]:
            started = [payload for method, payload in record_notifications if method == "subagent.started"]
        assert len(started) == 1, "the blocked provider call was not preceded by a real child-start notification"
        assert not state["child_response_finished"].is_set(), "the child provider response was not held back"

        if abort_mode == "timeout":
            _wait_for(lambda: record.status == SessionStatus.FAILED, timeout=8,
                      message="the dedicated foreground-child inactivity timeout did not fail the root")
            expected_terminal = "session.failed"
            terminals = [event for event in record.history if event["kind"] == expected_terminal]
            assert len(terminals) == 1
            assert terminals[0]["payload"].get("code") == "runtime-subagent-timeout"
        else:
            cancelled = adapter.cancel_session(session_id, "hard")
            assert cancelled["status"] == SessionStatus.INTERRUPTED
            expected_terminal = "session.cancelled"
            terminals = [event for event in record.history if event["kind"] == expected_terminal]
            assert len(terminals) == 1
            assert terminals[0]["payload"].get("mode") == "hard"

        _wait_for(lambda: record.process_closed, timeout=10,
                  message="the owned root harness stayed open after abort")
        state["child_response_release"].set()
        assert state["child_response_finished"].wait(timeout=5), "the synthetic late provider response did not finish"
        time.sleep(1.2)
        terminals = [event for event in record.history
                     if event["kind"] in {"session.result", "session.failed", "session.cancelled"}
                     and event["payload"].get("run_id") == run_id]
        assert [event["kind"] for event in terminals] == [expected_terminal]
        assert not any(request["has_tool_result"] for request in state["provider_requests"]), (
            "the closed root received a child result after its terminal event")
        assert record.process_closed is True
    finally:
        state["child_response_release"].set()
        adapter.close()
        for server in (mcp, provider):
            server.shutdown()
            server.server_close()
        for thread in server_threads:
            thread.join(timeout=2)
