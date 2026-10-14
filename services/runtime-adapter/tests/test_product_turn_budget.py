from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.research_request_gate import (
    SETTLED_OK,
    UNKNOWN_OR_UNPAIRED,
    RequestGateBlocked,
    RequestGateProxy,
    ResearchRequestGate,
)
from packages.contracts.product_turn_request import product_turn_limits, product_turn_profile


def _gate():
    return ResearchRequestGate(product_turn_limits(), execution_profile=product_turn_profile(),
        request_id="product-turn-test")


def _ordinary_options_gate(options=None, *, monotonic=time.monotonic, journal=None,
                           request_id="product-turn-v2-test"):
    from packages.contracts.agent_execution_options import default_agent_execution_options
    from packages.contracts.product_turn_request import (
        product_turn_execution_limits, product_turn_execution_profile,
    )

    values = default_agent_execution_options() if options is None else options
    profile = product_turn_execution_profile(values, revision=12)
    return ResearchRequestGate(
        product_turn_execution_limits(values), execution_profile=profile,
        request_id=request_id, monotonic=monotonic, journal=journal,
    )


def _body(**changes):
    value = {"model": "deepseek-v4.1-flash", "max_tokens": 8,
             "messages": [{"role": "user", "content": "synthetic only"}]}
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


def _task_ready_carrier(options=None, *, revision=7):
    from packages.contracts.agent_execution_options import default_agent_execution_options
    from packages.contracts.continuation_request import continuation_reservation_v3

    values = default_agent_execution_options() if options is None else options
    return continuation_reservation_v3(
        owner_principal="owner-a", workspace_id="workspace-a",
        conversation_id="conversation-a", task_id="task_" + "1" * 32,
        event_key="ready-v1:" + "2" * 64,
        signal_job_id="signaljob_" + "3" * 32,
        result_artifact_id="artifact_" + "4" * 32,
        result_artifact_content_sha256="5" * 64,
        options=values, options_revision=revision,
    )


def test_task_ready_overlay_preserves_nulls_and_uses_tightest_output_cap():
    from app.continuation_budget import create_acp_task_ready_execution_overlay
    from packages.contracts.agent_execution_options import default_agent_execution_options

    options = default_agent_execution_options()
    options["max_output_tokens_per_call"] = 240
    options["max_output_tokens_total"] = 96
    overlay = json.loads(create_acp_task_ready_execution_overlay(
        proxy_base_url="http://172.31.7.9:41337",
        provider_session_id="11111111-2222-4333-8444-555555555555",
        reservation_v3=_task_ready_carrier(options), root_run_id="a" * 32,
    ).decode())
    assert overlay[:3] == [
        {"id": "web-search-deepseek", "disabled": True},
        {"id": "tool-web", "disabled": True},
        {"id": "llm-deepseek", "config": {"maxTokens": 96}},
    ]
    chat = overlay[3]["config"]["providers"]["opencode-go-chat"]
    assert chat["retryPolicy"] == {"mode": "normal", "maxRetries": 0}
    assert chat["headers"] == {"x-opencode-session": "11111111-2222-4333-8444-555555555555"}
    assert chat["models"] == [{"id": "deepseek-v4.1-flash", "maxTokens": 96}]
    config = overlay[4]["insert"][0]["config"]
    assert config["guardMode"] == "task-ready-options"
    assert config["rootRunId"] == "a" * 32
    assert config["idempotencyKey"].startswith("task-ready-event:")
    assert config["sourceFactSha256"] == _task_ready_carrier(options)["source_fact_sha256"]
    assert "journalPath" not in config
    assert "deadlineEpochMs" not in config

    no_cap = json.loads(create_acp_task_ready_execution_overlay(
        proxy_base_url="http://172.31.7.9:41337",
        provider_session_id="11111111-2222-4333-8444-555555555555",
        reservation_v3=_task_ready_carrier(), root_run_id="b" * 32,
    ).decode())
    assert no_cap[2] == {"id": "llm-deepseek", "config": {}}
    assert no_cap[3]["config"]["providers"]["opencode-go-chat"]["models"] == [
        {"id": "deepseek-v4.1-flash"}
    ]
    assert no_cap[4]["insert"][0]["config"]["requestLimits"]["max_runtime_seconds"] is None


