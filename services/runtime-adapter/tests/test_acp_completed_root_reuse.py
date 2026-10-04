from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.runtime import RuntimeAdapter, SessionConflict, SessionStatus


@dataclass
class FakeAcpHarness:
    environment: dict[str, str]
    session_root: Path
    closed: bool = False
    native_session_ids: set[str] = field(default_factory=set)
    prompts: list[str] = field(default_factory=list)


class FakeAcpCompatibility:
    family = "dsh-v0.2.0-rc.2-acp"

    def __init__(self) -> None:
        self.harnesses: list[FakeAcpHarness] = []
        self.created: list[tuple[FakeAcpHarness, str, Path]] = []
        self.resumed: list[tuple[FakeAcpHarness, str, Path]] = []
        self.closed_sessions: list[tuple[FakeAcpHarness, str]] = []
        self.closed_processes: list[FakeAcpHarness] = []
        self.finish_reason = "completed"
        self.close_rpc_failures = 0
        self.process_close_failures = 0
        self.resume_failures = 0
        self.prompt_started = threading.Event()
        self.allow_prompt_return = threading.Event()
        self.block_prompt = False
        self.runtime: RuntimeAdapter | None = None

    def runtime_command(self, _runtime_root: Path, _node: str) -> tuple[str, ...]:
        return ("synthetic-dsh",)

    def build_harness(self, *, session_root: Path, environment: dict[str, str], **_kwargs):
        session_root.mkdir(parents=True, exist_ok=True)
        harness = FakeAcpHarness(dict(environment), session_root)
        self.harnesses.append(harness)
        return harness

    def start(self, harness: FakeAcpHarness) -> None:
        assert not harness.closed

    def create_session(self, harness: FakeAcpHarness, *, cwd: Path | str | None = None) -> str:
        native_id = str(uuid.uuid4())
        harness.native_session_ids.add(native_id)
        self.created.append((harness, native_id, Path(cwd or harness.session_root)))
        return native_id

    def resume_session(self, harness: FakeAcpHarness, native_session_id: str, *, cwd=None) -> str:
        if self.resume_failures:
            self.resume_failures -= 1
            raise RuntimeError("synthetic resume failure")
        assert harness.environment.get("BYQ_NATIVE_ROOT_SESSION_ID") == native_session_id
        harness.native_session_ids.add(native_session_id)
        self.resumed.append((harness, native_session_id, Path(cwd or harness.session_root)))
        return native_session_id

    @staticmethod
    def prepare_prompt(harness: FakeAcpHarness, _session_id: str):
        return SimpleNamespace(harness=harness)

    def run_prepared_prompt(self, prepared, content: str, _on_notification) -> str:
        prepared.harness.prompts.append(content)
        self.prompt_started.set()
        if self.block_prompt:
            assert self.allow_prompt_return.wait(2)
        return self.finish_reason

    def cancel_session(self, _harness: FakeAcpHarness, _native_session_id: str) -> None:
        self.allow_prompt_return.set()

    def close_session(self, harness: FakeAcpHarness, native_session_id: str) -> None:
        self.closed_sessions.append((harness, native_session_id))
        if self.runtime is not None:
            record = self.runtime._get("reuse-session")
            assert record.settlement_receipt is not None
            assert record.settlement_receipt["root_run_id"] == record.process_root_id
        if self.close_rpc_failures:
            self.close_rpc_failures -= 1
            raise RuntimeError("synthetic ACP close response lost")
        harness.native_session_ids.discard(native_session_id)

    def close(self, harness: FakeAcpHarness) -> None:
        self.closed_processes.append(harness)
        if self.process_close_failures:
            self.process_close_failures -= 1
            raise RuntimeError("synthetic process exit unconfirmed")
        harness.closed = True

    @staticmethod
    def observe(_notification, *, root_session_id: str):
        return SimpleNamespace(
            kind="ignored", session_id=root_session_id, root_session=True,
            runtime_activity=False, event_sequence=None,
        )


