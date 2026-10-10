"""Focused keyless tests for Product ACP workspace-slot transport and fences."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import socketserver
import threading
import time
from contextlib import contextmanager

import pytest

from app import acp_product_slot_client as product
from app import research_judgment_acp_runner_client as wire
from packages.contracts.acp_product_slot import product_scope_digest


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _scope(workspace: str = "workspace-a", suffix: str = "a") -> dict[str, str]:
    root_id = suffix * 32
    return {
        "workspace_id": workspace,
        "owner_principal": "owner-a",
        "session_id": "session-a",
        "trace_id": f"trace-{suffix}",
        "root_run_id": root_id,
        "runtime_boot_id": "b" * 32,
        "generation_id": "generation-" + "c" * 32,
        "cwd_leaf": "root-" + root_id,
    }


def _cwd(scope: dict[str, str]) -> str:
    return "/var/lib/byq/dsh-sessions/" + scope["cwd_leaf"]


def _bindings(tmp_path) -> tuple[str, dict[str, str], dict[str, bytes]]:
    secrets = {
        "workspace-a": bytes(range(32)),
        "workspace-b": bytes(range(32, 64)),
    }
    encoded = {workspace: _encoded(secret) for workspace, secret in secrets.items()}
    bindings = {
        "workspace-a": {
            "socket_path": str(tmp_path / "slot-a.sock"),
            "control_secret_env": "BYQ_ACP_PRODUCT_SLOT_A_SECRET",
        },
        "workspace-b": {
            "socket_path": str(tmp_path / "slot-b.sock"),
            "control_secret_env": "BYQ_ACP_PRODUCT_SLOT_B_SECRET",
        },
    }
    env = {
        "BYQ_ACP_PRODUCT_SLOT_A_SECRET": encoded["workspace-a"],
        "BYQ_ACP_PRODUCT_SLOT_B_SECRET": encoded["workspace-b"],
        wire.RUNNER_SECRET_ENV: _encoded(bytes(reversed(range(32)))),
    }
    return json.dumps(bindings), env, secrets


def _signed_frame(frame_type: int, body: dict[str, object], secret: bytes) -> bytes:
    signed = {**body, "mac": wire.sign_runner_reply(body, secret)}
    return wire.encode_frame(frame_type, wire.canonical_json(signed))


def _forged_frame(frame_type: int, body: dict[str, object], secret: bytes) -> bytes:
    signed = {**body, "mac": wire.sign_runner_reply(body, secret)}
    mac = str(signed["mac"])
    signed["mac"] = ("0" if mac[0] != "0" else "1") + mac[1:]
    return wire.encode_frame(frame_type, wire.canonical_json(signed))


class _FakeSlotServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, path, secret, scenario="hold"):
        self.secret = secret
        self.scenario = scenario
        self.connection_count = 0
        self.ready = threading.Event()
        super().__init__(str(path), _FakeSlotHandler)


class _FakeSlotHandler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        server.connection_count += 1
        challenge = "d" * 64
        conn = self.request
        conn.sendall(_signed_frame(
            wire.CHALLENGE,
            {"v": wire.PROTOCOL_VERSION, "challenge": challenge},
            server.secret,
        ))
        frame_type, payload = wire._read_frame(conn)
        assert frame_type == wire.START
        start = json.loads(payload)
        unsigned = {key: value for key, value in start.items() if key != "mac"}
        assert start["mac"] == wire.sign_runner_start(unsigned, server.secret)
        scope = start["scope"]
        nonce = start["nonce"]
        digest = product_scope_digest(scope)
        scenario = server.scenario
        if scenario == "timeout":
            time.sleep(0.3)
            return
        ready = {
            "v": wire.PROTOCOL_VERSION,
            "challenge": challenge,
            "nonce": nonce,
            "scope_digest": digest,
            "cwd": _cwd(scope),
        }
        if scenario == "tampered_ready":
            conn.sendall(_forged_frame(wire.READY, ready, server.secret))
            return
        conn.sendall(_signed_frame(wire.READY, ready, server.secret))
        server.ready.set()
        while True:
            frame_type, content = wire._read_frame(conn)
            if frame_type == wire.CANCEL and content == b"":
                exit_body = {
                    "v": wire.PROTOCOL_VERSION,
                    "challenge": challenge,
                    "nonce": nonce,
                    "scope_digest": digest,
                    "code": None,
                    "signal": 15,
                    "reason": "cancelled",
                    "cleanup": "proven",
                }
                conn.sendall(_signed_frame(wire.EXIT, exit_body, server.secret))
                return
            if frame_type == wire.STDIN:
                continue
            raise AssertionError("unexpected Product ACP runner frame")


@contextmanager
def _serve(path, secret, scenario="hold"):
    server = _FakeSlotServer(path, secret, scenario)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _registry(tmp_path):
    raw, env, secrets = _bindings(tmp_path)
    registry = product.ProductSlotRegistry(
        raw,
        environ=env,
        judgment_socket_path="/run/byq-acp-judgment/control.sock",
        judgment_control_secret=env[wire.RUNNER_SECRET_ENV],
    )
    return registry, env, secrets


def _client(registry, *, timeout=1.0):
    return product.ProductRunnerClient(
        registry,
        connect_timeout_s=timeout,
        cleanup_timeout_s=timeout,
    )


def _start(client, scope):
    return client.start(
        scope,
        {
            "BYQ_MCP_URL": "http://mcp:8300/mcp/v1",
            "BYQ_MCP_ACP_DISCOVERY_TOKEN": "d" * 48,
            "BYQ_MCP_ACP_SIGNING_KEY": "s" * 48,
            "BYQ_RUNTIME_BOOT_ID": scope["runtime_boot_id"],
            "BYQ_OWNER_PRINCIPAL": scope["owner_principal"],
            "BYQ_WORKSPACE_ID": scope["workspace_id"],
            "BYQ_ACTOR_PRINCIPAL": "byq-product-agent-" + scope["session_id"],
            "BYQ_TRACE_ID": scope["trace_id"],
            "BYQ_SESSION_ID": scope["session_id"],
            "BYQ_PROVIDER_SESSION_ID": "123e4567-e89b-42d3-a456-426614174000",
            "BYQ_DSH_RUN_ID": scope["generation_id"],
            "BYQ_ROOT_RUN_ID": scope["root_run_id"],
            "OPENCODE_API_KEY": "p" * 48,
        },
        int(time.time() * 1000) + 5000,
        _cwd(scope),
    )


def test_same_workspace_second_root_is_rejected_before_socket_connect(tmp_path):
    registry, _, secrets = _registry(tmp_path)
    client = _client(registry)
    first = _scope("workspace-a", "a")
    second = _scope("workspace-a", "d")
    with _serve(tmp_path / "slot-a.sock", secrets["workspace-a"]) as server:
        session = _start(client, first)
        assert server.ready.wait(1)
        assert registry.owns(first)
        assert not registry.owns(second)
        with pytest.raises(product.ProductSlotBusy):
            _start(client, second)
        assert server.connection_count == 1
        session.cancel()
        receipt = session.wait_exit(1)
        registry.cleanup(first, receipt)
        registry.acknowledge(first)
        assert not registry.owns(first)


def test_different_workspaces_can_use_independent_slots_concurrently(tmp_path):
    registry, _, secrets = _registry(tmp_path)
    client = _client(registry)
    first = _scope("workspace-a", "a")
    second = _scope("workspace-b", "d")
    with _serve(tmp_path / "slot-a.sock", secrets["workspace-a"]) as server_a, \
            _serve(tmp_path / "slot-b.sock", secrets["workspace-b"]) as server_b:
        session_a = _start(client, first)
        session_b = _start(client, second)
        assert server_a.ready.wait(1)
        assert server_b.ready.wait(1)
        session_a.cancel()
        session_b.cancel()
        exit_a = session_a.wait_exit(1)
        exit_b = session_b.wait_exit(1)
        registry.cleanup(first, exit_a)
        registry.acknowledge(first)
        registry.acknowledge(second)
        registry.cleanup(second, exit_b)


def test_slot_waits_for_both_cleanup_and_backend_ack_in_either_order(tmp_path):
    registry, _, _ = _registry(tmp_path)
    first = _scope("workspace-a", "a")
    second = _scope("workspace-a", "d")
    registry.reserve(first)
    registry.cleanup(first, wire.RunnerExit(0, None, "process_exit", "proven"))
    with pytest.raises(product.ProductSlotBusy):
        registry.reserve(second)
    registry.acknowledge(first)
    registry.reserve(second)

    registry.acknowledge(second)
    with pytest.raises(product.ProductSlotBusy):
        registry.reserve(first)
    registry.cleanup(second, wire.RunnerExit(0, None, "process_exit", "proven"))
    registry.reserve(first)


def test_wrong_ack_and_unknown_cleanup_never_release_workspace_fence(tmp_path):
    registry, _, _ = _registry(tmp_path)
    scope = _scope("workspace-a", "a")
    wrong_ack = {**scope, "trace_id": "trace-other"}
    registry.reserve(scope)
    with pytest.raises(product.ProductSlotLeaseMismatch):
        registry.acknowledge(wrong_ack)
    with pytest.raises(product.ProductSlotUnknown):
        registry.cleanup(scope, wire.RunnerExit(None, None, "transport_lost", "unknown"))
    registry.acknowledge(scope)
    with pytest.raises(product.ProductSlotBusy):
        registry.reserve(_scope("workspace-a", "d"))


@pytest.mark.parametrize("scenario", ["tampered_ready", "timeout"])
def test_ambiguous_handshake_retains_fence_after_start_bytes(scenario, tmp_path):
    registry, _, secrets = _registry(tmp_path)
    client = _client(registry, timeout=0.05 if scenario == "timeout" else 1.0)
    scope = _scope("workspace-a", "a")
    with _serve(tmp_path / "slot-a.sock", secrets["workspace-a"], scenario) as _server:
        with pytest.raises(product.ProductSlotUnknown):
            _start(client, scope)
        with pytest.raises(product.ProductSlotBusy):
            registry.reserve(_scope("workspace-a", "d"))


def test_pre_dispatch_connect_failure_releases_lease_for_retry(tmp_path):
    registry, _, _ = _registry(tmp_path)
    client = _client(registry, timeout=0.05)
    scope = _scope("workspace-a", "a")
    with pytest.raises(product.ProductSlotUnavailable):
        _start(client, scope)
    assert not registry.owns(scope)
    registry.reserve(scope)
    assert registry.owns(scope)


def test_from_environment_still_fails_closed_without_product_bindings(monkeypatch):
    monkeypatch.delenv(product.PRODUCT_BINDINGS_ENV, raising=False)
    with pytest.raises(ValueError, match="Product ACP slot bindings are unavailable"):
        product.ProductSlotRegistry.from_environment()


def test_pytest_collection_bootstrap_restores_environment_and_preserves_bindings(monkeypatch):
    conftest_path = Path(__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("runtime_adapter_conftest_under_test", conftest_path)
    assert spec is not None and spec.loader is not None
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)

    transport_name = "BYQ_DSH_ACP_PROCESS_TRANSPORT"
    bindings_name = product.PRODUCT_BINDINGS_ENV
    monkeypatch.setenv(transport_name, "product-slot-v1")
    monkeypatch.delenv(bindings_name, raising=False)
    before = dict(os.environ)

    bootstrap.pytest_configure(None)
    configured = json.loads(os.environ[bindings_name])
    assert list(configured) == ["byq-pytest-workspace"]
    binding = configured["byq-pytest-workspace"]
    assert binding["socket_path"].startswith("/tmp/byq-product-slot-pytest-")
    assert binding["socket_path"].endswith(".sock")
    secret_value = os.environ[binding["control_secret_env"]]
    decoded_secret = base64.urlsafe_b64decode(secret_value + "=" * (-len(secret_value) % 4))
    assert len(decoded_secret) == 32
    assert os.environ[transport_name] == "product-slot-v1"

    bootstrap.pytest_unconfigure(None)
    assert dict(os.environ) == before

    provided_invalid_bindings = "not-json; preserve-me"
    monkeypatch.setenv(bindings_name, provided_invalid_bindings)
    before_provided = dict(os.environ)
    bootstrap.pytest_configure(None)
    assert os.environ[bindings_name] == provided_invalid_bindings
    bootstrap.pytest_unconfigure(None)
    assert dict(os.environ) == before_provided
