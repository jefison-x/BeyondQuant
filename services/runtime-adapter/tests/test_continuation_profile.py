from __future__ import annotations

import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.continuation_budget import create_guard_patch, read_request_guard, validate_reservation
from app.research_request_gate import RequestGateBlocked, RequestGateProxy, ResearchRequestGate
from app.runtime import RuntimeAdapter
from packages.contracts.continuation_request import (
    PROFILE_ID,
    exceeded_request_limits,
    profile_binding,
    request_limits,
    validate_request_usage,
)


def _reservation(**changes):
    value = {
        "schema_version": "task-continuation-reservation.v2",
        "reservation_id": "continuation_" + "a" * 32,
        "task_id": "task_" + "b" * 32,
        "owner": "owner-a",
        "workspace_id": "workspace-a",
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    value.update(changes)
    return value


def _provider_body(**changes):
    value = {
        "model": "deepseek-v4-flash",
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "synthetic only"}],
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


def _usage_body(*, input_tokens=12, output_tokens=4):
    return json.dumps({"usage": {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }}).encode()


def _gate(*, journal=None):
    return ResearchRequestGate(request_limits(), execution_profile=profile_binding(),
        request_id="continuation_" + "a" * 32, journal=journal)


def test_v2_reservation_is_exact_profile_bound_and_has_no_cumulative_money_allowance():
    value = _reservation()
    assert validate_reservation(value, owner="owner-a", workspace="workspace-a") == value
    for invalid in [
        {**value, "token_limit": 16_000_000},
        {**value, "schema_version": "task-continuation-reservation.v1"},
        {**value, "request_limits": {**value["request_limits"], "max_tool_calls": 17}},
        {**value, "execution_profile": {**value["execution_profile"], "profile_sha256": "0" * 64}},
    ]:
        with pytest.raises(ValueError):
            validate_reservation(invalid, owner="owner-a", workspace="workspace-a")
    with pytest.raises(ValueError, match="ownership"):
        validate_reservation(value, owner="other", workspace="workspace-a")
    with pytest.raises(ValueError, match="ownership"):
        validate_reservation(value, owner="owner-a", workspace="other")


def test_guard_patch_binds_v2_identity_and_has_no_token_limit(tmp_path):
    composition = tmp_path / "composition.yml"
    composition.write_text(
        "- id: mcp-byq\n  config:\n    headers:\n"
        "      X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID\n",
        encoding="utf-8",
    )
    deadline_epoch_ms = int(time.time() * 1000) + request_limits()["deadline_ms"]
    patch, journal = create_guard_patch(
        composition, tmp_path / "private", _reservation(), deadline_epoch_ms=deadline_epoch_ms)
    text = patch.read_text(encoding="utf-8")
    assert PROFILE_ID in text
    assert "task-continuation-reservation.v2" not in text  # the config carries only the binding
    assert "tokenLimit" not in text and "token_limit" not in text
    assert "max_tool_calls" in text
    assert str(deadline_epoch_ms) in text
    assert journal.name == "continuation-tool-guard.jsonl"
    assert "X-BYQ-Continuation-Reservation" in text


def test_watchdog_wait_tracks_deadline_without_one_second_slack():
    assert RuntimeAdapter._watchdog_wait_timeout(None, 10.0) == 1.0
    assert RuntimeAdapter._watchdog_wait_timeout(10.05, 10.0) == pytest.approx(0.05)
    assert RuntimeAdapter._watchdog_wait_timeout(10.0, 10.0) == 0.0
    assert RuntimeAdapter._watchdog_wait_timeout(9.0, 10.0) == 0.0


