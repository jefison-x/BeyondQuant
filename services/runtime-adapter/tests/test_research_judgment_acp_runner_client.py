"""Focused, keyless transport tests for the dedicated ACP judgment runner."""

from __future__ import annotations

import base64
import json
import os
import socketserver
import struct
import threading
import time
from contextlib import contextmanager

import pytest

from app import research_judgment_acp_runner_client as runner


RAW_SECRET = bytes(range(32))
ENCODED_SECRET = base64.urlsafe_b64encode(RAW_SECRET).decode("ascii").rstrip("=")
SCOPE = {
    "task_id": "task-20261005-a",
    "call_identity": "call-20261005-a",
    "attempt_binding": "attempt-20261005-a",
    "root_run_id": "0123456789abcdef0123456789abcdef",
    "runtime_boot_id": "boot-20261005-a",
    "authority_epoch": 7,
}
EXPECTED_CWD = "/var/lib/byq/acp-judgment-sessions/" + runner.scope_digest(SCOPE)
ACP_INPUT = b'{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
OVERLAY = base64.b64encode(b'[{"providers":[]}]').decode("ascii")
PROXY_TOKEN = "byq-acp-proxy-" + "A" * 43


def _environment() -> dict[str, str]:
    return {
        "BYQ_MCP_URL": "http://mcp:8300/mcp/v1",
        "BYQ_MCP_ACP_IDENTITY_MODE": "research-judgment-root-v1",
        "BYQ_MCP_ACP_JUDGMENT_TASK_ID": SCOPE["task_id"],
        "BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY": SCOPE["call_identity"],
        "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY": "derived-root-key-synthetic",
        "BYQ_RUNTIME_BOOT_ID": SCOPE["runtime_boot_id"],
        "BYQ_OWNER_PRINCIPAL": "owner-a",
        "BYQ_WORKSPACE_ID": "workspace-a",
        "BYQ_ACTOR_PRINCIPAL": "byq-product-agent-session-a",
        "BYQ_TRACE_ID": "trace-a",
        "BYQ_SESSION_ID": "session-a",
        "BYQ_DSH_RUN_ID": "dsh-run-a",
        "BYQ_ROOT_RUN_ID": SCOPE["root_run_id"],
    }


def _reply(body: dict[str, object]) -> bytes:
    signed = {**body, "mac": runner.sign_runner_reply(body, RAW_SECRET)}
    return runner.encode_frame(0x81, runner.canonical_json(signed))


def _signed_frame(frame_type: int, body: dict[str, object]) -> bytes:
    signed = {**body, "mac": runner.sign_runner_reply(body, RAW_SECRET)}
    return runner.encode_frame(frame_type, runner.canonical_json(signed))


def _forged_signed_frame(frame_type: int, body: dict[str, object]) -> bytes:
    signed = {**body, "mac": runner.sign_runner_reply(body, RAW_SECRET)}
    mac = str(signed["mac"])
    signed["mac"] = ("0" if mac[0] != "0" else "1") + mac[1:]
    return runner.encode_frame(frame_type, runner.canonical_json(signed))


def _ready(challenge: str, nonce: str, digest: str, cwd: str = EXPECTED_CWD):
    return {
        "v": 1, "challenge": challenge, "nonce": nonce,
        "scope_digest": digest, "cwd": cwd,
    }


def _exit(challenge: str, nonce: str, digest: str, *, cleanup: str = "proven"):
    return {
        "v": 1, "challenge": challenge, "nonce": nonce,
        "scope_digest": digest, "code": 0, "signal": None,
        "reason": "cancelled", "cleanup": cleanup,
    }


class _FakeRunner(socketserver.ThreadingUnixStreamServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, path, scenario):
        self.scenario = scenario
        self.start_message = None
        self.received_cancel = threading.Event()
        self.received_stdin_event = threading.Event()
        self.received_stdin = None
        super().__init__(str(path), _FakeRunnerHandler)


