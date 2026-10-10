"""Keyless qualification for the single-workspace Product ACP slot."""

from __future__ import annotations

import hmac
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace
from pathlib import Path

import pytest

from packages.contracts.acp_product_slot import product_scope_digest, validate_product_scope
from services.acp_product_runner import server as slot


SECRET = bytes(range(32))
WORKSPACE = "workspace-team-a"
ECHO_CODE = (
    "import os,sys,time; "
    "sys.stdout.write('home='+os.environ['DSH_HOME']+'\\n'); sys.stdout.flush(); "
    "line=sys.stdin.buffer.readline(); sys.stdout.buffer.write(b'echo:'+line); "
    "sys.stdout.flush(); time.sleep(60)"
)


def _scope(*, workspace_id: str = WORKSPACE, root: str = "a", generation: str = "b",
           cwd_leaf: str = "root-c") -> dict[str, str]:
    kind = cwd_leaf.partition("-")[0]
    suffix = "e" if cwd_leaf.endswith("-c") else "f"
    return {
        "workspace_id": workspace_id,
        "owner_principal": "user:alice",
        "session_id": "session_123",
        "trace_id": "trace_123",
        "root_run_id": root * 32,
        "runtime_boot_id": "d" * 32,
        "generation_id": f"generation-{generation * 32}",
        "cwd_leaf": f"{kind}-{suffix * 32}",
    }


def _environment(scope: dict[str, str]) -> dict[str, str]:
    env = {
        "BYQ_MCP_URL": "http://mcp:8300/mcp/v1",
        "BYQ_MCP_ACP_DISCOVERY_TOKEN": "d" * 40,
        "BYQ_MCP_ACP_SIGNING_KEY": "s" * 40,
        "BYQ_RUNTIME_BOOT_ID": scope["runtime_boot_id"],
        "BYQ_OWNER_PRINCIPAL": scope["owner_principal"],
        "BYQ_WORKSPACE_ID": scope["workspace_id"],
        "BYQ_ACTOR_PRINCIPAL": f"byq-product-agent-{scope['session_id']}",
        "BYQ_TRACE_ID": scope["trace_id"],
        "BYQ_SESSION_ID": scope["session_id"],
        "BYQ_PROVIDER_SESSION_ID": str(uuid.uuid5(
            uuid.NAMESPACE_URL, "byq-test:" + scope["session_id"],
        )),
        "BYQ_DSH_RUN_ID": scope["generation_id"],
        "BYQ_ROOT_RUN_ID": scope["root_run_id"],
        "DEEPSEEK_API_KEY": "provider-key-qualification-only",
    }
    return env


