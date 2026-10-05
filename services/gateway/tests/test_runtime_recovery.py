from __future__ import annotations

from pathlib import Path

import pytest

from app import main
from app.trace_store import TraceStore


PRINCIPAL = main.Principal(subject="alice")
SESSION_ID = "runtime-private"
TRACE_ID = "trace-one"
CONVERSATION_ID = "conversation-one"
WORKSPACE_ID = "workspace-one"
ROOT_ID = "c" * 32
OLD_BOOT_ID = "b" * 32
NEW_BOOT_ID = "a" * 32


def _binding(state: str = "transfer_required") -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "byq-runtime-recovery-binding.v1",
        "state": state,
        "session_id": SESSION_ID,
        "trace_id": TRACE_ID,
        "owner_principal": PRINCIPAL.subject,
        "workspace_id": WORKSPACE_ID,
        "root_run_id": ROOT_ID,
        "previous_boot_id": OLD_BOOT_ID,
        "previous_authority_epoch": 7,
        "sequence": 4,
    }
    if state == "settled":
        value["settlement_receipt"] = {
            "schema_version": "agent-run-lifecycle-receipt.v1",
            "sequence": 9,
            "root_run_id": ROOT_ID,
            "event_sha256": "d" * 64,
        }
    return value


def _conversation_catalog(*_args, **_kwargs):
    return {"conversation": {
        "conversation_id": CONVERSATION_ID,
        "runtime_session_id": SESSION_ID,
        "trace_id": TRACE_ID,
        "status": "active",
    }}


def _lost_attach(*_args, **kwargs):
    if kwargs.get("payload", {}).get("attach_live_only") is True:
        raise main.HTTPException(status_code=404, detail="runtime session not found")
    return {
        "session_id": SESSION_ID,
        "trace_id": TRACE_ID,
        "boot_id": NEW_BOOT_ID,
        "status": "idle",
        "active_prompt": False,
        "continuity": "reattached",
        "resumed_from_run_id": ROOT_ID,
    }


def _trace_event(sequence: int) -> dict[str, object]:
    return {
        "session_id": SESSION_ID,
        "trace_id": TRACE_ID,
        "sequence": sequence,
        "timestamp": "2026-10-04T00:00:00+00:00",
        "source": "runtime-adapter",
        "kind": "session.progress",
        "payload": {},
    }


