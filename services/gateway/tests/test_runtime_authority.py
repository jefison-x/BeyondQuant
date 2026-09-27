from fastapi.testclient import TestClient
import pytest

from app import main
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event


BOOT_ID = "a" * 32
TOKEN = "test-runtime-authority-token"
SYNC_RUNTIME_AUTHORITY = main._sync_runtime_authority


def _response(url, body):
    return main.httpx.Response(200, request=main.httpx.Request("GET", url), json=body)


def test_transport_health_is_separate_from_agent_authority(monkeypatch):
    main._set_runtime_authority_state(ready=False)
    client = TestClient(main.app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    response = client.get("/agent-readyz")
    assert response.status_code == 503


def test_agent_mutations_fail_closed_before_adapter_calls(monkeypatch):
    main._set_runtime_authority_state(ready=False)
    monkeypatch.setattr(main, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(main, "_adapter_post", lambda *_a, **_k: pytest.fail("Adapter must not be called"))
    client = TestClient(main.app)
    headers = {"Authorization": "Bearer product-test-token"}

    for path, payload in (
        ("/v1/agent/sessions", {}),
        ("/v1/agent/sessions/synthetic/turns", {"content": "start a turn"}),
        ("/v1/agent/sessions/synthetic/resume", {}),
    ):
        assert client.post(path, json=payload, headers=headers).status_code == 503


def test_gateway_boot_fence_replays_the_same_adapter_boot_without_rotation(monkeypatch):
    main._set_runtime_authority_state(ready=False)
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", TOKEN)
    calls = []
    receipt = {
        "schema_version": "byq-runtime-authority-receipt.v1",
        "boot_id": BOOT_ID,
        "authority_epoch": 7,
        "revoked_root_count": 0,
        "revoked_agent_run_count": 0,
        "status": "current",
    }
    current = {
        "schema_version": "byq-runtime-authority-current.v1",
        "boot_id": BOOT_ID,
        "authority_epoch": 7,
        "status": "current",
    }

    def adapter_get(url, *, timeout):
        assert url.endswith("/internal/runtime/authority")
        return _response(url, {
            "schema_version": "byq-runtime-adapter-authority.v1",
            "boot_id": BOOT_ID,
            "status": "ready",
        })

    def backend_request(method, url, *, json, headers, timeout):
        calls.append((method, url, json, headers))
        if method == "POST":
            return _response(url, {"receipt": receipt})
        return _response(url, current)

    monkeypatch.setattr(main.httpx, "get", adapter_get)
    monkeypatch.setattr(main.httpx, "request", backend_request)

    assert SYNC_RUNTIME_AUTHORITY() == {"boot_id": BOOT_ID, "authority_epoch": 7}
    # A Gateway process restart repeats the POST with the same live Adapter id.
    main._set_runtime_authority_state(ready=False)
    assert SYNC_RUNTIME_AUTHORITY() == {"boot_id": BOOT_ID, "authority_epoch": 7}

    boots = [call for call in calls if call[0] == "POST"]
    assert len(boots) == 2
    assert all(call[2] == {"schema_version": "byq-runtime-authority-boot.v1", "boot_id": BOOT_ID}
               for call in boots)
    assert all(call[3] == {"Authorization": f"Bearer {TOKEN}"} for call in boots)
    assert all(call[3] == {} for call in calls if call[0] == "GET")
    assert main._runtime_authority_snapshot() == {
        "ready": True, "boot_id": BOOT_ID, "authority_epoch": 7,
    }


def test_bad_backend_current_receipt_keeps_agent_unready(monkeypatch):
    main._set_runtime_authority_state(ready=False)
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", TOKEN)
    monkeypatch.setattr(main, "_adapter_authority", lambda: {
        "schema_version": "byq-runtime-adapter-authority.v1", "boot_id": BOOT_ID, "status": "ready",
    })
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda method, path, payload=None: (
        {"receipt": {"schema_version": "byq-runtime-authority-receipt.v1", "boot_id": BOOT_ID,
                     "authority_epoch": 7, "revoked_root_count": 0, "revoked_agent_run_count": 0,
                     "status": "current"}}
        if method == "POST" else
        {"schema_version": "byq-runtime-authority-current.v1", "boot_id": "b" * 32,
         "authority_epoch": 7, "status": "current"}
    ))

    with pytest.raises(RuntimeError):
        SYNC_RUNTIME_AUTHORITY()
    assert main._runtime_authority_snapshot()["ready"] is False


def test_domain_evidence_uses_original_current_session_boot(monkeypatch):
    main._set_runtime_authority_state(ready=True, boot_id=BOOT_ID, authority_epoch=7)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    session = main.ProductSession("conversation-one", "session-one", "trace-one",
        main.Principal(subject="alice"), workspace_id="workspace-one", boot_id=BOOT_ID)
    main.product_sessions.add(session)
    monkeypatch.setattr(main, "require_runtime_authority", lambda: None)
    calls = []
    monkeypatch.setattr(main, "_catalog_request", lambda *args, **kwargs:
        calls.append((args, kwargs)) or {"receipt": "accepted"})
    context = {"conversation_id": "conversation-one", "session_id": "session-one",
        "trace_id": "trace-one", "workspace_id": "workspace-one", "owner": "alice"}

    assert main._send_domain_call(context, {"sequence": 1}) == {"receipt": "accepted"}
    assert calls[0][1]["runtime_boot_id"] == BOOT_ID

    main._set_runtime_authority_state(ready=True, boot_id="b" * 32, authority_epoch=8)
    with pytest.raises(main.HTTPException) as raised:
        main._send_domain_call(context, {"sequence": 1})
    assert raised.value.status_code == 503
    assert len(calls) == 1


def test_catalog_request_forwards_only_valid_runtime_boot_header(monkeypatch):
    calls = []

    def request(method, url, *, json, params, headers, timeout):
        calls.append(headers)
        return _response(url, {"receipt": "accepted"})

    monkeypatch.setattr(main.httpx, "request", request)
    principal = main.Principal(subject="alice")
    assert main._catalog_request("POST", "/internal/agent-lifecycle/c", principal,
        "workspace-one", payload={}, runtime_boot_id=BOOT_ID) == {"receipt": "accepted"}
    assert calls[0]["x-byq-runtime-boot-id"] == BOOT_ID
    with pytest.raises(main.HTTPException) as raised:
        main._catalog_request("POST", "/internal/agent-lifecycle/c", principal,
            "workspace-one", payload={}, runtime_boot_id="invalid")
    assert raised.value.status_code == 503
    assert len(calls) == 1


def test_terminal_close_requires_exact_adapter_evidence_then_acknowledges(monkeypatch):
    main._set_runtime_authority_state(ready=True, boot_id=BOOT_ID, authority_epoch=7)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    session = main.ProductSession("conversation-one", "session-one", "trace-one",
        main.Principal(subject="alice"), workspace_id="workspace-one", boot_id=BOOT_ID)
    main.product_sessions.add(session)
    value = project_lifecycle_event({
        "session_id": "session-one", "trace_id": "trace-one", "sequence": 4,
        "timestamp": "2026-09-27T00:00:00+00:00", "source": "runtime-adapter",
        "kind": "session.result", "payload": {"run_id": "c" * 32},
    }, "session-one", "trace-one")
    receipt = lifecycle_receipt(value)
    context = {"conversation_id": "conversation-one", "session_id": "session-one",
        "trace_id": "trace-one", "workspace_id": "workspace-one", "owner": "alice"}
    calls = []

    def adapter_get(path, *, params, timeout):
        calls.append(("evidence", path, params))
        return {"schema_version": "byq-runtime-terminal-evidence.v1", "session_id": "session-one",
            "boot_id": BOOT_ID, "root_run_id": value["root_run_id"], "sequence": 4,
            "outcome": "completed", "receipt": receipt}

    def backend(method, path, payload=None):
        calls.append(("close", method, path, payload))
        assert payload == {"schema_version": "byq-runtime-root-close.v1", "boot_id": BOOT_ID,
            "sequence": 4, "outcome": "completed", "event_sha256": receipt["event_sha256"]}
        return {"receipt": receipt}

    def adapter_post(path, *, payload=None, timeout):
        calls.append(("ack", path, payload))
        return {"receipt": receipt}

    monkeypatch.setattr(main, "_adapter_get", adapter_get)
    monkeypatch.setattr(main, "_backend_runtime_authority_request", backend)
    monkeypatch.setattr(main, "_adapter_post", adapter_post)
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: pytest.fail("terminal must use root close"))

    assert main._send_agent_lifecycle(context, value) == {"receipt": receipt}
    assert [call[0] for call in calls] == ["evidence", "close", "ack"]
    assert calls[0][2] == {"root_run_id": value["root_run_id"], "boot_id": BOOT_ID}


