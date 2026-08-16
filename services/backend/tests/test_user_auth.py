from __future__ import annotations

import pytest

from app.user_auth import UserAuthStore, UserForbidden


def test_user_login_session_and_disable(tmp_path) -> None:
    store = UserAuthStore(tmp_path / "users.sqlite3")
    admin = store.create_user(
        {"username": "admin", "password": "adminpass123", "display_name": "Admin"},
        actor_role="admin",
    )
    assert admin["username"] == "admin"
    assert "password_hash" not in admin

    logged_in = store.login("admin", "adminpass123")
    assert logged_in["user"]["user_id"] == admin["user_id"]
    session = store.get_session_user(logged_in["session_id"])
    assert session["username"] == "admin"

    store.disable_user(admin["user_id"], actor_role="admin")
    with pytest.raises(UserForbidden, match="disabled"):
        store.login("admin", "adminpass123")
    store.close()


def test_password_is_verified_with_modern_kdf_and_owner_session_revoked(tmp_path) -> None:
    store = UserAuthStore(tmp_path / "users.sqlite3")
    store.create_user(
        {"username": "user", "password": "password123", "display_name": "User"},
        actor_role="admin",
    )
    with pytest.raises(UserForbidden, match="invalid"):
        store.login("user", "wrong-password")
    result = store.login("user", "password123")
    store.logout(result["session_id"])
    with pytest.raises(UserForbidden):
        store.get_session_user(result["session_id"])
    store.close()