def test_restore_transfers_exact_backend_proof_before_adapter_recovery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path)
    store.append(_trace_event(7))
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_catalog_request", _conversation_catalog)
    binding = _binding()
    order: list[str] = []

    def adapter_get(path, **_kwargs):
        assert path == f"/internal/runtime/sessions/{SESSION_ID}/recovery-binding"
        order.append("binding")
        return binding

    monkeypatch.setattr(main, "_adapter_get", adapter_get)
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *_args, **_kwargs: (
        order.append("roots") or {"schema_version": "byq-business-root-status.v1", "roots": [{
            "root_run_id": ROOT_ID, "status": "active", "authority_status": "authority_revoked_unconfirmed",
            "terminal_sequence": None, "terminal_event_sha256": None,
            "terminal_acp_ingress_sequence": None, "terminal_acp_ingress_sha256": None,
            "terminal_unknown_claim_count": None, "terminal_unknown_claims_sha256": None,
        }]}
    ))
    transfer_receipt = {
        "schema_version": "byq-runtime-root-authority-transfer-receipt.v1",
        "root_run_id": ROOT_ID,
        "previous_boot_id": OLD_BOOT_ID,
        "previous_authority_epoch": 7,
        "boot_id": NEW_BOOT_ID,
        "authority_epoch": 1,
        "status": "transferred",
    }
    transfer_calls = []

    def transfer(url, *, json, headers, timeout):
        order.append("transfer")
        transfer_calls.append((url, json, headers, timeout))
        return main.httpx.Response(
            200, request=main.httpx.Request("POST", url), json={"receipt": transfer_receipt},
        )

    monkeypatch.setattr(main.httpx, "post", transfer)
    adapter_calls: list[tuple[str, dict[str, object] | None]] = []

    def adapter_post(path, *, payload=None, timeout=20.0):
        adapter_calls.append((path, payload))
        if payload and payload.get("attach_live_only") is True:
            order.append("attach")
            raise main.HTTPException(status_code=404, detail="runtime session not found")
        order.append("recover")
        return {
            "session_id": SESSION_ID,
            "trace_id": TRACE_ID,
            "boot_id": NEW_BOOT_ID,
            "status": "idle",
            "active_prompt": False,
            "continuity": "reattached",
            "resumed_from_run_id": ROOT_ID,
        }

    monkeypatch.setattr(main, "_adapter_post", adapter_post)
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)

    restored = main._restore_product_session(CONVERSATION_ID, PRINCIPAL, WORKSPACE_ID)

    assert restored.boot_id == NEW_BOOT_ID
    assert order == ["attach", "binding", "roots", "transfer", "recover"]
    assert transfer_calls == [(
        f"{main.BACKEND_URL}/internal/runtime-authority/roots/{ROOT_ID}/transfer",
        {
            "schema_version": "byq-runtime-root-authority-transfer.v1",
            "previous_boot_id": OLD_BOOT_ID,
            "previous_authority_epoch": 7,
            "boot_id": NEW_BOOT_ID,
            "authority_epoch": 1,
        },
        {
            "Authorization": "Bearer test-runtime-authority-token",
            "x-byq-owner-principal": PRINCIPAL.subject,
            "x-byq-workspace-id": WORKSPACE_ID,
            "x-byq-session-id": SESSION_ID,
            "x-byq-trace-id": TRACE_ID,
        },
        5.0,
    )]
    assert adapter_calls[-1] == (
        f"/internal/runtime/sessions/{SESSION_ID}/recover",
        {"receipt": transfer_receipt, "initial_sequence": 7},
    )
    assert not any(path.endswith("/prompt") for path, _payload in adapter_calls)


def test_settled_recovery_requires_backend_terminal_ack_match(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path)
    store.append(_trace_event(5))
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_catalog_request", _conversation_catalog)
    binding = _binding("settled")
    monkeypatch.setattr(main, "_adapter_get", lambda *_a, **_k: binding)
    roots_calls = []
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda method, path, **kwargs: (
        roots_calls.append((method, path, kwargs)) or {
            "schema_version": "byq-business-root-status.v1",
            "roots": [{
                "root_run_id": ROOT_ID,
                "status": "failed",
                "authority_status": "closed",
                "terminal_sequence": 9,
                "terminal_event_sha256": "d" * 64,
                "terminal_acp_ingress_sequence": 0,
                "terminal_acp_ingress_sha256": "a" * 64,
                "terminal_unknown_claim_count": 0,
                "terminal_unknown_claims_sha256": "e" * 64,
            }],
        }
    ))
    calls: list[tuple[str, dict[str, object] | None]] = []

    def adapter_post(path, *, payload=None, timeout=20.0):
        calls.append((path, payload))
        if payload and payload.get("attach_live_only") is True:
            raise main.HTTPException(status_code=404, detail="runtime session not found")
        return {
            "session_id": SESSION_ID,
            "trace_id": TRACE_ID,
            "boot_id": NEW_BOOT_ID,
            "status": "idle",
            "active_prompt": False,
            "continuity": "reattached",
            "resumed_from_run_id": None,
        }

    monkeypatch.setattr(main, "_adapter_post", adapter_post)
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)

    restored = main._restore_product_session(CONVERSATION_ID, PRINCIPAL, WORKSPACE_ID)

    assert restored.boot_id == NEW_BOOT_ID
    assert len(roots_calls) == 1
    assert roots_calls[0][0:2] == (
        "GET", f"/internal/runtime-authority/sessions/{SESSION_ID}/roots",
    )
    assert calls[-1] == (
        f"/internal/runtime/sessions/{SESSION_ID}/recover",
        {"receipt": binding["settlement_receipt"], "initial_sequence": 5},
    )


