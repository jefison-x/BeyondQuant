from __future__ import annotations

from pathlib import Path
import threading
from types import SimpleNamespace
import pytest
from starlette.requests import Request

from fastapi.testclient import TestClient

from app import main
from app.trace_store import TraceStore


TOKEN = "phase7-product-token"
TEST_BOOT_ID = "a" * 32


def test_active_catalog_status_requires_a_current_live_adapter_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "_adapter_containment", lambda _session_id: None)
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {
        "ready": True, "boot_id": "b" * 32, "authority_epoch": 7,
    })
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": "b" * 32})
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *_args, **_kwargs: {
        "schema_version": main.RUNTIME_AUTHORITY_CURRENT_SCHEMA,
        "boot_id": "b" * 32, "authority_epoch": 7, "status": "current",
    })
    conversation = {
        "conversation_id": "conversation_1", "runtime_session_id": "runtime_1",
        "trace_id": "trace_1", "title": "研究", "status": "active",
    }
    monkeypatch.setattr(main, "_catalog_request", lambda *_args, **_kwargs: {
        "conversation": conversation, "messages": [],
    })
    client = TestClient(main.app)

    def status():
        response = client.get("/v1/agent/sessions/conversation_1",
                              headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        return response.json()

    # After Gateway restart there is no live binding to prove the old catalog
    # status; after Adapter boot rotation a retained old binding is stale.
    assert status()["conversation"]["status"] == "unknown"
    assert status()["containment"]["status"] == "unknown"
    session = main.ProductSession("conversation_1", "runtime_1", "trace_1",
                                  main.Principal(subject=main.PRODUCT_PRINCIPAL))
    session.boot_id = TEST_BOOT_ID
    main.product_sessions.add(session)
    assert status()["conversation"]["status"] == "interrupted"
    assert status()["containment"]["status"] == "interrupted"
    session.boot_id = "b" * 32
    assert status()["conversation"]["status"] == "active"
    monkeypatch.setattr(main, "_backend_runtime_authority_request",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down")))
    assert status()["conversation"]["status"] == "unknown"
    monkeypatch.setattr(main, "_adapter_authority", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert status()["conversation"]["status"] == "unknown"


def authorize_runtime_session(monkeypatch, session):
    session.boot_id = TEST_BOOT_ID
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {
        "ready": True, "boot_id": TEST_BOOT_ID,
    })


@pytest.mark.parametrize("terminal_kind", ["session.failed", "session.cancelled"])
def test_ambiguous_continue_after_failed_or_cancelled_turn_requires_explicit_instruction(
    monkeypatch, tmp_path, terminal_kind,
):
    monkeypatch.setattr(main, "_attested_runtime_events", lambda events, _session: events)
    session = main.ProductSession("conversation", "runtime", "trace", main.Principal(subject="alice"))
    authorize_runtime_session(monkeypatch, session)
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    terminal_payload = {"run_id": "a" * 32}
    if terminal_kind == "session.failed":
        terminal_payload["code"] = "runtime-subagent-timeout"
    for sequence, kind, payload in [(1, "session.started", {"run_id": "a" * 32}),
                                    (2, terminal_kind, terminal_payload)]:
        store.append({"session_id": "runtime", "trace_id": "trace", "sequence": sequence,
            "timestamp": "2026-09-08T01:01:00Z", "source": "runtime-adapter", "kind": kind, "payload": payload})
    calls = []
    def catalog(method, *args, **kwargs):
        calls.append(method)
        return {"messages": [{"sequence": 1, "role": "user",
            "content": "沪深300近三年每周调仓，先研究凯利仓位",
            "created_at": "2026-09-08T01:00:00Z"}]}
    monkeypatch.setattr(main, "_catalog_request", catalog)
    monkeypatch.setattr(main, "_adapter_post", lambda *args, **kwargs: pytest.fail("ambiguous continuation was dispatched"))
    with pytest.raises(main.ProductError) as raised:
        main.submit_product_turn("conversation", main.ProductPromptRequest(content="继续"), Request({"type": "http"}))
    assert raised.value.status_code == 409
    assert raised.value.code == "agent_instruction_required"
    assert "明确重述" in raised.value.message
    assert calls == ["GET"]


def test_explicit_instruction_after_failure_uses_completed_public_transcript_only(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_attested_runtime_events", lambda events, _session: events)
    session = main.ProductSession("conversation", "runtime", "trace", main.Principal(subject="alice"))
    authorize_runtime_session(monkeypatch, session)
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    trace = [
        (1, "session.started", {"run_id": "completed-run"}, "2026-09-08T00:00:01Z"),
        (2, "agent.output.delta", {"schema_version": "workflow-answer.v1", "channel": "answer",
            "delta": "第一轮回答", "truncated": False}, "2026-09-08T00:00:02Z"),
        (3, "session.result", {"run_id": "completed-run"}, "2026-09-08T00:00:03Z"),
        (4, "session.started", {"run_id": "failed-run"}, "2026-09-08T01:00:01Z"),
        (5, "tool.completed", {"private_result": "不要暴露的工具输出"}, "2026-09-08T01:00:02Z"),
        (6, "agent.output.delta", {"schema_version": "workflow-answer.v1", "channel": "answer",
            "delta": "不应进入上下文的部分答案", "truncated": False}, "2026-09-08T01:00:03Z"),
        (7, "session.failed", {"run_id": "failed-run", "code": "runtime-subagent-timeout"},
            "2026-09-08T01:00:03Z"),
    ]
    for sequence, kind, payload, timestamp in trace:
        store.append({"session_id": "runtime", "trace_id": "trace", "sequence": sequence,
            "timestamp": timestamp, "source": "runtime-adapter", "kind": kind, "payload": payload})
    catalog_calls = []
    messages = [
        {"message_id": "user-1", "sequence": 1, "role": "user", "content": "第一轮问题",
         "created_at": "2026-09-08T00:00:00Z"},
        {"message_id": "assistant-1", "sequence": 2, "role": "assistant", "content": "第一轮回答",
         "workflow_sequence": 2, "created_at": "2026-09-08T00:00:04Z"},
        {"message_id": "user-failed", "sequence": 3, "role": "user", "content": "失败的旧需求",
         "created_at": "2026-09-08T01:00:00Z"},
        {"message_id": "assistant-partial", "sequence": 4, "role": "assistant",
         "content": "不应进入上下文的部分答案", "workflow_sequence": 6,
         "created_at": "2026-09-08T01:00:02Z"},
    ]

    def catalog(method, *args, **kwargs):
        catalog_calls.append(method)
        if method == "GET":
            return {"messages": messages}
        return {"message": {"message_id": "new-message"}}

    submitted = []
    def adapter(path, **kwargs):
        payload = kwargs["payload"]
        submitted.append(payload)
        return {"accepted": True, "run_id": "new-run"}

    monkeypatch.setattr(main, "_catalog_request", catalog)
    monkeypatch.setattr(main, "_adapter_post", adapter)
    main.submit_product_turn(
        "conversation",
        main.ProductPromptRequest(content="请研究上证50近两年月频动量策略"),
        Request({"type": "http"}),
    )

    assert catalog_calls == ["GET", "POST"]
    assert len(submitted) == 1
    payload = submitted[0]
    assert payload["content"] == "请研究上证50近两年月频动量策略"
    assert payload["conversation_context"] == [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
    ]
    assert "conversation_recovery" not in payload
    assert "runtime-subagent-timeout" not in str(payload)
    assert "不要暴露的工具输出" not in str(payload)
    assert "失败的旧需求" not in str(payload)
    assert "部分答案" not in str(payload)


def test_new_root_waits_for_previous_public_answer_to_be_durable(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_attested_runtime_events", lambda events, _session: events)
    session = main.ProductSession("conversation", "runtime", "trace", main.Principal(subject="alice"))
    authorize_runtime_session(monkeypatch, session)
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    for sequence, kind, payload in [(1, "session.started", {"run_id": "a" * 32}),
        (2, "agent.output.delta", {"schema_version": "workflow-answer.v1", "channel": "answer", "delta": "凯利仓位研究方案", "truncated": False}),
        (3, "session.result", {"run_id": "a" * 32})]:
        store.append({"session_id": "runtime", "trace_id": "trace", "sequence": sequence,
            "timestamp": "2026-09-08T01:01:00Z", "source": "runtime-adapter", "kind": kind, "payload": payload})
    messages = [{"sequence": 1, "role": "user", "content": "研究凯利仓位",
                 "created_at": "2026-09-08T01:00:00Z"}]
    monkeypatch.setattr(main, "_catalog_request", lambda *a, **k: {"messages": messages})
    with pytest.raises(main.HTTPException) as raised:
        main._runtime_conversation_payload(session)
    assert raised.value.status_code == 503
    messages.append({"sequence": 2, "role": "assistant", "content": "凯利仓位研究方案",
                     "workflow_sequence": 2, "created_at": "2026-09-08T01:02:00Z"})
    transcript = main._runtime_conversation_payload(session)
    assert transcript == {"conversation_context": [
        {"role": "user", "content": "研究凯利仓位"},
        {"role": "assistant", "content": "凯利仓位研究方案"},
    ]}
    assert "conversation_recovery" not in transcript


def test_public_terminal_requires_matching_backend_business_root(monkeypatch):
    session = main.ProductSession("conversation", "runtime", "trace", main.Principal(subject="alice"))
    terminal = {"session_id": "runtime", "trace_id": "trace", "source": "runtime-adapter",
                "sequence": 3, "kind": "session.result", "payload": {"run_id": "a" * 32}}
    lifecycle = main.project_lifecycle_event(terminal, "runtime", "trace")
    receipt = main.lifecycle_receipt(lifecycle)
    row = {"root_run_id": "a" * 32, "status": "completed", "authority_status": "closed",
           "terminal_sequence": 3, "terminal_event_sha256": receipt["event_sha256"]}
    calls = []
    def backend(method, path, payload=None, scope=None):
        calls.append((method, path, scope))
        return {"schema_version": "byq-business-root-status.v1", "roots": [row]}
    monkeypatch.setattr(main, "_backend_runtime_authority_request", backend)
    assert main._attested_runtime_events([terminal], session) == [terminal]
    assert calls == [("GET", "/internal/runtime-authority/sessions/runtime/roots", session)]
    row["status"] = "failed"
    with pytest.raises(main.HTTPException) as raised:
        main._attested_runtime_events([terminal], session)
    assert raised.value.status_code == 503
    row["status"] = "completed"
    row["authority_status"] = "active"
    with pytest.raises(main.HTTPException) as raised:
        main._attested_runtime_events([terminal], session)
    assert raised.value.status_code == 503
    row["authority_status"] = "closed"
    row["terminal_event_sha256"] = "0" * 64
    with pytest.raises(main.HTTPException) as raised:
        main._attested_runtime_events([terminal], session)
    assert raised.value.status_code == 503


@pytest.mark.parametrize("mutation", [None, {"session_id": "other-session"},
    {"idempotency_key": "other-message"}, {"content_sha256": "0" * 64},
    {"accepted": True}, {"accepted": 0}, {"extra": "untrusted"}, {"code": "some-server-error"}])
def test_only_exact_pre_admission_rejection_is_known_not_accepted(monkeypatch, mutation):
    import hashlib
    import httpx

    session = SimpleNamespace(conversation_id="conversation-1", session_id="runtime-1", trace_id="trace-1",
                              principal=None, workspace_id="workspace-1")
    authorize_runtime_session(monkeypatch, session)
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"messages": [], "message": {"message_id": "message_original"}})
    detail = {"schema_version": "prompt-rejection.v1", "code": "model_credentials_unavailable",
              "accepted": False, "session_id": "runtime-1", "idempotency_key": "message_original",
              "content_sha256": hashlib.sha256(b"synthetic original").hexdigest()}
    detail.update(mutation or {})
    monkeypatch.setattr(main.httpx, "post", lambda url, **_: httpx.Response(
        503, json={"detail": detail}, request=httpx.Request("POST", url)))
    reads = []
    monkeypatch.setattr(main, "_adapter_prompt_receipt", lambda *args: reads.append(args))
    if mutation is None:
        with pytest.raises(main.HTTPException) as raised:
            main.submit_product_turn("conversation-1", main.ProductPromptRequest(content="synthetic original"), Request({"type": "http"}))
        assert raised.value.status_code == 503
        assert reads == []
    else:
        with pytest.raises(main.ProductError) as raised:
            main.submit_product_turn("conversation-1", main.ProductPromptRequest(content="synthetic original"), Request({"type": "http"}))
        assert raised.value.code == "prompt_outcome_unknown"
        assert len(reads) == 1


@pytest.mark.parametrize("receipt", [{}, {"accepted": False, "run_id": "run-1"},
                                     {"accepted": True}, {"accepted": True, "run_id": " "}])
def test_normal_turn_never_claims_acceptance_from_an_invalid_receipt(monkeypatch, receipt) -> None:
    session = SimpleNamespace(conversation_id="conversation-1", session_id="runtime-1", trace_id="trace-1",
                              principal=None, workspace_id="workspace-1")
    authorize_runtime_session(monkeypatch, session)
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"messages": [], "message": {"message_id": "message_original"}})
    calls = []
    monkeypatch.setattr(main, "_adapter_post", lambda *args, **kwargs: calls.append((args, kwargs)) or receipt)
    monkeypatch.setattr(main, "_adapter_prompt_receipt", lambda *_: None)
    with pytest.raises(main.ProductError) as raised:
        main.submit_product_turn("conversation-1", main.ProductPromptRequest(content="synthetic original"), Request({"type": "http"}))
    assert raised.value.status_code == 502
    assert raised.value.code == "prompt_outcome_unknown"
    assert len(calls) == 1


