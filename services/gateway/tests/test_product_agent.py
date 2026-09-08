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


@pytest.mark.parametrize("mutation", [None, {"session_id": "other-session"},
    {"idempotency_key": "other-message"}, {"content_sha256": "0" * 64},
    {"accepted": True}, {"accepted": 0}, {"extra": "untrusted"}, {"code": "some-server-error"}])
def test_only_exact_pre_admission_rejection_is_known_not_accepted(monkeypatch, mutation):
    import hashlib
    import httpx

    session = SimpleNamespace(conversation_id="conversation-1", session_id="runtime-1", trace_id="trace-1",
                              principal=None, workspace_id="workspace-1")
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"message": {"message_id": "message_original"}})
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
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"message": {"message_id": "message_original"}})
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
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"message": {"message_id": "message_original"}})
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
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_catalog_request", lambda *_, **__: {"message": {"sequence": 1}})
    writes = []
    monkeypatch.setattr(main, "_adapter_post", lambda *args, **kwargs: writes.append(args) or {"accepted": True, "run_id": "run-1"})
    with pytest.raises(main.ProductError) as raised:
        main.submit_product_turn("conversation-1", main.ProductPromptRequest(content="synthetic original"), Request({"type": "http"}))
    assert raised.value.code == "prompt_outcome_unknown"
    assert writes == []


@pytest.mark.parametrize("persisted_count", [1, 2])
def test_collector_reconnect_preserves_history_and_accepts_only_its_session(monkeypatch, tmp_path, persisted_count):
    import json
    from contextlib import contextmanager

    store = TraceStore(tmp_path)
    first = {"trace_id": "trace-reconnect", "session_id": "session-reconnect", "sequence": 1,
             "timestamp": "2026-09-07T00:00:00+00:00", "kind": "session.ready",
             "source": "runtime-adapter", "payload": {"status": "ready"}}
    second = {**first, "sequence": 2, "kind": "session.started", "payload": {"run_id": "a" * 32}}
    third = {**second, "sequence": 3, "kind": "session.result"}
    store.append(first)
    if persisted_count == 2:
        store.append(second)

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(status_code=200, iter_lines=lambda: iter([
            "data: " + json.dumps(first),
            "data: " + json.dumps(second),
            "data: " + json.dumps({**third, "session_id": "another-session"}),
            "data: " + json.dumps(third),
        ]))

    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main.httpx, "stream", stream)
    monkeypatch.setattr(main, "_persist_projected_answer", lambda *_: None)
    monkeypatch.setattr(main, "answer_delivery", SimpleNamespace(register=lambda *_: None))
    main._collect_trace(SimpleNamespace(session_id="session-reconnect", trace_id="trace-reconnect", released=False))
    assert store.read("session-reconnect") == [first, second, third]
    assert store.read("another-session") == []


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
    from app.agent_lifecycle_delivery import LifecycleDelivery
    monkeypatch.setattr(main, "answer_delivery", LifecycleDelivery(tmp_path, main.trace_store, main._send_owned_answer, answers=True))
    session = main.ProductSession(
        conversation_id="conversation-reconnect", session_id="session-reconnect", trace_id="trace-reconnect",
        principal=main.Principal(subject="owner-1"), workspace_id="workspace-1")
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
            return {"status": "ready"} if len(calls) == 1 else {"accepted": True, "run_id": "run-1"}

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
        lambda path, **_kwargs: calls.append(path) or {"status": "ready"},
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
    main.product_sessions.add(session)
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


def test_restore_recreates_runtime_after_full_restart_and_continues_sequence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path)
    monkeypatch.setattr(main, "trace_store", store)
    store.append({
        "trace_id": "trace-1", "session_id": "runtime-private", "sequence": 7,
        "timestamp": "2026-08-24T00:00:00+00:00", "kind": "session.failed",
        "source": "runtime-adapter", "payload": {"code": "model-run-failed", "retryable": True},
    })
    monkeypatch.setattr(main, "_catalog_request", lambda *_args, **_kwargs: {"conversation": {
        "conversation_id": "conversation_1", "runtime_session_id": "runtime-private",
        "trace_id": "trace-1", "status": "active",
    }, "messages": [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
        {"role": "user", "content": "失败后待重试的问题"},
    ]})
    adapter_calls: list[tuple[str, dict[str, object] | None]] = []
    monkeypatch.setattr(
        main,
        "_adapter_post",
        lambda path, *, payload=None, timeout=20.0: adapter_calls.append((path, payload)) or {"status": "ready"},
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
        "initial_sequence": 7,
        "conversation_recovery": {
            "schema_version": "conversation-recovery.v2",
            "session_id": "runtime-private", "trace_id": "trace-1",
            "status": "needs_confirmation", "unanswered_turn": None,
            "failure": {"sequence": 7, "run_id": None, "code": "model-run-failed"},
        },
        "conversation_context": [
            {"role": "user", "content": "第一轮问题"},
            {"role": "assistant", "content": "第一轮回答"},
        ],
    })]
    assert collectors == ["runtime-private"]
    assert "runtime-private" not in store._closed


def test_conversation_context_keeps_recent_completed_public_turns_only() -> None:
    messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "failed prompt"},
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

    def conflict(*_args, **_kwargs):
        raise main.HTTPException(status_code=409, detail="already exists")

    monkeypatch.setattr(main, "_adapter_post", conflict)
    collectors: list[str] = []
    monkeypatch.setattr(main, "_start_trace_collector", lambda session: collectors.append(session.session_id))

    restored = main._restore_product_session(
        "conversation_1", main.Principal(subject=main.PRODUCT_PRINCIPAL), "workspace_bootstrap_unresolved"
    )

    assert restored.session_id == "runtime-private"
    assert collectors == ["runtime-private"]


def test_resume_rehydrates_when_only_runtime_adapter_restarted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    session = main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved",
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
        if calls == ["/internal/runtime/sessions/runtime-private/resume"]:
            raise main.HTTPException(status_code=404, detail="lost")
        return {"status": "ready", "resumed_from_run_id": None}

    monkeypatch.setattr(main, "_adapter_post", adapter)
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    response = TestClient(main.app).post(
        "/v1/agent/sessions/conversation_1/resume",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert calls == [
        "/internal/runtime/sessions/runtime-private/resume",
        "/internal/runtime/sessions",
        "/internal/runtime/sessions/runtime-private/resume",
    ]


def test_turn_rehydrates_after_runtime_loss_without_duplicating_user_message(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    main.product_sessions.add(main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-private", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved",
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
        if calls == ["/internal/runtime/sessions/runtime-private/prompt"]:
            raise main.HTTPException(status_code=404, detail="lost")
        return {"status": "ready", "accepted": True, "run_id": "run-rehydrated"}

    monkeypatch.setattr(main, "_adapter_post", adapter)
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    response = TestClient(main.app).post(
        "/v1/agent/sessions/conversation_1/turns",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"content": "follow-up"},
    )
    assert response.status_code == 202
    assert response.json()["run_id"] == "run-rehydrated"
    assert catalog_writes == [{"content": "follow-up"}]
    assert calls == [
        "/internal/runtime/sessions/runtime-private/prompt",
        "/internal/runtime/sessions",
        "/internal/runtime/sessions/runtime-private/prompt",
    ]