def test_dsh_tool_journal_is_exact_request_local_evidence(tmp_path):
    reservation = _reservation()
    path = tmp_path / "guard.jsonl"
    rows = [{
        "schema_version": "continuation-tool-guard.v1",
        "reservation_id": reservation["reservation_id"],
        "execution_profile": reservation["execution_profile"],
        "request_limits": reservation["request_limits"],
        "ready": True,
    }]
    for index in range(1, 17):
        rows.append({"phase": "tool", "reservation_id": reservation["reservation_id"],
            "call": index, "tool_name": "mcp__byq__byq_research_get"})
    rows.append({"phase": "blocked", "reservation_id": reservation["reservation_id"],
        "blocked_reason": "BYQ_CONTINUATION_TOOL_LIMIT", "tool_name": "mcp__byq__byq_research_get"})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert read_request_guard(path, reservation, terminal=True) == {
        "reservation_id": reservation["reservation_id"],
        "tool_calls": 16,
        "blocked_reason": "BYQ_CONTINUATION_TOOL_LIMIT",
        "status": "settled",
    }


def test_sixteenth_provider_attempt_is_counted_and_seventeenth_blocked_without_fake_overrun():
    gate = _gate()
    body = _provider_body()
    for _ in range(16):
        receipt = gate.before_request(body)
        assert gate.complete(receipt, status=200, body=_usage_body())["forward"]
    with pytest.raises(RequestGateBlocked, match="provider_call_limit"):
        gate.before_request(body)
    usage = gate.request_usage(tool_calls=0)
    admission = usage["admission_usage"]
    assert admission["provider_calls"] == admission["provider_attempts"] == 16
    assert admission["max_input_bytes"] == len(body)
    assert admission["max_declared_output_tokens"] == 8
    assert admission["elapsed_ms"] < request_limits()["deadline_ms"]
    assert usage["limit_violations"] == []
    assert gate.has_blocked_request()
    assert exceeded_request_limits(usage) == []


def test_provider_actual_output_over_declared_is_retained_as_a_limit_fact():
    gate = _gate()
    receipt = gate.before_request(_provider_body())
    result = gate.complete(receipt, status=200, body=_usage_body(output_tokens=9))
    assert result["forward"] is False
    assert result["reason"] == "output_tokens_exceeded"
    usage = gate.request_usage(tool_calls=0)
    assert usage["actual_usage"]["output_tokens"] == 9
    # Cache-read usage is absent from this synthetic response, so the provider
    # output and violation are known while the complete usage vector is partial.
    assert usage["actual_usage"]["completeness"] == "partial"
    assert usage["limit_violations"] == ["provider_declared_output_exceeded"]
    assert exceeded_request_limits(usage) == ["provider_declared_output_exceeded"]


def test_unknown_provider_usage_stays_unknown_and_does_not_invent_ceiling_as_consumption():
    gate = _gate()
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=b'{"choices":[]}')
    usage = gate.request_usage(tool_calls=0)
    assert usage["admission_usage"]["declared_output_tokens"] == 8
    assert usage["actual_usage"] == {
        "input_tokens": "unknown", "cache_read_tokens": "unknown", "output_tokens": "unknown",
        "provider_attempts": "unknown", "usage_source": "unknown", "completeness": "unknown",
    }
    assert usage["limit_violations"] == []
    assert validate_request_usage(usage) == usage


def test_oversized_ingress_is_refused_before_provider_call_and_not_charged_as_actual():
    gate = _gate()
    with pytest.raises(RequestGateBlocked, match="input_bytes_limit"):
        gate.reject_oversized_body(request_limits()["max_input_bytes"] + 1)
    usage = gate.request_usage(tool_calls=0)
    assert usage["admission_usage"]["provider_calls"] == 0
    assert usage["actual_usage"]["provider_attempts"] == 0
    assert usage["limit_violations"] == []
    assert gate.has_blocked_request()



