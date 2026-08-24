from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app import main
from app import product_api
from app import user_session


def test_product_api_uses_error_envelope_and_auth_boundary(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    client = TestClient(main.app)

    missing = client.get("/api/product/health")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "product_authentication_required"

    healthy = client.get(
        "/api/product/health",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert healthy.status_code == 200
    assert healthy.json()["status"] == "ok"


def test_operations_projection_is_admin_only_and_aggregates_normalized_runtime(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    monkeypatch.setattr(product_api, "resolve_user", lambda _request: {
        "user_id": "user_admin", "username": "admin", "role": "admin",
    })
    monkeypatch.setattr(product_api.httpx, "request", lambda *args, **kwargs: FakeResponse({
        "schema_version": "operations.v1",
        "database": {"status": "ready", "engine": "postgresql"},
        "cache": {"kind": "postgresql_market_data", "redis": "not_used"},
        "models": {"secrets_exposed": False},
        "agents": {"recent_runs": []},
        "graphs": {"raw_dsh_events": False},
        "access": {"operations_audit": []},
        "budget": {"version": 1},
    }))
    monkeypatch.setattr(product_api.httpx, "get", lambda *args, **kwargs: FakeResponse({
        "schema_version": "runtime-operations.v1",
        "runtime": {"status": "ready", "sdk": "deepseek-harness-sdk==0.1.0rc6"},
        "sessions": {"active": 1, "active_prompts": 0, "status_counts": {"idle": 1}},
        "usage": {"total_tokens": 125, "model_calls": 1},
        "raw_dsh_events": False,
    }))
    client = TestClient(main.app)
    response = client.get("/api/product/operations/status")
    assert response.status_code == 200
    body = response.json()
    assert body["services"]["runtime_adapter"] == "ready"
    assert body["runtime"]["usage"]["total_tokens"] == 125
    assert body["cache"]["redis"] == "not_used"
    assert "api_key" not in response.text.lower()

    monkeypatch.setattr(product_api, "resolve_user", lambda _request: {
        "user_id": "user_regular", "username": "regular", "role": "user",
    })
    denied = client.get("/api/product/operations/status")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "product_forbidden"


def test_operations_budget_update_forwards_only_admin_actor_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"budget": {"version": 2, "enabled": True}}

    monkeypatch.setattr(product_api, "resolve_user", lambda _request: {
        "user_id": "user_admin", "username": "admin", "role": "admin",
    })

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.put("/api/product/operations/budget", json={
        "enabled": True,
        "alert_total_tokens": 500000,
        "alert_requests": 60,
        "expected_version": 1,
        "idempotency_key": "gateway-budget-1",
    })
    assert response.status_code == 200
    assert captured["method"] == "PUT"
    assert str(captured["url"]).endswith("/v1/operations/budget")
    assert captured["headers"] == {
        "x-byq-actor-role": "admin",
        "x-byq-actor-principal": "admin",
    }


def test_product_dashboard_is_safe_and_normalized(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"status": "ok"}

    monkeypatch.setattr(product_api.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(
        product_api.httpx,
        "request",
        lambda *args, **kwargs: FakeResponse(),
    )
    client = TestClient(main.app)
    response = client.get(
        "/api/product/dashboard",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["resources"]["migration"] == "not_started"


def test_product_profile_loads_and_updates_owner_profile(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "user": {
                    "user_id": "user_abc123",
                    "username": "testuser",
                    "display_name": "老李",
                    "preferences": "低波动",
                    "default_prompt": "先给结论",
                    "role": "user",
                    "status": "active",
                },
                "workspace": {"workspace_id": "workspace_test", "kind": "personal", "role": "owner"},
            }

    monkeypatch.setattr(user_session.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(product_api.httpx, "request", lambda *args, **kwargs: FakeResponse())
    client = TestClient(main.app)
    client.cookies.set(product_api.SESSION_COOKIE, "session_test")

    response = client.get("/api/product/profile")
    assert response.status_code == 200
    assert response.json()["profile"]["display_name"] == "老李"
    response = client.put("/api/product/profile", json={"display_name": "量化小周"})
    assert response.status_code == 200
    assert response.json()["profile"]["display_name"] == "老李"


def test_product_appearance_is_owner_scoped_and_versioned(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    calls: list[tuple[str, str, dict[str, object]]] = []

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    monkeypatch.setattr(
        user_session.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse({
            "user": {
                "user_id": "user_abc123",
                "username": "alice",
                "display_name": "Alice",
                "role": "user",
                "status": "active",
            },
            "workspace": {"workspace_id": "workspace_test", "kind": "personal", "role": "owner"},
        }),
    )

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        calls.append((method, url, kwargs))
        payload = kwargs.get("json") or {}
        return FakeResponse({
            "preferences": {
                "schema_version": "ui-preferences.v1",
                "color_mode": payload.get("color_mode", "system"),
                "accent_theme": payload.get("accent_theme", "emerald"),
                "version": 1 if method == "PUT" else 0,
                "updated_at": None,
            }
        })

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    client.cookies.set(product_api.SESSION_COOKIE, "session_test")

    response = client.get("/api/product/settings/appearance")
    assert response.status_code == 200
    assert response.json()["preferences"]["accent_theme"] == "emerald"
    response = client.put(
        "/api/product/settings/appearance",
        json={
            "schema_version": "ui-preferences.v1",
            "color_mode": "dark",
            "accent_theme": "indigo",
            "expected_version": 0,
        },
    )
    assert response.status_code == 200
    assert response.json()["preferences"]["version"] == 1
    assert all(call[1].endswith("/v1/users/user_abc123/ui-preferences") for call in calls)
    assert all(call[2]["headers"]["x-byq-owner-user-id"] == "user_abc123" for call in calls)

def test_product_model_settings_are_secret_free(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        if url.endswith("/v1/users/model-catalog"):
            return FakeResponse({
                "models": [{"provider": "deepseek", "model": "deepseek-v4-flash"}],
                "agents": [{"agent_id": "byq-product", "name": "小霸 Product Agent"}],
            })
        if url.endswith("/v1/users/model-credentials"):
            return FakeResponse({
                "credentials": [{
                    "credential_id": "cred_0123456789abcdef0123456789abcdef",
                    "provider": "deepseek",
                    "status": "active",
                    "configured": True,
                    "masked": "sk-…abcd",
                }],
                "encryption": {"configured": True, "status": "ready"},
            })
        if url.endswith("/v1/users/model-profiles"):
            return FakeResponse({"profiles": []})
        if url.endswith("/v1/users/model-bindings"):
            return FakeResponse({"bindings": []})
        if "/v1/users/model-credential-audit" in url:
            return FakeResponse({"events": []})
        raise AssertionError(url)

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.get(
        "/api/product/settings/models",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["credentials"]["masked"] is True
    assert response.json()["credential_items"][0]["masked"] == "sk-…abcd"
    assert "token" not in response.text.lower()
    assert "secret" not in response.text.lower()


def test_product_model_mutations_keep_secret_write_only(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "credential": {
                    "credential_id": "cred_0123456789abcdef0123456789abcdef",
                    "provider": "deepseek",
                    "status": "active",
                    "configured": True,
                    "masked": "sk-…abcd",
                    "version": 1,
                }
            }

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/settings/models/credentials",
        headers={"Authorization": "Bearer product-test-token"},
        json={
            "provider": "deepseek",
            "label": "个人 API",
            "secret": "sk-browser-write-only-abcd",
            "idempotency_key": "browser-create-1",
        },
    )
    assert response.status_code == 201
    assert captured["method"] == "POST"
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"
    assert captured["json"]["secret"] == "sk-browser-write-only-abcd"
    assert "sk-browser-write-only-abcd" not in response.text
    assert "ciphertext" not in response.text


def test_browser_cannot_override_session_workspace_context(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(product_api, "resolve_user", lambda _request: {
        "user_id": "user_alice", "username": "alice", "role": "user",
        "_workspace": {"workspace_id": "workspace_alice", "kind": "personal", "role": "owner"},
    })
    monkeypatch.setattr(
        product_api, "resolve_principal", lambda _request: product_api.Principal(subject="alice")
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"credential": {"credential_id": "credential_test"}}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    client.cookies.set(product_api.SESSION_COOKIE, "session_alice")
    response = client.post(
        "/api/product/settings/models/credentials",
        headers={"x-byq-workspace-id": "workspace_forged"},
        json={
            "provider": "deepseek", "label": "test", "secret": "write-only-test",
            "idempotency_key": "workspace-spoof-test",
        },
    )
    assert response.status_code == 201
    assert captured["headers"]["x-byq-workspace-id"] == "workspace_alice"
    assert captured["headers"]["x-byq-owner-principal"] == "alice"


def test_product_assets_export_and_import_are_owner_scoped(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        if method == "GET" and url.endswith("/v1/research/artifacts"):
            return FakeResponse({"artifacts": [{
                "artifact_id": "artifact_1", "kind": "strategy_version", "status": "validated",
                "content_sha256": "a" * 64,
                "content": {"export": {"schema_version": "strategy-version-v1", "version_id": "version-portable-1", "snapshot": {"strategy_id": "portable_one"}}},
            }]})
        if url.endswith("/v1/research/backtests"):
            return FakeResponse({"backtests": [{"job_id": "backtest_1", "status": "succeeded", "input_manifest": {"schema_version": "backtest-input-manifest-v1"}, "summary": {"total_return": 0.1}}]})
        if method == "GET" and url.endswith("/v1/paper/pools"):
            return FakeResponse({"pools": [{"pool_id": "stock_pool_1", "name": "沪深300", "symbols": ["000001.SZ"]}]})
        if method == "GET" and url.endswith("/v1/paper/accounts"):
            return FakeResponse({"accounts": []})
        if method == "POST" and url.endswith("/v1/research/tasks"):
            assert kwargs["json"]["owner_principal"] == "product-user"
            return FakeResponse({"task_id": "task_import_1"})
        if method == "POST" and url.endswith("/v1/research/strategies/validate"):
            return FakeResponse({"artifact": {"artifact_id": "artifact_draft_1"}})
        if method == "POST" and url.endswith("/v1/research/strategies/versions"):
            return FakeResponse({"artifact": {"artifact_id": "artifact_version_2"}, "strategy_version": {"version_id": "version-portable-1"}})
        if method == "POST" and url.endswith("/v1/research/artifacts"):
            assert kwargs["json"]["kind"] == "backtest_archive"
            return FakeResponse({"artifact_id": "artifact_archive_1"})
        return FakeResponse({})

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}
    exported = client.get("/api/product/settings/assets/export", headers=auth)
    assert exported.status_code == 200
    bundle = exported.json()
    assert bundle["schema_version"] == "byq-workspace-assets-v2"
    assert bundle["assets"]["strategies"][0]["kind"] == "strategy_version"
    assert bundle["assets"]["backtests"][0]["kind"] == "backtest_archive"
    assert bundle["manifest_sha256"]

    imported = client.post(
        "/api/product/settings/assets/import",
        headers=auth,
        json=bundle,
    )
    assert imported.status_code == 200
    assert imported.json()["imported"]["pools"] == 1
    assert imported.json()["imported"]["strategies"] == 1
    assert imported.json()["imported"]["backtests"] == 1
    assert imported.json()["source_owner_reused"] is False


def test_product_backtest_result_is_owner_scoped(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"job_id": "backtest_1", "result": {"total_return": 0.1, "trade_count": 2, "equity_curve": []}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.get(
        "/api/product/backtests/backtest_1/result",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["trade_count"] == 2
    assert captured["url"].endswith("/v1/research/backtests/backtest_1/result")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_strategy_version_create_proxy(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"artifact": {"artifact_id": "artifact_version_1", "kind": "strategy_version"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/strategies/versions",
        headers={"Authorization": "Bearer product-test-token"},
        json={"task_id": "task_1", "draft_artifact_id": "artifact_draft_1"},
    )
    assert response.status_code == 201
    assert captured["url"].endswith("/v1/research/strategies/versions")
    assert captured["payload"] == {"task_id": "task_1", "draft_artifact_id": "artifact_draft_1"}


def test_product_strategy_draft_and_projection_routes_forward_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        if url.endswith("/v1/research/strategies/drafts"):
            return FakeResponse({"artifact": {"artifact_id": "artifact_draft_1", "kind": "strategy_draft"}})
        if url.endswith("/strategies/MomentumStrategy/versions"):
            return FakeResponse({"strategy_id": "MomentumStrategy", "versions": [{"artifact_id": "artifact_version_1"}]})
        if url.endswith("/strategies/MomentumStrategy/backtest-count"):
            return FakeResponse({"strategy_id": "MomentumStrategy", "version_count": 1, "backtest_count": 2})
        return FakeResponse({"artifact": {"artifact_id": "artifact_draft_1", "status": "superseded"}})

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}

    saved = client.post(
        "/api/product/strategies/drafts",
        headers=auth,
        json={"task_id": "task_1", "strategy": {"strategy_id": "MomentumStrategy", "script": "class CustomStrategy: pass"}},
    )
    assert saved.status_code == 201
    assert captured["url"].endswith("/v1/research/strategies/drafts")
    assert saved.json()["artifact"]["kind"] == "strategy_draft"

    deleted = client.delete("/api/product/strategies/drafts/artifact_draft_1", headers=auth)
    assert deleted.status_code == 200
    assert captured["url"].endswith("/v1/research/strategies/drafts/artifact_draft_1")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"

    history = client.get("/api/product/strategies/MomentumStrategy/versions", headers=auth)
    assert history.status_code == 200
    assert history.json()["versions"][0]["artifact_id"] == "artifact_version_1"
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"

    counts = client.get("/api/product/strategies/MomentumStrategy/backtest-count", headers=auth)
    assert counts.status_code == 200
    assert counts.json()["backtest_count"] == 2
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_stock_pool_create_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"pool": {"pool_id": "stock_pool_1", "name": "测试池", "pool_type": "custom"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/paper/pools",
        headers={"Authorization": "Bearer product-test-token"},
        json={"name": "测试池", "symbols": ["000001.SZ"], "pool_type": "custom"},
    )
    assert response.status_code == 201
    assert captured["url"].endswith("/v1/paper/pools")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_stock_pool_depth_routes_forward_methods_and_owner(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    captured: list[tuple[str, str, dict[str, str]]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured.append((method, url, kwargs.get("headers", {})))
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}
    assert client.patch("/api/product/paper/pools/stock_pool_1/metadata", headers=auth, json={}).status_code == 200
    assert client.put("/api/product/paper/pools/stock_pool_1/snapshot", headers=auth, json={}).status_code == 200
    assert client.get("/api/product/paper/pools/stock_pool_1/snapshots", headers=auth).status_code == 200
    assert client.get("/api/product/paper/pools/stock_pool_1/as-of/20240131", headers=auth).status_code == 200
    assert client.patch("/api/product/paper/pools/stock_pool_1/lifecycle", headers=auth, json={}).status_code == 200
    assert client.get("/api/product/paper/pools/stock_pool_1/references", headers=auth).status_code == 200
    assert [item[0] for item in captured] == ["PATCH", "PUT", "GET", "GET", "PATCH", "GET"]
    assert all(item[2]["x-byq-owner-principal"] == "product-user" for item in captured)


def test_product_stock_pool_mutation_preserves_domain_validation(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    request = product_api.httpx.Request("PUT", "http://backend/v1/paper/pools/pool_1/snapshot")
    response = product_api.httpx.Response(
        422,
        request=request,
        json={"detail": "weights must sum to 1"},
    )
    monkeypatch.setattr(product_api.httpx, "request", lambda *args, **kwargs: response)

    client = TestClient(main.app)
    result = client.put(
        "/api/product/paper/pools/pool_1/snapshot",
        headers={"Authorization": "Bearer product-test-token"},
        json={},
    )

    assert result.status_code == 422
    assert result.json()["error"]["code"] == "product_domain_rejected"
    assert result.json()["error"]["message"] == "weights must sum to 1"


def test_product_paper_ledger_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ledger": [{"fill_id": "fill_1", "cash_delta": -1000.0}]}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.get(
        "/api/product/paper/accounts/paper_account_1/ledger",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert captured["url"].endswith("/v1/paper/accounts/paper_account_1/ledger")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_paper_order_create_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"order": {"order_id": "order_1", "status": "filled"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/paper/orders",
        headers={"Authorization": "Bearer product-test-token"},
        json={"account_id": "paper_account_1", "symbol": "000001.SZ", "side": "buy"},
    )
    assert response.status_code == 201
    assert captured["url"].endswith("/v1/paper/orders")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_paper_depth_routes_forward_methods_and_owner(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    captured: list[tuple[str, str, dict[str, str]]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured.append((method, url, kwargs.get("headers", {})))
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}
    base = "/api/product/paper/accounts/paper_account_1"
    assert client.get(f"{base}/orders/paper_order_1", headers=auth).status_code == 200
    assert client.get(f"{base}/snapshots", headers=auth).status_code == 200
    assert client.post(f"{base}/settlements", headers=auth, json={}).status_code == 201
    assert client.get(f"{base}/controls", headers=auth).status_code == 200
    assert client.put(f"{base}/controls", headers=auth, json={}).status_code == 200
    assert client.put(f"{base}/binding", headers=auth, json={}).status_code == 200
    assert client.get(f"{base}/export", headers=auth).status_code == 200
    assert client.post("/api/product/paper/accounts/import", headers=auth, json={}).status_code == 201
    assert [item[0] for item in captured] == ["GET", "GET", "POST", "GET", "PUT", "PUT", "GET", "POST"]
    assert all(item[2]["x-byq-owner-principal"] == "product-user" for item in captured)


def test_product_approval_decision_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"approval": {"approval_id": "agent_approval_1", "status": "approved"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        captured["payload"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/approvals/agent_approval_1/decision",
        headers={"Authorization": "Bearer product-test-token"},
        json={"decision": "approved", "rationale": "ok"},
    )
    assert response.status_code == 200
    assert captured["url"].endswith("/v1/agents/approvals/agent_approval_1/decision")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"
    assert captured["payload"] == {"decision": "approved", "rationale": "ok"}


def test_product_agent_policy_get_and_update(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        if url.endswith("/v1/agents/approvals"):
            return FakeResponse({"approvals": []})
        if method == "PUT":
            return FakeResponse({"policy": {"owner_principal": "product-user", "automation_enabled": False, "paused": True, "default_decision_mode": "manual"}})
        return FakeResponse({"policy": {"owner_principal": "product-user", "automation_enabled": True, "default_decision_mode": "manual"}})

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}
    response = client.get("/api/product/settings/agent-policy", headers=auth)
    assert response.status_code == 200
    assert response.json()["personal_policy"]["automation_enabled"] is True

    updated = client.put(
        "/api/product/settings/agent-policy",
        headers=auth,
        json={"automation_enabled": False, "paused": True},
    )
    assert updated.status_code == 200
    assert updated.json()["personal_policy"]["paused"] is True


def test_product_data_center_status_exposes_masked_provider_capability(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "schema_version": "data-center.v1", "provider": "tushare", "legacy_providers": [],
                "migration": "not_started", "quality": "empty",
                "source": {"configured": True, "effective_source": "credential_store", "credentials": [{"masked": "configured"}], "secrets_exposed": False, "can_manage": False},
                "jobs": [], "coverage": {"quality": "empty", "row_count": 0, "symbol_count": 0, "groups": [], "symbols": []},
            }

    monkeypatch.setattr(product_api.httpx, "request", lambda *args, **kwargs: FakeResponse())
    client = TestClient(main.app)
    response = client.get(
        "/api/product/data-center/status",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["source"]["configured"] is True
    assert response.json()["source"]["effective_source"] == "credential_store"
    assert "token" not in response.text.lower()
    assert "ciphertext" not in response.text.lower()


def test_product_data_center_writes_are_admin_only_and_use_backend_boundary(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"job": {"job_id": "sync_1", "status": "completed"}, "created": True}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured.append({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(product_api, "resolve_user", lambda _request: {"username": "admin", "role": "admin"})
    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    client.cookies.set(product_api.SESSION_COOKIE, "session_admin")
    response = client.post("/api/product/data-center/sync-jobs", json={
        "mode": "range", "symbols": ["000001.SZ"], "start_date": "20240102",
        "end_date": "20240112", "idempotency_key": "gateway-sync-1",
    })
    assert response.status_code == 201
    assert str(captured[0]["url"]).endswith("/v1/data-sync/jobs")
    assert captured[0]["headers"] == {"x-byq-actor-principal": "admin", "x-byq-actor-role": "admin"}

    monkeypatch.setattr(product_api, "resolve_user", lambda _request: {"username": "alice", "role": "user"})
    denied = client.post("/api/product/data-center/source/test", json={"symbol": "000001.SZ", "trade_date": "20240102"})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "product_forbidden"


def test_product_asset_import_rejects_secret_fields(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    client = TestClient(main.app)
    unsigned = {
        "schema_version": "byq-workspace-assets-v2",
        "exported_at": "2026-08-22T00:00:00+00:00",
        "owner_principal": "product-user",
        "assets": {"pools": [{"name": "bad", "api_token": "secret"}]},
    }
    response = client.post(
        "/api/product/settings/assets/import",
        headers={"Authorization": "Bearer product-test-token"},
        json={**unsigned, "manifest_sha256": product_api._canonical_digest(unsigned)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "product_asset_bundle_invalid"


def test_product_asset_import_rejects_tampered_manifest(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    client = TestClient(main.app)
    response = client.post(
        "/api/product/settings/assets/import",
        headers={"Authorization": "Bearer product-test-token"},
        json={
            "schema_version": "byq-workspace-assets-v2",
            "exported_at": "2026-08-22T00:00:00+00:00",
            "owner_principal": "alice",
            "assets": {"strategies": []},
            "manifest_sha256": "0" * 64,
        },
    )
    assert response.status_code == 422
    assert "digest" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/product/research/tasks/task_1", None),
        ("get", "/api/product/backtests/backtest_1", None),
        ("post", "/api/product/backtests/backtest_1/run", None),
        ("post", "/api/product/backtests/backtest_1/cancel", None),
        ("post", "/api/product/signal-producer/jobs", {}),
        ("get", "/api/product/signal-producer/jobs/signaljob_1", None),
        ("get", "/api/product/strategies/versions/artifact_1/export", None),
        ("post", "/api/product/strategies/drafts", {}),
        ("post", "/api/product/strategies/approvals", {}),
        ("post", "/api/product/strategies/validate", {}),
        ("get", "/api/product/paper/accounts/paper_account_1", None),
        ("get", "/api/product/paper/pools/stock_pool_1", None),
    ],
)
def test_product_business_proxy_routes_forward_owner_context(
    monkeypatch,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {}

    captured: dict[str, object] = {}

    def fake_request(request_method: str, url: str, **kwargs) -> FakeResponse:
        captured["method"] = request_method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.request(
        method,
        path,
        headers={"Authorization": "Bearer product-test-token"},
        json=payload,
    )

    assert response.status_code < 400, response.text
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"
    assert captured["headers"]["x-byq-actor-principal"] == "product-user"


def test_product_research_task_creation_owns_identity_fields(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"task_id": "task_1", "owner_principal": "product-user"}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/research/tasks",
        headers={"Authorization": "Bearer product-test-token"},
        json={"title": "Momentum research", "objective": "Evaluate the signal"},
    )

    assert response.status_code == 201
    assert captured["method"] == "POST"
    assert str(captured["url"]).endswith("/v1/research/tasks")
    assert captured["json"]["owner_principal"] == "product-user"
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"
    assert set(captured["json"]) == {
        "owner_principal", "title", "objective", "trace_id", "idempotency_key",
    }

    invalid = client.post(
        "/api/product/research/tasks",
        headers={"Authorization": "Bearer product-test-token"},
        json={"title": "bad", "objective": "bad", "owner_principal": "other-user"},
    )
    assert invalid.status_code == 422
