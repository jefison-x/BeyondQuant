"""Keyless control, one-shot and process-reaping tests for the ACP runner."""

from __future__ import annotations

import base64
import hmac
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from services.acp_judgment_runner import server as runner


CONTROL_SECRET = bytes(range(32))
PROXY_TOKEN = "byq-acp-proxy-" + "A" * 43
SCOPE = {
    "task_id": "task_01",
    "call_identity": "call_01",
    "attempt_binding": "attempt_01",
    "root_run_id": "root_01",
    "runtime_boot_id": "boot_01",
    "authority_epoch": 7,
}
ENVIRONMENT = {
    "BYQ_MCP_URL": "http://mcp-acp-judgment:8301/mcp/v1",
    "BYQ_MCP_PRODUCT_URL": "http://mcp:8300/mcp/v1",
    "BYQ_MCP_ACP_IDENTITY_MODE": "research-judgment-root-v1",
    "BYQ_MCP_ACP_JUDGMENT_TASK_ID": SCOPE["task_id"],
    "BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY": SCOPE["call_identity"],
    "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY": "synthetic-derived-root-key",
    "BYQ_RUNTIME_BOOT_ID": SCOPE["runtime_boot_id"],
    "BYQ_OWNER_PRINCIPAL": "owner_01",
    "BYQ_WORKSPACE_ID": "workspace_01",
    "BYQ_ACTOR_PRINCIPAL": "actor_01",
    "BYQ_TRACE_ID": "trace_01",
    "BYQ_SESSION_ID": "session_01",
    "BYQ_DSH_RUN_ID": "run_01",
    "BYQ_ROOT_RUN_ID": SCOPE["root_run_id"],
}
OVERLAY = base64.b64encode(b'[{"id":"synthetic-route"}]').decode("ascii")


