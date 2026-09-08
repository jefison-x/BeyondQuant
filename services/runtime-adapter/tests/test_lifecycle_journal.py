import json
import hashlib
import subprocess
import sys

import pytest

from app.lifecycle_journal import LifecycleJournal, JournalBusy
from app.contracts import make_workflow_trace_event
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event


CTX = {"session_id": "journal-session", "trace_id": "journal-trace",
       "owner": "alice", "workspace_id": "workspace_alice"}


def event(sequence, kind="session.started", **payload):
    return make_workflow_trace_event(session_id=CTX["session_id"], trace_id=CTX["trace_id"],
        sequence=sequence, kind=kind, source="runtime-adapter", payload={"run_id": "a" * 32, **payload})


def test_terminal_ack_is_exact_durable_and_not_a_public_event(tmp_path):
    journal = LifecycleJournal.claim(tmp_path, CTX, create=True)
    try:
        journal.observe(event(1), generation="one")
        terminal = event(2, "session.result")
        journal.observe(terminal, generation="one")
        receipt = lifecycle_receipt(project_lifecycle_event(terminal, CTX["session_id"], CTX["trace_id"]))
        for invalid in ({**receipt, "sequence": 3}, {**receipt, "sequence": 2.0},
                        {**receipt, "event_sha256": "0" * 64}, {**receipt, "extra": True}):
            with pytest.raises(ValueError):
                journal.acknowledge_terminal(invalid)
            assert journal.state["terminal_acks"] == {}
        journal.acknowledge_terminal(receipt)
        journal.acknowledge_terminal(receipt)
        assert len(journal.state["events"]) == 2
        assert journal.state["sequence"] == 2
        path = journal.path
    finally:
        journal.close()
    assert LifecycleJournal.read(path)["terminal_acks"] == {"a" * 32: receipt}


def test_v1_migration_does_not_invent_acknowledgements(tmp_path):
    journal = LifecycleJournal.claim(tmp_path, CTX, create=True)
    journal.observe(event(1), generation="one")
    journal.observe(event(2, "session.result"), generation="one")
    path = journal.path
    journal.close()
    envelope = json.loads(path.read_text())
    del envelope["state"]["terminal_acks"]
    del envelope["state"]["calls"]
    envelope["schema_version"] = "byq-lifecycle-journal.v1"
    envelope["sha256"] = hashlib.sha256(json.dumps(envelope["state"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    path.write_text(json.dumps(envelope))
    assert LifecycleJournal.read(path)["terminal_acks"] == {}
    # A malformed v2 may not silently use the legacy migration path.
    envelope["schema_version"] = "byq-lifecycle-journal.v2"
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError):
        LifecycleJournal.read(path)


def test_exclusive_owner_and_recovery_preserve_exact_root(tmp_path):
    journal = LifecycleJournal.claim(tmp_path, CTX, create=True)
    journal.observe(event(1), generation="generation-one", prompt=("original-key", "b" * 64))
    with pytest.raises(JournalBusy):
        LifecycleJournal.claim(tmp_path, CTX)
    journal.close()
    recovered = LifecycleJournal.claim(tmp_path, CTX)
    try:
        assert recovered.state["open_root"] is None
        assert recovered.state["events"][-1]["kind"] == "session.closed"
        assert recovered.state["events"][-1]["payload"]["run_id"] == "a" * 32
        assert recovered.state["sequence"] == 2
        assert recovered.receipt("original-key", "b" * 64)["run_id"] == "a" * 32
        with pytest.raises(ValueError):
            recovered.receipt("original-key", "c" * 64)
    finally:
        recovered.close()
    again = LifecycleJournal.claim(tmp_path, CTX)
    assert len(again.state["events"]) == 2
    again.close()


def test_terminal_is_not_overwritten_and_high_watermark_is_durable(tmp_path):
    journal = LifecycleJournal.claim(tmp_path, CTX, create=True)
    journal.observe(event(1), generation="one")
    journal.observe(event(9, "session.result", content="private-answer-must-not-persist"), generation="one")
    journal.observe(event(10, "session.ready"), generation="one")
    journal.close()
    journal = LifecycleJournal.claim(tmp_path, CTX)
    assert journal.state["sequence"] == 10
    assert [row["kind"] for row in journal.state["events"]] == ["session.started", "session.result"]
    assert "private-answer-must-not-persist" not in journal.path.read_text()
    journal.close()


def test_unknown_corrupt_and_foreign_journals_fail_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        LifecycleJournal.claim(tmp_path, CTX)
    journal = LifecycleJournal.claim(tmp_path, CTX, create=True)
    journal.close()
    with pytest.raises(ValueError):
        LifecycleJournal.claim(tmp_path, {**CTX, "owner": "bob"})
    path = tmp_path / "journal-session.json"
    path.write_text("broken")
    with pytest.raises(ValueError):
        LifecycleJournal.claim(tmp_path, CTX)
    assert path.read_text() == "broken"


def test_actual_process_death_releases_owner_lock_without_model_execution(tmp_path):
    script = '''import json,sys,time
from app.lifecycle_journal import LifecycleJournal
from app.contracts import make_workflow_trace_event
ctx=json.loads(sys.argv[2])
j=LifecycleJournal.claim(sys.argv[1],ctx,create=True)
j.observe(make_workflow_trace_event(session_id=ctx['session_id'],trace_id=ctx['trace_id'],sequence=7,
    kind='session.started',source='runtime-adapter',payload={'run_id':'a'*32}),generation='dead-generation')
print('persisted',flush=True)
time.sleep(60)
'''
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), json.dumps(CTX)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "persisted"
        with pytest.raises(JournalBusy):
            LifecycleJournal.claim(tmp_path, CTX)
        child.kill()
        child.wait(timeout=5)
        journal = LifecycleJournal.claim(tmp_path, CTX)
        assert journal.state["sequence"] == 8
        assert journal.state["events"][-1]["kind"] == "session.closed"
        journal.close()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_copy_or_missing_lock_is_not_evidence_of_original_executor_death(tmp_path):
    source = tmp_path / "source"
    journal = LifecycleJournal.claim(source, CTX, create=True)
    journal.observe(event(1), generation="original")
    copy = tmp_path / "copy"
    copy.mkdir()
    for suffix in ("json", "lock"):
        (copy / f"journal-session.{suffix}").write_bytes((source / f"journal-session.{suffix}").read_bytes())
    with pytest.raises(ValueError, match="identity"):
        LifecycleJournal.claim(copy, CTX)
    journal.close()
    (source / "journal-session.lock").unlink()
    with pytest.raises(ValueError, match="identity"):
        LifecycleJournal.claim(source, CTX)
