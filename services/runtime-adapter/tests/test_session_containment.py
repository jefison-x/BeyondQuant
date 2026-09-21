"""ADR-0084 session failure containment at the Runtime Adapter boundary.

These tests drive the real ``RuntimeAdapter`` state machine with its synthetic
compatibility harness. Execution loss is simulated by dropping in-memory state
and releasing the durable journal lock exactly as a SIGKILL/container recreation
would (the kernel releases the flock, no graceful close event is emitted).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from packages.contracts import session_failure_containment as containment_contract
from packages.contracts.session_failure_containment import FencedWrite
from app import containment
from app import executor_identity
from app.executor_identity import ExecutorFenced, ExecutorIdentity
from app.runtime import RuntimeAdapter, SessionStatus
from .test_process_cleanup import FakeHarness, adapter, wait_for_status  # noqa: F401
from .test_session_rehydration import _simulate_process_death


def _restart(adapter: RuntimeAdapter) -> RuntimeAdapter:
    return RuntimeAdapter(adapter._compatibility)


def test_lost_executor_run_is_interrupted_and_business_state_survives(
    adapter: RuntimeAdapter,
) -> None:
    FakeHarness.allow_run.clear()
    adapter.create_session("loss-1", "loss-trace", "alice", "workspace_alice")
    content = "synthetic long research"
    root = adapter.submit_prompt("loss-1", content, idempotency_key="loss-original-key")
    assert FakeHarness.run_started.wait(1.0)
    record = adapter._get("loss-1")
    durable_sequence = record.sequence
    assert record.status == SessionStatus.RUNNING

    _simulate_process_death(adapter)
    restarted = _restart(adapter)
    try:
        rebound = restarted.create_session(
            "loss-1", "loss-trace", "alice", "workspace_alice", durable_sequence, [],
        )
        # Honest terminal: the lost incomplete run is interrupted, never completed
        # and never silently reattached.
        assert rebound["continuity"] == "interrupted"
        rehydrated = restarted._get("loss-1")
        assert rehydrated.session_id == "loss-1"
        assert rehydrated.trace_id == "loss-trace"
        # Conversation identity, public history and the durable prompt receipt
        # survive; no second model call was made.
        kinds = [event["kind"] for event in rehydrated.history]
        assert "session.started" in kinds and "session.closed" in kinds
        digest = hashlib.sha256(content.encode()).hexdigest()
        assert restarted.reconcile_prompt("loss-1", "loss-original-key", digest) == {
            "schema_version": "prompt-receipt.v1", "state": "accepted", "run_id": root,
        }
        assert FakeHarness.instances[0].run_count == 1

        summary = restarted.containment_summary("loss-1")
        assert summary["contained"] is True
        assert summary["latest"]["loss_cause"] == "executor-loss"
        assert summary["latest"]["interrupted_run_id"] == root
        assert summary["latest"]["interrupted_generation"]
        assert summary["latest"]["executor_epoch"] >= 1
        # Framework-neutral trace binding: the Gateway may only project
        # interrupted when this matches the exact session/trace.
        assert summary["latest"]["trace_id"] == "loss-trace"
        records = containment.read(restarted._session_root / "byq-lifecycle-evidence", "loss-1")
        # The record carries the execution-boundary assertion, not business
        # evidence: the adapter cannot and does not claim business preservation.
        assert all(record["boundary_invariant"] == containment_contract.BOUNDARY_INVARIANT
                   for record in records)
        assert all("preserved" not in record for record in records)
    finally:
        restarted.close()
        FakeHarness.allow_run.set()
        adapter.close()


def test_containment_write_fails_closed_on_stale_executor_epoch(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("loss-2", "loss-2-trace", "alice", "workspace_alice")
    evidence_root = adapter._session_root / "byq-lifecycle-evidence"
    current = adapter._get("loss-2").journal.executor
    adapter.release_session("loss-2")
    # An explicit, audited takeover advances the authoritative volume epoch; the
    # previous epoch becomes a fenced writer.
    executor_identity.takeover(evidence_root, reason="synthetic containment takeover", operator="test")
    stale = ExecutorIdentity(
        deployment_id=current.deployment_id, runtime_release=current.runtime_release,
        volume_identity=current.volume_identity, executor_epoch=current.executor_epoch,
        state_path=current.state_path, reason="test-stale",
    )
    context = {"session_id": "loss-2", "trace_id": "loss-2-trace",
               "owner": "alice", "workspace_id": "workspace_alice"}
    with pytest.raises(ExecutorFenced):
        containment.record_loss(
            evidence_root, context=context, executor=stale, loss_cause="executor-loss",
            interrupted_run_id="a" * 32, interrupted_generation="generation-dead",
            attempt=1, recorded_at=1.0)
    assert containment.read(evidence_root, "loss-2") == []
    adapter.close()


def test_duplicate_or_reopened_containment_attempt_is_rejected(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("loss-3", "loss-3-trace", "alice", "workspace_alice")
    evidence_root = adapter._session_root / "byq-lifecycle-evidence"
    executor = adapter._get("loss-3").journal.executor
    context = {"session_id": "loss-3", "trace_id": "loss-3-trace",
               "owner": "alice", "workspace_id": "workspace_alice"}

    def write(*, loss_cause="executor-loss", generation="generation-old", attempt=1, at=1.0):
        return containment.record_loss(
            evidence_root, context=context, executor=executor, loss_cause=loss_cause,
            interrupted_run_id="b" * 32, interrupted_generation=generation,
            attempt=attempt, recorded_at=at)

    first = write()
    assert len(first) == 1
    # An exact re-observation is idempotent, not a second fact.
    assert write(at=99.0) == first
    # A different terminal for the same attempt is a reopen: fail closed.
    with pytest.raises(FencedWrite):
        write(loss_cause="runtime-loss")
    with pytest.raises(FencedWrite):
        write(generation="generation-other")
    # A genuine later loss is a new, allowed attempt.
    second = write(generation="generation-new", attempt=2, at=2.0)
    assert [row["attempt"] for row in second] == [1, 2]
    # A late settlement of the superseded attempt cannot reopen it.
    with pytest.raises(FencedWrite):
        write(loss_cause="runtime-loss", at=3.0)
    adapter.close()


def test_stale_generation_terminal_settlement_is_fenced(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.clear()
    adapter.create_session("loss-4", "loss-4-trace", "alice", "workspace_alice")
    adapter.submit_prompt("loss-4", "running")
    assert FakeHarness.run_started.wait(1.0)
    record = adapter._get("loss-4")
    old_generation = record.runtime_generation
    assert adapter._terminal_fenced(record, old_generation, record.executor_epoch) is False

    adapter.cancel_session("loss-4", "hard")
    resumed = adapter.resume_session("loss-4")
    assert resumed["continuity"] == "interrupted"
    assert record.runtime_generation != old_generation
    # A terminal for the replaced generation can no longer settle state.
    assert adapter._terminal_fenced(record, old_generation, record.executor_epoch) is True
    adapter.close()
    FakeHarness.allow_run.set()


def test_late_success_cannot_overwrite_a_newer_generation(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.clear()
    adapter.create_session("loss-5", "loss-5-trace", "alice", "workspace_alice")
    root = adapter.submit_prompt("loss-5", "running", idempotency_key="loss-5-key")
    assert FakeHarness.run_started.wait(1.0)
    record = adapter._get("loss-5")
    run = record.active_run
    assert run is not None
    adapter.cancel_session("loss-5", "hard")
    adapter.resume_session("loss-5")
    history_before = list(record.history)
    # Release the old, blocked worker: its late success must not reopen or
    # overwrite the new generation's state.
    FakeHarness.allow_run.set()
    wait_for_status(adapter, "loss-5", SessionStatus.READY)
    assert record.history == history_before
    assert record.active_run is None
    assert run.run_id == root
    adapter.close()


def test_terminal_settlement_guard_rejects_duplicate_and_late(adapter: RuntimeAdapter) -> None:
    contract = containment_contract
    contract.assert_terminal_settlement(settled={1: "interrupted"}, write_attempt=2, write_terminal="interrupted")
    with pytest.raises(FencedWrite):
        contract.assert_terminal_settlement(settled={1: "interrupted"}, write_attempt=1, write_terminal="interrupted")
    with pytest.raises(FencedWrite):
        contract.assert_terminal_settlement(settled={1: "interrupted"}, write_attempt=1, write_terminal="completed")
    with pytest.raises(FencedWrite):
        contract.assert_terminal_settlement(settled={2: "completed"}, write_attempt=1, write_terminal="interrupted")


def test_containment_summary_http_boundary(adapter: RuntimeAdapter, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app import main

    FakeHarness.allow_run.clear()
    adapter.create_session("loss-http", "loss-http-trace", "alice", "workspace_alice")
    adapter.submit_prompt("loss-http", "running")
    assert FakeHarness.run_started.wait(1.0)
    _simulate_process_death(adapter)
    restarted = _restart(adapter)
    monkeypatch.setattr(main, "adapter", restarted)
    client = TestClient(main.app)
    try:
        restarted.create_session("loss-http", "loss-http-trace", "alice", "workspace_alice", 1, [])
        body = client.get("/internal/runtime/sessions/loss-http/containment")
        assert body.status_code == 200
        assert body.json()["contained"] is True
        assert body.json()["latest"]["loss_cause"] == "executor-loss"
        # The projection carries no DSH private identity.
        serialized = json.dumps(body.json())
        assert "native_session" not in serialized and "dsh" not in serialized.lower()
    finally:
        restarted.close()
        FakeHarness.allow_run.set()
        adapter.close()
