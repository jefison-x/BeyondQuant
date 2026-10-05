"""Focused lifecycle tests for Product ACP slot transport integration."""

from __future__ import annotations

import json
import os
import queue
import stat
import threading
from pathlib import Path

import pytest

from app.acp_product_slot_client import ProductSlotRejected, ProductSlotUnavailable
from app.compat import acp_slot_transport as slot_transport
from app.compat.dsh_acp import AcpHarness, AcpTransportError, DshAcpCompatibility
from app.research_judgment_acp_runner_client import RunnerExit


ROOT_ID = "a" * 32
SCOPE = {
    "workspace_id": "workspace-a",
    "owner_principal": "owner-a",
    "session_id": "session-a",
    "trace_id": "trace-a",
    "root_run_id": ROOT_ID,
    "runtime_boot_id": "b" * 32,
    "generation_id": "generation-" + "c" * 32,
    "cwd_leaf": "root-" + ROOT_ID,
}


def _environment() -> dict[str, str]:
    return {
        "BYQ_MCP_URL": "http://mcp:8300/mcp/v1",
        "BYQ_MCP_ACP_DISCOVERY_TOKEN": "d" * 48,
        "BYQ_MCP_ACP_SIGNING_KEY": "s" * 48,
        "BYQ_RUNTIME_BOOT_ID": SCOPE["runtime_boot_id"],
        "BYQ_OWNER_PRINCIPAL": SCOPE["owner_principal"],
        "BYQ_WORKSPACE_ID": SCOPE["workspace_id"],
        "BYQ_ACTOR_PRINCIPAL": "byq-product-agent-" + SCOPE["session_id"],
        "BYQ_TRACE_ID": SCOPE["trace_id"],
        "BYQ_SESSION_ID": SCOPE["session_id"],
        "BYQ_PROVIDER_SESSION_ID": "123e4567-e89b-42d3-a456-426614174000",
        "BYQ_DSH_RUN_ID": SCOPE["generation_id"],
        "BYQ_ROOT_RUN_ID": SCOPE["root_run_id"],
        "OPENCODE_API_KEY": "p" * 48,
    }


class _Registry:
    def __init__(self, *, lease_after_start: bool = True) -> None:
        self.scope = None
        self.lease_after_start = lease_after_start
        self.cleaned = False
        self.acknowledged = False
        self.cleanup_calls = 0
        self.ack_calls = 0

    def owns(self, scope):
        return self.lease_after_start and self.scope == dict(scope)

    def cleanup(self, scope, receipt):
        assert self.scope == dict(scope)
        assert receipt.cleanup == "proven"
        self.cleanup_calls += 1
        self.cleaned = True
        self._release_if_complete()

    def acknowledge(self, scope):
        assert self.scope == dict(scope)
        self.ack_calls += 1
        self.acknowledged = True
        self._release_if_complete()

    def _release_if_complete(self):
        if self.cleaned and self.acknowledged:
            self.lease_after_start = False
            self.scope = None


class _FakeSession:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.events: queue.Queue[bytes | RunnerExit] = queue.Queue()
        self.cancelled = False
        self.active_receives = 0
        self.concurrent_receive = False
        self.wait_exit_timeouts: list[float] = []
        self._lock = threading.Lock()
        if mode == "malformed":
            self.events.put(b"{not-json}\n")

    def send_stdin(self, content: bytes) -> None:
        request = json.loads(content)
        if self.mode in {"valid", "wrong_version"} and request.get("method") == "initialize":
            version = 999 if self.mode == "wrong_version" else 1
            response = {"jsonrpc": "2.0", "id": 1,
                        "result": {"protocolVersion": version}}
            self.events.put((json.dumps(response, separators=(",", ":")) + "\n").encode())

    def receive(self, timeout_s=None):
        with self._lock:
            if self.active_receives:
                self.concurrent_receive = True
            self.active_receives += 1
        try:
            try:
                return self.events.get(timeout=timeout_s)
            except queue.Empty:
                return None
        finally:
            with self._lock:
                self.active_receives -= 1

    def cancel(self) -> None:
        self.cancelled = True
        if self.mode in {"valid", "wrong_version"}:
            self.events.put(RunnerExit(0, None, "cancelled", "proven"))

    def wait_exit(self, timeout_s=None) -> RunnerExit:
        assert timeout_s is not None and 0 < timeout_s <= slot_transport._CLOSE_TIMEOUT_SECONDS
        self.wait_exit_timeouts.append(timeout_s)
        with self._lock:
            assert self.active_receives == 0
        if self.mode == "malformed":
            return RunnerExit(0, None, "cancelled", "proven")
        raise AssertionError("wait_exit should not race the ACP reader")