def test_settled_acp_recovery_requires_frozen_backend_cursor_and_no_unknown_claim(monkeypatch) -> None:
    session = main.ProductSession(CONVERSATION_ID, SESSION_ID, TRACE_ID, PRINCIPAL, WORKSPACE_ID)
    binding = _binding("settled")
    row = {"root_run_id": ROOT_ID, "status": "failed", "authority_status": "closed",
           "terminal_sequence": 9, "terminal_event_sha256": "d" * 64,
           "terminal_acp_ingress_sequence": 0, "terminal_acp_ingress_sha256": "a" * 64,
           "terminal_unknown_claim_count": 0, "terminal_unknown_claims_sha256": "e" * 64}
    monkeypatch.setattr(main, "_runtime_root_rows", lambda _session: [row])
    assert main._verify_settled_recovery_binding(binding, session) == binding["settlement_receipt"]
    for altered in ({**row, "terminal_acp_ingress_sequence": None},
                    {**row, "terminal_unknown_claim_count": 1}):
        monkeypatch.setattr(main, "_runtime_root_rows", lambda _session, value=altered: [value])
        with pytest.raises(main.ProductError):
            main._verify_settled_recovery_binding(binding, session)


def test_backend_closed_before_adapter_ack_recovers_without_transfer_or_prompt(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path)
    terminal = {**_trace_event(9), "kind": "session.failed",
                "payload": {"run_id": ROOT_ID, "code": "runtime-interrupted"}}
    store.append(terminal)
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "_catalog_request", _conversation_catalog)
    monkeypatch.setattr(main, "_adapter_get", lambda *_args, **_kwargs: _binding("transfer_required"))
    receipt = main.lifecycle_receipt(main.project_lifecycle_event(terminal, SESSION_ID, TRACE_ID))
    row = {"root_run_id": ROOT_ID, "status": "failed", "authority_status": "closed",
           "terminal_sequence": receipt["sequence"], "terminal_event_sha256": receipt["event_sha256"],
           "terminal_acp_ingress_sequence": 1, "terminal_acp_ingress_sha256": "a" * 64,
           "terminal_unknown_claim_count": 0, "terminal_unknown_claims_sha256": "e" * 64}
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *_args, **_kwargs: {
        "schema_version": "byq-business-root-status.v1", "roots": [row]})
    calls: list[tuple[str, object]] = []
    def adapter_post(path, *, payload=None, timeout=20.0):
        calls.append((path, payload))
        if payload and payload.get("attach_live_only") is True:
            raise main.HTTPException(status_code=404, detail="runtime session not found")
        return {"session_id": SESSION_ID, "trace_id": TRACE_ID, "boot_id": NEW_BOOT_ID,
                "status": "idle", "active_prompt": False, "continuity": "reattached",
                "resumed_from_run_id": None}
    monkeypatch.setattr(main, "_adapter_post", adapter_post)
    monkeypatch.setattr(main.httpx, "post", lambda *_args, **_kwargs: pytest.fail("closed root must not transfer"))
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)
    assert main._restore_product_session(CONVERSATION_ID, PRINCIPAL, WORKSPACE_ID).boot_id == NEW_BOOT_ID
    assert calls[-1] == (f"/internal/runtime/sessions/{SESSION_ID}/recover",
                          {"receipt": receipt, "initial_sequence": 9})


