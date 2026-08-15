from __future__ import annotations

from pathlib import Path

import pytest

from app.trace_store import TraceConflict, TraceStore


def event(sequence: int, *, kind: str = "session.progress") -> dict[str, object]:
    return {
        "trace_id": "trace-1",
        "session_id": "session-1",
        "sequence": sequence,
        "timestamp": "2026-08-15T00:00:00+00:00",
        "kind": kind,
        "source": "runtime-adapter",
        "payload": {"step": sequence},
    }


def test_trace_store_is_append_only_and_replayable(tmp_path: Path) -> None:
    store = TraceStore(tmp_path)
    assert store.append(event(1, kind="session.ready")) is True
    assert store.append(event(2)) is True
    assert store.append(event(2)) is False
    assert store.read("session-1") == [event(1, kind="session.ready"), event(2)]

    replay = store.stream("session-1", after_sequence=1)
    assert next(replay) == event(2)
    store.close("session-1")
    with pytest.raises(StopIteration):
        next(replay)


def test_trace_store_rejects_gaps_and_reused_sequences(tmp_path: Path) -> None:
    store = TraceStore(tmp_path)
    store.append(event(1))
    with pytest.raises(TraceConflict):
        store.append(event(3))
    with pytest.raises(TraceConflict):
        store.append({**event(1), "payload": {"different": True}})
