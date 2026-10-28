r"""Focused, unactivated task-ready-read.v2 provider-gate contract tests.

These tests cover the optional F6 profile, shared request accounting, factual
usage, and provider transport settlement. Planned node IDs and frozen-runner
requirements are recorded in the private WORKER-TEST-PLAN.json artifact. Local
transport stubs override the upstream only after profile-pinned construction.
"""

from __future__ import annotations

import copy
import http.client
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.research_request_gate import (
    KNOWN_BLOCKED,
    SETTLED_OK,
    UNKNOWN_OR_UNPAIRED,
    RequestGateBlocked,
    RequestGateProxy,
    ResearchRequestGate,
    build_continuation_request_gate,
    build_task_ready_v2_request_gate,
)
from packages.contracts.agent_execution_options import default_agent_execution_options
from packages.contracts.continuation_request import (
    execution_profile_v2,
    request_limits_v2,
    validate_request_usage,
)
from packages.contracts.product_turn_request import (
    product_turn_execution_limits,
    product_turn_execution_profile,
)


def _options(**overrides):
    values = default_agent_execution_options()
    values.update(overrides)
    return values


def _profile(options=None, *, revision=7):
    return execution_profile_v2(
        default_agent_execution_options() if options is None else options,
        revision=revision,
    )


def _gate(options=None, *, clock=None, journal=None, request_id="task-ready-v2-test"):
    profile = _profile(options)
    monotonic = time.monotonic if clock is None else lambda: clock[0]
    return ResearchRequestGate(
        request_limits_v2(profile["options"]),
        execution_profile=profile,
        request_id=request_id,
        journal=journal,
        monotonic=monotonic,
    )


def _ordinary_gate(options=None, *, clock=None):
    values = default_agent_execution_options() if options is None else options
    profile = product_turn_execution_profile(values, revision=7)
    monotonic = time.monotonic if clock is None else lambda: clock[0]
    return ResearchRequestGate(
        product_turn_execution_limits(profile["options"]),
        execution_profile=profile,
        request_id="ordinary-v2-shared-tracker-test",
        monotonic=monotonic,
    )


_OMIT = object()


def _body(*, max_tokens=_OMIT, **changes):
    value = {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "synthetic contract test"}],
    }
    if max_tokens is not _OMIT:
        value["max_tokens"] = max_tokens
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


def _usage_body(*, input_tokens=2, cache_tokens=1, output_tokens=3):
    usage = {"prompt_tokens": input_tokens, "completion_tokens": output_tokens}
    if cache_tokens is not None:
        usage["cache_read_input_tokens"] = cache_tokens
    return json.dumps({"usage": usage}, separators=(",", ":")).encode()


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_task_ready_v2_builder_validates_exact_profile_and_limits(monkeypatch):
    profile = _profile()
    gate = build_task_ready_v2_request_gate(
        request_id="task-ready-v2-builder", execution_profile=profile)
    assert gate.task_ready_v2 is True
    assert gate.product_turn_v2 is False
    assert gate.product_turn is False
    assert gate._optional_execution is True
    assert gate.execution_profile == profile
    assert gate.limits == request_limits_v2(profile["options"])

    def unexpected_server(*_args, **_kwargs):
        pytest.fail("proxy socket was created before upstream qualification")

    monkeypatch.setattr("app.research_request_gate.ThreadingHTTPServer", unexpected_server)
    with pytest.raises(ValueError, match="qualified endpoint"):
        RequestGateProxy(gate, "https://api.deepseek.com")

    bad_profile = copy.deepcopy(profile)
    bad_profile["upstream_request_target"] = "/other/route"
    with pytest.raises(ValueError, match="profile v2"):
        build_task_ready_v2_request_gate(
            request_id="task-ready-v2-bad-profile", execution_profile=bad_profile)
    with pytest.raises(ValueError, match="profile v2"):
        ResearchRequestGate(
            request_limits_v2(profile["options"]),
            execution_profile=bad_profile,
            request_id="task-ready-v2-no-downgrade",
        )

    altered_limits = request_limits_v2(profile["options"])
    altered_limits["max_provider_calls"] = 1
    with pytest.raises(ValueError, match="limits v2"):
        ResearchRequestGate(
            altered_limits, execution_profile=profile,
            request_id="task-ready-v2-bad-limits")


