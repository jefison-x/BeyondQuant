from pathlib import Path

from fastapi.testclient import TestClient

from app import main


def test_maintenance_rejects_before_user_history_or_runtime_writes(monkeypatch, tmp_path: Path):
    gate = tmp_path / "admission.state"
    gate.write_text("closed\n")
    monkeypatch.setenv("BYQ_CHAT_ADMISSION_FILE", str(gate))
    monkeypatch.setattr(main, "_product_session", lambda *_: (_ for _ in ()).throw(AssertionError("session touched")))
    monkeypatch.setattr(main, "_adapter_post", lambda *_, **__: (_ for _ in ()).throw(AssertionError("runtime touched")))
    client = TestClient(main.app)
    for path, body in (
        ("/v1/agent/sessions", {}),
        ("/v1/agent/sessions/synthetic/turns", {"content": "synthetic retained input"}),
        ("/v1/agent/sessions/synthetic/resume", {}),
        ("/internal/runtime/sessions", {"session_id": "synthetic", "trace_id": "synthetic"}),
        ("/internal/runtime/sessions/synthetic/prompt", {"content": "synthetic"}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "chat_maintenance"
        assert str(gate) not in response.text
    assert client.get("/healthz").status_code == 200


def test_maintenance_preserves_queued_approval_without_claiming(monkeypatch, tmp_path: Path):
    gate = tmp_path / "admission.state"
    gate.write_text("closed\n")
    monkeypatch.setenv("BYQ_CHAT_ADMISSION_FILE", str(gate))
    monkeypatch.setattr(main, "_backend_request", lambda *_, **__: (_ for _ in ()).throw(AssertionError("claimed")))
    assert main.continue_approval_conversation(None, "conversation", "approval", "approved", "action") == {"status": "queued"}


def test_approval_continuation_rehydrates_exact_session_after_adapter_restart(monkeypatch):
    monkeypatch.delenv("BYQ_CHAT_ADMISSION_FILE", raising=False)
    old = main.ProductSession("conversation", "old-runtime", "trace", main.Principal(subject="synthetic"))
    restored = main.ProductSession("conversation", "new-runtime", "trace", old.principal)
    monkeypatch.setattr(main, "_trusted_agent_headers", lambda _: {})
    monkeypatch.setattr(main, "_product_session", lambda *_: old)
    replacements, prompts, states = [], [], []
    monkeypatch.setattr(main, "_replace_lost_runtime_session", lambda session: replacements.append(session) or restored)

    def backend(method, path, payload, **kwargs):
        states.append(payload["status"])
        return {"approval": {"continuation_changed": True, "continuation_status": payload["status"]}}

    def adapter(path, **kwargs):
        prompts.append((path, kwargs["payload"]))
        if len(prompts) == 1:
            raise main.HTTPException(status_code=404, detail="missing")
        return {"run_id": "one-run"}

    monkeypatch.setattr(main, "_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", adapter)
    result = main.continue_approval_conversation(None, "conversation", "approval", "approved", "action")
    assert result == {"status": "submitted"}
    assert states == ["submitting", "submitted"]
    assert replacements == [old]
    assert prompts[0][0].endswith("old-runtime/prompt")
    assert prompts[1][0].endswith("new-runtime/prompt")
    assert prompts[0][1] == prompts[1][1]
    assert prompts[1][1]["idempotency_key"] == "approval-continuation-approval"
