from __future__ import annotations

import os

import pytest

from app import product_feedback as feedback_module
from app.product_feedback import (
    FeedbackConflict,
    FeedbackForbidden,
    FeedbackNotFound,
    FeedbackRateLimited,
    FeedbackUnsafe,
    ProductFeedbackStore,
)
from app.user_auth import UserAuthStore
from app.workspace_tenancy import WorkspaceTenancyStore


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set")


def provision() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    users = UserAuthStore()
    admin = users.create_user(
        {"username": "feedback-admin", "password": "Password-123!", "display_name": "Feedback Admin", "role": "admin"},
        actor_role="admin",
    )
    alice = users.create_user(
        {"username": "feedback-alice", "password": "Password-123!", "display_name": "Alice", "role": "user"},
        actor_role="admin",
    )
    bob = users.create_user(
        {"username": "feedback-bob", "password": "Password-123!", "display_name": "Bob", "role": "user"},
        actor_role="admin",
    )
    users.close()
    return admin, alice, bob


def workspace(user: dict[str, object]) -> str:
    tenancy = WorkspaceTenancyStore()
    result = str(tenancy.public_workspace(str(user["user_id"]))["workspace_id"])
    tenancy.close()
    return result


def content(title: str = "模型研究详情加载速度较慢") -> dict[str, object]:
    return {
        "schema_version": "product-feedback.v1",
        "category": "performance",
        "component": "model_research",
        "title": title,
        "description": "选择一条研究后，详情需要等待较长时间才能显示。",
        "reproduction_steps": ["打开模型研究", "选择第一条研究记录"],
        "expected_behavior": "详情快速显示。",
        "actual_behavior": "加载状态持续较长时间。",
        "severity": "normal",
        "diagnostics": {
            "include_product_version": True,
            "include_deployment_kind": True,
            "include_browser_family": True,
            "include_os_family": True,
            "include_performance_summary": False,
        },
    }


def create(store: ProductFeedbackStore, user: dict[str, object], key: str = "feedback-create-1") -> dict[str, object]:
    return store.create(
        {**content(), "idempotency_key": key},
        trusted_workspace=workspace(user), trusted_owner=str(user["username"]), trusted_actor=str(user["username"]),
    )["feedback"]


def submit(store: ProductFeedbackStore, feedback: dict[str, object], user: dict[str, object], key: str = "feedback-submit-1") -> dict[str, object]:
    preview = store.preview(
        feedback["feedback_id"], trusted_workspace=workspace(user), expected_version=feedback["version"],
        browser_family="chrome", os_family="linux",
    )
    assert preview["public_content"]["environment"] == {
        "browser_family": "chrome", "deployment_kind": "self_hosted",
        "os_family": "linux", "product_version": "0.1.0",
    }
    return store.submit(
        feedback["feedback_id"],
        {"expected_version": feedback["version"], "preview_hash": preview["preview_hash"],
         "disclosure_confirmed": True, "idempotency_key": key},
        trusted_workspace=workspace(user), trusted_actor=str(user["username"]),
        browser_family="chrome", os_family="linux",
    )["feedback"]


def test_feedback_lifecycle_is_workspace_owned_and_accept_enqueues_atomically() -> None:
    _admin, alice, bob = provision()
    store = ProductFeedbackStore()
    draft = create(store, alice)
    assert draft["status"] == "draft"
    assert "workspace_id" not in draft and "owner_principal" not in draft
    replay = create(store, alice)
    assert replay["feedback_id"] == draft["feedback_id"]
    with pytest.raises(FeedbackNotFound):
        store.get_owner(draft["feedback_id"], trusted_workspace=workspace(bob))

    updated = store.update(
        draft["feedback_id"],
        {"content": content("模型研究详情首次加载速度较慢"), "expected_version": 1, "idempotency_key": "update-1"},
        trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]),
    )["feedback"]
    assert updated["version"] == 2 and updated["current_revision"] == 2
    revisions = store.list_revisions(draft["feedback_id"], trusted_workspace=workspace(alice), limit=1)
    assert revisions["total"] == 2 and revisions["has_more"] is True

    submitted = submit(store, updated, alice)
    assert submitted["status"] == "submitted"
    moderation = store.list_moderation(actor_role="admin")
    assert moderation["total"] == 1
    moderated = moderation["items"][0]
    assert "workspace_id" not in moderated and "owner_principal" not in moderated
    assert moderated["submitted_snapshot"]["public_content"]["title"] == updated["title"]
    with pytest.raises(FeedbackForbidden):
        store.list_moderation(actor_role="user")

    triaged = store.moderate(
        draft["feedback_id"], "triage",
        {"expected_version": submitted["version"], "rationale": "已确认可复现", "idempotency_key": "triage-1"},
        trusted_actor="feedback-admin", actor_role="admin",
    )["feedback"]
    accepted = store.moderate(
        draft["feedback_id"], "accept",
        {"expected_version": triaged["version"], "rationale": "进入公开问题队列", "idempotency_key": "accept-1"},
        trusted_actor="feedback-admin", actor_role="admin",
    )["feedback"]
    assert accepted["status"] == "accepted"
    assert accepted["publication_status"] == "publisher_unconfigured"
    assert store.outbox_summary(actor_role="admin")["queue"] == {"queued": 1}
    publication = store._fetch_one("SELECT snapshot_json FROM product_feedback_publications WHERE feedback_id=:id", {"id": draft["feedback_id"]})
    assert publication["snapshot_json"]["schema_version"] == "feedback-publication.v1"
    outbox = store._fetch_one("SELECT state,destination_key,attempt,lease_owner FROM product_feedback_outbox WHERE feedback_id=:id", {"id": draft["feedback_id"]})
    assert outbox == {"state": "queued", "destination_key": "github_primary", "attempt": 0, "lease_owner": None}
    store.close()