def test_task_ready_overlay_rejects_javascript_unsafe_profile_values():
    from app.continuation_budget import create_acp_task_ready_execution_overlay
    from packages.contracts.agent_execution_options import default_agent_execution_options

    def encode(reservation):
        return create_acp_task_ready_execution_overlay(
            proxy_base_url="http://172.31.7.9:41337",
            provider_session_id="11111111-2222-4333-8444-555555555555",
            reservation_v3=reservation, root_run_id="a" * 32,
        )

    options = default_agent_execution_options()
    options["max_tool_calls"] = 9007199254740992
    with pytest.raises(ValueError, match="JavaScript integer precision"):
        encode(_task_ready_carrier(options))
    options = default_agent_execution_options()
    options["max_output_tokens_total"] = 9007199254740992
    with pytest.raises(ValueError, match="JavaScript integer precision"):
        encode(_task_ready_carrier(options))
    with pytest.raises(ValueError, match="JavaScript integer precision"):
        encode(_task_ready_carrier(revision=9007199254740992))


def test_ordinary_v2_defaults_allow_more_than_legacy_calls_and_runtime():
    clock = [0.0]
    gate = _ordinary_options_gate(monotonic=lambda: clock[0])
    response_body = b'{"usage":{"prompt_tokens":2,"completion_tokens":3}}'

    # Hold two independently admitted requests open at once to prove the
    # default provider-concurrency option is unset. Both are paired below.
    parallel = [gate.before_request(_body(max_tokens=10000)) for _ in range(2)]
    assert gate._max_concurrent == 2
    for receipt in parallel:
        clock[0] += 220
        assert gate.complete(receipt, status=200, body=response_body)["forward"] is True

    for _ in range(18):
        receipt = gate.before_request(_body(max_tokens=10000))
        assert receipt["declared_max_output_tokens"] == 10000
        clock[0] += 220
        result = gate.complete(receipt, status=200, body=response_body)
        assert result["forward"] is True

    assert clock[0] > 3600
    assert gate.product_turn_v2 is True
    assert gate.limits["max_provider_calls"] is None
    assert gate.limits["max_runtime_seconds"] is None
    assert gate.limits["max_concurrent"] is None
    assert gate._max_declared_output_tokens == 10000 > 8192
    assert gate._declared_output_tokens_total == 200000 > 131072
    assert sum(row["phase"] == "admitted" for row in gate.receipts()) == 20
    assert sum(row.get("phase") == "completed" and row["forwarded"]
               for row in gate.receipts()) == 20


def test_ordinary_v2_unset_output_declaration_and_missing_usage_stay_unknown():
    gate = _ordinary_options_gate()
    for max_tokens in (None, 64, None):
        admitted = gate.before_request(_body(max_tokens=max_tokens))
        assert admitted["declared_max_output_tokens"] == max_tokens
        result = gate.complete(admitted, status=200, body=b"{}")
        assert result["forward"] is True
        assert result["actual_output_tokens"] == "unknown"
        assert gate._declared_output_tokens_total is None
        completed = gate.receipts()[-1]
        assert completed["declared_max_output_tokens"] == max_tokens
        assert completed["actual_output_tokens"] == "unknown"
        assert completed["usage_source"] == "unknown"


def test_ordinary_v2_total_output_ceiling_requires_and_sums_each_declared_call():
    from packages.contracts.agent_execution_options import default_agent_execution_options
    from app.continuation_budget import create_acp_product_execution_overlay

    options = default_agent_execution_options()
    options["max_output_tokens_per_call"] = 200
    options["max_output_tokens_total"] = 100
    missing_gate = _ordinary_options_gate(
        options, request_id="product-turn-v2-output-missing")
    overlay = json.loads(create_acp_product_execution_overlay(
        proxy_base_url="http://172.31.7.9:41337",
        provider_session_id="11111111-2222-4333-8444-555555555555",
        provider="opencode-go-chat", model="deepseek-v4.1-flash",
        execution_profile=missing_gate.execution_profile,
    ).decode())
    model = overlay[0]["config"]["providers"]["opencode-go-chat"]["models"][0]
    assert model == {"id": "deepseek-v4.1-flash", "maxTokens": 100}
    assert missing_gate.limits["max_output_tokens"] == 200
    assert missing_gate.limits["max_total_output_tokens"] == 100

    with pytest.raises(RequestGateBlocked, match="declared_output_limit_missing"):
        missing_gate.before_request(_body(max_tokens=None))
    with pytest.raises(RequestGateBlocked, match="cancelled"):
        missing_gate.before_request(_body(max_tokens=70))

    per_call_gate = _ordinary_options_gate(
        options, request_id="product-turn-v2-output-per-call")
    with pytest.raises(RequestGateBlocked, match="product_output_tokens_limit"):
        per_call_gate.before_request(_body(max_tokens=201))

    total_gate = _ordinary_options_gate(
        options, request_id="product-turn-v2-output-total")
    first = total_gate.before_request(_body(max_tokens=70))
    assert total_gate.complete(first, status=200,
                               body=b'{"usage":{"prompt_tokens":1,"completion_tokens":65}}')["forward"]
    with pytest.raises(RequestGateBlocked, match="product_total_output_tokens_limit"):
        total_gate.before_request(_body(max_tokens=31))


