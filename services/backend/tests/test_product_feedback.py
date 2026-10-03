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


def test_feedback_lifecycle_is_workspace_owned_and_hub_receipt_is_authoritative() -> None:
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
    assert "publication_status" not in submitted
    assert submitted["central_hub"]["status"] == "queued"
    store.hub_relay_heartbeat({
        "configured": True, "hub_origin": "https://feedback.example", "worker_version": "test-v1",
    })
    delivery = store.claim_hub_deliveries({"worker_id": "hub-relay-test", "limit": 1, "lease_seconds": 30})["events"][0]
    receipt = "cf-hub-receipt-1234567890"
    store.complete_hub_delivery(delivery["event_id"], {
        "worker_id": "hub-relay-test", "lease_fence": delivery["lease_fence"],
        "receipt_id": receipt, "status_token": "status-token-" + "x" * 40,
    })
    issue = {"repository": "jefison-x/BeyondQuant", "issue_number": 321,
             "html_url": "https://github.com/jefison-x/BeyondQuant/issues/321"}
    store.update_hub_status(delivery["event_id"], {
        "schema_version": "central-feedback-status.v1", "receipt_id": receipt,
        "status": "published", "github_issue": issue,
    })
    owner = store.get_owner(draft["feedback_id"], trusted_workspace=workspace(alice))["feedback"]
    assert owner["central_hub"] == {"status": "published", "receipt_id": receipt, "last_error_category": None}
    assert owner["github_issue"] == issue
    assert "publication_status" not in owner
    store.close()


def test_owner_projection_ignores_historical_local_publication_mapping() -> None:
    _admin, alice, bob = provision()
    store = ProductFeedbackStore()
    draft = create(store, alice, "legacy-publication-projection")
    submit(store, draft, alice, "legacy-publication-submit")
    legacy_publication_id = "feedback_publication_" + "f" * 32
    store._execute("UPDATE product_feedback SET publication_status='published' WHERE feedback_id=:feedback",
                   {"feedback": draft["feedback_id"]})
    store._execute("""INSERT INTO product_feedback_publications
        (publication_id,feedback_id,schema_version,snapshot_json,snapshot_hash,created_by,created_at,
         github_repository,github_issue_number,github_html_url,provider_identity,published_at)
        VALUES (:publication,:feedback,'feedback-publication.v1',:snapshot,:hash,'legacy',NOW(),
                'legacy-org/legacy-repo',77,'https://github.com/legacy-org/legacy-repo/issues/77','legacy-77',NOW())""",
        {"publication": legacy_publication_id, "feedback": draft["feedback_id"],
         "snapshot": {"schema_version": "feedback-publication.v1", "public_content": {}, "redactions": {}},
         "hash": "a" * 64})

    owner = store.get_owner(draft["feedback_id"], trusted_workspace=workspace(alice))["feedback"]
    assert owner["github_issue"] is None
    assert owner["central_hub"]["status"] == "queued"
    assert "publication_status" not in owner
    legacy = store._fetch_one("SELECT github_issue_number FROM product_feedback_publications WHERE publication_id=:id",
                              {"id": legacy_publication_id})
    assert legacy["github_issue_number"] == 77

    command = store._fetch_one("""SELECT command_id,result_json FROM product_feedback_commands
        WHERE scope_key=:workspace AND actor_principal=:actor AND operation=:operation AND idempotency_key=:key""",
        {"workspace": workspace(alice), "actor": alice["username"],
         "operation": f"submit:{draft['feedback_id']}", "key": "legacy-publication-submit"})
    old_receipt = command["result_json"]
    old_receipt["feedback"]["publication_status"] = "published"
    old_receipt["feedback"]["github_issue"] = {
        "repository": "legacy-org/legacy-repo", "issue_number": 77,
        "html_url": "https://github.com/legacy-org/legacy-repo/issues/77",
    }
    store._execute("UPDATE product_feedback_commands SET result_json=:result WHERE command_id=:id",
                   {"result": old_receipt, "id": command["command_id"]})
    receipt = store.reconcile_command("submit", "legacy-publication-submit", feedback_id=draft["feedback_id"],
        trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]))
    assert receipt["state"] == "confirmed"
    assert "publication_status" not in receipt["feedback"]
    assert receipt["feedback"]["github_issue"] is None
    assert receipt["feedback"]["central_hub"]["status"] == "queued"
    with pytest.raises(FeedbackNotFound):
        store.get_owner(draft["feedback_id"], trusted_workspace=workspace(bob))
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


def test_withdraw_pagination_and_rate_limit_are_bounded() -> None:
    _admin, alice, _bob = provision()
    store = ProductFeedbackStore()
    first = submit(store, create(store, alice, "create-first"), alice, "submit-first")
    second = submit(store, create(store, alice, "create-second"), alice, "submit-second")
    third = submit(store, create(store, alice, "create-third"), alice, "submit-third")
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


