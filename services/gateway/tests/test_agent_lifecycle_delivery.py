import json
from types import SimpleNamespace

import pytest

from app.agent_lifecycle_delivery import LifecycleDelivery, MAX_ATTEMPTS, DEADLINE_SECONDS
from app.trace_store import TraceStore
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event


def fixture(tmp_path, send):
    traces = TraceStore(tmp_path)
    session = SimpleNamespace(session_id="session-one", trace_id="trace-one", conversation_id="conversation-one",
                              workspace_id="workspace-one", principal=SimpleNamespace(subject="alice"))
    now = [1000.0]
    delivery = LifecycleDelivery(tmp_path, traces, send, clock=lambda: now[0])
    delivery.register(session)
    return traces, session, now, delivery


def event(sequence=1, **overrides):
    return {"session_id": "session-one", "trace_id": "trace-one", "sequence": sequence,
            "timestamp": "2026-09-07T00:00:00+00:00", "source": "runtime-adapter",
            "kind": "session.failed", "payload": {"run_id": "a" * 32}, **overrides}


def test_lost_ack_restarts_with_same_event_and_then_stops(tmp_path):
    writes = []
    def send(ctx, value):
        writes.append((ctx, value))
        if len(writes) == 1:
            raise TimeoutError("synthetic lost ack")
        return {"receipt": lifecycle_receipt(value)}
    traces, session, now, delivery = fixture(tmp_path, send)
    traces.append(event())  # crash gap: ledger has context, not the event
    delivery.run_once()
    assert len(writes) == 1
    restarted = LifecycleDelivery(tmp_path, TraceStore(tmp_path), send, clock=lambda: now[0])
    restarted.run_once()
    assert len(writes) == 1  # backoff survives restart
    now[0] += 2
    restarted.run_once()
    assert writes[0] == writes[1]
    restarted.run_once()
    assert len(writes) == 2
    state = json.loads((tmp_path / "session-one.lifecycle.json").read_text())
    assert state["pending"] == {}
    assert state["last_receipt"] == lifecycle_receipt(writes[0][1])


def test_legacy_delivered_terminal_receipt_is_reconciled_once(tmp_path):
    writes = []
    traces, session, now, delivery = fixture(tmp_path, lambda ctx, value:
        writes.append(value) or {"receipt": lifecycle_receipt(value)})
    traces.append(event())
    delivery.run_once()
    path = tmp_path / "session-one.lifecycle.json"
    state = json.loads(path.read_text())
    for key in list(state):
        if key.startswith("terminal_ack_migration_") or key == "durable_terminal_ack_migrated":
            del state[key]
    path.write_text(json.dumps(state))
    delivery.run_once()
    assert writes == [writes[0], writes[0]]
    delivery.run_once()
    assert len(writes) == 2
    assert json.loads(path.read_text())["durable_terminal_ack_migrated"] is True


def test_legacy_ack_migration_preserves_exhausted_retry_budget(tmp_path):
    writes = []
    traces, session, now, delivery = fixture(tmp_path, lambda ctx, value: writes.append(value))
    traces.append(event())
    delivery.run_once()
    path = tmp_path / "session-one.lifecycle.json"
    state = json.loads(path.read_text())
    for key in list(state):
        if key.startswith("terminal_ack_migration_") or key == "durable_terminal_ack_migrated":
            del state[key]
    state["pending"]["1"]["attempts"] = MAX_ATTEMPTS
    state["pending"]["1"]["status"] = "exhausted"
    path.write_text(json.dumps(state))
    delivery.run_once()
    assert len(writes) == 1
    assert json.loads(path.read_text())["pending"]["1"]["attempts"] == MAX_ATTEMPTS


def test_gateway_only_releases_runtime_barrier_after_exact_backend_receipt(monkeypatch):
    from app import main
    from fastapi import HTTPException
    value = project_lifecycle_event(event(), "session-one", "trace-one")
    context = {"conversation_id": "conversation-one", "session_id": "session-one",
               "workspace_id": "workspace-one", "owner": "alice", "trace_id": "trace-one"}
    reply = {"receipt": lifecycle_receipt(value)}
    calls = []
    monkeypatch.setattr(main, "_catalog_request", lambda *a, **k: {})
    monkeypatch.setattr(main, "_adapter_post", lambda *a, **k: calls.append(k) or reply)
    with pytest.raises(ValueError):
        main._send_agent_lifecycle(context, value)
    assert calls == []
    monkeypatch.setattr(main, "_catalog_request", lambda *a, **k: reply)
    assert main._send_agent_lifecycle(context, value) == reply
    assert calls == [{"payload": reply, "timeout": 5.0}]
    for status in [404, 409, 503]:
        def fail(*a, **k):
            raise HTTPException(status_code=status)
        monkeypatch.setattr(main, "_adapter_post", fail)
        with pytest.raises(HTTPException):
            main._send_agent_lifecycle(context, value)


