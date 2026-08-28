import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import ConversationCatalogStore, ConversationNotFound, deterministic_title
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set"
)


def test_deterministic_title_is_stable_and_bounded() -> None:
    assert deterministic_title("  分析   贵州茅台  ") == "分析 贵州茅台"
    assert deterministic_title("研" * 60) == "研" * 47 + "…"


def test_catalog_is_owner_scoped_and_replays_messages() -> None:
    store = ConversationCatalogStore.from_env()
    conversation = store.create("alice", "session-a", "trace-a")
    message = store.append_user_message("alice", conversation["conversation_id"], "比较两种动量策略")

    assert message["sequence"] == 1
    detail = store.get("alice", conversation["conversation_id"])
    assert detail["title"] == "比较两种动量策略"
    assert store.messages("alice", conversation["conversation_id"])[0]["content"] == "比较两种动量策略"
    try:
        store.get("bob", conversation["conversation_id"])
    except ConversationNotFound:
        pass
    else:
        raise AssertionError("another owner must not see the conversation")


def test_catalog_survives_store_recreation() -> None:
    first = ConversationCatalogStore.from_env()
    conversation = first.create("alice", "session-restart", "trace-restart")
    first.append_user_message("alice", conversation["conversation_id"], "重启后继续研究")
    first.close()

    reopened = ConversationCatalogStore.from_env()
    assert reopened.get("alice", conversation["conversation_id"])["title"] == "重启后继续研究"
    assert reopened.messages("alice", conversation["conversation_id"])[0]["content"] == "重启后继续研究"


def test_catalog_supports_pin_archive_search_and_pagination() -> None:
    store = ConversationCatalogStore.from_env()
    first = store.create("alice", "session-a", "trace-a")
    second = store.create("alice", "session-b", "trace-b")
    store.update("alice", first["conversation_id"], {"title": "动量研究", "pinned": True})
    store.update("alice", second["conversation_id"], {"title": "价值研究"})

    page = store.list("alice", search="研究", limit=1, offset=0)
    assert page["total"] == 2
    assert page["conversations"][0]["conversation_id"] == first["conversation_id"]
    store.update("alice", first["conversation_id"], {"status": "archived"})
    assert store.list("alice", status="active")["total"] == 1
    assert store.list("alice", status="archived")["total"] == 1


def test_catalog_delete_removes_messages_and_remains_owner_scoped() -> None:
    store = ConversationCatalogStore.from_env()
    conversation = store.create("alice", "session-delete", "trace-delete")
    store.append_user_message("alice", conversation["conversation_id"], "删除这段历史")

    try:
        store.delete("bob", conversation["conversation_id"])
    except ConversationNotFound:
        pass
    else:
        raise AssertionError("another owner must not delete the conversation")

    result = store.delete("alice", conversation["conversation_id"])

    assert result == {"conversation_id": conversation["conversation_id"], "deleted": True}
    assert store.list("alice")["total"] == 0
    try:
        store.get("alice", conversation["conversation_id"])
    except ConversationNotFound:
        pass
    else:
        raise AssertionError("deleted conversation must not remain readable")


def test_conversation_api_exposes_owner_scoped_permanent_delete(monkeypatch) -> None:
    store = ConversationCatalogStore.from_env()
    monkeypatch.setattr(main, "conversation_store", store)
    client = TestClient(main.app)
    client.headers.update(trusted_agent_context("conversation-owner"))
    created = client.post(
        "/v1/product/conversations",
        json={"runtime_session_id": "runtime-delete", "trace_id": "trace-delete"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["conversation"]["conversation_id"]
    assert client.post(
        f"/v1/product/conversations/{conversation_id}/messages",
        json={"content": "需要彻底删除的会话"},
    ).status_code == 201

    deleted = client.delete(f"/v1/product/conversations/{conversation_id}")

    assert deleted.status_code == 200
    assert deleted.json() == {"conversation_id": conversation_id, "deleted": True}
    assert client.get(f"/v1/product/conversations/{conversation_id}").status_code == 404