def _fake_client(monkeypatch, registry, session=None, *, failure=None):
    class FakeClient:
        def __init__(self, actual_registry):
            assert actual_registry is registry

        def start(self, *, scope, env, deadline_at_ms, expected_cwd):
            assert env["BYQ_WORKSPACE_ID"] == SCOPE["workspace_id"]
            assert deadline_at_ms > 0
            assert Path(expected_cwd).name == SCOPE["cwd_leaf"]
            if failure is not None:
                raise failure
            registry.scope = dict(scope)
            registry.lease_after_start = True
            return session

    monkeypatch.setattr(slot_transport, "ProductRunnerClient", FakeClient)


def _compat(registry) -> DshAcpCompatibility:
    compat = DshAcpCompatibility.__new__(DshAcpCompatibility)
    compat.product_slots = registry
    compat._validate_runtime_identity = lambda _environment: None
    compat._validate_judgment_process_environment = lambda *_args: None
    return compat


def _harness(cwd: Path) -> AcpHarness:
    return AcpHarness(
        provider="opencode-go-chat",
        model="synthetic-model",
        composition=Path("/opt/byq/profiles/byq-product.patch.yml"),
        session_root=cwd,
        runtime_command=("dsh",),
        environment=_environment(),
    )


@pytest.mark.parametrize("mode", ["malformed", "wrong_version"])
def test_initialize_failure_keeps_exact_scope_and_close_drains_after_reader_exit(
    mode, tmp_path, monkeypatch,
):
    cwd = tmp_path / SCOPE["cwd_leaf"]
    cwd.mkdir(mode=0o700)
    registry = _Registry()
    session = _FakeSession(mode)
    _fake_client(monkeypatch, registry, session)
    compat = _compat(registry)
    harness = _harness(cwd)

    with pytest.raises(AcpTransportError):
        compat.start(harness)

    transport = harness.process
    assert isinstance(transport, slot_transport.SlotAcpProcess)
    assert harness.slot_scope == SCOPE
    assert registry.owns(SCOPE)

    compat.close(harness)

    assert session.cancelled
    assert len(session.wait_exit_timeouts) == (1 if mode == "malformed" else 0)
    assert not session.concurrent_receive
    assert registry.cleanup_calls == 1
    assert harness.process is None
    assert harness.slot_scope == SCOPE

    transport.close()
    assert registry.cleanup_calls == 1
    compat.acknowledge_slot(harness)
    assert harness.slot_scope is None
    assert not registry.lease_after_start
    compat.acknowledge_slot(harness)
    assert registry.ack_calls == 1
    compat.acknowledge_slot(None)


def test_exact_ack_before_cleanup_is_idempotent_and_cleanup_releases_slot(
    tmp_path, monkeypatch,
):
    cwd = tmp_path / SCOPE["cwd_leaf"]
    cwd.mkdir(mode=0o700)
    registry = _Registry()
    session = _FakeSession("valid")
    _fake_client(monkeypatch, registry, session)
    compat = _compat(registry)
    harness = _harness(cwd)

    compat.start(harness)
    transport = harness.process
    assert transport is not None
    assert harness.slot_scope == SCOPE

    compat.acknowledge_slot(harness)
    assert harness.slot_scope is None
    assert registry.lease_after_start
    compat.close(harness)
    transport.close()

    assert registry.ack_calls == 1
    assert registry.cleanup_calls == 1
    assert not registry.lease_after_start
    assert harness.process is None