def test_withdraw_is_rejected_after_hub_receipt_and_review() -> None:
    _admin, alice, _bob = provision()
    store = ProductFeedbackStore()
    item = submit(store, create(store, alice), alice)
    store.hub_relay_heartbeat({
        "configured": True, "hub_origin": "https://feedback.example", "worker_version": "test-v1",
    })
    delivery = store.claim_hub_deliveries({"worker_id": "hub-relay-withdraw", "limit": 1, "lease_seconds": 30})["events"][0]
    receipt = "cf-hub-receipt-withdraw-12345"
    store.complete_hub_delivery(delivery["event_id"], {
        "worker_id": "hub-relay-withdraw", "lease_fence": delivery["lease_fence"],
        "receipt_id": receipt, "status_token": "status-token-" + "w" * 40,
    })
    with pytest.raises(FeedbackConflict, match="central hub delivery starts"):
        store.withdraw(item["feedback_id"], {
            "expected_version": item["version"], "idempotency_key": "withdraw-after-receipt",
        }, trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]))
    store.update_hub_status(delivery["event_id"], {
        "schema_version": "central-feedback-status.v1", "receipt_id": receipt, "status": "triaged",
    })
    with pytest.raises(FeedbackConflict, match="central hub delivery starts"):
        store.withdraw(item["feedback_id"], {
            "expected_version": item["version"], "idempotency_key": "withdraw-after-triage",
        }, trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]))
    current = store.get_owner(item["feedback_id"], trusted_workspace=workspace(alice))["feedback"]
    assert current["status"] == "submitted"
    assert current["central_hub"]["status"] == "triaged"
    store.close()


def test_hub_delivery_retry_fences_unknown_attempt_and_publishes_receipt() -> None:
    _admin, alice, _bob = provision()
    store = ProductFeedbackStore()
    item = submit(store, create(store, alice), alice)
    store.hub_relay_heartbeat({
        "configured": True, "hub_origin": "https://feedback.example", "worker_version": "test-v1",
    })
    first = store.claim_hub_deliveries({"worker_id": "hub-relay-one", "limit": 1, "lease_seconds": 30})["events"][0]
    assert first["attempt"] == 1 and first["lease_fence"] == 1
    with pytest.raises(FeedbackConflict, match="stale"):
        store.retry_hub_delivery(first["event_id"], {
            "worker_id": "hub-relay-one", "lease_fence": 2, "error_category": "transport_ambiguous",
            "retry_after_seconds": 5,
        })
    retry = store.retry_hub_delivery(first["event_id"], {
        "worker_id": "hub-relay-one", "lease_fence": 1, "error_category": "transport_ambiguous",
        "retry_after_seconds": 5,
    })
    assert retry["status"] == "retry_wait"
    with pytest.raises(FeedbackConflict, match="central hub delivery starts"):
        store.withdraw(item["feedback_id"], {
            "expected_version": item["version"], "idempotency_key": "withdraw-after-unknown-delivery",
        }, trusted_workspace=workspace(alice), trusted_actor=str(alice["username"]))
    store._execute("UPDATE product_feedback_hub_outbox SET next_attempt_at=NOW()-INTERVAL '1 second'")
    second = store.claim_hub_deliveries({"worker_id": "hub-relay-two", "limit": 1, "lease_seconds": 30})["events"][0]
    assert second["attempt"] == 2 and second["lease_fence"] == 2
    receipt = "cf-hub-receipt-recovered-12345"
    store.complete_hub_delivery(second["event_id"], {
        "worker_id": "hub-relay-two", "lease_fence": 2,
        "receipt_id": receipt, "status_token": "status-token-" + "r" * 40,
    })
    owner = store.get_owner(item["feedback_id"], trusted_workspace=workspace(alice))["feedback"]
    assert owner["central_hub"] == {"status": "received", "receipt_id": receipt, "last_error_category": None}
    assert owner["github_issue"] is None
    store.close()


def test_hub_outbox_insert_rolls_back_submission(monkeypatch) -> None:
    _admin, alice, _bob = provision()
    store = ProductFeedbackStore()
    draft = create(store, alice)
    original_execute = feedback_module.execute

    def fail_hub_outbox(connection, sql, params=None):
        if "INSERT INTO product_feedback_hub_outbox" in sql:
            raise RuntimeError("injected hub outbox failure")
        return original_execute(connection, sql, params)

    monkeypatch.setattr(feedback_module, "execute", fail_hub_outbox)
    with pytest.raises(RuntimeError, match="injected hub outbox failure"):
        submit(store, draft, alice, "hub-outbox-rollback")
    current = store.get_owner(draft["feedback_id"], trusted_workspace=workspace(alice))["feedback"]
    assert current["status"] == "draft" and current["central_hub"] is None
    assert store._fetch_one("SELECT COUNT(*) AS count FROM product_feedback_hub_outbox WHERE feedback_id=:feedback",
                            {"feedback": draft["feedback_id"]})["count"] == 0
    store.close()