def test_normal_turn_reconciles_original_receipt_without_repeating_prompt(monkeypatch) -> None:
    session = SimpleNamespace(conversation_id="conversation-1", session_id="runtime-1", trace_id="trace-1",
                              principal=None, workspace_id="workspace-1")
    authorize_runtime_session(monkeypatch, session)
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"messages": [], "message": {"message_id": "message_original"}})
    writes = []
    def lost_ack(*args, **kwargs):
        writes.append((args, kwargs))
        raise main.HTTPException(status_code=504, detail="synthetic lost ack")
    def reconcile(session_id, key, content):
        assert (session_id, key, content) == ("runtime-1", "message_original", "synthetic original")
        return {"schema_version": "prompt-receipt.v1", "state": "accepted", "run_id": "run-original"}
    monkeypatch.setattr(main, "_adapter_post", lost_ack)
    monkeypatch.setattr(main, "_adapter_prompt_receipt", reconcile)
    result = main.submit_product_turn("conversation-1", main.ProductPromptRequest(content="synthetic original"), Request({"type": "http"}))
    assert result["accepted"] is True
    assert result["run_id"] == "run-original"
    assert len(writes) == 1


def test_turn_requires_a_durable_message_identity_before_runtime_submission(monkeypatch) -> None:
    session = SimpleNamespace(conversation_id="conversation-1", session_id="runtime-1", trace_id="trace-1",
                              principal=None, workspace_id="workspace-1")
    authorize_runtime_session(monkeypatch, session)
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"messages": [], "message": {"sequence": 1}})
    writes = []
    monkeypatch.setattr(main, "_adapter_post", lambda *args, **kwargs: writes.append(args) or {"accepted": True, "run_id": "run-1"})
    with pytest.raises(main.ProductError) as raised:
        main.submit_product_turn("conversation-1", main.ProductPromptRequest(content="synthetic original"), Request({"type": "http"}))
    assert raised.value.code == "prompt_outcome_unknown"
    assert writes == []