def test_loopback_proxy_counts_retry_and_compaction_posts_at_the_http_boundary(monkeypatch):
    from app import research_request_gate as gate_module

    captured = []
    read_errors = []
    original_read_response = gate_module._read_response

    def observe_read_response(response, gate):
        try:
            return original_read_response(response, gate)
        except Exception as error:
            sock = gate_module._response_socket(response)
            read_errors.append({
                "response_type": type(response).__name__,
                "response_fp_type": type(getattr(response, "fp", None)).__name__,
                "response_fp_none": getattr(response, "fp", object()) is None,
                "response_length": getattr(response, "length", None),
                "socket_found": sock is not None,
                "socket_closed": getattr(sock, "_closed", None),
                "error_type": type(error).__name__,
                "error": str(error)[:160],
            })
            raise

    monkeypatch.setattr(gate_module, "_read_response", observe_read_response)

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers.get("content-length", "0")))))
            body = b'{"error":"synthetic retryable failure"}'
            self.send_response(503)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    gate = _gate()
    proxy = RequestGateProxy(gate, "https://api.deepseek.com")
    proxy._server.upstream = f"http://127.0.0.1:{provider.server_port}"
    proxy.__enter__()
    bodies = []
    try:
        for index in range(16):
            # The repeated full-context request is a retry; the shorter request
            # models a compacted context. Both are counted as actual HTTP posts.
            messages = ([{"role": "user", "content": "full context " + ("history " * 100)}]
                if index % 2 == 0 else [{"role": "user", "content": "compacted summary"}])
            value = {
                "model": "deepseek-v4-flash", "max_tokens": 8192,
                "messages": messages, "tools": [{"type": "function", "function": {
                    "name": "mcp__byq__byq_research_get",
                    "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}},
                }}],
            }
            body = json.dumps(value, separators=(",", ":")).encode()
            bodies.append((value, body))
            response = httpx.post(proxy.base_url + "/chat/completions", content=body, timeout=3)
            assert response.status_code == 503, {
                "response_error": response.json().get("error", {}).get("code"),
                "provider_posts": len(captured),
                "gate_receipts": gate.receipts(),
                "read_errors": read_errors,
            }
        denied = httpx.post(proxy.base_url + "/chat/completions", content=bodies[-1][1], timeout=3)
        assert denied.status_code == 429
        usage = gate.request_usage(tool_calls=0)
        admission = usage["admission_usage"]
        assert len(captured) == 16
        assert admission["provider_calls"] == admission["provider_attempts"] == 16
        assert admission["input_bytes"] == sum(len(body) for _, body in bodies)
        assert admission["max_input_bytes"] == max(len(body) for _, body in bodies)
        assert admission["tool_payload_bytes"] == sum(
            len(json.dumps(value["tools"], sort_keys=True, separators=(",", ":")).encode())
            for value, _ in bodies)
        assert admission["max_concurrent"] == 1
        assert usage["actual_usage"]["completeness"] == "unknown"
        assert gate.has_blocked_request()
    finally:
        proxy.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)


def test_unknown_provider_transport_result_blocks_any_second_external_post():
    captured = []

    class DisconnectingProvider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers.get("content-length", "0")))))
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()

    provider = ThreadingHTTPServer(("127.0.0.1", 0), DisconnectingProvider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    gate = _gate()
    proxy = RequestGateProxy(gate, "https://api.deepseek.com")
    proxy._server.upstream = f"http://127.0.0.1:{provider.server_port}"
    proxy.__enter__()
    body = _provider_body()
    try:
        first = httpx.post(proxy.base_url + "/chat/completions", content=body, timeout=3)
        assert first.status_code == 502
        assert first.json()["error"]["code"] == "provider_outcome_unknown"

        # Model-side retry reaches the request proxy, but the closed request
        # scope refuses it before opening a second provider connection.
        second = httpx.post(proxy.base_url + "/chat/completions", content=body, timeout=3)
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "cancelled"
        assert len(captured) == 1

        usage = gate.request_usage(tool_calls=0)
        assert usage["admission_usage"]["provider_calls"] == 1
        assert usage["admission_usage"]["provider_attempts"] == 1
        assert usage["actual_usage"]["provider_attempts"] == "unknown"
        assert usage["actual_usage"]["completeness"] == "unknown"
        assert [row["reason"] for row in gate.receipts() if row["phase"] in {"completed", "rejected"}] == [
            "provider_outcome_unknown", "cancelled",
        ]
    finally:
        proxy.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)