class _FakeRunnerHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        challenge = "a" * 64
        if self.server.scenario == "forged_challenge":
            body = {"v": 1, "challenge": challenge}
            conn.sendall(_forged_signed_frame(runner.CHALLENGE, body))
            return
        conn.sendall(_signed_frame(
            runner.CHALLENGE, {"v": 1, "challenge": challenge},
        ))
        frame_type, payload = runner._read_frame(conn)
        assert frame_type == runner.START
        start = json.loads(payload)
        self.server.start_message = start
        unsigned_start = {key: value for key, value in start.items() if key != "mac"}
        assert start["mac"] == runner.sign_runner_start(unsigned_start, RAW_SECRET)
        nonce = start["nonce"]
        digest = runner.scope_digest(start["scope"])
        scenario = self.server.scenario
        ready = _ready(challenge, nonce, digest)
        if scenario == "wrong_scope_ready":
            ready["scope_digest"] = "b" * 64
            conn.sendall(_signed_frame(runner.READY, ready))
            return
        if scenario == "wrong_cwd":
            ready["cwd"] = "/var/lib/byq/acp-judgment-sessions/wrong"
        conn.sendall(_signed_frame(runner.READY, ready))

        if scenario == "eof":
            return
        if scenario == "timeout":
            time.sleep(0.3)
            return
        if scenario == "oversize":
            conn.sendall(struct.pack("!I", runner.MAX_FRAME_BYTES + 1))
            return
        if scenario in {"forged_exit", "wrong_scope_exit", "cancel_unknown", "wrong_cwd", "signal_cancel"}:
            frame_type, cancel_payload = runner._read_frame(conn)
            assert frame_type == runner.CANCEL and cancel_payload == b""
            self.server.received_cancel.set()
            exit_body = _exit(challenge, nonce, digest)
            if scenario == "forged_exit":
                conn.sendall(_forged_signed_frame(runner.EXIT, exit_body))
            elif scenario == "wrong_scope_exit":
                exit_body["scope_digest"] = "c" * 64
                conn.sendall(_signed_frame(runner.EXIT, exit_body))
            elif scenario == "cancel_unknown":
                exit_body["cleanup"] = "unknown"
                exit_body["code"] = None
                conn.sendall(_signed_frame(runner.EXIT, exit_body))
            elif scenario == "signal_cancel":
                exit_body["code"] = None
                exit_body["signal"] = 15
                conn.sendall(_signed_frame(runner.EXIT, exit_body))
            else:
                conn.sendall(_signed_frame(runner.EXIT, exit_body))
            return
        if scenario == "echo_cancel":
            frame_type, stdin_payload = runner._read_frame(conn)
            assert frame_type == runner.STDIN
            self.server.received_stdin = stdin_payload
            self.server.received_stdin_event.set()
            conn.sendall(runner.encode_frame(runner.STDOUT, stdin_payload))
            frame_type, cancel_payload = runner._read_frame(conn)
            assert frame_type == runner.CANCEL and cancel_payload == b""
            self.server.received_cancel.set()
            conn.sendall(_signed_frame(runner.EXIT, _exit(challenge, nonce, digest)))
            return
        raise AssertionError("unhandled fake runner scenario")


@contextmanager
def _fake_runner(tmp_path, scenario):
    path = tmp_path / "control.sock"
    server = _FakeRunner(path, scenario)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _client(path, *, timeout=0.1):
    return runner.RunnerClient(
        path, ENCODED_SECRET, connect_timeout_s=timeout,
        cleanup_timeout_s=timeout,
    )


def _start(client, *, cwd=EXPECTED_CWD):
    return client.start(
        scope=SCOPE, env=_environment(),
        proxy_token_env="DEEPSEEK_API_KEY", proxy_token=PROXY_TOKEN,
        overlay_b64=OVERLAY, deadline_at_ms=int(time.time() * 1000) + 5000,
        expected_cwd=cwd,
    )


def test_runner_client_relays_acp_bytes_and_accepts_only_signed_cleanup(tmp_path):
    with _fake_runner(tmp_path, "echo_cancel") as (server, path):
        session = _start(_client(path, timeout=1))
        assert session.cwd == EXPECTED_CWD
        session.send_stdin(ACP_INPUT)
        assert session.receive(timeout_s=1) == ACP_INPUT
        session.cancel()
        receipt = session.wait_exit(timeout_s=1)

    assert server.start_message["scope"] == SCOPE
    assert "DEEPSEEK_API_KEY" not in server.start_message["env"]
    assert "OPENCODE_API_KEY" not in server.start_message["env"]
    assert server.start_message["proxy_token"] == PROXY_TOKEN
    assert server.received_stdin == ACP_INPUT
    assert server.received_cancel.is_set()
    assert receipt == runner.RunnerExit(0, None, "cancelled", "proven")
    assert session.cleanup == "proven"


