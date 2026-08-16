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
