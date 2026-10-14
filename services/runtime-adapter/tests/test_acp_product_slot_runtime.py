from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
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

    def build_harness(self, *, session_root: Path, environment: dict[str, str],
                      continuation_guard_b64: str | None = None, **kwargs):
        harness = super().build_harness(
            session_root=session_root, environment=environment,
            continuation_guard_b64=continuation_guard_b64, **kwargs,
        )
        if continuation_guard_b64 is not None:
            # Exercise the actual Adapter-owned patch writer in this synthetic
            # lifecycle test. No DSH process or provider request is launched.
            from app.compat.dsh_acp import _prepare_private_product_home, _write_continuation_guard
            # The shared fake ACP harness creates paths with mkdir's broad
            # default mode; the real Product slot requires an Adapter-owned
            # 0700 root. Keep the synthetic fixture at that production mode.
            session_root.chmod(0o700)
            _prepare_private_product_home(session_root)
            harness.prepared_guard_sha256 = _write_continuation_guard(
                session_root, continuation_guard_b64,
                root_run_id=environment["BYQ_ROOT_RUN_ID"],
            )
            # Model DSH plugin startup by writing only its schema-bound ready
            # record before RuntimeAdapter.prepare_prompt validates the guard.
            # This is synthetic evidence; it performs no tool or provider call.
            guard = json.loads(base64.b64decode(continuation_guard_b64))
            if len(guard) == 5:
                config = guard[4]["insert"][0]["config"]
                journal = session_root / (
                    f"continuation-tool-guard-{environment['BYQ_ROOT_RUN_ID']}.jsonl")
                journal.write_text(json.dumps({
                    "schema_version": "continuation-tool-guard.v1",
                    "reservation_id": config["reservationId"],
                    "execution_profile": config["executionProfile"],
                    "request_limits": config["requestLimits"],
                    "ready": True,
                }, sort_keys=True) + "\n", encoding="utf-8")
        return harness

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
    import httpx
    from urllib.parse import unquote, urlsplit

    from packages.contracts.agent_execution_options import default_agent_execution_options

    workspaces = ("workspace_slot_a", "workspace_slot_b")
    registry = _registry(workspaces)
    compatibility = SlotFakeCompatibility(registry)
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_MCP_ACP_DISCOVERY_TOKEN", "test-discovery-token")
    monkeypatch.setenv("BYQ_MCP_ACP_SIGNING_KEY", "test-signing-key-0123456789abcdef")  # gitleaks:allow — fixed synthetic test key
    monkeypatch.setenv("BYQ_F6_EXECUTOR_ENABLED", "1")
    monkeypatch.setenv("BYQ_BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "synthetic-runtime-authority-token")
    (tmp_path / "composition.yml").write_text("[]\n", encoding="utf-8")
    runtime = RuntimeAdapter(compatibility)
    runtime.require_current_backend_authority = lambda: 7
    runtime._test_execution_options_by_session = {}
    runtime._test_execution_revision_by_session = {}
    runtime._test_execution_projection_overrides = {}
    runtime._test_backend_reads = []

    conversation_scopes = {}

    def backend_get(url, *, headers, timeout):
        runtime._test_backend_reads.append((url, dict(headers), timeout))
        assert url.startswith("http://backend.test/")
        assert timeout == 2.0
        assert headers["Authorization"] == "Bearer synthetic-runtime-authority-token"
        session_id = headers["X-BYQ-Session-ID"]
        owner = headers["X-BYQ-Owner-Principal"]
        workspace_id = headers["X-BYQ-Workspace-ID"]
        assert headers["X-BYQ-Actor-Principal"] == f"byq-product-agent-{session_id}"
        assert headers["X-BYQ-Trace-ID"]
        assert headers["X-BYQ-DSH-Run-ID"]
        assert headers["X-BYQ-Runtime-Boot-ID"]
        assert headers["X-BYQ-Root-Run-ID"]
        path = urlsplit(url).path
        if path.startswith("/v1/product/conversations/by-runtime/"):
            path_session = unquote(path.rsplit("/", 1)[-1])
            assert path_session == session_id
            conversation_id = ("conversation-" + session_id)[:64]
            scope = {
                "conversation_id": conversation_id,
                "runtime_session_id": session_id,
                "owner_principal": owner,
                "workspace_id": workspace_id,
                "trace_id": headers["X-BYQ-Trace-ID"],
                "status": "active",
            }
            conversation_scopes[conversation_id] = (session_id, scope)
            return httpx.Response(
                200, json={"conversation": scope}, request=httpx.Request("GET", url))
        prefix = "/v1/product/conversations/"
        suffix = "/execution-options"
        assert path.startswith(prefix) and path.endswith(suffix)
        conversation_id = unquote(path[len(prefix):-len(suffix)])
        assert conversation_id in conversation_scopes
        path_session, scope = conversation_scopes[conversation_id]
        assert path_session == session_id
        options = runtime._test_execution_options_by_session.get(
            session_id, default_agent_execution_options())
        projection = {
            "schema_version": "agent-execution-options.v1",
            "conversation_id": conversation_id,
            "owner_principal": owner,
            "workspace_id": workspace_id,
            "revision": runtime._test_execution_revision_by_session.get(session_id, 4),
            "options": options,
            "updated_at": None,
        }
        projection.update(runtime._test_execution_projection_overrides.get(session_id, {}))
        return httpx.Response(
            200, json=projection, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", backend_get)
    runtime._resolve_model = lambda **_kwargs: {
        # ADR-0106: the ACP product candidate only qualifies the OpenCode Go /
        # deepseek-v4.1-flash route, so the synthetic slot fixture uses that exact
        # provider/model with a fake key (no network). Non-authorized models are
        # rejected on the ACP budget path.
        "source": "synthetic-test", "provider": "opencode-go-chat",
        "model": "deepseek-v4.1-flash", "api_key": "synthetic-provider-key",
    }
    # Admission's Backend contract has its own direct PostgreSQL tests below;
    # this fixture isolates Adapter slot sequencing without external services.
    runtime._require_group_admission = lambda _record, _root: None
    runtime._group_admission_impl = RuntimeAdapter._require_group_admission.__get__(runtime)
    try:
        yield runtime, compatibility, registry
    finally:
        runtime.close()


def test_operations_snapshot_uses_live_registry_and_omits_unconfigured_registry(
        slot_runtime):
    runtime, compatibility, registry = slot_runtime
    scope = _scope("workspace_slot_a", "a")
    assert compatibility.product_slots is registry
    registry.reserve(scope)
    snapshot = runtime.operations_snapshot()
    assert snapshot["product_slot_leases"] == {
        "configured": 2,
        "held": 1,
        "awaiting_backend_ack": 1,
        "awaiting_cleanup": 1,
        "scope": "adapter_process_lifetime",
        "source": "live_product_slot_registry",
    }
    assert "workspace_slot_a" not in json.dumps(snapshot)
    assert "BYQ_ACP_PRODUCT_SLOT_TEST" not in json.dumps(snapshot)
    assert registry.owns(scope)

    unconfigured = RuntimeAdapter(FakeAcpCompatibility())
    try:
        unconfigured_snapshot = unconfigured.operations_snapshot()
        assert "product_slot_leases" not in unconfigured_snapshot
    finally:
        unconfigured.close()


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
    record = runtime._get(session_id)
    recent = record.history[-4:]
    raise AssertionError(
        f"{session_id} did not reach {status}; got {record.status}; recent events={recent}"
    )


def _run_to_idle(runtime: RuntimeAdapter, session_id: str, content: str) -> tuple[str, dict]:
    root = runtime.submit_prompt(session_id, content, conversation_context=[])
    _wait_status(runtime, session_id, SessionStatus.IDLE)
    record = runtime._get(session_id)
    return root, record.terminal_receipts[root]


def _f6_reservation(owner: str, workspace: str, suffix: str) -> dict:
    from packages.contracts.continuation_request import profile_binding, request_limits

    return {
        "schema_version": "task-continuation-reservation.v2",
        "reservation_id": "continuation_" + suffix * 32,
        "task_id": "task_" + suffix * 32,
        "owner": owner,
        "workspace_id": workspace,
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }


def _guard_journal_path(home: Path) -> Path:
    patch = json.loads((home / "continuation-guard.patch.json").read_text(encoding="utf-8"))
    guard = patch[1] if len(patch) == 2 else patch[4]
    return Path(guard["insert"][0]["config"]["journalPath"])


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
    assert second.harness is not None

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


def test_normal_f6_normal_f6_reuses_native_only_after_exact_ack_with_fresh_root_guards(slot_runtime):
    runtime, compatibility, _registry_value = slot_runtime
    workspace = "workspace_slot_a"
    _create(runtime, "f6-reuse", workspace)

    first_root, first_receipt = _run_to_idle(runtime, "f6-reuse", "first user turn")
    record = runtime._get("f6-reuse")
    native_id = record.runtime_session_id
    home = Path(record.recovery_cwd)
    first_harness = compatibility.successful_starts[-1]
    first_patch = home / "continuation-guard.patch.json"
    first_patch_bytes = first_patch.read_bytes()
    first_journal = _guard_journal_path(home)
    assert first_journal.name == f"product-turn-tool-guard-{first_root}.jsonl"

    reservation_a = _f6_reservation("slot-owner", workspace, "a")
    start_attempts = len(compatibility.start_attempts)
    with pytest.raises(SessionConflict, match="not yet acknowledged"):
        runtime.submit_prompt(
            "f6-reuse", "must wait for terminal ACK", conversation_context=[],
            idempotency_key=reservation_a["reservation_id"],
            continuation_budget=reservation_a,
        )
    assert len(compatibility.start_attempts) == start_attempts
    assert first_patch.read_bytes() == first_patch_bytes
    assert not record.reuse_native_session_ready

    runtime.acknowledge_terminal("f6-reuse", first_receipt)
    assert record.reuse_native_session_ready
    second_root = runtime.submit_prompt(
        "f6-reuse", "background result A", conversation_context=[
            {"role": "user", "content": "first user turn"},
            {"role": "assistant", "content": "first answer"},
        ], idempotency_key=reservation_a["reservation_id"],
        continuation_budget=reservation_a,
    )
    _wait_status(runtime, "f6-reuse", SessionStatus.IDLE)
    second_receipt = record.terminal_receipts[second_root]
    second_harness = compatibility.successful_starts[-1]
    assert compatibility.resumed[-1] == (second_harness, native_id, home)
    assert second_harness.environment["BYQ_ROOT_RUN_ID"] == second_root
    assert second_harness.environment["BYQ_ROOT_RUN_ID"] != first_root
    assert second_harness.environment["BYQ_DSH_RUN_ID"] != first_harness.environment["BYQ_DSH_RUN_ID"]
    assert second_harness.environment["BYQ_NATIVE_ROOT_SESSION_ID"] == native_id
    assert second_harness.prompts == ["background result A"]
    assert (home / f"continuation-guard.closed-{first_root}.patch.json").read_bytes() == first_patch_bytes
    second_journal = _guard_journal_path(home)
    assert second_journal.name == f"continuation-tool-guard-{second_root}.jsonl"
    assert record.budget_journal == second_journal
    assert record.continuation_request_gate._journal.name == (
        f"continuation-provider-request-{second_root}.jsonl")
    assert runtime.continuation_receipt("f6-reuse", reservation_a["reservation_id"])["status"] == "outcome_unknown"
    runtime.acknowledge_terminal("f6-reuse", second_receipt)
    assert record.reuse_native_session_ready
    settled_a = runtime.continuation_receipt("f6-reuse", reservation_a["reservation_id"])
    assert settled_a["status"] == "settled" and settled_a["outcome"] == "completed"
    assert settled_a["run_id"] == second_root

    third_root = runtime.submit_prompt(
        "f6-reuse", "ordinary after F6", conversation_context=[
            {"role": "user", "content": "first user turn"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "background result A"},
        ],
    )
    _wait_status(runtime, "f6-reuse", SessionStatus.IDLE)
    third_receipt = record.terminal_receipts[third_root]
    third_harness = compatibility.successful_starts[-1]
    assert compatibility.resumed[-1] == (third_harness, native_id, home)
    assert third_harness.environment["BYQ_ROOT_RUN_ID"] == third_root
    assert third_harness.environment["BYQ_DSH_RUN_ID"] != second_harness.environment["BYQ_DSH_RUN_ID"]
    assert third_harness.environment["BYQ_NATIVE_ROOT_SESSION_ID"] == native_id
    assert third_harness.prompts == ["ordinary after F6"]
    third_journal = _guard_journal_path(home)
    assert third_journal.name == f"product-turn-tool-guard-{third_root}.jsonl"
    assert third_journal != first_journal and third_journal != second_journal
    assert (home / f"continuation-guard.closed-{second_root}.patch.json").is_file()
    runtime.acknowledge_terminal("f6-reuse", third_receipt)
    assert record.reuse_native_session_ready

    reservation_b = _f6_reservation("slot-owner", workspace, "b")
    fourth_root = runtime.submit_prompt(
        "f6-reuse", "background result B", conversation_context=[],
        idempotency_key=reservation_b["reservation_id"],
        continuation_budget=reservation_b,
    )
    _wait_status(runtime, "f6-reuse", SessionStatus.IDLE)
    fourth_receipt = record.terminal_receipts[fourth_root]
    fourth_harness = compatibility.successful_starts[-1]
    assert compatibility.resumed[-1] == (fourth_harness, native_id, home)
    assert fourth_harness.prompts == ["background result B"]
    fourth_journal = _guard_journal_path(home)
    assert fourth_journal.name == f"continuation-tool-guard-{fourth_root}.jsonl"
    assert fourth_journal not in {first_journal, second_journal, third_journal}
    assert (home / f"continuation-guard.closed-{third_root}.patch.json").is_file()
    runtime.acknowledge_terminal("f6-reuse", fourth_receipt)
    assert record.reuse_native_session_ready
    settled_b = runtime.continuation_receipt("f6-reuse", reservation_b["reservation_id"])
    assert settled_b["status"] == "settled" and settled_b["outcome"] == "completed"
    assert settled_b["run_id"] == fourth_root


def test_unknown_f6_provider_result_does_not_inherit_previous_native_reuse_readiness(slot_runtime):
    runtime, _compatibility, _registry_value = slot_runtime
    workspace = "workspace_slot_a"
    _create(runtime, "f6-unknown", workspace)
    first_root, first_receipt = _run_to_idle(runtime, "f6-unknown", "first user turn")
    record = runtime._get("f6-unknown")
    native_id = record.runtime_session_id
    runtime.acknowledge_terminal("f6-unknown", first_receipt)
    assert record.reuse_native_session_ready

    reservation = _f6_reservation("slot-owner", workspace, "c")
    unknown_root = runtime.submit_prompt(
        "f6-unknown", "background result with lost provider outcome", conversation_context=[],
        idempotency_key=reservation["reservation_id"], continuation_budget=reservation,
    )
    _wait_status(runtime, "f6-unknown", SessionStatus.IDLE)
    unknown_receipt = record.terminal_receipts[unknown_root]
    gate = record.continuation_request_gate
    assert gate is not None
    with gate._lock:
        gate._outcome_unknown = True
    assert gate.settlement_state() == "unknown_or_unpaired"

    # The user-visible root may complete, but a provider-side unknown is a
    # separate fail-closed fact and cannot inherit the preceding root's reuse.
    runtime.acknowledge_terminal("f6-unknown", unknown_receipt)
    assert not record.reuse_native_session_ready
    budget_receipt = runtime.continuation_receipt("f6-unknown", reservation["reservation_id"])
    assert budget_receipt["status"] == "outcome_unknown"
    assert budget_receipt.get("run_id") != first_root
    assert record.runtime_session_id == native_id


def test_f6_needs_attention_result_does_not_enable_native_reuse(slot_runtime):
    runtime, _compatibility, _registry_value = slot_runtime
    workspace = "workspace_slot_a"
    _create(runtime, "f6-needs-attention", workspace)
    _first_root, first_receipt = _run_to_idle(runtime, "f6-needs-attention", "first user turn")
    record = runtime._get("f6-needs-attention")
    runtime.acknowledge_terminal("f6-needs-attention", first_receipt)
    assert record.reuse_native_session_ready

    reservation = _f6_reservation("slot-owner", workspace, "d")
    root = runtime.submit_prompt(
        "f6-needs-attention", "background result with a blocked tool", conversation_context=[],
        idempotency_key=reservation["reservation_id"], continuation_budget=reservation,
    )
    _wait_status(runtime, "f6-needs-attention", SessionStatus.IDLE)
    receipt = record.terminal_receipts[root]
    assert record.budget_journal is not None
    with record.budget_journal.open("a", encoding="utf-8") as journal:
        journal.write(json.dumps({
            "phase": "blocked",
            "reservation_id": reservation["reservation_id"],
            "blocked_reason": "BYQ_CONTINUATION_TOOL_UNQUALIFIED",
            "tool_name": "mcp__byq__byq_research_get",
        }, sort_keys=True) + "\n")

    runtime.acknowledge_terminal("f6-needs-attention", receipt)
    settlement = runtime.continuation_receipt(
        "f6-needs-attention", reservation["reservation_id"])
    assert settlement["status"] == "settled"
    assert settlement["outcome"] == "needs_attention"
    assert not record.reuse_native_session_ready


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
    record.harness.environment.pop("OPENCODE_API_KEY", None)

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
        "source": "synthetic-test", "provider": "opencode-go-chat",
        "model": "deepseek-v4.1-flash", "api_key": "synthetic-provider-key",
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


class _StubSlots:
    def __init__(self, workspaces: tuple[str, ...]) -> None:
        self._workspaces = tuple(workspaces)

    def configured_workspaces(self) -> tuple[str, ...]:
        return self._workspaces


class _StubCompat:
    def __init__(self, workspaces: tuple[str, ...]) -> None:
        self.product_slots = _StubSlots(workspaces)

    def session_storage_root(self, base: Path, workspace_id: str) -> Path:
        assert workspace_id in self.product_slots.configured_workspaces()
        return (base / workspace_id).resolve()


def _binding_adapter(tmp_path: Path, workspaces: tuple[str, ...]) -> RuntimeAdapter:
    adapter = object.__new__(RuntimeAdapter)
    adapter._acp = True
    adapter._acp_product_slots = True
    adapter._session_root = tmp_path
    adapter._compatibility = _StubCompat(workspaces)
    return adapter


def _valid_binding(session_id: str, workspace_id: str, cwd: Path) -> dict:
    return {
        "schema_version": "byq-acp-root-binding.v1", "session_id": session_id,
        "trace_id": "trace-1", "owner_principal": "owner-1", "workspace_id": workspace_id,
        "root_run_id": "a" * 32, "native_session_id": "8b90c2b5-3a08-4eae-9fc7-04baf12910de",
        "runtime_generation": "generation-" + "b" * 32, "model_provider": "deepseek-official",
        "model_id": "deepseek-v4-flash", "cwd": str(cwd.resolve()),
        "previous_boot_id": "c" * 32, "previous_authority_epoch": 1, "sequence": 1,
        "settlement_receipt": None, "domain_call_sequence": 0,
        "domain_call_drained_sequence": 0, "native_session_close_confirmed": True,
        "process_exit_confirmed": True, "cleanup_unconfirmed": False, "closed": False,
    }


def test_binding_path_is_group_scoped_and_ambiguity_fails_closed(tmp_path: Path) -> None:
    adapter = _binding_adapter(tmp_path, ("workspace_a", "workspace_b"))
    explicit = adapter._acp_binding_path("byq-session-x", "workspace_a")
    assert explicit == (tmp_path / "workspace_a" / "byq-acp-bindings" / "byq-session-x.json")
    with pytest.raises(SessionConflict):
        adapter._acp_binding_path("byq-session-x")


def test_read_binding_rejects_file_found_in_another_group(tmp_path: Path) -> None:
    adapter = _binding_adapter(tmp_path, ("workspace_a", "workspace_b"))
    session_id = "byq-session-x"
    cwd_a = tmp_path / "workspace_a" / ("session-" + "d" * 32)
    value = _valid_binding(session_id, "workspace_a", cwd_a)
    # A binding physically written into group B while declaring group A.
    wrong = adapter._acp_binding_path(session_id, "workspace_b")
    wrong.parent.mkdir(parents=True, exist_ok=True)
    wrong.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(SessionConflict):
        adapter._read_acp_binding(session_id)


def test_ordinary_path_unsupported_model_is_rejected_before_any_proxy(slot_runtime, monkeypatch):
    # ADR-0106: a non-authorized resolved model is rejected on the ACP budget path
    # BEFORE any proxy/process start (no unbudgeted egress, no silent switch).
    runtime, compatibility, registry = slot_runtime
    from app import runtime as runtime_module
    opened = []
    original = runtime_module.RequestGateProxy

    class Spy(original):
        def __init__(self, *args, **kwargs):
            opened.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "RequestGateProxy", Spy)
    runtime._resolve_model = lambda **_kwargs: {
        "source": "synthetic-test", "provider": "opencode-zen-chat",
        "model": "deepseek-v4-flash", "api_key": "synthetic-provider-key",
    }
    _create(runtime, "ord-unsupported", "workspace_slot_a")
    with pytest.raises(Exception, match="NOT_QUALIFIED"):
        runtime.submit_prompt("ord-unsupported", "hello", conversation_context=[])
    assert opened == []


def test_ordinary_path_authorized_model_first_submit_opens_product_turn_gate(slot_runtime, monkeypatch):
    # ADR-0111: the first ordinary submit reads the exact trusted Backend
    # options projection, then builds the v2 gate/proxy before process start.
    runtime, compatibility, registry = slot_runtime
    from app import runtime as runtime_module
    captured = {}
    original = runtime_module.RequestGateProxy

    class Spy(original):
        def __init__(self, gate, *args, **kwargs):
            captured["gate"] = gate
            captured["proxy"] = self
            super().__init__(gate, *args, **kwargs)

    monkeypatch.setattr(runtime_module, "RequestGateProxy", Spy)
    runtime._resolve_model = lambda **_kwargs: {
        "source": "synthetic-test", "provider": "opencode-go-chat",
        "model": "deepseek-v4.1-flash", "api_key": "synthetic-provider-key",
    }
    _create(runtime, "ord-authorized", "workspace_slot_a")
    _run_to_idle(runtime, "ord-authorized", "hello")
    gate = captured["gate"]
    assert gate.product_turn_v2 is True
    assert gate.execution_profile["profile_id"] == "product-turn.v2"
    assert gate.execution_profile["options_revision"] == 4
    assert gate.limits["max_provider_calls"] is None
    assert gate.limits["max_runtime_seconds"] is None
    assert gate.execution_profile["provider"] == "opencode-go-chat"
    assert gate.execution_profile["model"] == "deepseek-v4.1-flash"
    reads = runtime._test_backend_reads
    assert [url.rsplit("/", 1)[-1] for url, _headers, _timeout in reads] == [
        "ord-authorized", "execution-options",
    ]
    assert len({headers["X-BYQ-Root-Run-ID"] for _url, headers, _timeout in reads}) == 1
    assert all(headers["X-BYQ-Owner-Principal"] == "slot-owner"
               and headers["X-BYQ-Workspace-ID"] == "workspace_slot_a"
               for _url, headers, _timeout in reads)


def test_ordinary_options_scope_mismatch_fails_before_proxy_or_runner_start(slot_runtime, monkeypatch):
    runtime, compatibility, _registry_value = slot_runtime
    runtime._test_execution_projection_overrides["ord-options-scope"] = {
        "workspace_id": "workspace_slot_b",
    }
    from app import runtime as runtime_module
    opened = []
    original = runtime_module.RequestGateProxy

    class Spy(original):
        def __init__(self, *args, **kwargs):
            opened.append(True)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "RequestGateProxy", Spy)
    _create(runtime, "ord-options-scope", "workspace_slot_a")
    with pytest.raises(RuntimeAuthorityUnavailable, match="options are unavailable or unproven"):
        runtime.submit_prompt("ord-options-scope", "hello", conversation_context=[])
    assert opened == []
    assert compatibility.start_attempts == []
    assert len(runtime._test_backend_reads) == 2


