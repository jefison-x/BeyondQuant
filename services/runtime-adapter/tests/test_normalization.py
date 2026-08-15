from deepseek_harness import Notification

from app.normalization import normalize_dsh_notification


def test_session_status_is_a_byq_owned_event() -> None:
    event = normalize_dsh_notification(
        Notification(
            method="session.status",
            payload={"sessionId": "s-1", "status": "idle"},
        ),
        trace_id="t-1",
        session_id="s-1",
        sequence=4,
    )

    assert event == {
        "trace_id": "t-1",
        "session_id": "s-1",
        "sequence": 4,
        "timestamp": event["timestamp"],
        "kind": "session.status",
        "source": "dsh",
        "payload": {"status": "idle"},
    }


def test_session_event_does_not_forward_raw_event_data() -> None:
    event = normalize_dsh_notification(
        Notification(
            method="session.event",
            payload={
                "sessionId": "s-1",
                "event": {
                    "type": "turn/end",
                    "data": {"reason": {"kind": "completed"}, "private": "not-forwarded"},
                },
            },
        ),
        trace_id="t-1",
        session_id="s-1",
        sequence=5,
    )

    assert event is not None
    assert event["kind"] == "turn.completed"
    assert event["payload"] == {"reason": "completed"}
    assert "event" not in event