def test_task_ready_v2_default_options_exceed_legacy_call_and_runtime_caps():
    clock = [0.0]
    gate = _gate(clock=clock)
    body = _body(max_tokens=10_000)
    for _ in range(18):
        receipt = gate.before_request(body)
        clock[0] += 11.0
        assert gate.complete(receipt, status=200, body=_usage_body())["forward"] is True

    assert clock[0] > 180
    assert gate._provider_calls == 18 > 16
    assert gate._attempts == 18 > 16
    assert gate._max_declared_output_tokens == 10_000
    assert gate._declared_output_tokens_total == 180_000
    usage = gate.request_usage(tool_calls=0)
    assert usage["schema_version"] == "continuation-request-usage.v2"
    assert usage["admission_usage"]["elapsed_ms"] > 180_000
    assert usage["actual_usage"] == {
        "input_tokens": 36,
        "cache_read_tokens": 18,
        "output_tokens": 54,
        "provider_attempts": 18,
        "usage_source": "provider_response",
        "completeness": "known",
    }


def test_task_ready_v2_enforces_provider_call_and_attempt_caps():
    call_gate = _gate(_options(max_provider_calls=1))
    first = call_gate.before_request(_body(max_tokens=8))
    assert call_gate.complete(first, status=200, body=_usage_body())["forward"]
    with pytest.raises(RequestGateBlocked, match="product_provider_call_limit"):
        call_gate.before_request(_body(max_tokens=8))

    attempt_gate = _gate(_options(max_provider_attempts=1))
    first = attempt_gate.before_request(_body(max_tokens=8))
    assert attempt_gate.complete(first, status=200, body=_usage_body())["forward"]
    with pytest.raises(RequestGateBlocked, match="product_attempt_limit"):
        attempt_gate.before_request(_body(max_tokens=8))


def test_task_ready_v2_enforces_runtime_input_and_tool_payload_limits():
    clock = [0.0]
    runtime_gate = _gate(_options(max_runtime_seconds=2), clock=clock)
    clock[0] = 2.0
    with pytest.raises(RequestGateBlocked, match="product_runtime_limit"):
        runtime_gate.before_request(_body(max_tokens=8))

    body = _body(max_tokens=8)
    input_gate = _gate(_options(max_input_bytes_per_call=len(body) - 1))
    with pytest.raises(RequestGateBlocked, match="product_input_bytes_limit"):
        input_gate.before_request(body)

    total_input_gate = _gate(_options(max_input_bytes_total=len(body)))
    first = total_input_gate.before_request(body)
    assert total_input_gate.complete(first, status=200, body=_usage_body())["forward"]
    with pytest.raises(RequestGateBlocked, match="product_total_input_bytes_limit"):
        total_input_gate.before_request(body)

    per_call_tool_gate = _gate(_options(max_tool_payload_bytes_per_call=1))
    with pytest.raises(RequestGateBlocked, match="product_tool_payload_limit"):
        per_call_tool_gate.before_request(body)

    total_tool_gate = _gate(_options(max_tool_payload_bytes_total=3))
    first = total_tool_gate.before_request(body)
    assert total_tool_gate.complete(first, status=200, body=_usage_body())["forward"]
    with pytest.raises(RequestGateBlocked, match="product_total_tool_payload_limit"):
        total_tool_gate.before_request(body)


