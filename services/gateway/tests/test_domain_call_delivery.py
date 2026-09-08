import json
from types import SimpleNamespace

import pytest

from app.agent_lifecycle_delivery import LifecycleDelivery, MAX_ATTEMPTS
from app.trace_store import TraceStore
from packages.contracts.domain_call_admission import call_evidence_receipt


def evidence(sequence=1):
    return {"schema_version": "domain-call-observed.v1", "sequence": sequence,
        "root_run_id": "a" * 32, "generation": "generation-one", "call_id": "call-one",
        "action": "byq_strategy_validate", "task_id": "task-one", "agent_run_id": "run-one",
        "idempotency_key": "key-one", "request_sha256": "b" * 64, "input_sha256": "c" * 64}


def setup(tmp_path, source, send, now):
    traces = TraceStore(tmp_path)
    delivery = LifecycleDelivery(tmp_path, traces, send, private_source=source, clock=lambda: now[0])
    delivery.register(SimpleNamespace(session_id="session-one", trace_id="trace-one", conversation_id="conversation-one",
        workspace_id="workspace-one", principal=SimpleNamespace(subject="alice")))
    return delivery


def page(events):
    return {"schema_version": "domain-call-page.v1", "events": events, "more": False, "idle": False}


def test_private_delivery_restarts_with_same_receipt_without_public_trace(tmp_path):
    now, sends, reads = [1000.], [], []
    def source(ctx, cursor):
        reads.append((ctx, cursor))
        return page([evidence()] if cursor == 0 else [])
    def send(ctx, value):
        sends.append(value)
        if len(sends) == 1:
            raise TimeoutError("synthetic lost receipt")
        return {"receipt": call_evidence_receipt(value)}
    first = setup(tmp_path, source, send, now)
    first.run_once()
    assert sends == [evidence()]
    restarted = setup(tmp_path, source, send, now)
    restarted.run_once()
    assert len(sends) == 1
    now[0] += 2
    restarted.run_once()
    assert sends == [evidence(), evidence()]
    assert reads[-1][1] == 1
    assert TraceStore(tmp_path).read("session-one") == []
    state = json.loads((tmp_path / "session-one.domain-calls.json").read_text())
    assert state["pending"] == {} and state["cursor"] == 1
    assert "terminal_events" not in state and "durable_terminal_ack_migrated" not in state


@pytest.mark.parametrize("invalid", [page([evidence(2)]), page([{**evidence(), "raw_arguments": "secret"}]),
    {"schema_version": "domain-call-page.v1", "events": [], "more": True, "idle": False}])
def test_invalid_private_page_is_never_delivered_and_read_budget_survives_restart(tmp_path, invalid):
    now, sends, reads = [1000.], [], []
    def source(ctx, cursor):
        reads.append(cursor)
        return invalid
    for _ in range(MAX_ATTEMPTS + 2):
        delivery = setup(tmp_path, source, lambda ctx, value: sends.append(value), now)
        delivery.run_once()
        now[0] += 4000
    assert sends == [] and len(reads) == MAX_ATTEMPTS
    state = json.loads((tmp_path / "session-one.domain-calls.json").read_text())
    assert state["cursor"] == 0 and state["source_exhausted"]


def test_mismatched_backend_receipts_exhaust_without_new_domain_execution(tmp_path):
    now, sends = [1000.], []
    def source(ctx, cursor):
        return page([evidence()] if cursor == 0 else [])
    def send(ctx, value):
        sends.append(value)
        return {"receipt": {**call_evidence_receipt(value), "root_run_id": "d" * 32}}
    delivery = setup(tmp_path, source, send, now)
    for _ in range(MAX_ATTEMPTS + 2):
        delivery.run_once()
        now[0] += 4000
    assert sends == [evidence()] * MAX_ATTEMPTS
    state = json.loads((tmp_path / "session-one.domain-calls.json").read_text())
    assert state["pending"]["1"]["status"] == "exhausted"


def test_idle_private_source_stops_http_polling_until_public_root_changes(tmp_path):
    from tests.test_agent_lifecycle_delivery import event
    now, reads = [1000.], []
    def source(ctx, cursor):
        reads.append(cursor)
        return {**page([]), "idle": True}
    delivery = setup(tmp_path, source, lambda *args: None, now)
    delivery.run_once()
    now[0] += 100
    delivery.run_once()
    assert reads == [0]
    # Root publication is only a wake signal, never private evidence itself.
    TraceStore(tmp_path).append(event(kind="session.started", payload={"run_id": "b" * 32}))
    delivery.run_once()
    assert reads == [0, 0]


def test_crash_before_idle_page_cursor_commit_cannot_drop_private_evidence(tmp_path, monkeypatch):
    now, sends = [1000.], []
    def source(ctx, cursor):
        return {**page([evidence()] if cursor == 0 else []), "idle": True}
    def send(ctx, value):
        sends.append(value)
        return {"receipt": call_evidence_receipt(value)}
    delivery = setup(tmp_path, source, send, now)
    monkeypatch.setattr(delivery, "_project", lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic crash")))
    with pytest.raises(RuntimeError):
        delivery.run_once()
    now[0] += 2
    setup(tmp_path, source, send, now).run_once()
    assert sends == [evidence()]
