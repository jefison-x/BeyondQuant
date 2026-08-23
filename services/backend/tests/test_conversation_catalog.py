from app.conversation_catalog import ConversationCatalogStore, ConversationNotFound, deterministic_title


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
