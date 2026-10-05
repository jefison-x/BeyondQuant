from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path

import pytest

from app.acp_product_slot_client import (
    ProductSlotBusy,
    ProductSlotLeaseMismatch,
    ProductSlotRejected,
    ProductSlotRegistry,
)
from app.runtime import RuntimeAuthorityUnavailable
from app.research_judgment_acp_runner_client import RunnerExit
from app.runtime import RuntimeAdapter, SessionConflict, SessionStatus

_FAKE_MODULE_NAME = "_acp_completed_root_reuse_fakes"
_FAKE_MODULE_SPEC = importlib.util.spec_from_file_location(
    _FAKE_MODULE_NAME, Path(__file__).with_name("test_acp_completed_root_reuse.py"),
)
assert _FAKE_MODULE_SPEC is not None and _FAKE_MODULE_SPEC.loader is not None
_FAKE_MODULE = importlib.util.module_from_spec(_FAKE_MODULE_SPEC)
sys.modules[_FAKE_MODULE_NAME] = _FAKE_MODULE
_FAKE_MODULE_SPEC.loader.exec_module(_FAKE_MODULE)
FakeAcpCompatibility = _FAKE_MODULE.FakeAcpCompatibility
FakeAcpHarness = _FAKE_MODULE.FakeAcpHarness


def _scope(workspace: str, suffix: str = "a") -> dict[str, str]:
    return {
        "workspace_id": workspace,
        "owner_principal": "slot-owner",
        "session_id": f"slot-session-{suffix}",
        "trace_id": f"slot-trace-{suffix}",
        "root_run_id": (suffix[0] * 32) if len(suffix) == 1 else uuid.uuid4().hex,
        "runtime_boot_id": "b" * 32,
        "generation_id": f"generation-{'c' * 32}",
        "cwd_leaf": f"session-{'d' * 32}",
    }


def _registry(workspaces: tuple[str, ...]) -> ProductSlotRegistry:
    bindings: dict[str, dict[str, str]] = {}
    environ: dict[str, str] = {}
    for index, workspace in enumerate(workspaces):
        secret_name = f"BYQ_ACP_PRODUCT_SLOT_TEST_{index}"
        secret = bytes([index + 1]) * 32
        bindings[workspace] = {
            "socket_path": f"/run/byq-acp-product/{index}/control.sock",
            "control_secret_env": secret_name,
        }
        environ[secret_name] = base64.urlsafe_b64encode(secret).decode().rstrip("=")
    return ProductSlotRegistry(
        json.dumps(bindings), environ=environ,
        judgment_socket_path="/run/byq-acp-judgment/control.sock",
    )


class SlotFakeCompatibility(FakeAcpCompatibility):
    family = "dsh-v0.2.0-rc.2-acp"

    def __init__(self, registry: ProductSlotRegistry) -> None:
        super().__init__()
        self.product_slots = registry
        self.start_attempts: list[FakeAcpHarness] = []
        self.successful_starts: list[FakeAcpHarness] = []

    @staticmethod
    def session_storage_root(base: Path, workspace_id: str | None) -> Path:
        assert workspace_id
        return base / workspace_id

    @staticmethod
    def _scope(harness: FakeAcpHarness) -> dict[str, str]:
        env = harness.environment
        return {
            "workspace_id": env["BYQ_WORKSPACE_ID"],
            "owner_principal": env["BYQ_OWNER_PRINCIPAL"],
            "session_id": env["BYQ_SESSION_ID"],
            "trace_id": env["BYQ_TRACE_ID"],
            "root_run_id": env["BYQ_ROOT_RUN_ID"],
            "runtime_boot_id": env["BYQ_RUNTIME_BOOT_ID"],
            "generation_id": env["BYQ_DSH_RUN_ID"],
            "cwd_leaf": harness.session_root.name,
        }

    def start(self, harness: FakeAcpHarness) -> None:
        self.start_attempts.append(harness)
        if not (harness.environment.get("DEEPSEEK_API_KEY")
                or harness.environment.get("OPENCODE_API_KEY")):
            # The real ProductRunnerClient validates provider credentials
            # before reserving or dispatching START. Model that no-launch
            # result without making a provider request.
            harness.process = None
            harness.slot_scope = None
            raise ProductSlotRejected("environment_rejected")
        scope = self._scope(harness)
        self.product_slots.reserve(scope)
        harness.slot_scope = scope
        harness.slot_scope_for_ack = scope
        harness.slot_scope_for_cleanup = scope
        harness.slot_cleanup_proven = False
        self.successful_starts.append(harness)

    def acknowledge_slot(self, harness: FakeAcpHarness) -> None:
        self.product_slots.acknowledge(harness.slot_scope_for_ack)
        # The compatibility layer may clear its public ACK scope after sending
        # it. The transport still keeps the independent cleanup scope.
        harness.slot_scope = None

    def close_session(self, harness: FakeAcpHarness, native_session_id: str) -> None:
        self.closed_sessions.append((harness, native_session_id))
        harness.native_session_ids.discard(native_session_id)

    def close(self, harness: FakeAcpHarness) -> None:
        if self.process_close_failures:
            self.process_close_failures -= 1
            raise RuntimeError("synthetic process exit unconfirmed")
        scope = getattr(harness, "slot_scope_for_cleanup", None)
        if scope is not None and not getattr(harness, "slot_cleanup_proven", False):
            self.product_slots.cleanup(
                scope, RunnerExit(0, None, "process_exit", "proven"),
            )
            harness.slot_cleanup_proven = True
        harness.closed = True
        self.closed_processes.append(harness)


