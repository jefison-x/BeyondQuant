from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
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
        self.prompt_error: Exception | None = None
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
        if self.prompt_error is not None:
            raise self.prompt_error
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
    monkeypatch.setenv("BYQ_MCP_ACP_SIGNING_KEY", "test-signing-key-0123456789abcdef")  # gitleaks:allow — fixed synthetic test key
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "synthetic-runtime-authority-token")
    (tmp_path / "composition.yml").write_text("[]\n", encoding="utf-8")
    runtime = RuntimeAdapter(compatibility)
    runtime.require_current_backend_authority = lambda: 7
    compatibility.runtime = runtime
    def backend_get(url, *, headers, timeout):
        active_runtime = compatibility.runtime or runtime
        record = active_runtime._get("reuse-session")
        assert url.endswith(f"/internal/runtime-authority/sessions/{quote(record.session_id, safe='')}/roots")
        assert headers == {
            "Authorization": "Bearer synthetic-runtime-authority-token",
            "X-BYQ-Owner-Principal": record.owner_principal,
            "X-BYQ-Workspace-ID": record.workspace_id,
            "X-BYQ-Trace-ID": record.trace_id,
        }
        assert timeout == 2.0
        return httpx.Response(200, json={
            "schema_version": "byq-business-root-status.v1",
            "roots": [{"root_run_id": record.process_root_id,
                       "local_validation_pre_ack": None,
                       "local_validation": None}],
        }, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", backend_get)
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


def test_failed_transport_recovers_only_new_input_in_fresh_native_after_exact_ack(acp_adapter):
    from app.compat.dsh_acp import AcpTransportError

    runtime = acp_adapter
    compat = runtime._compatibility
    compat.finish_reason = "failed"
    compat.prompt_error = AcpTransportError("official DSH ACP connection was lost")
    record, old_root, receipt = _create_and_complete(runtime, compat, "failed input")
    old_harness = compat.harnesses[0]
    old_prompts = list(old_harness.prompts)
    old_native = record.runtime_session_id
    failed = [event for event in record.history if event["kind"] == "session.failed"][-1]
    assert failed["payload"]["code"] == "runtime-transport-failed"
    assert failed["payload"]["reason"] == "connection-lost"
    assert failed["payload"]["retryable"] is False
    with pytest.raises(SessionConflict):
        runtime.recover_acp_session("reuse-session", receipt, record.sequence)

    compat.close_rpc_failures = 1
    runtime.acknowledge_terminal("reuse-session", receipt)
    assert not record.current_generation.native_session_close_confirmed
    assert record.current_generation.process_exit_confirmed
    result = runtime.recover_acp_session("reuse-session", receipt, record.sequence)
    assert result["status"] == "idle"
    assert not record.reuse_native_session_ready
    # A lost resume response can be retried without recovering the failed native.
    runtime.recover_acp_session("reuse-session", receipt, record.sequence)
    assert compat.resumed == []
    assert len(compat.harnesses) == 1

    compat.prompt_error = None
    compat.finish_reason = "completed"
    new_root = runtime.submit_prompt("reuse-session", "new explicit instruction", conversation_context=[])
    _wait_for_status(runtime, SessionStatus.IDLE)
    assert new_root != old_root
    assert record.runtime_session_id != old_native
    assert compat.harnesses[-1].session_root != old_harness.session_root
    assert compat.harnesses[-1].environment.get("BYQ_NATIVE_ROOT_SESSION_ID") is None
    assert old_harness.closed
    assert len(old_prompts) == 1
    assert old_harness.prompts == old_prompts
    assert compat.harnesses[-1].prompts == ["new explicit instruction"]
    assert compat.resumed == []
    assert record.terminal_receipts[old_root] == receipt
    runtime.acknowledge_terminal("reuse-session", receipt)
    assert not compat.harnesses[-1].closed
    assert runtime._read_acp_binding("reuse-session")["root_run_id"] == new_root


@pytest.mark.parametrize("older_pending,same_original_boot", [(False, False), (True, False), (True, True)])
def test_restart_recovers_settled_failure_after_lost_native_close(
    acp_adapter, older_pending, same_original_boot,
):
    runtime = acp_adapter
    compat = runtime._compatibility
    compat.finish_reason = "failed"
    record, old_root, receipt = _create_and_complete(runtime, compat, "failed input")
    compat.close_rpc_failures = 1
    runtime.acknowledge_terminal("reuse-session", receipt)
    assert record.current_generation.process_exit_confirmed
    assert not record.current_generation.native_session_close_confirmed
    native_id = record.runtime_session_id
    failed_prompts = list(compat.harnesses[0].prompts)
    tail = record.sequence

    first_boot = RuntimeAdapter(compat)
    first_boot.boot_id = runtime.boot_id if same_original_boot else uuid.uuid4().hex
    first_boot.require_current_backend_authority = lambda: 7 if same_original_boot else 8
    try:
        first = first_boot.recover_acp_session("reuse-session", receipt, tail, trace_tail=tail)
        boundary = first["recovery_boundary"]
        assert boundary["state"] == "pending"
        assert boundary["next_sequence"] == tail + 1
        restarted = first_boot
        if older_pending:
            restarted = RuntimeAdapter(compat)
            restarted.boot_id = uuid.uuid4().hex
            restarted.require_current_backend_authority = lambda: 9
        try:
            compat.runtime = restarted
            if older_pending:
                path = restarted._acp_binding_path("reuse-session")
                original_binding = path.read_bytes()
                for unproven in ({"process_exit_confirmed": False}, {"cleanup_unconfirmed": True},
                                 {"domain_call_sequence": 1}, {"settlement_receipt": None}):
                    path.write_text(json.dumps({**json.loads(original_binding), **unproven}))
                    with pytest.raises(SessionConflict, match="recovery boundary binding is invalid"):
                        restarted.recover_acp_session("reuse-session", receipt, tail, trace_tail=tail)
                path.write_bytes(original_binding)
                with pytest.raises(SessionConflict, match="settled|another trace"):
                    restarted.recover_acp_session("reuse-session", {}, tail, trace_tail=tail)
                result = restarted.recover_acp_session("reuse-session", receipt, tail, trace_tail=tail)
                assert result["boot_id"] != boundary["runtime_boot_id"]
                assert result["recovery_boundary"] == boundary
            with pytest.raises(SessionConflict, match="boundary is not acknowledged"):
                restarted.submit_prompt("reuse-session", "not admitted")
            ack = {"trace_tail": tail + 1, "boundary_ack_sha256": boundary["event_sha256"]}
            result = restarted.recover_acp_session("reuse-session", receipt, tail + 1, **ack)
            assert result["recovery_boundary"] == {**boundary, "state": "acknowledged"}
            assert restarted.recover_acp_session("reuse-session", receipt, tail + 1, **ack) == result
            assert restarted.recovery_binding("reuse-session")["settlement_receipt"] == receipt
            compat.finish_reason = "completed"
            new_root = restarted.submit_prompt("reuse-session", "new input", conversation_context=[])
            _wait_for_status(restarted, SessionStatus.IDLE)
            assert new_root != old_root
            assert restarted._get("reuse-session").runtime_session_id != native_id
            assert not compat.resumed
            assert [h.prompts for h in compat.harnesses] == [failed_prompts, ["new input"]]
        finally:
            if older_pending:
                restarted.close()
    finally:
        first_boot.close()


@pytest.mark.parametrize("unproven", [
    "native_close_mismatch", "binding_exit", "generation_exit", "cleanup", "receipt", "domain_drain",
])
def test_failed_fresh_native_recovery_preserves_settlement_and_cleanup_fences(acp_adapter, unproven):
    runtime = acp_adapter
    compat = runtime._compatibility
    compat.finish_reason = "failed"
    record, _root, receipt = _create_and_complete(runtime, compat)
    compat.close_rpc_failures = 1
    runtime.acknowledge_terminal("reuse-session", receipt)
    binding_path = runtime._acp_binding_path("reuse-session")
    binding = json.loads(binding_path.read_text())
    if unproven == "native_close_mismatch":
        binding["native_session_close_confirmed"] = True
    elif unproven == "binding_exit":
        binding["process_exit_confirmed"] = False
    elif unproven == "generation_exit":
        record.current_generation.process_exit_confirmed = False
    elif unproven == "cleanup":
        record.cleanup_unconfirmed = True
    elif unproven == "receipt":
        receipt = {**receipt, "event_sha256": "0" * 64}
    elif unproven == "domain_drain":
        record.domain_call_sequence += 1
    binding_path.write_text(json.dumps(binding))
    with pytest.raises(SessionConflict):
        runtime.recover_acp_session("reuse-session", receipt, record.sequence)
    assert record.status == SessionStatus.FAILED
    assert len(compat.harnesses) == 1
    assert compat.resumed == []


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


def test_idle_release_preserves_settled_public_session_without_native_resume(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, root, receipt = _create_and_complete(runtime, compat)
    old_native_id = record.runtime_session_id

    assert runtime.acknowledge_terminal("reuse-session", receipt) == {"receipt": receipt}
    runtime.release_session("reuse-session", preserve_conversation=True)
    binding = runtime._read_acp_binding("reuse-session")
    assert binding["closed"] is False
    assert binding["settlement_receipt"] == receipt
    assert binding["root_run_id"] == root

    restarted = RuntimeAdapter(compat)
    restarted.require_current_backend_authority = lambda: 8
    compat.runtime = restarted
    try:
        recovery = restarted.recovery_binding("reuse-session")
        assert recovery["state"] == "settled"
        assert recovery["settlement_receipt"] == receipt
        recovered = restarted.recover_acp_session(
            "reuse-session", receipt, recovery["sequence"],
        )
        assert recovered["status"] == SessionStatus.IDLE
        assert recovered["resumed_from_run_id"] is None
        assert not compat.resumed
        boundary = recovered["recovery_boundary"]
        assert boundary["state"] == "pending"
        with pytest.raises(SessionConflict, match="recovery trace boundary is not acknowledged"):
            restarted.submit_prompt("reuse-session", "next user input")
        restarted.recover_acp_session(
            "reuse-session", receipt, boundary["next_sequence"],
            trace_tail=boundary["next_sequence"],
            boundary_ack_sha256=boundary["event_sha256"],
        )
        assert restarted._read_acp_binding("reuse-session")["recovery_boundary"]["state"] == "acknowledged"

        next_root = restarted.submit_prompt(
            "reuse-session", "next user input",
            conversation_context=[
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "completed answer"},
            ],
        )
        _wait_for_status(restarted, SessionStatus.IDLE)
        assert not compat.resumed
        assert compat.created[-1][1] != old_native_id
        fresh_prompt = compat.harnesses[-1].prompts[0]
        assert fresh_prompt.count("[BYQ_CONVERSATION_REHYDRATION]") == 1
        assert fresh_prompt.count('"completed answer"') == 1
        assert fresh_prompt.count("next user input") == 1

        next_record = restarted._get("reuse-session")
        terminal_receipt = next_record.terminal_receipts[next_root]
        assert next_record.sequence == terminal_receipt["sequence"]
        assert next_root in next_record.pending_terminal_receipts
        next_harness = compat.harnesses[-1]
        assert restarted.acknowledge_terminal("reuse-session", terminal_receipt) == {
            "receipt": terminal_receipt,
        }
        assert next_root not in next_record.pending_terminal_receipts
        assert next_record.current_generation.native_session_close_confirmed is True
        assert next_record.current_generation.process_exit_confirmed is True
        assert next_harness.closed is True
        assert compat.closed_processes[-1] is next_harness
        next_binding = restarted._read_acp_binding("reuse-session")
        assert next_binding["root_run_id"] == next_root
        assert next_binding["settlement_receipt"] == terminal_receipt
        assert "recovery_boundary" not in next_binding
        assert next_binding["previous_boot_id"] == restarted.boot_id
        assert next_binding["previous_authority_epoch"] == next_record.authority_epoch == 8
        assert next_binding["runtime_generation"] == next_record.runtime_generation
        assert next_binding["native_session_id"] == next_record.runtime_session_id
        assert next_binding["cwd"] == str(Path(next_record.recovery_cwd).resolve())
        assert next_binding["sequence"] == terminal_receipt["sequence"]
        assert next_binding["cleanup_unconfirmed"] is False
    finally:
        restarted.close()


def test_acknowledged_recovery_boundary_tracks_idle_release_tail(acp_adapter):
    runtime = acp_adapter
    compat = runtime._compatibility
    record, root, receipt = _create_and_complete(runtime, compat)

    assert runtime.acknowledge_terminal("reuse-session", receipt) == {"receipt": receipt}
    runtime.release_session("reuse-session", preserve_conversation=True)

    restarted = RuntimeAdapter(compat)
    restarted.require_current_backend_authority = lambda: 8
    compat.runtime = restarted
    try:
        original_binding = restarted._read_acp_binding("reuse-session")
        original_boot_id = original_binding["previous_boot_id"]
        original_authority_epoch = original_binding["previous_authority_epoch"]
        recovery = restarted.recovery_binding("reuse-session")
        recovered = restarted.recover_acp_session(
            "reuse-session", receipt, recovery["sequence"],
        )
        first_boundary = recovered["recovery_boundary"]
        assert first_boundary["state"] == "pending"
        with pytest.raises(SessionConflict, match="recovery boundary must be acknowledged"):
            restarted.release_session("reuse-session", preserve_conversation=True)
        with pytest.raises(SessionConflict, match="recovery boundary ACK does not match"):
            restarted.recover_acp_session(
                "reuse-session", receipt, first_boundary["next_sequence"],
                trace_tail=first_boundary["next_sequence"], boundary_ack_sha256="0" * 64,
            )
        released_record = restarted._get("reuse-session")
        acknowledged_event = next(
            event for event in released_record.history
            if event["kind"] == "session.reattached"
        )

        restarted.recover_acp_session(
            "reuse-session", receipt, first_boundary["next_sequence"],
            trace_tail=first_boundary["next_sequence"],
            boundary_ack_sha256=first_boundary["event_sha256"],
        )
        acked_binding = restarted._read_acp_binding("reuse-session")
        assert acked_binding["recovery_boundary"] == {
            **first_boundary, "state": "acknowledged",
        }
        assert acked_binding["previous_boot_id"] == original_boot_id
        assert acked_binding["previous_authority_epoch"] == original_authority_epoch
        assert acked_binding["root_run_id"] == root
        assert acked_binding["settlement_receipt"] == receipt
        assert acked_binding["sequence"] == first_boundary["next_sequence"]

        restarted.release_session("reuse-session", preserve_conversation=True)
        release_tail = released_record.sequence
        release_event = released_record.history[-1]
        assert release_event["kind"] == "session.closed"
        assert release_event["sequence"] == release_tail

        # The Gateway supplies the actual append-only trace tail. The prior
        # ACKed boundary remains immutable while the release advances cursor.
        after_release = restarted._read_acp_binding("reuse-session")
        assert after_release["recovery_boundary"] == acked_binding["recovery_boundary"]
        assert after_release["sequence"] == release_tail
        assert after_release["root_run_id"] == root
        assert after_release["settlement_receipt"] == receipt
        assert after_release["previous_boot_id"] == original_boot_id
        assert after_release["previous_authority_epoch"] == original_authority_epoch

        foreign_boot = RuntimeAdapter(compat)
        foreign_boot.require_current_backend_authority = lambda: 8
        foreign_boot.boot_id = "f" * 32
        try:
            assert foreign_boot.boot_id != restarted.boot_id
            with pytest.raises(SessionConflict, match="another trace or Runtime boot"):
                foreign_boot.recover_acp_session(
                    "reuse-session", receipt, release_tail, trace_tail=release_tail,
                )
        finally:
            foreign_boot.close()

        with pytest.raises(SessionConflict, match="acknowledged recovery boundary requires"):
            restarted.recover_acp_session(
                "reuse-session", receipt, release_tail + 1,
                trace_tail=release_tail + 1,
            )
        recovered_again = restarted.recover_acp_session(
            "reuse-session", receipt, release_tail, trace_tail=release_tail,
        )
        next_boundary = recovered_again["recovery_boundary"]
        assert next_boundary["state"] == "pending"
        assert next_boundary["binding_sequence"] == release_tail
        assert next_boundary["next_sequence"] == release_tail + 1
        assert next_boundary["previous_boot_id"] == original_boot_id
        assert next_boundary["previous_authority_epoch"] == original_authority_epoch
        assert next_boundary["runtime_boot_id"] == restarted.boot_id
        assert next_boundary["runtime_authority_epoch"] == 8
        assert next_boundary["event_sha256"] != first_boundary["event_sha256"]
        next_record = restarted._get("reuse-session")
        assert acknowledged_event in released_record.history
        assert next_record.history[-1]["sequence"] == release_tail + 1
        assert next_record.history[-1]["kind"] == "session.reattached"
        assert next_record.history[-1]["payload"]["root_run_id"] == root
        assert next_record.history[-1]["payload"]["prior_sequence"] == release_tail
        assert next_record.history[-1]["payload"]["authority_epoch"] == 8
        with pytest.raises(SessionConflict, match="recovery boundary must be acknowledged"):
            restarted.release_session("reuse-session", preserve_conversation=True)
        with pytest.raises(SessionConflict, match="recovery boundary ACK does not match"):
            restarted.recover_acp_session(
                "reuse-session", receipt, next_boundary["next_sequence"],
                trace_tail=next_boundary["next_sequence"], boundary_ack_sha256="0" * 64,
            )
        pending_binding = restarted._read_acp_binding("reuse-session")
        assert pending_binding["recovery_boundary"]["state"] == "pending"
        assert pending_binding["sequence"] == release_tail
        restarted.recover_acp_session(
            "reuse-session", receipt, next_boundary["next_sequence"],
            trace_tail=next_boundary["next_sequence"],
            boundary_ack_sha256=next_boundary["event_sha256"],
        )
        acked_again = restarted._read_acp_binding("reuse-session")
        assert acked_again["recovery_boundary"]["state"] == "acknowledged"
        assert acked_again["sequence"] == next_boundary["next_sequence"]
        assert not compat.resumed
        assert all(not harness.prompts for harness in compat.harnesses[1:])
    finally:
        restarted.close()


def test_preserve_release_requires_ack_and_cannot_reopen_ended_binding(acp_adapter, monkeypatch):
    runtime = acp_adapter
    record, _root, receipt = _create_and_complete(runtime, runtime._compatibility)

    with pytest.raises(SessionConflict, match="Backend terminal receipt must be acknowledged"):
        runtime.release_session("reuse-session", preserve_conversation=True)
    unsettled = runtime._read_acp_binding("reuse-session")
    assert unsettled["closed"] is False
    assert unsettled["settlement_receipt"] is None

    assert runtime.acknowledge_terminal("reuse-session", receipt) == {"receipt": receipt}
    # Retain the ended Adapter record to exercise a repeated internal request;
    # the preserve intent must not rewrite an already ended binding as open.
    monkeypatch.setattr(runtime, "_maybe_reap_released", lambda _record: False)
    runtime.release_session("reuse-session")
    ended = runtime._read_acp_binding("reuse-session")
    assert ended["closed"] is True
    with pytest.raises(SessionConflict, match="BYQ session was ended"):
        runtime.release_session("reuse-session", preserve_conversation=True)
    assert runtime._read_acp_binding("reuse-session")["closed"] is True

    restarted = RuntimeAdapter(runtime._compatibility)
    restarted.require_current_backend_authority = lambda: 8
    try:
        with pytest.raises(SessionConflict, match="BYQ session was ended"):
            restarted.recovery_binding("reuse-session")
        with pytest.raises(SessionConflict, match="BYQ session was ended"):
            restarted.recover_acp_session("reuse-session", receipt, record.sequence)
        assert "reuse-session" not in restarted._sessions
        assert not runtime._compatibility.resumed
    finally:
        restarted.close()


def test_hard_cancel_cannot_be_overridden_by_preserve_release(acp_adapter, monkeypatch):
    runtime = acp_adapter
    compat = runtime._compatibility
    runtime.create_session("reuse-session", "reuse-trace", "alice", "workspace_alice")
    compat.block_prompt = True
    root = runtime.submit_prompt("reuse-session", "cancel this root")
    assert compat.prompt_started.wait(1)

    original_close = compat.close

    def close_and_unblock(harness):
        compat.allow_prompt_return.set()
        original_close(harness)

    monkeypatch.setattr(compat, "close", close_and_unblock)
    runtime.cancel_session("reuse-session", "hard")
    record = runtime._get("reuse-session")
    assert record.conversation_ended is True
    receipt = record.terminal_receipts[root]

    with pytest.raises(SessionConflict, match="Backend terminal receipt must be acknowledged"):
        runtime.release_session("reuse-session", preserve_conversation=True)

    assert runtime.acknowledge_terminal("reuse-session", receipt) == {"receipt": receipt}
    binding = runtime._read_acp_binding("reuse-session")
    assert binding["closed"] is True
    with pytest.raises(SessionConflict, match="BYQ session was ended"):
        runtime.release_session("reuse-session", preserve_conversation=True)


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
            restarted.recover_acp_session("reuse-session", receipt, binding["sequence"])
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
            restarted.recover_acp_session("reuse-session", transfer, binding["sequence"])
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
