from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import (
    ConversationCatalogStore,
    ConversationConflict,
    ConversationNotFound,
)
from app.user_auth import UserAuthStore
from app.workspace_reset import WorkspaceResetStore
from app.workspace_tenancy import WorkspaceTenancyStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)


@pytest.fixture
def alice_workspace():
    trusted_agent_context("alice")


def _conversation(owner: str, suffix: str) -> tuple[ConversationCatalogStore, dict[str, object]]:
    store = ConversationCatalogStore.from_env()
    unique = uuid4().hex
    return store, store.create(owner, f"session-options-{suffix}-{unique}", f"trace-options-{unique}")


def test_execution_options_get_is_read_only_and_put_is_revisioned_and_durable(alice_workspace):
    store, conversation = _conversation("alice", "durable")
    owner = "alice"
    workspace = str(conversation["workspace_id"])
    conversation_id = str(conversation["conversation_id"])

    initial = store.get_execution_options(owner, workspace, conversation_id)
    assert initial["revision"] == 0
    assert initial["options"]["auto_continue"] is True
    assert initial["options"]["max_provider_calls"] is None
    assert store._fetch_one("""SELECT conversation_id FROM product_conversation_execution_options
        WHERE conversation_id=:conversation""", {"conversation": conversation_id}) is None

    updated = store.update_execution_options(owner, workspace, conversation_id, {
        "schema_version": "agent-execution-options.v1", "expected_revision": 0,
        "options": {"auto_continue": False, "max_output_tokens_total": 1234},
    })
    assert updated["revision"] == 1
    assert updated["options"]["auto_continue"] is False
    assert updated["options"]["max_output_tokens_total"] == 1234
    assert updated["options"]["max_provider_calls"] is None
    with pytest.raises(ConversationConflict, match="stale"):
        store.update_execution_options(owner, workspace, conversation_id, {
            "schema_version": "agent-execution-options.v1", "expected_revision": 0,
            "options": {"auto_continue": True},
        })

    store.close()
    reopened = ConversationCatalogStore.from_env()
    persisted = reopened.get_execution_options(owner, workspace, conversation_id)
    assert persisted["revision"] == 1
    assert persisted["options"] == updated["options"]
    reopened.close()


def test_execution_options_scope_hides_foreign_owner_workspace_and_conversation(alice_workspace):
    store, conversation = _conversation("alice", "scope")
    conversation_id = str(conversation["conversation_id"])
    workspace = str(conversation["workspace_id"])
    with pytest.raises(ConversationNotFound):
        store.get_execution_options("bob", workspace, conversation_id)
    with pytest.raises(ConversationNotFound):
        store.get_execution_options("alice", "workspace_foreign", conversation_id)
    with pytest.raises(ConversationNotFound):
        store.get_execution_options("alice", workspace, "conversation_not_found")
    store.update("alice", conversation_id, {"status": "archived"})
    with pytest.raises(ConversationConflict, match="read-only"):
        store.update_execution_options("alice", workspace, conversation_id, {
            "schema_version": "agent-execution-options.v1", "expected_revision": 0,
            "options": {"auto_continue": False},
        })


def test_execution_options_simultaneous_same_revision_has_one_winner(alice_workspace):
    store, conversation = _conversation("alice", "cas-race")
    workspace = str(conversation["workspace_id"])
    conversation_id = str(conversation["conversation_id"])
    barrier = Barrier(2)

    def update(value: bool):
        independent = ConversationCatalogStore.from_env()
        try:
            barrier.wait()
            return independent.update_execution_options("alice", workspace, conversation_id, {
                "schema_version": "agent-execution-options.v1", "expected_revision": 0,
                "options": {"auto_continue": value},
            })
        except ConversationConflict:
            return "stale"
        finally:
            independent.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, (False, True)))
    assert sum(isinstance(value, dict) and value["revision"] == 1 for value in results) == 1
    assert results.count("stale") == 1


