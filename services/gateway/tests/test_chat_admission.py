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
        if payload["status"] != "submitting":
            assert payload["expected_attempt"] == 3
        return {"approval": {"continuation_changed": True, "continuation_status": payload["status"], "continuation_attempt": 3}}

    def adapter(path, **kwargs):
        prompts.append((path, kwargs["payload"]))
        if len(prompts) == 1:
            raise main.HTTPException(status_code=404, detail="missing")
        return {"accepted": True, "run_id": "one-run"}

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


def test_approval_continuation_preserves_unknown_receipts_without_resubmission(monkeypatch):
    monkeypatch.delenv("BYQ_CHAT_ADMISSION_FILE", raising=False)
    session = main.ProductSession("conversation", "runtime", "trace", main.Principal(subject="synthetic"))
    monkeypatch.setattr(main, "_trusted_agent_headers", lambda _: {})
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    monkeypatch.setattr(main, "_adapter_prompt_receipt", lambda *args: None)
    for mode in ("timeout", "malformed", "rejected"):
        states, calls = [], []
        def backend(method, path, payload, **kwargs):
            states.append(payload["status"])
            return {"approval": {"continuation_changed": True, "continuation_status": payload["status"], "continuation_attempt": 1}}
        def adapter(*args, **kwargs):
            calls.append(1)
            if mode == "malformed":
                return {"accepted": True}
            raise main.HTTPException(status_code=503 if mode == "timeout" else 409, detail="synthetic")
        monkeypatch.setattr(main, "_backend_request", backend)
        monkeypatch.setattr(main, "_adapter_post", adapter)
        expected = "failed" if mode == "rejected" else "outcome_unknown"
        assert main.continue_approval_conversation(None, "conversation", "approval", "approved", "action") == {"status": expected}
        assert states == ["submitting", expected] and len(calls) == 1


def test_approval_continuation_reconciles_the_original_accepted_prompt(monkeypatch):
    monkeypatch.delenv("BYQ_CHAT_ADMISSION_FILE", raising=False)
    session = main.ProductSession("conversation", "runtime", "trace", main.Principal(subject="synthetic"))
    monkeypatch.setattr(main, "_trusted_agent_headers", lambda _: {})
    monkeypatch.setattr(main, "_product_session", lambda *_: session)
    states, writes, reads = [], [], []
    def backend(method, path, payload, **kwargs):
        states.append(payload["status"])
        return {"approval": {"continuation_changed": True, "continuation_status": payload["status"], "continuation_attempt": 1}}
    def submit(*args, **kwargs):
        writes.append(kwargs["payload"])
        raise main.HTTPException(status_code=503, detail="lost response")
    def lookup(session_id, key, content):
        reads.append((session_id, key, content))
        return {"schema_version": "prompt-receipt.v1", "state": "accepted", "run_id": "original-run"}
    monkeypatch.setattr(main, "_backend_request", backend)
    monkeypatch.setattr(main, "_adapter_post", submit)
    monkeypatch.setattr(main, "_adapter_prompt_receipt", lookup)
    assert main.continue_approval_conversation(None, "conversation", "approval", "approved", "action") == {"status": "submitted"}
    assert states == ["submitting", "submitted"] and len(writes) == len(reads) == 1
    assert reads[0] == ("runtime", writes[0]["idempotency_key"], writes[0]["content"])


def test_approval_continuation_refuses_a_claim_without_fence(monkeypatch):
    monkeypatch.delenv("BYQ_CHAT_ADMISSION_FILE", raising=False)
    monkeypatch.setattr(main, "_trusted_agent_headers", lambda _: {})
    monkeypatch.setattr(main, "_backend_request", lambda *args, **kwargs: {
        "approval": {"continuation_changed": True, "continuation_status": "submitting"},
    })
    monkeypatch.setattr(main, "_product_session", lambda *_: (_ for _ in ()).throw(AssertionError("unfenced prompt")))
    assert main.continue_approval_conversation(None, "conversation", "approval", "approved", "action") == {"status": "failed"}


def test_prompt_receipt_lookup_is_exact_and_never_sends_prompt_text(monkeypatch):
    calls = []
    def lookup(url, **kwargs):
        calls.append((url, kwargs))
        return main.httpx.Response(200, request=main.httpx.Request("GET", url), json={
            "schema_version": "prompt-receipt.v1", "state": "accepted", "run_id": "original-run"})
    monkeypatch.setattr(main.httpx, "get", lookup)
    assert main._adapter_prompt_receipt("original-session", "original-key", "synthetic private instruction")["run_id"] == "original-run"
    assert calls[0][0].endswith("/original-session/prompts/reconcile")
    assert calls[0][1]["params"]["idempotency_key"] == "original-key"
    assert len(calls[0][1]["params"]["content_sha256"]) == 64
    assert "synthetic private instruction" not in str(calls)
