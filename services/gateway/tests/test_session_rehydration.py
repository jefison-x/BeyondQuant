"""Gateway trace continuity for a surviving live Adapter session.

Gateway recreation may attach to an existing in-memory Adapter session and
reopen its trace. Adapter process loss never rebinds the old Agent session.
Real gaps, backwards and reused sequences must still fail.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import main
from app.trace_store import TraceConflict, TraceStore


def event(session_id: str, trace_id: str, sequence: int, kind: str, payload: dict) -> dict:
    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "sequence": sequence,
        "timestamp": "2026-09-08T00:00:00+00:00",
        "source": "runtime-adapter",
        "kind": kind,
        "payload": payload,
    }


def test_reopened_trace_continues_from_persisted_sequence(tmp_path: Path) -> None:
    store = TraceStore(tmp_path)
    for sequence in range(1, 6):
        store.append(event("session-1", "trace-1", sequence, "session.progress", {"step": sequence}))
    store.close("session-1")

    # A Gateway restart can reopen its trace for a surviving Adapter session.
    restarted = TraceStore(tmp_path)
    assert [item["sequence"] for item in restarted.read("session-1")] == [1, 2, 3, 4, 5]
    restarted.reopen("session-1")
    assert restarted.append(event("session-1", "trace-1", 6, "session.progress", {"step": 6})) is True

    with pytest.raises(TraceConflict, match="gap"):
        restarted.append(event("session-1", "trace-1", 8, "session.progress", {"step": 8}))
    with pytest.raises(TraceConflict, match="backwards"):
        restarted.append(event("session-1", "trace-1", 5, "session.progress", {"step": 5}))
    with pytest.raises(TraceConflict, match="reused"):
        restarted.append(event("session-1", "trace-1", 6, "session.progress", {"step": 99}))


def test_restore_attaches_live_session_and_reopens_trace(monkeypatch, tmp_path: Path) -> None:
    store = TraceStore(tmp_path)
    for sequence in range(1, 5):
        store.append(event("runtime-private", "trace-1", sequence, "session.progress", {"step": sequence}))
    store.close("runtime-private")
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "_catalog_request", lambda *_args, **_kwargs: {"conversation": {
        "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
        "trace_id": "trace-1", "status": "active",
    }})
    posts: list[tuple[str, dict]] = []

    def adapter(path, *, payload=None, timeout=20.0):
        posts.append((path, payload))
        return {"status": "ready", "boot_id": "a" * 32}

    monkeypatch.setattr(main, "_adapter_post", adapter)
    collectors: list[str] = []
    monkeypatch.setattr(main, "_start_trace_collector", lambda session: collectors.append(session.session_id))

    restored = main._restore_product_session(
        "conversation_1", main.Principal(subject=main.PRODUCT_PRINCIPAL), "workspace_bootstrap_unresolved",
    )

    assert restored.session_id == "runtime-private"
    assert posts == [("/internal/runtime/sessions", {
        "session_id": "runtime-private", "trace_id": "trace-1",
        "workspace_id": "workspace_bootstrap_unresolved", "owner_principal": main.PRODUCT_PRINCIPAL,
        "initial_sequence": 4, "attach_live_only": True,
    })]
    # The trace was reopened for the surviving runtime's continuation.
    assert store.append(event("runtime-private", "trace-1", 5, "session.progress", {"step": 5})) is True
    assert collectors == ["runtime-private"]
