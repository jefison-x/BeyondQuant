from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app import main
from app.agent_lifecycle_delivery import LifecycleDelivery
from app.trace_store import TraceStore
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event


BOOT_ID = 'a' * 32


def event(sequence=1, **overrides):
    return {"session_id": "session-one", "trace_id": "trace-one", "sequence": sequence,
            "timestamp": "2026-09-07T00:00:00+00:00", "source": "runtime-adapter",
            "kind": "session.failed", "payload": {"run_id": "a" * 32}, **overrides}


def context():
    return {"conversation_id": "conversation-one", "session_id": "session-one",
            "workspace_id": "workspace-one", "owner": "alice", "trace_id": "trace-one"}


def product_session(boot_id=BOOT_ID):
    return main.ProductSession("conversation-one", "session-one", "trace-one",
        main.Principal(subject="alice"), workspace_id="workspace-one", boot_id=boot_id)


def use_live_adapter_boot(monkeypatch, boot_id=BOOT_ID):
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": boot_id})


def test_active_root_registration_still_uses_the_existing_backend_path(monkeypatch):
    monkeypatch.setattr(main, "require_runtime_authority", lambda: None)
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {"ready": True, "boot_id": BOOT_ID})
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    main.product_sessions.add(product_session())
    value = project_lifecycle_event(event(kind="agent.run.registration", payload={
        "schema_version": "agent-run-registration-observed.v1",
        "run_id": "a" * 32, "registration_fingerprint": "b" * 64,
    }), "session-one", "trace-one")
    reply = {"receipt": lifecycle_receipt(value)}
    calls = []
    monkeypatch.setattr(main, "_catalog_request", lambda *a, **k: calls.append((a, k)) or reply)
    monkeypatch.setattr(main, "_adapter_post", lambda *a, **k: pytest.fail("active roots have no terminal ACK"))
    assert main._send_agent_lifecycle(context(), value, expected_boot_id=BOOT_ID) == reply
    assert len(calls) == 1
    assert calls[0][0][1] == "/internal/agent-lifecycle/conversation-one"
    assert calls[0][1]["payload"]["event"] == value
    assert calls[0][1]["runtime_boot_id"] == BOOT_ID
    assert "boot_id" not in calls[0][1]["payload"]


def test_terminal_close_keeps_exact_same_boot_receipt_fence(monkeypatch):
    monkeypatch.setattr(main, "require_runtime_authority", lambda: None)
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {"ready": True, "boot_id": BOOT_ID})
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    main.product_sessions.add(product_session())
    value = project_lifecycle_event(event(), "session-one", "trace-one")
    receipt = lifecycle_receipt(value)
    evidence = {"schema_version": main.RUNTIME_TERMINAL_EVIDENCE_SCHEMA,
        "session_id": "session-one", "boot_id": BOOT_ID, "root_run_id": value["root_run_id"],
        "sequence": value["sequence"], "outcome": value["outcome"], "receipt": receipt}
    reads, closes, acknowledgements = [], [], []
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": BOOT_ID})
    monkeypatch.setattr(main, "_adapter_get", lambda *a, **k: reads.append((a, k)) or evidence)
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *a, **k:
        closes.append((a, k)) or {"receipt": receipt})
    def acknowledge(*args, **kwargs):
        acknowledgements.append((args, kwargs))
        if len(acknowledgements) == 1:
            # The Adapter persisted this exact ACK and reaped its live record,
            # but the response was lost. Its durable receipt accepts the retry.
            raise main.HTTPException(status_code=503, detail="synthetic lost ACK response")
        return {"receipt": receipt}
    monkeypatch.setattr(main, "_adapter_post", acknowledge)
    assert main._send_agent_lifecycle(context(), value, expected_boot_id=BOOT_ID) == {"receipt": receipt}
    assert reads[0][1]["params"]["boot_id"] == BOOT_ID
    assert closes[0][0][0] == "POST"
    assert acknowledgements[0][0][0].endswith("/terminal-receipt")
    assert acknowledgements[0][1]["timeout"] == main.TRACE_TERMINAL_ACK_TIMEOUT_SECONDS
    assert acknowledgements[0][1]["timeout"] > 60
    assert len(reads) == len(closes) == 1 and len(acknowledgements) == 2
    assert acknowledgements[0] == acknowledgements[1]


