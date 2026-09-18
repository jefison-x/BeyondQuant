"""ADR-0046 restart survivability: durable sessions rebind after process death.

A deploy recreates the runtime-adapter container. The in-memory ``_sessions``
map is empty afterwards, but the BYQ lifecycle journal and DSH session root are
durable. A follow-up prompt/events/subscribe for such a session must rehydrate
the record from disk instead of returning 404, and the public BYQ sequence must
continue from the durable/gateway-persisted value so the Gateway trace never
sees a false gap.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from app.runtime import RuntimeAdapter, SessionStatus
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


def test_rehydrated_session_continues_after_adapter_restart(adapter: RuntimeAdapter) -> None:
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
            subscriber = restarted.subscribe("restart-1", replay=True)
            replayed = []
            while not subscriber.empty():
                replayed.append(subscriber.get())
            assert [event["sequence"] for event in replayed] == sorted(
                event["sequence"] for event in replayed
            )

            second = restarted.submit_prompt("restart-1", "second synthetic turn")
            assert restarted._get("restart-1").harness is not None, "harness not bound"
            assert second and second != first
            wait_for_status(restarted, "restart-1", SessionStatus.IDLE)

            started = [
                event for event in restarted._get("restart-1").history
                if event["kind"] == "session.started" and event["payload"]["run_id"] == second
            ]
            assert started, "rehydrated prompt did not emit session.started"
            assert started[0]["sequence"] == durable + 1
            assert started[0]["trace_id"] == "restart-trace"
        finally:
            restarted.close()
    finally:
        adapter.close()


def test_rehydrated_session_rebases_public_sequence_to_persisted_trace(
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
            created = rebound.create_session(
                "restart-2", "restart-trace-2", "alice", "workspace_alice",
                persisted, [{"role": "user", "content": "earlier synthetic turn"}],
            )
            assert created["status"] == SessionStatus.READY
            assert rebound._get("restart-2").sequence == persisted + 1
        finally:
            rebound.close()
    finally:
        adapter.close()


def test_root_scoped_rehydrated_session_binds_a_reserved_root(
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
            second = restarted.submit_prompt("root-rehydrate", "second root turn")
            assert second != root and len(second) == 32
            wait_for_status(restarted, "root-rehydrate", SessionStatus.IDLE)
            started = [item for item in restarted._get("root-rehydrate").history
                       if item["kind"] == "session.started" and item["payload"]["run_id"] == second]
            assert started and started[0]["sequence"] == durable + 1
        finally:
            restarted.close()
    finally:
        first.close()


def test_diverged_durable_tail_is_reanchored_on_rebind(adapter: RuntimeAdapter) -> None:
    """A frozen Gateway trace resumes gap-free from its persisted cursor.

    The Runtime can keep emitting while no collector persists it. On rebind,
    durable evidence the Gateway never saw is re-anchored at persisted + 1 so
    the registration event is delivered contiguously and the run can bind.
    """

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
            created = rebound.create_session(
                "restart-tail", "restart-tail-trace", "alice", "workspace_alice",
                gateway_cursor, [],
            )
            assert created["status"] == SessionStatus.READY
            replayed = [
                item for item in rebound._get("restart-tail").history
                if item["sequence"] > gateway_cursor
            ]
            assert [item["sequence"] for item in replayed] == [
                gateway_cursor + 1, gateway_cursor + 2, gateway_cursor + 3, gateway_cursor + 4,
            ]
            assert [item["kind"] for item in replayed] == [
                "session.started", "agent.run.registration", "session.result", "session.ready",
            ]
        finally:
            rebound.close()
    finally:
        adapter.close()


@pytest.mark.parametrize("shutdown", ["release", "close"])
def test_rehydrated_session_shutdown_without_a_process_is_safe(
    adapter: RuntimeAdapter, shutdown: str,
) -> None:
    """An events-only rehydration owns no DSH process yet."""

    adapter.create_session("restart-shutdown", "restart-shutdown-trace", "alice", "workspace_alice")
    _simulate_process_death(adapter)
    restarted = RuntimeAdapter(adapter._compatibility)
    restarted.subscribe("restart-shutdown")
    if shutdown == "release":
        assert restarted.release_session("restart-shutdown")["status"] == SessionStatus.CLOSED
    restarted.close()


def test_http_boundary_after_restart_is_404_or_accepted(adapter: RuntimeAdapter, monkeypatch) -> None:
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
    client = TestClient(main.app)
    try:
        assert client.post("/internal/runtime/sessions/never-existed/prompt",
                           json={"content": "synthetic"}).status_code == 404
        assert client.get("/internal/runtime/sessions/never-existed/events").status_code == 404
        accepted = client.post("/internal/runtime/sessions/restart-http/prompt",
                               json={"content": "second synthetic turn"})
        assert accepted.status_code == 202
        assert accepted.json()["accepted"] is True and accepted.json()["run_id"]
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
