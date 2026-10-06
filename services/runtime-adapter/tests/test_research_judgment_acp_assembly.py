"""Complete-message aggregation for one dedicated judgment root prompt."""

from __future__ import annotations

import queue
from pathlib import Path

from app.compat.dsh_acp import (
    AcpHarness,
    AcpNotification,
    DshAcpCompatibility,
    _Pending,
)

SESSION = "00000000-0000-4000-8000-000000000001"


class _FakeTransport:
    initialized = True

    def __init__(self, notifications, result):
        self._queue: queue.Queue = queue.Queue()
        for notification in notifications:
            self._queue.put(notification)
        self._result = result
        self._sequence = 0
        self.notified: list[tuple[str, dict]] = []

    def next_sequence(self, session_id: str) -> int:
        self._sequence += 1
        return self._sequence

    def next_notification(self, session_id: str, timeout: float):
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def request_async(self, method: str, params: dict) -> _Pending:
        pending = _Pending()
        pending.event.set()
        return pending

    def await_response(self, pending: _Pending, *, timeout: float | None = None):
        return self._result

    def notify(self, method: str, params: dict) -> None:
        self.notified.append((method, params))


def _chunk(message_id: str, text: str, sequence: int) -> AcpNotification:
    return AcpNotification(
        method="session/update",
        params={"sessionId": SESSION, "update": {
            "sessionUpdate": "agent_message_chunk", "messageId": message_id,
            "content": {"type": "text", "text": text}}},
        event_sequence=sequence,
    )


def _run(notifications, result=None, *, content="prompt"):
    transport = _FakeTransport(notifications, result or {"stopReason": "end_turn"})
    harness = AcpHarness(
        provider="deepseek-official", model="deepseek-v4-flash",
        composition=Path("/opt/byq/profiles/byq-research-judgment.patch.yml"),
        session_root=Path("/tmp"), runtime_command=(), environment={},
        process=transport)
    harness.native_session_ids.add(SESSION)
    compatibility = DshAcpCompatibility()
    captured: list = []
    finish = compatibility.run_prepared_prompt(
        compatibility.prepare_prompt(harness, SESSION), content, captured.append)
    messages = [event.params["text"] for event in captured
                if isinstance(event, AcpNotification)
                and event.method == "byq/assistant_message"]
    return finish, messages


def test_multi_chunk_message_is_aggregated_into_one_complete_answer():
    finish, messages = _run([
        _chunk("m1", '{"proposal":', 1),
        _chunk("m1", 'null,', 2),
        _chunk("m1", '"durable_evidence":{"kind":"none"}}', 3),
    ])
    assert finish == "completed"
    # The last streaming chunk is never a standalone answer.
    assert messages == ['{"proposal":null,"durable_evidence":{"kind":"none"}}']


def test_tool_use_turn_delivers_intermediate_and_final_messages_separately():
    finish, messages = _run([
        _chunk("m1", "I'll gather the bounded read-only context.", 1),
        _chunk("m2", '{"proposal":null,"durable_evidence":{"kind":"none"}}', 2),
    ])
    assert finish == "completed"
    assert messages == [
        "I'll gather the bounded read-only context.",
        '{"proposal":null,"durable_evidence":{"kind":"none"}}',
    ]
