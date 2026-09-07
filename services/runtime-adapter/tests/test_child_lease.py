from app.child_lease import ChildLease
from app.compat.types import RuntimeObservation
from app.runtime import ActiveRun, RuntimeAdapter
from types import SimpleNamespace


def test_new_progress_renews_inactivity_but_not_hard_limit():
    lease = ChildLease("parent", "child", "call", 0, 0)
    assert lease.observe(1, 170)
    assert not lease.expired(181, 180, 600)
    assert lease.observe(2, 340)
    assert lease.observe(3, 510)
    assert lease.expired(601, 180, 600)


def test_duplicate_out_of_order_missing_and_boolean_sequences_do_not_renew():
    lease = ChildLease("parent", "child", "call", 0, 0)
    assert lease.observe(8, 100)
    for seq in (8, 7, None, True, -1):
        assert not lease.observe(seq, 200)
    assert lease.last_activity_at == 100
    assert lease.expired(281, 180, 600)


def test_sibling_progress_does_not_renew_other_child():
    first = ChildLease("parent", "a", "call-a", 0, 0)
    second = ChildLease("parent", "b", "call-b", 0, 0)
    first.observe(10, 170)
    assert not first.expired(181, 180, 600)
    assert second.expired(181, 180, 600)


def test_adapter_correlates_unique_call_and_rejects_late_and_duplicate_child_events(monkeypatch):
    import app.runtime as runtime
    monkeypatch.setattr(runtime.time, "monotonic", lambda: 170.0)
    run = ActiveRun("run", 0, 0)
    record = SimpleNamespace(runtime_session_id="root")
    run.active_subagent_calls["call"] = 0
    started = RuntimeObservation(kind="subagent.started", parent_session_id="root", child_session_id="child")
    assert RuntimeAdapter._observe_run_observation(record, run, started)
    assert not RuntimeAdapter._observe_run_observation(record, run, started)
    assert run.active_subagent_calls == {}
    event = RuntimeObservation(kind="private.activity", session_id="child", runtime_activity=True, event_sequence=5)
    assert RuntimeAdapter._observe_run_observation(record, run, event)
    assert not RuntimeAdapter._observe_run_observation(record, run, event)
    assert not run.child_leases["child"].expired(181, 180, 600)
    finished = RuntimeObservation(kind="subagent.finished", parent_session_id="root", child_session_id="child")
    assert RuntimeAdapter._observe_run_observation(record, run, finished)
    assert not RuntimeAdapter._observe_run_observation(record, run, event)
    assert not RuntimeAdapter._observe_run_observation(record, run, started)


def test_ambiguous_parallel_calls_and_foreign_parents_cannot_claim_a_lease():
    record = SimpleNamespace(runtime_session_id="root")
    run = ActiveRun("run", 0, 0)
    run.active_subagent_calls.update(a=0, b=0)
    for parent in ("root", "foreign"):
        event = RuntimeObservation(kind="subagent.started", parent_session_id=parent, child_session_id="child")
        assert not RuntimeAdapter._observe_run_observation(record, run, event)
    assert run.child_leases == {}
    assert run.active_subagent_calls == {"a": 0, "b": 0}