def _fake_popen_for_current_uid(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    real_popen = subprocess.Popen
    calls: list[dict[str, object]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        observed = dict(kwargs)
        kwargs.pop("user")
        kwargs.pop("group")
        kwargs.pop("extra_groups")
        calls.append(observed)
        process = real_popen(*args, **kwargs)  # type: ignore[arg-type]
        observed["pid"] = process.pid
        return process

    monkeypatch.setattr(slot.subprocess, "Popen", popen)
    return calls


def _server(tmp_path: Path, code: str) -> tuple[slot.ProductSlotServer, threading.Thread]:
    previous_subreaper = slot._helpers._prctl_child_subreaper()
    assert slot._helpers._prctl_child_subreaper(enabled=True)
    assert slot._helpers._prctl_child_subreaper()
    assert slot._helpers._read_no_new_privs(os.getpid()) is True
    uid, gid = os.geteuid(), os.getegid()
    control_dir = tmp_path / "control"
    base = tmp_path / "dsh-sessions" / "dsh-v0.2.0-rc.2-acp"
    slot._prepare_root_directory(base, uid=uid, gid=gid, mode=0o710)
    try:
        server = slot.ProductSlotServer(
            secret=SECRET,
            workspace_id=WORKSPACE,
            socket_path=control_dir / "control.sock",
            control_directory=control_dir,
            session_base=base,
            state_dir=tmp_path / "state",
            ready_file=control_dir / "ready",
            launcher=(sys.executable, "-u", "-c", code),
            child_uid=uid,
            child_gid=gid,
            runner_uid=uid,
            control_gid=gid,
            state_gid=gid,
        )
    except BaseException:
        if slot._helpers._prctl_child_subreaper() != previous_subreaper:
            assert slot._helpers._prctl_child_subreaper(enabled=previous_subreaper)
        raise
    def serve() -> None:
        try:
            server.serve_forever(poll_interval=0.01)
        except slot.RetireSlot:
            return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    server._test_previous_subreaper = previous_subreaper
    return server, thread


def _close_server(server: slot.ProductSlotServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    assert not thread.is_alive()
    previous = server._test_previous_subreaper
    if slot._helpers._prctl_child_subreaper() != previous:
        assert slot._helpers._prctl_child_subreaper(enabled=previous)
    assert slot._helpers._prctl_child_subreaper() == previous


def _connect(path: Path) -> tuple[socket.socket, str]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(4)
    connection.connect(str(path))
    challenge = slot._helpers._read_json_frame(connection, slot.CHALLENGE)
    assert set(challenge) == {"v", "challenge", "mac"}
    signature = challenge.pop("mac")
    assert isinstance(signature, str)
    assert hmac.compare_digest(signature, slot._reply_mac(challenge, SECRET))
    return connection, str(challenge["challenge"])


def _start(connection: socket.socket, challenge: str, scope: dict[str, str],
           env: dict[str, str] | None = None) -> tuple[str, str]:
    nonce = os.urandom(32).hex()
    request = {
        "v": slot.PROTOCOL_VERSION,
        "challenge": challenge,
        "nonce": nonce,
        "scope": scope,
        "env": _environment(scope) if env is None else env,
        "deadline_at_ms": int(time.time() * 1000) + 15_000,
    }
    request["mac"] = slot._helpers.sign_start_message(request, SECRET)
    slot._helpers._send_json(connection, slot.START, request)
    return nonce, product_scope_digest(scope)


def _verified_reply(connection: socket.socket, frame_type: int,
                    expected: set[str]) -> dict[str, object]:
    reply = slot._helpers._read_json_frame(connection, frame_type)
    assert set(reply) == expected
    signature = reply.pop("mac")
    assert isinstance(signature, str)
    assert hmac.compare_digest(signature, slot._reply_mac(reply, SECRET))
    return reply


def _adapter_prepare_cwd(cwd: Path) -> None:
    """Model the trusted Adapter preparing a private home and temp leaf."""
    cwd.mkdir(mode=0o700, parents=True)
    (cwd / "tmp").mkdir(mode=0o700)
    assert stat.S_IMODE(os.stat(cwd).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(cwd / "tmp").st_mode) == 0o700


def _receive_reject(connection: socket.socket, challenge: str, nonce: str,
                    digest: str) -> str:
    reply = _verified_reply(
        connection, slot.REJECT,
        {"v", "challenge", "nonce", "scope_digest", "code", "mac"},
    )
    assert reply["challenge"] == challenge
    assert reply["nonce"] == nonce
    assert reply["scope_digest"] == digest
    return str(reply["code"])


def _cancel_root(path: Path, scope: dict[str, str], expected_cwd: Path,
                 env: dict[str, str] | None = None,
                 expected_cleanup: str = "proven") -> dict[str, object]:
    connection, challenge = _connect(path)
    nonce, digest = _start(connection, challenge, scope, env)
    ready = _verified_reply(
        connection, slot.READY,
        {"v", "challenge", "nonce", "scope_digest", "cwd", "mac"},
    )
    assert ready["challenge"] == challenge
    assert ready["nonce"] == nonce
    assert ready["scope_digest"] == digest
    assert ready["cwd"] == str(expected_cwd)
    output = bytearray()
    while b"home=" not in output:
        frame_type, payload = slot._helpers.read_frame(connection)
        assert frame_type == slot.STDOUT
        output.extend(payload)
    assert f"home={expected_cwd}\n".encode() in output
    connection.sendall(slot._helpers.encode_frame(slot.STDIN, b"hello\n"))
    while b"echo:hello\n" not in output:
        frame_type, payload = slot._helpers.read_frame(connection)
        assert frame_type == slot.STDOUT
        output.extend(payload)
    connection.sendall(slot._helpers.encode_frame(slot.CANCEL, b""))
    exit_reply = _verified_reply(
        connection, slot.EXIT,
        {"v", "challenge", "nonce", "scope_digest", "code", "signal",
         "reason", "cleanup", "mac"},
    )
    assert exit_reply["challenge"] == challenge
    assert exit_reply["nonce"] == nonce
    assert exit_reply["scope_digest"] == digest
    assert exit_reply["cleanup"] == expected_cleanup
    assert exit_reply["reason"] in {"cancelled", "process_exit"}
    connection.close()
    return ready


def test_scope_and_environment_contract_are_closed() -> None:
    scope = _scope()
    assert validate_product_scope(scope) == scope
    assert len(product_scope_digest(scope)) == 64
    env = _environment(scope)
    assert slot.validate_product_environment(env, scope) == env
    with pytest.raises(slot.ProductSlotContractError):
        validate_product_scope({**scope, "cwd_leaf": "../outside"})
    with pytest.raises(slot.ProductSlotContractError):
        slot.validate_product_environment(
            {**env, "BYQ_RUNTIME_AUTHORITY_TOKEN": "forbidden"}, scope,
        )


def test_workspace_mismatch_is_signed_and_never_creates_a_cwd(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, "import sys,time; time.sleep(60)")
    path = tmp_path / "control" / "control.sock"
    try:
        scope = _scope(workspace_id="another-workspace")
        connection, challenge = _connect(path)
        nonce, digest = _start(connection, challenge, scope)
        assert _receive_reject(connection, challenge, nonce, digest) == "workspace_mismatch"
        assert not (server.session_base / "another-workspace").exists()
        assert list(server.state_dir.iterdir()) == []
        connection.close()
    finally:
        _close_server(server, thread)


def test_forbidden_authority_environment_is_rejected_before_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, "import sys,time; time.sleep(60)")
    path = tmp_path / "control" / "control.sock"
    try:
        scope = _scope()
        env = {**_environment(scope), "BYQ_RUNTIME_AUTHORITY_TOKEN": "forbidden"}
        connection, challenge = _connect(path)
        nonce, digest = _start(connection, challenge, scope, env)
        assert _receive_reject(connection, challenge, nonce, digest) == "environment_rejected"
        assert not (server.session_root / scope["cwd_leaf"]).exists()
        assert list(server.state_dir.iterdir()) == []
        connection.close()
    finally:
        _close_server(server, thread)


def test_deadline_after_scope_consumption_is_reported_as_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, "import sys,time; time.sleep(60)")
    original_clock = slot.time
    monotonic_values = iter((100.0, 10_000.0, 20_000.0))
    monkeypatch.setattr(slot, "time", SimpleNamespace(
        time=original_clock.time,
        monotonic=lambda: next(monotonic_values),
    ))
    path = tmp_path / "control" / "control.sock"
    try:
        scope = _scope()
        connection, challenge = _connect(path)
        nonce, digest = _start(connection, challenge, scope)
        assert _receive_reject(connection, challenge, nonce, digest) == "scope_consumed"
        connection.close()
        assert len(list(server.state_dir.glob("*.used"))) == 1
        assert not (server.session_root / scope["cwd_leaf"]).exists()
        assert calls == []

        # A caller's retry with that same prelaunch scope must see the durable
        # tombstone, never be told it is available after the deadline race.
        retry, retry_challenge = _connect(path)
        retry_nonce, retry_digest = _start(retry, retry_challenge, scope)
        assert _receive_reject(retry, retry_challenge, retry_nonce, retry_digest) == "scope_consumed"
        retry.close()
    finally:
        _close_server(server, thread)


def test_signed_cleanup_allows_serial_reuse_and_replay_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, ECHO_CODE)
    path = tmp_path / "control" / "control.sock"
    try:
        scope_one = _scope(root="a", generation="b")
        expected_cwd = server.session_root / scope_one["cwd_leaf"]
        _adapter_prepare_cwd(expected_cwd)
        first = _cancel_root(path, scope_one, expected_cwd)
        assert first["cwd"] == str(expected_cwd)

        # A later root resumes the same native working directory after the
        # caller has settled the previous root; it gets a fresh root scope.
        scope_two = {**scope_one, "root_run_id": "f" * 32,
                     "generation_id": "generation-" + "1" * 32}
        env_two = _environment(scope_two)
        env_two["BYQ_NATIVE_ROOT_SESSION_ID"] = "123e4567-e89b-42d3-a456-426614174000"
        _cancel_root(path, scope_two, expected_cwd, env_two)

        replay, challenge = _connect(path)
        nonce, digest = _start(replay, challenge, scope_two, env_two)
        assert _receive_reject(replay, challenge, nonce, digest) == "scope_consumed"
        replay.close()

        assert len(calls) == 2
        assert all(call["user"] == os.geteuid() and call["group"] == os.getegid()
                   and call["extra_groups"] == () for call in calls)
        assert all(call["cwd"] == "/" for call in calls)
        assert server.retire_requested is False
    finally:
        _close_server(server, thread)