def test_closing_proxy_interrupts_an_active_slow_upstream_and_client():
    provider_started = threading.Event()
    provider_closed = threading.Event()
    client_done = threading.Event()
    client_errors = []

    class SlowProvider(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            provider_started.set()
            try:
                while True:
                    self.wfile.write(b"1\r\nx\r\n")
                    self.wfile.flush()
                    time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError, OSError):
                provider_closed.set()

    provider = ThreadingHTTPServer(("127.0.0.1", 0), SlowProvider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    gate = _gate()
    proxy = RequestGateProxy(gate, "https://api.deepseek.com")
    proxy._server.upstream = f"http://127.0.0.1:{provider.server_port}"
    proxy.__enter__()

    def request():
        try:
            httpx.post(proxy.base_url + "/chat/completions", content=_provider_body(), timeout=10)
        except httpx.HTTPError as error:
            client_errors.append(type(error).__name__)
        finally:
            client_done.set()

    client_thread = threading.Thread(target=request, daemon=True)
    client_thread.start()
    try:
        assert provider_started.wait(2)
        close_started = time.monotonic()
        proxy.close()
        assert time.monotonic() - close_started < 2.5
        assert client_done.wait(2)
        client_thread.join(timeout=1)
        assert not client_thread.is_alive()
        assert provider_closed.wait(2)
        assert client_errors
        assert gate.request_usage(tool_calls=0)["admission_usage"]["provider_calls"] == 1
    finally:
        proxy.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)

def test_continuation_proxy_rejects_redirect_without_following_or_forwarding_location():
    redirected = []

    class Destination(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            redirected.append(self.path)
            self.send_response(200)
            self.end_headers()

    destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)
    destination_thread = threading.Thread(target=destination.serve_forever, daemon=True)
    destination_thread.start()

    class RedirectProvider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/escaped")
            self.send_header("content-length", "0")
            self.end_headers()

    provider = ThreadingHTTPServer(("127.0.0.1", 0), RedirectProvider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    gate = _gate()
    try:
        with pytest.raises(ValueError, match="official DeepSeek"):
            RequestGateProxy(gate, f"http://127.0.0.1:{provider.server_port}")
        with RequestGateProxy(gate, f"https://api.deepseek.com") as proxy:
            # The test may point only this local fixture at a local fake upstream;
            # production construction is separately locked to api.deepseek.com.
            proxy._upstream = f"http://127.0.0.1:{provider.server_port}"
            proxy._server.upstream = proxy._upstream
            response = httpx.post(proxy.base_url + "/chat/completions", content=_provider_body(), timeout=3)
        assert response.status_code == 502
        assert "Location" not in response.headers
        assert redirected == []
        assert gate.request_usage(tool_calls=0)["admission_usage"]["provider_calls"] == 1
        assert gate.has_blocked_request()
    finally:
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)
        destination.shutdown()
        destination.server_close()
        destination_thread.join(timeout=2)


def test_slow_trickle_is_cut_off_by_total_deadline_and_proxy_close_is_bounded():
    sent = threading.Event()

    class SlowProvider(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            try:
                for _ in range(80):
                    self.wfile.write(b"1\r\nx\r\n")
                    self.wfile.flush()
                    sent.set()
                    time.sleep(0.02)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), SlowProvider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    gate = _gate()
    # Use the contract's exact deadline while placing this isolated fixture near
    # its end; the slow trickle must not renew the deadline for each recv.
    gate._continuation_started = time.monotonic() - (request_limits()["deadline_ms"] / 1000 - 0.25)
    proxy = RequestGateProxy(gate, "https://api.deepseek.com")
    proxy._upstream = f"http://127.0.0.1:{provider.server_port}"
    proxy._server.upstream = proxy._upstream
    proxy.__enter__()
    started = time.monotonic()
    try:
        response = httpx.post(proxy.base_url + "/chat/completions", content=_provider_body(), timeout=2)
        elapsed = time.monotonic() - started
        assert sent.wait(1)
        assert response.status_code == 504
        assert elapsed < 1.5
        rows = gate.receipts()
        assert sum(row.get("phase") == "admitted" for row in rows) == 1
        assert sum(row.get("phase") == "completed" for row in rows) == 1
        assert rows[-1]["reason"] == "deadline_exceeded"
        assert gate.request_usage(tool_calls=0)["admission_usage"]["provider_calls"] == 1
        close_started = time.monotonic()
        proxy.close()
        assert time.monotonic() - close_started < 2.5
    finally:
        proxy.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)
