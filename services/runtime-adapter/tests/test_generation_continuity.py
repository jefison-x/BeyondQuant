"""ADR-0079 R2: durable session identity vs ephemeral runtime generations.

A durable BYQ AgentSession can be served by generation-1..N. This suite proves
that replacing a generation (adapter restart, crash, resume) never changes the
durable session identity, never loses evidence/sequence, and reports one honest
framework-neutral continuity status.
"""
from __future__ import annotations

import pytest

from packages.contracts.runtime_continuity import (
    FRESH, INTERRUPTED, REATTACHED, REHYDRATED, STATUSES, valid_continuity,
)

from app.lifecycle_journal import LifecycleJournal
from app.runtime import RuntimeAdapter, SessionStatus
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


def test_fresh_session_is_fresh_and_live_generation_reattaches(adapter: RuntimeAdapter) -> None:
    created = adapter.create_session("r2-fresh", "r2-fresh-trace", "alice", "workspace_alice")
    assert created["continuity"] == FRESH
    first_generation = _generation_id(adapter, "r2-fresh")

    resumed = adapter.resume_session("r2-fresh")

    # Path A: the original in-process generation is still alive and is reused.
    assert resumed["continuity"] == REATTACHED
    assert resumed["resumed_from_run_id"] is None
    assert _generation_id(adapter, "r2-fresh") == first_generation
    assert len(FakeHarness.instances) == 1
    adapter.close()


def test_recreation_with_durable_evidence_is_rehydrated(adapter: RuntimeAdapter) -> None:
    adapter.create_session("r2-new", "r2-new-trace", "alice", "workspace_alice")
    adapter.release_session("r2-new")
    # A released adapter session is gone from memory but its journal remains;
    # the durable session is rehydrated rather than reported as brand new.
    recreated = adapter.create_session("r2-new", "r2-new-trace", "alice", "workspace_alice")
    assert recreated["continuity"] == REHYDRATED
    adapter.close()


def test_restart_rehydrates_with_new_generation_and_stable_identity(
    adapter: RuntimeAdapter,
) -> None:
    FakeHarness.allow_run.set()
    created = adapter.create_session("r2-restart", "r2-restart-trace", "alice", "workspace_alice")
    assert created["continuity"] == FRESH
    first_generation = _generation_id(adapter, "r2-restart")
    root = adapter.submit_prompt("r2-restart", "first synthetic turn")
    wait_for_status(adapter, "r2-restart", SessionStatus.IDLE)
    record = adapter._get("r2-restart")
    durable_sequence = record.sequence
    adapter.acknowledge_terminal("r2-restart", record.terminal_receipts[root])
    assert durable_sequence > 1
    _simulate_process_death(adapter)

    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        rebound = restarted.create_session(
            "r2-restart", "r2-restart-trace", "alice", "workspace_alice",
            durable_sequence, [{"role": "user", "content": "earlier public turn"}],
        )
        assert rebound["continuity"] == REHYDRATED

        rehydrated = restarted._get("r2-restart")
        # The durable session identity and the persisted trace sequence survive
        # generation replacement.
        assert rehydrated.session_id == "r2-restart"
        assert rehydrated.trace_id == "r2-restart-trace"
        assert rehydrated.sequence == durable_sequence + 1
        # A brand-new generation replaced the lost one; the previous generation
        # remains recorded in the bounded BYQ generation history.
        new_generation = _generation_id(restarted, "r2-restart")
        assert new_generation != first_generation
        assert any(item.generation_id == first_generation for item in rehydrated.generations)
        # Durable lifecycle evidence is intact and still contains the run.
        state = LifecycleJournal.read(
            restarted._session_root / "byq-lifecycle-evidence" / "r2-restart.json")
        assert state["sequence"] >= durable_sequence
        assert any(event["kind"] == "session.result" for event in state["events"])
    finally:
        restarted.close()
        adapter.close()


def test_crashed_generation_is_interrupted_and_a_new_generation_rehydrates(
    adapter: RuntimeAdapter,
) -> None:
    FakeHarness.allow_run.clear()
    adapter.create_session("r2-crash", "r2-crash-trace", "alice", "workspace_alice")
    first_generation = _generation_id(adapter, "r2-crash")
    adapter.submit_prompt("r2-crash", "long synthetic turn")
    assert FakeHarness.run_started.wait(1.0)

    # Ungraceful adapter/DSH death while the root is still open. Detach the
    # dead worker so it cannot append after the journal lock is released.
    with adapter._lock:
        record = adapter._sessions["r2-crash"]
        record.active_run = None
        record.journal.close()
        del adapter._sessions["r2-crash"]

    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        rebound = restarted.create_session(
            "r2-crash", "r2-crash-trace", "alice", "workspace_alice", 1, [],
        )
        # Truthful: the previous run/generation was terminated, not silently
        # reattached, and a new generation carries the durable session forward.
        assert rebound["continuity"] == INTERRUPTED
        rehydrated = restarted._get("r2-crash")
        assert rehydrated.session_id == "r2-crash"
        assert _generation_id(restarted, "r2-crash") != first_generation
        previous = [item for item in rehydrated.generations
                    if item.generation_id == first_generation]
        assert previous and previous[0].state == INTERRUPTED
    finally:
        restarted.close()
        FakeHarness.allow_run.set()
        adapter.close()


def test_resume_after_hard_cancel_reports_interrupted_with_new_generation(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("r2-cancel", "r2-cancel-trace", "alice", "workspace_alice")
    first_generation = _generation_id(adapter, "r2-cancel")
    adapter.submit_prompt("r2-cancel", "running synthetic turn")
    assert FakeHarness.run_started.wait(1.0)
    adapter.cancel_session("r2-cancel", "hard")

    resumed = adapter.resume_session("r2-cancel")

    assert resumed["continuity"] == INTERRUPTED
    assert resumed["resumed_from_run_id"]
    assert _generation_id(adapter, "r2-cancel") != first_generation
    assert adapter._get("r2-cancel").session_id == "r2-cancel"
    adapter.close()


def test_continuity_status_crosses_the_runtime_http_boundary(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "adapter", adapter)
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
    finally:
        adapter.close()
