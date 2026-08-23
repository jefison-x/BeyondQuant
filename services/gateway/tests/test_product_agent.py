from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.trace_store import TraceStore


TOKEN = "phase7-product-token"


def test_product_api_requires_bearer_auth(monkeypatch) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    response = TestClient(main.app).post("/v1/agent/sessions")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert TOKEN not in response.text


def test_product_turn_passes_only_prompt_semantics_to_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    messages: list[str] = []

    def fake_catalog(method, path, principal, *, payload=None, params=None):
        if method == "POST" and path == "/v1/product/conversations":
            return {"conversation": {"conversation_id": "conversation_1", "title": "新投研对话", "status": "active"}}
        if path.endswith("/messages"):
            messages.append(str(payload["content"]))
            return {"message": {"sequence": 1}}
        raise AssertionError((method, path, params))

    monkeypatch.setattr(main, "_catalog_request", fake_catalog)
    calls: list[tuple[str, dict[str, object] | None]] = []

    class FakeResponse:
        status_code = 201

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"status": "ready"} if len(calls) == 1 else {"run_id": "run-1"}

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
    }
    assert calls[0][1]["owner_principal"] == main.PRODUCT_PRINCIPAL
    assert messages == ["summarize the health contract"]
    assert TOKEN not in str(calls)


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
    assert "id: 1" in response.text
    assert '"kind":"session.ready"' in response.text
    assert ("session." + "event") not in response.text
    assert '"session_id":"conversation_1"' in response.text


def test_durable_replay_hides_runtime_session_and_is_owner_scoped(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
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

    def fake_catalog(method, path, principal, *, payload=None, params=None):
        assert principal.subject == main.PRODUCT_PRINCIPAL
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