def test_terminal_close_rejects_mismatched_adapter_evidence_without_backend_write(monkeypatch):
    main._set_runtime_authority_state(ready=True, boot_id=BOOT_ID, authority_epoch=7)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    main.product_sessions.add(main.ProductSession("conversation-one", "session-one", "trace-one",
        main.Principal(subject="alice"), workspace_id="workspace-one", boot_id=BOOT_ID))
    value = project_lifecycle_event({
        "session_id": "session-one", "trace_id": "trace-one", "sequence": 4,
        "timestamp": "2026-09-27T00:00:00+00:00", "source": "runtime-adapter",
        "kind": "session.result", "payload": {"run_id": "c" * 32},
    }, "session-one", "trace-one")
    calls = []
    monkeypatch.setattr(main, "_adapter_get", lambda *_a, **_k: {
        "schema_version": "byq-runtime-terminal-evidence.v1", "session_id": "session-one",
        "boot_id": BOOT_ID, "root_run_id": value["root_run_id"], "sequence": 5,
        "outcome": "completed", "receipt": lifecycle_receipt(value),
    })
    monkeypatch.setattr(main, "_backend_runtime_authority_request", lambda *_a, **_k: calls.append("close"))
    monkeypatch.setattr(main, "_adapter_post", lambda *_a, **_k: calls.append("ack"))

    with pytest.raises(ValueError, match="terminal evidence"):
        main._send_agent_lifecycle({"conversation_id": "conversation-one", "session_id": "session-one",
            "trace_id": "trace-one", "workspace_id": "workspace-one", "owner": "alice"}, value)
    assert calls == []