def _tools_with_payload_bytes(target: int):
    from app.research_request_gate import _tool_payload_bytes
    base = [{"type": "function", "function": {"name": "mcp__byq__byq_research_get", "description": ""}}]
    pad = target - _tool_payload_bytes({"tools": base})
    return [{"type": "function", "function": {"name": "mcp__byq__byq_research_get", "description": "d" * pad}}]


def test_second_turn_guard_rotation_waits_for_previous_cleanup(slot_runtime):
    # The route-only guard is rotated only after the previous generation is
    # cleaned and the old root is acknowledged; a submit before that is refused
    # and does NOT rebuild the harness (no guard rewrite for an active old root).
    runtime, compatibility, registry = slot_runtime
    _create(runtime, "ord-order", "workspace_slot_a")
    _root, _receipt = _run_to_idle(runtime, "ord-order", "first")
    record = runtime._get("ord-order")
    before_harness = record.harness
    before_binding = runtime._read_acp_binding("ord-order")
    with pytest.raises(SessionConflict, match="acknowledged|cleanup|not complete"):
        runtime.submit_prompt("ord-order", "second", conversation_context=[])
    assert record.harness is before_harness
    assert runtime._read_acp_binding("ord-order") == before_binding


def test_write_continuation_guard_accepts_product_turn_overlay(tmp_path):
    import base64
    import uuid

    from app.compat.dsh_acp import (
        AcpTransportError, _prepare_private_product_home, _write_continuation_guard,
    )
    from app.continuation_budget import create_acp_product_budget_overlay
    # The runtime generates the provider session id as a UUIDv5 (see runtime.py).
    provider_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "beyondquant:provider-session:test"))
    overlay = create_acp_product_budget_overlay(
        proxy_base_url="http://172.31.7.9:41337",
        provider_session_id=provider_session_id,
        provider="opencode-go-chat", model="deepseek-v4.1-flash")
    home = tmp_path / "ok"
    home.mkdir(mode=0o700)
    _prepare_private_product_home(home)
    root_run_id = "a" * 32
    _write_continuation_guard(
        home, base64.b64encode(overlay).decode(), root_run_id=root_run_id,
    )
    patch = json.loads((home / "continuation-guard.patch.json").read_text())
    assert patch[1]["insert"][0]["config"]["journalPath"] == str(
        home / f"product-turn-tool-guard-{root_run_id}.jsonl")
    before = (home / "continuation-guard.patch.json").read_bytes()
    with pytest.raises(AcpTransportError, match="could not be written"):
        _write_continuation_guard(
            home, base64.b64encode(overlay).decode(), root_run_id="b" * 32,
        )
    assert (home / "continuation-guard.patch.json").read_bytes() == before
    # Non-dict members, non-str baseURL and wrong shapes are rejected with the
    # contract exception (never a non-contract AttributeError/TypeError).
    bad_route = {"id": "llm-pi-ai", "config": {"providers": {"opencode-go-chat": {
        "api": "openai-completions", "apiKeyEnv": "OPENCODE_API_KEY",
        "baseURL": 123, "retryPolicy": {"mode": "normal", "maxRetries": 0},
        "headers": {"x-opencode-session": provider_session_id},
        "models": [{"id": "deepseek-v4.1-flash"}]}}}}
    for i, bad in enumerate((["not-a-dict"], [{"id": "llm-pi-ai", "config": "x"}],
                             [bad_route],
                             [{"id": "llm-pi-ai", "config": {"providers": {"opencode-zen-chat": {}}}}])):
        home = tmp_path / f"bad{i}"
        home.mkdir(mode=0o700)
        _prepare_private_product_home(home)
        with pytest.raises(AcpTransportError):
            _write_continuation_guard(
                home, base64.b64encode(json.dumps(bad).encode()).decode(),
                root_run_id="c" * 32,
            )