def test_workspace_cwd_is_canonical_and_group_specific(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, ECHO_CODE)
    try:
        assert (tmp_path / "control" / "ready").read_text(encoding="ascii") == WORKSPACE + "\n"
        scope = _scope(cwd_leaf="session-c")
        expected = tmp_path / "dsh-sessions" / "dsh-v0.2.0-rc.2-acp" / WORKSPACE / scope["cwd_leaf"]
        root_info = os.stat(server.session_root)
        assert root_info.st_gid == os.getegid()
        assert stat.S_IMODE(root_info.st_mode) == 0o770
        assert os.access(server.session_root, os.W_OK | os.X_OK)
        _adapter_prepare_cwd(expected)
        ready = _cancel_root(tmp_path / "control" / "control.sock", scope, expected)
        assert Path(str(ready["cwd"])).parent == server.session_root
        assert server.session_root.name == scope["workspace_id"]
        assert server.session_root.parent == server.session_base
    finally:
        _close_server(server, thread)


def test_product_scope_cleanup_receipt_is_persisted_atomically_and_signed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_popen_for_current_uid(monkeypatch)
    server, thread = _server(tmp_path, ECHO_CODE)
    try:
        scope = _scope()
        cwd = server.session_root / scope["cwd_leaf"]
        _adapter_prepare_cwd(cwd)
        _cancel_root(tmp_path / "control" / "control.sock", scope, cwd)
        digest = product_scope_digest(scope)
        directory = tmp_path / "control" / "cleanup-receipts"
        path = directory / f"{digest}.json"
        assert path.is_file()
        assert not list(directory.glob("*.tmp"))
        raw = json.loads(path.read_text())
        mac = raw.pop("mac")
        assert slot._helpers.sign_runner_reply(raw, SECRET) == mac
        # Closed key set: the Product receipt binds only its own scope contract
        # and never forges judgment fields (task_id/call_identity/authority_epoch).
        assert set(raw) == {
            "schema_version", "scope_digest", "workspace_id", "owner_principal",
            "session_id", "trace_id", "root_run_id", "runtime_boot_id",
            "generation_id", "cwd_leaf", "runner_instance_id", "code", "signal",
            "reason", "cleanup",
        }
        assert raw["schema_version"] == slot._PRODUCT_CLEANUP_RECEIPT_SCHEMA
        assert raw["scope_digest"] == digest
        assert raw["cleanup"] == "proven"
        assert raw["workspace_id"] == scope["workspace_id"]
        assert raw["owner_principal"] == scope["owner_principal"]
        assert raw["session_id"] == scope["session_id"]
        assert raw["trace_id"] == scope["trace_id"]
        assert raw["root_run_id"] == scope["root_run_id"]
        assert raw["runtime_boot_id"] == scope["runtime_boot_id"]
        assert raw["generation_id"] == scope["generation_id"]
        assert raw["cwd_leaf"] == scope["cwd_leaf"]
        assert raw["runner_instance_id"] == server.instance_id
        assert raw["code"] is None or type(raw["code"]) is int
        assert raw["signal"] is None or type(raw["signal"]) is int
        assert raw["reason"] in {"cancelled", "process_exit"}
    finally:
        _close_server(server, thread)