@pytest.fixture
def slot_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    workspaces = ("workspace_slot_a", "workspace_slot_b")
    registry = _registry(workspaces)
    compatibility = SlotFakeCompatibility(registry)
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_MCP_ACP_DISCOVERY_TOKEN", "test-discovery-token")
    monkeypatch.setenv("BYQ_MCP_ACP_SIGNING_KEY", "test-signing-key-0123456789abcdef")
    (tmp_path / "composition.yml").write_text("[]\n", encoding="utf-8")
    runtime = RuntimeAdapter(compatibility)
    runtime.require_current_backend_authority = lambda: 7
    runtime._resolve_model = lambda **_kwargs: {
        "source": "synthetic-test", "provider": "deepseek-official",
        "model": "synthetic-model", "api_key": "synthetic-provider-key",
    }
    # Admission's Backend contract has its own direct PostgreSQL tests below;
    # this fixture isolates Adapter slot sequencing without external services.
    runtime._require_group_admission = lambda _record, _root: None
    runtime._group_admission_impl = RuntimeAdapter._require_group_admission.__get__(runtime)
    try:
        yield runtime, compatibility, registry
    finally:
        runtime.close()


def _create(runtime: RuntimeAdapter, session_id: str, workspace: str) -> None:
    runtime.create_session(
        session_id, f"trace-{session_id}", "slot-owner", workspace,
        conversation_context=[{"role": "user", "content": "seed"}],
    )


def _wait_status(runtime: RuntimeAdapter, session_id: str, status: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if runtime._get(session_id).status == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"{session_id} did not reach {status}")


def _run_to_idle(runtime: RuntimeAdapter, session_id: str, content: str) -> tuple[str, dict]:
    root = runtime.submit_prompt(session_id, content, conversation_context=[])
    _wait_status(runtime, session_id, SessionStatus.IDLE)
    record = runtime._get(session_id)
    return root, record.terminal_receipts[root]


def test_lazy_slot_start_busy_retry_and_exact_ack_release(slot_runtime):
    runtime, compatibility, registry = slot_runtime
    workspace = "workspace_slot_a"
    _create(runtime, "slot-first", workspace)
    _create(runtime, "slot-second", workspace)

    assert compatibility.start_attempts == []
    assert registry.get_available_binding(workspace).workspace_id == workspace

    first_root, first_receipt = _run_to_idle(runtime, "slot-first", "first root")
    first_harness = compatibility.successful_starts[0]
    assert first_harness.environment["BYQ_ROOT_RUN_ID"] == first_root
    assert registry._leases[workspace].backend_acknowledged is False

    second = runtime._get("slot-second")
    with pytest.raises(SessionConflict, match="slot is busy"):
        runtime.submit_prompt("slot-second", "retry after first ACK", conversation_context=[])
    assert second.status == SessionStatus.READY
    assert not second.process_used
    assert not second.cleanup_unconfirmed
    assert second.harness is compatibility.harnesses[1]

    with pytest.raises(SessionConflict, match="does not match"):
        runtime.acknowledge_terminal("slot-first", {**first_receipt, "sequence": first_receipt["sequence"] + 1})
    assert registry._leases[workspace].backend_acknowledged is False

    assert runtime.acknowledge_terminal("slot-first", first_receipt) == {"receipt": first_receipt}
    assert workspace not in registry._leases
    second_root, second_receipt = _run_to_idle(runtime, "slot-second", "retry succeeds")
    assert compatibility.successful_starts[-1] is second.harness
    assert second.harness.environment["BYQ_ROOT_RUN_ID"] == second_root
    runtime.acknowledge_terminal("slot-second", second_receipt)


