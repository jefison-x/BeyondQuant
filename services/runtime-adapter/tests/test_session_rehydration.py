"""Adapter process loss ends the Agent session without replaying its prompt.

BYQ lifecycle evidence and exact prompt receipts remain durable for read-only
business reconciliation, while runtime operations require a live in-memory DSH
session. A new Agent session uses a new stable ID.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from app.runtime import RuntimeAdapter, SessionConflict, SessionStatus
from app.lifecycle_journal import LifecycleJournal
from .test_process_cleanup import FakeHarness, adapter, release_compatibility, wait_for_status


def _simulate_process_death(runtime: RuntimeAdapter) -> None:
    """Drop all in-memory state and release the durable journal lock only.

    This models a container recreation (SIGKILL): no graceful ``close()`` event
    is emitted, but the kernel releases the flock with the dead process.
    """

    with runtime._lock:
        for record in runtime._sessions.values():
            if record.journal is not None:
                record.journal.close()
        runtime._sessions.clear()


def test_gateway_attaches_only_to_a_live_adapter_session(adapter: RuntimeAdapter) -> None:
    adapter.create_session("live-attach", "live-trace", "alice", "workspace_alice")
    assert adapter.attach_live_session(
        "live-attach", "live-trace", "alice", "workspace_alice",
    )["session_id"] == "live-attach"
    with pytest.raises(SessionConflict, match="identity conflicts"):
        adapter.attach_live_session("live-attach", "live-trace", "other", "workspace_alice")
    _simulate_process_death(adapter)
    with pytest.raises(SessionConflict, match="interrupted"):
        adapter.attach_live_session("live-attach", "live-trace", "alice", "workspace_alice")


def test_http_create_requires_workspace_scoped_identity(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch, allow_current_runtime_authority,
) -> None:
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "adapter", adapter)
    allow_current_runtime_authority(adapter)
    client = TestClient(main.app)
    for identity in (
        {"owner_principal": "alice"},
        {"owner_principal": "alice", "workspace_id": ""},
        {"owner_principal": "", "workspace_id": "workspace_alice"},
    ):
        response = client.post("/internal/runtime/sessions", json={
            "session_id": "unscoped", "trace_id": "unscoped-trace", **identity,
        })
        assert response.status_code == 422
    with pytest.raises(KeyError):
        adapter._get("unscoped")


def test_adapter_restart_does_not_rebind_a_completed_session(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.set()
    try:
        adapter.create_session("restart-1", "restart-trace", "alice", "workspace_alice")
        first = adapter.submit_prompt("restart-1", "first synthetic turn")
        wait_for_status(adapter, "restart-1", SessionStatus.IDLE)
        durable = adapter._get("restart-1").sequence
        assert durable > 1
        # The Gateway's lifecycle delivery acknowledges the settled terminal.
        adapter.acknowledge_terminal("restart-1", adapter._get("restart-1").terminal_receipts[first])
        _simulate_process_death(adapter)

        restarted = RuntimeAdapter(adapter._compatibility)
        try:
            with pytest.raises(KeyError):
                restarted.submit_prompt("restart-1", "second synthetic turn")
            with pytest.raises(KeyError):
                restarted.subscribe("restart-1", replay=True)
            with pytest.raises(SessionConflict, match="interrupted"):
                restarted.create_session(
                    "restart-1", "restart-trace", "alice", "workspace_alice", durable, [],
                )
            state = LifecycleJournal.read(
                restarted._session_root / "byq-lifecycle-evidence" / "restart-1.json")
            assert state["open_root"] is None
            assert any(event["kind"] == "session.result"
                       and event["payload"]["run_id"] == first for event in state["events"])
        finally:
            restarted.close()
    finally:
        adapter.close()


def test_adapter_restart_rejects_old_identity_even_with_a_persisted_trace_cursor(
    adapter: RuntimeAdapter,
) -> None:
    """A journal ahead only on non-durable events must not create a trace gap.

    The Gateway persisted sequence is the append authority; rebinding with the
    caller's ``initial_sequence`` must continue from it rather than from the
    adapter's phantom release/recreate tail.
    """

    FakeHarness.allow_run.set()
    try:
        adapter.create_session("restart-2", "restart-trace-2", "alice", "workspace_alice")
        adapter.submit_prompt("restart-2", "first synthetic turn")
        wait_for_status(adapter, "restart-2", SessionStatus.IDLE)
        record = adapter._get("restart-2")
        persisted = record.sequence
        # Non-durable events advanced the journal past the Gateway trace.
        for _ in range(3):
            adapter._emit(record, "session.status", "runtime-adapter", {"status": "idle"})
        assert record.sequence == persisted + 3
        _simulate_process_death(adapter)

        rebound = RuntimeAdapter(adapter._compatibility)
        try:
            with pytest.raises(SessionConflict, match="interrupted"):
                rebound.create_session(
                    "restart-2", "restart-trace-2", "alice", "workspace_alice",
                    persisted, [{"role": "user", "content": "earlier synthetic turn"}],
                )
        finally:
            rebound.close()
    finally:
        adapter.close()


def test_root_scoped_session_cannot_be_reused_after_adapter_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Production ``root-turn`` ownership resumes with a reserved root id."""

    composition = "X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID\n"
    profile = tmp_path / "root-profile.yml"
    profile.write_text(composition)
    identity = tmp_path / "root-identity.json"
    identity.write_text(json.dumps({
        "root_identity_contract": "byq-root-process.v1",
        "composition_hash": "sha256:" + hashlib.sha256(composition.encode()).hexdigest(),
    }))
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(profile))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(identity))
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.delenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", raising=False)
    FakeHarness.reset()
    FakeHarness.allow_run.set()
    compatibility = release_compatibility(tmp_path)
    first = RuntimeAdapter(compatibility)
    try:
        first.create_session("root-rehydrate", "root-trace", "alice", "workspace_alice")
        root = first.submit_prompt("root-rehydrate", "first root turn")
        wait_for_status(first, "root-rehydrate", SessionStatus.IDLE)
        durable = first._get("root-rehydrate").sequence
        first.acknowledge_terminal("root-rehydrate", first._get("root-rehydrate").terminal_receipts[root])
        _simulate_process_death(first)

        restarted = RuntimeAdapter(compatibility)
        try:
            with pytest.raises(KeyError):
                restarted.submit_prompt("root-rehydrate", "second root turn")
            with pytest.raises(SessionConflict, match="interrupted"):
                restarted.create_session(
                    "root-rehydrate", "root-trace", "alice", "workspace_alice", durable, [],
                )
        finally:
            restarted.close()
    finally:
        first.close()