def test_fixed_guard_patch_rotation_is_private_root_scoped_and_no_replace(tmp_path):
    import base64
    import os
    import stat
    import uuid

    from app.compat.dsh_acp import (
        AcpTransportError, _prepare_private_product_home,
        _write_continuation_guard, archive_previous_continuation_guard_patch,
    )
    from app.continuation_budget import create_acp_product_budget_overlay

    home = tmp_path / "private-root"
    home.mkdir(mode=0o700)
    _prepare_private_product_home(home)

    def overlay(port: int) -> str:
        provider_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"test:{port}"))
        value = create_acp_product_budget_overlay(
            proxy_base_url=f"http://172.31.7.9:{port}",
            provider_session_id=provider_session_id,
            provider="opencode-go-chat", model="deepseek-v4.1-flash",
        )
        return base64.b64encode(value).decode()

    first_root = "d" * 32
    _write_continuation_guard(home, overlay(41337), root_run_id=first_root)
    first_path = home / "continuation-guard.patch.json"
    first_bytes = first_path.read_bytes()
    patch_info = os.lstat(first_path)
    assert stat.S_ISREG(patch_info.st_mode)
    assert patch_info.st_uid == os.getuid() and patch_info.st_gid == os.getgid()
    assert stat.S_IMODE(patch_info.st_mode) == 0o600 and patch_info.st_nlink == 1
    with pytest.raises(AcpTransportError, match="root mismatch"):
        archive_previous_continuation_guard_patch(home, previous_root_id="f" * 32)
    assert first_path.read_bytes() == first_bytes
    archive_previous_continuation_guard_patch(home, previous_root_id=first_root)
    archive_path = home / f"continuation-guard.closed-{first_root}.patch.json"
    assert not first_path.exists()
    assert archive_path.read_bytes() == first_bytes
    archive_info = os.lstat(archive_path)
    assert stat.S_ISREG(archive_info.st_mode)
    assert archive_info.st_uid == os.getuid() and archive_info.st_gid == os.getgid()
    assert stat.S_IMODE(archive_info.st_mode) == 0o600 and archive_info.st_nlink == 1
    archive_previous_continuation_guard_patch(home, previous_root_id=first_root)

    # Recover only the exact same-inode two-link state left by a crash between
    # link() and unlink(); the source root ID must match the retry scope.
    crash_root = "1" * 32
    _write_continuation_guard(home, overlay(41339), root_run_id=crash_root)
    crash_source = home / "continuation-guard.patch.json"
    crash_archive = home / f"continuation-guard.closed-{crash_root}.patch.json"
    os.link(crash_source, crash_archive, follow_symlinks=False)
    assert os.lstat(crash_source).st_nlink == 2
    archive_previous_continuation_guard_patch(home, previous_root_id=crash_root)
    assert not crash_source.exists()
    assert os.lstat(crash_archive).st_nlink == 1

    second_root = "e" * 32
    _write_continuation_guard(home, overlay(41338), root_run_id=second_root)
    current = json.loads(first_path.read_text())
    assert current[1]["insert"][0]["config"]["journalPath"] == str(
        home / f"product-turn-tool-guard-{second_root}.jsonl")

    hostile = tmp_path / "hostile-home"
    hostile.mkdir(mode=0o700)
    _prepare_private_product_home(hostile)
    external = tmp_path / "external-target"
    external.write_text("outside DSH root", encoding="utf-8")
    (hostile / "continuation-guard.patch.json").symlink_to(external)
    with pytest.raises(AcpTransportError, match="archive is unsafe"):
        archive_previous_continuation_guard_patch(hostile, previous_root_id="f" * 32)
    assert external.read_text(encoding="utf-8") == "outside DSH root"