def test_terminal_lifecycle_rejects_a_superseded_boot_before_io(monkeypatch):
    monkeypatch.setattr(main, "require_runtime_authority", lambda: None)
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {"ready": True, "boot_id": BOOT_ID})
    calls = []
    monkeypatch.setattr(main, "_adapter_get", lambda *a, **k: calls.append((a, k)))
    with pytest.raises(RuntimeError, match="superseded Adapter boot"):
        main._send_agent_lifecycle(context(), project_lifecycle_event(event(), "session-one", "trace-one"),
                                   expected_boot_id="b" * 32)
    assert calls == []


def test_terminal_ack_does_not_cross_an_adapter_boot_change(monkeypatch):
    monkeypatch.setattr(main, "require_runtime_authority", lambda: None)
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {"ready": True, "boot_id": BOOT_ID})
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    main.product_sessions.add(product_session())
    value = project_lifecycle_event(event(), "session-one", "trace-one")
    receipt = lifecycle_receipt(value)
    evidence = {"schema_version": main.RUNTIME_TERMINAL_EVIDENCE_SCHEMA,
        "session_id": "session-one", "boot_id": BOOT_ID, "root_run_id": value["root_run_id"],
        "sequence": value["sequence"], "outcome": value["outcome"], "receipt": receipt}
    monkeypatch.setattr(main, "_adapter_get", lambda *a, **k: evidence)
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *a, **k: {"receipt": receipt})
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": "b" * 32})
    acknowledgements = []
    monkeypatch.setattr(main, "_adapter_post", lambda *a, **k: acknowledgements.append((a, k)))
    with pytest.raises(RuntimeError, match="superseded Adapter boot"):
        main._send_agent_lifecycle(context(), value, expected_boot_id=BOOT_ID)
    assert acknowledgements == []


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


def test_collector_is_only_lifecycle_sender_when_delivery_workers_tick(monkeypatch, tmp_path):
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    use_live_adapter_boot(monkeypatch)
    use_live_adapter_boot(monkeypatch)
    terminal = {**event(kind="session.result"), "session_id": "session-one", "trace_id": "trace-one"}
    session = product_session()

    def lines():
        yield "data: " + json.dumps(terminal)
        session.released = True

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(status_code=200, iter_lines=lines)

    monkeypatch.setattr(main.httpx, "stream", stream)
    sent = []
    monkeypatch.setattr(main, "_send_agent_lifecycle", lambda ctx, item, **kwargs: sent.append((item, kwargs)))
    answers = LifecycleDelivery(tmp_path, store, lambda *_: pytest.fail("answer worker sent lifecycle"), answers=True)
    domain_calls = LifecycleDelivery(tmp_path, store, lambda *_: pytest.fail("domain worker sent lifecycle"),
        private_source=lambda *_: {"schema_version": "domain-call-page.v1", "events": [], "more": False,
                                  "idle": True})
    monkeypatch.setattr(main, "answer_delivery", answers)
    monkeypatch.setattr(main, "domain_call_delivery", domain_calls)
    main._collect_trace(session)
    answers.register(session)
    domain_calls.register(session)
    answers.run_once()
    domain_calls.run_once()

    assert len(sent) == 1
    assert sent[0][1] == {"expected_boot_id": BOOT_ID}
    assert len(store.read(session.session_id)) == 1
    assert not hasattr(main, "lifecycle_delivery")
    assert not any(route.path.endswith("/lifecycle-delivery") for route in main.app.routes)


@pytest.mark.parametrize("first_status", [503, "http_error"])
def test_collector_reconnects_after_transient_adapter_or_backend_failure(monkeypatch, tmp_path, first_status):
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_register_answer_delivery", lambda _: None)
    use_live_adapter_boot(monkeypatch)
    use_live_adapter_boot(monkeypatch)
    terminal = {**event(kind="session.result"), "session_id": "session-one", "trace_id": "trace-one"}
    opens = []
    session = product_session()

    def lines():
        yield "data: " + json.dumps(terminal)
        session.released = True

    @contextmanager
    def stream(*args, **kwargs):
        opens.append(1)
        if len(opens) == 1 and first_status == "http_error":
            raise main.httpx.HTTPError("temporary Adapter outage")
        status = first_status if len(opens) == 1 else 200
        yield SimpleNamespace(status_code=status, iter_lines=lines)

    monkeypatch.setattr(main.httpx, "stream", stream)
    sent = []
    monkeypatch.setattr(main, "_send_agent_lifecycle", lambda ctx, item, **kwargs: sent.append(item))
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    main._collect_trace(session)
    assert len(opens) == 2
    assert sent == [project_lifecycle_event(terminal, "session-one", "trace-one")]
    assert store.read("session-one") == [terminal]