@pytest.mark.parametrize("persisted_count", [1, 2, 3])
def test_collector_reconnect_preserves_history_and_accepts_only_its_session(monkeypatch, tmp_path, persisted_count):
    import json
    from contextlib import contextmanager

    store = TraceStore(tmp_path)
    first = {"trace_id": "trace-reconnect", "session_id": "session-reconnect", "sequence": 1,
             "timestamp": "2026-09-07T00:00:00+00:00", "kind": "session.ready",
             "source": "runtime-adapter", "payload": {"status": "ready"}}
    second = {**first, "sequence": 2, "kind": "session.started", "payload": {"run_id": "a" * 32}}
    third = {**second, "sequence": 3, "kind": "session.result"}
    session = main.ProductSession("conversation-reconnect", "session-reconnect", "trace-reconnect",
                                  main.Principal(subject="owner-reconnect"), "workspace-reconnect",
                                  boot_id=TEST_BOOT_ID)
    store.append(first)
    if persisted_count >= 2:
        store.append(second)
    if persisted_count == 3:
        store.append(third)

    def stream_lines():
        yield "data: " + json.dumps(first)
        yield "data: " + json.dumps(second)
        yield "data: " + json.dumps({**third, "session_id": "another-session"})
        yield "data: " + json.dumps(third)
        session.released = True

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(status_code=200, iter_lines=stream_lines)

    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main.httpx, "stream", stream)
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": TEST_BOOT_ID})
    monkeypatch.setattr(main, "_persist_projected_answer", lambda *_: None)
    monkeypatch.setattr(main, "answer_delivery", SimpleNamespace(register=lambda *_: None))
    lifecycle = []
    monkeypatch.setattr(main, "_send_agent_lifecycle", lambda context, event, **kwargs: lifecycle.append(event))
    main._collect_trace(session)
    assert store.read("session-reconnect") == [first, second, third]
    assert store.read("another-session") == []
    assert lifecycle == [
        {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
         "sequence": 2, "outcome": "active"},
        {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
         "sequence": 3, "outcome": "completed"},
    ]


