"""ADR-0084 business-recovery admission at the Runtime Adapter boundary.

These tests exercise the real ``RuntimeAdapter`` state machine plus the real
BYQ lifecycle journal and containment ledger. The snapshot digest is computed
from the actual append-only call evidence, and fault injection proves that a
tail append, an idle flip, a tampered digest, a mismatched containment record and
a stale target are all rejected before any new root/generation is created.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from packages.contracts import business_recovery as contract
from app import business_recovery as recovery
from app import containment
from app.runtime import RuntimeAdapter
from .test_process_cleanup import FakeHarness, release_compatibility
from .test_session_rehydration import _simulate_process_death

_ROOT_IDENTITY_LINE = "X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID\n"


def _root_scoped_adapter(tmp_path: Path, monkeypatch) -> RuntimeAdapter:
    source = ("- id: mcp-byq\n  config:\n    headers:\n      "
              + _ROOT_IDENTITY_LINE)
    profile = tmp_path / "product.yml"
    profile.write_text(source, encoding="utf-8")
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({
        "root_identity_contract": "byq-root-process.v1",
        "composition_hash": "sha256:" + hashlib.sha256(source.encode()).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(profile))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(identity))
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_F6_EXECUTOR_ENABLED", "1")
    adapter = RuntimeAdapter(release_compatibility(tmp_path))
    _qualify(adapter, monkeypatch)
    return adapter


def _qualify(adapter: RuntimeAdapter, monkeypatch) -> None:
    monkeypatch.setattr(adapter, "continuation_qualified", lambda record: True)
    monkeypatch.setattr(adapter, "_resolve_model", lambda **kwargs: {
        "provider": "deepseek-official", "model": "deepseek-v4-flash", "api_key": "synthetic-only"})


def _lost_session(tmp_path: Path, monkeypatch) -> tuple[RuntimeAdapter, dict]:
    """Produce a truthful executor-loss containment fact on a real journal."""

    FakeHarness.reset()
    adapter = _root_scoped_adapter(tmp_path, monkeypatch)
    adapter.create_session("rec-1", "rec-trace", "alice", "workspace_alice")
    adapter.submit_prompt("rec-1", "synthetic long research")
    assert FakeHarness.run_started.wait(2.0)
    record = adapter._get("rec-1")
    durable_sequence = record.sequence
    _simulate_process_death(adapter)
    restarted = RuntimeAdapter(adapter._compatibility)
    _qualify(restarted, monkeypatch)
    restarted.create_session("rec-1", "rec-trace", "alice", "workspace_alice", durable_sequence, [])
    recorded = restarted.containment_summary("rec-1")["latest"]
    # The Gateway acknowledges the lost root's durable terminal before a
    # rearm, exactly as the real continuation consumer does.
    record = restarted._get("rec-1")
    restarted.acknowledge_terminal("rec-1", record.terminal_receipts[recorded["interrupted_run_id"]])
    return restarted, recorded


def _carrier(recorded: dict, *, reservation_id: str, snapshot: dict, digest: str | None = None,
             run_id: str | None = None, epoch: int | None = None) -> dict:
    run = run_id or recorded["interrupted_run_id"]
    trigger = contract.trigger_key(reservation_id, run, recorded["interrupted_generation"],
                                   recorded["attempt"], epoch if epoch is not None else recorded["executor_epoch"])
    return {
        "attempt_key": contract.attempt_key(trigger, 1),
        "ordinal": 1,
        "trigger_key": trigger,
        "interrupted_run_id": run,
        "interrupted_generation": recorded["interrupted_generation"],
        "containment_attempt": recorded["attempt"],
        "interrupted_executor_epoch": epoch if epoch is not None else recorded["executor_epoch"],
        "snapshot_tail_sequence": snapshot["tail_sequence"],
        "snapshot_digest": digest if digest is not None else snapshot["digest"],
    }


def _reservation(carrier: dict, *, token_limit: int | None = None) -> dict:
    from datetime import datetime, timedelta, timezone
    return {
        "schema_version": "task-continuation-reservation.v1",
        "reservation_id": "continuation_" + "a" * 32,
        "task_id": "task_" + "b" * 32,
        "owner": "alice", "workspace_id": "workspace_alice",
        "token_limit": token_limit or (contract.MODEL_CALL_FLOOR * 2),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
        "recovery_attempt": carrier,
    }


def test_snapshot_is_the_real_session_global_call_closure(tmp_path, monkeypatch):
    adapter, _ = _lost_session(tmp_path, monkeypatch)
    try:
        state = adapter._get("rec-1").journal.state
        snapshot = recovery.snapshot_from_state(state)
        assert snapshot["idle"] is True
        assert snapshot["tail_sequence"] == len(state["calls"])
        assert snapshot["digest"] == contract.canonical_snapshot_digest(
            session_id="rec-1", trace_id="rec-trace",
            tail_sequence=snapshot["tail_sequence"], calls=state["calls"])
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_recovery_submits_and_installs_a_new_target_generation(tmp_path, monkeypatch):
    adapter, recorded = _lost_session(tmp_path, monkeypatch)
    try:
        record = adapter._get("rec-1")
        snapshot = recovery.snapshot_from_state(record.journal.state)
        carrier = _carrier(recorded, reservation_id="continuation_" + "a" * 32, snapshot=snapshot)
        reservation = _reservation(carrier)
        FakeHarness.allow_run.set()
        run = adapter.submit_prompt("rec-1", "recover", idempotency_key=carrier["attempt_key"],
                                    conversation_context=[], continuation_budget=reservation)
        receipt = adapter.recovery_receipt("rec-1", carrier["attempt_key"])
        assert receipt["run_id"] == run
        assert receipt["target_executor_epoch"] == record.executor_epoch
        assert receipt["target_generation"] == record.runtime_generation
        assert receipt["attempt_key"] == carrier["attempt_key"]
        assert receipt["snapshot_digest"] == snapshot["digest"]
        # A retry under the same attempt key reuses the same accepted run.
        assert adapter.submit_prompt("rec-1", "recover", idempotency_key=carrier["attempt_key"],
                                     conversation_context=[], continuation_budget=reservation) == run
        started = [event for event in record.history
                   if event["kind"] == "session.started" and event["payload"]["run_id"] == run]
        assert len(started) == 1
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_tampered_digest_and_changed_tail_fail_closed(tmp_path, monkeypatch):
    adapter, recorded = _lost_session(tmp_path, monkeypatch)
    try:
        record = adapter._get("rec-1")
        snapshot = recovery.snapshot_from_state(record.journal.state)
        reservation_id = "continuation_" + "a" * 32
        tampered = _carrier(recorded, reservation_id=reservation_id, snapshot=snapshot, digest="f" * 64)
        with pytest.raises(contract.RecoveryRejected) as exc:
            recovery.admission_precheck(journal_state=record.journal.state, carrier=tampered,
                reservation_id=reservation_id,
                evidence_root=adapter._session_root / "byq-lifecycle-evidence",
                session_id="rec-1")
        assert exc.value.code in {"snapshot_digest_changed", "snapshot_tail_changed"}
        # An appended call after the carrier was issued invalidates the anchor.
        changed_state = json.loads(json.dumps(record.journal.state))
        changed_state["calls"].append({
            "schema_version": "domain-call-observed.v1", "sequence": 1, "root_run_id": "a" * 32,
            "generation": "generation-1", "call_id": "call-1", "action": "byq_strategy_validate",
            "task_id": "task_" + "b" * 32, "agent_run_id": "c" * 32,
            "idempotency_key": "idem-1", "request_sha256": "d" * 64, "input_sha256": "e" * 64})
        with pytest.raises(contract.RecoveryRejected) as exc:
            recovery.verify_snapshot_against_state(
                _carrier(recorded, reservation_id=reservation_id, snapshot=snapshot), changed_state)
        assert exc.value.code in {"invalid_snapshot_input", "snapshot_tail_changed"}
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_idle_flip_and_containment_mismatch_fail_closed(tmp_path, monkeypatch):
    adapter, recorded = _lost_session(tmp_path, monkeypatch)
    try:
        record = adapter._get("rec-1")
        reservation_id = "continuation_" + "a" * 32
        snapshot = recovery.snapshot_from_state(record.journal.state)
        carrier = _carrier(recorded, reservation_id=reservation_id, snapshot=snapshot)
        # An open root at admission is not a closed snapshot.
        busy = json.loads(json.dumps(record.journal.state))
        busy["open_root"] = {"root_run_id": "a" * 32, "generation": "generation-1"}
        with pytest.raises(contract.RecoveryRejected) as exc:
            recovery.verify_snapshot_against_state(carrier, busy)
        assert exc.value.code == "snapshot_not_idle"
        # A source loss that does not match the durable containment record fails.
        wrong = _carrier(recorded, reservation_id=reservation_id, snapshot=snapshot, run_id="f" * 32)
        with pytest.raises(contract.RecoveryRejected) as exc:
            recovery.verify_carrier(wrong, reservation_id=reservation_id,
                evidence_root=adapter._session_root / "byq-lifecycle-evidence", session_id="rec-1")
        assert exc.value.code == "containment_mismatch"
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_interrupted_epoch_is_not_the_live_target_and_stale_targets_are_fenced(tmp_path, monkeypatch):
    adapter, recorded = _lost_session(tmp_path, monkeypatch)
    try:
        record = adapter._get("rec-1")
        snapshot = recovery.snapshot_from_state(record.journal.state)
        carrier = _carrier(recorded, reservation_id="continuation_" + "a" * 32, snapshot=snapshot)
        receipt = recovery.accepted_receipt(
            carrier, reservation_id="continuation_" + "a" * 32, run_id="d" * 32,
            target_executor_epoch=record.executor_epoch, target_generation=record.runtime_generation)
        # The interrupted (source) epoch never has to equal the live target epoch.
        assert carrier["interrupted_executor_epoch"] == recorded["executor_epoch"]
        recovery.assert_target_current(receipt=receipt, live_executor_epoch=record.executor_epoch,
                                       live_generation=record.runtime_generation)
        with pytest.raises(contract.RecoveryRejected) as exc:
            recovery.assert_target_current(receipt=receipt, live_executor_epoch=record.executor_epoch + 1,
                                           live_generation=record.runtime_generation)
        assert exc.value.code == "stale_target_epoch"
        with pytest.raises(contract.RecoveryRejected) as exc:
            recovery.assert_target_current(receipt=receipt, live_executor_epoch=record.executor_epoch,
                                           live_generation="generation-other")
        assert exc.value.code == "stale_target_generation"
        # A late terminal from the replaced generation cannot settle state.
        adapter.resume_session("rec-1")
        old_generation = carrier["interrupted_generation"]
        assert adapter._terminal_fenced(record, old_generation, record.executor_epoch) is True
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_recovery_reservation_rejects_a_carrier_with_extra_fields(tmp_path, monkeypatch):
    from app.continuation_budget import validate_reservation
    adapter, recorded = _lost_session(tmp_path, monkeypatch)
    try:
        record = adapter._get("rec-1")
        snapshot = recovery.snapshot_from_state(record.journal.state)
        carrier = _carrier(recorded, reservation_id="continuation_" + "a" * 32, snapshot=snapshot)
        carrier["target_executor_epoch"] = 2
        with pytest.raises(contract.RecoveryRejected) as exc:
            validate_reservation(_reservation(carrier), owner="alice", workspace="workspace_alice")
        assert exc.value.code == "invalid_carrier"
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_envelope_blocks_new_key_actions_and_unknown_reads(tmp_path, monkeypatch):
    occurred = [{"action": "byq_strategy_validate", "task_id": "task_x", "idempotency_key": "idem-1",
                 "request_sha256": "a" * 64, "input_sha256": "b" * 64}]
    exact = contract.admission_envelope(read_only=False, replayed_calls=occurred, occurred_calls=occurred)
    assert exact["eligible"] is True and exact["mode"] == "exact_reuse"
    new_key = contract.admission_envelope(read_only=False, replayed_calls=[
        {"action": "byq_ml_strategy_create", "task_id": "task_x", "idempotency_key": "idem-1",
         "request_sha256": "a" * 64, "input_sha256": "b" * 64}], occurred_calls=occurred)
    assert new_key["eligible"] is False and "new_key_action:byq_ml_strategy_create" in new_key["reasons"]
    altered = contract.admission_envelope(read_only=False, replayed_calls=[
        {"action": "byq_strategy_validate", "task_id": "task_x", "idempotency_key": "idem-1",
         "request_sha256": "c" * 64, "input_sha256": "b" * 64}], occurred_calls=occurred)
    assert altered["eligible"] is False and "not_original_call:byq_strategy_validate" in altered["reasons"]


def test_budget_decision_is_tri_state_and_never_double_deducts():
    # Numeric example from the merged design: R_available is 40, not 10, but it is
    # still below the qualified model-call floor so it is blocked (not eligible).
    below = contract.budget_decision(
        permission_token_limit=100, other_settled=30, other_unresolved=0,
        r_token_limit=60, cum_exact=20, model_call_floor=1_000_000)
    assert below == {"decision": "blocked", "reason": "below_model_call_floor", "r_available": None}
    eligible = contract.budget_decision(
        permission_token_limit=10_000_000, other_settled=30, other_unresolved=0,
        r_token_limit=2_000_000, cum_exact=20, model_call_floor=1_000_000)
    assert eligible["decision"] == "eligible" and eligible["r_available"] == 2_000_000 - 20
    assert contract.budget_decision(
        permission_token_limit=100, other_settled=30, other_unresolved=0,
        r_token_limit=60, cum_exact=None, model_call_floor=1)["decision"] == "paused"
    assert contract.budget_decision(
        permission_token_limit=100, other_settled=30, other_unresolved=0,
        r_token_limit=80, cum_exact=0, model_call_floor=1)["reason"] == "grant_invariant_violated"
    assert contract.budget_decision(
        permission_token_limit=10_000_000, other_settled=0, other_unresolved=0,
        r_token_limit=2_000_000, cum_exact=0, model_call_floor=1,
        evidence_conflict=True)["reason"] == "authoritative_evidence_conflict"


def test_containment_summary_exposes_idle_recovery_anchor(tmp_path, monkeypatch):
    adapter, recorded = _lost_session(tmp_path, monkeypatch)
    try:
        summary = adapter.containment_summary("rec-1")
        anchor = summary["recovery_anchor"]
        state = adapter._get("rec-1").journal.state
        assert anchor["idle"] is True
        assert anchor["snapshot_tail_sequence"] == len(state["calls"])
        assert anchor["snapshot_digest"] == contract.canonical_snapshot_digest(
            session_id="rec-1", trace_id="rec-trace",
            tail_sequence=len(state["calls"]), calls=state["calls"])
        # A missing durable journal yields no anchor, never a fabricated one.
        assert adapter._recovery_anchor(adapter._session_root / "byq-lifecycle-evidence",
                                        "unknown-session") is None
    finally:
        adapter.close()
        FakeHarness.allow_run.set()


def test_prompt_route_returns_the_accepted_recovery_target(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    adapter, recorded = _lost_session(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "adapter", adapter)
    client = TestClient(main.app)
    try:
        record = adapter._get("rec-1")
        snapshot = recovery.snapshot_from_state(record.journal.state)
        # A tampered snapshot is rejected by the route with a closed reason.
        tampered = _carrier(recorded, reservation_id="continuation_" + "a" * 32,
                            snapshot=snapshot, digest="f" * 64)
        rejected = client.post("/internal/runtime/sessions/rec-1/prompt", json={
            "content": "recover", "idempotency_key": tampered["attempt_key"],
            "conversation_context": [], "continuation_budget": _reservation(tampered)})
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "snapshot_digest_changed"
        carrier = _carrier(recorded, reservation_id="continuation_" + "a" * 32, snapshot=snapshot)
        FakeHarness.allow_run.set()
        body = client.post("/internal/runtime/sessions/rec-1/prompt", json={
            "content": "recover", "idempotency_key": carrier["attempt_key"],
            "conversation_context": [], "continuation_budget": _reservation(carrier)})
        assert body.status_code == 202, body.text
        payload = body.json()
        assert payload["accepted"] is True
        assert payload["recovery"]["attempt_key"] == carrier["attempt_key"]
        assert payload["recovery"]["target_executor_epoch"] == record.executor_epoch
        assert payload["recovery"]["target_generation"] == record.runtime_generation
    finally:
        adapter.close()
        FakeHarness.allow_run.set()
