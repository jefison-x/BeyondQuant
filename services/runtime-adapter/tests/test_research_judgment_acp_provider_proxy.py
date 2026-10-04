"""Local-only ACP judgment provider proxy and durable attempt boundary."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from app.research_judgment_acp_journal import AcpJudgmentJournal
from app.research_judgment_acp_provider_proxy import (
    AcpJudgmentProviderProxy, ProviderHttpResponse, _IsolatedHttpsTransport,
)
from app.research_judgment_acp_provider_routes import selected_route


TASK = "task_" + "a" * 32
CALL = "byq-judgment-" + "d" * 32
ROOT = "b" * 32
BOOT = "c" * 32
NATIVE = "00000000-0000-4000-8000-000000000001"


def _ready(tmp_path):
    directory = tmp_path / "control"
    directory.mkdir(mode=0o700)
    journal = AcpJudgmentJournal(
        directory, TASK, CALL, backend_url="http://backend",
        authority_headers={"authorization": "Bearer synthetic-runtime-authority"})
    journal.record_begin({"task_id": TASK, "status": "admitted", "created": True,
                          "call_identity": CALL, "attempt_binding": "1:strategy_draft:1",
                          "root": {"root_run_id": ROOT, "runtime_boot_id": BOOT,
                                   "authority_epoch": 1, "dsh_run_id": "byqjudg-" + "f" * 32}})
    journal.record_binding({"schema_version": "byq-acp-agent-bind-receipt.v1",
                            "status": "bound", "root_run_id": ROOT,
                            "runtime_boot_id": BOOT, "origin": "root", "depth": 0,
                            "native_agent_session_id": NATIVE,
                            "native_parent_session_id": None,
                            "agent_run_id": "agent_run_" + "e" * 32})
    journal.mark_prompt_may_dispatch()
    limits = {"max_calls": 2, "max_input_bytes": 1024,
              "max_total_input_bytes": 2048, "max_output_tokens": 32,
              "max_total_output_tokens": 64,
              "max_tool_payload_bytes": 1024,
              "max_total_tool_payload_bytes": 2048,
              "deadline_at_ms": int(time.time() * 1000) + 10000}
    return journal, limits


def _post(url, *, path="/v1/chat/completions", authorization="Bearer synthetic-key"):
    body = json.dumps({"model": "synthetic-model", "max_tokens": 16,
                       "stream": True, "messages": []}).encode()
    request = urllib.request.Request(
        url + path, data=body, method="POST",
        headers={"content-type": "application/json", "authorization": authorization})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _chat_sse():
    event = {"choices": [{"finish_reason": "stop"}],
             "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    return ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode()


def _await_phase(journal, phase):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        attempts = journal.snapshot().get("provider_attempts", [])
        if attempts and attempts[-1]["phase"] == phase:
            return
        time.sleep(0.005)
    assert journal.snapshot()["provider_attempts"][-1]["phase"] == phase


def _route_sse(protocol):
    if protocol == "chat":
        return _chat_sse()
    if protocol == "responses":
        event = {"type": "response.completed", "response": {
            "status": "completed", "usage": {"input_tokens": 7,
                                             "output_tokens": 3}}}
        return ("event: response.completed\ndata: " + json.dumps(event) + "\n\n").encode()
    start = {"type": "message_start", "message": {"usage": {
        "input_tokens": 7, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0}}}
    delta = {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 3}}
    return ("event: message_start\ndata: " + json.dumps(start)
            + "\n\nevent: message_delta\ndata: " + json.dumps(delta)
            + "\n\nevent: message_stop\ndata: {\"type\":\"message_stop\"}\n\n").encode()


@pytest.mark.parametrize("route_name", [
    "deepseek-official", "opencode-go-chat", "opencode-go-responses",
    "opencode-go-messages", "opencode-zen-chat", "opencode-zen-responses",
    "opencode-zen-messages",
])
def test_all_selected_proxy_routes_use_exact_upstream_and_headers(tmp_path, route_name):
    journal, limits = _ready(tmp_path)
    route = selected_route(route_name)
    sent = []

    def fake_transport(url, headers, body, deadline):
        assert journal.snapshot()["provider_attempts"][0]["phase"] == "may_have_dispatched"
        assert url == route.upstream_url
        assert set(headers) <= {"content-type", "accept", "authorization",
                                "x-api-key", "anthropic-version"}
        sent.append(url)
        return ProviderHttpResponse(200, "text/event-stream", _route_sse(route.protocol))

    with AcpJudgmentProviderProxy(
            journal, route_name=route_name, model="synthetic-model",
            credential="synthetic-key", limits=limits,
            transport=fake_transport) as proxy:
        origin = proxy.base_url.removesuffix(route.local_base_path) if route.local_base_path else proxy.base_url
        token_headers = ({"x-api-key": "synthetic-key", "anthropic-version": "2023-06-01"}
                         if route.protocol == "messages" else
                         {"authorization": "Bearer synthetic-key"})
        limit = "max_output_tokens" if route.protocol == "responses" else "max_tokens"
        body = json.dumps({"model": "synthetic-model", limit: 16,
                           "stream": True, "messages": []}).encode()
        request = urllib.request.Request(
            origin + route.local_base_path + route.request_target,
            data=body, method="POST",
            headers={"content-type": "application/json", **token_headers})
        with urllib.request.urlopen(request, timeout=3) as response:
            assert response.status == 200
            assert response.headers["content-type"] == "text/event-stream"
            assert response.read() == _route_sse(route.protocol)
    assert sent == [route.upstream_url]
    _await_phase(journal, "completed")


def test_proxy_forwards_only_selected_route_after_durable_attempt(tmp_path):
    journal, limits = _ready(tmp_path)
    seen = []

    def fake_transport(url, headers, body, deadline):
        pending = journal.snapshot()["provider_attempts"][-1]
        assert pending["phase"] == "may_have_dispatched"
        assert pending["route"] == "opencode-go-chat"
        assert url == "https://opencode.ai/zen/go/v1/chat/completions"
        assert headers["authorization"] == "Bearer synthetic-key"
        assert "host" not in headers
        seen.append(url)
        return ProviderHttpResponse(200, "text/event-stream", _chat_sse())

    with AcpJudgmentProviderProxy(
            journal, route_name="opencode-go-chat", model="synthetic-model",
            credential="synthetic-key", limits=limits,
            transport=fake_transport) as proxy:
        assert proxy.base_url.endswith("/v1")
        origin = proxy.base_url.removesuffix("/v1")
        assert _post(origin, path="/v1/models")[0] == 502
        assert journal.snapshot().get("provider_attempts") is None
        status, body = _post(origin)
        assert status == 200 and body == _chat_sse()
        _await_phase(journal, "completed")
        assert _post(origin, authorization="Bearer wrong")[0] == 502
        assert len(journal.snapshot()["provider_attempts"]) == 1
    assert len(seen) == 1


def test_lost_provider_response_latches_unknown_and_blocks_retry(tmp_path):
    journal, limits = _ready(tmp_path)
    sent = []

    def lost_response(url, headers, body, deadline):
        sent.append(url)
        assert journal.snapshot()["provider_attempts"][0]["phase"] == "may_have_dispatched"
        raise OSError("synthetic provider connection loss")

    with AcpJudgmentProviderProxy(
            journal, route_name="opencode-go-chat", model="synthetic-model",
            credential="synthetic-key", limits=limits,
            transport=lost_response) as proxy:
        origin = proxy.base_url.removesuffix("/v1")
        assert _post(origin)[0] == 502
        _await_phase(journal, "unknown")
        assert _post(origin)[0] == 502
    assert len(sent) == 1


def test_next_call_waits_for_previous_delivery_and_durable_settlement(tmp_path):
    journal, limits = _ready(tmp_path)
    original_settle = journal.settle_provider_attempt
    settling = threading.Event()
    release = threading.Event()

    def delayed_settle(**kwargs):
        if kwargs["index"] == 1:
            settling.set()
            assert release.wait(3)
        return original_settle(**kwargs)

    journal.settle_provider_attempt = delayed_settle
    outcomes = []

    def call(origin):
        outcomes.append(_post(origin)[0])

    with AcpJudgmentProviderProxy(
            journal, route_name="opencode-go-chat", model="synthetic-model",
            credential="synthetic-key", limits=limits,
            transport=lambda *_: ProviderHttpResponse(200, "text/event-stream", _chat_sse())) as proxy:
        origin = proxy.base_url.removesuffix("/v1")
        first = threading.Thread(target=call, args=(origin,))
        first.start()
        assert settling.wait(3)
        second = threading.Thread(target=call, args=(origin,))
        second.start()
        time.sleep(0.05)
        assert len(journal.snapshot()["provider_attempts"]) == 1
        release.set()
        first.join(timeout=3)
        second.join(timeout=3)
        assert not first.is_alive() and not second.is_alive()
    assert sorted(outcomes) == [200, 200]
    assert [row["phase"] for row in journal.snapshot()["provider_attempts"]] == [
        "completed", "completed"]


def test_close_waits_for_inflight_dispatch_and_no_new_send_after_return(tmp_path):
    journal, limits = _ready(tmp_path)
    dispatched = threading.Event()
    release = threading.Event()
    close_returned = threading.Event()
    sent = []

    def held_transport(url, headers, body, deadline):
        sent.append(url)
        dispatched.set()
        assert release.wait(3)
        return ProviderHttpResponse(200, "text/event-stream", _chat_sse())

    proxy = AcpJudgmentProviderProxy(
        journal, route_name="opencode-go-chat", model="synthetic-model",
        credential="synthetic-key", limits=limits, transport=held_transport)
    proxy.__enter__()
    origin = proxy.base_url.removesuffix("/v1")
    def send_during_close():
        try:
            _post(origin)
        except OSError:
            pass

    caller = threading.Thread(target=send_during_close)
    caller.start()
    assert dispatched.wait(3)
    closer = threading.Thread(target=lambda: (proxy.close(), close_returned.set()))
    closer.start()
    time.sleep(0.05)
    assert not close_returned.is_set()
    release.set()
    caller.join(timeout=3)
    closer.join(timeout=3)
    assert not caller.is_alive() and not closer.is_alive() and close_returned.is_set()
    assert len(sent) == 1
    assert journal.snapshot()["provider_attempts"][0]["phase"] == "unknown"
    with pytest.raises(urllib.error.URLError):
        _post(origin)
    assert len(sent) == 1


def test_isolated_transport_abort_kills_blocked_resolution(tmp_path):
    marker = tmp_path / "dns-started"
    stalled_worker = "from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text('resolving'); time.sleep(60)"
    transport = _IsolatedHttpsTransport(
        command=(sys.executable, "-c", stalled_worker, str(marker)))
    result = []

    def send():
        try:
            transport("https://example.invalid", {}, b"request", time.monotonic() + 10)
        except (OSError, TimeoutError):
            result.append("unknown")

    caller = threading.Thread(target=send)
    caller.start()
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), "transport worker did not reach the blocked resolver"
    started = time.monotonic()
    transport.abort()
    caller.join(timeout=2)
    assert not caller.is_alive()
    assert time.monotonic() - started < 2
    assert result == ["unknown"]
    with pytest.raises(TimeoutError):
        transport("https://example.invalid", {}, b"request", time.monotonic() + 10)


def test_default_https_worker_loads_and_fails_closed_on_local_refusal():
    transport = _IsolatedHttpsTransport()
    with pytest.raises(OSError):
        transport("https://127.0.0.1:1/v1/chat/completions", {}, b"{}",
                  time.monotonic() + 3)
    transport.abort()


def test_proxy_close_kills_blocked_https_worker_and_latches_unknown(tmp_path):
    journal, limits = _ready(tmp_path)
    marker = tmp_path / "dns-started"
    stalled_worker = "from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text('resolving'); time.sleep(60)"
    transport = _IsolatedHttpsTransport(
        command=(sys.executable, "-c", stalled_worker, str(marker)))
    proxy = AcpJudgmentProviderProxy(
        journal, route_name="opencode-go-chat", model="synthetic-model",
        credential="synthetic-key", limits=limits, transport=transport)
    proxy.__enter__()
    origin = proxy.base_url.removesuffix("/v1")
    outcome = []
    def send_while_worker_stalls():
        try:
            outcome.append(_post(origin)[0])
        except OSError:
            outcome.append("disconnected")

    caller = threading.Thread(target=send_while_worker_stalls)
    caller.start()
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), "worker did not reach the stalled resolution phase"
    started = time.monotonic()
    proxy.close()
    caller.join(timeout=2)
    assert not caller.is_alive() and outcome[0] in (502, "disconnected")
    assert time.monotonic() - started < 2
    assert journal.snapshot()["provider_attempts"][0]["phase"] == "unknown"
    with pytest.raises(urllib.error.URLError):
        _post(origin)


def test_proxy_close_interrupts_stalled_local_client_body(tmp_path):
    journal, limits = _ready(tmp_path)
    proxy = AcpJudgmentProviderProxy(
        journal, route_name="opencode-go-chat", model="synthetic-model",
        credential="synthetic-key", limits=limits,
        transport=lambda *_: pytest.fail("incomplete body reached upstream"))
    proxy.__enter__()
    port = proxy._server.server_address[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    try:
        client.sendall(
            b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nAuthorization: Bearer synthetic-key\r\n"
            b"Content-Length: 100\r\n\r\n{}")
        deadline = time.monotonic() + 2
        while proxy._active_client is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert proxy._active_client is not None
        started = time.monotonic()
        proxy.close()
        assert time.monotonic() - started < 2
        assert journal.snapshot().get("provider_attempts") is None
    finally:
        client.close()


def test_proxy_close_interrupts_partial_headers_before_handler_entry(tmp_path):
    journal, limits = _ready(tmp_path)
    proxy = AcpJudgmentProviderProxy(
        journal, route_name="opencode-go-chat", model="synthetic-model",
        credential="synthetic-key", limits=limits,
        transport=lambda *_: pytest.fail("partial headers reached upstream"))
    proxy.__enter__()
    port = proxy._server.server_address[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    try:
        client.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nContent-Type:")
        deadline = time.monotonic() + 2
        while not proxy._clients and time.monotonic() < deadline:
            time.sleep(0.01)
        assert proxy._clients
        started = time.monotonic()
        proxy.close()
        assert time.monotonic() - started < 2
        assert journal.snapshot().get("provider_attempts") is None
        proxy.close()
    finally:
        client.close()


def test_close_failure_still_closes_listener_and_can_be_rechecked(tmp_path):
    journal, limits = _ready(tmp_path)
    proxy = AcpJudgmentProviderProxy(
        journal, route_name="opencode-go-chat", model="synthetic-model",
        credential="synthetic-key", limits=limits,
        transport=lambda *_: pytest.fail("unexpected upstream"))
    proxy.__enter__()
    origin = proxy.base_url.removesuffix("/v1")
    proxy._dispatch_lock.acquire()
    try:
        with pytest.raises(Exception, match="dispatch did not stop"):
            proxy.close()
        with pytest.raises(urllib.error.URLError):
            _post(origin)
    finally:
        proxy._dispatch_lock.release()
    proxy.close()
    assert proxy._close_complete


def test_https_worker_environment_excludes_unrelated_secrets(monkeypatch):
    monkeypatch.setenv("BYQ_RUNTIME_JUDGMENT_TOKEN", "synthetic-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.invalid")
    env = _IsolatedHttpsTransport._worker_environment()
    assert set(env) == {"PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE"}
    assert "synthetic-secret" not in str(env)
    assert "untrusted.invalid" not in str(env)
    assert os.path.isdir(env["PYTHONPATH"].split(os.pathsep)[0])


def test_https_worker_stdout_bound_is_checked_while_reading():
    flood = "import sys; sys.stdout.buffer.write(b'x' * (17 * 1024 * 1024)); sys.stdout.flush()"
    transport = _IsolatedHttpsTransport(command=(sys.executable, "-c", flood))
    with pytest.raises(OSError, match="exceeds bound"):
        transport("https://127.0.0.1:1", {}, b"{}", time.monotonic() + 3)
    transport.abort()


def test_abort_after_worker_registration_prevents_request_delivery(tmp_path):
    marker = tmp_path / "received-secret"
    receiver = ("from pathlib import Path; import sys; data=sys.stdin.buffer.read(); "
                "Path(sys.argv[1]).write_bytes(data)")
    transport = _IsolatedHttpsTransport(
        command=(sys.executable, "-c", receiver, str(marker)))
    registered = threading.Event()
    release = threading.Event()
    original_exchange = transport._exchange

    def held_exchange(process, payload, deadline):
        registered.set()
        assert release.wait(3)
        return original_exchange(process, payload, deadline)

    transport._exchange = held_exchange
    outcomes = []

    def send():
        try:
            transport("https://127.0.0.1:1", {"authorization": "synthetic-secret"},
                      b"prompt", time.monotonic() + 5)
        except (OSError, TimeoutError):
            outcomes.append("unknown")

    caller = threading.Thread(target=send)
    caller.start()
    assert registered.wait(3)
    transport.abort()
    release.set()
    caller.join(timeout=2)
    assert not caller.is_alive() and outcomes == ["unknown"]
    assert not marker.exists()
