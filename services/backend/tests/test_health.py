from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_healthz_is_stable() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-backend",
        "status": "ok",
        "version": "0.1.0",
    }


def test_readyz_is_available_without_domain_dependencies() -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["service"] == "byq-backend"
