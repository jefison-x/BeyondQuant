from types import SimpleNamespace

from deepseek_harness import Notification

from app.compat import Dsh011Compatibility


def notification(event_type: str, data: dict, *, session_id: str = "root") -> Notification:
    return Notification(
        method="session.event",
        payload={"sessionId": session_id, "event": {"type": event_type, "data": data}},
    )


def test_observation_drops_reasoning_arguments_and_raw_payload() -> None:
    compatibility = Dsh011Compatibility()
    assistant = compatibility.observe(
        notification("assistant/message", {
            "message": {"id": "message-1", "content": [
                {"type": "reasoning", "text": "private-chain"},
                {"type": "text", "text": "公开回答"},
            ]},
        }), root_session_id="root",
    )
    tool = compatibility.observe(
        notification("tool/call", {
            "callId": "call-1", "name": "byq_market_daily",
            "arguments": {"secret": "must-not-cross"},
        }), root_session_id="root",
    )

    assert assistant.answer_text == "公开回答"
    assert "private-chain" not in repr(assistant)
    assert tool.call_id == "call-1"
    assert "must-not-cross" not in repr(tool)


def test_tool_bearing_message_has_no_public_answer_candidate() -> None:
    observed = Dsh011Compatibility().observe(
        notification("assistant/message", {
            "message": {"id": "message-tool", "content": [
                {"type": "text", "text": "internal narration"},
                {"type": "tool-call", "name": "byq_market_daily", "arguments": {}},
            ]},
        }), root_session_id="root",
    )

    assert observed.kind == "assistant.message"
    assert observed.answer_text is None


def test_error_and_unknown_turn_reasons_fail_closed() -> None:
    compatibility = Dsh011Compatibility()
    error = compatibility.observe(
        notification("turn/end", {"reason": {"kind": "error"}}), root_session_id="root",
    )
    unknown = compatibility.observe(
        notification("turn/end", {"reason": {"kind": "future-value"}}), root_session_id="root",
    )

    assert error.terminal_reason == "failed"
    assert unknown.terminal_reason == "failed"


def test_descendant_activity_is_private_and_never_root_projectable() -> None:
    observed = Dsh011Compatibility().observe(
        notification(
            "assistant/chunk", {"chunk": {"type": "reasoning-delta", "text": "child-private"}},
            session_id="child",
        ), root_session_id="root",
    )

    assert observed.runtime_activity is True
    assert observed.root_session is False
    assert "child-private" not in repr(observed)


def test_public_sdk_lifecycle_is_called_through_compatibility() -> None:
    calls: list[object] = []

    class Session:
        def run(self, content: str, *, on_notification: object) -> SimpleNamespace:
            calls.extend([content, on_notification])
            return SimpleNamespace(finish_reason="completed")

    class Harness:
        def start(self) -> None:
            calls.append("start")

        def start_session(self, session_id: str) -> Session:
            calls.append(session_id)
            return Session()

        def close(self) -> None:
            calls.append("close")

    harness = Harness()
    compatibility = Dsh011Compatibility()
    compatibility.start(harness)
    reason = compatibility.prompt(harness, "root", "hello", lambda _: None)
    compatibility.close(harness)

    assert calls[0:3] == ["start", "root", "hello"]
    assert reason == "completed"
    assert calls[-1] == "close"
