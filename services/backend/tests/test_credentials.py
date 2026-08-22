from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.credentials import (
    CredentialCipher,
    CredentialConflict,
    CredentialNotFound,
    CredentialStore,
    CredentialUnavailable,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

KEY_OLD = bytes(range(32))
KEY_NEW = bytes(reversed(range(32)))
CONTEXT = {
    "x-byq-owner-principal": "alice",
    "x-byq-actor-principal": "alice",
    "x-byq-trace-id": "trace-credential-test",
    "x-byq-session-id": "session-credential-test",
    "x-byq-dsh-run-id": "run-credential-test",
}


def _store(*, active: str = "old", include_old: bool = True) -> CredentialStore:
    keys = {"new": KEY_NEW}
    if include_old:
        keys["old"] = KEY_OLD
    return CredentialStore(cipher=CredentialCipher.for_test(keys, active))


def _credential_payload(secret: str = "sk-phase37-secret-abcd") -> dict[str, object]:
    return {
        "purpose": "model_api_key",
        "provider": "deepseek",
        "scope": "user",
        "label": "我的 DeepSeek",
        "secret": secret,
        "idempotency_key": "credential-create-1",
    }


def test_cipher_authenticates_aad_and_tamper() -> None:
    cipher = CredentialCipher.for_test({"old": KEY_OLD}, "old")
    envelope = cipher.encrypt("sk-test-value", aad=b"record-a")
    assert cipher.decrypt(envelope, aad=b"record-a") == "sk-test-value"

    with pytest.raises(CredentialUnavailable, match="authentication"):
        cipher.decrypt(envelope, aad=b"record-b")

    tampered = dict(envelope)
    tampered["ciphertext"] = bytes(envelope["ciphertext"])[:-1] + b"\x00"
    with pytest.raises(CredentialUnavailable, match="authentication"):
        cipher.decrypt(tampered, aad=b"record-a")


def test_keyring_rejects_duplicate_and_invalid_keys(monkeypatch) -> None:
    encoded = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    monkeypatch.setenv("BYQ_CREDENTIAL_ACTIVE_KEY_ID", "a")
    monkeypatch.setenv("BYQ_CREDENTIAL_KEYRING", f'{{"a":"{encoded}","a":"{encoded}"}}')
    with pytest.raises(CredentialUnavailable, match="duplicate"):
        CredentialCipher.from_env()

    monkeypatch.setenv("BYQ_CREDENTIAL_KEYRING", '{"a":"c2hvcnQ"}')
    with pytest.raises(CredentialUnavailable, match="32 bytes"):
        CredentialCipher.from_env()


def test_credential_crud_is_masked_owner_scoped_and_audited() -> None:
    store = _store()
    created = store.create_credential("alice", _credential_payload(), actor="alice")
    assert created["masked"] == "sk-…abcd"
    assert created["configured"] is True
    assert "secret" not in json.dumps(created).lower()
    assert "cipher" not in json.dumps(created).lower()

    replay = store.create_credential("alice", _credential_payload(), actor="alice")
    assert replay["credential_id"] == created["credential_id"]
    with pytest.raises(CredentialConflict, match="idempotency"):
        store.create_credential(
            "alice",
            {**_credential_payload("sk-different-value-efgh")},
            actor="alice",
        )
    assert store.list_credentials("bob") == []
    with pytest.raises(CredentialNotFound):
        store.get_credential(created["credential_id"], owner="bob")

    updated = store.update_credential(
        created["credential_id"],
        "alice",
        {
            "label": "轮换后的密钥",
            "secret": "sk-rotated-secret-wxyz",
            "expected_version": 1,
            "request_id": "credential-replace-1",
        },
        actor="alice",
    )
    assert updated["version"] == 2
    assert updated["masked"] == "sk-…wxyz"

    revoked = store.revoke_credential(
        created["credential_id"],
        "alice",
        actor="alice",
        expected_version=2,
        request_id="credential-revoke-1",
    )
    assert revoked["status"] == "revoked"
    assert revoked["configured"] is False
    assert [event["action"] for event in store.list_audit("alice")] == [
        "revoked", "secret_replaced", "created",
    ]
    store.close()


def test_profile_binding_resolution_and_rotation_fail_closed() -> None:
    store = _store()
    credential = store.create_credential("alice", _credential_payload(), actor="alice")
    profile = store.create_profile(
        "alice",
        {
            "credential_id": credential["credential_id"],
            "key_name": "research-fast",
            "display_name": "研究快速模型",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "temperature": 0.2,
            "reasoning_enabled": False,
        },
    )
    binding = store.bind("alice", "byq-product", profile["profile_id"])
    assert binding["effective_source"] == "personal"
    resolution = store.resolve_model("alice", "byq-product")
    assert resolution == {
        "source": "user_binding",
        "provider": "deepseek-official",
        "model": "deepseek-v4-flash",
        "temperature": 0.2,
        "reasoning_enabled": False,
        "api_key": "sk-phase37-secret-abcd",
    }
    assert store.resolve_model("bob", "byq-product") is None

    with pytest.raises(CredentialNotFound):
        store.create_profile(
            "bob",
            {
                "credential_id": credential["credential_id"],
                "key_name": "cross-owner",
                "display_name": "越权",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
        )

    # Re-open with a ring containing both old and new keys, then rewrap.
    store.cipher = CredentialCipher.for_test({"old": KEY_OLD, "new": KEY_NEW}, "new")
    assert store.rewrap_active(actor="operator", request_id="rotate-1")["rewrapped"] == 1
    assert store.resolve_model("alice", "byq-product")["api_key"] == "sk-phase37-secret-abcd"
    store.cipher = CredentialCipher.for_test({"new": KEY_NEW}, "new")
    assert store.resolve_model("alice", "byq-product")["api_key"] == "sk-phase37-secret-abcd"

    store.revoke_credential(
        credential["credential_id"],
        "alice",
        actor="alice",
        expected_version=2,
        request_id="revoke-after-rotate",
    )
    with pytest.raises(CredentialUnavailable):
        store.resolve_model("alice", "byq-product")
    assert store.list_bindings("alice")[0]["profile_id"] == profile["profile_id"]
    assert store.list_bindings("alice")[0]["available"] is False
    store.close()


def test_backend_model_routes_never_echo_secret_and_resolver_is_private(monkeypatch) -> None:
    store = _store()
    monkeypatch.setattr(main, "credential_store", store)
    monkeypatch.setattr(main, "CREDENTIAL_RESOLVER_TOKEN", "resolver-test-only")
    client = TestClient(main.app)

    created = client.post(
        "/v1/users/model-credentials",
        headers=CONTEXT,
        json={
            "provider": "deepseek",
            "label": "API",
            "secret": "sk-http-secret-abcd",
            "idempotency_key": "http-create-1",
        },
    )
    assert created.status_code == 201
    assert "sk-http-secret" not in created.text
    assert "ciphertext" not in created.text
    credential = created.json()["credential"]

    profile = client.post(
        "/v1/users/model-profiles",
        headers=CONTEXT,
        json={
            "credential_id": credential["credential_id"],
            "key_name": "http-profile",
            "display_name": "HTTP Profile",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        },
    )
    assert profile.status_code == 201
    profile_id = profile.json()["profile"]["profile_id"]
    bound = client.put(
        "/v1/users/model-bindings/byq-product",
        headers=CONTEXT,
        json={"profile_id": profile_id, "expected_version": 0},
    )
    assert bound.status_code == 200

    payload = {
        "owner_principal": "alice",
        "agent_id": "byq-product",
        "session_id": "session-resolve",
        "trace_id": "trace-resolve",
    }
    denied = client.post("/internal/credentials/model-resolution", json=payload)
    assert denied.status_code == 403
    assert "sk-http-secret" not in denied.text
    resolved = client.post(
        "/internal/credentials/model-resolution",
        headers={"x-byq-credential-resolver-token": "resolver-test-only"},
        json=payload,
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolution"]["api_key"] == "sk-http-secret-abcd"

    other_headers = {**CONTEXT, "x-byq-owner-principal": "bob", "x-byq-actor-principal": "bob"}
    hidden = client.get("/v1/users/model-credentials", headers=other_headers)
    assert hidden.status_code == 200
    assert hidden.json()["credentials"] == []
    store.close()