def test_task_ready_v2_enforces_output_token_limits():
    per_call_gate = _gate(_options(max_output_tokens_per_call=8))
    with pytest.raises(RequestGateBlocked, match="product_output_tokens_limit"):
        per_call_gate.before_request(_body(max_tokens=9))

    total_gate = _gate(_options(max_output_tokens_total=12))
    first = total_gate.before_request(_body(max_tokens=8))
    assert total_gate.complete(first, status=200, body=_usage_body())["forward"]
    with pytest.raises(RequestGateBlocked, match="product_total_output_tokens_limit"):
        total_gate.before_request(_body(max_tokens=8))


def test_task_ready_v2_null_and_explicit_concurrency_are_distinct():
    unbounded = _gate()
    parallel = [unbounded.before_request(_body(max_tokens=8)) for _ in range(2)]
    assert unbounded.limits["max_concurrent"] is None
    assert unbounded._inflight == unbounded._max_concurrent == 2
    for receipt in parallel:
        assert unbounded.complete(receipt, status=200, body=_usage_body())["forward"]

    one_slot = _gate(_options(max_concurrent_provider_calls=1))
    first = one_slot.before_request(_body(max_tokens=8))
    with pytest.raises(RequestGateBlocked, match="product_concurrency_limit"):
        one_slot.before_request(_body(max_tokens=8))
    assert one_slot._inflight == one_slot._max_concurrent == 1
    one_slot.complete(first, status=200, body=_usage_body())

    two_slots = _gate(_options(max_concurrent_provider_calls=2))
    parallel = [two_slots.before_request(_body(max_tokens=8)) for _ in range(2)]
    with pytest.raises(RequestGateBlocked, match="product_concurrency_limit"):
        two_slots.before_request(_body(max_tokens=8))
    assert two_slots._inflight == two_slots._max_concurrent == 2
    for receipt in parallel:
        two_slots.complete(receipt, status=200, body=_usage_body())


def test_unknown_declared_output_makes_total_and_peak_sticky_null():
    gate = _gate()
    unknown = gate.before_request(_body())
    assert unknown["declared_max_output_tokens"] is None
    gate.complete(unknown, status=200, body=_usage_body())
    assert gate._declared_output_tokens_total is None
    assert gate._max_declared_output_tokens is None
    known = gate.before_request(_body(max_tokens=64))
    gate.complete(known, status=200, body=_usage_body())
    task_usage = gate.request_usage(tool_calls=0)["admission_usage"]
    assert task_usage["declared_output_tokens"] is None
    assert task_usage["max_declared_output_tokens"] is None

    ordinary = _ordinary_gate()
    first = ordinary.before_request(_body())
    ordinary.complete(first, status=200, body=_usage_body())
    second = ordinary.before_request(_body(max_tokens=64))
    ordinary.complete(second, status=200, body=_usage_body())
    assert ordinary._declared_output_tokens_total is None
    assert ordinary._max_declared_output_tokens is None


def test_task_ready_v2_usage_preserves_unknown_zero_and_partial_facts():
    zero = _gate().request_usage(tool_calls=0)
    assert zero["actual_usage"] == {
        "input_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
        "provider_attempts": 0,
        "usage_source": "no_provider_calls",
        "completeness": "known",
    }
    assert zero["admission_usage"]["provider_attempts"] == 0
    with pytest.raises(ValueError):
        validate_request_usage(zero)

    unknown_gate = _gate()
    receipt = unknown_gate.before_request(_body(max_tokens=8))
    assert unknown_gate.complete(receipt, status=200, body=b"{}")["forward"]
    unknown = unknown_gate.request_usage(tool_calls=0)["actual_usage"]
    assert unknown == {
        "input_tokens": None,
        "cache_read_tokens": None,
        "output_tokens": None,
        "provider_attempts": None,
        "usage_source": "unknown",
        "completeness": "unknown",
    }

    partial_gate = _gate()
    receipt = partial_gate.before_request(_body(max_tokens=8))
    partial_gate.complete(
        receipt, status=200,
        body=b'{"usage":{"prompt_tokens":2,"completion_tokens":4}}')
    partial = partial_gate.request_usage(tool_calls=0)["actual_usage"]
    assert partial == {
        "input_tokens": 2,
        "cache_read_tokens": None,
        "output_tokens": 4,
        "provider_attempts": 1,
        "usage_source": "provider_response",
        "completeness": "partial",
    }


