"""ADR-0079 R1: stable executor identity, monotonic epoch fencing, v3 migration.

The headline acceptance is that a simulated host reboot (a changed
``/proc/sys/kernel/random/boot_id``) produces ZERO stale sessions. The stable
lease deliberately never consults the boot identity, so the test also makes any
boot-id read raise to prove independence.
"""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app import executor_identity
from app.executor_identity import ExecutorIdentity, ExecutorTakeoverBusy
from app.lifecycle_journal import JournalBusy, JournalIdentityMismatch, LifecycleJournal
from app.contracts import make_workflow_trace_event
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event


def context(session_id: str) -> dict:
    return {"session_id": session_id, "trace_id": f"{session_id}-trace",
            "owner": "alice", "workspace_id": "workspace_alice"}


def event(sequence: int, ctx: dict, kind: str = "session.started", **payload) -> dict:
    return make_workflow_trace_event(
        session_id=ctx["session_id"], trace_id=ctx["trace_id"], sequence=sequence,
        kind=kind, source="runtime-adapter", payload={"run_id": "a" * 32, **payload})


def call_evidence(root: str, generation: str) -> dict:
    return {
        "schema_version": "domain-call-observed.v1", "sequence": 1, "root_run_id": root,
        "generation": generation, "call_id": "private-call-one", "action": "byq_strategy_validate",
        "task_id": "task-one", "agent_run_id": "run-one", "idempotency_key": "key-one",
        "request_sha256": "b" * 64, "input_sha256": "c" * 64,
    }


def test_startup_bootstraps_epoch_once_on_an_empty_volume(tmp_path):
    identity = executor_identity.resolve(tmp_path)
    assert identity.executor_epoch == 1
    assert identity.reason == "bootstrap"
    assert identity.deployment_id == "byq-test-runtime"


def test_process_restart_resumes_without_stale(tmp_path):
    ctx = context("process-restart")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    journal.observe(event(1, ctx), generation="generation-one")
    journal.close()
    # A renewed claim models a new adapter process on the same durable volume.
    resumed = LifecycleJournal.claim(tmp_path, ctx)
    try:
        assert resumed.state["lease_identity"] == resumed.lease_identity
        assert resumed.state["events"][-1]["kind"] == "session.closed"
        assert resumed.state["executor_identity"] == "byq-test-runtime"
    finally:
        resumed.close()


def test_container_restart_resumes_without_stale(tmp_path):
    ctx = context("container-restart")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    journal.observe(event(1, ctx), generation="generation-one")
    journal.observe(event(2, ctx, "session.result"), generation="generation-one")
    journal.close()
    # Container recreation loses memory but keeps the mounted evidence volume.
    resumed = LifecycleJournal.claim(tmp_path, ctx)
    try:
        assert resumed.state["sequence"] == 2
        assert resumed.state["open_root"] is None
    finally:
        resumed.close()


def test_simulated_host_reboot_has_zero_stale_sessions(tmp_path, monkeypatch):
    sessions = [f"reboot-{index:02d}" for index in range(17)]
    contexts = {}
    for session_id in sessions:
        ctx = context(session_id)
        contexts[session_id] = ctx
        journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
        journal.observe(event(1, ctx), generation="generation-one")
        journal.close()

    def boot_id_must_not_be_read(*_args, **_kwargs):
        raise AssertionError("the stable lease must never read the host boot identity")

    # A host reboot changes boot_id, but the stable lease is boot-independent.
    monkeypatch.setattr(executor_identity, "read_boot_id", boot_id_must_not_be_read)
    stale = []
    for session_id in sessions:
        try:
            journal = LifecycleJournal.claim(tmp_path, contexts[session_id])
        except JournalIdentityMismatch:
            stale.append(session_id)
        else:
            journal.close()
    assert stale == []
    assert len(sessions) == 17


def test_second_live_writer_is_rejected(tmp_path):
    ctx = context("live-writer")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    try:
        with pytest.raises(JournalBusy):
            LifecycleJournal.claim(tmp_path, ctx)
    finally:
        journal.close()