def test_collector_stops_when_exact_terminal_close_is_unconfirmed(monkeypatch, tmp_path):
    import json
    from contextlib import contextmanager

    event = {"trace_id": "trace-close", "session_id": "session-close", "sequence": 1,
             "timestamp": "2026-09-07T00:00:00+00:00", "kind": "session.result",
             "source": "runtime-adapter", "payload": {"run_id": "a" * 32}}
    store = TraceStore(tmp_path)
    later = {**event, "sequence": 2, "kind": "session.ready", "payload": {"status": "ready"}}

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(status_code=200, iter_lines=lambda: iter([
            "data: " + json.dumps(event), "data: " + json.dumps(later)]))

    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main.httpx, "stream", stream)
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": TEST_BOOT_ID})
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    monkeypatch.setattr(main, "answer_delivery", SimpleNamespace(register=lambda *_: None))
    session = main.ProductSession("conversation-close", "session-close", "trace-close",
                                  main.Principal(subject="owner-close"), "workspace-close",
                                  boot_id=TEST_BOOT_ID)
    def fail_and_release(*_, **__):
        session.released = True
        raise ValueError("unconfirmed")
    monkeypatch.setattr(main, "_send_agent_lifecycle", fail_and_release)
    main._collect_trace(session)
    assert store.read(session.session_id) == [event]


def test_product_api_requires_bearer_auth(monkeypatch) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    response = TestClient(main.app).post("/v1/agent/sessions")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert TOKEN not in response.text


@pytest.mark.parametrize("catalog_failure", [False, True])
def test_collector_retries_durable_answers_without_runtime_history(monkeypatch, tmp_path, catalog_failure):
    from contextlib import contextmanager

    store = TraceStore(tmp_path)
    first = {"trace_id": "trace-reconnect", "session_id": "session-reconnect", "sequence": 1,
             "timestamp": "2026-09-07T00:00:00+00:00", "kind": "agent.output.delta",
             "source": "runtime-adapter", "payload": {
                 "schema_version": "workflow-answer.v1", "channel": "answer",
                 "delta": "original durable answer", "truncated": False}}
    store.append(first)
    store.append({**first, "sequence": 2, "trace_id": "foreign-trace"})
    store.append({**first, "sequence": 3})
    calls = []

    def catalog(method, path, principal, workspace, *, payload):
        assert (method, path, principal.subject, workspace) == (
            "POST", "/v1/product/conversations/conversation-reconnect/messages", "owner-1", "workspace-1")
        calls.append(payload)
        if catalog_failure:
            raise main.HTTPException(status_code=503)
        return {"message": {"workflow_sequence": payload["workflow_sequence"], "role": "assistant",
                            "content": payload["content"], "message_id": "synthetic-message", "sequence": 1}}

    @contextmanager
    def missing_runtime(*args, **kwargs):
        yield SimpleNamespace(status_code=404)

    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))  # process restart
    monkeypatch.setattr(main, "_catalog_request", catalog)
    monkeypatch.setattr(main.httpx, "stream", missing_runtime)
    monkeypatch.setattr(main, "_adapter_authority", lambda: {"boot_id": TEST_BOOT_ID})
    from app.agent_lifecycle_delivery import LifecycleDelivery
    monkeypatch.setattr(main, "answer_delivery", LifecycleDelivery(tmp_path, main.trace_store, main._send_owned_answer, answers=True))
    session = main.ProductSession(
        conversation_id="conversation-reconnect", session_id="session-reconnect", trace_id="trace-reconnect",
        principal=main.Principal(subject="owner-1"), workspace_id="workspace-1", boot_id=TEST_BOOT_ID)
    main._collect_trace(session)
    assert calls == []  # Catalog I/O cannot delay or stop SSE collection.
    main.answer_delivery.run_once()
    assert [call["workflow_sequence"] for call in calls] == ([1] if catalog_failure else [1, 3])
    assert all(call["content"] == "original durable answer" for call in calls)
    assert store.read(session.session_id) == main.trace_store.read(session.session_id)