def test_ordinary_submit_loopback_gate_cap_posts0_and_root_journal(slot_runtime, monkeypatch):
    # SYNTHETIC ENGINEERING proof (NOT Product E2E): the actual
    # RuntimeAdapter.submit_prompt reads an explicit per-call payload option and
    # builds the real v2 gate/proxy/overlay; a controlled HTTP request to the real
    # advertised proxy is sent while it is open and counted by a loopback upstream.
    import http.server
    import threading

    import httpx

    runtime, compatibility, registry = slot_runtime
    from packages.contracts.agent_execution_options import default_agent_execution_options
    options = default_agent_execution_options()
    options["max_tool_payload_bytes_per_call"] = 131072
    runtime._test_execution_options_by_session["ord-loopback"] = options
    from app import runtime as runtime_module
    captured = {}
    original_proxy = runtime_module.RequestGateProxy

    class Spy(original_proxy):
        def __init__(self, gate, *args, **kwargs):
            captured["proxy"] = self
            super().__init__(gate, *args, **kwargs)

    monkeypatch.setattr(runtime_module, "RequestGateProxy", Spy)

    upstream_posts = []

    class Provider(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            upstream_posts.append(1)
            body = b"{}"
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()

    original_start = compatibility.start

    def start_and_probe(harness):
        original_start(harness)
        proxy = captured["proxy"]
        proxy._server.upstream = f"http://127.0.0.1:{upstream.server_port}"
        _host, port = proxy._server.server_address[:2]
        over = {"model": "deepseek-v4.1-flash", "max_tokens": 8,
                "messages": [{"role": "user", "content": "synthetic"}],
                "tools": _tools_with_payload_bytes(131073)}
        response = httpx.post(f"http://127.0.0.1:{port}/chat/completions",
                              content=json.dumps(over).encode(), timeout=3)
        captured["status"] = response.status_code

    monkeypatch.setattr(compatibility, "start", start_and_probe)
    runtime._resolve_model = lambda **_kwargs: {
        "source": "synthetic-test", "provider": "opencode-go-chat",
        "model": "deepseek-v4.1-flash", "api_key": "synthetic-provider-key",
    }
    try:
        _create(runtime, "ord-loopback", "workspace_slot_a")
        root = runtime.submit_prompt("ord-loopback", "hello", conversation_context=[])
        # A request refused by a known ADR-0106 budget limit is a fully known
        # budget exhaustion: the failed root is still truthfully failed, but the
        # live conversation stays promptable for an explicit new instruction.
        _wait_status(runtime, "ord-loopback", SessionStatus.IDLE)
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)
    assert captured["status"] == 429          # over-cap refused
    assert upstream_posts == []               # posts=0 before any upstream post
    # Root journal association: the product-turn request journal was written for
    # this exact root.
    record = runtime._get("ord-loopback")
    assert record.status == SessionStatus.IDLE
    journal = Path(record.recovery_cwd) / (
        f"product-turn-provider-request-{record.process_root_id}.jsonl")
    assert journal.is_file()
    rows = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    assert any(row.get("phase") == "rejected"
               and row.get("reason") == "product_tool_payload_limit"
               for row in rows)
    gate = record.continuation_request_gate
    assert gate is not None
    assert gate.settlement_state() == "known_blocked"
    assert gate.known_budget_block_reason() == "product_tool_payload_limit"
    terminal = [event for event in record.history
                if event["kind"] in {"session.result", "session.failed"}]
    assert [event["kind"] for event in terminal] == ["session.failed"]
    assert terminal[0]["payload"]["run_id"] == root
    assert terminal[0]["payload"]["code"] == "budget-exhausted"
    assert terminal[0]["payload"]["retryable"] is False
    # Exact ACK + proven cleanup still close the failed root.
    receipt = record.terminal_receipts[root]
    assert runtime.acknowledge_terminal("ord-loopback", receipt) == {"receipt": receipt}
    assert not record.reuse_native_session_ready


