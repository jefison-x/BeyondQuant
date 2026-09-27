"""No-replay continuation guards for legacy recovery rows."""
import os

import pytest
from fastapi import HTTPException


@pytest.mark.parametrize("payload", [
    {"reservation_id": "continuation_" + "a" * 32, "recovery": {}},
    {"reservation_id": "continuation_" + "a" * 32, "attempt_key": "recovery_" + "b" * 32},
])
def test_dispatch_route_rejects_recovery_carrier_fields(monkeypatch, payload):
    from app import main

    monkeypatch.setattr(main, "_continuation_consumer_context", lambda request: {})
    with pytest.raises(HTTPException) as error:
        main.dispatch_task_continuation("task_" + "c" * 32, payload, request=None)
    assert error.value.status_code == 422


def test_receipt_route_rejects_recovery_target_fields(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "_continuation_consumer_context", lambda request: {})
    with pytest.raises(HTTPException) as error:
        main.record_task_continuation_receipt("task_" + "c" * 32, {
            "reservation_id": "continuation_" + "a" * 32,
            "status": "accepted", "run_id": "d" * 32,
            "attempt_key": "recovery_" + "b" * 32,
            "target_executor_epoch": 2, "target_generation": "generation-target",
        }, request=None)
    assert error.value.status_code == 422


def test_legacy_recovery_roots_remain_blocked_at_domain_claim_gate(monkeypatch):
    from app import domain_call_admission as admission

    rows = [{"task_id": "task_legacy", "continuation_budget": [{"recovery_attempts": [
        {"status": "accepted", "run_id": "e" * 32,
         "envelope_mode": "exact_reuse", "allowed_calls": [["byq_strategy_validate"]]},
    ]}]}]
    monkeypatch.setattr(admission, "execute", lambda *args, **kwargs: rows)
    assert admission.DomainCallEvidenceMixin._recovery_claim_gate(None,
        owner="alice", workspace="workspace-a", session="session-a", root="e" * 32
    ) == "recovery_envelope_violation"

    # The prior exact-reuse exception is gone: this legacy root is denied even
    # when its old row lists a matching call. A pending old attempt also stays
    # fail-closed until an explicit domain reconciliation path exists.
    rows[0]["continuation_budget"][0]["recovery_attempts"] = [{
        "status": "reserved", "run_id": None,
    }]
    assert admission.DomainCallEvidenceMixin._recovery_claim_gate(None,
        owner="alice", workspace="workspace-a", session="session-a", root="f" * 32
    ) == "recovery_envelope_violation"


@pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")
def test_legacy_reserved_row_with_original_run_id_is_not_dispatchable(monkeypatch):
    monkeypatch.setenv("BYQ_F6_EXECUTOR_ENABLED", "1")
    from tests.test_research_continuation import setup_permission

    store, task, context, payload = setup_permission()
    original_run = "b" * 32
    try:
        store.create_continuation_permission(task, {**payload, "token_limit": 12_000_000},
            trusted_context=context)
        reservation_id = store.reserve_continuation_budget(task, trusted_context=context,
            grant_version=1, event_key="event-no-replay", input_sha256="a" * 64,
            token_limit=6_000_000)["reservation_id"]
        store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status="accepted", run_id=original_run,
            charged_tokens=1_048_584)

        ledger = store._fetch_one(
            "SELECT continuation_budget FROM research_tasks WHERE task_id=:task", {"task": task}
        )["continuation_budget"]
        row = ledger[0]
        row.update(status="reserved", next_attempt_at="2000-01-01T00:00:00+00:00",
            next_reconcile_at="2000-01-01T00:00:00+00:00",
            recovery_attempts=[{"status": "accepted", "run_id": "c" * 32}])
        store._execute("UPDATE research_tasks SET continuation_budget=:budget WHERE task_id=:task",
            {"budget": ledger, "task": task})

        with store._transaction() as connection:
            task_row, conversation = store._continuation_task(connection, task, context, human=False)
            intent = store._continuation_intent(task_row, conversation, task_row["continuation_budget"][0])
        assert intent["status"] == "intent"
        assert intent["receipt"]["status"] == "reserved"
        assert intent["receipt"]["run_id"] == original_run
        assert intent["may_dispatch"] is False
        assert "recovery_attempt" not in intent["reservation"]
        assert store.claim_continuation_dispatch(task, reservation_id,
            trusted_context=context) == {"dispatch": False}

        # Reconciliation can bind the exact original acceptance/known charge;
        # it still does not turn the row into another dispatch.
        accepted = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status="accepted", run_id=original_run,
            charged_tokens=1_048_584)
        assert accepted["run_id"] == original_run
        assert accepted["charged_tokens"] == 1_048_584
        assert store.claim_continuation_dispatch(task, reservation_id,
            trusted_context=context) == {"dispatch": False}

        # Unknown outcome keeps the liability and stays non-dispatchable.
        unknown = store.record_continuation_receipt(task, trusted_context=context,
            reservation_id=reservation_id, status="outcome_unknown")
        assert unknown["charged_tokens"] == 1_048_584
        assert store.claim_continuation_dispatch(task, reservation_id,
            trusted_context=context) == {"dispatch": False}
    finally:
        store.close()