def test_signed_signal_exit_proves_cancelled_child_cleanup(tmp_path):
    with _fake_runner(tmp_path, "signal_cancel") as (server, path):
        session = _start(_client(path, timeout=1))
        session.cancel()
        receipt = session.wait_exit(timeout_s=1)

    assert server.received_cancel.is_set()
    assert receipt == runner.RunnerExit(None, 15, "cancelled", "proven")
    assert session.cleanup == "proven"


def test_stdio_relay_forwards_bytes_then_waits_for_cancel_exit(tmp_path):
    with _fake_runner(tmp_path, "echo_cancel") as (server, path):
        session = _start(_client(path, timeout=1))
        input_read, input_write = os.pipe()
        output_read, output_write = os.pipe()
        cancel = threading.Event()
        try:
            os.write(input_write, ACP_INPUT)

            def cancel_after_dispatch():
                assert server.received_stdin_event.wait(1)
                cancel.set()

            request = threading.Thread(target=cancel_after_dispatch, daemon=True)
            request.start()
            receipt = session.relay_stdio(
                input_read, output_write, cancel_event=cancel,
                cancel_exit_timeout_s=1,
            )
            request.join(timeout=1)
            output = os.read(output_read, len(ACP_INPUT))
        finally:
            for fd in (input_read, input_write, output_read, output_write):
                os.close(fd)

    assert output == ACP_INPUT
    assert receipt.cleanup_proven
    assert server.received_cancel.is_set()


def test_forged_challenge_is_rejected_before_start_is_sent(tmp_path):
    with _fake_runner(tmp_path, "forged_challenge") as (server, path):
        with pytest.raises(runner.RunnerCleanupUnknown):
            _start(_client(path, timeout=1))
    assert server.start_message is None


def test_signed_ready_for_another_scope_is_rejected(tmp_path):
    with _fake_runner(tmp_path, "wrong_scope_ready") as (_server, path):
        with pytest.raises(runner.RunnerCleanupUnknown):
            _start(_client(path, timeout=1))


@pytest.mark.parametrize("scenario", ["forged_exit", "wrong_scope_exit"])
def test_bad_exit_signature_or_scope_never_proves_cleanup(tmp_path, scenario):
    with _fake_runner(tmp_path, scenario) as (_server, path):
        session = _start(_client(path, timeout=1))
        session.cancel()
        with pytest.raises(runner.RunnerCleanupUnknown):
            session.wait_exit(timeout_s=1)
        assert session.cleanup == "unknown"


@pytest.mark.parametrize("scenario", ["eof", "timeout", "oversize"])
def test_eof_timeout_and_oversize_frame_leave_cleanup_unknown(tmp_path, scenario):
    with _fake_runner(tmp_path, scenario) as (_server, path):
        session = _start(_client(path, timeout=1))
        if scenario == "timeout":
            with pytest.raises(runner.RunnerCleanupUnknown):
                session.wait_exit(timeout_s=0.05)
        else:
            with pytest.raises(runner.RunnerCleanupUnknown):
                session.receive(timeout_s=1)
        assert session.cleanup == "unknown"


def test_wrong_cwd_is_cancelled_and_requires_authenticated_cleanup(tmp_path):
    with _fake_runner(tmp_path, "wrong_cwd") as (server, path):
        with pytest.raises(runner.RunnerStartupRejected) as rejected:
            _start(_client(path, timeout=1))
    assert server.received_cancel.is_set()
    assert rejected.value.cleanup == "proven"
    assert rejected.value.exit_receipt.reason == "cancelled"


def test_signed_unknown_exit_remains_unknown(tmp_path):
    with _fake_runner(tmp_path, "cancel_unknown") as (_server, path):
        session = _start(_client(path, timeout=1))
        session.cancel()
        receipt = session.wait_exit(timeout_s=1)
    assert receipt.cleanup == "unknown"
    assert not receipt.cleanup_proven


def test_start_rejects_provider_master_or_non_root_scoped_environment(tmp_path):
    with _fake_runner(tmp_path, "echo_cancel") as (_server, path):
        environment = _environment()
        environment["DEEPSEEK_API_KEY"] = "upstream-secret-must-not-cross"
        with pytest.raises(ValueError, match="environment fields"):
            _client(path).start(
                scope=SCOPE, env=environment, proxy_token_env="DEEPSEEK_API_KEY",
                proxy_token=PROXY_TOKEN, overlay_b64=OVERLAY,
                deadline_at_ms=int(time.time() * 1000) + 5000,
                expected_cwd=EXPECTED_CWD,
            )