def test_cancel_closes_registered_upstream_before_response_headers_and_seals_unknown(tmp_path):
    received = threading.Event()
    peer_closed = threading.Event()
    post_count = {"value": 0}

    class NoHeaders(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            post_count["value"] += 1
            received.set()
            try:
                while self.connection.recv(4096):
                    pass
            finally:
                peer_closed.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), NoHeaders)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    journal = tmp_path / "cancelled-upstream.jsonl"
    gate = _ordinary_options_gate(journal=journal)
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = f"http://127.0.0.1:{server.server_address[1]}"
    proxy.__enter__()
    outcome = {}

    def call_provider():
        try:
            outcome["response"] = httpx.post(
                proxy.base_url + "/chat/completions", content=_body(), timeout=None)
        except httpx.HTTPError as error:
            outcome["error"] = type(error).__name__

    caller = threading.Thread(target=call_provider, daemon=True)
    caller.start()
    try:
        assert received.wait(3)
        assert gate._inflight == 1
        # The provider has received the request but withholds response headers.
        # User cancellation closes the registered live connection; it does not
        # assign an artificial deadline to this healthy execution.
        gate.cancel()
        proxy.close()
        caller.join(3)
        assert not caller.is_alive()
        assert peer_closed.wait(2)
        assert "error" in outcome or outcome.get("response", None) is not None
        assert post_count["value"] == 1
        assert gate._inflight == 0
        assert gate.has_unknown_outcome() is True
        assert gate.settlement_state() == "unknown_or_unpaired"
        completed = [row for row in gate.receipts() if row.get("phase") == "completed"]
        assert len(completed) == 1
        assert completed[0]["forwarded"] is False
        assert completed[0]["reason"] == "provider_outcome_unknown"
        durable_rows = [json.loads(line) for line in journal.read_text().splitlines()]
        assert durable_rows[-1]["phase"] == "completed"
        assert durable_rows[-1]["reason"] == "provider_outcome_unknown"
        assert durable_rows[-1]["forwarded"] is False
        with pytest.raises(RequestGateBlocked, match="cancelled"):
            gate.before_request(_body())
        assert post_count["value"] == 1
    finally:
        proxy.close()
        server.shutdown()
        server.server_close()


def test_v2_connection_failure_before_first_send_is_known_predispatch(monkeypatch):
    def fail_connect(_connection):
        raise socket.timeout("synthetic connect timeout")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_connect)
    gate = _ordinary_options_gate()
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy.__enter__()
    try:
        response = httpx.post(
            proxy.base_url + "/chat/completions", content=_body(), timeout=None)
        assert response.status_code == 502
        assert gate._inflight == 0
        assert gate.has_unknown_outcome() is False
        assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
        proxy.close()
        assert gate.settlement_state() == SETTLED_OK
        completed = [row for row in gate.receipts() if row.get("phase") == "completed"]
        assert len(completed) == 1
        assert completed[0]["status"] == 502
        assert completed[0]["reason"] != "provider_outcome_unknown"
    finally:
        proxy.close()