def test_ordinary_acp_product_slot_fails_closed_when_provider_gate_is_missing(slot_runtime):
    """The ACP Product slot cannot publish a completed root without its gate."""

    runtime, compatibility, _registry_value = slot_runtime
    compatibility.block_prompt = True
    _create(runtime, "ord-missing-gate", "workspace_slot_a")
    root = runtime.submit_prompt("ord-missing-gate", "hello", conversation_context=[])
    assert compatibility.prompt_started.wait(timeout=1.0)
    record = runtime._get("ord-missing-gate")
    with record.lock:
        run = record.active_run
        assert run is not None
        generation = record.current_generation
        assert generation is not None
        assert generation.continuation_request_gate is not None
        assert generation.continuation_request_proxy is not None
        # Model a missing runtime gate while keeping the real proxy available to
        # the terminal cleanup path; the closed proxy flag must not replace the
        # required gate receipt.
        generation.continuation_request_gate = None

    try:
        compatibility.allow_prompt_return.set()
        assert run.watchdog_stop.wait(timeout=3.0), "prompt worker did not finish"
        with record.lock:
            assert record.active_run is None
            assert record.status == SessionStatus.FAILED
            assert generation.continuation_proxy_closed is True
            assert generation.state == "failed"
            terminal = [event for event in record.history
                        if event["kind"] in {"session.result", "session.failed"}]
            assert [event["kind"] for event in terminal] == ["session.failed"]
            assert terminal[0]["payload"]["run_id"] == root
            assert terminal[0]["payload"]["code"] == "model-run-failed"
            assert terminal[0]["payload"]["retryable"] is False
    finally:
        compatibility.allow_prompt_return.set()
        assert run.watchdog_stop.wait(timeout=3.0), "prompt worker leaked after gate removal"
        with record.lock:
            assert record.active_run is None


def test_ordinary_submit_loopback_gate_unknown_blocks_next_http(slot_runtime, monkeypatch):
    # SYNTHETIC ENGINEERING proof (NOT Product E2E): a provider transport that
    # ends without a complete response marks the request unknown and blocks any
    # further external post for that root.
    import http.server
    import threading

    import httpx

    runtime, compatibility, registry = slot_runtime
    from app import runtime as runtime_module
    captured = {}
    original_proxy = runtime_module.RequestGateProxy

    class Spy(original_proxy):
        def __init__(self, gate, *args, **kwargs):
            captured["proxy"] = self
            super().__init__(gate, *args, **kwargs)

    monkeypatch.setattr(runtime_module, "RequestGateProxy", Spy)

    disconnect_posts = []

    class Disconnecting(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            disconnect_posts.append(1)
            self.close_connection = True

    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Disconnecting)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()

    original_start = compatibility.start
    statuses = []

    def start_and_probe(harness):
        original_start(harness)
        proxy = captured["proxy"]
        proxy._server.upstream = f"http://127.0.0.1:{upstream.server_port}"
        _host, port = proxy._server.server_address[:2]
        body = json.dumps({"model": "deepseek-v4.1-flash", "max_tokens": 8,
                           "messages": [{"role": "user", "content": "synthetic"}]}).encode()
        try:
            statuses.append(httpx.post(f"http://127.0.0.1:{port}/chat/completions",
                                       content=body, timeout=3).status_code)
        except httpx.HTTPError:
            statuses.append("error")
        statuses.append(httpx.post(f"http://127.0.0.1:{port}/chat/completions",
                                   content=body, timeout=3).status_code)

    monkeypatch.setattr(compatibility, "start", start_and_probe)
    runtime._resolve_model = lambda **_kwargs: {
        "source": "synthetic-test", "provider": "opencode-go-chat",
        "model": "deepseek-v4.1-flash", "api_key": "synthetic-provider-key",
    }
    try:
        _create(runtime, "ord-unknown", "workspace_slot_a")
        root = runtime.submit_prompt("ord-unknown", "hello", conversation_context=[])
        # ADR-0106 §4: an unknown provider outcome fails the root closed instead
        # of reporting a successful turn before the outcome is accounted.
        _wait_status(runtime, "ord-unknown", SessionStatus.FAILED)
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)
    # First request reached the upstream once (unknown); the next was blocked with
    # no further upstream post.
    assert disconnect_posts == [1]
    assert statuses[-1] == 429
    record = runtime._get("ord-unknown")
    terminal = [event for event in record.history
                if event["kind"] in {"session.result", "session.failed"}]
    assert [event["kind"] for event in terminal] == ["session.failed"]
    assert terminal[0]["payload"]["run_id"] == root
    # An unprovable provider outcome never qualifies as a known budget block:
    # the root stays failed and fenced (no conversation reopening).
    assert record.status == SessionStatus.FAILED
    assert terminal[0]["payload"]["code"] == "model-run-failed"
    assert terminal[0]["payload"]["retryable"] is False