def test_busy_replacement_preserves_acked_native_reuse_for_retry(slot_runtime):
    runtime, compatibility, registry = slot_runtime
    workspace = "workspace_slot_a"
    _create(runtime, "slot-reuse", workspace)
    _create(runtime, "slot-occupier", workspace)

    first_root, first_receipt = _run_to_idle(runtime, "slot-reuse", "first")
    first = runtime._get("slot-reuse")
    first_native = first.runtime_session_id
    runtime.acknowledge_terminal("slot-reuse", first_receipt)
    assert first.reuse_native_session_ready

    _occupier_root, occupier_receipt = _run_to_idle(runtime, "slot-occupier", "occupies slot")
    before_binding = runtime._read_acp_binding("slot-reuse")
    before_generation = first.runtime_generation

    with pytest.raises(SessionConflict, match="slot is busy"):
        runtime.submit_prompt("slot-reuse", "must remain retryable", conversation_context=[])
    assert first.reuse_native_session_ready
    assert not first.cleanup_unconfirmed
    assert first.process_root_id == first_root
    assert first.runtime_generation == before_generation
    assert runtime._read_acp_binding("slot-reuse") == before_binding

    runtime.acknowledge_terminal("slot-occupier", occupier_receipt)
    second_root, second_receipt = _run_to_idle(runtime, "slot-reuse", "retry after release")
    second = runtime._get("slot-reuse")
    assert second_root != first_root
    assert compatibility.resumed[-1][1] == first_native
    assert compatibility.resumed[-1][0] is second.harness
    assert second.harness.environment["BYQ_NATIVE_ROOT_SESSION_ID"] == first_native
    assert second.harness.prompts == ["retry after release"]
    runtime.acknowledge_terminal("slot-reuse", second_receipt)


def test_workspace_lease_requires_exact_ack_and_proven_cleanup_in_either_order():
    registry = _registry(("workspace_slot_a",))
    first = _scope("workspace_slot_a", "a")
    second = {**first, "root_run_id": "e" * 32, "generation_id": f"generation-{'f' * 32}"}
    proven = RunnerExit(0, None, "process_exit", "proven")

    registry.reserve(first)
    registry.cleanup(first, proven)
    with pytest.raises(ProductSlotBusy):
        registry.reserve(second)
    with pytest.raises(ProductSlotLeaseMismatch):
        registry.acknowledge(second)
    registry.acknowledge(first)
    registry.reserve(second)

    registry.acknowledge(second)
    with pytest.raises(ProductSlotBusy):
        registry.reserve(first)
    registry.cleanup(second, proven)
    registry.reserve(first)


def test_exact_ack_retry_keeps_transport_cleanup_scope_after_ack_scope_clears(slot_runtime):
    runtime, compatibility, registry = slot_runtime
    workspace = "workspace_slot_a"
    _create(runtime, "slot-ack-retry", workspace)
    root, receipt = _run_to_idle(runtime, "slot-ack-retry", "ack retry")
    harness = runtime._get("slot-ack-retry").harness
    assert harness.environment["BYQ_ROOT_RUN_ID"] == root
    compatibility.process_close_failures = 1

    with pytest.raises(SessionConflict, match="exit could not be confirmed"):
        runtime.acknowledge_terminal("slot-ack-retry", receipt)
    assert harness.slot_scope is None
    assert harness.slot_scope_for_cleanup["root_run_id"] == root
    assert registry._leases[workspace].backend_acknowledged
    assert not registry._leases[workspace].cleanup_proven

    assert runtime.acknowledge_terminal("slot-ack-retry", receipt) == {"receipt": receipt}
    assert workspace not in registry._leases


def test_missing_provider_credential_is_known_no_start_and_retryable(slot_runtime):
    runtime, compatibility, registry = slot_runtime
    _create(runtime, "slot-credential", "workspace_slot_a")
    record = runtime._get("slot-credential")
    record.model_resolution.pop("api_key")
    record.harness.environment.pop("DEEPSEEK_API_KEY")

    with pytest.raises(SessionConflict, match="unavailable; retry later"):
        runtime.submit_prompt("slot-credential", "synthetic credential gate", conversation_context=[])
    assert record.status == SessionStatus.READY
    assert not record.process_used
    assert not record.cleanup_unconfirmed
    assert record.cleanup_harness is None
    assert "workspace_slot_a" not in registry._leases

    # Supplying a test-only credential permits a retry. The fake ACP runtime
    # returns locally and never calls a paid model endpoint.
    record.model_resolution["api_key"] = "synthetic-provider-key"
    record.harness.environment["DEEPSEEK_API_KEY"] = "synthetic-provider-key"
    root, receipt = _run_to_idle(runtime, "slot-credential", "retry with synthetic credential")
    assert compatibility.successful_starts[-1].environment["BYQ_ROOT_RUN_ID"] == root
    runtime.acknowledge_terminal("slot-credential", receipt)


