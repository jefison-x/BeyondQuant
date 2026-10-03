from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main
from app import user_auth
from app.user_auth import UserAuthStore, UserConflict, UserForbidden, UserRateLimited
from app.workspace_tenancy import WorkspaceTenancyStore


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


def test_password_change_is_owner_scoped_persistent_and_revokes_all_sessions() -> None:
    store = UserAuthStore()
    alice_name = "a" + uuid.uuid4().hex[:12]
    bob_name = "b" + uuid.uuid4().hex[:12]
    alice = store.create_user(
        {"username": alice_name, "password": "old-password-123", "display_name": "Alice"},
        actor_role="admin",
    )
    bob = store.create_user(
        {"username": bob_name, "password": "other-password-123", "display_name": "Bob"},
        actor_role="admin",
    )
    alice_before = store.get_user(alice["user_id"])
    alice_sessions = [store.login(alice_name, "old-password-123")["session_id"] for _ in range(2)]
    bob_session = store.login(bob_name, "other-password-123")["session_id"]

    assert store.change_password(alice_sessions[0], {
        "current_password": "old-password-123",
        "new_password": "new-password-456",
    }) == {"status": "ok"}

    alice_after = store.get_user(alice["user_id"])
    for field in ("user_id", "username", "role", "status", "created_at"):
        assert alice_after[field] == alice_before[field]
    assert alice_after["password_changed_at"] != alice_before["password_changed_at"]
    assert "password_hash" not in alice_after
    for session_id in alice_sessions:
        with pytest.raises(UserForbidden, match="session"):
            store.get_session_user(session_id)
    with pytest.raises(UserForbidden, match="invalid username or password"):
        store.login(alice_name, "old-password-123")
    assert store.login(alice_name, "new-password-456")["user"]["user_id"] == alice["user_id"]
    assert store.get_session_user(bob_session)["user_id"] == bob["user_id"]
    store.close()


def test_failed_password_change_keeps_existing_password_and_sessions() -> None:
    store = UserAuthStore()
    username = "a" + uuid.uuid4().hex[:12]
    user = store.create_user(
        {"username": username, "password": "old-password-123", "display_name": "User"},
        actor_role="admin",
    )
    session_id = store.login(username, "old-password-123")["session_id"]

    with pytest.raises(UserForbidden, match="current password is incorrect"):
        store.change_password(session_id, {
            "current_password": "wrong-password-123",
            "new_password": "new-password-456",
        })
    with pytest.raises(ValueError, match="unknown fields"):
        store.change_password(session_id, {
            "current_password": "old-password-123",
            "new_password": "new-password-456",
            "user_id": user["user_id"],
        })

    assert store.get_session_user(session_id)["user_id"] == user["user_id"]
    assert store.login(username, "old-password-123")["user"]["user_id"] == user["user_id"]
    store.close()