def test_proxy_close_racing_upstream_registration_fences_provider_dispatch():
    post_count = {"value": 0}
    request_entered = threading.Event()
    release_registration = threading.Event()

    class ImmediateResponse(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            post_count["value"] += 1
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), ImmediateResponse)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    gate = _ordinary_options_gate()
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = f"http://127.0.0.1:{server.server_address[1]}"
    original_register = proxy._register_upstream

    def pause_before_registration(upstream):
        if isinstance(upstream, http.client.HTTPConnection):
            request_entered.set()
            assert release_registration.wait(3)
        return original_register(upstream)

    proxy._register_upstream = pause_before_registration
    proxy.__enter__()
    result = {}

    def call_provider():
        try:
            result["response"] = httpx.post(
                proxy.base_url + "/chat/completions", content=_body(), timeout=None)
        except httpx.HTTPError as error:
            result["error"] = type(error).__name__

    caller = threading.Thread(target=call_provider, daemon=True)
    caller.start()
    closer = None
    try:
        assert request_entered.wait(3)
        closer = threading.Thread(target=proxy.close, daemon=True)
        closer.start()
        deadline = time.monotonic() + 3
        while not proxy._closed and time.monotonic() < deadline:
            time.sleep(0.005)
        assert proxy._closed is True
        release_registration.set()
        caller.join(3)
        closer.join(3)
        assert not caller.is_alive()
        assert not closer.is_alive()
        assert post_count["value"] == 0
        assert gate._inflight == 0
        assert gate.settlement_state() == SETTLED_OK
        assert gate.has_unknown_outcome() is False
    finally:
        release_registration.set()
        proxy.close()
        if closer is not None:
            closer.join(3)
        server.shutdown()
        server.server_close()


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


def _hold_first_upstream():
    """Provider that holds its FIRST post until released and tracks concurrency.

    Parent and child Agents of one product root share one RequestGateProxy, so a
    second, overlapping request must serialize at the gate and never reach the
    upstream while the first is still in flight.
    """

    lock = threading.Lock()
    state = {"active": 0, "max_active": 0, "posts": 0}
    first_post = threading.Event()
    release_first = threading.Event()
    response = b'{"usage":{"prompt_tokens":1,"completion_tokens":1}}'

    class Provider(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
                state["posts"] += 1
                first = state["posts"] == 1
            if first:
                first_post.set()
                release_first.wait(5)
            try:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            except OSError:
                pass
            finally:
                with lock:
                    state["active"] -= 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", state, lock, first_post, release_first


def _wait_until(predicate, timeout=5.0, interval=0.005):
    """Deterministic state-based synchronization (no fixed sleep)."""

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)
    return predicate()


def test_product_turn_gate_serializes_overlapping_requests_within_max_concurrent():
    server, upstream, state, lock, first_post, release_first = _hold_first_upstream()
    gate = _gate()
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = upstream
    proxy.__enter__()
    results: dict = {}

    def call(name):
        results[name] = httpx.post(proxy.base_url + "/chat/completions",
            content=_body(), timeout=10)

    try:
        first = threading.Thread(target=call, args=("A",), daemon=True)
        first.start()
        assert first_post.wait(3)
        second = threading.Thread(target=call, args=("B",), daemon=True)
        second.start()
        # Deterministic sync point: B has reached the gate and is queued on the
        # single slot (not dispatched). It must not open a second upstream post.
        assert _wait_until(lambda: gate.waiting == 1)
        with lock:
            assert state["posts"] == 1
            assert state["active"] == 1
        assert second.is_alive()
        release_first.set()
        first.join(5)
        second.join(5)
        assert not first.is_alive() and not second.is_alive()
        assert results["A"].status_code == 200
        assert results["B"].status_code == 200
        with lock:
            assert state["max_active"] == 1
            assert state["posts"] == 2
        assert gate.waiting == 0
        # Both requests were admitted (serialized) within the unchanged cap.
        admitted = [row for row in gate.receipts() if row.get("phase") == "admitted"]
        assert len(admitted) == 2
        assert product_turn_limits()["max_concurrent"] == 1
    finally:
        proxy.close()
        server.shutdown()
        server.server_close()


def test_product_turn_waiting_request_fails_closed_on_cancel_without_upstream_post():
    server, upstream, state, lock, first_post, release_first = _hold_first_upstream()
    gate = _gate()
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = upstream
    proxy.__enter__()
    results: dict = {}

    def call(name):
        results[name] = httpx.post(proxy.base_url + "/chat/completions",
            content=_body(), timeout=10)

    try:
        first = threading.Thread(target=call, args=("A",), daemon=True)
        first.start()
        assert first_post.wait(3)
        second = threading.Thread(target=call, args=("B",), daemon=True)
        second.start()
        # Deterministic sync point: B reached the gate and is queued.
        assert _wait_until(lambda: gate.waiting == 1)
        with lock:
            assert state["posts"] == 1
        # Cancellation wakes the serialized waiter; it fails closed, no replay.
        gate.cancel()
        second.join(5)
        assert not second.is_alive()
        assert gate.waiting == 0
        assert results["B"].status_code == 429
        assert results["B"].json()["error"]["code"] == "cancelled"
        with lock:
            assert state["posts"] == 1  # B never reached upstream
        release_first.set()
        first.join(5)
        assert results["A"].status_code == 200
    finally:
        proxy.close()
        server.shutdown()
        server.server_close()