def test_backend_root_status_rejects_partial_or_unknown_terminal_snapshot(monkeypatch) -> None:
    session = main.ProductSession(CONVERSATION_ID, SESSION_ID, TRACE_ID, PRINCIPAL, WORKSPACE_ID)
    row = {"root_run_id": ROOT_ID, "status": "completed", "authority_status": "closed",
           "terminal_sequence": 3, "terminal_event_sha256": "d" * 64,
           "terminal_acp_ingress_sequence": 2, "terminal_acp_ingress_sha256": "a" * 64,
           "terminal_unknown_claim_count": 0, "terminal_unknown_claims_sha256": "e" * 64}
    def project(value):
        monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *_args, **_kwargs: {
            "schema_version": "byq-business-root-status.v1", "roots": [value]})
        return main._runtime_root_rows(session)
    assert project(row) == [row]
    legacy = {**row, "terminal_acp_ingress_sequence": None,
              "terminal_acp_ingress_sha256": None,
              "terminal_unknown_claim_count": None,
              "terminal_unknown_claims_sha256": None}
    assert project(legacy) == [legacy]
    with pytest.raises(main.HTTPException):
        project({**row, "terminal_acp_ingress_sha256": None})
    with pytest.raises(main.HTTPException):
        project({**row, "terminal_unknown_claim_count": -1})


def test_missing_recovery_binding_needs_zero_backend_roots_before_fresh_shell(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "_catalog_request", _conversation_catalog)
    monkeypatch.setattr(main, "_adapter_get", lambda *_a, **_k: (_ for _ in ()).throw(
        main.HTTPException(status_code=404, detail="not found")))
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *_a, **_k: {
        "schema_version": "byq-business-root-status.v1", "roots": [],
    })
    calls: list[tuple[str, dict[str, object] | None]] = []

    def adapter_post(path, *, payload=None, timeout=20.0):
        calls.append((path, payload))
        if payload and payload.get("attach_live_only") is True:
            raise main.HTTPException(status_code=404, detail="runtime session not found")
        return {"session_id": SESSION_ID, "trace_id": TRACE_ID, "boot_id": NEW_BOOT_ID}

    monkeypatch.setattr(main, "_adapter_post", adapter_post)
    monkeypatch.setattr(main, "_start_trace_collector", lambda _session: None)

    main._restore_product_session(CONVERSATION_ID, PRINCIPAL, WORKSPACE_ID)

    assert calls[-1] == (
        "/internal/runtime/sessions",
        {
            "session_id": SESSION_ID,
            "trace_id": TRACE_ID,
            "workspace_id": WORKSPACE_ID,
            "owner_principal": PRINCIPAL.subject,
            "initial_sequence": 0,
        },
    )


def test_missing_binding_with_backend_root_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    monkeypatch.setattr(main, "trace_store", TraceStore(tmp_path))
    monkeypatch.setattr(main, "_catalog_request", _conversation_catalog)
    monkeypatch.setattr(main, "_adapter_get", lambda *_a, **_k: (_ for _ in ()).throw(
        main.HTTPException(status_code=404, detail="not found")))
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *_a, **_k: {
        "schema_version": "byq-business-root-status.v1",
        "roots": [{
            "root_run_id": ROOT_ID,
            "status": "active",
            "authority_status": "authority_revoked_unconfirmed",
            "terminal_sequence": None,
            "terminal_event_sha256": None,
        }],
    })
    calls = []

    def adapter_post(path, *, payload=None, timeout=20.0):
        calls.append(path)
        raise main.HTTPException(status_code=404, detail="runtime session not found")

    monkeypatch.setattr(main, "_adapter_post", adapter_post)

    with pytest.raises(main.ProductError) as raised:
        main._restore_product_session(CONVERSATION_ID, PRINCIPAL, WORKSPACE_ID)

    assert raised.value.code == "agent_session_interrupted"
    assert calls == ["/internal/runtime/sessions"]


