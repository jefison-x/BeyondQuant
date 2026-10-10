"""No-replay continuation boundaries at the Runtime Adapter."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.compat import compatibility_for_release
from app.runtime import RuntimeAdapter
from .test_process_cleanup import FakeHarness, release_compatibility
from .test_session_rehydration import _simulate_process_death
from packages.contracts.continuation_request import profile_binding, request_limits

_ROOT_IDENTITY_LINE = "X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID\n"


def _root_scoped_adapter(tmp_path: Path, monkeypatch) -> RuntimeAdapter:
    source = "- id: mcp-byq\n  config:\n    headers:\n      " + _ROOT_IDENTITY_LINE
    profile = tmp_path / "product.yml"
    profile.write_text(source, encoding="utf-8")
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({
        "root_identity_contract": "byq-root-process.v1",
        "composition_hash": "sha256:" + hashlib.sha256(source.encode()).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(profile))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(identity))
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_F6_EXECUTOR_ENABLED", "1")
    # ADR-0105 pins the continuation route to OpenCode Go chat.
    monkeypatch.setenv("BYQ_DSH_PROVIDER", "opencode-go-chat")
    monkeypatch.setenv("BYQ_DSH_MODEL", "deepseek-v4.1-flash")
    adapter = RuntimeAdapter(release_compatibility(tmp_path))
    monkeypatch.setattr(adapter, "continuation_qualified", lambda record: True)
    monkeypatch.setattr(adapter, "_resolve_model", lambda **kwargs: {
        "provider": "opencode-go-chat", "model": "deepseek-v4.1-flash", "api_key": "synthetic-only"})
    return adapter


def _plain_reservation() -> dict:
    return {
        "schema_version": "task-continuation-reservation.v2",
        "reservation_id": "continuation_" + "a" * 32,
        "task_id": "task_" + "b" * 32,
        "owner": "alice", "workspace_id": "workspace_alice",
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
    }


def test_legacy_recovery_carrier_is_rejected_before_prompt_admission(tmp_path, monkeypatch):
    FakeHarness.reset()
    adapter = _root_scoped_adapter(tmp_path, monkeypatch)
    adapter.create_session("no-replay", "no-replay-trace", "alice", "workspace_alice")
    record = adapter._get("no-replay")
    reservation = {**_plain_reservation(), "recovery_attempt": {"attempt_key": "recovery_" + "c" * 32}}
    try:
        with pytest.raises(ValueError, match="invalid continuation reservation"):
            adapter.submit_prompt("no-replay", "recovery", idempotency_key="recovery_" + "c" * 32,
                conversation_context=[], continuation_budget=reservation)
        assert record.active_run is None
        assert not any(event["kind"] == "session.started" for event in record.history)
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_original_reservation_key_replay_returns_the_same_accepted_run(tmp_path, monkeypatch):
    FakeHarness.reset()
    adapter = _root_scoped_adapter(tmp_path, monkeypatch)
    adapter.create_session("original", "original-trace", "alice", "workspace_alice")
    reservation = _plain_reservation()
    try:
        FakeHarness.allow_run.set()
        run_id = adapter.submit_prompt("original", "original instruction",
            idempotency_key=reservation["reservation_id"], conversation_context=[],
            continuation_budget=reservation)
        assert adapter.submit_prompt("original", "original instruction",
            idempotency_key=reservation["reservation_id"], conversation_context=[],
            continuation_budget=reservation) == run_id
        record = adapter._get("original")
        assert sum(event["kind"] == "session.started" for event in record.history) == 1
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_lost_original_prompt_remains_unknown_until_a_fresh_session(tmp_path, monkeypatch):
    """An in-flight receipt is unknown after Adapter loss and is never replayed."""
    from app import runtime as runtime_module

    FakeHarness.reset()
    adapter = _root_scoped_adapter(tmp_path, monkeypatch)
    def clean_tool_guard(_journal, _reservation, *, terminal=False):
        return {"reservation_id": _reservation["reservation_id"], "tool_calls": 0,
                "blocked_reason": None, "status": "settled" if terminal else "accepted"}
    monkeypatch.setattr(runtime_module, "read_request_guard", clean_tool_guard)
    monkeypatch.setattr(FakeHarness, "close", lambda self: None)
    try:
        adapter.create_session("lost", "lost-trace", "alice", "workspace_alice")
        reservation = _plain_reservation()
        content = "synthetic long research"
        adapter.submit_prompt("lost", content, idempotency_key=reservation["reservation_id"],
            conversation_context=[], continuation_budget=reservation)
        assert FakeHarness.run_started.wait(2.0)
        old_native_session = adapter._get("lost").runtime_session_id
        identity = json.dumps({"content": content, "reservation": reservation},
            sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(identity.encode()).hexdigest()
        assert adapter.reconcile_prompt("lost", reservation["reservation_id"], digest)["state"] == "accepted"
        _simulate_process_death(adapter)
        restarted = RuntimeAdapter(adapter._compatibility)
        with pytest.raises(KeyError):
            restarted.submit_prompt("lost", content, idempotency_key=reservation["reservation_id"])
        assert restarted.reconcile_prompt("lost", reservation["reservation_id"], digest) == {
            "schema_version": "prompt-receipt.v1", "state": "outcome_unknown"}
        restarted.create_session("lost", "lost-trace", "alice", "workspace_alice", initial_sequence=0)
        assert restarted._get("lost").runtime_session_id != old_native_session
        assert restarted.reconcile_prompt("lost", reservation["reservation_id"], digest) == {
            "schema_version": "prompt-receipt.v1", "state": "outcome_unknown"}
        restarted.close()
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_missing_continuation_receipt_does_not_scan_old_guard_files(tmp_path, monkeypatch):
    FakeHarness.reset()
    adapter = _root_scoped_adapter(tmp_path, monkeypatch)
    old_session_root = adapter._session_root / "old-native-session"
    old_session_root.mkdir(parents=True)
    reservation = _plain_reservation()
    (old_session_root / "continuation-budget.jsonl").write_text(json.dumps({
        "schema_version": "continuation-budget-guard.v1",
        "reservation_id": reservation["reservation_id"], "token_limit": 2_000_000,
    }))
    try:
        assert adapter.continuation_receipt("missing-session", reservation["reservation_id"]) == {
            "reservation_id": reservation["reservation_id"], "status": "outcome_unknown",
        }
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_acp_recovery_accepts_closed_before_ack_receipt_without_resume_or_replay(
    tmp_path, monkeypatch,
):
    """A Backend close receipt repairs the ACK race without reopening DSH."""
    session_id = "ack-race-session"
    trace_id = "ack-race-trace"
    root_run_id = "a" * 32
    native_session_id = "8b90c2b5-3a08-4eae-9fc7-04baf12910de"
    runtime_generation = "generation-" + "d" * 32
    session_root = tmp_path / "sessions"
    cwd = session_root / "byq-acp-workspaces" / session_id
    cwd.mkdir(parents=True)
    # This settled receipt test exercises local ACP recovery; it does not claim a Product slot binding.
    monkeypatch.setenv("BYQ_DSH_ACP_PROCESS_TRANSPORT", "local")
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("DSH_SESSION_ROOT", str(session_root))

    adapter = RuntimeAdapter(compatibility_for_release("dsh-v0.2.0-rc.2-acp"))
    monkeypatch.setattr(adapter, "require_current_backend_authority", lambda: 8)
    monkeypatch.setattr(adapter, "_resolve_model", lambda **kwargs: {
        "provider": "deepseek-official", "model": "deepseek-v4-flash",
        "api_key": "synthetic-only",
    })
    monkeypatch.setattr(adapter, "_build_harness", lambda *args, **kwargs: pytest.fail(
        "settled lifecycle recovery must not resume or start ACP"))

    binding = {
        "schema_version": "byq-acp-root-binding.v1",
        "session_id": session_id,
        "trace_id": trace_id,
        "owner_principal": "alice",
        "workspace_id": "workspace_alice",
        "root_run_id": root_run_id,
        "native_session_id": native_session_id,
        "runtime_generation": runtime_generation,
        "model_provider": "deepseek-official",
        "model_id": "deepseek-v4-flash",
        "cwd": str(cwd.resolve()),
        "previous_boot_id": "b" * 32,
        "previous_authority_epoch": 7,
        "sequence": 4,
        "settlement_receipt": None,
        "domain_call_sequence": 0,
        "domain_call_drained_sequence": 0,
        # This fixture represents the narrow ACK race after the prior process
        # was independently confirmed exited. Without this proof, reattach
        # must fail closed even though Backend supplied a terminal receipt.
        "native_session_close_confirmed": False,
        "process_exit_confirmed": True,
        "cleanup_unconfirmed": False,
        "closed": False,
    }
    binding_path = adapter._acp_binding_path(session_id)
    binding_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    lifecycle_receipt = {
        "schema_version": "agent-run-lifecycle-receipt.v1",
        "root_run_id": root_run_id,
        "sequence": 5,
        "event_sha256": "c" * 64,
    }

    try:
        result = adapter.recover_acp_session(
            session_id, lifecycle_receipt, initial_sequence=5,
        )

        assert result["status"] == "idle"
        assert result["continuity"] == "reattached"
        assert result["resumed_from_run_id"] is None
        persisted = json.loads(binding_path.read_text(encoding="utf-8"))
        assert persisted["settlement_receipt"] == lifecycle_receipt
        assert persisted["native_session_id"] == native_session_id
        assert persisted["runtime_generation"] == runtime_generation
        assert adapter.recovery_binding(session_id) == {
            "schema_version": "byq-runtime-recovery-binding.v1",
            "state": "settled",
            "session_id": session_id,
            "trace_id": trace_id,
            "owner_principal": "alice",
            "workspace_id": "workspace_alice",
            "root_run_id": root_run_id,
            "previous_boot_id": adapter.boot_id,
            "previous_authority_epoch": 8,
            "sequence": 5,
            "settlement_receipt": lifecycle_receipt,
        }
        assert adapter._get(session_id).history == []
    finally:
        adapter.close()