def test_product_turn_proxy_close_wakes_serialized_waiter_without_second_upstream_post():
    server, upstream, state, lock, first_post, release_first = _hold_first_upstream()
    gate = _gate()
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = upstream
    proxy.__enter__()
    outcome: dict = {}

    def call(name):
        try:
            outcome[name] = ("response", httpx.post(
                proxy.base_url + "/chat/completions", content=_body(), timeout=10))
        except httpx.HTTPError as error:
            outcome[name] = ("error", type(error).__name__)

    try:
        first = threading.Thread(target=call, args=("A",), daemon=True)
        first.start()
        assert first_post.wait(3)
        second = threading.Thread(target=call, args=("B",), daemon=True)
        second.start()
        assert _wait_until(lambda: gate.waiting == 1)
        # Closing the proxy must wake B fail-closed; it must not hang until the
        # deadline nor open a second upstream post.
        proxy.close()
        second.join(5)
        assert not second.is_alive()
        with lock:
            assert state["posts"] == 1
        # Either a structured 429 refusal or a client transport error is valid
        # (close also shuts the client sockets); a forwarded 200 never is.
        kind, value = outcome["B"]
        if kind == "response":
            assert value.status_code == 429
            assert value.json()["error"]["code"] == "cancelled"
        else:
            assert kind == "error"
    finally:
        release_first.set()
        proxy.close()  # idempotent
        server.shutdown()
        server.server_close()


def test_product_turn_waiting_request_fails_closed_at_deadline_without_upstream_post():
    clock = {"t": 1000.0}
    gate = ResearchRequestGate(
        product_turn_limits(), execution_profile=product_turn_profile(),
        request_id="product-turn-test", monotonic=lambda: clock["t"])
    admitted = gate.before_request(_body())
    assert admitted["admitted"] is True
    # The request deadline elapses while the single slot is still held: the next
    # request fails closed with a structured reason instead of waiting or
    # dispatching upstream.
    clock["t"] += product_turn_limits()["deadline_ms"] / 1000.0
    with pytest.raises(RequestGateBlocked, match="deadline_exceeded"):
        gate.before_request(_body())
    admitted = [row for row in gate.receipts() if row.get("phase") == "admitted"]
    rejected = [row for row in gate.receipts() if row.get("phase") == "rejected"]
    assert len(admitted) == 1  # only A ever reached upstream admission
    assert [row["reason"] for row in rejected] == ["deadline_exceeded"]


def test_product_turn_admitted_journal_failure_fails_closed_without_stranding_slot(tmp_path):
    # A directory path makes every journal open() fail with OSError.
    gate = ResearchRequestGate(
        product_turn_limits(), execution_profile=product_turn_profile(),
        request_id="product-turn-test", journal=tmp_path)
    with pytest.raises(RequestGateBlocked, match="storage_failed"):
        gate.before_request(_body())
    assert gate.journal_failed is True
    assert gate.waiting == 0  # the admitted-but-undispatched slot was released
    # Later requests must not dispatch either; fail closed immediately, no hang.
    with pytest.raises(RequestGateBlocked, match="storage_failed"):
        gate.before_request(_body())


def test_product_turn_completion_journal_failure_keeps_scope_fail_closed(monkeypatch):
    gate = _gate()
    real = gate._write_journal
    calls = {"n": 0}

    def flaky(receipt):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RequestGateBlocked("storage_failed")
        return real(receipt)

    monkeypatch.setattr(gate, "_write_journal", flaky)
    receipt = gate.before_request(_body())  # admitted journal write (#1) succeeds
    assert calls["n"] == 1
    with pytest.raises(RequestGateBlocked, match="storage_failed"):
        gate.complete(receipt, status=200,
                      body=b'{"usage":{"prompt_tokens":1,"completion_tokens":1}}')
    assert gate.journal_failed is True
    # The freed slot must not admit a later dispatch once the journal is broken.
    with pytest.raises(RequestGateBlocked, match="storage_failed"):
        gate.before_request(_body())


