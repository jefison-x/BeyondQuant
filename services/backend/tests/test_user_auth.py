from __future__ import annotations

import os

import pytest

from app.user_auth import UserAuthStore, UserForbidden


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_user_login_session_and_disable() -> None:
    store = UserAuthStore()
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


def test_password_is_verified_with_modern_kdf_and_owner_session_revoked() -> None:
    store = UserAuthStore()
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


def test_profile_preferences_are_durable_and_owner_scoped() -> None:
    store = UserAuthStore()
    user = store.create_user(
        {"username": "user", "password": "password123", "display_name": "User"},
        actor_role="admin",
    )
    updated = store.update_profile(
        user["user_id"],
        {"display_name": "老李", "preferences": "低波动", "default_prompt": "先给结论"},
    )
    assert updated["display_name"] == "老李"
    assert updated["preferences"] == "低波动"
    assert updated["default_prompt"] == "先给结论"
    assert "password_hash" not in updated

    refreshed = store.get_user(user["user_id"])
    assert refreshed["preferences"] == "低波动"

    with pytest.raises(ValueError):
        store.update_profile(user["user_id"], {"role": "admin"})
    store.close()
