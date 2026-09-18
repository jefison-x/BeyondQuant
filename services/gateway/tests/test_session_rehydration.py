"""Gateway continuity when the runtime-adapter is recreated by a deploy.

The adapter rehydrates its durable session and continues the public BYQ
sequence at ``persisted + 1``. The Gateway must reopen the durable trace and
project the rehydrated lifecycle so a new turn binds instead of staying
``pending_binding``. Real gaps/backwards/reused sequences must still fail.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import main
from app.agent_lifecycle_delivery import LifecycleDelivery
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

    # A deploy recreates the Gateway process; the durable trace is required to
    # receive the rehydrated runtime's continuation at persisted + 1.
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


def test_restore_seeds_persisted_sequence_and_reopens_trace(monkeypatch, tmp_path: Path) -> None:
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
        return {"status": "ready"}

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
        "initial_sequence": 4, "conversation_context": [],
    })]
    # The trace was reopened for the rehydrated runtime's continuation.
    assert store.append(event("runtime-private", "trace-1", 5, "session.progress", {"step": 5})) is True
    assert collectors == ["runtime-private"]


def test_rebound_lifecycle_registration_is_delivered_for_run_binding(tmp_path: Path) -> None:
    fingerprint = "b" * 64
    run_id = "c" * 32
    sent: list[dict] = []
    traces = TraceStore(tmp_path)
    for sequence, kind, payload in [
        (1, "session.ready", {"status": "ready"}),
        (2, "session.started", {"run_id": "a" * 32}),
        (3, "session.result", {"run_id": "a" * 32}),
    ]:
        traces.append(event("rehydrated-session", "rehydrated-trace", sequence, kind, payload))
    traces.close("rehydrated-session")

    session = main.ProductSession(
        conversation_id="conversation_1", session_id="rehydrated-session",
        trace_id="rehydrated-trace", principal=main.Principal(subject="admin"),
        workspace_id="workspace_admin",
    )

    def send(context, projected):
        sent.append(projected)
        return {"receipt": delivery.receipt(projected)}

    delivery = LifecycleDelivery(tmp_path, TraceStore(tmp_path), send, clock=lambda: 1000.0)
    delivery.register(session)
    # A rehydrated turn registers its newly opened root at persisted + 1.
    traces.reopen("rehydrated-session")
    traces.append(event("rehydrated-session", "rehydrated-trace", 4, "agent.run.registration", {
        "schema_version": "agent-run-registration-observed.v1",
        "run_id": run_id, "registration_fingerprint": fingerprint,
    }))

    delivery.run_once()

    # The rehydrated registration is delivered last; the backend binds the
    # still-``pending_binding`` agent run through its exact fingerprint.
    assert sent[-1] == {
        "schema_version": "agent-run-lifecycle.v1", "root_run_id": run_id,
        "sequence": 4, "outcome": "active", "registration_fingerprint": fingerprint,
    }