def test_password_change_limiter_persists_isolates_users_and_expires(monkeypatch) -> None:
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(user_auth, "_now", lambda: now[0])
    store = UserAuthStore()
    alice_name = "a" + uuid.uuid4().hex[:12]
    bob_name = "b" + uuid.uuid4().hex[:12]
    alice = store.create_user(
        {"username": alice_name, "password": "alice-password-123", "display_name": "Alice"},
        actor_role="admin",
    )
    bob = store.create_user(
        {"username": bob_name, "password": "bob-password-12345", "display_name": "Bob"},
        actor_role="admin",
    )
    alice_session = store.login(alice_name, "alice-password-123")["session_id"]
    bob_session = store.login(bob_name, "bob-password-12345")["session_id"]
    monkeypatch.setattr(main, "user_store", store)
    client = TestClient(main.app)

    wrong = {"current_password": "wrong-password-123", "new_password": "alice-new-password"}
    for _ in range(4):
        response = client.post("/v1/auth/change-password", headers={"x-byq-session-id": alice_session}, json=wrong)
        assert response.status_code == 403
    fifth_failure = client.post("/v1/auth/change-password", headers={"x-byq-session-id": alice_session}, json=wrong)
    assert fifth_failure.status_code == 429

    original_verify = user_auth._verify_password
    monkeypatch.setattr(user_auth, "_verify_password", lambda *_args: pytest.fail("blocked request must skip scrypt"))
    locked = client.post("/v1/auth/change-password", headers={"x-byq-session-id": alice_session}, json={
        "current_password": "alice-password-123", "new_password": "alice-new-password",
    })
    assert locked.status_code == 429
    monkeypatch.setattr(user_auth, "_verify_password", original_verify)

    # The persisted budget is per user, so another account can still change its password.
    bob_changed = client.post("/v1/auth/change-password", headers={"x-byq-session-id": bob_session}, json={
        "current_password": "bob-password-12345", "new_password": "bob-new-password-123",
    })
    assert bob_changed.status_code == 200

    store.close()
    restarted = UserAuthStore()
    monkeypatch.setattr(main, "user_store", restarted)
    still_locked = TestClient(main.app).post(
        "/v1/auth/change-password",
        headers={"x-byq-session-id": alice_session},
        json={"current_password": "alice-password-123", "new_password": "alice-new-password"},
    )
    assert still_locked.status_code == 429

    now[0] += timedelta(minutes=16)
    after_window = TestClient(main.app).post(
        "/v1/auth/change-password",
        headers={"x-byq-session-id": alice_session},
        json={"current_password": "alice-password-123", "new_password": "alice-new-password"},
    )
    assert after_window.status_code == 200
    assert restarted.login(alice_name, "alice-new-password")["user"]["user_id"] == alice["user_id"]
    restarted.close()


def test_successful_password_change_resets_failure_budget() -> None:
    store = UserAuthStore()
    username = "a" + uuid.uuid4().hex[:12]
    store.create_user(
        {"username": username, "password": "old-password-123", "display_name": "User"},
        actor_role="admin",
    )
    session_id = store.login(username, "old-password-123")["session_id"]
    payload = {"current_password": "wrong-password-123", "new_password": "new-password-456"}
    for _ in range(4):
        with pytest.raises(UserForbidden, match="current password is incorrect"):
            store.change_password(session_id, payload)

    store.change_password(session_id, {
        "current_password": "old-password-123", "new_password": "new-password-456",
    })
    new_session = store.login(username, "new-password-456")["session_id"]
    next_payload = {"current_password": "wrong-password-123", "new_password": "next-password-789"}
    for _ in range(4):
        with pytest.raises(UserForbidden, match="current password is incorrect"):
            store.change_password(new_session, next_payload)
    with pytest.raises(UserRateLimited):
        store.change_password(new_session, next_payload)
    store.close()


def test_password_change_transaction_rolls_back_hash_when_session_revoke_fails(monkeypatch) -> None:
    store = UserAuthStore()
    username = "a" + uuid.uuid4().hex[:12]
    user = store.create_user(
        {"username": username, "password": "old-password-123", "display_name": "User"},
        actor_role="admin",
    )
    session_id = store.login(username, "old-password-123")["session_id"]
    original_execute = user_auth.execute

    def fail_session_delete(connection, statement, params=None):
        if statement.startswith("DELETE FROM auth_sessions"):
            raise RuntimeError("synthetic revoke failure")
        return original_execute(connection, statement, params)

    monkeypatch.setattr(user_auth, "execute", fail_session_delete)
    with pytest.raises(RuntimeError, match="synthetic revoke failure"):
        store.change_password(session_id, {
            "current_password": "old-password-123",
            "new_password": "new-password-456",
        })
    monkeypatch.setattr(user_auth, "execute", original_execute)

    assert store.get_session_user(session_id)["user_id"] == user["user_id"]
    assert store.login(username, "old-password-123")["user"]["user_id"] == user["user_id"]
    with pytest.raises(UserForbidden, match="invalid username or password"):
        store.login(username, "new-password-456")
    store.close()