def test_task_ready_v2_usage_retains_provider_declared_output_overrun():
    gate = _gate(_options(max_output_tokens_per_call=1))
    receipt = gate.before_request(_body(max_tokens=1))
    completed = gate.complete(
        receipt, status=200, body=_usage_body(output_tokens=2))
    assert completed["forward"] is False
    assert completed["reason"] == "output_tokens_exceeded"
    usage = gate.request_usage(tool_calls=0)
    assert usage["limit_violations"] == ["provider_declared_output_exceeded"]
    assert usage["actual_usage"]["output_tokens"] == 2


def test_task_ready_v2_closed_unpaired_admission_cannot_replay():
    gate = _gate()
    gate.before_request(_body(max_tokens=8))
    gate.release_waiters()
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
    with pytest.raises(RequestGateBlocked, match="cancelled"):
        gate.before_request(_body(max_tokens=8))
    assert gate.request_usage(tool_calls=0)["admission_usage"]["provider_calls"] == 1
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
    assert gate.request_usage(tool_calls=0)["actual_usage"]["provider_attempts"] is None


def test_task_ready_v2_proxy_rejects_non_chat_route_before_upstream():
    posts = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            posts.append(self.path)
            self.send_response(200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    server, thread, upstream = _serve(Provider)
    try:
        for path in ("/v2/not-chat", "/v1/chat/completions"):
            gate = _gate()
            proxy = RequestGateProxy(gate, gate.execution_profile["upstream_base_url"])
            proxy._server.upstream = upstream
            proxy.__enter__()
            try:
                response = httpx.post(
                    proxy.base_url + path, content=_body(max_tokens=8), timeout=3)
                assert response.status_code == 403
                assert posts == []
                assert gate.request_usage(tool_calls=0)["admission_usage"]["provider_calls"] == 0
                assert gate.receipts()[-1]["reason"] == "provider_path_unqualified"
                proxy.close()
                assert gate.settlement_state() == KNOWN_BLOCKED
            finally:
                proxy.close()
    finally:
        _stop(server, thread)


def test_task_ready_v2_proxy_does_not_follow_provider_redirect():
    target_posts = []

    class Target(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            target_posts.append(self.path)
            self.rfile.read(int(self.headers.get("content-length", "0")))
            self.send_response(200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    target, target_thread, target_url = _serve(Target)
    source_posts = []

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            source_posts.append(self.path)
            self.send_response(302)
            self.send_header("Location", target_url + "/redirected")
            self.send_header("content-length", "0")
            self.end_headers()

    source, source_thread, source_url = _serve(Redirect)
    gate = _gate()
    proxy = RequestGateProxy(gate, gate.execution_profile["upstream_base_url"])
    proxy._server.upstream = source_url
    proxy.__enter__()
    try:
        response = httpx.post(
            proxy.base_url + "/chat/completions", content=_body(max_tokens=8), timeout=3)
        assert response.status_code == 502
        assert source_posts == ["/chat/completions"]
        assert target_posts == []
        completed = [row for row in gate.receipts() if row.get("phase") == "completed"]
        assert len(completed) == 1
        assert completed[0]["reason"] == "provider_redirect_blocked"
    finally:
        proxy.close()
        _stop(source, source_thread)
        _stop(target, target_thread)


def test_task_ready_v2_predispatch_connect_timeout_is_known(monkeypatch):
    posts = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            posts.append(self.path)
            self.rfile.read(int(self.headers.get("content-length", "0")))

    server, thread, upstream = _serve(Provider)

    def fail_connect(_connection):
        raise socket.timeout("synthetic pre-send timeout")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_connect)
    gate = _gate()
    proxy = RequestGateProxy(gate, gate.execution_profile["upstream_base_url"])
    proxy._server.upstream = upstream
    proxy.__enter__()
    try:
        response = httpx.post(
            proxy.base_url + "/chat/completions", content=_body(max_tokens=8), timeout=None)
        assert response.status_code == 502
        assert posts == []
        assert gate.has_unknown_outcome() is False
        assert gate._inflight == 0
        proxy.close()
        assert gate.settlement_state() == SETTLED_OK
        assert gate.request_usage(tool_calls=0)["actual_usage"]["usage_source"] == "unknown"
    finally:
        proxy.close()
        _stop(server, thread)


def test_task_ready_v2_proxy_close_seals_dispatched_unknown_without_replay():
    received = threading.Event()
    peer_closed = threading.Event()
    posts = []

    class NoResponse(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            posts.append(self.path)
            received.set()
            try:
                while self.connection.recv(4096):
                    pass
            except OSError:
                # The proxy closes the dispatched socket to interrupt its
                # pending response read; that reset is the expected signal.
                pass
            finally:
                peer_closed.set()

    server, thread, upstream = _serve(NoResponse)
    gate = _gate()
    proxy = RequestGateProxy(gate, gate.execution_profile["upstream_base_url"])
    proxy._server.upstream = upstream
    proxy.__enter__()
    outcome = {}

    def call_provider():
        try:
            outcome["response"] = httpx.post(
                proxy.base_url + "/chat/completions", content=_body(max_tokens=8), timeout=None)
        except httpx.HTTPError as error:
            outcome["error"] = type(error).__name__

    caller = threading.Thread(target=call_provider, daemon=True)
    caller.start()
    try:
        assert received.wait(3)
        assert gate._inflight == 1
        gate.cancel()
        proxy.close()
        caller.join(3)
        assert not caller.is_alive()
        assert peer_closed.wait(2)
        assert "error" in outcome or "response" in outcome
        assert posts == ["/chat/completions"]
        assert gate.has_unknown_outcome() is True
        assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
        completed = [row for row in gate.receipts() if row.get("phase") == "completed"]
        assert len(completed) == 1
        assert completed[0]["reason"] == "provider_outcome_unknown"
        with pytest.raises(RequestGateBlocked, match="cancelled"):
            gate.before_request(_body(max_tokens=8))
        assert posts == ["/chat/completions"]
        usage = gate.request_usage(tool_calls=0)["actual_usage"]
        assert usage["provider_attempts"] is None
        assert usage["usage_source"] == "unknown"
    finally:
        proxy.close()
        caller.join(3)
        _stop(server, thread)


def test_task_ready_v1_serialized_waiter_wakes_closed_without_replay():
    from packages.contracts.continuation_request import profile_binding, request_limits

    gate = build_continuation_request_gate(
        request_id="task-ready-v1-waiter-test",
        execution_profile=profile_binding(),
        limits=request_limits(),
    )
    first = gate.before_request(_body(max_tokens=8))
    waiting = threading.Event()
    outcome = {}

    def request_while_slot_is_held():
        waiting.set()
        try:
            gate.before_request(_body(max_tokens=8))
        except RequestGateBlocked as error:
            outcome["reason"] = error.reason

    waiter = threading.Thread(target=request_while_slot_is_held, daemon=True)
    waiter.start()
    try:
        assert waiting.wait(1)
        deadline = time.monotonic() + 2
        while gate.waiting != 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert gate.waiting == 1
        gate.release_waiters()
        waiter.join(2)
        assert not waiter.is_alive()
        assert outcome["reason"] == "cancelled"
        assert gate.request_usage(tool_calls=0)["admission_usage"]["provider_calls"] == 1
        assert gate.waiting == 0
        assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
        assert gate.complete(first, status=200, body=_usage_body())["forward"]
        assert gate.settlement_state() == KNOWN_BLOCKED
        assert gate.request_usage(tool_calls=0)["schema_version"] == "continuation-request-usage.v1"
    finally:
        gate.release_waiters()
        waiter.join(2)