def test_product_turn_released_slot_with_journal_failure_does_not_dispatch_waiter(monkeypatch):
    server, upstream, state, lock, first_post, release_first = _hold_first_upstream()
    gate = _gate()
    real = gate._write_journal
    calls = {"n": 0}

    def flaky(receipt):
        calls["n"] += 1
        if calls["n"] >= 2:  # A admitted write (#1) ok; A completion write (#2) fails
            raise RequestGateBlocked("storage_failed")
        return real(receipt)

    monkeypatch.setattr(gate, "_write_journal", flaky)
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = upstream
    proxy.__enter__()
    outcome: dict = {}

    def call(name):
        try:
            outcome[name] = httpx.post(proxy.base_url + "/chat/completions",
                                       content=_body(), timeout=10)
        except httpx.HTTPError:
            outcome[name] = None

    try:
        first = threading.Thread(target=call, args=("A",), daemon=True)
        first.start()
        assert first_post.wait(3)
        second = threading.Thread(target=call, args=("B",), daemon=True)
        second.start()
        assert _wait_until(lambda: gate.waiting == 1)
        release_first.set()  # A completes; its completion journal write fails
        first.join(5)
        second.join(5)
        assert not second.is_alive()
        assert gate.journal_failed is True
        with lock:
            # The released slot must not dispatch the queued request once the
            # durable completion row failed to persist.
            assert state["posts"] == 1
    finally:
        release_first.set()
        proxy.close()
        server.shutdown()
        server.server_close()


def test_product_turn_serialized_waiter_queue_is_bounded_and_fails_closed():
    gate = _gate()
    body = _body()
    assert gate.before_request(body)["admitted"] is True  # A owns the single slot
    limits = product_turn_limits()
    # Simulate a full serialized queue at the closed profile's attempt budget.
    with gate._cond:
        gate._waiting = limits["max_attempts"]
    try:
        with pytest.raises(RequestGateBlocked, match="queue_limit"):
            gate.before_request(body)
        # Bounded-queue overflow refuses only this request; it must not poison
        # the scope or raise upstream concurrency.
        assert gate.cancelled is False
        rejected = [row for row in gate.receipts() if row.get("phase") == "rejected"]
        assert [row["reason"] for row in rejected] == ["queue_limit"]
    finally:
        with gate._cond:
            gate._waiting = 0
    # The scope is still usable once the queue drains.
    assert gate.waiting == 0


def test_product_turn_completion_journal_failure_does_not_forward_provider_200(monkeypatch):
    posted = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            posted.append(1)
            payload = b'{"usage":{"prompt_tokens":1,"completion_tokens":1}}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    gate = _gate()
    real = gate._write_journal
    calls = {"n": 0}

    def flaky(receipt):
        calls["n"] += 1
        if calls["n"] >= 2:  # admitted write (#1) ok; completion write (#2) fails
            raise RequestGateBlocked("storage_failed")
        return real(receipt)

    monkeypatch.setattr(gate, "_write_journal", flaky)
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = f"http://127.0.0.1:{server.server_address[1]}"
    proxy.__enter__()
    try:
        response = httpx.post(proxy.base_url + "/chat/completions", content=_body(), timeout=10)
        assert len(posted) == 1  # the provider call was issued
        assert gate.journal_failed is True
        # The provider's 200 must not be forwarded once its completion row
        # failed to persist; the refusal is a structured 502.
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "storage_failed"
    finally:
        proxy.close()
        server.shutdown()
        server.server_close()


def test_product_turn_disconnected_waiter_is_not_dispatched_upstream_after_slot_frees():
    server, upstream, state, lock, first_post, release_first = _hold_first_upstream()
    gate = _gate()
    proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
    proxy._server.upstream = upstream
    proxy.__enter__()
    body = _body()

    def call_a():
        try:
            httpx.post(proxy.base_url + "/chat/completions", content=body, timeout=10)
        except httpx.HTTPError:
            pass

    try:
        first = threading.Thread(target=call_a, daemon=True)
        first.start()
        assert first_post.wait(3)
        parsed = urllib.parse.urlparse(proxy.base_url)
        client = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
        request = (f"POST /chat/completions HTTP/1.1\r\nHost: {parsed.hostname}\r\n"
                   f"content-type: application/json\r\ncontent-length: {len(body)}\r\n"
                   f"Connection: close\r\n\r\n").encode() + body
        client.sendall(request)
        assert _wait_until(lambda: gate.waiting == 1)
        client.close()  # the queued request's client disconnects while waiting
        release_first.set()
        first.join(5)
        assert _wait_until(lambda: gate.waiting == 0)
        # The disconnected queued request must not become a late provider call.
        assert not _wait_until(lambda: state["posts"] >= 2, timeout=1.0)
        with lock:
            assert state["posts"] == 1
    finally:
        release_first.set()
        proxy.close()
        server.shutdown()
        server.server_close()