def _fake_popen_for_current_uid(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Keep the production UID arguments observable without requiring root in CI."""
    real_popen = subprocess.Popen
    calls: list[dict[str, object]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        observed = dict(kwargs)
        # This test process is an unprivileged developer account. The separate
        # assertion below verifies the production identity and group arguments.
        kwargs.pop("user")
        kwargs.pop("group")
        kwargs.pop("extra_groups")
        calls.append(observed)
        process = real_popen(*args, **kwargs)  # type: ignore[arg-type]
        observed["pid"] = process.pid
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    return calls


def _server(tmp_path: Path, launcher_code: str) -> tuple[runner.JudgmentRunnerServer, threading.Thread]:
    previous_subreaper = runner._prctl_child_subreaper()
    assert runner._prctl_child_subreaper(enabled=True)
    assert runner._prctl_child_subreaper()
    assert runner._read_no_new_privs(os.getpid()) is True
    uid = os.geteuid()
    gid = os.getegid()
    control_dir = tmp_path / "control"
    try:
        server = runner.JudgmentRunnerServer(
            control_dir / "control.sock",
            secret=CONTROL_SECRET,
            state_dir=tmp_path / "state",
            session_root=tmp_path / "sessions",
            launcher=(sys.executable, "-c", launcher_code),
            child_uid=uid,
            child_gid=gid,
            prepare_roots=True,
            ready_file=control_dir / "ready",
            control_gid=gid,
            state_uid=uid,
            state_gid=gid,
            runner_uid=uid,
        )
    except BaseException:
        if runner._prctl_child_subreaper() != previous_subreaper:
            assert runner._prctl_child_subreaper(enabled=previous_subreaper)
        raise
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    server._test_previous_subreaper = previous_subreaper
    return server, thread


def _close_server(server: runner.JudgmentRunnerServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive()
    previous_subreaper = server._test_previous_subreaper
    if runner._prctl_child_subreaper() != previous_subreaper:
        assert runner._prctl_child_subreaper(enabled=previous_subreaper)
    assert runner._prctl_child_subreaper() == previous_subreaper


def _connect(path: Path) -> tuple[socket.socket, str]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(3)
    connection.connect(str(path))
    challenge = runner._read_json_frame(connection, runner.CHALLENGE)
    assert set(challenge) == {"v", "challenge", "mac"}
    signature = challenge.pop("mac")
    assert isinstance(signature, str)
    assert hmac.compare_digest(signature, runner.sign_runner_reply(challenge, CONTROL_SECRET))
    assert challenge["v"] == runner.PROTOCOL_VERSION
    return connection, str(challenge["challenge"])


def _start(connection: socket.socket, challenge: str, *, scope: dict[str, object] | None = None,
           environment: dict[str, str] | None = None) -> tuple[str, str]:
    selected_scope = SCOPE if scope is None else scope
    nonce = "a" * 64
    request = {
        "v": runner.PROTOCOL_VERSION,
        "challenge": challenge,
        "nonce": nonce,
        "scope": selected_scope,
        "env": ENVIRONMENT if environment is None else environment,
        "proxy_token_env": "DEEPSEEK_API_KEY",
        "proxy_token": PROXY_TOKEN,
        "overlay_b64": OVERLAY,
        "deadline_at_ms": int(time.time() * 1000) + 15_000,
    }
    request["mac"] = runner.sign_start_message(request, CONTROL_SECRET)
    runner._send_json(connection, runner.START, request)
    return nonce, runner.scope_digest(selected_scope)


def _verified_reply(connection: socket.socket, expected_type: int,
                    exact_fields: set[str]) -> dict[str, object]:
    reply = runner._read_json_frame(connection, expected_type)
    assert set(reply) == exact_fields
    signature = reply.pop("mac")
    assert isinstance(signature, str)
    assert hmac.compare_digest(signature, runner.sign_runner_reply(reply, CONTROL_SECRET))
    return reply


def _open_ready(path: Path, *, scope: dict[str, object] | None = None) -> tuple[
        socket.socket, str, str, dict[str, object]]:
    connection, challenge = _connect(path)
    nonce, digest = _start(connection, challenge, scope=scope)
    ready = _verified_reply(connection, runner.READY,
                            {"v", "challenge", "nonce", "scope_digest", "cwd", "mac"})
    assert ready["v"] == runner.PROTOCOL_VERSION
    assert ready["challenge"] == challenge
    assert ready["nonce"] == nonce
    assert ready["scope_digest"] == digest
    return connection, challenge, nonce, ready


def test_authenticated_stdio_relay_and_signed_cleanup(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_popen_for_current_uid(monkeypatch)
    code = (
        "import os,sys,time; "
        "sys.stdout.write('uid=%s;control=%s;provider=%s;cwd=%s\\n' % ("
        "os.getuid(), os.getenv('BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET', 'absent'), "
        "os.getenv('DEEPSEEK_API_KEY', 'absent'), os.getcwd())); sys.stdout.flush(); "
        "line=sys.stdin.buffer.readline(); sys.stdout.buffer.write(b'echo:'+line); "
        "sys.stdout.flush(); time.sleep(60)"
    )
    server, thread = _server(tmp_path, code)
    socket_path = tmp_path / "control" / "control.sock"
    try:
        assert (socket_path.parent.stat().st_mode & 0o777) == 0o710
        connection, challenge, nonce, ready = _open_ready(socket_path)
        leaf = tmp_path / "sessions" / str(ready["scope_digest"])
        assert ready["cwd"] == str(leaf)
        connection.settimeout(3)
        output = bytearray()
        while b"\n" not in output:
            frame_type, payload = runner.read_frame(connection)
            assert frame_type == runner.STDOUT
            output.extend(payload)
        first_line = bytes(output).splitlines()[0]
        assert first_line == (
            f"uid={os.geteuid()};control=absent;provider={PROXY_TOKEN};cwd={leaf}"
        ).encode()

        connection.sendall(runner.encode_frame(runner.STDIN, b"hello\n"))
        while b"echo:hello\n" not in output:
            frame_type, payload = runner.read_frame(connection)
            assert frame_type == runner.STDOUT
            output.extend(payload)
        connection.sendall(runner.encode_frame(runner.CANCEL, b""))
        exit_reply = _verified_reply(
            connection, runner.EXIT,
            {"v", "challenge", "nonce", "scope_digest", "code", "signal", "reason", "cleanup", "mac"},
        )
        assert exit_reply["challenge"] == challenge
        assert exit_reply["nonce"] == nonce
        assert exit_reply["scope_digest"] == ready["scope_digest"]
        assert exit_reply["reason"] == "cancelled"
        assert exit_reply["cleanup"] == "proven"
        connection.close()

        assert calls and calls[0]["user"] == os.geteuid() and calls[0]["group"] == os.getegid()
        assert calls[0]["extra_groups"] == ()
        assert calls[0]["cwd"] == "/"
        assert calls[0]["umask"] == 0o077 and calls[0]["start_new_session"] is True
        state_marker = tmp_path / "state" / f"{ready['scope_digest']}.used"
        assert state_marker.read_bytes() == b"byq-acp-runner-one-shot.v1\n"
        assert (state_marker.stat().st_mode & 0o777) == 0o600
        assert (tmp_path / "sessions").stat().st_mode & 0o777 == 0o710
        assert leaf.stat().st_mode & 0o777 == 0o700
        overlay = leaf / "selected-provider.patch.yml"
        assert overlay.read_bytes() == base64.b64decode(OVERLAY)
        assert overlay.stat().st_mode & 0o777 == 0o600
    finally:
        _close_server(server, thread)


def test_restart_rejects_consumed_scope_without_relaunch(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, "import time; time.sleep(60)")
    socket_path = tmp_path / "control" / "control.sock"
    try:
        connection, challenge, nonce, ready = _open_ready(socket_path)
        connection.sendall(runner.encode_frame(runner.CANCEL, b""))
        exit_reply = _verified_reply(
            connection, runner.EXIT,
            {"v", "challenge", "nonce", "scope_digest", "code", "signal", "reason", "cleanup", "mac"},
        )
        assert exit_reply["cleanup"] == "proven"
        connection.close()
        assert len(calls) == 1
    finally:
        _close_server(server, thread)

    # A fresh runner process sees the durable SHA-256 tombstone and never
    # attempts a second launch for that exact Backend scope.
    restarted, restarted_thread = _server(tmp_path, "raise SystemExit('must not run')")
    try:
        connection, new_challenge = _connect(socket_path)
        nonce, digest = _start(connection, new_challenge)
        rejection = _verified_reply(
            connection, runner.REJECT,
            {"v", "challenge", "nonce", "scope_digest", "code", "mac"},
        )
        assert rejection == {
            "v": runner.PROTOCOL_VERSION,
            "challenge": new_challenge,
            "nonce": nonce,
            "scope_digest": digest,
            "code": "scope_consumed",
        }
        assert len(calls) == 1
        connection.close()
    finally:
        _close_server(restarted, restarted_thread)


def test_cancel_reaps_double_forked_setsid_child(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_popen_for_current_uid(monkeypatch)
    marker = tmp_path / "escaped-process.txt"
    code = f"""
import os, time
child = os.fork()
if child == 0:
    os.setsid()
    grandchild = os.fork()
    if grandchild:
        os._exit(0)
    open({str(marker)!r}, 'w').write(str(os.getpid()) + ' ' + str(os.getpgrp()))
    while True:
        time.sleep(1)
print('leader-ready', flush=True)
time.sleep(60)
"""
    server, thread = _server(tmp_path, code)
    socket_path = tmp_path / "control" / "control.sock"
    connection: socket.socket | None = None
    escaped_pid: int | None = None
    try:
        connection, _challenge, nonce, ready = _open_ready(socket_path)
        assert calls and type(calls[0]["pid"]) is int
        leader_pid = int(calls[0]["pid"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.01)
        assert marker.exists(), "launcher did not create the setsid grandchild"
        escaped_pid_text, escaped_pgid_text = marker.read_text().split()
        escaped_pid = int(escaped_pid_text)
        assert int(escaped_pgid_text) != leader_pid
        assert os.getpgid(escaped_pid) == int(escaped_pgid_text)

        connection.sendall(runner.encode_frame(runner.CANCEL, b""))
        # The launcher may have emitted a final ACP stdout chunk before the
        # signed process receipt. Consume only that bounded relay output.
        while True:
            frame_type, frame_payload = runner.read_frame(connection)
            if frame_type == runner.EXIT:
                break
            assert frame_type == runner.STDOUT and frame_payload
        assert frame_payload
        import io
        exit_reply = _verified_reply(
            io.BytesIO(runner.encode_frame(runner.EXIT, frame_payload)), runner.EXIT,
            {"v", "challenge", "nonce", "scope_digest", "code", "signal", "reason", "cleanup", "mac"},
        )
        assert exit_reply["nonce"] == nonce
        assert exit_reply["scope_digest"] == ready["scope_digest"]
        assert exit_reply["reason"] == "cancelled"
        assert exit_reply["cleanup"] == "proven"
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and Path("/proc", str(escaped_pid)).exists():
            time.sleep(0.01)
        assert not Path("/proc", str(escaped_pid)).exists(), "setsid child survived signed cleanup"
    finally:
        if connection is not None:
            connection.close()
        if escaped_pid is not None and Path("/proc", str(escaped_pid)).exists():
            # Keep a failed negative test from leaving a synthetic child behind.
            try:
                os.kill(escaped_pid, 9)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(escaped_pid, 0)
            except ChildProcessError:
                pass
        _close_server(server, thread)


def test_launch_failure_returns_authenticated_rejection(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, "pass")
    # The binary path is deliberately absent; this never launches DSH or a provider.
    server.launcher = (str(tmp_path / "no-such-executable"),)
    socket_path = tmp_path / "control" / "control.sock"
    try:
        connection, challenge = _connect(socket_path)
        nonce, digest = _start(connection, challenge)
        rejection = _verified_reply(
            connection, runner.REJECT,
            {"v", "challenge", "nonce", "scope_digest", "code", "mac"},
        )
        assert rejection == {
            "v": runner.PROTOCOL_VERSION,
            "challenge": challenge,
            "nonce": nonce,
            "scope_digest": digest,
            "code": "launch_failed",
        }
        assert calls == []
        assert (tmp_path / "state" / f"{digest}.used").is_file()
        connection.close()
    finally:
        _close_server(server, thread)


def test_invalid_mac_does_not_consume_scope_or_launch(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, "raise SystemExit('must not run')")
    socket_path = tmp_path / "control" / "control.sock"
    try:
        connection, _challenge = _connect(socket_path)
        connection.close()
        connection, challenge = _connect(socket_path)
        request = {
            "v": runner.PROTOCOL_VERSION,
            "challenge": challenge,
            "nonce": "b" * 64,
            "scope": SCOPE,
            "env": ENVIRONMENT,
            "proxy_token_env": "DEEPSEEK_API_KEY",
            "proxy_token": PROXY_TOKEN,
            "overlay_b64": OVERLAY,
            "deadline_at_ms": int(time.time() * 1000) + 15_000,
            "mac": "0" * 64,
        }
        runner._send_json(connection, runner.START, request)
        assert runner.read_frame(connection) is None
        connection.close()
        assert not list((tmp_path / "state").glob("*.used"))
        assert calls == []
    finally:
        _close_server(server, thread)


def test_frame_bound_and_exact_scope_schema() -> None:
    with pytest.raises(runner.ProtocolError):
        runner.encode_frame(runner.STDIN, b"x" * runner.MAX_FRAME_BYTES)
    with pytest.raises(runner.ProtocolError):
        runner._validate_scope({**SCOPE, "extra": "field"})


def test_production_child_identity_defaults_to_dedicated_uid(tmp_path: Path) -> None:
    uid = os.geteuid()
    gid = os.getegid()
    control_dir = tmp_path / "control"
    control_dir.mkdir(mode=0o700)
    server = runner.JudgmentRunnerServer(
        control_dir / "control.sock",
        secret=CONTROL_SECRET,
        state_dir=tmp_path / "state",
        session_root=tmp_path / "sessions",
        launcher=(sys.executable, "-c", "pass"),
        prepare_roots=False,
        ready_file=control_dir / "ready",
        control_gid=gid,
        state_uid=uid,
        state_gid=gid,
        runner_uid=uid,
    )
    try:
        assert server.child_uid == 10002
        assert server.child_gid == 10002
    finally:
        server.server_close()


def test_cleanup_receipt_is_persisted_atomically_and_signed(tmp_path):
    digest = runner.scope_digest(SCOPE)
    exit_fields = {"code": 0, "signal": None, "reason": "process_exit",
                   "cleanup": "proven"}
    runner._persist_cleanup_receipt(
        tmp_path, SCOPE, digest, "f" * 64, exit_fields, CONTROL_SECRET, os.getgid())
    path = tmp_path / "cleanup-receipts" / f"{digest}.json"
    assert path.is_file()
    assert not list((tmp_path / "cleanup-receipts").glob("*.tmp"))
    raw = json.loads(path.read_text())
    mac = raw.pop("mac")
    assert runner.sign_runner_reply(raw, CONTROL_SECRET) == mac
    assert raw["cleanup"] == "proven" and raw["scope_digest"] == digest
    assert raw["runner_instance_id"] == "f" * 64