def test_recovery_poll_is_throttled_durable_and_stops_after_recovered(tmp_path):
    traces, session, now, delivery = fixture(tmp_path, lambda ctx, value: {"receipt": lifecycle_receipt(value)})
    calls = []
    def recover(ctx):
        calls.append(ctx)
        if len(calls) == 1:
            raise OSError("synthetic restart")
        traces.append(event())
        return True
    delivery.recover = recover
    delivery.run_once()
    restarted = LifecycleDelivery(tmp_path, traces, delivery.send, clock=lambda: now[0], recover=recover)
    restarted.run_once()
    assert len(calls) == 1
    now[0] += 30
    restarted.run_once()
    assert len(calls) == 2
    now[0] += 30
    restarted.run_once()
    assert len(calls) == 2
    assert json.loads((tmp_path / "session-one.lifecycle.json").read_text())["pending"] == {}


def test_recovery_failure_budget_survives_restart(tmp_path):
    traces, session, now, delivery = fixture(tmp_path, lambda *args: None)
    calls = []
    def recover(ctx):
        calls.append(1)
        raise ValueError("unproven or unavailable evidence")
    for _ in range(MAX_ATTEMPTS + 2):
        delivery = LifecycleDelivery(tmp_path, traces, delivery.send, clock=lambda: now[0], recover=recover)
        delivery.run_once()
        now[0] += 3600
    assert len(calls) == MAX_ATTEMPTS
    assert json.loads((tmp_path / "session-one.lifecycle.json").read_text())["recovery_exhausted"] is True


def test_recovery_attempt_is_charged_before_process_loss(tmp_path):
    traces, session, now, delivery = fixture(tmp_path, lambda *args: None)
    calls = []
    def crash(ctx):
        calls.append(1)
        raise SystemExit("synthetic Gateway death after request admission")
    for _ in range(MAX_ATTEMPTS):
        delivery = LifecycleDelivery(tmp_path, traces, delivery.send, clock=lambda: now[0], recover=crash)
        with pytest.raises(SystemExit):
            delivery.run_once()
        now[0] += 3600
    delivery.run_once()
    assert len(calls) == MAX_ATTEMPTS
    assert json.loads((tmp_path / "session-one.lifecycle.json").read_text())["recovery_exhausted"] is True


def test_recovery_import_rejects_foreign_and_non_lifecycle_data(tmp_path, monkeypatch):
    from app import main
    traces, session, now, delivery = fixture(tmp_path, lambda *a: None)
    monkeypatch.setattr(main, "trace_store", traces)
    ctx = json.loads((tmp_path / "session-one.lifecycle.json").read_text())["context"]
    for value in [event(trace_id="foreign"), event(kind="agent.output.delta", payload={"text": "private"})]:
        monkeypatch.setattr(main, "_adapter_post", lambda *a, **k: {"state": "recovered", "events": [value], "more": False})
        with pytest.raises(ValueError):
            main._recover_agent_lifecycle(ctx)
    assert traces.read(session.session_id) == []
    monkeypatch.setattr(main, "_adapter_post", lambda *a, **k: {"state": "recovered", "events": [event()], "more": False})
    assert main._recover_agent_lifecycle(ctx) is True
    assert len(traces.read(session.session_id)) == 1


@pytest.mark.parametrize("failure", ["transport", "wrong_ack"])
def test_retry_budget_is_durable_and_does_not_block_other_terminal(tmp_path, failure):
    writes = []
    def send(ctx, value):
        writes.append(value)
        if value["root_run_id"] == "b" * 32:
            return {"receipt": lifecycle_receipt(value)}
        if failure == "transport":
            raise TimeoutError()
        return {"receipt": {**lifecycle_receipt(value), "event_sha256": "0" * 64}}
    traces, session, now, delivery = fixture(tmp_path, send)
    traces.append(event())
    for _ in range(MAX_ATTEMPTS + 2):
        LifecycleDelivery(tmp_path, traces, send, clock=lambda: now[0]).run_once()
        now[0] += 4000
    assert len(writes) == MAX_ATTEMPTS
    traces.append(event(2, payload={"run_id": "b" * 32}))
    delivery.run_once()
    assert len(writes) == MAX_ATTEMPTS + 1
    state = json.loads((tmp_path / "session-one.lifecycle.json").read_text())
    assert state["pending"]["1"]["status"] == "exhausted"
    assert "2" not in state["pending"]