def test_collector_keeps_reconnecting_after_more_than_four_same_boot_outages(monkeypatch, tmp_path):
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_register_answer_delivery", lambda _: None)
    use_live_adapter_boot(monkeypatch)
    terminal = {**event(kind="session.result"), "session_id": "session-one", "trace_id": "trace-one"}
    session = product_session()
    opens, delays, sent = [], [], []

    def lines(attempt):
        if attempt in {6, 7}:
            yield "data: " + json.dumps(terminal)
        if attempt == 7:
            session.released = True

    @contextmanager
    def stream(*args, **kwargs):
        opens.append(1)
        attempt = len(opens)
        status = 503 if attempt <= 3 else 200
        yield SimpleNamespace(status_code=status, iter_lines=lambda: lines(attempt))

    monkeypatch.setattr(main.httpx, "stream", stream)
    monkeypatch.setattr(main, "_send_agent_lifecycle", lambda ctx, item, **kwargs: sent.append(item))
    monkeypatch.setattr(main.time, "sleep", delays.append)
    main._collect_trace(session)

    assert len(opens) == 7  # Three 503s and two clean premature EOFs before recovery.
    assert len(delays) == 6
    assert all(0 < delay <= main.TRACE_RETRY_MAX_DELAY_SECONDS for delay in delays)
    assert sent == [project_lifecycle_event(terminal, "session-one", "trace-one")]
    assert store.read("session-one") == [terminal]


def test_collector_retries_the_exact_lifecycle_event_after_temporary_backend_failure(monkeypatch, tmp_path):
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_register_answer_delivery", lambda _: None)
    use_live_adapter_boot(monkeypatch)
    use_live_adapter_boot(monkeypatch)
    terminal = {**event(kind="session.result"), "session_id": "session-one", "trace_id": "trace-one"}
    session = product_session()

    def lines():
        yield "data: " + json.dumps(terminal)
        session.released = True

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(status_code=200, iter_lines=lines)

    monkeypatch.setattr(main.httpx, "stream", stream)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    calls = []
    def send(ctx, value, **kwargs):
        calls.append((ctx, value, kwargs))
        if len(calls) == 1:
            raise main.HTTPException(status_code=503, detail="synthetic Backend outage")
    monkeypatch.setattr(main, "_send_agent_lifecycle", send)
    main._collect_trace(session)
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0][2] == {"expected_boot_id": BOOT_ID}


def test_collector_reconnects_after_transient_backend_card_hydration(monkeypatch, tmp_path):
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_register_answer_delivery", lambda _: None)
    use_live_adapter_boot(monkeypatch)
    use_live_adapter_boot(monkeypatch)
    card = {"session_id": "session-one", "trace_id": "trace-one", "sequence": 1,
        "timestamp": "2026-09-07T00:00:00+00:00", "source": "runtime-adapter",
        "kind": "agent.card.approval", "payload": {"approval_id": "approval-one"}}
    opens, backend_reads = [], []
    session = product_session()

    @contextmanager
    def stream(*args, **kwargs):
        opens.append(1)
        def lines():
            yield "data: " + json.dumps(card)
            if len(opens) > 1:
                session.released = True
        yield SimpleNamespace(status_code=200, iter_lines=lines)

    class BackendResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"approval": {"approval_id": "approval-one", "action": "byq_strategy_approve",
                "status": "pending", "execution_outcome": "not_started"}}

    def backend_get(*args, **kwargs):
        backend_reads.append((args, kwargs))
        if len(backend_reads) == 1:
            raise main.httpx.HTTPError("synthetic Backend outage")
        return BackendResponse()

    monkeypatch.setattr(main.httpx, "stream", stream)
    monkeypatch.setattr(main.httpx, "get", backend_get)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    main._collect_trace(session)
    assert len(opens) == len(backend_reads) == 2
    projected = store.read("session-one")
    assert len(projected) == 1
    assert projected[0]["source"] == "byq-domain"


def test_collector_fails_closed_when_adapter_boot_changes(monkeypatch, tmp_path):
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_register_answer_delivery", lambda _: None)
    boots = iter([BOOT_ID, "b" * 32])
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": next(boots)})
    opens = []

    @contextmanager
    def stream(*args, **kwargs):
        opens.append(1)
        yield SimpleNamespace(status_code=503, iter_lines=lambda: ())

    monkeypatch.setattr(main.httpx, "stream", stream)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    main._collect_trace(product_session(BOOT_ID))
    assert opens == [1]
    assert store.read("session-one") == []