@pytest.fixture
def acp_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RuntimeAdapter:
    compatibility = FakeAcpCompatibility()
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_MCP_ACP_DISCOVERY_TOKEN", "test-discovery-token")
    monkeypatch.setenv("BYQ_MCP_ACP_SIGNING_KEY", "test-signing-key-0123456789abcdef")
    (tmp_path / "composition.yml").write_text("[]\n", encoding="utf-8")
    runtime = RuntimeAdapter(compatibility)
    runtime.require_current_backend_authority = lambda: 7
    compatibility.runtime = runtime
    try:
        yield runtime
    finally:
        runtime.close()


def _wait_for_status(runtime: RuntimeAdapter, status: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if runtime._get("reuse-session").status == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"session did not reach {status}")


def _create_and_complete(runtime: RuntimeAdapter, compat: FakeAcpCompatibility, content: str = "first"):
    runtime.create_session(
        "reuse-session", "reuse-trace", "alice", "workspace_alice",
        conversation_context=[{"role": "user", "content": "seed context"}],
    )
    root = runtime.submit_prompt("reuse-session", content)
    _wait_for_status(runtime, SessionStatus.IDLE if compat.finish_reason == "completed" else SessionStatus.FAILED)
    record = runtime._get("reuse-session")
    return record, root, record.terminal_receipts[root]


def _transfer_receipt(restarted: RuntimeAdapter, binding: dict) -> dict:
    return {
        "schema_version": "byq-runtime-root-authority-transfer-receipt.v1",
        "root_run_id": binding["root_run_id"],
        "previous_boot_id": binding["previous_boot_id"],
        "previous_authority_epoch": binding["previous_authority_epoch"],
        "boot_id": restarted.boot_id,
        "authority_epoch": restarted.require_current_backend_authority(),
        "status": "transferred",
    }


def test_completed_exact_ack_closes_then_resumes_same_native_without_public_history_replay(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, first_root, first_receipt = _create_and_complete(runtime, compat)
    first_harness = compat.harnesses[0]
    native_id = record.runtime_session_id
    old_cwd = record.recovery_cwd
    old_generation = record.runtime_generation

    assert not first_harness.closed
    assert not compat.closed_sessions
    with pytest.raises(SessionConflict, match="acknowledged"):
        runtime.submit_prompt("reuse-session", "second", conversation_context=[])
    assert runtime.acknowledge_terminal("reuse-session", first_receipt) == {"receipt": first_receipt}
    assert compat.closed_sessions == [(first_harness, native_id)]
    assert first_harness.closed
    assert record.current_generation.native_session_close_confirmed
    assert record.current_generation.process_exit_confirmed
    assert record.reuse_native_session_ready

    second_context = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer from first root"},
    ]
    second_root = runtime.submit_prompt(
        "reuse-session", "second input", conversation_context=second_context,
    )
    _wait_for_status(runtime, SessionStatus.IDLE)
    second_harness = compat.harnesses[-1]
    assert compat.created == [(first_harness, native_id, Path(old_cwd))]
    assert compat.resumed[-1] == (second_harness, native_id, Path(old_cwd))
    assert second_harness.session_root == Path(old_cwd)
    assert second_harness.environment["BYQ_ROOT_RUN_ID"] == second_root
    assert second_harness.environment["BYQ_ROOT_RUN_ID"] != first_root
    assert second_harness.environment["BYQ_DSH_RUN_ID"] != first_harness.environment["BYQ_DSH_RUN_ID"]
    assert second_harness.environment["BYQ_NATIVE_ROOT_SESSION_ID"] == native_id
    assert second_harness.prompts == ["second input"]
    assert record.runtime_generation != old_generation

    # A lost response retry for the old receipt must not overwrite the current
    # root's binding or close its live ACP process.
    current_binding = runtime._read_acp_binding("reuse-session")
    assert current_binding["root_run_id"] == second_root
    assert current_binding["settlement_receipt"] is None
    runtime.acknowledge_terminal("reuse-session", first_receipt)
    after_retry = runtime._read_acp_binding("reuse-session")
    assert after_retry["root_run_id"] == second_root
    assert after_retry["settlement_receipt"] is None
    assert not second_harness.closed


