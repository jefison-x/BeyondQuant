"""In-boot generation replacement and fresh-session continuity contracts."""
from __future__ import annotations

import hashlib

import pytest

from packages.contracts.runtime_continuity import (
    FRESH, INTERRUPTED, REATTACHED, REHYDRATED, STATUSES, valid_continuity,
)

from app.runtime import RuntimeAdapter, SESSION_LOST_DETAIL, SessionConflict, SessionStatus
from .test_process_cleanup import FakeHarness, adapter, wait_for_status  # noqa: F401
from .test_session_rehydration import _simulate_process_death


def _generation_id(runtime: RuntimeAdapter, session_id: str) -> str:
    generation = runtime._get(session_id).current_generation
    assert generation is not None
    return generation.generation_id


def test_continuity_vocabulary_is_closed_and_framework_neutral() -> None:
    assert STATUSES == {FRESH, REATTACHED, REHYDRATED, INTERRUPTED}
    assert all(valid_continuity(value) for value in STATUSES)
    assert not valid_continuity("attached")
    assert not valid_continuity(None)


def test_fresh_session_and_live_adapter_reattachment(adapter: RuntimeAdapter) -> None:
    created = adapter.create_session("r2-fresh", "r2-fresh-trace", "alice", "workspace_alice")
    assert created["continuity"] == FRESH
    first_generation = _generation_id(adapter, "r2-fresh")
    native_session = adapter._get("r2-fresh").runtime_session_id
    assert native_session != "r2-fresh"

    resumed = adapter.resume_session("r2-fresh")

    assert resumed["continuity"] == REATTACHED
    assert resumed["resumed_from_run_id"] is None
    assert _generation_id(adapter, "r2-fresh") == first_generation
    assert len(FakeHarness.instances) == 1
    adapter.close()


def test_released_public_id_starts_a_new_native_dsh_session(adapter: RuntimeAdapter) -> None:
    adapter.create_session("r2-new", "r2-new-trace", "alice", "workspace_alice")
    old_native_session = adapter._get("r2-new").runtime_session_id
    adapter.release_session("r2-new")

    created = adapter.create_session("r2-new", "r2-new-trace", "alice", "workspace_alice")

    assert created["continuity"] == FRESH
    assert adapter._get("r2-new").runtime_session_id != old_native_session
    assert not (adapter._session_root / "byq-lifecycle-evidence").exists()
    adapter.close()


def test_adapter_restart_has_no_old_session_or_prompt_receipt(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.set()
    adapter.create_session("r2-restart", "r2-restart-trace", "alice", "workspace_alice")
    root = adapter.submit_prompt("r2-restart", "first synthetic turn", idempotency_key="restart-key-01")
    wait_for_status(adapter, "r2-restart", SessionStatus.IDLE)
    record = adapter._get("r2-restart")
    old_native_session = record.runtime_session_id
    sequence = record.sequence
    adapter.acknowledge_terminal("r2-restart", record.terminal_receipts[root])
    _simulate_process_death(adapter)

    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        digest = hashlib.sha256(b"first synthetic turn").hexdigest()
        assert restarted.reconcile_prompt("r2-restart", "restart-key-01", digest)["state"] == "outcome_unknown"
        with pytest.raises(KeyError):
            restarted.submit_prompt("r2-restart", "must not replay")
        with pytest.raises(SessionConflict, match="interrupted"):
            restarted.create_session(
                "r2-restart", "r2-restart-trace", "alice", "workspace_alice", sequence,
            )
        restarted.create_session("r2-restart", "r2-restart-trace", "alice", "workspace_alice")
        assert restarted._get("r2-restart").runtime_session_id != old_native_session
        assert restarted._get("r2-restart").history[0]["kind"] == "session.ready"
    finally:
        restarted.close()
        adapter.close()


def test_resume_after_hard_cancel_reports_lost_without_new_generation(
    adapter: RuntimeAdapter,
) -> None:
    created = adapter.create_session("r2-cancel", "r2-cancel-trace", "alice", "workspace_alice")
    first_generation = _generation_id(adapter, "r2-cancel")
    adapter.submit_prompt("r2-cancel", "running synthetic turn")
    assert FakeHarness.run_started.wait(1.0)
    adapter.cancel_session("r2-cancel", "hard")
    record = adapter._get("r2-cancel")
    history_after_cancel = list(record.history)

    with pytest.raises(SessionConflict) as exc:
        adapter.resume_session("r2-cancel")

    assert str(exc.value) == SESSION_LOST_DETAIL
    assert record.status == SessionStatus.INTERRUPTED
    assert record.continuity == created["continuity"] == FRESH
    assert record.history == history_after_cancel
    assert _generation_id(adapter, "r2-cancel") == first_generation
    assert len(FakeHarness.instances) == 1
    adapter.close()


def test_lost_resume_http_conflicts_without_starting_harness(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch, allow_current_runtime_authority,
) -> None:
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "adapter", adapter)
    allow_current_runtime_authority(adapter)
    client = TestClient(main.app)
    try:
        adapter.create_session("r2-http-lost", "r2-http-lost-trace", "alice", "workspace_alice")
        adapter.submit_prompt("r2-http-lost", "synthetic request", idempotency_key="lost-resume-key")
        assert FakeHarness.run_started.wait(1.0)
        adapter.cancel_session("r2-http-lost", "hard")
        record = adapter._get("r2-http-lost")
        history_after_cancel = list(record.history)
        generation = record.current_generation

        response = client.post("/internal/runtime/sessions/r2-http-lost/resume", json={})

        assert response.status_code == 409
        assert response.json() == {"detail": SESSION_LOST_DETAIL}
        assert len(FakeHarness.instances) == 1
        assert FakeHarness.instances[0].run_count == 1
        assert record.status == SessionStatus.INTERRUPTED
        assert record.history == history_after_cancel
        assert record.current_generation is generation
    finally:
        adapter.close()


def test_continuity_status_crosses_runtime_http_boundary(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch, allow_current_runtime_authority,
) -> None:
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "adapter", adapter)
    allow_current_runtime_authority(adapter)
    client = TestClient(main.app)
    try:
        created = client.post("/internal/runtime/sessions", json={
            "session_id": "r2-http", "trace_id": "r2-http-trace",
            "owner_principal": "alice", "workspace_id": "workspace_alice",
        })
        assert created.status_code == 201
        assert created.json()["continuity"] == FRESH

        resumed = client.post("/internal/runtime/sessions/r2-http/resume", json={})
        assert resumed.status_code == 200
        assert resumed.json()["continuity"] == REATTACHED

        stale = client.post("/internal/runtime/sessions", json={
            "session_id": "r2-http-stale", "trace_id": "r2-http-stale-trace",
            "owner_principal": "alice", "workspace_id": "workspace_alice", "initial_sequence": 1,
        })
        assert stale.status_code == 409
    finally:
        adapter.close()
