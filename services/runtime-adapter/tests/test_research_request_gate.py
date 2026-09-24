"""ADR-0086 request-scoped provider gate: fail-able contract + boundary tests.

These are host tests (no carrier, no real provider). They prove the pure budget
decision blocks each dimension, that the gate records provider-reported ACTUAL
usage (never the declared ceiling), and that the proxy refuses an over-budget,
over-limit or late request BEFORE/INSTEAD OF forwarding it.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.research_request_gate import (
    RequestGateBlocked,
    RequestGateProxy,
    ResearchRequestGate,
    build_request_gate,
    declared_output_tokens,
    forwarded_request_headers,
    parse_response_usage,
    request_role,
    resolve_declared_output_tokens,
)
from packages.contracts.research_request_budget import (
    JUDGMENT_STAGES,
    REQUEST_PROFILES,
    request_budget_decision,
    stage_request_limits,
    validate_request_budget,
)


def _root_body(**overrides) -> bytes:
    body = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "judge"}],
        "tools": [{"type": "function", "function": {"name": "byq_research_judgment_turn"}}],
        "max_tokens": 100,
    }
    body.update(overrides)
    return json.dumps(body).encode()


def _child_body(**overrides) -> bytes:
    body = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "judge"}],
        "tools": [{"type": "function", "function": {"name": "mcp__byq__byq_research_get"}}],
        "max_tokens": 100,
    }
    body.update(overrides)
    return json.dumps(body).encode()


def _short_deadline_gate(ms: int) -> ResearchRequestGate:
    limits = stage_request_limits("strategy_draft", request_id="byq-judgment-short",
                                  started_at_ms=int(time.time() * 1000))
    limits = validate_request_budget({**limits, "deadline_at_ms": int(time.time() * 1000) + ms})
    return ResearchRequestGate(limits)


def _sse_usage(prompt: int, completion: int) -> bytes:
    chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}
    return (f"data: {json.dumps(chunk)}\n\n" + "data: [DONE]\n\n").encode()


def test_limits_are_closed_per_stage_and_caller_override_fails_closed():
    # Every judgment stage maps to its OWN named profile with explicit limits.
    profile_ids = {
        stage: stage_request_limits(stage, request_id="byq-judgment-a",
                                    started_at_ms=1000)["profile_id"]
        for stage in JUDGMENT_STAGES}
    assert len(set(profile_ids.values())) == len(JUDGMENT_STAGES)
    assert all(pid in REQUEST_PROFILES for pid in profile_ids.values())
    limits = stage_request_limits("strategy_draft", request_id="byq-judgment-a",
                                  started_at_ms=1000)
    assert limits["max_provider_calls"] == REQUEST_PROFILES[limits["profile_id"]]["max_provider_calls"]
    assert limits["evidence"]
    # Unknown stage / unknown profile / caller override all fail closed.
    with pytest.raises(ValueError):
        stage_request_limits("waiting_for_data", request_id="x", started_at_ms=1)
    with pytest.raises(ValueError):
        stage_request_limits("strategy_draft", request_id="x", started_at_ms=1,
                             profile="final-selection-bounded.v1")
    with pytest.raises(ValueError):
        validate_request_budget({**limits, "profile_id": "unknown-profile.v1"})
    # A forged/raised budget cannot pass even with a valid profile id.
    with pytest.raises(ValueError):
        validate_request_budget({**limits, "max_provider_calls": 99})
    # A missing field fails closed.
    with pytest.raises(ValueError):
        validate_request_budget({k: v for k, v in limits.items() if k != "evidence"})


def test_decision_blocks_every_dimension_and_uses_declared_max():
    limits = stage_request_limits("strategy_draft", request_id="byq-judgment-a", started_at_ms=0)
    base = {"provider_calls": 1, "input_bytes": 1, "declared_max_output_tokens": 1,
            "tool_payload_bytes": 1, "attempts": 1, "concurrent": 1,
            "now_ms": 1, "cancelled": False}
    assert request_budget_decision(limits, base)["admit"] is True
    for field, value, reason in (
        ("provider_calls", limits["max_provider_calls"] + 1, "provider_call_limit"),
        ("input_bytes", limits["max_input_bytes"] + 1, "input_bytes_limit"),
        ("declared_max_output_tokens", limits["max_output_tokens"] + 1, "output_tokens_limit"),
        ("tool_payload_bytes", limits["max_tool_payload_bytes"] + 1, "tool_payload_limit"),
        ("attempts", limits["max_attempts"] + 1, "attempt_limit"),
        ("concurrent", limits["max_concurrent"] + 1, "concurrency_limit"),
    ):
        blocked = request_budget_decision(limits, {**base, field: value})
        assert blocked["admit"] is False and blocked["reason"] == reason
    assert request_budget_decision(
        limits, {**base, "now_ms": limits["deadline_at_ms"]})["reason"] == "deadline_exceeded"
    assert request_budget_decision(
        limits, {**base, "cancelled": True})["reason"] == "cancelled"


def test_role_declared_ceiling_and_usage_parsing():
    assert request_role(json.loads(_root_body())) == "root"
    assert request_role(json.loads(_child_body())) == "child"
    assert declared_output_tokens({"max_completion_tokens": 12}) == 12
    assert declared_output_tokens({}) is None
    # Missing / invalid / conflicting declarations fail closed with a closed reason.
    assert resolve_declared_output_tokens({})[1] == "declared_output_limit_missing"
    assert resolve_declared_output_tokens({"max_tokens": 0})[1] == "declared_output_limit_invalid"
    assert resolve_declared_output_tokens({"max_tokens": True})[1] == "declared_output_limit_invalid"
    assert resolve_declared_output_tokens({"max_tokens": -1})[1] == "declared_output_limit_invalid"
    assert resolve_declared_output_tokens(
        {"max_tokens": 5, "max_completion_tokens": 6})[1] == "declared_output_limit_conflict"
    assert resolve_declared_output_tokens(
        {"max_tokens": 5, "max_completion_tokens": 5}) == (5, None)
    parsed = parse_response_usage(_sse_usage(7, 3))
    assert parsed == {"actual_input_tokens": 7, "actual_cache_read_tokens": "unknown",
                      "actual_output_tokens": 3, "usage_source": "provider_response"}
    # A non-streaming JSON body is a supported provider response shape.
    non_streaming = json.dumps({
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "x"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2}}).encode()
    assert parse_response_usage(non_streaming) == {
        "actual_input_tokens": 4, "actual_cache_read_tokens": "unknown",
        "actual_output_tokens": 2, "usage_source": "provider_response"}
    # A missing usage block is structured unknown, never the declared ceiling.
    unknown = parse_response_usage(b'data: {"choices":[]}\n\n')
    assert unknown == {"actual_input_tokens": "unknown", "actual_cache_read_tokens": "unknown",
                       "actual_output_tokens": "unknown", "usage_source": "unknown"}


def test_gate_records_declared_ceiling_and_actual_usage(tmp_path):
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a",
                              journal=tmp_path / "gate.jsonl")
    receipt = gate.before_request(_root_body(max_tokens=123))
    assert receipt["declared_max_output_tokens"] == 123
    assert "output_tokens" not in receipt
    completion = gate.complete(receipt, status=200, body=_sse_usage(11, 4))
    assert completion["forward"] is True
    assert completion["actual_input_tokens"] == 11
    assert completion["actual_output_tokens"] == 4
    assert completion["elapsed_ms"] >= 0
    rows = [json.loads(line) for line in (tmp_path / "gate.jsonl").read_text().splitlines()]
    completed = [r for r in rows if r["phase"] == "completed"][0]
    assert completed["declared_max_output_tokens"] == 123
    assert completed["actual_output_tokens"] == 4
    assert completed["usage_source"] == "provider_response"


def test_gate_is_request_scoped_and_blocks_the_fourth_call(tmp_path):
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a",
                              journal=tmp_path / "gate.jsonl")
    for _ in range(3):
        receipt = gate.before_request(_root_body())
        gate.complete(receipt, status=200, body=_sse_usage(5, 5))
    with pytest.raises(RequestGateBlocked) as error:
        gate.before_request(_root_body())
    assert error.value.reason in {"attempt_limit", "provider_call_limit"}
    fresh = build_request_gate("strategy_draft", request_id="byq-judgment-b",
                               journal=tmp_path / "gate2.jsonl")
    assert fresh.before_request(_root_body())["admitted"] is True


def test_gate_blocks_oversized_input_tool_payload_and_cancel(tmp_path):
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a",
                              journal=tmp_path / "gate.jsonl")
    with pytest.raises(RequestGateBlocked) as error:
        gate.before_request(_root_body(messages=[{"role": "user", "content": "x" * 200000}]))
    assert error.value.reason == "input_bytes_limit"
    big_tools = [{"type": "function", "function": {
        "name": "byq_research_judgment_turn", "description": "d" * 70000}}]
    with pytest.raises(RequestGateBlocked) as error:
        gate.before_request(_root_body(tools=big_tools))
    assert error.value.reason == "tool_payload_limit"
    gate.cancel()
    with pytest.raises(RequestGateBlocked) as error:
        gate.before_request(_root_body())
    assert error.value.reason == "cancelled"


def test_gate_refuses_undeclared_or_invalid_output_cap_for_root_and_child(tmp_path):
    for body in (_root_body(max_tokens=None), _child_body(max_tokens=None),
                 _root_body(max_tokens=0), _child_body(max_completion_tokens=-1),
                 _root_body(max_tokens=5, max_output_tokens=6)):
        gate = build_request_gate("strategy_draft", request_id="byq-judgment-a",
                                  journal=tmp_path / "gate.jsonl")
        with pytest.raises(RequestGateBlocked) as error:
            gate.before_request(body)
        assert error.value.reason in {
            "declared_output_limit_missing", "declared_output_limit_invalid",
            "declared_output_limit_conflict"}


def test_gate_refuses_declared_cap_above_the_profile():
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a")
    with pytest.raises(RequestGateBlocked) as error:
        gate.before_request(_root_body(max_tokens=8193))
    assert error.value.reason == "output_tokens_limit"


def test_gate_discards_output_over_the_declared_ceiling():
    gate = _short_deadline_gate(60000)
    receipt = gate.before_request(_root_body(max_tokens=4))
    completion = gate.complete(receipt, status=200, body=_sse_usage(5, 9))
    assert completion["forward"] is False and completion["reason"] == "output_tokens_exceeded"
    # ADR-0086 §3: an unprovable actual output is NOT submitted; it fails closed
    # with a structured reason (never fabricated as 0 or the declared ceiling).
    gate2 = _short_deadline_gate(60000)
    receipt2 = gate2.before_request(_root_body(max_tokens=4))
    completion2 = gate2.complete(receipt2, status=200, body=b'data: {"choices":[]}\n\n')
    assert completion2["forward"] is False
    assert completion2["reason"] == "actual_usage_unknown"
    assert completion2["actual_output_tokens"] == "unknown"


class _Upstream(BaseHTTPRequestHandler):
    hits = 0
    mode = "ok"
    delay = 0.0
    last_headers: dict = {}

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length") or "0")
        self.rfile.read(length)
        self.__class__.hits += 1
        self.__class__.last_headers = {k.lower(): v for k, v in self.headers.items()}
        if self.__class__.delay:
            time.sleep(self.__class__.delay)
        if self.__class__.mode == "over_limit":
            payload = _sse_usage(5, 999999)
        elif self.__class__.mode == "no_usage":
            payload = b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        else:
            payload = _sse_usage(5, 5)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _serve(mode="ok", delay=0.0):
    _Upstream.hits = 0
    _Upstream.mode = mode
    _Upstream.delay = delay
    _Upstream.last_headers = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(proxy: RequestGateProxy, body: bytes, headers: dict | None = None) -> int:
    request = urllib.request.Request(
        proxy.base_url + "/chat/completions", data=body, method="POST",
        headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_forwarded_headers_allowlist_excludes_internal_and_hop_by_hop():
    forwarded = forwarded_request_headers({
        "Authorization": "Bearer test-secret",
        "content-type": "application/json",
        "Accept": "text/event-stream",
        "x-byq-internal-token": "should-not-leak",
        "x-byq-runtime-judgment-token": "should-not-leak",
        "cookie": "session=should-not-leak",
        "connection": "keep-alive",
        "proxy-authorization": "should-not-leak",
    })
    assert forwarded == {"authorization": "Bearer test-secret",
                         "content-type": "application/json",
                         "accept": "text/event-stream"}


def test_proxy_forwards_only_allowlisted_provider_headers(tmp_path):
    server, upstream = _serve()
    journal = tmp_path / "gate.jsonl"
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a", journal=journal)
    with RequestGateProxy(gate, upstream) as proxy:
        assert _post(proxy, _root_body(), headers={
            "Authorization": "Bearer test-secret-value",
            "Accept": "text/event-stream",
            "x-byq-internal-token": "should-not-leak",
            "cookie": "session=should-not-leak",
            "connection": "keep-alive"}) == 200
    server.shutdown()
    server.server_close()
    headers = _Upstream.last_headers
    assert headers.get("authorization") == "Bearer test-secret-value"
    assert headers.get("accept") == "text/event-stream"
    # The client's internal token and cookie are never forwarded, and the
    # client's hop-by-hop connection value is not propagated.
    assert "x-byq-internal-token" not in headers
    assert "cookie" not in headers
    assert headers.get("connection") != "keep-alive"
    # No secret value is written to the receipt journal.
    text = journal.read_text()
    assert "test-secret-value" not in text and "should-not-leak" not in text


def test_proxy_refuses_missing_invalid_or_conflicting_output_cap():
    for body in (_root_body(max_tokens=None), _root_body(max_tokens=0),
                 _root_body(max_tokens=True),
                 _root_body(max_tokens=5, max_completion_tokens=6)):
        server, upstream = _serve()
        gate = build_request_gate("strategy_draft", request_id="byq-judgment-a")
        with RequestGateProxy(gate, upstream) as proxy:
            assert _post(proxy, body) == 429
        server.shutdown()
        server.server_close()
        assert _Upstream.hits == 0


def test_proxy_forwards_admitted_and_refuses_over_budget():
    server, upstream = _serve()
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a")
    with RequestGateProxy(gate, upstream) as proxy:
        for body in (_root_body(), _child_body(), _root_body()):
            assert _post(proxy, body) == 200
        assert _post(proxy, _root_body()) == 429
    server.shutdown()
    server.server_close()
    assert _Upstream.hits == 3


def test_proxy_refuses_and_discards_over_limit_response():
    server, upstream = _serve(mode="over_limit")
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a")
    with RequestGateProxy(gate, upstream) as proxy:
        assert _post(proxy, _root_body(max_tokens=4)) == 502
    server.shutdown()
    server.server_close()


def test_proxy_discards_response_without_provable_usage():
    # A response whose actual output usage cannot be proven must not be forwarded.
    server, upstream = _serve(mode="no_usage")
    gate = build_request_gate("strategy_draft", request_id="byq-judgment-a")
    with RequestGateProxy(gate, upstream) as proxy:
        assert _post(proxy, _root_body()) == 502
    server.shutdown()
    server.server_close()


def test_proxy_deadline_bounds_the_upstream_and_rejects_late_result():
    server, upstream = _serve(delay=1.0)
    gate = _short_deadline_gate(150)
    with RequestGateProxy(gate, upstream) as proxy:
        assert _post(proxy, _root_body()) == 504
    server.shutdown()
    server.server_close()