def _inject_gate_rejection(gate, reason: str) -> None:
    """Synthetic known/unknown block on the real request-scoped gate.

    No provider request is dispatched; this records one pre-dispatch refusal so
    the terminal decision classifies the real sealed gate.
    """

    with gate._lock:
        gate._receipts.append({
            "schema_version": "continuation-request-gate.v1",
            "request_id": gate.request_id,
            "phase": "rejected", "admitted": False, "reason": reason,
            "input_bytes": 1, "at_ms": 1,
        })


def test_known_budget_block_keeps_conversation_promptable_and_never_reuses_failed_native(slot_runtime):
    runtime, compatibility, _registry_value = slot_runtime
    workspace = "workspace_slot_a"
    compatibility.block_prompt = True
    _create(runtime, "ord-budget", workspace)
    first_root = runtime.submit_prompt(
        "ord-budget", "first explicit instruction", conversation_context=[])
    assert compatibility.prompt_started.wait(timeout=1.0)
    record = runtime._get("ord-budget")
    with record.lock:
        gate = record.current_generation.continuation_request_gate
    assert gate is not None
    first_harness = compatibility.harnesses[-1]
    first_native = record.runtime_session_id
    _inject_gate_rejection(gate, "product_total_tool_payload_limit")
    compatibility.allow_prompt_return.set()
    _wait_status(runtime, "ord-budget", SessionStatus.IDLE)

    # Root outcome is truthfully failed; the conversation stays promptable.
    assert record.status == SessionStatus.IDLE
    assert gate.settlement_state() == "known_blocked"
    assert gate.known_budget_block_reason() == "product_total_tool_payload_limit"
    terminal = [event for event in record.history
                if event["kind"] in {"session.result", "session.failed"}]
    assert [event["kind"] for event in terminal] == ["session.failed"]
    assert terminal[0]["payload"]["code"] == "budget-exhausted"
    # The failed turn itself is never retryable/replayed; only an explicit new
    # user instruction is accepted.
    assert terminal[0]["payload"]["retryable"] is False

    # Until the exact terminal ACK + proven cleanup, a new root is fenced.
    with pytest.raises(SessionConflict, match="not yet acknowledged"):
        runtime.submit_prompt("ord-budget", "second explicit instruction", conversation_context=[])
    assert record.process_root_id == first_root

    runtime.acknowledge_terminal("ord-budget", record.terminal_receipts[first_root])
    assert not record.reuse_native_session_ready

    # An explicit new instruction is admitted as a fresh root with a fresh native
    # session, new generation and its own gate; the failed turn is never replayed.
    compatibility.block_prompt = False
    compatibility.prompt_started.clear()
    second_root = runtime.submit_prompt(
        "ord-budget", "second explicit instruction", conversation_context=[])
    _wait_status(runtime, "ord-budget", SessionStatus.IDLE)
    second_harness = compatibility.successful_starts[-1]
    assert second_root != first_root
    assert compatibility.resumed == []
    assert second_harness is not first_harness
    assert second_harness.environment["BYQ_ROOT_RUN_ID"] == second_root
    assert second_harness.environment["BYQ_DSH_RUN_ID"] != first_harness.environment["BYQ_DSH_RUN_ID"]
    assert second_harness.prompts == ["second explicit instruction"]
    assert record.process_root_id == second_root
    assert record.runtime_session_id != first_native
    assert record.continuation_request_gate is not gate
    runtime.acknowledge_terminal("ord-budget", record.terminal_receipts[second_root])


@pytest.mark.parametrize("reason", ["storage_failed", "cancelled", "model_route_unqualified",
                                    "provider_outcome_unknown"])
def test_non_budget_refusal_stays_failed_and_fenced(slot_runtime, reason):
    runtime, compatibility, _registry_value = slot_runtime
    workspace = "workspace_slot_a"
    compatibility.block_prompt = True
    _create(runtime, "ord-refused", workspace)
    root = runtime.submit_prompt("ord-refused", "first", conversation_context=[])
    assert compatibility.prompt_started.wait(timeout=1.0)
    record = runtime._get("ord-refused")
    with record.lock:
        gate = record.current_generation.continuation_request_gate
    assert gate is not None
    _inject_gate_rejection(gate, reason)
    if reason == "storage_failed":
        with gate._lock:
            gate._journal_failed = True
    if reason == "provider_outcome_unknown":
        with gate._lock:
            gate._outcome_unknown = True
    compatibility.allow_prompt_return.set()
    _wait_status(runtime, "ord-refused", SessionStatus.FAILED)
    assert record.status == SessionStatus.FAILED
    assert gate.known_budget_block_reason() is None
    terminal = [event for event in record.history
                if event["kind"] in {"session.result", "session.failed"}]
    assert [event["kind"] for event in terminal] == ["session.failed"]
    assert terminal[0]["payload"]["code"] == "model-run-failed"
    assert terminal[0]["payload"]["retryable"] is False
    assert record.process_root_id == root


def test_known_budget_block_requires_a_closed_proxy(slot_runtime, monkeypatch):
    # If the provider proxy close is unconfirmed, the known budget block must NOT
    # reopen the conversation: the root stays failed and fenced.
    runtime, compatibility, _registry_value = slot_runtime
    from app import runtime as runtime_module

    captured = {}
    original_proxy_cls = runtime_module.RequestGateProxy

    class Spy(original_proxy_cls):
        def __init__(self, *args, **kwargs):
            captured["proxy"] = self
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "RequestGateProxy", Spy)
    compatibility.block_prompt = True
    _create(runtime, "ord-budget-noclose", "workspace_slot_a")
    root = runtime.submit_prompt("ord-budget-noclose", "first", conversation_context=[])
    assert compatibility.prompt_started.wait(timeout=1.0)
    record = runtime._get("ord-budget-noclose")
    with record.lock:
        gate = record.current_generation.continuation_request_gate
    assert gate is not None
    _inject_gate_rejection(gate, "product_total_tool_payload_limit")
    proxy = captured["proxy"]
    original_close = proxy.close

    def failing_close():
        # Fail exactly once so the runtime records an unconfirmed close; later
        # cleanup (ACK path / fixture teardown) uses the real close.
        proxy.close = original_close
        raise RuntimeError("synthetic proxy close failure")

    proxy.close = failing_close
    compatibility.allow_prompt_return.set()
    _wait_status(runtime, "ord-budget-noclose", SessionStatus.FAILED)
    assert record.status == SessionStatus.FAILED
    assert record.current_generation.continuation_proxy_closed is False
    terminal = [event for event in record.history
                if event["kind"] in {"session.result", "session.failed"}]
    assert [event["kind"] for event in terminal] == ["session.failed"]
    assert terminal[0]["payload"]["code"] == "model-run-failed"
    assert terminal[0]["payload"]["retryable"] is False
    # Admission stays fenced until the exact terminal ACK.
    with pytest.raises(SessionConflict, match="not yet acknowledged"):
        runtime.submit_prompt("ord-budget-noclose", "second", conversation_context=[])
    assert record.process_root_id == root


