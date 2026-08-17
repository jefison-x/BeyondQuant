from __future__ import annotations

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
                }
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


def test_product_model_settings_are_secret_free(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    client = TestClient(main.app)
    response = client.get(
        "/api/product/settings/models",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["credentials"]["masked"] is True
    assert "token" not in response.text.lower()
    assert "secret" not in response.text.lower()


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
        if url.endswith("/v1/research/artifacts"):
            return FakeResponse({"artifacts": [{"artifact_id": "artifact_1", "kind": "strategy_version", "status": "validated"}]})
        if url.endswith("/v1/research/backtests"):
            return FakeResponse({"backtests": []})
        if url.endswith("/v1/paper/pools"):
            return FakeResponse({"pools": [{"pool_id": "stock_pool_1", "name": "沪深300", "symbols": ["000001.SZ"]}]})
        if url.endswith("/v1/paper/accounts"):
            return FakeResponse({"accounts": []})
        return FakeResponse({})

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}
    exported = client.get("/api/product/settings/assets/export", headers=auth)
    assert exported.status_code == 200
    assert exported.json()["schema_version"] == "byq-workspace-assets-v1"
    assert exported.json()["assets"]["strategies"][0]["artifact_id"] == "artifact_1"

    imported = client.post(
        "/api/product/settings/assets/import",
        headers=auth,
        json={
            "schema_version": "byq-workspace-assets-v1",
            "assets": {
                "pools": [{"name": "新池", "symbols": ["000002.SZ"], "provenance": {"source": "export"}}],
                "paper_accounts": [],
                "strategies": [],
                "backtests": [],
            },
        },
    )
    assert imported.status_code == 200
    assert imported.json()["imported"]["pools"] == 1


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


def test_product_asset_import_rejects_secret_fields(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    client = TestClient(main.app)
    response = client.post(
        "/api/product/settings/assets/import",
        headers={"Authorization": "Bearer product-test-token"},
        json={
            "schema_version": "byq-workspace-assets-v1",
            "assets": {"pools": [{"name": "bad", "api_token": "secret"}]},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "product_asset_bundle_invalid"