def test_diverged_durable_tail_does_not_authorize_rebinding(adapter: RuntimeAdapter) -> None:

    FakeHarness.allow_run.set()
    try:
        adapter.create_session("restart-tail", "restart-tail-trace", "alice", "workspace_alice")
        first = adapter.submit_prompt("restart-tail", "first synthetic turn")
        wait_for_status(adapter, "restart-tail", SessionStatus.IDLE)
        record = adapter._get("restart-tail")
        gateway_cursor = record.sequence
        adapter.acknowledge_terminal("restart-tail", record.terminal_receipts[first])
        # Non-durable events inflate the journal past the Gateway cursor.
        for _ in range(2):
            adapter._emit(record, "session.status", "runtime-adapter", {"status": "idle"})
        second_root = "d" * 32
        adapter._emit(record, "session.started", "runtime-adapter", {"run_id": second_root})
        adapter._emit(record, "agent.run.registration", "runtime-adapter", {
            "schema_version": "agent-run-registration-observed.v1",
            "run_id": second_root, "registration_fingerprint": "e" * 64,
        })
        adapter._emit(record, "session.result", "runtime-adapter", {"run_id": second_root})
        assert record.sequence == gateway_cursor + 5
        _simulate_process_death(adapter)

        rebound = RuntimeAdapter(adapter._compatibility)
        try:
            with pytest.raises(SessionConflict, match="interrupted"):
                rebound.create_session(
                    "restart-tail", "restart-tail-trace", "alice", "workspace_alice",
                    gateway_cursor, [],
                )
        finally:
            rebound.close()
    finally:
        adapter.close()


@pytest.mark.parametrize("shutdown", ["release", "close"])
def test_lost_session_has_no_adapter_record_to_release_or_subscribe(
    adapter: RuntimeAdapter, shutdown: str,
) -> None:
    adapter.create_session("restart-shutdown", "restart-shutdown-trace", "alice", "workspace_alice")
    _simulate_process_death(adapter)
    restarted = RuntimeAdapter(adapter._compatibility)
    with pytest.raises(KeyError):
        restarted.subscribe("restart-shutdown")
    if shutdown == "release":
        with pytest.raises(KeyError):
            restarted.release_session("restart-shutdown")
    restarted.close()


def test_http_boundary_after_restart_rejects_the_old_session(
    adapter: RuntimeAdapter, monkeypatch, allow_current_runtime_authority,
) -> None:
    from fastapi.testclient import TestClient
    from app import main

    FakeHarness.allow_run.set()
    adapter.create_session("restart-http", "restart-http-trace", "alice", "workspace_alice")
    root = adapter.submit_prompt("restart-http", "first synthetic turn")
    wait_for_status(adapter, "restart-http", SessionStatus.IDLE)
    adapter.acknowledge_terminal("restart-http", adapter._get("restart-http").terminal_receipts[root])
    _simulate_process_death(adapter)

    restarted = RuntimeAdapter(adapter._compatibility)
    monkeypatch.setattr(main, "adapter", restarted)
    allow_current_runtime_authority(restarted)
    client = TestClient(main.app)
    try:
        assert client.post("/internal/runtime/sessions/never-existed/prompt",
                           json={"content": "synthetic"}).status_code == 404
        assert client.get("/internal/runtime/sessions/never-existed/events").status_code == 404
        rejected = client.post("/internal/runtime/sessions/restart-http/prompt",
                              json={"content": "second synthetic turn"})
        assert rejected.status_code == 404
        recreated = client.post("/internal/runtime/sessions", json={
            "session_id": "restart-http", "trace_id": "restart-http-trace",
            "owner_principal": "alice", "workspace_id": "workspace_alice", "initial_sequence": 1,
        })
        assert recreated.status_code == 409
        assert "interrupted" in recreated.json()["detail"]
    finally:
        restarted.close()
        adapter.close()


