"""Current-session Adapter state is live-only and never rehydrates after restart."""
from __future__ import annotations

import hashlib

import pytest

from app.runtime import RuntimeAdapter, SessionConflict, SessionStatus
from packages.contracts.domain_call_admission import call_evidence_receipt, request_evidence
from .test_process_cleanup import FakeHarness, adapter, wait_for_status  # noqa: F401


def _simulate_process_death(runtime: RuntimeAdapter) -> None:
    """Drop the Adapter's current-session map without emitting lifecycle events."""
    with runtime._lock:
        records = list(runtime._sessions.values())
        runtime._sessions.clear()
    for record in records:
        if record.active_run is not None:
            record.active_run.watchdog_stop.set()
            record.active_run = None
        if record.harness is not None:
            runtime._compatibility.close(record.harness)


def test_gateway_restart_attaches_only_to_same_live_adapter_boot(adapter: RuntimeAdapter) -> None:
    created = adapter.create_session("live-attach", "live-trace", "alice", "workspace_alice")
    attached = adapter.attach_live_session(
        "live-attach", "live-trace", "alice", "workspace_alice",
    )
    assert attached["session_id"] == "live-attach"
    assert attached["boot_id"] == created["boot_id"] == adapter.boot_id

    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        with pytest.raises(SessionConflict, match="interrupted"):
            restarted.attach_live_session(
                "live-attach", "live-trace", "alice", "workspace_alice",
            )
    finally:
        restarted.close()
        adapter.close()


def test_adapter_restart_returns_unknown_and_only_accepts_fresh_sequence_zero(
    adapter: RuntimeAdapter,
) -> None:
    FakeHarness.allow_run.set()
    adapter.create_session("restart-live", "restart-trace", "alice", "workspace_alice")
    root = adapter.submit_prompt("restart-live", "synthetic prompt", idempotency_key="restart-prompt-key")
    wait_for_status(adapter, "restart-live", SessionStatus.IDLE)
    old_record = adapter._get("restart-live")
    old_native_session = old_record.runtime_session_id
    old_sequence = old_record.sequence
    digest = hashlib.sha256(b"synthetic prompt").hexdigest()
    assert adapter.reconcile_prompt("restart-live", "restart-prompt-key", digest)["run_id"] == root
    adapter.acknowledge_terminal("restart-live", old_record.terminal_receipts[root])
    _simulate_process_death(adapter)

    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        assert restarted.reconcile_prompt("restart-live", "restart-prompt-key", digest) == {
            "schema_version": "prompt-receipt.v1", "state": "outcome_unknown",
        }
        with pytest.raises(KeyError):
            restarted.submit_prompt("restart-live", "must not replay")
        with pytest.raises(SessionConflict, match="interrupted"):
            restarted.create_session(
                "restart-live", "restart-trace", "alice", "workspace_alice", old_sequence,
            )

        fresh = restarted.create_session(
            "restart-live", "restart-trace", "alice", "workspace_alice", initial_sequence=0,
        )
        new_record = restarted._get("restart-live")
        assert fresh["continuity"] == "fresh"
        assert new_record.sequence == 1
        assert new_record.history[0]["kind"] == "session.ready"
        assert new_record.runtime_session_id != old_native_session
        assert new_record.runtime_session_id.startswith("session-")
        assert restarted.reconcile_prompt("restart-live", "restart-prompt-key", digest)["state"] == "outcome_unknown"
        assert not (restarted._session_root / "byq-lifecycle-evidence").exists()
    finally:
        restarted.close()
        adapter.close()


def test_private_domain_call_ack_retries_after_reap_only_in_same_boot(adapter: RuntimeAdapter) -> None:
    adapter.create_session("private-ack", "private-trace", "alice", "workspace_alice")
    record = adapter._get("private-ack")
    context = {
        "session_id": "private-ack", "trace_id": "private-trace",
        "owner": "alice", "workspace_id": "workspace_alice",
    }
    evidence = {
        "schema_version": "domain-call-observed.v1", "sequence": 1,
        "root_run_id": "a" * 32, "generation": record.runtime_generation,
        "call_id": "private-call-1",
        **request_evidence("byq_strategy_validate", {
            "task_id": "task_private", "agent_run_id": "run_private",
            "idempotency_key": "private-call-key", "strategy": {},
        }, trace_id="private-trace"),
    }
    record.domain_call_evidence.append(evidence)
    record.domain_call_sequence = 1
    adapter.release_session("private-ack")

    page = adapter.domain_call_evidence(context)
    assert page["events"] == [evidence]
    receipt = call_evidence_receipt(evidence)
    assert adapter.acknowledge_domain_call_evidence(context, receipt) == {"receipt": receipt}
    with pytest.raises(KeyError):
        adapter._get("private-ack")
    assert adapter.acknowledge_domain_call_evidence(context, receipt) == {"receipt": receipt}
    assert adapter.domain_call_evidence(context, after_sequence=1) == {
        "schema_version": "domain-call-page.v1", "events": [], "more": False, "idle": True,
    }
    with pytest.raises(ValueError, match="final drained sequence"):
        adapter.domain_call_evidence(context, after_sequence=0)
    with pytest.raises(ValueError, match="final drained sequence"):
        adapter.domain_call_evidence(context, after_sequence=2)
    with pytest.raises(ValueError, match="context mismatch"):
        adapter.domain_call_evidence({**context, "owner": "bob"}, after_sequence=1)

    with pytest.raises(SessionConflict, match="context mismatch"):
        adapter.acknowledge_domain_call_evidence({**context, "owner": "bob"}, receipt)
    restarted = RuntimeAdapter(adapter._compatibility)
    try:
        with pytest.raises(SessionConflict, match="Adapter boot"):
            restarted.acknowledge_domain_call_evidence(context, receipt)
        with pytest.raises(ValueError, match="not live"):
            restarted.domain_call_evidence(context, after_sequence=1)
    finally:
        restarted.close()
        adapter.close()
