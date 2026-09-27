"""Current-v4 stable executor identity and monotonic epoch fencing.

The headline acceptance is that a simulated host reboot (a changed
``/proc/sys/kernel/random/boot_id``) produces ZERO stale sessions. The stable
lease deliberately never consults the boot identity, so the test also makes any
boot-id read raise to prove independence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

import pytest

from app import executor_identity
from app.executor_identity import ExecutorIdentity, ExecutorTakeoverBusy
from app.lifecycle_journal import JournalBusy, JournalIdentityMismatch, LifecycleJournal
from app.contracts import make_workflow_trace_event


def context(session_id: str) -> dict:
    return {"session_id": session_id, "trace_id": f"{session_id}-trace",
            "owner": "alice", "workspace_id": "workspace_alice"}


def event(sequence: int, ctx: dict, kind: str = "session.started", **payload) -> dict:
    return make_workflow_trace_event(
        session_id=ctx["session_id"], trace_id=ctx["trace_id"], sequence=sequence,
        kind=kind, source="runtime-adapter", payload={"run_id": "a" * 32, **payload})


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
    # A journal from the prior epoch remains fail-closed after takeover.
    with pytest.raises(JournalIdentityMismatch):
        LifecycleJournal.claim(tmp_path, ctx)


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


@pytest.mark.parametrize("schema", [
    "byq-lifecycle-journal.v1",
    "byq-lifecycle-journal.v2",
    "byq-lifecycle-journal.v3",
    "unknown-journal-schema",
])
def test_missing_epoch_never_bootstraps_over_existing_journal(tmp_path, schema):
    ctx = context("existing-journal")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    path = journal.path
    journal.close()

    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["schema_version"] = schema
    path.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    before = path.read_bytes()
    epoch_path = executor_identity.state_path(tmp_path)
    epoch_path.unlink()

    with pytest.raises(JournalIdentityMismatch, match="epoch state is missing"):
        LifecycleJournal.claim(tmp_path, ctx)
    assert not epoch_path.exists()
    assert path.read_bytes() == before


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


def test_takeover_cannot_interleave_between_validation_and_durable_write(tmp_path, monkeypatch):
    """The epoch shared lock is held across validation AND persistence.

    The durable replacement is held open while a concurrent takeover is
    attempted. Pre-fix the shared check lock was already released before the
    write, so the takeover completed inside the window and the mid-write
    assertion failed. Post-fix the takeover blocks on the epoch lock until the
    write is durable, then advances the epoch and fences the old writer.
    """

    ctx = context("lease-toctou")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    entered = threading.Event()
    release = threading.Event()
    attempting = threading.Event()
    takeover_done = threading.Event()
    takeover_refused = threading.Event()
    errors: list[BaseException] = []
    original_replace = os.replace

    def guarded_replace(src, dst, *args, **kwargs):
        if Path(dst) == journal.path and not entered.is_set():
            entered.set()
            if not release.wait(timeout=10):
                raise AssertionError("durable write was never released")
        return original_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", guarded_replace)

    def write():
        try:
            journal.observe(event(1, ctx), generation="generation-one")
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def take():
        attempting.set()
        try:
            LifecycleJournal.takeover_executor_epoch(
                tmp_path, reason="concurrent takeover during evidence write")
            takeover_done.set()
        except ExecutorTakeoverBusy:
            takeover_refused.set()
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    writer = threading.Thread(target=write)
    taker = threading.Thread(target=take)
    try:
        writer.start()
        assert entered.wait(timeout=10), "the write never reached os.replace"
        taker.start()
        assert attempting.wait(timeout=10)
        time.sleep(0.5)
        assert not takeover_done.is_set(), (
            "takeover completed inside the validation->durable-write window")
        release.set()
        writer.join(timeout=10)
        taker.join(timeout=10)
        assert not writer.is_alive() and not taker.is_alive()
        assert errors == []
        # The takeover was refused while the fenced write held the epoch lock.
        assert takeover_refused.is_set() and not takeover_done.is_set()
        # Once the durable write released the lock the takeover wins exactly once.
        winner = LifecycleJournal.takeover_executor_epoch(
            tmp_path, reason="takeover after the fenced write becomes durable")
        assert winner["executor_epoch"] == 2
        # The evidence write completed BEFORE the takeover: the epoch change
        # could not interleave with the fenced persistence.
        persisted = LifecycleJournal.read(journal.path)
        assert persisted["executor_epoch"] == 1
        assert persisted["sequence"] == 1
        with pytest.raises(JournalIdentityMismatch):
            journal.observe(event(2, ctx, "session.result"), generation="generation-one")
    finally:
        release.set()
        writer.join(timeout=10)
        taker.join(timeout=10)
        journal.close()


def test_old_epoch_writer_is_fenced_after_takeover(tmp_path):
    ctx = context("old-epoch-writer")
    journal = LifecycleJournal.claim(tmp_path, ctx, create=True)
    try:
        LifecycleJournal.takeover_executor_epoch(
            tmp_path, reason="replace executor while the old writer is still live")
        # Both the direct persistence primitive and a normal observation fail
        # closed; the stale writer can never re-establish ownership.
        with pytest.raises(JournalIdentityMismatch):
            journal._save(journal.state)
        with pytest.raises(JournalIdentityMismatch):
            journal.observe(event(1, ctx), generation="generation-one")
    finally:
        journal.close()
