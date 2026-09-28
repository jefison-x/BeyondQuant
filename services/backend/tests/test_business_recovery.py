"""Reject retired recovery fields on continuation routes."""
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