def test_backend_execution_options_api_requires_human_actor_only_for_update(alice_workspace, monkeypatch):
    store, conversation = _conversation("alice", "http")
    monkeypatch.setattr(main, "conversation_store", store)
    client = TestClient(main.app)
    headers = trusted_agent_context("alice")
    conversation_id = str(conversation["conversation_id"])
    path = f"/v1/product/conversations/{conversation_id}/execution-options"

    read = client.get(path, headers=headers)
    assert read.status_code == 200
    assert read.json()["options"]["auto_continue"] is True

    payload = {"schema_version": "agent-execution-options.v1", "expected_revision": 0,
               "options": {"max_tool_calls": 2}}
    assert client.put(path, headers=headers, json=payload).status_code == 403
    headers["x-byq-product-human-actor"] = "true"
    changed = client.put(path, headers=headers, json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 1

    foreign = {**headers, "x-byq-actor-principal": "bob"}
    assert client.put(path, headers=foreign, json={**payload, "expected_revision": 1}).status_code == 403
    assert client.get(path, headers={**headers, "x-byq-workspace-id": "workspace_wrong"}).status_code == 401


@pytest.mark.parametrize("disabled_scope", ["user", "workspace", "membership"])
def test_execution_options_rejects_disabled_owner_workspace_or_membership(disabled_scope):
    owner = f"options-disabled-{disabled_scope}-{uuid4().hex}"
    headers = trusted_agent_context(owner)
    workspace_id = headers["x-byq-workspace-id"]
    store, conversation = _conversation(owner, disabled_scope)
    conversation_id = str(conversation["conversation_id"])
    store.update_execution_options(owner, workspace_id, conversation_id, {
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

    with pytest.raises(ConversationNotFound):
        store.get_execution_options(owner, workspace_id, conversation_id)
    with pytest.raises(ConversationNotFound):
        store.update_execution_options(owner, workspace_id, conversation_id, {
            "schema_version": "agent-execution-options.v1", "expected_revision": 1,
            "options": {"auto_continue": True},
        })

    client = TestClient(main.app)
    path = f"/v1/product/conversations/{conversation_id}/execution-options"
    trusted_actor = {**headers, "x-byq-product-human-actor": "true"}
    assert client.get(path, headers=headers).status_code == 401
    assert client.put(path, headers=trusted_actor, json={
        "schema_version": "agent-execution-options.v1", "expected_revision": 1,
        "options": {"auto_continue": True},
    }).status_code == 401


def test_workspace_reset_archives_and_clears_only_its_execution_options():
    owner = f"options-reset-{uuid4().hex}"
    foreign_owner = f"options-reset-foreign-{uuid4().hex}"
    owner_context = trusted_agent_context(owner)
    foreign_context = trusted_agent_context(foreign_owner)
    catalog, conversation = _conversation(owner, "reset-target")
    foreign_catalog, foreign_conversation = _conversation(foreign_owner, "reset-foreign")
    conversation_id = str(conversation["conversation_id"])
    foreign_conversation_id = str(foreign_conversation["conversation_id"])
    catalog.update_execution_options(owner, owner_context["x-byq-workspace-id"], conversation_id, {
        "schema_version": "agent-execution-options.v1", "expected_revision": 0,
        "options": {"auto_continue": False, "max_tool_calls": 7},
    })
    foreign_catalog.update_execution_options(
        foreign_owner, foreign_context["x-byq-workspace-id"], foreign_conversation_id, {
            "schema_version": "agent-execution-options.v1", "expected_revision": 0,
            "options": {"auto_continue": True, "max_tool_calls": 3},
        })
    reset = WorkspaceResetStore()
    try:
        result = reset.reset_workspace(
            owner_principal=owner, workspace_id=owner_context["x-byq-workspace-id"])
        assert result["deleted"]["product_conversation_execution_options"] == 1
        archived = reset._fetch_one("""SELECT payload_json FROM workspace_reset_archives
            WHERE reset_id=:reset""", {"reset": result["archive"]["reset_id"]})["payload_json"]
        snapshots = archived["tables"]["product_conversation_execution_options"]
        assert any(row["conversation_id"] == conversation_id
                   and row["options_json"]["max_tool_calls"] == 7 for row in snapshots)
        assert reset._fetch_one("""SELECT conversation_id FROM product_conversation_execution_options
            WHERE conversation_id=:conversation""", {"conversation": conversation_id}) is None
        foreign_row = reset._fetch_one("""SELECT owner_principal, options_json
            FROM product_conversation_execution_options WHERE conversation_id=:conversation""",
            {"conversation": foreign_conversation_id})
        assert foreign_row == {"owner_principal": foreign_owner,
                               "options_json": foreign_catalog.get_execution_options(
                                   foreign_owner, foreign_context["x-byq-workspace-id"],
                                   foreign_conversation_id)["options"]}
    finally:
        reset.close()
        catalog.close()
        foreign_catalog.close()
