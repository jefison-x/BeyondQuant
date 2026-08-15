from fastapi.testclient import TestClient

from app import main


client = TestClient(main.app)


def test_healthz_is_local_and_stable() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-gateway",
        "status": "ok",
        "version": "0.1.0",
    }


def test_readyz_reports_gateway_bootstrap_only() -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-gateway",
        "status": "ok",
        "version": "0.1.0",
        "dsh_runtime_integration": "not-configured",
    }