def test_old_password_login_racing_change_is_revoked_at_the_transaction_boundary(monkeypatch) -> None:
    login_store = UserAuthStore()
    change_store = UserAuthStore()
    username = "a" + uuid.uuid4().hex[:12]
    user = login_store.create_user(
        {"username": username, "password": "old-password-123", "display_name": "User"},
        actor_role="admin",
    )
    change_session = login_store.login(username, "old-password-123")["session_id"]
    verifying = threading.Event()
    release_login = threading.Event()
    change_started = threading.Event()
    change_done = threading.Event()
    results: dict[str, object] = {}
    original_verify = user_auth._verify_password

    def delayed_verify(password: str, encoded: str) -> bool:
        if threading.current_thread().name == "old-password-login":
            verifying.set()
            if not release_login.wait(5):
                raise TimeoutError("login test release timed out")
        return original_verify(password, encoded)

    monkeypatch.setattr(user_auth, "_verify_password", delayed_verify)

    def run_old_login() -> None:
        try:
            results["login"] = login_store.login(username, "old-password-123")
        except Exception as exc:  # captured for assertion in the test thread
            results["login_error"] = exc

    def run_change() -> None:
        change_started.set()
        try:
            results["change"] = change_store.change_password(change_session, {
                "current_password": "old-password-123",
                "new_password": "new-password-456",
            })
        except Exception as exc:
            results["change_error"] = exc
        finally:
            change_done.set()

    login_thread = threading.Thread(target=run_old_login, name="old-password-login")
    change_thread = threading.Thread(target=run_change, name="password-change")
    login_thread.start()
    if not verifying.wait(5):
        release_login.set()
        login_thread.join(5)
        pytest.fail("login did not reach password verification")
    change_thread.start()
    if not change_started.wait(5):
        release_login.set()
        login_thread.join(5)
        change_thread.join(5)
        pytest.fail("password change did not start")
    change_finished_while_login_blocked = change_done.wait(0.2)
    release_login.set()
    login_thread.join(5)
    change_thread.join(5)
    assert not login_thread.is_alive() and not change_thread.is_alive()
    assert not change_finished_while_login_blocked, "password change must wait for an in-flight old-password login"
    assert "login_error" not in results and "change_error" not in results
    new_session_id = results["login"]["session_id"]
    with pytest.raises(UserForbidden, match="session"):
        change_store.get_session_user(new_session_id)
    assert change_store.login(username, "new-password-456")["user"]["user_id"] == user["user_id"]
    change_store.close()
    login_store.close()


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


def test_ui_preferences_are_versioned_durable_and_owner_isolated() -> None:
    store = UserAuthStore()
    alice = store.create_user(
        {"username": "alice", "password": "password123", "display_name": "Alice"},
        actor_role="admin",
    )
    bob = store.create_user(
        {"username": "bob", "password": "password123", "display_name": "Bob"},
        actor_role="admin",
    )

    assert store.get_ui_preferences(alice["user_id"]) == {
        "schema_version": "ui-preferences.v1",
        "color_mode": "system",
        "accent_theme": "emerald",
        "version": 0,
        "updated_at": None,
    }
    updated = store.update_ui_preferences(
        alice["user_id"],
        {
            "schema_version": "ui-preferences.v1",
            "color_mode": "dark",
            "accent_theme": "ocean",
            "expected_version": 0,
        },
    )
    assert updated["version"] == 1
    assert updated["color_mode"] == "dark"
    assert store.get_ui_preferences(bob["user_id"])["accent_theme"] == "emerald"

    restarted = UserAuthStore()
    assert restarted.get_ui_preferences(alice["user_id"])["accent_theme"] == "ocean"
    with pytest.raises(UserConflict, match="stale"):
        restarted.update_ui_preferences(
            alice["user_id"],
            {
                "schema_version": "ui-preferences.v1",
                "color_mode": "light",
                "accent_theme": "indigo",
                "expected_version": 0,
            },
        )
    with pytest.raises(ValueError):
        restarted.update_ui_preferences(
            alice["user_id"],
            {
                "schema_version": "ui-preferences.v1",
                "color_mode": "dark",
                "accent_theme": "custom-red",
                "expected_version": 1,
            },
        )
    restarted.close()
    store.close()


