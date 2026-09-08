import json
from types import SimpleNamespace

import pytest

from app.agent_lifecycle_delivery import LifecycleDelivery, MAX_ATTEMPTS
from app.trace_store import TraceStore


def answer(sequence, **change):
    return {"session_id": "answer-session", "trace_id": "answer-trace", "sequence": sequence,
        "timestamp": "2026-09-08T00:00:00+00:00", "source": "runtime-adapter", "kind": "agent.output.delta",
        "payload": {"schema_version": "workflow-answer.v1", "channel": "answer", "delta": f"Synthetic answer {sequence}",
                    "truncated": False}, **change}


def setup(tmp_path, send):
    traces = TraceStore(tmp_path)
    session = SimpleNamespace(session_id="answer-session", trace_id="answer-trace", conversation_id="answer-conversation",
                              workspace_id="answer-workspace", principal=SimpleNamespace(subject="synthetic-user"))
    now = [1000]
    delivery = LifecycleDelivery(tmp_path, traces, send, clock=lambda: now[0], answers=True)
    delivery.register(session)
    return traces, session, now, delivery


def test_answer_lost_ack_and_restart_keep_order_and_one_catalog_write(tmp_path):
    catalog, calls = {}, []
    def send(ctx, event):
        calls.append(event["sequence"])
        catalog.setdefault(event["sequence"], event["content"])
        if len(calls) == 1:
            raise TimeoutError("synthetic lost commit response")
        return {"receipt": delivery.receipt(event)}
    traces, session, now, delivery = setup(tmp_path, send)
    traces.append(answer(9))
    traces.append(answer(10))
    delivery.run_once()
    assert calls == [9]
    restarted = LifecycleDelivery(tmp_path, TraceStore(tmp_path), send, clock=lambda: now[0], answers=True)
    restarted.run_once()
    assert calls == [9]
    now[0] += 2
    restarted.run_once()
    assert calls == [9, 9, 10]
    assert len(catalog) == 2
    restarted.deliver_session(session)
    assert calls == [9, 9, 10]
    state = json.loads((tmp_path / "answer-session.answers.json").read_text())
    assert state["pending"] == {}
    assert state["cursor"] == 10


@pytest.mark.parametrize("failure", ["transport", "wrong_receipt", "crash"])
def test_answer_retry_budget_survives_restart_and_blocks_overtaking(tmp_path, failure):
    calls = []
    def send(ctx, event):
        calls.append(event["sequence"])
        if failure == "transport":
            raise TimeoutError("not persisted")
        if failure == "crash":
            raise SystemExit("synthetic process exit after durable attempt charge")
        return {"receipt": {}}
    traces, session, now, delivery = setup(tmp_path, send)
    traces.append(answer(1))
    traces.append(answer(2))
    for _ in range(MAX_ATTEMPTS):
        restarted = LifecycleDelivery(tmp_path, TraceStore(tmp_path), send, clock=lambda: now[0], answers=True)
        if failure == "crash":
            with pytest.raises(SystemExit):
                restarted.run_once()
        else:
            restarted.run_once()
        now[0] += 3600
    restarted.run_once()
    assert calls == [1] * MAX_ATTEMPTS
    state = json.loads((tmp_path / "answer-session.answers.json").read_text())
    assert state["pending"]["1"]["status"] == "exhausted"
    assert state["pending"]["2"]["attempts"] == 0


def test_answer_scope_and_lifecycle_ledgers_are_independent(tmp_path):
    calls = []
    traces, session, now, delivery = setup(tmp_path, lambda ctx, event: calls.append(event))
    traces.append(answer(1, trace_id="foreign"))
    traces.append(answer(2, source="byq-domain"))
    traces.append(answer(3, kind="session.failed", payload={"run_id": "a" * 32}))
    delivery.run_once()
    assert calls == []
    lifecycle = LifecycleDelivery(tmp_path, traces, lambda ctx, event: {"receipt": lifecycle.receipt(event)})
    lifecycle.register(session)
    lifecycle.run_once()
    assert (tmp_path / "answer-session.lifecycle.json").exists()
    assert json.loads((tmp_path / "answer-session.lifecycle.json").read_text())["pending"] == {}
    assert json.loads((tmp_path / "answer-session.answers.json").read_text())["pending"] == {}


def test_answer_status_is_owner_scoped_without_resetting_budget(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main
    traces, session, now, delivery = setup(tmp_path, lambda *_: {})
    monkeypatch.setattr(main, "answer_delivery", delivery)
    monkeypatch.setattr(main, "PRODUCT_TOKEN", "synthetic-answer-test-token")
    client = TestClient(main.app)
    path = "/v1/agent/sessions/answer-conversation/answer-delivery"
    assert client.get(path).status_code == 401
    monkeypatch.setattr(main, "_trusted_request_identity", lambda _: (session.principal, session.workspace_id))
    monkeypatch.setattr(main, "_catalog_request", lambda *args, **kwargs: {"conversation": {
        "runtime_session_id": session.session_id, "trace_id": session.trace_id}})
    traces.append(answer(1))
    delivery.run_once()
    before = (tmp_path / "answer-session.answers.json").read_text()
    body = client.get(path).json()
    assert body["schema_version"] == "public-answer-delivery-status.v1"
    assert body["pending_events"] == 1
    assert "content" not in body
    assert (tmp_path / "answer-session.answers.json").read_text() == before
    session.principal = SimpleNamespace(subject="foreign")
    assert client.get(path).json()["state"] == "unavailable"