def test_cached_product_session_from_old_boot_forces_recovery(monkeypatch) -> None:
    registry = main.ProductSessionRegistry()
    registry.add(main.ProductSession(
        CONVERSATION_ID, SESSION_ID, TRACE_ID, PRINCIPAL,
        workspace_id=WORKSPACE_ID, boot_id=OLD_BOOT_ID,
    ))
    monkeypatch.setattr(main, "product_sessions", registry)
    monkeypatch.setattr(main, "_trusted_request_identity", lambda _request: (PRINCIPAL, WORKSPACE_ID))
    calls = []
    replacement = main.ProductSession(
        CONVERSATION_ID, SESSION_ID, TRACE_ID, PRINCIPAL,
        workspace_id=WORKSPACE_ID, boot_id=NEW_BOOT_ID,
    )

    def restore(*args, **kwargs):
        calls.append((args, kwargs))
        return replacement

    monkeypatch.setattr(main, "_restore_product_session", restore)

    assert main._product_session(None, CONVERSATION_ID) is replacement
    assert calls == [((CONVERSATION_ID, PRINCIPAL, WORKSPACE_ID), {"force_recovery": True})]
    assert registry.find_owned(CONVERSATION_ID, PRINCIPAL) is None


def test_public_resume_does_not_send_byq_history_to_native_acp_resume(monkeypatch) -> None:
    session = main.ProductSession(
        CONVERSATION_ID, SESSION_ID, TRACE_ID, PRINCIPAL,
        workspace_id=WORKSPACE_ID, boot_id=NEW_BOOT_ID,
    )
    monkeypatch.setattr(main, "_product_session", lambda *_a: session)
    monkeypatch.setattr(main, "_require_session_runtime_authority", lambda _session: NEW_BOOT_ID)
    monkeypatch.setattr(main, "_runtime_conversation_payload", lambda *_a, **_k: pytest.fail(
        "native ACP resume must not receive public BYQ history"))
    calls = []
    monkeypatch.setattr(main, "_adapter_post", lambda path, *, payload=None, **_k: (
        calls.append((path, payload)) or {
            "status": "idle", "continuity": "reattached", "resumed_from_run_id": ROOT_ID,
        }
    ))

    result = main.resume_product_session(CONVERSATION_ID, None)

    assert result["continuity"] == "reattached"
    assert calls == [
        (f"/internal/runtime/sessions/{SESSION_ID}/resume", {}),
    ]


def test_turn_retries_same_message_until_old_root_ack_barrier_clears(monkeypatch) -> None:
    session = main.ProductSession(
        CONVERSATION_ID, SESSION_ID, TRACE_ID, PRINCIPAL,
        workspace_id=WORKSPACE_ID, boot_id=NEW_BOOT_ID,
    )
    monkeypatch.setattr(main, "_product_session", lambda *_a: session)
    monkeypatch.setattr(main, "_require_session_runtime_authority", lambda _session: NEW_BOOT_ID)
    monkeypatch.setattr(main, "_runtime_conversation_payload", lambda *_a, **_k: {"conversation_context": []})
    monkeypatch.setattr(main, "time", type("Clock", (), {"sleep": staticmethod(lambda _delay: None)})())
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: {
        "message": {"message_id": "message-stable-123"},
    })
    acknowledged = False
    submitted: list[dict[str, object]] = []

    def adapter_post(path, *, payload=None, timeout=20.0):
        nonlocal acknowledged
        assert path == f"/internal/runtime/sessions/{SESSION_ID}/prompt"
        submitted.append(payload)
        if not acknowledged:
            error = main.HTTPException(status_code=409, detail="runtime session is not available")
            error.adapter_conflict_detail = "previous turn domain cleanup is not yet acknowledged"
            acknowledged = True
            raise error
        return {"accepted": True, "run_id": "new-root-run"}

    monkeypatch.setattr(main, "_adapter_post", adapter_post)

    result = main.submit_product_turn(
        CONVERSATION_ID, main.ProductPromptRequest(content="next question"), None,
    )

    assert result["accepted"] is True
    assert len(submitted) == 2
    assert submitted[0]["idempotency_key"] == submitted[1]["idempotency_key"] == "message-stable-123"