def test_released_pre_dispatch_failure_clears_scope_and_is_retryable(
    tmp_path, monkeypatch,
):
    cwd = tmp_path / SCOPE["cwd_leaf"]
    cwd.mkdir(mode=0o700)
    registry = _Registry(lease_after_start=False)
    _fake_client(monkeypatch, registry,
                 failure=ProductSlotUnavailable("synthetic pre-dispatch failure"))
    compat = _compat(registry)
    harness = _harness(cwd)

    with pytest.raises(ProductSlotUnavailable):
        compat.start(harness)

    assert harness.process is None
    assert harness.slot_scope is None
    compat.close(harness)
    compat.acknowledge_slot(harness)
    assert registry.cleanup_calls == 0
    assert registry.ack_calls == 0


def test_held_scope_rejection_keeps_unknown_startup_fenced(tmp_path, monkeypatch):
    cwd = tmp_path / SCOPE["cwd_leaf"]
    cwd.mkdir(mode=0o700)
    registry = _Registry()
    registry.scope = dict(SCOPE)
    _fake_client(monkeypatch, registry,
                 failure=ProductSlotRejected("scope_consumed"))
    compat = _compat(registry)
    harness = _harness(cwd)

    with pytest.raises(ProductSlotRejected):
        compat.start(harness)

    transport = harness.process
    assert isinstance(transport, slot_transport.SlotAcpProcess)
    assert harness.slot_scope == SCOPE
    assert registry.owns(SCOPE)
    with pytest.raises(AcpTransportError, match="outcome remains unknown"):
        compat.close(harness)
    assert harness.process is transport
    assert harness.slot_scope == SCOPE
    assert registry.cleanup_calls == 0
    assert registry.ack_calls == 0


def test_product_session_leaf_is_private_and_existing_broad_mode_is_rejected(
    tmp_path,
):
    profile = tmp_path / "profile.patch.yml"
    profile.write_text("synthetic profile\n", encoding="utf-8")
    compat = _compat(_Registry())
    secure_home = tmp_path / "secure" / SCOPE["cwd_leaf"]

    compat.build_harness(
        provider="opencode-go-chat",
        model="synthetic-model",
        composition=profile,
        session_root=secure_home,
        runtime_command=("dsh",),
        environment=_environment(),
    )
    secure_stat = os.stat(secure_home)
    assert stat.S_IMODE(secure_stat.st_mode) == 0o700
    assert secure_stat.st_uid == os.getuid()
    assert secure_stat.st_gid == os.getgid()
    secure_tmp_stat = os.stat(secure_home / "tmp")
    assert stat.S_IMODE(secure_tmp_stat.st_mode) == 0o700
    assert secure_tmp_stat.st_uid == os.getuid()
    assert secure_tmp_stat.st_gid == os.getgid()

    broad_home = tmp_path / "broad" / SCOPE["cwd_leaf"]
    broad_home.mkdir(parents=True, mode=0o755)
    broad_home.chmod(0o755)
    with pytest.raises(AcpTransportError, match="permissions are unsafe"):
        compat.build_harness(
            provider="opencode-go-chat",
            model="synthetic-model",
            composition=profile,
            session_root=broad_home,
            runtime_command=("dsh",),
            environment=_environment(),
        )
    assert stat.S_IMODE(os.stat(broad_home).st_mode) == 0o755

    real_home = tmp_path / "real-home"
    real_home.mkdir(mode=0o700)
    symlink_home = tmp_path / "linked-home"
    symlink_home.symlink_to(real_home, target_is_directory=True)
    with pytest.raises(AcpTransportError, match="cannot be a symlink"):
        compat.build_harness(
            provider="opencode-go-chat",
            model="synthetic-model",
            composition=profile,
            session_root=symlink_home,
            runtime_command=("dsh",),
            environment=_environment(),
        )
    assert not (real_home / "tmp").exists()

    tmp_link_home = tmp_path / "tmp-link-home"
    tmp_link_home.mkdir(mode=0o700)
    tmp_target = tmp_path / "tmp-target"
    tmp_target.mkdir(mode=0o700)
    (tmp_link_home / "tmp").symlink_to(tmp_target, target_is_directory=True)
    with pytest.raises(AcpTransportError, match="scratch directory permissions are unsafe"):
        compat.build_harness(
            provider="opencode-go-chat",
            model="synthetic-model",
            composition=profile,
            session_root=tmp_link_home,
            runtime_command=("dsh",),
            environment=_environment(),
        )