def test_postdispatch_product_runtime_limit_starts_only_a_fresh_root_after_ack(slot_runtime):
    # A dispatched request stopped by the user's v2 runtime cap is not a
    # pre-dispatch budget block, but a paired result may admit a fresh root after
    # exact ACK/cleanup. The old root is never resumed or replayed.
    runtime, compatibility, _registry_value = slot_runtime
    from packages.contracts.agent_execution_options import default_agent_execution_options
    options = default_agent_execution_options()
    options["max_runtime_seconds"] = 60
    runtime._test_execution_options_by_session["ord-post-runtime"] = options
    runtime._test_execution_revision_by_session["ord-post-runtime"] = 11
    compatibility.block_prompt = True
    _create(runtime, "ord-post-runtime", "workspace_slot_a")
    root = runtime.submit_prompt("ord-post-runtime", "first", conversation_context=[])
    assert compatibility.prompt_started.wait(timeout=1.0)
    record = runtime._get("ord-post-runtime")
    with record.lock:
        gate = record.current_generation.continuation_request_gate
    assert gate is not None
    assert gate.execution_profile["options_revision"] == 11
    with gate._lock:
        gate._receipts.extend([
            {"schema_version": "continuation-request-gate.v1",
             "request_id": gate.request_id,
             "phase": "admitted", "admitted": True, "call": 1, "attempt": 1},
            {"schema_version": "continuation-request-gate.v1",
             "request_id": gate.request_id,
             "phase": "completed", "admitted": True, "call": 1, "attempt": 1,
             "forwarded": False, "reason": "product_runtime_limit", "status": 200},
        ])
        gate._provider_calls = 1
        gate._attempts = 1
    compatibility.allow_prompt_return.set()
    _wait_status(runtime, "ord-post-runtime", SessionStatus.IDLE)
    assert record.status == SessionStatus.IDLE
    assert gate.known_budget_block_reason() is None
    assert gate.known_postdispatch_product_runtime_limit() is True
    terminal = [event for event in record.history
                if event["kind"] in {"session.result", "session.failed"}]
    assert [event["kind"] for event in terminal] == ["session.failed"]
    assert terminal[0]["payload"]["code"] == "model-run-failed"
    assert terminal[0]["payload"]["retryable"] is False
    assert record.process_root_id == root

    # The explicit next instruction starts a distinct root with a new trusted
    # revision. It cannot inherit the stopped native transcript or request gate.
    runtime.acknowledge_terminal("ord-post-runtime", record.terminal_receipts[root])
    runtime._test_execution_options_by_session["ord-post-runtime"] = default_agent_execution_options()
    runtime._test_execution_revision_by_session["ord-post-runtime"] = 12
    compatibility.block_prompt = False
    compatibility.prompt_started.clear()
    second_root = runtime.submit_prompt(
        "ord-post-runtime", "second explicit instruction", conversation_context=[])
    _wait_status(runtime, "ord-post-runtime", SessionStatus.IDLE)
    second_gate = record.continuation_request_gate
    assert second_root != root
    assert second_gate is not None and second_gate is not gate
    assert second_gate.execution_profile["options_revision"] == 12
    assert compatibility.resumed == []
    assert compatibility.successful_starts[-1].prompts == ["second explicit instruction"]
    runtime.acknowledge_terminal("ord-post-runtime", record.terminal_receipts[second_root])


def test_postdispatch_runtime_limit_exception_starts_only_a_fresh_root_after_ack(
    slot_runtime, monkeypatch,
):
    from packages.contracts.agent_execution_options import default_agent_execution_options

    runtime, compatibility, _registry_value = slot_runtime
    original_run = compatibility.run_prepared_prompt
    options = default_agent_execution_options()
    options["max_runtime_seconds"] = 60
    runtime._test_execution_options_by_session["ord-exc-runtime"] = options
    runtime._test_execution_revision_by_session["ord-exc-runtime"] = 21

    def arm_runtime_stop(gate):
        with gate._lock:
            gate._receipts = [
                {"schema_version": "continuation-request-gate.v1",
                 "request_id": gate.request_id, "phase": "admitted",
                 "admitted": True, "call": 1, "attempt": 1},
                {"schema_version": "continuation-request-gate.v1",
                 "request_id": gate.request_id, "phase": "completed",
                 "admitted": True, "call": 1, "attempt": 1,
                 "forwarded": False, "reason": "product_runtime_limit", "status": 429},
            ]
            gate._provider_calls = 1
            gate._attempts = 1

    _submit_raising_acp_error(
        runtime, compatibility, monkeypatch, "ord-exc-runtime",
        arm_gate=arm_runtime_stop,
    )
    _wait_status(runtime, "ord-exc-runtime", SessionStatus.IDLE)
    record = runtime._get("ord-exc-runtime")
    first_root = record.process_root_id
    first_gate = record.continuation_request_gate
    assert first_gate is not None
    assert first_gate.execution_profile["options_revision"] == 21
    assert first_gate.known_budget_block_reason() is None
    assert first_gate.known_postdispatch_product_runtime_limit() is True
    assert record.current_generation.continuation_proxy_closed is True
    payloads = _terminal_payloads(record)
    assert len(payloads) == 1
    assert payloads[0]["code"] == "model-run-failed"
    assert payloads[0]["retryable"] is False
    assert payloads[0]["error"] == "AcpRpcError"
    with pytest.raises(SessionConflict, match="not yet acknowledged"):
        runtime.submit_prompt("ord-exc-runtime", "second", conversation_context=[])

    runtime.acknowledge_terminal("ord-exc-runtime", record.terminal_receipts[first_root])
    runtime._test_execution_revision_by_session["ord-exc-runtime"] = 22
    monkeypatch.setattr(compatibility, "run_prepared_prompt", original_run)
    compatibility.prompt_started.clear()
    second_root = runtime.submit_prompt(
        "ord-exc-runtime", "second explicit instruction", conversation_context=[])
    _wait_status(runtime, "ord-exc-runtime", SessionStatus.IDLE)
    second_gate = record.continuation_request_gate
    assert second_root != first_root
    assert second_gate is not None and second_gate is not first_gate
    assert second_gate.execution_profile["options_revision"] == 22
    assert compatibility.resumed == []
    assert compatibility.successful_starts[-1].prompts == ["second explicit instruction"]
    runtime.acknowledge_terminal("ord-exc-runtime", record.terminal_receipts[second_root])


# --------------------------------------------------------------------------- #
# Exception-path known budget block (retained actual batch1 signature)
# --------------------------------------------------------------------------- #

_BATCH1_JOURNAL_FIXTURE = (
    Path(__file__).with_name("fixtures") / "dsh_batch1_known_budget_journal.jsonl"
)


def _capture_gate(runtime_module, monkeypatch, *, fail_proxy_close: bool = False) -> dict:
    captured: dict = {"state": {"fail": fail_proxy_close}}
    original = runtime_module.RequestGateProxy

    class Spy(original):
        def __init__(self, gate, *args, **kwargs):
            captured["gate"] = gate
            captured["proxy"] = self
            super().__init__(gate, *args, **kwargs)
            if fail_proxy_close:
                real_close = self.close
                state = captured["state"]

                def close() -> None:
                    if state["fail"]:
                        raise RuntimeError("synthetic proxy close failure")
                    real_close()

                self.close = close

    monkeypatch.setattr(runtime_module, "RequestGateProxy", Spy)
    return captured


def _batch1_receipts(request_id: str) -> list[dict]:
    rows = [json.loads(line) for line in _BATCH1_JOURNAL_FIXTURE.read_text().splitlines()
            if line.strip()]
    for row in rows:
        row["request_id"] = request_id
    return rows


def _arm_batch1_gate(gate) -> None:
    rows = _batch1_receipts(gate.request_id)
    with gate._lock:
        gate._receipts = rows
        gate._provider_calls = sum(1 for row in rows if row.get("phase") == "completed")
        gate._attempts = gate._provider_calls