def test_unknown_session_still_raises_clean_keyerror(adapter: RuntimeAdapter) -> None:
    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        with pytest.raises(KeyError):
            restarted.submit_prompt("never-existed", "synthetic")
        with pytest.raises(KeyError):
            restarted.subscribe("never-existed")
    finally:
        restarted.close()


def _rewrite_lease_identity(runtime: RuntimeAdapter, session_id: str, lease_identity: str) -> None:
    """Simulate a journal written under a different host boot identity."""

    path = runtime._session_root / "byq-lifecycle-evidence" / f"{session_id}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["state"]["lease_identity"] = lease_identity
    encoded = json.dumps(envelope["state"], sort_keys=True, separators=(",", ":")).encode()
    envelope["sha256"] = hashlib.sha256(encoded).hexdigest()
    path.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _stale_session(adapter: RuntimeAdapter, session_id: str) -> int:
    FakeHarness.allow_run.set()
    adapter.create_session(session_id, f"{session_id}-trace", "alice", "workspace_alice")
    first = adapter.submit_prompt(session_id, "first synthetic turn")
    wait_for_status(adapter, session_id, SessionStatus.IDLE)
    record = adapter._get(session_id)
    durable = record.sequence
    adapter.acknowledge_terminal(session_id, record.terminal_receipts[first])
    _simulate_process_death(adapter)
    # 2026-09-10 host reboot: the stored lease can never match this boot again.
    _rewrite_lease_identity(adapter, session_id, "f" * 64)
    return durable


def test_stale_lease_is_explicit_and_distinct_from_unknown(adapter: RuntimeAdapter) -> None:
    durable = _stale_session(adapter, "stale-1")
    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        with pytest.raises(KeyError):
            restarted.submit_prompt("stale-1", "second synthetic turn")
        with pytest.raises(SessionConflict, match="interrupted"):
            restarted.create_session(
                "stale-1", "stale-1-trace", "alice", "workspace_alice", durable, [],
            )
        # A genuinely unknown session stays a clean 404 (KeyError), not 409.
        with pytest.raises(KeyError):
            restarted.submit_prompt("never-existed", "synthetic")
    finally:
        restarted.close()
        adapter.close()


def test_valid_and_stale_old_sessions_are_both_unavailable_after_restart(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.set()
    try:
        adapter.create_session("valid-1", "valid-1-trace", "alice", "workspace_alice")
        first = adapter.submit_prompt("valid-1", "first synthetic turn")
        wait_for_status(adapter, "valid-1", SessionStatus.IDLE)
        durable = adapter._get("valid-1").sequence
        adapter.acknowledge_terminal("valid-1", adapter._get("valid-1").terminal_receipts[first])
        _stale_session(adapter, "stale-2")

        restarted = RuntimeAdapter(adapter._compatibility)
        try:
            with pytest.raises(KeyError):
                restarted.submit_prompt("valid-1", "second synthetic turn")
            with pytest.raises(SessionConflict, match="interrupted"):
                restarted.create_session("valid-1", "valid-1-trace", "alice", "workspace_alice", durable, [])
            with pytest.raises(KeyError):
                restarted.submit_prompt("stale-2", "second synthetic turn")
        finally:
            restarted.close()
    finally:
        adapter.close()


def test_http_old_session_is_rejected_after_adapter_restart(
    adapter: RuntimeAdapter, monkeypatch, allow_current_runtime_authority,
) -> None:
    from fastapi.testclient import TestClient
    from app import main

    durable = _stale_session(adapter, "stale-http")
    restarted = RuntimeAdapter(adapter._compatibility)
    monkeypatch.setattr(main, "adapter", restarted)
    allow_current_runtime_authority(restarted)
    client = TestClient(main.app, raise_server_exceptions=False)
    try:
        prompt = client.post("/internal/runtime/sessions/stale-http/prompt",
                             json={"content": "second synthetic turn"})
        assert prompt.status_code == 404

        created = client.post("/internal/runtime/sessions", json={
            "session_id": "stale-http", "trace_id": "stale-http-trace",
            "owner_principal": "alice", "workspace_id": "workspace_alice",
            "initial_sequence": durable,
        })
        assert created.status_code == 409
        assert "interrupted" in created.json()["detail"]

        unknown = client.get("/internal/runtime/sessions/never-existed/events")
        assert unknown.status_code == 404
    finally:
        restarted.close()
        adapter.close()
