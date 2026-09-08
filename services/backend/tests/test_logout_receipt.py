import os
import pytest
from fastapi.testclient import TestClient

from app import main
from app.user_auth import UserAuthStore

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def test_logout_returns_explicit_receipt_and_invalidates_session(monkeypatch):
    users = UserAuthStore()
    monkeypatch.setattr(main, "user_store", users)
    try:
        users.create_user({"username": "logout-test-user", "password": "synthetic-password-123",
                           "display_name": "Synthetic logout"}, actor_role="admin")
        session = users.login("logout-test-user", "synthetic-password-123")["session_id"]
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.post("/v1/auth/logout", json={"session_id": session})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert client.post("/v1/auth/logout", json={"session_id": session}).json() == {"status": "ok"}
        assert client.get("/v1/auth/session", headers={"x-byq-session-id": session}).status_code == 403
    finally:
        users.close()