def test_explicit_takeover_increments_epoch_and_fences_old_writer(tmp_path):
    ctx = context("takeover")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    try:
        result = LifecycleJournal.takeover_executor_epoch(
            tmp_path, reason="replace executor after storage reassignment", operator="operator-a")
        assert result["previous_epoch"] == 1
        assert result["executor_epoch"] == 2
        assert result["reversible"] is False
        assert result["database_rows_modified"] is False
        # The still-live old-epoch writer is fenced on its very next write.
        with pytest.raises(JournalIdentityMismatch):
            journal.observe(event(1, ctx), generation="generation-one")
    finally:
        journal.close()
    # A stale old-epoch journal cannot be re-claimed without explicit repair.
    with pytest.raises(JournalIdentityMismatch):
        LifecycleJournal.claim(tmp_path, ctx)
    # The exceptional re-anchor path adopts the new epoch and preserves evidence.
    stored = LifecycleJournal.read(tmp_path / f"{ctx['session_id']}.json")["lease_identity"]
    repaired = LifecycleJournal.reanchor_lease(
        tmp_path, ctx["session_id"], expected_stored_lease=stored)
    assert repaired["status"] == "reanchored"
    assert repaired["executor_epoch"] == 2
    reclaimed = LifecycleJournal.claim(tmp_path, ctx)
    try:
        assert reclaimed.state["executor_epoch"] == 2
    finally:
        reclaimed.close()


def test_concurrent_takeover_has_exactly_one_winner(tmp_path):
    executor_identity.resolve(tmp_path)
    with executor_identity.epoch_lock(tmp_path, exclusive=True):
        # Another owner already holds the takeover lock; the second must lose.
        with pytest.raises(ExecutorTakeoverBusy):
            executor_identity.takeover(tmp_path, reason="concurrent takeover attempt")
    # Once released a single takeover proceeds and the epoch advances by exactly one.
    winner = executor_identity.takeover(tmp_path, reason="single winner after release")
    assert winner["previous_epoch"] == 1
    assert winner["executor_epoch"] == 2


def test_missing_epoch_fails_closed_for_stable_journals(tmp_path):
    ctx = context("missing-epoch")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    journal.close()
    executor_identity.state_path(tmp_path).unlink()
    with pytest.raises(JournalIdentityMismatch):
        LifecycleJournal.claim(tmp_path, ctx)


def test_corrupt_epoch_fails_closed(tmp_path):
    ctx = context("corrupt-epoch")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    journal.close()
    executor_identity.state_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(JournalIdentityMismatch):
        LifecycleJournal.claim(tmp_path, ctx)


def test_deployment_identity_mismatch_fails_closed(tmp_path):
    ctx = context("deployment-mismatch")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    journal.close()
    other = ExecutorIdentity(
        "byq-other-runtime", "dsh-0.1.2rc1", "byq-test-sessions", 1,
        executor_identity.state_path(tmp_path), "test")
    with pytest.raises(JournalIdentityMismatch):
        LifecycleJournal.claim(tmp_path, ctx, executor=other)


def test_legacy_v3_journal_migrates_to_v4_preserving_all_evidence(tmp_path):
    ctx = context("legacy-v3")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    journal.observe(event(1, ctx), generation="generation-one", prompt=("original-key", "b" * 64))
    journal.observe_call(call_evidence("a" * 32, "generation-one"))
    terminal = event(2, ctx, "session.result")
    journal.observe(terminal, generation="generation-one")
    receipt = lifecycle_receipt(project_lifecycle_event(terminal, ctx["session_id"], ctx["trace_id"]))
    journal.acknowledge_terminal(receipt)
    snapshot = copy.deepcopy(journal.state)
    path = journal.path
    journal.close()

    # Downgrade the stored envelope to a legacy boot-bound v3 journal.
    envelope = json.loads(path.read_text(encoding="utf-8"))
    del envelope["state"]["executor_identity"]
    del envelope["state"]["executor_epoch"]
    envelope["state"]["lease_identity"] = "f" * 64
    envelope["schema_version"] = "byq-lifecycle-journal.v3"
    encoded = json.dumps(envelope["state"], sort_keys=True, separators=(",", ":")).encode()
    envelope["sha256"] = hashlib.sha256(encoded).hexdigest()
    path.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    migrated = LifecycleJournal.claim(tmp_path, ctx)
    try:
        assert migrated.state["executor_identity"] == "byq-test-runtime"
        assert migrated.state["executor_epoch"] == 1
        assert migrated.state["lease_identity"] == migrated.lease_identity
        for field in ("context", "sequence", "open_root", "events", "prompts", "terminal_acks", "calls"):
            assert migrated.state[field] == snapshot[field]
        assert migrated.state["calls"][0]["call_id"] == "private-call-one"
    finally:
        migrated.close()
    # The migrated journal claims cleanly on disk as a stable v4 journal.
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "byq-lifecycle-journal.v4"
    again = LifecycleJournal.claim(tmp_path, ctx)
    try:
        assert again.state["sequence"] == snapshot["sequence"]
    finally:
        again.close()