def test_cleanup_receipt_write_failure_keeps_cleanup_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_popen_for_current_uid(monkeypatch)

    def fail_write(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic cleanup receipt write failure")

    monkeypatch.setattr(slot, "_persist_product_cleanup_receipt", fail_write)
    server, thread = _server(tmp_path, ECHO_CODE)
    try:
        scope = _scope()
        cwd = server.session_root / scope["cwd_leaf"]
        _adapter_prepare_cwd(cwd)
        _cancel_root(tmp_path / "control" / "control.sock", scope, cwd,
                     expected_cleanup="unknown")
        assert server.retire_requested is True
        # A failed write must leave no proven receipt behind.
        directory = tmp_path / "control" / "cleanup-receipts"
        assert not directory.exists() or not list(directory.glob("*.json"))
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        _close_server(server, thread)


def test_relay_unknown_exit_retires_the_only_workspace_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_popen_for_current_uid(monkeypatch)
    real_cleanup = slot._helpers._terminate_and_reap

    def cleanup_but_report_unknown(process: subprocess.Popen[bytes], *, child_uid: int):
        code, child_signal, _cleanup = real_cleanup(process, child_uid=child_uid)
        return code, child_signal, "unknown"

    monkeypatch.setattr(slot._helpers, "_terminate_and_reap", cleanup_but_report_unknown)
    server, thread = _server(tmp_path, ECHO_CODE)
    try:
        scope = _scope()
        cwd = server.session_root / scope["cwd_leaf"]
        _adapter_prepare_cwd(cwd)
        _cancel_root(
            tmp_path / "control" / "control.sock", scope, cwd,
            expected_cleanup="unknown",
        )
        assert server.retire_requested is True
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        _close_server(server, thread)


def test_unproven_startup_cleanup_retires_the_only_workspace_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_popen_for_current_uid(monkeypatch)
    real_cleanup = slot._helpers._terminate_and_reap
    real_nnp = slot._helpers._read_no_new_privs

    def cleanup_but_report_unknown(process: subprocess.Popen[bytes], *, child_uid: int):
        code, child_signal, _cleanup = real_cleanup(process, child_uid=child_uid)
        return code, child_signal, "unknown"

    def child_nnp_unverified(pid: int) -> bool | None:
        return False if pid != os.getpid() else real_nnp(pid)

    monkeypatch.setattr(slot._helpers, "_terminate_and_reap", cleanup_but_report_unknown)
    monkeypatch.setattr(slot._helpers, "_read_no_new_privs", child_nnp_unverified)
    server, thread = _server(tmp_path, "import sys,time; time.sleep(60)")
    try:
        scope = _scope()
        _adapter_prepare_cwd(server.session_root / scope["cwd_leaf"])
        connection, challenge = _connect(tmp_path / "control" / "control.sock")
        nonce, digest = _start(connection, challenge, scope)
        assert _receive_reject(connection, challenge, nonce, digest) == "launch_failed"
        connection.close()
        assert server.retire_requested is True
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        _close_server(server, thread)


def test_child_environment_forces_runner_runtime_root_and_drops_authority(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "BYQ_DSH_RUNTIME_ROOT": "/evil-attacker-root",
        "BYQ_RUNTIME_AUTHORITY_TOKEN": "authority",
        "DEEPSEEK_API_KEY_UPSTREAM": "search",
        "BYQ_WORKSPACE_ID": "workspace-team-a",
    }
    child = slot._minimal_child_environment(
        env, home, tmp_path / "sessions", Path("/opt/dsh-runtime"))
    assert child["BYQ_DSH_RUNTIME_ROOT"] == "/opt/dsh-runtime"
    assert "BYQ_RUNTIME_AUTHORITY_TOKEN" not in child
    assert "DEEPSEEK_API_KEY_UPSTREAM" not in child
    assert child["BYQ_WORKSPACE_ID"] == "workspace-team-a"


def _guard_overlay_b64(*, headers):
    import base64
    from packages.contracts.continuation_request import profile_binding, request_limits
    chat = {
        "api": "openai-completions",
        "apiKeyEnv": "OPENCODE_API_KEY",
        "baseURL": "http://172.31.7.9:41337",
        "retryPolicy": {"mode": "normal", "maxRetries": 0},
        "models": [{"id": "deepseek-v4.1-flash", "maxTokens": 8192}],
    }
    if headers is not None:
        chat["headers"] = headers
    overlay = [
        {"id": "web-search-deepseek", "disabled": True},
        {"id": "tool-web", "disabled": True},
        {"id": "llm-deepseek", "config": {"maxTokens": 8192}},
        {"id": "llm-pi-ai", "config": {"providers": {"opencode-go-chat": chat}}},
        {"insert": [{"id": "byq-continuation-budget",
                     "name": "file:///opt/byq/runtime/byq-continuation-budget.js",
                     "config": {"deadlineEpochMs": int(time.time() * 1000) + 60_000,
                                "reservationId": "continuation_" + "a" * 32,
                                "executionProfile": profile_binding(),
                                "requestLimits": request_limits()}}]},
    ]
    return base64.b64encode(json.dumps(
        overlay, sort_keys=True, separators=(",", ":")).encode()).decode()


def test_validate_guard_requires_the_exact_route_session_header():
    # The trusted runner must accept the exact generated shape, including the
    # x-opencode-session route header (ADR-0105), and reject a missing or altered
    # header, so the OpenCode Go route can never be dispatched without its
    # session identity or with an arbitrary header.
    accepted = slot._validate_guard(_guard_overlay_b64(
        headers={"x-opencode-session": "123e4567-e89b-42d3-a456-426614174000"}))
    assert isinstance(accepted, list) and len(accepted) == 5
    with pytest.raises(slot.ProductSlotError):
        slot._validate_guard(_guard_overlay_b64(headers=None))
    with pytest.raises(slot.ProductSlotError):
        slot._validate_guard(_guard_overlay_b64(headers={"x-other": "value"}))
    with pytest.raises(slot.ProductSlotError):
        slot._validate_guard(_guard_overlay_b64(headers={"x-opencode-session": "not-a-uuid"}))


def test_validate_guard_accepts_the_ordinary_count_only_product_turn_overlay():
    import base64

    from packages.contracts.product_turn_request import (
        PRODUCT_TURN_LIMITS, PRODUCT_TURN_PROFILE_ID, PRODUCT_TURN_PROFILE_SHA256,
        PRODUCT_TURN_PROFILE_VERSION)

    def encode(value):
        return base64.b64encode(json.dumps(
            value, sort_keys=True, separators=(",", ":")).encode()).decode()

    chat = {
        "api": "openai-completions",
        "apiKeyEnv": "OPENCODE_API_KEY",
        "baseURL": "http://172.31.7.9:41337",
        "retryPolicy": {"mode": "normal", "maxRetries": 0},
        "headers": {"x-opencode-session": "123e4567-e89b-42d3-a456-426614174000"},
        "models": [{"id": "deepseek-v4.1-flash", "maxTokens": 8192}],
    }
    guard_config = {
        "guardMode": "count-only",
        "deadlineEpochMs": int(time.time() * 1000) + 60_000,
        "executionProfile": {"profile_id": PRODUCT_TURN_PROFILE_ID,
                             "profile_version": PRODUCT_TURN_PROFILE_VERSION,
                             "profile_sha256": PRODUCT_TURN_PROFILE_SHA256},
        "requestLimits": dict(PRODUCT_TURN_LIMITS),
    }
    # This is the exact PRE-injection overlay that
    # `app.continuation_budget.create_acp_product_budget_overlay` sends in the
    # START frame: closed identity + limits, and NO journalPath. The trusted
    # Adapter injects journalPath into the on-disk patch from the
    # workspace-bound session home after the frame is validated.
    overlay = [
        {"id": "llm-pi-ai", "config": {"providers": {"opencode-go-chat": chat}}},
        {"insert": [{"id": "byq-continuation-budget",
                     "name": "file:///opt/byq/runtime/byq-continuation-budget.js",
                     "config": guard_config}]},
    ]
    accepted = slot._validate_guard(encode(overlay))
    assert isinstance(accepted, list) and len(accepted) == 2
    # A frame-supplied journalPath (arbitrary absolute path), a continuation
    # reservation, a widened limit, or a foreign profile is refused.
    for mutate in (
        lambda value: value[1]["insert"][0]["config"].update(
            {"journalPath": "/tmp/product-turn-tool-guard.jsonl"}),
        lambda value: value[1]["insert"][0]["config"].update({"reservationId": "continuation_" + "a" * 32}),
        lambda value: value[1]["insert"][0]["config"]["requestLimits"].update({"max_tool_calls": 17}),
        lambda value: value[1]["insert"][0]["config"]["executionProfile"].update({"profile_id": "task-ready-read.v1"}),
    ):
        bad = json.loads(json.dumps(overlay))
        mutate(bad)
        with pytest.raises(slot.ProductSlotError):
            slot._validate_guard(encode(bad))