def test_preview_requires_exact_version_confirmation_and_safe_content() -> None:
    _admin, alice, _bob = provision()
    store = ProductFeedbackStore()
    draft = create(store, alice)
    preview = store.preview(draft["feedback_id"], trusted_workspace=workspace(alice), expected_version=1)
    with pytest.raises(FeedbackForbidden, match="explicitly confirmed"):
        store.submit(
            draft["feedback_id"], {"expected_version": 1, "preview_hash": preview["preview_hash"],
                                   "disclosure_confirmed": False, "idempotency_key": "submit-no"},
            trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]),
        )
    with pytest.raises(FeedbackConflict, match="preview changed"):
        store.submit(
            draft["feedback_id"], {"expected_version": 1, "preview_hash": "0" * 64,
                                   "disclosure_confirmed": True, "idempotency_key": "submit-stale"},
            trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]),
        )
    for unsafe in (
        "password=do-not-store-this", "ghp_abcdefghijklmnopqrstuvwxyz1234",
        "security vulnerability permits remote code execution", "person@example.com", "https://example.com/log",
    ):
        with pytest.raises(FeedbackUnsafe):
            store.create(
                {**content("反馈内容需要安全检查"), "description": unsafe, "idempotency_key": f"unsafe-{len(unsafe)}"},
                trusted_workspace=workspace(alice), trusted_owner=str(alice["username"]), trusted_actor=str(alice["username"]),
            )
    assert store.list_owner(trusted_workspace=workspace(alice))["total"] == 1
    store.close()


def test_withdraw_duplicate_pagination_and_rate_limit_are_bounded() -> None:
    _admin, alice, _bob = provision()
    store = ProductFeedbackStore()
    canonical = create(store, alice, "create-canonical")
    canonical = submit(store, canonical, alice, "submit-canonical")
    canonical = store.moderate(
        canonical["feedback_id"], "triage",
        {"expected_version": canonical["version"], "rationale": "canonical item", "idempotency_key": "triage-canonical"},
        trusted_actor="feedback-admin", actor_role="admin",
    )["feedback"]

    second = create(store, alice, "create-second")
    second = submit(store, second, alice, "submit-second")
    second = store.moderate(
        second["feedback_id"], "triage",
        {"expected_version": second["version"], "rationale": "duplicate candidate", "idempotency_key": "triage-second"},
        trusted_actor="feedback-admin", actor_role="admin",
    )["feedback"]
    duplicate = store.moderate(
        second["feedback_id"], "duplicate",
        {"expected_version": second["version"], "rationale": "same reproduction",
         "canonical_feedback_id": canonical["feedback_id"], "idempotency_key": "duplicate-second"},
        trusted_actor="feedback-admin", actor_role="admin",
    )["feedback"]
    assert duplicate["status"] == "duplicate"
    assert "canonical_feedback_id" not in duplicate

    third = create(store, alice, "create-third")
    third = submit(store, third, alice, "submit-third")
    withdrawn = store.withdraw(
        third["feedback_id"], {"expected_version": third["version"], "idempotency_key": "withdraw-third"},
        trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]),
    )["feedback"]
    assert withdrawn["status"] == "withdrawn"
    page = store.list_owner(trusted_workspace=workspace(alice), limit=2, offset=0)
    assert page["total"] == 3 and len(page["items"]) == 2 and page["has_more"] is True

    for index in range(3, 10):
        create(store, alice, f"create-{index}")
    with pytest.raises(FeedbackRateLimited):
        create(store, alice, "create-over-limit")
    store.close()


def test_accept_and_outbox_roll_back_as_one_transaction(monkeypatch) -> None:
    _admin, alice, _bob = provision()
    store = ProductFeedbackStore()
    item = submit(store, create(store, alice), alice)
    item = store.moderate(
        item["feedback_id"], "triage",
        {"expected_version": item["version"], "rationale": "ready for review", "idempotency_key": "rollback-triage"},
        trusted_actor="feedback-admin", actor_role="admin",
    )["feedback"]
    original_execute = feedback_module.execute

    def fail_outbox(connection, sql, params=None):
        if "INSERT INTO product_feedback_outbox" in sql:
            raise RuntimeError("injected outbox failure")
        return original_execute(connection, sql, params)

    monkeypatch.setattr(feedback_module, "execute", fail_outbox)
    with pytest.raises(RuntimeError, match="injected outbox failure"):
        store.moderate(
            item["feedback_id"], "accept",
            {"expected_version": item["version"], "rationale": "queue publication", "idempotency_key": "rollback-accept"},
            trusted_actor="feedback-admin", actor_role="admin",
        )
    current = store.get_moderation(item["feedback_id"], actor_role="admin")["feedback"]
    assert current["status"] == "triaged" and current["publication_status"] == "not_queued"
    assert store._fetch_one("SELECT COUNT(*) AS count FROM product_feedback_publications")["count"] == 0
    assert store._fetch_one("SELECT COUNT(*) AS count FROM product_feedback_outbox")["count"] == 0
    store.close()
