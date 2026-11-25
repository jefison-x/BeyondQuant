from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app import main


client = TestClient(main.app)


def test_healthz_is_stable() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-backend",
        "status": "ok",
        "version": "0.1.0",
    }


def test_readyz_checks_the_existing_database_pool() -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "byq-backend",
        "status": "ok",
        "version": "0.1.0",
        "database": "ready",
    }


def test_readyz_fails_closed_when_the_database_is_unavailable(monkeypatch) -> None:
    def unavailable():
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(main.agent_store.engine, "begin", unavailable)
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": "backend database is unavailable"}
