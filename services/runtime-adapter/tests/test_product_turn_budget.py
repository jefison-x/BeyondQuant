from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.research_request_gate import RequestGateBlocked, RequestGateProxy, ResearchRequestGate
from packages.contracts.product_turn_request import product_turn_limits, product_turn_profile


def _gate():
    return ResearchRequestGate(product_turn_limits(), execution_profile=product_turn_profile(),
        request_id="product-turn-test")


def _body(**changes):
    value = {"model": "deepseek-v4.1-flash", "max_tokens": 8,
             "messages": [{"role": "user", "content": "synthetic only"}]}
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


def _tools_with_payload_bytes(target: int):
    from app.research_request_gate import _tool_payload_bytes
    base = [{"type": "function", "function": {"name": "mcp__byq__byq_research_get", "description": ""}}]
    pad = target - _tool_payload_bytes({"tools": base})
    assert pad >= 0
    return [{"type": "function", "function": {"name": "mcp__byq__byq_research_get", "description": "d" * pad}}]


def test_product_turn_profile_is_closed_and_limits_are_normative():
    # ADR-0106 accepted values.
    assert product_turn_profile()["profile_id"] == "product-turn.v1"
    limits = product_turn_limits()
    assert limits == {
        "max_provider_calls": 16, "max_attempts": 16, "max_concurrent": 1,
        "max_input_bytes": 262144, "max_total_input_bytes": 4194304,
        "max_output_tokens": 8192, "max_total_output_tokens": 131072,
        "max_tool_payload_bytes": 131072, "max_total_tool_payload_bytes": 1048576,
        "max_tool_calls": 16, "deadline_ms": 180000,
    }
    # The ordinary gate accepts the product-turn profile in continuation mode.
    gate = _gate()
    assert gate.continuation_mode is True and gate.product_turn is True


def test_product_turn_overlay_binds_only_closed_go_chat_route():
    from app.continuation_budget import create_acp_product_budget_overlay
    provider_session_id = "11111111-2222-4333-8444-555555555555"
    overlay = json.loads(create_acp_product_budget_overlay(
        proxy_base_url="http://172.31.7.9:41337", provider_session_id=provider_session_id,
        provider="opencode-go-chat", model="deepseek-v4.1-flash").decode())
    # Exactly two entries: the single authorized Go chat route plus the ADR-0106
    # count-only tool guard (no continuation reservation, no web-tool disabling).
    assert len(overlay) == 2 and overlay[0]["id"] == "llm-pi-ai"
    providers = overlay[0]["config"]["providers"]
    assert set(providers) == {"opencode-go-chat"}
    chat = providers["opencode-go-chat"]
    assert chat["baseURL"] == "http://172.31.7.9:41337"
    assert chat["retryPolicy"] == {"mode": "normal", "maxRetries": 0}
    assert [m["id"] for m in chat["models"]] == ["deepseek-v4.1-flash"]
    entry = overlay[1]["insert"][0]
    assert entry["id"] == "byq-continuation-budget"
    assert entry["name"] == "file:///opt/byq/runtime/byq-continuation-budget.js"
    guard = entry["config"]
    # The START frame carries the PRE-injection overlay: exactly identity +
    # limits, and never a journalPath (the Adapter injects that into the
    # on-disk patch from the workspace-bound session home).
    assert set(guard) == {"guardMode", "deadlineEpochMs", "executionProfile", "requestLimits"}
    assert guard["guardMode"] == "count-only"
    assert guard["executionProfile"]["profile_id"] == "product-turn.v1"
    assert guard["executionProfile"]["profile_version"] == 1
    assert guard["requestLimits"] == product_turn_limits()
    # No silent provider/model switch.
    for bad in ({"provider": "opencode-zen-chat", "model": "deepseek-v4.1-flash"},
                {"provider": "opencode-go-chat", "model": "deepseek-v4-pro"}):
        with pytest.raises(ValueError):
            create_acp_product_budget_overlay(
                proxy_base_url="http://172.31.7.9:41337", provider_session_id=provider_session_id, **bad)


def test_product_turn_gate_blocks_over_cap_before_any_upstream_post():
    captured = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers.get("content-length", "0")))))
            body = b"{}"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    proxy = RequestGateProxy(_gate(), "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = f"http://127.0.0.1:{provider.server_port}"
    proxy.__enter__()
    try:
        # tool-payload cap 131072 -> 131073 refused before any upstream post
        blocked = httpx.post(proxy.base_url + "/chat/completions",
            content=_body(tools=_tools_with_payload_bytes(131073)), timeout=3)
        assert blocked.status_code == 429
        assert captured == []  # posts=0
        # per-call input cap 262144 -> 262145 refused
        base = len(_body(messages=[{"role": "user", "content": ""}]))
        big = _body(messages=[{"role": "user", "content": "x" * (262145 - base)}])
        gate2 = _gate()
        with pytest.raises(RequestGateBlocked, match="input_bytes_limit"):
            gate2.before_request(big)
    finally:
        proxy.close()
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=2)