def test_deadline_and_context_cannot_reset(tmp_path):
    calls = []
    traces, session, now, delivery = fixture(tmp_path, lambda *args: calls.append(args))
    traces.append(event())
    delivery.run_once()
    now[0] += DEADLINE_SECONDS
    delivery.register(session)
    delivery.run_once()
    assert len(calls) == 1
    session.principal = SimpleNamespace(subject="bob")
    with pytest.raises(ValueError):
        delivery.register(session)


def test_translation_is_closed_and_ignores_foreign_or_unowned_events():
    for kind, outcome in (("session.result", "completed"), ("session.failed", "failed"),
                          ("session.cancelled", "cancelled"), ("session.closed", "interrupted")):
        assert project_lifecycle_event(event(kind=kind), "session-one", "trace-one")["outcome"] == outcome
    for change in ({"session_id": "foreign"}, {"trace_id": "foreign"}, {"source": "gateway"}, {"payload": {}}):
        assert project_lifecycle_event(event(**change), "session-one", "trace-one") is None
    registered = event(kind="agent.run.registration", payload={"schema_version": "agent-run-registration-observed.v1",
        "run_id": "a" * 32, "registration_fingerprint": "b" * 64})
    assert project_lifecycle_event(registered, "session-one", "trace-one")["outcome"] == "active"
    registered["payload"]["arguments"] = "not allowed"
    with pytest.raises(ValueError):
        project_lifecycle_event(registered, "session-one", "trace-one")


def test_first_terminal_wins_across_restart_and_late_registration_still_delivers(tmp_path):
    calls = []
    def send(ctx, value):
        calls.append(value)
        return {"receipt": lifecycle_receipt(value)}
    traces, session, now, delivery = fixture(tmp_path, send)
    traces.append(event(kind="session.cancelled"))
    delivery.run_once()
    traces.append(event(2, kind="session.cancelled"))
    traces.append(event(3, kind="agent.run.registration", payload={
        "schema_version": "agent-run-registration-observed.v1", "run_id": "a" * 32,
        "registration_fingerprint": "b" * 64}))
    LifecycleDelivery(tmp_path, TraceStore(tmp_path), send, clock=lambda: now[0]).run_once()
    assert [value["sequence"] for value in calls] == [1, 3]


def test_two_consumers_cannot_send_same_event_concurrently(tmp_path):
    import threading
    entered, release = threading.Event(), threading.Event()
    calls = []
    def send(ctx, value):
        calls.append(value)
        entered.set()
        assert release.wait(5)
        return {"receipt": lifecycle_receipt(value)}
    traces, session, now, delivery = fixture(tmp_path, send)
    traces.append(event())
    thread = threading.Thread(target=delivery.run_once)
    thread.start()
    try:
        assert entered.wait(5)
        LifecycleDelivery(tmp_path, traces, send).run_once()
        assert len(calls) == 1
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()


def test_status_is_owner_scoped_and_never_means_research_completed(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main
    traces, session, now, delivery = fixture(tmp_path, lambda *_: {})
    monkeypatch.setattr(main, "PRODUCT_TOKEN", "synthetic-lifecycle-token")
    monkeypatch.setattr(main, "lifecycle_delivery", delivery)
    client = TestClient(main.app)
    path = "/v1/agent/sessions/conversation-one/lifecycle-delivery"
    assert client.get(path).status_code == 401
    monkeypatch.setattr(main, "_trusted_request_identity", lambda _: (session.principal, session.workspace_id))
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"conversation": {
        "runtime_session_id": session.session_id, "trace_id": session.trace_id}})
    traces.append(event())
    assert client.get(path).json()["state"] == "pending"
    delivery.run_once()
    now[0] += DEADLINE_SECONDS
    delivery.run_once()
    body = client.get(path).json()
    assert body["state"] == "attention_required"
    assert body["exhausted_events"] == 1
    assert body["max_attempts"] == 8
    assert "root_run_id" not in body and "registration_fingerprint" not in body
    session.principal = SimpleNamespace(subject="bob")
    assert client.get(path).json()["state"] == "unavailable"
