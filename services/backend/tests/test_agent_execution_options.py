from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import ConversationCatalogStore
from app.user_auth import UserAuthStore, UserConflict
from app.workspace_reset import WorkspaceResetStore
from app.workspace_tenancy import WorkspaceTenancyStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)


@pytest.fixture
def alice_workspace():
    owner = f"agent-options-{uuid4().hex}"
    headers = trusted_agent_context(owner)
    users = UserAuthStore()
    user = users._fetch_one("SELECT user_id, role FROM users WHERE username=:owner", {"owner": owner})
    users.close()
    return owner, headers, user


def _conversation(owner: str, suffix: str) -> tuple[ConversationCatalogStore, dict[str, object]]:
    store = ConversationCatalogStore.from_env()
    unique = uuid4().hex
    return store, store.create(owner, f"session-options-{suffix}-{unique}", f"trace-options-{unique}")


def test_execution_options_are_user_scoped_revisioned_and_durable(alice_workspace):
    owner, _headers, user = alice_workspace
    store, conversation = _conversation(owner, "durable")
    other_conversation = store.create(
        owner, f"session-options-same-user-{uuid4().hex}", f"trace-options-same-user-{uuid4().hex}",
    )
    workspace = str(conversation["workspace_id"])
    conversation_id = str(conversation["conversation_id"])
    users = UserAuthStore()
    user_id = user["user_id"]

    initial = users.get_agent_execution_options(user_id)
    assert initial["scope"] == "user"
    assert "conversation_id" not in initial and "workspace_id" not in initial
    assert initial["revision"] == 0
    assert initial["options"]["auto_continue"] is True
    assert initial["options"]["max_provider_calls"] is None
    assert store._fetch_one("""SELECT conversation_id FROM product_conversation_execution_options
        WHERE conversation_id=:conversation""", {"conversation": conversation_id}) is None

    # A pre-existing conversation row stays historical and never becomes the
    # active user setting.
    legacy = {"auto_continue": False, "max_tool_calls": 11}
    store._execute("""INSERT INTO product_conversation_execution_options
        (conversation_id, owner_principal, workspace_id, revision, options_json, updated_at)
        VALUES (:conversation, :owner, :workspace, 3, :options, now())""",
        {"conversation": conversation_id, "owner": owner, "workspace": workspace,
         "options": legacy})
    assert users.get_agent_execution_options(user_id) == initial

    updated = users.update_agent_execution_options(user_id, {
        "schema_version": "agent-execution-options.v1", "expected_revision": 0,
        "options": {"auto_continue": False, "max_output_tokens_total": 1234},
    })
    assert updated["revision"] == 1
    assert updated["options"]["auto_continue"] is False
    assert updated["options"]["max_output_tokens_total"] == 1234
    assert updated["options"]["max_provider_calls"] is None
    assert store._fetch_one("""SELECT revision, options_json FROM product_conversation_execution_options
        WHERE conversation_id=:conversation""", {"conversation": conversation_id}) == {
            "revision": 3, "options_json": legacy,
        }
    assert users.get_agent_execution_options(user_id) == updated
    with pytest.raises(UserConflict, match="stale"):
        users.update_agent_execution_options(user_id, {
            "schema_version": "agent-execution-options.v1", "expected_revision": 0,
            "options": {"auto_continue": True},
        })

    store.close()
    users.close()
    reopened = UserAuthStore.from_env()
    persisted = reopened.get_agent_execution_options(user_id)
    assert persisted["revision"] == 1
    assert persisted["options"] == updated["options"]
    reopened.close()
    assert initial["options"]["auto_continue"] is True
    assert other_conversation["workspace_id"] == conversation["workspace_id"]


def test_execution_options_simultaneous_same_revision_has_one_winner(alice_workspace):
    _owner, _headers, user = alice_workspace
    user_id = user["user_id"]
    barrier = Barrier(2)

    def update(value: bool):
        independent = UserAuthStore.from_env()
        try:
            barrier.wait()
            return independent.update_agent_execution_options(user_id, {
                "schema_version": "agent-execution-options.v1", "expected_revision": 0,
                "options": {"auto_continue": value},
            })
        except UserConflict:
            return "stale"
        finally:
            independent.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, (False, True)))
    assert sum(isinstance(value, dict) and value["revision"] == 1 for value in results) == 1
    assert results.count("stale") == 1