def test_admission_http_contract_fails_closed_and_checks_exact_root(slot_runtime, monkeypatch):
    import app.runtime as runtime_module

    runtime, _compatibility, _registry = slot_runtime
    record = type("Record", (), {
        "workspace_id": "workspace_slot_a", "owner_principal": "slot-owner",
        "session_id": "slot-admission-session",
    })()
    root = "1" * 32
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "synthetic-authority-token")
    calls: list[dict] = []

    class Response:
        def __init__(self, body: dict) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.body

    valid = {
        "schema_version": "byq-workspace-agent-admission.v1",
        "workspace_id": record.workspace_id,
        "boot_id": runtime.boot_id,
        "root_run_id": root,
        "can_start": True,
    }

    def get(url, *, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return Response(valid)

    monkeypatch.setattr(runtime_module.httpx, "get", get)
    runtime._group_admission_impl(record, root)
    assert calls[-1]["url"].endswith("/internal/runtime-authority/workspaces/workspace_slot_a/agent-admission")
    assert calls[-1]["params"] == {"root_run_id": root, "session_id": record.session_id}
    assert calls[-1]["headers"]["X-BYQ-Owner-Principal"] == record.owner_principal
    assert calls[-1]["headers"]["X-BYQ-Runtime-Boot-ID"] == runtime.boot_id
    assert calls[-1]["timeout"] == 2.0

    monkeypatch.setattr(runtime_module.httpx, "get", lambda *_args, **_kwargs: Response({**valid, "can_start": False}))
    with pytest.raises(SessionConflict, match="unsettled Agent turn"):
        runtime._group_admission_impl(record, root)

    monkeypatch.setattr(runtime_module.httpx, "get", lambda *_args, **_kwargs: Response({**valid, "root_run_id": "2" * 32}))
    with pytest.raises(RuntimeAuthorityUnavailable, match="unproven"):
        runtime._group_admission_impl(record, root)

    def unavailable(*_args, **_kwargs):
        raise runtime_module.httpx.ConnectError("synthetic disconnected Backend")

    monkeypatch.setattr(runtime_module.httpx, "get", unavailable)
    with pytest.raises(RuntimeAuthorityUnavailable, match="unavailable"):
        runtime._group_admission_impl(record, root)


def test_recovered_interrupted_root_keeps_slot_until_exact_terminal_ack(slot_runtime):
    runtime, old_compatibility, _old_registry = slot_runtime
    workspace = "workspace_slot_a"
    _create(runtime, "slot-recover", workspace)
    root, _old_receipt = _run_to_idle(runtime, "slot-recover", "interrupted before Backend close")
    old_record = runtime._get("slot-recover")
    old_harness = old_record.harness

    # Model a restart after the old ACP process has been independently proven
    # exited, while Backend has transferred this still-unsettled root.
    old_compatibility.close(old_harness)
    old_record.current_generation.process_exit_confirmed = True
    old_record.process_closed = True
    runtime._persist_acp_binding(old_record)
    binding = runtime._read_acp_binding("slot-recover")

    new_compatibility = SlotFakeCompatibility(_registry((workspace,)))
    restarted = RuntimeAdapter(new_compatibility)
    restarted.require_current_backend_authority = lambda: 8
    restarted._resolve_model = lambda **_kwargs: {
        "source": "synthetic-test", "provider": "deepseek-official",
        "model": "synthetic-model", "api_key": "synthetic-provider-key",
    }
    restarted._require_group_admission = lambda _record, _root: None
    transfer = {
        "schema_version": "byq-runtime-root-authority-transfer-receipt.v1",
        "root_run_id": binding["root_run_id"],
        "previous_boot_id": binding["previous_boot_id"],
        "previous_authority_epoch": binding["previous_authority_epoch"],
        "boot_id": restarted.boot_id,
        "authority_epoch": 8,
        "status": "transferred",
    }
    try:
        restarted.recover_acp_session("slot-recover", transfer, binding["sequence"])
        recovered = restarted._get("slot-recover")
        repair_harness = new_compatibility.harnesses[-1]
        assert recovered.harness is repair_harness
        assert repair_harness.closed
        assert repair_harness.slot_cleanup_proven
        assert workspace in new_compatibility.product_slots._leases
        terminal_receipt = recovered.terminal_receipts[root]

        assert restarted.acknowledge_terminal("slot-recover", terminal_receipt) == {
            "receipt": terminal_receipt,
        }
        assert workspace not in new_compatibility.product_slots._leases
    finally:
        restarted.close()