def test_ui_preferences_http_boundary_requires_exact_owner() -> None:
    store = UserAuthStore()
    alice = store.create_user(
        {"username": "alice", "password": "password123", "display_name": "Alice"},
        actor_role="admin",
    )
    bob = store.create_user(
        {"username": "bob", "password": "password123", "display_name": "Bob"},
        actor_role="admin",
    )
    client = TestClient(main.app)
    path = f"/v1/users/{alice['user_id']}/ui-preferences"

    denied = client.get(path, headers={"x-byq-owner-user-id": bob["user_id"]})
    assert denied.status_code == 403
    response = client.put(
        path,
        headers={"x-byq-owner-user-id": alice["user_id"]},
        json={
            "schema_version": "ui-preferences.v1",
            "color_mode": "dark",
            "accent_theme": "graphite",
            "expected_version": 0,
        },
    )
    assert response.status_code == 200
    assert response.json()["preferences"]["accent_theme"] == "graphite"
    assert client.get(path, headers={"x-byq-owner-user-id": alice["user_id"]}).json()["preferences"]["version"] == 1
    store.close()


def test_login_and_session_expose_same_bounded_personal_workspace(monkeypatch) -> None:
    store = UserAuthStore()
    store.create_user(
        {"username": "alice", "password": "password123", "display_name": "Alice"},
        actor_role="admin",
    )
    monkeypatch.setattr(main, "user_store", store)
    monkeypatch.setattr(main, "workspace_tenancy_store", WorkspaceTenancyStore())
    client = TestClient(main.app)
    logged_in = client.post("/v1/auth/login", json={"username": "alice", "password": "password123"})
    assert logged_in.status_code == 200
    workspace = logged_in.json()["workspace"]
    assert workspace["kind"] == "personal"
    assert workspace["role"] == "owner"
    assert "owner_user_id" not in workspace
    session = client.get(
        "/v1/auth/session", headers={"x-byq-session-id": logged_in.json()["session_id"]}
    )
    assert session.status_code == 200
    assert session.json()["workspace"] == workspace
    main.workspace_tenancy_store.close()
    store.close()


def test_change_password_http_route_uses_only_the_trusted_session(monkeypatch) -> None:
    store = UserAuthStore()
    username = "a" + uuid.uuid4().hex[:12]
    user = store.create_user(
        {"username": username, "password": "old-password-123", "display_name": "User"},
        actor_role="admin",
    )
    monkeypatch.setattr(main, "user_store", store)
    client = TestClient(main.app)

    missing_session = client.post("/v1/auth/change-password", json={
        "current_password": "old-password-123", "new_password": "new-password-456",
    })
    assert missing_session.status_code == 401

    session_id = store.login(username, "old-password-123")["session_id"]
    forbidden_target = client.post(
        "/v1/auth/change-password",
        headers={"x-byq-session-id": session_id},
        json={"current_password": "old-password-123", "new_password": "new-password-456",
              "user_id": user["user_id"]},
    )
    assert forbidden_target.status_code == 422
    assert store.get_session_user(session_id)["user_id"] == user["user_id"]

    changed = client.post(
        "/v1/auth/change-password",
        headers={"x-byq-session-id": session_id},
        json={"current_password": "old-password-123", "new_password": "new-password-456"},
    )
    assert changed.status_code == 200
    assert changed.json() == {"status": "ok"}
    assert "password" not in changed.text
    invalidated = client.get("/v1/auth/session", headers={"x-byq-session-id": session_id})
    assert invalidated.status_code == 403
    store.close()