def test_close_rpc_failure_uses_fresh_native_session_after_process_exit(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, _root, receipt = _create_and_complete(runtime, compat)
    old_harness = compat.harnesses[0]
    old_native = record.runtime_session_id
    compat.close_rpc_failures = 1

    assert runtime.acknowledge_terminal("reuse-session", receipt) == {"receipt": receipt}
    assert old_harness.closed
    assert record.current_generation.process_exit_confirmed
    assert not record.current_generation.native_session_close_confirmed
    assert not record.reuse_native_session_ready

    runtime.submit_prompt("reuse-session", "fresh root", conversation_context=[])
    _wait_for_status(runtime, SessionStatus.IDLE)
    fresh = compat.harnesses[-1]
    assert fresh.session_root != old_harness.session_root
    assert fresh.environment.get("BYQ_NATIVE_ROOT_SESSION_ID") is None
    assert record.runtime_session_id != old_native


def test_process_exit_failure_keeps_terminal_fence_until_exact_ack_retry(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, _root, receipt = _create_and_complete(runtime, compat)
    compat.process_close_failures = 1

    with pytest.raises(SessionConflict, match="exit could not be confirmed"):
        runtime.acknowledge_terminal("reuse-session", receipt)
    assert receipt["root_run_id"] in record.pending_terminal_receipts
    assert record.process_closing
    assert not record.current_generation.process_exit_confirmed
    with pytest.raises(SessionConflict, match="cleanup"):
        runtime.submit_prompt("reuse-session", "must wait", conversation_context=[])

    assert runtime.acknowledge_terminal("reuse-session", receipt) == {"receipt": receipt}
    assert not record.pending_terminal_receipts
    assert record.current_generation.process_exit_confirmed
    assert record.reuse_native_session_ready


def test_failed_resume_persists_fence_and_restart_cannot_recover_promptable_session(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, _root, receipt = _create_and_complete(runtime, compat)
    runtime.acknowledge_terminal("reuse-session", receipt)
    compat.resume_failures = 1

    with pytest.raises(RuntimeError, match="resume failure"):
        runtime.submit_prompt("reuse-session", "new root", conversation_context=[])
    assert record.cleanup_unconfirmed
    assert record.cleanup_harness is not None
    binding = runtime._read_acp_binding("reuse-session")
    assert binding["cleanup_unconfirmed"] is True

    restarted = RuntimeAdapter(compat)
    restarted.require_current_backend_authority = lambda: 8
    try:
        with pytest.raises(SessionConflict, match="unconfirmed process cleanup"):
            restarted.recover_acp_session("reuse-session", receipt, record.sequence)
        with pytest.raises(SessionConflict, match="unconfirmed process cleanup"):
            restarted.recovery_binding("reuse-session")
        with pytest.raises(KeyError):
            restarted.submit_prompt("reuse-session", "not admitted")
    finally:
        restarted.close()


def test_shutdown_attempts_cleanup_harness_when_primary_process_close_fails(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, _root, _receipt = _create_and_complete(runtime, compat)
    cleanup_harness = FakeAcpHarness({}, Path(record.recovery_cwd) / "orphaned-startup")
    record.cleanup_harness = cleanup_harness
    compat.process_close_failures = 1

    with pytest.raises(RuntimeError, match="process exit unconfirmed"):
        runtime.close()
    assert compat.closed_processes == [record.harness, cleanup_harness]
    assert cleanup_harness.closed


def test_closed_before_ack_recovery_rejects_unconfirmed_prior_process_exit(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, _root, receipt = _create_and_complete(runtime, compat)
    binding_path = runtime._acp_binding_path("reuse-session")
    # Emulate an older additive-v1 record: missing proof fields must remain
    # false and cannot make a Backend-closed root promptable after restart.
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding.pop("native_session_close_confirmed")
    binding.pop("process_exit_confirmed")
    binding.pop("cleanup_unconfirmed")
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    restarted = RuntimeAdapter(compat)
    restarted.require_current_backend_authority = lambda: 7
    try:
        # Gateway reads this before it asks Backend to transfer authority, so
        # an unprovable old process cannot strand a root after transfer.
        with pytest.raises(SessionConflict, match="prior process exit is confirmed"):
            restarted.recovery_binding("reuse-session")
        with pytest.raises(SessionConflict, match="no confirmed prior process exit"):
            restarted.recover_acp_session("reuse-session", receipt, record.sequence)
        assert "reuse-session" not in restarted._sessions
        assert not compat.resumed
    finally:
        restarted.close()


def test_unsettled_transfer_recovery_blocks_without_old_process_exit_proof(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, _root, _receipt = _create_and_complete(runtime, compat)
    binding = runtime._read_acp_binding("reuse-session")
    assert not binding["process_exit_confirmed"]

    restarted = RuntimeAdapter(compat)
    restarted.require_current_backend_authority = lambda: 8
    transfer = _transfer_receipt(restarted, binding)
    try:
        with pytest.raises(SessionConflict, match="prior process exit is confirmed"):
            restarted.recovery_binding("reuse-session")
        with pytest.raises(SessionConflict, match="no confirmed prior process exit"):
            restarted.recover_acp_session("reuse-session", transfer, record.sequence)
        assert "reuse-session" not in restarted._sessions
        assert not compat.resumed
    finally:
        restarted.close()


def test_proven_transfer_repair_exit_allows_exact_terminal_ack(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, root, _old_terminal_receipt = _create_and_complete(runtime, compat)
    old_harness = compat.harnesses[0]
    # Model independently confirmed isolation of the old-boot process. A
    # repair-process close below is a separate proof and cannot stand in for it.
    compat.close(old_harness)
    record.current_generation.process_exit_confirmed = True
    record.process_closed = True
    runtime._persist_acp_binding(record)
    binding = runtime._read_acp_binding("reuse-session")
    assert binding["process_exit_confirmed"]

    restarted = RuntimeAdapter(compat)
    restarted.require_current_backend_authority = lambda: 8
    compat.runtime = restarted
    transfer = _transfer_receipt(restarted, binding)
    try:
        recovered = restarted.recover_acp_session(
            "reuse-session", transfer, binding["sequence"],
        )
        recovered_record = restarted._get("reuse-session")
        repair_harness = compat.harnesses[-1]
        assert recovered["continuity"] == "reattached"
        assert recovered["resumed_from_run_id"] == root
        assert compat.resumed[-1][1] == binding["native_session_id"]
        assert repair_harness.closed
        assert recovered_record.current_generation.process_exit_confirmed

        terminal_receipt = recovered_record.terminal_receipts[root]
        assert restarted.acknowledge_terminal("reuse-session", terminal_receipt) == {
            "receipt": terminal_receipt,
        }
        assert not recovered_record.pending_terminal_receipts
        persisted = restarted._read_acp_binding("reuse-session")
        assert persisted["settlement_receipt"] == terminal_receipt
        assert persisted["process_exit_confirmed"]
    finally:
        restarted.close()


def test_soft_cancelled_root_never_enters_native_reuse_path(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    runtime.create_session("reuse-session", "reuse-trace", "alice", "workspace_alice")
    compat.block_prompt = True
    compat.finish_reason = "cancelled"
    runtime.submit_prompt("reuse-session", "cancel me")
    assert compat.prompt_started.wait(1)
    runtime.cancel_session("reuse-session", "soft")
    _wait_for_status(runtime, SessionStatus.IDLE)
    record = runtime._get("reuse-session")
    root = record.process_root_id
    receipt = record.terminal_receipts[root]
    runtime.acknowledge_terminal("reuse-session", receipt)
    assert not record.reuse_native_session_ready

    compat.block_prompt = False
    compat.finish_reason = "completed"
    old_native = record.runtime_session_id
    runtime.submit_prompt("reuse-session", "continue after cancel", conversation_context=[])
    _wait_for_status(runtime, SessionStatus.IDLE)
    assert record.runtime_session_id != old_native
    assert compat.harnesses[-1].environment.get("BYQ_NATIVE_ROOT_SESSION_ID") is None
