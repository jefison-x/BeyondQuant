"""No-replay continuation boundaries at the Runtime Adapter."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.runtime import RuntimeAdapter
from .test_process_cleanup import FakeHarness, release_compatibility
from .test_session_rehydration import _simulate_process_death

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
    adapter = RuntimeAdapter(release_compatibility(tmp_path))
    monkeypatch.setattr(adapter, "continuation_qualified", lambda record: True)
    monkeypatch.setattr(adapter, "_resolve_model", lambda **kwargs: {
        "provider": "deepseek-official", "model": "deepseek-v4-flash", "api_key": "synthetic-only"})
    return adapter


def _plain_reservation() -> dict:
    return {
        "schema_version": "task-continuation-reservation.v1",
        "reservation_id": "continuation_" + "a" * 32,
        "task_id": "task_" + "b" * 32,
        "owner": "alice", "workspace_id": "workspace_alice",
        "token_limit": 2_000_000,
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
    monkeypatch.setattr(runtime_module, "read_guard", lambda *args, **kwargs: {"charged_tokens": 1})
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
        "reservation_id": reservation["reservation_id"], "token_limit": reservation["token_limit"],
    }))
    try:
        assert adapter.continuation_receipt("missing-session", reservation["reservation_id"]) == {
            "reservation_id": reservation["reservation_id"], "status": "outcome_unknown",
        }
    finally:
        adapter.close()
        FakeHarness.allow_run.set()