def _submit_raising_acp_error(runtime, compatibility, monkeypatch, session, *,
                              fail_proxy_close: bool = False, arm_gate=None, arm_run=None) -> dict:
    """Drive the real exception branch with the retained batch1 AcpRpcError signature."""

    from app import runtime as runtime_module
    from app.compat.dsh_acp import AcpRpcError

    captured = _capture_gate(runtime_module, monkeypatch, fail_proxy_close=fail_proxy_close)

    def raising_run(prepared, content, _on_notification):
        gate = captured["gate"]
        _arm_batch1_gate(gate)
        if arm_gate is not None:
            arm_gate(gate)
        if arm_run is not None:
            arm_run(runtime._get(session))
        compatibility.prompt_started.set()
        raise AcpRpcError("session/prompt", -32000)

    monkeypatch.setattr(compatibility, "run_prepared_prompt", raising_run)
    _create(runtime, session, "workspace_slot_a")
    runtime.submit_prompt(session, "first explicit instruction", conversation_context=[])
    assert compatibility.prompt_started.wait(timeout=1.0)
    return captured


def _terminal_payloads(record) -> list[dict]:
    return [event["payload"] for event in record.history
            if event["kind"] in {"session.result", "session.failed"}]


def test_known_budget_exception_path_reopens_conversation(slot_runtime, monkeypatch):
    runtime, compatibility, _registry_value = slot_runtime
    original_run = compatibility.run_prepared_prompt
    _submit_raising_acp_error(runtime, compatibility, monkeypatch, "ord-exc-budget")
    _wait_status(runtime, "ord-exc-budget", SessionStatus.IDLE)
    record = runtime._get("ord-exc-budget")
    first_root = record.process_root_id
    assert record.status == SessionStatus.IDLE
    payloads = _terminal_payloads(record)
    assert len(payloads) == 1
    assert payloads[0]["code"] == "budget-exhausted"
    assert payloads[0]["retryable"] is False
    assert payloads[0]["error"] == "AcpRpcError"
    assert payloads[0]["run_id"] == first_root

    # Old root stays failed; exact ACK + cleanup fence the next root.
    with pytest.raises(SessionConflict, match="not yet acknowledged"):
        runtime.submit_prompt("ord-exc-budget", "second explicit instruction", conversation_context=[])
    runtime.acknowledge_terminal("ord-exc-budget", record.terminal_receipts[first_root])
    assert not record.reuse_native_session_ready

    # A fresh native new root is admitted; the failed input is never replayed.
    monkeypatch.setattr(compatibility, "run_prepared_prompt", original_run)
    compatibility.prompt_started.clear()
    second_root = runtime.submit_prompt(
        "ord-exc-budget", "second explicit instruction", conversation_context=[])
    _wait_status(runtime, "ord-exc-budget", SessionStatus.IDLE)
    assert second_root != first_root
    assert compatibility.resumed == []
    assert compatibility.successful_starts[-1].prompts == ["second explicit instruction"]
    runtime.acknowledge_terminal("ord-exc-budget", record.terminal_receipts[second_root])


def test_exception_path_unknown_outcome_stays_failed(slot_runtime, monkeypatch):
    runtime, compatibility, _registry_value = slot_runtime

    def arm_gate(gate):
        with gate._lock:
            gate._outcome_unknown = True

    _submit_raising_acp_error(runtime, compatibility, monkeypatch, "ord-exc-unknown",
                              arm_gate=arm_gate)
    _wait_status(runtime, "ord-exc-unknown", SessionStatus.FAILED)
    record = runtime._get("ord-exc-unknown")
    assert record.status == SessionStatus.FAILED
    payloads = _terminal_payloads(record)
    assert len(payloads) == 1
    assert payloads[0].get("code") != "budget-exhausted"
    assert payloads[0]["error"] == "AcpRpcError"


def test_exception_path_storage_failure_stays_failed(slot_runtime, monkeypatch):
    runtime, compatibility, _registry_value = slot_runtime

    def arm_gate(gate):
        with gate._lock:
            gate._journal_failed = True

    _submit_raising_acp_error(runtime, compatibility, monkeypatch, "ord-exc-storage",
                              arm_gate=arm_gate)
    _wait_status(runtime, "ord-exc-storage", SessionStatus.FAILED)
    record = runtime._get("ord-exc-storage")
    assert record.status == SessionStatus.FAILED
    assert _terminal_payloads(record)[0].get("code") != "budget-exhausted"


def test_exception_path_domain_stop_stays_failed(slot_runtime, monkeypatch):
    runtime, compatibility, _registry_value = slot_runtime

    def arm_run(record):
        record.active_run.domain_stop_code = "synthetic-domain-stop"

    _submit_raising_acp_error(runtime, compatibility, monkeypatch, "ord-exc-domain",
                              arm_run=arm_run)
    _wait_status(runtime, "ord-exc-domain", SessionStatus.FAILED)
    record = runtime._get("ord-exc-domain")
    assert record.status == SessionStatus.FAILED
    assert _terminal_payloads(record)[0].get("code") != "budget-exhausted"


def test_exception_path_unconfirmed_proxy_close_stays_failed(slot_runtime, monkeypatch):
    runtime, compatibility, _registry_value = slot_runtime
    captured = _submit_raising_acp_error(runtime, compatibility, monkeypatch, "ord-exc-noclose",
                                         fail_proxy_close=True)
    try:
        _wait_status(runtime, "ord-exc-noclose", SessionStatus.FAILED)
        record = runtime._get("ord-exc-noclose")
        assert record.status == SessionStatus.FAILED
        assert record.current_generation.continuation_proxy_closed is False
        assert _terminal_payloads(record)[0].get("code") != "budget-exhausted"
    finally:
        captured["state"]["fail"] = False


def test_private_predicate_rejects_non_ordinary_and_fenced_scopes(slot_runtime):
    from types import SimpleNamespace

    from app.research_request_gate import ResearchRequestGate
    from packages.contracts.agent_execution_options import default_agent_execution_options
    from packages.contracts.product_turn_request import (
        product_turn_execution_limits, product_turn_execution_profile,
    )

    runtime, _compatibility, _registry_value = slot_runtime
    options = default_agent_execution_options()
    gate = ResearchRequestGate(
        product_turn_execution_limits(options),
        execution_profile=product_turn_execution_profile(options, revision=4),
        request_id="product-turn-predicate",
    )
    with gate._lock:
        gate._receipts = [{
            "schema_version": "continuation-request-gate.v1",
            "request_id": "product-turn-predicate", "phase": "rejected",
            "admitted": False, "reason": "product_total_tool_payload_limit",
        }]
        gate._gate_closed = True
    generation = SimpleNamespace(generation_id="gen-a", continuation_proxy_closed=True)
    run = SimpleNamespace(domain_stop_code=None)
    ok_record = SimpleNamespace(current_generation=generation, continuation_request_gate=gate,
                                continuation_budget=None)
    assert runtime._known_ordinary_budget_block(ok_record, "gen-a", run) is True
    # F6 continuation budget is not the ordinary path.
    assert runtime._known_ordinary_budget_block(
        SimpleNamespace(current_generation=generation, continuation_request_gate=gate,
                        continuation_budget={"reservation_id": "r"}), "gen-a", run) is False
    # Unconfirmed proxy close.
    assert runtime._known_ordinary_budget_block(
        SimpleNamespace(current_generation=SimpleNamespace(generation_id="gen-a",
                                                           continuation_proxy_closed=False),
                        continuation_request_gate=gate, continuation_budget=None),
        "gen-a", run) is False
    # Domain stop.
    assert runtime._known_ordinary_budget_block(
        ok_record, "gen-a", SimpleNamespace(domain_stop_code="x")) is False
    # Stale generation.
    assert runtime._known_ordinary_budget_block(ok_record, "gen-b", run) is False
    # Missing gate.
    assert runtime._known_ordinary_budget_block(
        SimpleNamespace(current_generation=generation, continuation_request_gate=None,
                        continuation_budget=None), "gen-a", run) is False