def test_product_turn_passes_only_prompt_semantics_to_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    messages: list[str] = []

    def fake_catalog(method, path, principal, workspace_id, *, payload=None, params=None):
        assert workspace_id == "workspace_bootstrap_unresolved"
        if method == "POST" and path == "/v1/product/conversations":
            return {"conversation": {"conversation_id": "conversation_1", "title": "新投研对话", "status": "active"}}
        if method == "GET" and path == "/v1/product/conversations/conversation_1":
            return {"messages": []}
        if path.endswith("/messages"):
            messages.append(str(payload["content"]))
            return {"message": {"sequence": 1, "message_id": "message_original"}}
        raise AssertionError((method, path, params))

    monkeypatch.setattr(main, "_catalog_request", fake_catalog)
    calls: list[tuple[str, dict[str, object] | None]] = []

    class FakeResponse:
        status_code = 201

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return ({"status": "ready", "boot_id": "a" * 32} if len(calls) == 1
                    else {"accepted": True, "run_id": "run-1"})

    def fake_post(url: str, *, json: dict[str, object] | None, timeout: float) -> FakeResponse:
        calls.append((url, json))
        return FakeResponse()

    monkeypatch.setattr(main.httpx, "post", fake_post)
    client = TestClient(main.app)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    created = client.post("/v1/agent/sessions", headers=headers)
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    response = client.post(
        f"/v1/agent/sessions/{session_id}/turns",
        headers=headers,
        json={"content": "summarize the health contract"},
    )

    assert response.status_code == 202
    assert calls[1][1] == {
        "content": "summarize the health contract",
        "require_model_key": True,
        "idempotency_key": "message_original",
        "conversation_context": [],
    }
    assert calls[0][1]["owner_principal"] == main.PRODUCT_PRINCIPAL
    assert messages == ["summarize the health contract"]
    assert TOKEN not in str(calls)


