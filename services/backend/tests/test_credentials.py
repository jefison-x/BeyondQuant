from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import main
from app.credentials import (
    MODEL_CATALOG,
    RUNTIME_MODEL_ALLOWLIST,
    CredentialCipher,
    CredentialConflict,
    CredentialNotFound,
    CredentialStore,
    CredentialUnavailable,
    _default_model_list_fetch,
    _runtime_provider_for,
)
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

KEY_OLD = bytes(range(32))
KEY_NEW = bytes(reversed(range(32)))
def _store(*, active: str = "old", include_old: bool = True) -> CredentialStore:
    keys = {"new": KEY_NEW}
    if include_old:
        keys["old"] = KEY_OLD
    return CredentialStore(cipher=CredentialCipher.for_test(keys, active))


def _credential_payload(
    secret: str = "sk-phase37-secret-abcd",
    *,
    provider: str = "deepseek",
) -> dict[str, object]:
    return {
        "purpose": "model_api_key",
        "provider": provider,
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
    assert binding["agent_name"] == "小巴 Product Agent"
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
    assert store.list_bindings("alice")[0]["agent_name"] == "小巴 Product Agent"
    assert store.list_bindings("alice")[0]["available"] is False
    store.close()


def test_opencode_go_credential_resolves_to_the_reviewed_protocol_route() -> None:
    store = _store()
    credential = store.create_credential(
        "alice",
        _credential_payload("go-personal-secret-abcd", provider="opencode-go"),
        actor="alice",
    )
    profile = store.create_profile(
        "alice",
        {
            "credential_id": credential["credential_id"],
            "key_name": "go-minimax",
            "display_name": "Go MiniMax",
            "provider": "opencode-go",
            "model": "minimax-m3",
            "temperature": 0.2,
            "reasoning_enabled": True,
        },
    )
    store.bind("alice", "byq-product", profile["profile_id"])

    assert store.resolve_model("alice", "byq-product") == {
        "source": "user_binding",
        "provider": "opencode-go-messages",
        "model": "minimax-m3",
        "temperature": 0.2,
        "reasoning_enabled": True,
        "api_key": "go-personal-secret-abcd",
    }
    with pytest.raises(CredentialNotFound, match="active model credential"):
        store.create_profile(
            "alice",
            {
                "credential_id": credential["credential_id"],
                "key_name": "cross-provider",
                "display_name": "Wrong provider",
                "provider": "opencode-zen",
                "model": "minimax-m3",
            },
        )
    store.close()


def test_system_tushare_resolution_is_backend_only_and_fails_closed_when_ambiguous() -> None:
    store = _store()
    first = store.create_credential(
        "admin",
        {
            "purpose": "tushare_token",
            "provider": "tushare",
            "scope": "system",
            "label": "系统行情",
            "secret": "tushare-system-token-abcd",
            "idempotency_key": "tushare-create-1",
        },
        actor="admin",
        actor_role="admin",
    )
    assert store.resolve_tushare() == {
        "source": "credential_store",
        "credential_id": first["credential_id"],
        "version": 1,
        "token": "tushare-system-token-abcd",
    }
    assert "tushare-system-token" not in json.dumps(store.list_credentials("admin", actor_role="admin"))

    store.create_credential(
        "admin",
        {
            "purpose": "tushare_token",
            "provider": "tushare",
            "scope": "system",
            "label": "冲突凭据",
            "secret": "tushare-other-token-wxyz",
            "idempotency_key": "tushare-create-2",
        },
        actor="admin",
        actor_role="admin",
    )
    with pytest.raises(CredentialUnavailable, match="multiple active"):
        store.resolve_tushare()
    store.close()


def test_backend_model_routes_never_echo_secret_and_resolver_is_private(monkeypatch) -> None:
    context = trusted_agent_context(
        "alice", trace_id="trace-credential-test", session_id="session-credential-test",
        dsh_run_id="run-credential-test",
    )
    store = _store()
    monkeypatch.setattr(main, "credential_store", store)
    monkeypatch.setattr(main, "CREDENTIAL_RESOLVER_TOKEN", "resolver-test-only")
    client = TestClient(main.app)

    catalog = client.get("/v1/users/model-catalog", headers=context)
    assert catalog.status_code == 200
    assert {item["provider"] for item in catalog.json()["providers"]} == {
        "deepseek", "opencode-go", "opencode-zen",
    }
    assert "runtime_provider" not in catalog.text
    assert "base_url" not in catalog.text

    created = client.post(
        "/v1/users/model-credentials",
        headers=context,
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
        headers=context,
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
        headers=context,
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

    other_headers = trusted_agent_context("bob")
    hidden = client.get("/v1/users/model-credentials", headers=other_headers)
    assert hidden.status_code == 200
    assert hidden.json()["credentials"] == []
    store.close()


def test_discover_models_refreshes_provider_list_without_leaking_secret() -> None:
    store = _store()
    payload = _credential_payload("sk-discover-secret-abcd")
    payload["idempotency_key"] = "discover-deepseek-1"
    credential = store.create_credential("alice", payload, actor="alice")
    calls = []

    def fetch(url, token, timeout):
        calls.append((url, token, timeout))
        return 200, json.dumps({"data": [
            {"id": "deepseek-v4-flash"}, {"id": "deepseek-v4.1-flash"}, {"id": "deepseek-v4-flash"},
        ]}).encode()

    result = store.discover_models(credential["credential_id"], owner="alice", fetch=fetch)
    assert calls[0][0] == "https://api.deepseek.com/models"
    assert calls[0][1] == "sk-discover-secret-abcd"
    assert [item["model"] for item in result["models"]] == ["deepseek-v4-flash", "deepseek-v4.1-flash"]
    assert result["provider"] == "deepseek"
    assert all(item["runtime_provider"] == "deepseek-official" for item in result["models"])
    assert [item["supported"] for item in result["models"]] == [True, False]
    assert "sk-discover-secret-abcd" not in json.dumps(result)
    store.close()


def test_discover_models_fails_closed_and_is_owner_scoped() -> None:
    store = _store()
    payload = _credential_payload("sk-discover-secret-efgh", provider="opencode-go")
    payload["idempotency_key"] = "discover-opencode-1"
    credential = store.create_credential("alice", payload, actor="alice")
    identity = credential["credential_id"]

    for response in ((500, b"{}"), (200, b"not-json"), (200, b'{"data": []}')):
        with pytest.raises(CredentialUnavailable):
            store.discover_models(identity, owner="alice", fetch=lambda *a, r=response: r)
    captured = {}

    def fetch(url, token, timeout):
        captured["url"] = url
        return 200, json.dumps({"data": [{"id": "deepseek-v4-pro"}]}).encode()

    store.discover_models(identity, owner="alice", fetch=fetch)
    assert captured["url"] == "https://opencode.ai/zen/go/v1/models"
    with pytest.raises(CredentialNotFound):
        store.discover_models(identity, owner="bob", fetch=fetch)
    store.close()


def test_runtime_provider_mapping_is_closed() -> None:
    assert _runtime_provider_for("deepseek", "deepseek-v4.1-flash") == "deepseek-official"
    assert _runtime_provider_for("opencode-go", "kimi-k3") == "opencode-go-chat"
    assert _runtime_provider_for("opencode-go", "minimax-m3") == "opencode-go-messages"
    assert _runtime_provider_for("opencode-zen", "claude-opus-5") == "opencode-zen-messages"
    assert _runtime_provider_for("opencode-go", "unknown-model") is None
    assert _runtime_provider_for("unknown-provider", "x") is None


def test_discovery_request_sends_bounded_client_identity(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200
        def read(self) -> bytes:
            return b'{"data":[{"id":"deepseek-v4-flash"}]}'
        def __enter__(self) -> "FakeResponse":
            return self
        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(request, timeout):
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return FakeResponse()

    import app.credentials as credentials
    monkeypatch.setattr(credentials.urllib.request, "urlopen", fake_urlopen)
    status, body = _default_model_list_fetch("https://api.deepseek.com/models", "secret-token", 3.0)
    assert status == 200 and b"deepseek-v4-flash" in body
    assert captured["timeout"] == 3.0
    assert captured["headers"]["authorization"] == "Bearer secret-token"
    assert captured["headers"].get("user-agent")


def test_discovered_models_are_selectable_and_unknown_models_fail_closed() -> None:
    store = _store()
    credential = store.create_credential(
        "alice",
        _credential_payload("go-discovered-secret-abcd", provider="opencode-go"),
        actor="alice",
    )

    def fetch(url, token, timeout):
        return 200, json.dumps({"data": [
            {"id": "kimi-k3"},
            {"id": "kimi-k3-experimental"},
            {"id": "mystery-model"},
        ]}).encode()

    result = store.discover_models(credential["credential_id"], owner="alice", fetch=fetch)
    # Allowlisted models are supported; unknown prefixes and unlisted ids are not.
    assert [item["supported"] for item in result["models"]] == [True, False, False]
    # Only the allowlisted model is persisted as a selectable discovery row.
    discovered = store._execute(
        "SELECT model FROM credential_discovered_models WHERE credential_id = :credential_id",
        {"credential_id": credential["credential_id"]},
    )
    assert [row["model"] for row in discovered] == ["kimi-k3"]

    profile = store.create_profile(
        "alice",
        {
            "credential_id": credential["credential_id"],
            "key_name": "go-discovered",
            "display_name": "Discovered",
            "provider": "opencode-go",
            "model": "kimi-k3",
        },
    )
    store.bind("alice", "byq-product", profile["profile_id"])
    resolution = store.resolve_model("alice", "byq-product")
    assert resolution["provider"] == "opencode-go-chat"
    assert resolution["model"] == "kimi-k3"

    with pytest.raises(ValueError, match="BYQ catalogue"):
        store.create_profile(
            "alice",
            {
                "credential_id": credential["credential_id"],
                "key_name": "go-unsupported",
                "display_name": "Unsupported",
                "provider": "opencode-go",
                "model": "kimi-k3-experimental",
            },
        )
    with pytest.raises(ValueError, match="BYQ catalogue"):
        store.create_profile(
            "alice",
            {
                "credential_id": credential["credential_id"],
                "key_name": "go-never-discovered",
                "display_name": "Never discovered",
                "provider": "opencode-go",
                "model": "kimi-k9",
            },
        )
    store.close()


def test_create_profile_rejects_discovered_model_outside_runtime_allowlist() -> None:
    store = _store()
    credential = store.create_credential(
        "alice",
        _credential_payload("go-drift-secret-abcd", provider="opencode-go"),
        actor="alice",
    )
    # Simulate a stale discovery row written before the composition changed: the
    # prefix maps to a runtime route, but the runtime rejects the exact model id.
    store._execute(
        """INSERT INTO credential_discovered_models
           (credential_id, model, runtime_provider, discovered_at)
           VALUES (:credential_id, :model, :runtime_provider, :discovered_at)""",
        {
            "credential_id": credential["credential_id"],
            "model": "deepseek-v4.1-flash",
            "runtime_provider": "opencode-go-chat",
            "discovered_at": "2026-09-17T00:00:00+00:00",
        },
    )
    with pytest.raises(ValueError, match="runtime allowlist"):
        store.create_profile(
            "alice",
            {
                "credential_id": credential["credential_id"],
                "key_name": "go-drift",
                "display_name": "Drift",
                "provider": "opencode-go",
                "model": "deepseek-v4.1-flash",
            },
        )
    store.close()


def test_profile_disable_enable_lifecycle_is_idempotent_and_owner_scoped() -> None:
    store = _store()
    credential = store.create_credential("alice", _credential_payload(), actor="alice")
    profile = store.create_profile(
        "alice",
        {
            "credential_id": credential["credential_id"],
            "key_name": "lifecycle-profile",
            "display_name": "生命周期",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        },
    )
    assert store.bind("alice", "byq-product", profile["profile_id"])["version"] == 1

    disabled = store.disable_profile(
        profile["profile_id"], "alice", expected_version=1, actor="alice",
    )
    assert disabled["status"] == "disabled"
    assert disabled["version"] == 2
    assert disabled["available"] is False
    unbound = store.list_bindings("alice")[0]
    assert unbound["profile_id"] is None and unbound["version"] == 2
    assert {
        row["profile_id"]: row["status"] for row in store.list_profiles("alice")
    }[profile["profile_id"]] == "disabled"
    replay = store.disable_profile(
        profile["profile_id"], "alice", expected_version=1, actor="alice",
    )
    assert replay["status"] == "disabled" and replay["version"] == 2
    assert store.reconcile_model_command(
        "alice", "disable_profile", profile["profile_id"], 1,
    ) == {
        "state": "confirmed", "operation": "disable_profile",
        "resource_id": profile["profile_id"], "expected_version": 1,
        "profile_id": profile["profile_id"], "committed_version": 2,
    }
    with pytest.raises(CredentialNotFound):
        store.disable_profile(profile["profile_id"], "bob", expected_version=1)
    with pytest.raises(CredentialConflict):
        store.disable_profile(profile["profile_id"], "alice", expected_version=1 + 1)
    with pytest.raises(CredentialConflict):
        store.enable_profile(profile["profile_id"], "alice", expected_version=1, actor="alice")

    enabled = store.enable_profile(
        profile["profile_id"], "alice", expected_version=2, actor="alice",
    )
    assert enabled["status"] == "active" and enabled["version"] == 3
    assert store.list_bindings("alice")[0]["profile_id"] is None  # enable does not rebind
    replay_enable = store.enable_profile(
        profile["profile_id"], "alice", expected_version=2, actor="alice",
    )
    assert replay_enable["status"] == "active" and replay_enable["version"] == 3
    assert store.bind(
        "alice", "byq-product", profile["profile_id"], expected_version=2,
    )["profile_id"] == profile["profile_id"]

    deleted = store.delete_profile(profile["profile_id"], "alice", expected_version=3)
    assert deleted["status"] == "deleted"
    with pytest.raises(CredentialConflict, match="deleted"):
        store.enable_profile(profile["profile_id"], "alice", expected_version=4)
    with pytest.raises(CredentialConflict, match="deleted"):
        store.disable_profile(profile["profile_id"], "alice", expected_version=4)

    actions = [event["action"] for event in store.list_audit("alice")]
    assert "disable_profile" in actions and "enable_profile" in actions
    rows = store._execute(
        """SELECT operation, expected_version, committed_version
           FROM model_profile_status_receipts WHERE owner_principal = 'alice'
           ORDER BY expected_version"""
    )
    assert [
        (row["operation"], row["expected_version"], row["committed_version"]) for row in rows
    ] == [("disable_profile", 1, 2), ("enable_profile", 2, 3)]
    store.close()


def _repository_root() -> Path:
    candidates: list[Path] = []
    env_root = os.environ.get("BYQ_REPO_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend(Path(__file__).resolve().parents)
    candidates.append(Path.cwd())
    for candidate in candidates:
        if (candidate / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").is_file():
            return candidate
    pytest.skip("DSH composition is not available in this test environment")


def _load_cordis_document(path: Path):
    class CordisLoader(yaml.SafeLoader):
        pass

    CordisLoader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: None)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=CordisLoader)


def _llm_provider_models(document: object, entry_id: str) -> dict[str, tuple[str, ...]]:
    for entry in document if isinstance(document, list) else []:
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            providers = entry["config"]["providers"]
            return {
                name: tuple(model["id"] for model in config["models"])
                for name, config in providers.items()
            }
    raise AssertionError(f"DSH composition entry {entry_id!r} not found")


def test_runtime_model_allowlist_matches_dsh_composition() -> None:
    root = _repository_root()
    composition_models = _llm_provider_models(
        _load_cordis_document(root / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml"),
        "llm-opencode",
    )
    patch_models = _llm_provider_models(
        _load_cordis_document(
            root / "plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml"
        ),
        "llm-pi-ai",
    )
    assert composition_models == patch_models
    for runtime, models in composition_models.items():
        assert RUNTIME_MODEL_ALLOWLIST[runtime] == models, runtime
    assert RUNTIME_MODEL_ALLOWLIST["deepseek-official"] == tuple(
        item["model"] for item in MODEL_CATALOG if item["provider"] == "deepseek"
    )
    assert set(RUNTIME_MODEL_ALLOWLIST) == set(composition_models) | {"deepseek-official"}