def test_backend_user_execution_options_api_is_owner_scoped_and_not_admin_gated(alice_workspace, monkeypatch):
    owner, headers, user = alice_workspace
    user_id = user["user_id"]
    client = TestClient(main.app)
    path = "/v1/users/agent-execution-options"
    gateway_token = "g" * 48
    runtime_token = "r" * 48
    monkeypatch.setattr(main, "GATEWAY_SERVICE_TOKEN", gateway_token)
    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", runtime_token)
    scoped = {"authorization": f"Bearer {gateway_token}", "x-byq-owner-user-id": user_id}

    assert client.get(path, headers={"x-byq-owner-user-id": user_id}).status_code == 401
    assert client.get("/v1/product/conversations/conversation_retired/execution-options",
                      headers=headers).status_code == 404

    read = client.get(path, headers=scoped)
    assert read.status_code == 200
    assert read.json()["scope"] == "user"
    assert read.json()["owner_principal"] == owner
    assert read.json()["options"]["auto_continue"] is True
    assert "conversation_id" not in read.json() and "workspace_id" not in read.json()

    payload = {"schema_version": "agent-execution-options.v1", "expected_revision": 0,
               "options": {"max_tool_calls": 2}}
    assert client.put(path, headers=scoped, json=payload).status_code == 403
    assert client.put(path, headers={
        "authorization": f"Bearer {runtime_token}",
        "x-byq-owner-user-id": user_id,
        "x-byq-actor-principal": owner,
        "x-byq-product-human-actor": "true",
    }, json=payload).status_code == 401
    actor_headers = {**scoped, "x-byq-actor-principal": owner, "x-byq-product-human-actor": "true"}
    changed = client.put(path, headers=actor_headers, json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 1

    stale = client.put(path, headers=actor_headers, json=payload)
    assert stale.status_code == 409
    foreign = trusted_agent_context(f"foreign-options-{uuid4().hex}")
    foreign_user = UserAuthStore()
    foreign_row = foreign_user._fetch_one("SELECT user_id FROM users WHERE username=:owner",
                                          {"owner": foreign["x-byq-owner-principal"]})
    foreign_options = foreign_user.get_agent_execution_options(foreign_row["user_id"])
    foreign_user.close()
    assert client.put(path, headers={**scoped, "x-byq-actor-principal": "someone-else",
                                     "x-byq-product-human-actor": "true"},
                      json={**payload, "expected_revision": 1}).status_code == 403
    assert user["role"] == "user"
    assert foreign_options["revision"] == 0
    assert set(read.json()) == {
        "schema_version", "scope", "owner_principal", "revision", "options", "updated_at",
    }

    # A misconfigured service token must not make a Runtime bearer writable.
    monkeypatch.setattr(main, "GATEWAY_SERVICE_TOKEN", runtime_token)
    assert client.put(path, headers={
        "authorization": f"Bearer {runtime_token}",
        "x-byq-owner-user-id": user_id,
        "x-byq-actor-principal": owner,
        "x-byq-product-human-actor": "true",
    }, json={**payload, "expected_revision": 1}).status_code == 503
    assert main.user_store.get_agent_execution_options(user_id)["revision"] == 1

    # Runtime keeps its established owner/Workspace identity and authority
    # token when reading the same user-level projection.
    monkeypatch.setattr(main, "GATEWAY_SERVICE_TOKEN", gateway_token)
    runtime_headers = {
        "authorization": f"Bearer {runtime_token}",
        "x-byq-owner-principal": owner,
        "x-byq-workspace-id": headers["x-byq-workspace-id"],
    }
    runtime_read = client.get(path, headers=runtime_headers)
    assert runtime_read.status_code == 200
    assert runtime_read.json() == changed.json()
    assert client.get(path, headers={
        **runtime_headers, "x-byq-owner-principal": "foreign-user",
    }).status_code == 401
    assert client.get(path, headers={
        "x-byq-owner-principal": owner,
        "x-byq-workspace-id": headers["x-byq-workspace-id"],
    }).status_code == 401


@pytest.mark.parametrize("disabled_scope", ["user", "workspace", "membership"])
def test_execution_options_rejects_disabled_owner_but_is_workspace_independent(disabled_scope, monkeypatch):
    owner = f"options-disabled-{disabled_scope}-{uuid4().hex}"
    headers = trusted_agent_context(owner)
    workspace_id = headers["x-byq-workspace-id"]
    gateway_token = "g" * 48
    monkeypatch.setattr(main, "GATEWAY_SERVICE_TOKEN", gateway_token)
    users = UserAuthStore()
    user = users._fetch_one("SELECT user_id FROM users WHERE username=:owner", {"owner": owner})
    options = users.update_agent_execution_options(user["user_id"], {
        "schema_version": "agent-execution-options.v1", "expected_revision": 0,
        "options": {"auto_continue": False},
    })

    if disabled_scope == "user":
        users = UserAuthStore()
        user = users._fetch_one("SELECT user_id FROM users WHERE username=:owner", {"owner": owner})
        users.disable_user(user["user_id"], actor_role="admin")
        users.close()
    elif disabled_scope == "workspace":
        tenancy = WorkspaceTenancyStore()
        tenancy._execute("UPDATE workspaces SET status='disabled' WHERE workspace_id=:workspace",
                         {"workspace": workspace_id})
        tenancy.close()
    else:
        tenancy = WorkspaceTenancyStore()
        tenancy._execute("""UPDATE workspace_memberships SET status='disabled'
            WHERE workspace_id=:workspace""", {"workspace": workspace_id})
        tenancy.close()

    client = TestClient(main.app)
    user_settings_path = "/v1/users/agent-execution-options"
    request_headers = {
        "authorization": f"Bearer {gateway_token}",
        "x-byq-owner-user-id": user["user_id"],
    }
    if disabled_scope == "user":
        assert client.get(user_settings_path, headers=request_headers).status_code == 403
    else:
        assert client.get(user_settings_path, headers=request_headers).status_code == 200
        assert users.get_agent_execution_options(user["user_id"])["options"]["auto_continue"] is False
    assert options["options"]["auto_continue"] is False
    users.close()


def test_workspace_reset_archives_legacy_rows_and_preserves_user_options():
    owner = f"options-reset-{uuid4().hex}"
    foreign_owner = f"options-reset-foreign-{uuid4().hex}"
    owner_context = trusted_agent_context(owner)
    foreign_context = trusted_agent_context(foreign_owner)
    catalog, conversation = _conversation(owner, "reset-target")
    foreign_catalog, foreign_conversation = _conversation(foreign_owner, "reset-foreign")
    conversation_id = str(conversation["conversation_id"])
    foreign_conversation_id = str(foreign_conversation["conversation_id"])
    legacy_owner_options = {"auto_continue": False, "max_tool_calls": 7}
    legacy_foreign_options = {"auto_continue": True, "max_tool_calls": 3}
    catalog._execute("""INSERT INTO product_conversation_execution_options
        (conversation_id, owner_principal, workspace_id, revision, options_json, updated_at)
        VALUES (:conversation, :owner, :workspace, 4, :options, now())""",
        {"conversation": conversation_id, "owner": owner,
         "workspace": owner_context["x-byq-workspace-id"], "options": legacy_owner_options})
    foreign_catalog._execute("""INSERT INTO product_conversation_execution_options
        (conversation_id, owner_principal, workspace_id, revision, options_json, updated_at)
        VALUES (:conversation, :owner, :workspace, 2, :options, now())""",
        {"conversation": foreign_conversation_id, "owner": foreign_owner,
         "workspace": foreign_context["x-byq-workspace-id"], "options": legacy_foreign_options})
    users = UserAuthStore()
    owner_user = users._fetch_one("SELECT user_id FROM users WHERE username=:owner", {"owner": owner})
    foreign_user = users._fetch_one("SELECT user_id FROM users WHERE username=:owner", {"owner": foreign_owner})
    default_owner_options = users.get_agent_execution_options(owner_user["user_id"])
    assert default_owner_options["revision"] == 0
    assert default_owner_options["options"]["auto_continue"] is True
    owner_options = users.update_agent_execution_options(owner_user["user_id"], {
        "schema_version": "agent-execution-options.v1", "expected_revision": 0,
        "options": {"auto_continue": True, "max_tool_calls": 5},
    })
    foreign_options = users.update_agent_execution_options(foreign_user["user_id"], {
        "schema_version": "agent-execution-options.v1", "expected_revision": 0,
        "options": {"auto_continue": False, "max_tool_calls": 6},
    })
    # The old session row remains historical and is not promoted into the
    # user's active preference.
    assert owner_options["revision"] == 1
    reset = WorkspaceResetStore()
    try:
        result = reset.reset_workspace(
            owner_principal=owner, workspace_id=owner_context["x-byq-workspace-id"])
        assert result["deleted"]["product_conversation_execution_options"] == 1
        archived = reset._fetch_one("""SELECT payload_json FROM workspace_reset_archives
            WHERE reset_id=:reset""", {"reset": result["archive"]["reset_id"]})["payload_json"]
        snapshots = archived["tables"]["product_conversation_execution_options"]
        assert any(row["conversation_id"] == conversation_id
                   and row["options_json"] == legacy_owner_options for row in snapshots)
        assert reset._fetch_one("""SELECT conversation_id FROM product_conversation_execution_options
            WHERE conversation_id=:conversation""", {"conversation": conversation_id}) is None
        foreign_row = reset._fetch_one("""SELECT owner_principal, options_json
            FROM product_conversation_execution_options WHERE conversation_id=:conversation""",
            {"conversation": foreign_conversation_id})
        assert foreign_row == {"owner_principal": foreign_owner,
                               "options_json": legacy_foreign_options}
        assert users.get_agent_execution_options(owner_user["user_id"]) == owner_options
        assert users.get_agent_execution_options(foreign_user["user_id"]) == foreign_options
    finally:
        reset.close()
        users.close()
        catalog.close()
        foreign_catalog.close()