def test_failed_catalog_create_releases_ephemeral_runtime(monkeypatch) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    calls: list[str] = []
    monkeypatch.setattr(
        main,
        "_adapter_post",
        lambda path, **_kwargs: calls.append(path) or {"status": "ready", "boot_id": "a" * 32},
    )
    monkeypatch.setattr(
        main,
        "_catalog_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(main.HTTPException(status_code=503)),
    )

    response = TestClient(main.app).post(
        "/v1/agent/sessions", headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503
    assert calls[0] == "/internal/runtime/sessions"
    assert calls[1].endswith("/release")


def test_delete_product_session_releases_runtime_and_deletes_catalog_and_trace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    session = main.ProductSession(
        conversation_id="conversation_1",
        session_id="runtime-private",
        trace_id="trace-1",
        principal=main.Principal(subject=main.PRODUCT_PRINCIPAL),
    )
    main.product_sessions.add(session)
    store.append({
        "trace_id": "trace-1", "session_id": "runtime-private", "sequence": 1,
        "timestamp": "2026-08-28T00:00:00+00:00", "kind": "session.ready",
        "source": "runtime-adapter", "payload": {"status": "ready"},
    })
    catalog_calls: list[tuple[str, str]] = []

    def fake_catalog(method, path, *_args, **_kwargs):
        catalog_calls.append((method, path))
        if method == "GET":
            return {"conversation": {
                "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
                "trace_id": "trace-1", "status": "archived",
            }}
        return {"conversation_id": "conversation_1", "deleted": True}

    adapter_calls: list[str] = []
    monkeypatch.setattr(main, "_catalog_request", fake_catalog)
    monkeypatch.setattr(
        main, "_adapter_post",
        lambda path, **_kwargs: adapter_calls.append(path) or {"status": "closed"},
    )

    response = TestClient(main.app).delete(
        "/v1/agent/sessions/conversation_1",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert adapter_calls == ["/internal/runtime/sessions/runtime-private/release"]
    assert catalog_calls == [
        ("GET", "/v1/product/conversations/conversation_1"),
        ("DELETE", "/v1/product/conversations/conversation_1"),
    ]
    assert main.product_sessions.find_owned(
        "conversation_1", main.Principal(subject=main.PRODUCT_PRINCIPAL)
    ) is None
    assert store.read("runtime-private") == []


def test_product_trace_stream_replays_ordered_byq_events(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    session = main.ProductSession(
        conversation_id="conversation_1",
        session_id="session-1",
        trace_id="trace-1",
        principal=main.Principal(subject=main.PRODUCT_PRINCIPAL),
    )
    session.boot_id = TEST_BOOT_ID
    main.product_sessions.add(session)
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {
        "ready": True, "boot_id": TEST_BOOT_ID, "authority_epoch": 1,
    })
    store.append(
        {
            "trace_id": "trace-1",
            "session_id": "session-1",
            "sequence": 1,
            "timestamp": "2026-08-15T00:00:00+00:00",
            "kind": "session.ready",
            "source": "runtime-adapter",
            "payload": {"status": "ready"},
        }
    )
    store.close("session-1")

    response = TestClient(main.app).get(
        "/v1/workflows/conversation_1/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert "id: 1" in response.text
    assert '"kind":"session.ready"' in response.text
    assert ("session." + "event") not in response.text
    assert '"session_id":"conversation_1"' in response.text


def test_durable_replay_hides_runtime_session_and_is_owner_scoped(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    store.append({
        "trace_id": "trace-1", "session_id": "runtime-private", "sequence": 1,
        "timestamp": "2026-08-24T00:00:00+00:00", "kind": "agent.output.delta",
        "source": "runtime-adapter", "payload": {
            "schema_version": "workflow-answer.v1", "channel": "answer",
            "delta": "公开回答", "truncated": False,
        },
    })

    def fake_catalog(method, path, principal, workspace_id, *, payload=None, params=None):
        assert principal.subject == main.PRODUCT_PRINCIPAL
        assert workspace_id == "workspace_bootstrap_unresolved"
        return {
            "conversation": {
                "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
                "trace_id": "trace-1", "title": "研究", "status": "active",
            },
            "messages": [{"sequence": 1, "role": "user", "content": "问题"}],
        }

    monkeypatch.setattr(main, "_catalog_request", fake_catalog)
    response = TestClient(main.app).get(
        "/v1/agent/sessions/conversation_1", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200
    assert "runtime-private" not in response.text
    assert response.json()["events"][0]["session_id"] == "conversation_1"


def test_projected_answer_is_persisted_and_filtered_from_durable_replay(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    event = {
        "trace_id": "trace-1", "session_id": "runtime-private", "sequence": 8,
        "timestamp": "2026-08-28T00:00:08+00:00", "kind": "agent.output.delta",
        "source": "runtime-adapter", "payload": {
            "schema_version": "workflow-answer.v1", "channel": "answer",
            "delta": "持久化回答", "truncated": False,
        },
    }
    store.append(event)
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_catalog(method, path, _principal, _workspace_id, *, payload=None, params=None):
        calls.append((method, path, payload))
        if method == "POST":
            return {"message": {"workflow_sequence": 8, "role": "assistant", "content": "持久化回答",
                                "message_id": "message-1", "sequence": 1}}
        return {
            "conversation": {
                "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
                "trace_id": "trace-1", "title": "研究", "status": "active",
            },
            "messages": [{
                "message_id": "message-1", "sequence": 1, "role": "assistant",
                "content": "持久化回答", "workflow_sequence": 8,
                "created_at": "2026-08-28T00:00:08+00:00",
            }],
        }

    monkeypatch.setattr(main, "_catalog_request", fake_catalog)
    session = main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=main.Principal(subject=main.PRODUCT_PRINCIPAL),
    )
    main._persist_projected_answer(session, event)
    response = TestClient(main.app).get(
        "/v1/agent/sessions/conversation_1", headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert calls[0] == (
        "POST", "/v1/product/conversations/conversation_1/messages",
        {"role": "assistant", "content": "持久化回答", "workflow_sequence": 8},
    )
    assert response.status_code == 200
    assert response.json()["messages"][0]["role"] == "assistant"
    assert response.json()["events"] == []


@pytest.mark.parametrize("failure", [main.HTTPException(status_code=503), ValueError("invalid JSON")])
def test_answer_trace_remains_available_when_catalog_persistence_is_temporarily_unavailable(
    monkeypatch, tmp_path: Path, failure,
) -> None:
    monkeypatch.setattr(
        main, "_catalog_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    session = main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=main.Principal(subject=main.PRODUCT_PRINCIPAL),
    )
    event = {
        "kind": "agent.output.delta", "sequence": 8,
        "payload": {"delta": "仍由执行记录回放"},
    }

    assert main._persist_projected_answer(session, event) is False


@pytest.mark.parametrize("change", [{"workflow_sequence": True}, {"workflow_sequence": 9},
    {"role": "user"}, {"content": "different answer"}, {"message_id": ""}, {"sequence": False},
    {"sequence": 0}])
def test_answer_receipt_must_match_exact_durable_fragment(monkeypatch, change):
    message = {"message_id": "synthetic-message", "sequence": 1, "role": "assistant",
               "content": "synthetic answer", "workflow_sequence": 8, **change}
    monkeypatch.setattr(main, "_catalog_request", lambda *args, **kwargs: {"message": message})
    session = main.ProductSession(conversation_id="synthetic-conversation", session_id="synthetic-session",
                                  trace_id="synthetic-trace", principal=main.Principal(subject="synthetic-user"))
    assert main._persist_projected_answer(session, {"kind": "agent.output.delta", "sequence": 8,
        "payload": {"delta": "synthetic answer"}}) is False


def test_restore_attaches_surviving_runtime_and_continues_sequence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "_runtime_authority_snapshot", lambda: {
        "ready": True, "boot_id": "a" * 32,
    })
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    # Completed history requires evidence from its original turn, not merely
    # an assistant row that may have arrived after another user message.
    for sequence, kind, payload in [
        (4, "session.started", {"run_id": "old-run"}),
        (5, "agent.output.delta", {"schema_version": "workflow-answer.v1", "channel": "answer",
                                    "delta": "第一轮回答", "truncated": False}),
        (6, "session.result", {"run_id": "old-run"}),
        (7, "session.started", {"run_id": "failed-run"}),
        (8, "session.failed", {"run_id": "failed-run", "code": "model-run-failed", "retryable": True}),
    ]:
        timestamp = ("2026-08-24T00:00:00+00:00" if sequence == 7 else
                     "2026-08-24T00:00:01+00:00" if sequence == 8 else
                     f"2026-08-23T00:00:0{sequence}+00:00")
        store.append({"trace_id": "trace-1", "session_id": "runtime-private", "sequence": sequence,
                      "timestamp": timestamp, "kind": kind,
                      "source": "runtime-adapter", "payload": payload})
    monkeypatch.setattr(main, "_catalog_request", lambda *_args, **_kwargs: {"conversation": {
        "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
        "trace_id": "trace-1", "status": "active",
    }, "messages": [
        {"message_id": "user-old", "sequence": 1, "role": "user", "content": "第一轮问题",
         "created_at": "2026-08-23T00:00:00+00:00"},
        {"message_id": "answer-old", "sequence": 2, "role": "assistant", "content": "第一轮回答",
         "workflow_sequence": 5, "created_at": "2026-08-23T00:00:07+00:00"},
        {"message_id": "user-failed", "sequence": 3, "role": "user", "content": "失败后待重试的问题",
         "created_at": "2026-08-24T00:00:00+00:00"},
    ]})
    adapter_calls: list[tuple[str, dict[str, object] | None]] = []
    monkeypatch.setattr(
        main,
        "_adapter_post",
        lambda path, *, payload=None, timeout=20.0: adapter_calls.append((path, payload)) or {
            "status": "ready", "boot_id": "a" * 32},
    )
    collectors: list[str] = []
    monkeypatch.setattr(main, "_start_trace_collector", lambda session: collectors.append(session.session_id))

    restored = main._restore_product_session(
        "conversation_1", main.Principal(subject=main.PRODUCT_PRINCIPAL), "workspace_bootstrap_unresolved"
    )

    assert restored.session_id == "runtime-private"
    assert adapter_calls == [("/internal/runtime/sessions", {
        "session_id": "runtime-private", "trace_id": "trace-1",
        "workspace_id": "workspace_bootstrap_unresolved", "owner_principal": main.PRODUCT_PRINCIPAL,
        "initial_sequence": 8, "attach_live_only": True,
    })]
    assert collectors == ["runtime-private"]
    assert "runtime-private" not in store._closed


def test_conversation_context_keeps_only_supported_public_roles() -> None:
    messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "answer"},
        {"role": "internal", "content": "must not pass"},
    ]

    assert main._conversation_context(messages) == [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "answer"},
    ]


def test_disconnected_public_stream_releases_idle_runtime(monkeypatch) -> None:
    registry = main.ProductSessionRegistry()
    monkeypatch.setattr(main, "product_sessions", registry)
    monkeypatch.setattr(main, "RUNTIME_SESSION_IDLE_SECONDS", 0.01)
    released = threading.Event()
    monkeypatch.setattr(main, "_adapter_post", lambda _path, **_kwargs: released.set() or {"status": "closed"})
    session = main.ProductSession(
        conversation_id="conversation_idle", session_id="runtime-idle", trace_id="trace-idle",
        principal=main.Principal(subject=main.PRODUCT_PRINCIPAL),
    )
    registry.add(session)
    registry.begin_stream(session)

    main._schedule_idle_release(session)

    assert released.wait(timeout=1.0)
    assert registry.find_owned(session.conversation_id, session.principal) is None


def test_restore_accepts_an_adapter_session_that_survived_gateway_restart(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "_catalog_request", lambda *_args, **_kwargs: {"conversation": {
        "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
        "trace_id": "trace-1", "status": "active",
    }})

    def live_attach(*_args, **kwargs):
        assert kwargs["payload"]["attach_live_only"] is True
        return {"session_id": "runtime-private", "trace_id": "trace-1", "status": "ready",
                "boot_id": "a" * 32}

    monkeypatch.setattr(main, "_adapter_post", live_attach)
    collectors: list[str] = []
    monkeypatch.setattr(main, "_start_trace_collector", lambda session: collectors.append(session.session_id))

    restored = main._restore_product_session(
        "conversation_1", main.Principal(subject=main.PRODUCT_PRINCIPAL), "workspace_bootstrap_unresolved"
    )

    assert restored.session_id == "runtime-private"
    assert collectors == ["runtime-private"]


def test_restore_surfaces_an_interrupted_adapter_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "_catalog_request", lambda *_args, **_kwargs: {"conversation": {
        "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
        "trace_id": "trace-1", "status": "active",
    }})

    def interrupted(*_args, **_kwargs):
        error = main.HTTPException(status_code=409, detail="runtime adapter rejected the request")
        error.adapter_conflict_detail = "BYQ runtime session was interrupted; start a new Agent session"
        raise error

    monkeypatch.setattr(main, "_adapter_post", interrupted)
    # A lost-session conflict now consults the Adapter recovery binding; a
    # missing binding plus an existing business root proves interruption.
    monkeypatch.setattr(main, "_adapter_get",
        lambda *_a, **_k: (_ for _ in ()).throw(main.HTTPException(status_code=404, detail="no binding")))
    monkeypatch.setattr(main, "_runtime_root_rows", lambda _session: [{"root_run_id": "a" * 32}])
    with pytest.raises(main.ProductError) as raised:
        main._restore_product_session(
            "conversation_1", main.Principal(subject=main.PRODUCT_PRINCIPAL), "workspace_bootstrap_unresolved"
        )

    assert raised.value.code == "agent_session_interrupted"


def test_resume_reports_interruption_when_runtime_adapter_lost_the_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    session = main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved", boot_id="a" * 32,
    )
    main.product_sessions.add(session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_args, **_kwargs: {
        "conversation": {
            "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
            "trace_id": "trace-1", "status": "active",
        },
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
        ],
    })
    calls: list[str] = []

    def adapter(path, **_kwargs):
        calls.append(path)
        raise main.HTTPException(status_code=404, detail="unknown BYQ session")

    monkeypatch.setattr(main, "_adapter_post", adapter)
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    response = TestClient(main.app).post(
        "/v1/agent/sessions/conversation_1/resume",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_session_interrupted"
    assert calls == ["/internal/runtime/sessions/runtime-private/resume"]


def test_resume_interrupted_adapter_generation_requires_a_new_agent_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    main.product_sessions.add(main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved", boot_id="a" * 32,
    ))
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: {
        "conversation": {"conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
                         "trace_id": "trace-1", "status": "active"}, "messages": [],
    })
    calls = []

    def interrupted(path, **_kwargs):
        calls.append(path)
        error = main.HTTPException(status_code=409, detail="runtime session unavailable")
        error.adapter_conflict_detail = "BYQ runtime session was interrupted; start a new Agent session"
        raise error

    monkeypatch.setattr(main, "_adapter_post", interrupted)
    response = TestClient(main.app).post(
        "/v1/agent/sessions/conversation_1/resume",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_session_interrupted"
    assert "job_id" in response.json()["error"]["message"]
    assert calls == ["/internal/runtime/sessions/runtime-private/resume"]


def test_resume_failed_adapter_generation_reports_failure_without_claiming_interruption(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    main.product_sessions.add(main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved", boot_id="a" * 32,
    ))
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: {
        "conversation": {"conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
                         "trace_id": "trace-1", "status": "active"}, "messages": [],
    })

    def failed(_path, **_kwargs):
        error = main.HTTPException(status_code=409, detail="runtime session unavailable")
        error.adapter_conflict_detail = "BYQ runtime session failed; start a new Agent session"
        raise error

    monkeypatch.setattr(main, "_adapter_post", failed)
    response = TestClient(main.app).post(
        "/v1/agent/sessions/conversation_1/resume",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_session_failed"


def test_create_product_session_projects_fresh_continuity(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    monkeypatch.setattr(main, "_adapter_post", lambda *_a, **_k: {
        "status": "ready", "boot_id": "a" * 32, "continuity": "fresh"})
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: {"conversation": {
        "conversation_id": "conversation_new", "runtime_session_id": "runtime-new",
        "trace_id": "trace-new", "status": "active",
    }})

    response = TestClient(main.app).post(
        "/v1/agent/sessions", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 201
    assert response.json()["continuity"] == "fresh"


def test_resume_product_session_projects_continuity_without_dsh_identity(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    main.product_sessions.add(main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved", boot_id="a" * 32,
    ))
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: {
        "conversation": {
            "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
            "trace_id": "trace-1", "status": "active",
        },
        "messages": [],
    })
    monkeypatch.setattr(main, "_adapter_post", lambda *_a, **_k: {
        "status": "ready", "boot_id": "a" * 32,
        "resumed_from_run_id": None, "continuity": "reattached",
    })

    response = TestClient(main.app).post(
        "/v1/agent/sessions/conversation_1/resume",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["continuity"] == "reattached"
    # Framework-neutral only: no runtime/DSH private session or generation id.
    assert "runtime-private" not in str(body)
    assert "generation-" not in str(body)


def test_turn_reports_runtime_loss_without_reposting_the_persisted_user_message(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    main.product_sessions.add(main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved", boot_id="a" * 32,
    ))
    catalog_writes: list[dict[str, object]] = []

    def catalog(method, _path, _principal, _workspace_id, *, payload=None, params=None):
        if method == "POST":
            catalog_writes.append(payload)
        return {
            "conversation": {
                "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
                "trace_id": "trace-1", "status": "active",
            },
            "messages": [{"role": "user", "content": "follow-up"}],
            "message": {"message_id": "message_stable_retry"},
        }

    monkeypatch.setattr(main, "_catalog_request", catalog)
    calls: list[str] = []

    def adapter(path, **_kwargs):
        calls.append(path)
        if path.endswith("/prompt"):
            assert _kwargs["payload"]["idempotency_key"] == "message_stable_retry"
        raise main.HTTPException(status_code=404, detail="unknown BYQ session")

    monkeypatch.setattr(main, "_adapter_post", adapter)
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    response = TestClient(main.app).post(
        "/v1/agent/sessions/conversation_1/turns",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"content": "follow-up"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_session_interrupted"
    assert catalog_writes == [{"content": "follow-up"}]
    assert calls == ["/internal/runtime/sessions/runtime-private/prompt"]
