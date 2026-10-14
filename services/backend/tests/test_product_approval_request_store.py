"""PostgreSQL contract for typed Product approval persistence and isolation."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.exc import SQLAlchemyError
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import ConversationCatalogStore
from app.product_approval_requests import ProductApprovalConflict, ProductApprovalNotFound
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def _context(owner: str):
    headers = trusted_agent_context(owner, session_id=f"{owner}-session", trace_id=f"{owner}-trace")
    return {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}


def test_typed_requests_bind_exact_scope_and_keep_attention_separate_from_pending():
    owner = "approval-store-owner"
    context = _context(owner)
    catalog = ConversationCatalogStore()
    catalog.create(owner, context["session_id"], context["trace_id"])
    catalog.close()
    store = ResearchStore()
    try:
        task = store.create_task({"owner_principal": owner, "title": "Approval fixture",
            "objective": "Exercise the typed approval store.", "trace_id": context["trace_id"],
            "idempotency_key": "approval-store-task"}, trusted_context=context)
        strategy = store.create_artifact({"task_id": task["task_id"], "kind": "strategy_version",
            "content": {"synthetic": "strategy"}, "lineage": [], "trace_id": context["trace_id"],
            "idempotency_key": "approval-store-strategy"})
        strategy = store.transition("artifact", strategy["artifact_id"], "validated", "approval-store-strategy-validated")
        ml_strategy = store.create_artifact({"task_id": task["task_id"], "kind": "ml_strategy_version",
            "content": {"synthetic": "ml-strategy"}, "lineage": [], "trace_id": context["trace_id"],
            "idempotency_key": "approval-store-ml-strategy"})
        ml_strategy = store.transition("artifact", ml_strategy["artifact_id"], "validated", "approval-store-ml-validated")

        strategy_body = {"schema_version": "byq-product-approval-request.v1", "request_type": "strategy_version",
            "request_key": "approval-store-strategy-request", "task_id": task["task_id"],
            "strategy_version_artifact_id": strategy["artifact_id"]}
        strategy_request = store.create_product_approval_request(strategy_body, owner=owner,
            workspace=context["workspace_id"])
        assert store.create_product_approval_request(strategy_body, owner=owner,
            workspace=context["workspace_id"])["request"] == strategy_request["request"]
        with pytest.raises(ProductApprovalConflict):
            store.create_product_approval_request({**strategy_body, "request_key": "another-strategy-key"},
                owner=owner, workspace=context["workspace_id"])

        ml_body = {"schema_version": "byq-product-approval-request.v1", "request_type": "ml_strategy_version",
            "request_key": "approval-store-ml-request", "task_id": task["task_id"],
            "ml_strategy_artifact_id": ml_strategy["artifact_id"]}
        store.create_product_approval_request(ml_body, owner=owner, workspace=context["workspace_id"])

        continuation_body = {"schema_version": "byq-product-approval-request.v1", "request_type": "continuation_consent",
            "request_key": "approval-store-continuation", "task_id": task["task_id"],
            "confirmed_artifact_ids": [strategy["artifact_id"]], "execution_profile_id": "task-ready-read.v1"}
        continuation = store.create_product_approval_request(continuation_body, owner=owner,
            workspace=context["workspace_id"])
        continuation_request = continuation["request"]
        decision_key = "approval-store-decision"
        claimed, did_claim = store.claim_product_approval_decision(continuation_request["request_id"],
            owner=owner, workspace=context["workspace_id"], decision="approved", decision_key=decision_key,
            rationale="approved exact test resource", actor=owner)
        assert did_claim is True
        replay, did_claim_again = store.claim_product_approval_decision(continuation_request["request_id"],
            owner=owner, workspace=context["workspace_id"], decision="approved", decision_key=decision_key,
            rationale="approved exact test resource", actor=owner)
        assert did_claim_again is False
        assert replay["request"]["decision_key"] == claimed["request"]["decision_key"]
        with pytest.raises(ProductApprovalConflict):
            store.claim_product_approval_decision(continuation_request["request_id"], owner=owner,
                workspace=context["workspace_id"], decision="rejected", decision_key="different-decision-key",
                rationale="conflicting decision", actor=owner)

        profile = continuation_request["execution_profile_id"]
        permission = store.create_continuation_permission(task["task_id"], {
            "idempotency_key": f"product-approval-{continuation_request['request_id']}",
            "execution_profile_id": profile,
            "confirmed_artifact_ids": continuation_request["confirmed_artifact_ids"],
        }, trusted_context=context)
        assert permission["permission"]["confirmation_id"] == f"product-approval-{continuation_request['request_id']}"
        ledger = store.get_continuation_permission_snapshot_readonly(task["task_id"], trusted_context=context)["ledger"]
        assert ledger["owner_principal"] == owner
        assert ledger["workspace_id"] == context["workspace_id"]
        with pytest.raises(ProductApprovalConflict):
            store.create_product_approval_request({**continuation_body, "request_key": "replacement-continuation"},
                owner=owner, workspace=context["workspace_id"])

        store.finish_product_approval_decision(continuation_request["request_id"], owner=owner,
            workspace=context["workspace_id"], status="approved", permission=permission)
        strategy_id = strategy_request["request"]["request_id"]
        store.claim_product_approval_decision(strategy_id, owner=owner, workspace=context["workspace_id"],
            decision="approved", decision_key="approval-store-strategy-decision",
            rationale="approved strategy request with uncertain materialization", actor=owner)
        store.finish_product_approval_decision(strategy_id, owner=owner,
            workspace=context["workspace_id"], status="outcome_unknown")
        page = store.list_product_approval_requests(owner=owner, workspace=context["workspace_id"],
            status="pending", limit=50, offset=0)
        assert page["total"] == 1 and page["pending_count"] == 1 and page["attention_count"] == 1
        attention = store.list_product_approval_requests(owner=owner, workspace=context["workspace_id"],
            status="unresolved", limit=50, offset=0)
        assert attention["total"] == 1 and attention["requests"][0]["status"] == "outcome_unknown"
        all_rows = store.list_product_approval_requests(owner=owner, workspace=context["workspace_id"],
            status="all", limit=50, offset=0)
        assert all_rows["total"] == 3
        with pytest.raises(ProductApprovalNotFound):
            store.get_product_approval_request(strategy_request["request"]["request_id"], owner="foreign-owner",
                workspace=context["workspace_id"])
        assert store._fetch_one("SELECT to_regclass('product_approval_requests') AS name")["name"] == "product_approval_requests"
    finally:
        store.close()


def test_continuation_approval_rejects_configuration_or_artifact_drift_before_grant(monkeypatch):
    """The frozen Product request is rechecked against current domain facts in the grant TX."""
    from app import research_continuation
    from packages.contracts import continuation_request
    from tests.test_research_continuation import setup_permission

    store, task_id, context, grant_payload = setup_permission()
    try:
        body = {"schema_version": "byq-product-approval-request.v1", "request_type": "continuation_consent",
            "request_key": "approval-freeze-drift-request", "task_id": task_id,
            "confirmed_artifact_ids": grant_payload["confirmed_artifact_ids"],
            "execution_profile_id": "task-ready-read.v1"}
        record = store.create_product_approval_request(body, owner=context["owner_principal"],
            workspace=context["workspace_id"])["request"]

        def frozen_snapshot():
            return {
                "idempotency_key": f"product-approval-{record['request_id']}",
                "task_id": record["task_id"], "owner_principal": record["owner_principal"],
                "workspace_id": record["workspace_id"], "conversation_id": record["conversation_id"],
                "execution_profile": record["execution_profile"], "request_limits": record["request_limits"],
                "confirmed_artifact_ids": record["confirmed_artifact_ids"],
                "confirmed_artifacts": record["confirmed_artifacts"], "max_turns": record["max_turns"],
                "valid_seconds": record["valid_seconds"], "turn_timeout_seconds": record["turn_timeout_seconds"],
            }

        payload = {"idempotency_key": f"product-approval-{record['request_id']}",
            "execution_profile_id": record["execution_profile_id"],
            "confirmed_artifact_ids": record["confirmed_artifact_ids"]}

        # Simulate a deployment configuration change after request creation. Both the
        # canonical validator and grant builder see the changed binding/limits, while
        # the typed request remains frozen at its original values.
        changed_profile = {**record["execution_profile"], "profile_sha256": "f" * 64}
        changed_limits = {**record["request_limits"], "deadline_ms": record["request_limits"]["deadline_ms"] - 1}
        with monkeypatch.context() as drift:
            drift.setattr(continuation_request, "profile_binding", lambda: changed_profile)
            drift.setattr(research_continuation, "profile_binding", lambda: changed_profile)
            drift.setattr(continuation_request, "_LIMITS", changed_limits)
            with pytest.raises(ValueError, match="frozen approval request"):
                store.create_continuation_permission(task_id, payload, trusted_context=context,
                    expected_frozen_request=frozen_snapshot())
        assert store.get_continuation_permission(task_id, trusted_context=context)["permission"] is None

        # A validated artifact whose current content digest differs from the frozen
        # digest is likewise rejected before the permission ledger is updated.
        mismatched = frozen_snapshot()
        mismatched["confirmed_artifacts"] = [
            {**record["confirmed_artifacts"][0], "content_sha256": "e" * 64}
        ]
        with pytest.raises(ValueError, match="frozen approval request"):
            store.create_continuation_permission(task_id, payload, trusted_context=context,
                expected_frozen_request=mismatched)
        assert store.get_continuation_permission(task_id, trusted_context=context)["permission"] is None
    finally:
        store.close()


def test_continuation_decision_marks_config_drift_attention_without_grant(monkeypatch):
    from app import research_continuation
    from packages.contracts import continuation_request
    from tests.test_research_continuation import setup_permission

    store, task_id, context, grant_payload = setup_permission()
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    api = TestClient(main.app)
    try:
        created = api.post("/v1/product/research/approval-requests", headers=headers,
            json={"schema_version": "byq-product-approval-request.v1", "request_type": "continuation_consent",
                "request_key": "approval-config-drift-route", "task_id": task_id,
                "confirmed_artifact_ids": grant_payload["confirmed_artifact_ids"],
                "execution_profile_id": "task-ready-read.v1"})
        assert created.status_code == 201, created.text
        request_id = created.json()["request"]["request_id"]
        frozen = created.json()["request"]
        changed_profile = {**frozen["execution_profile"], "profile_sha256": "d" * 64}
        changed_limits = {**frozen["request_limits"], "deadline_ms": frozen["request_limits"]["deadline_ms"] - 1}
        with monkeypatch.context() as drift:
            drift.setattr(continuation_request, "profile_binding", lambda: changed_profile)
            drift.setattr(research_continuation, "profile_binding", lambda: changed_profile)
            drift.setattr(continuation_request, "_LIMITS", changed_limits)
            decided = api.post(f"/v1/product/research/approval-requests/{request_id}/decision", headers=headers,
                json={"schema_version": "byq-product-approval-decision.v1", "decision_key": "decision-config-drift-route",
                    "decision": "approved", "rationale": "Approve the frozen request."})
        assert decided.status_code == 200, decided.text
        assert decided.json()["request"]["status"] == "needs_attention"
        assert decided.json()["request"]["materialization_error_code"] == "domain_validation_failed"
        assert store.get_continuation_permission(task_id, trusted_context=context)["permission"] is None
    finally:
        store.close()


def test_product_routes_materialize_each_domain_fact_once_and_exact_get_does_not_replay(monkeypatch):
    from app.ml_strategy import normalize_ml_strategy
    from app.strategy_artifact import prepare_strategy, strategy_version_content
    from tests.test_ml_strategy import valid_strategy
    from tests.test_strategy_artifact import strategy_payload
    from tests.test_research_continuation import setup_permission

    store, task_id, context, grant_payload = setup_permission()
    headers = {"x-byq-" + key.replace("_", "-"): value for key, value in context.items()}
    api = TestClient(main.app)
    calls = {"continuation": 0, "strategy": 0, "ml": 0}
    uncertain_domain_keys = set()
    original_continuation = main.research_store.create_continuation_permission
    original_strategy = main.create_strategy_approval
    original_ml = main.create_ml_strategy_approval

    def continuation_once(*args, **kwargs):
        calls["continuation"] += 1
        return original_continuation(*args, **kwargs)

    def strategy_once(*args, **kwargs):
        calls["strategy"] += 1
        if args and args[0].get("idempotency_key") in uncertain_domain_keys:
            raise SQLAlchemyError("synthetic storage response uncertainty")
        return original_strategy(*args, **kwargs)

    def ml_once(*args, **kwargs):
        calls["ml"] += 1
        return original_ml(*args, **kwargs)

    monkeypatch.setattr(main.research_store, "create_continuation_permission", continuation_once)
    monkeypatch.setattr(main, "create_strategy_approval", strategy_once)
    monkeypatch.setattr(main, "create_ml_strategy_approval", ml_once)
    strategy = store.create_artifact({"task_id": task_id, "kind": "strategy_version",
        "content": strategy_version_content(prepare_strategy(strategy_payload())), "lineage": [],
        "trace_id": context["trace_id"], "idempotency_key": "approval-route-strategy"})
    strategy = store.transition("artifact", strategy["artifact_id"], "validated", "approval-route-strategy-valid")
    ml_strategy = store.create_artifact({"task_id": task_id, "kind": "ml_strategy_version",
        "content": normalize_ml_strategy(valid_strategy()), "lineage": [],
        "trace_id": context["trace_id"], "idempotency_key": "approval-route-ml"})
    ml_strategy = store.transition("artifact", ml_strategy["artifact_id"], "validated", "approval-route-ml-valid")

    requests = [
        {"request_type": "continuation_consent", "request_key": "approval-route-continuation",
         "task_id": task_id, "confirmed_artifact_ids": grant_payload["confirmed_artifact_ids"],
         "execution_profile_id": "task-ready-read.v1"},
        {"request_type": "strategy_version", "request_key": "approval-route-strategy-request",
         "task_id": task_id, "strategy_version_artifact_id": strategy["artifact_id"]},
        {"request_type": "ml_strategy_version", "request_key": "approval-route-ml-request",
         "task_id": task_id, "ml_strategy_artifact_id": ml_strategy["artifact_id"]},
    ]
    try:
        for request_body in requests:
            created = api.post("/v1/product/research/approval-requests", headers=headers,
                json={"schema_version": "byq-product-approval-request.v1", **request_body})
            assert created.status_code == 201, created.text
            envelope = created.json()
            request_id = envelope["request"]["request_id"]
            decided = api.post(f"/v1/product/research/approval-requests/{request_id}/decision", headers=headers,
                json={"schema_version": "byq-product-approval-decision.v1", "decision_key": f"decision-{request_body['request_key']}",
                      "decision": "approved", "rationale": "Approved the exact immutable resource."})
            assert decided.status_code == 200, decided.text
            assert decided.json()["request"]["status"] == "approved"
            readback = api.get(f"/v1/product/research/approval-requests/{request_id}", headers=headers)
            assert readback.status_code == 200 and readback.json()["request"]["status"] == "approved"
            result = readback.json()["request"]
            if request_body["request_type"] == "continuation_consent":
                assert result["permission"]["permission"]["confirmation_id"] == f"product-approval-{request_id}"
                fact = api.get(f"/v1/research/tasks/{task_id}/continuation-permission", headers=headers)
                assert fact.status_code == 200 and fact.json()["permission"]["confirmation_id"] == f"product-approval-{request_id}"
            else:
                domain = store.get_artifact(result["domain_artifact_id"])
                expected_kind = ("strategy_approval" if request_body["request_type"] == "strategy_version"
                                 else "ml_strategy_approval")
                expected_target_field = ("strategy_version_artifact_id" if expected_kind == "strategy_approval"
                                         else "ml_strategy_artifact_id")
                expected_target = request_body[expected_target_field]
                assert domain["kind"] == expected_kind and domain["status"] == "validated"
                assert domain["content"]["decision"] == "approved"
                assert domain["content"]["execution_authorized"] is True
                assert domain["content"][expected_target_field] == expected_target
            # An exact read and the explicit reconcile action only inspect the
            # already-materialized fact; neither may call the domain writer again.
            before_reconcile_calls = dict(calls)
            reconcile = api.post(f"/v1/product/research/approval-requests/{request_id}/reconcile",
                headers=headers)
            assert reconcile.status_code == 200 and reconcile.json()["request"]["status"] == "approved"
            assert calls == before_reconcile_calls
        assert calls == {"continuation": 1, "strategy": 1, "ml": 1}

        rejected_version = store.create_artifact({"task_id": task_id, "kind": "strategy_version",
            "content": strategy["content"], "lineage": [], "trace_id": context["trace_id"],
            "idempotency_key": "approval-route-strategy-rejected"})
        rejected_version = store.transition("artifact", rejected_version["artifact_id"], "validated",
            "approval-route-strategy-rejected-valid")
        rejected_request = api.post("/v1/product/research/approval-requests", headers=headers,
            json={"schema_version": "byq-product-approval-request.v1", "request_type": "strategy_version",
                "request_key": "approval-route-rejected-request", "task_id": task_id,
                "strategy_version_artifact_id": rejected_version["artifact_id"]})
        assert rejected_request.status_code == 201, rejected_request.text
        rejected_id = rejected_request.json()["request"]["request_id"]
        rejected_decision = api.post(f"/v1/product/research/approval-requests/{rejected_id}/decision", headers=headers,
            json={"schema_version": "byq-product-approval-decision.v1", "decision_key": "decision-rejected-request",
                  "decision": "rejected", "rationale": "The exact strategy version does not meet review criteria."})
        assert rejected_decision.status_code == 200
        assert rejected_decision.json()["request"]["status"] == "rejected"
        rejection_fact = store.get_artifact(rejected_decision.json()["request"]["domain_artifact_id"])
        assert rejection_fact["kind"] == "strategy_approval" and rejection_fact["status"] == "validated"
        assert rejection_fact["content"]["decision"] == "rejected"
        assert rejection_fact["content"]["execution_authorized"] is False

        rejected_ml_version = store.create_artifact({"task_id": task_id, "kind": "ml_strategy_version",
            "content": normalize_ml_strategy(valid_strategy()), "lineage": [], "trace_id": context["trace_id"],
            "idempotency_key": "approval-route-ml-rejected"})
        rejected_ml_version = store.transition("artifact", rejected_ml_version["artifact_id"], "validated",
            "approval-route-ml-rejected-valid")
        rejected_ml_request = api.post("/v1/product/research/approval-requests", headers=headers,
            json={"schema_version": "byq-product-approval-request.v1", "request_type": "ml_strategy_version",
                "request_key": "approval-route-ml-rejected-request", "task_id": task_id,
                "ml_strategy_artifact_id": rejected_ml_version["artifact_id"]})
        assert rejected_ml_request.status_code == 201, rejected_ml_request.text
        rejected_ml_id = rejected_ml_request.json()["request"]["request_id"]
        rejected_ml_decision = api.post(f"/v1/product/research/approval-requests/{rejected_ml_id}/decision",
            headers=headers, json={"schema_version": "byq-product-approval-decision.v1",
                "decision_key": "decision-ml-rejected-request", "decision": "rejected",
                "rationale": "The exact ML strategy version does not meet review criteria."})
        assert rejected_ml_decision.status_code == 200, rejected_ml_decision.text
        assert rejected_ml_decision.json()["request"]["status"] == "rejected"
        rejected_ml_fact = store.get_artifact(rejected_ml_decision.json()["request"]["domain_artifact_id"])
        assert rejected_ml_fact["kind"] == "ml_strategy_approval" and rejected_ml_fact["status"] == "validated"
        assert rejected_ml_fact["content"]["decision"] == "rejected"
        assert rejected_ml_fact["content"]["execution_authorized"] is False
        assert rejected_ml_fact["content"]["ml_strategy_artifact_id"] == rejected_ml_version["artifact_id"]

        interrupted_version = store.create_artifact({"task_id": task_id, "kind": "strategy_version",
            "content": strategy["content"], "lineage": [], "trace_id": context["trace_id"],
            "idempotency_key": "approval-route-strategy-interrupted"})
        interrupted_version = store.transition("artifact", interrupted_version["artifact_id"], "validated",
            "approval-route-strategy-interrupted-valid")
        interrupted = api.post("/v1/product/research/approval-requests", headers=headers,
            json={"schema_version": "byq-product-approval-request.v1", "request_type": "strategy_version",
                "request_key": "approval-route-interrupted-request", "task_id": task_id,
                "strategy_version_artifact_id": interrupted_version["artifact_id"]})
        assert interrupted.status_code == 201, interrupted.text
        interrupted_id = interrupted.json()["request"]["request_id"]
        original_transition = main.research_store.transition

        def fail_approval_validation(entity_type, identity, target_status, *args, **kwargs):
            artifact = main.research_store.get_artifact(identity) if entity_type == "artifact" else None
            if artifact and artifact["kind"] == "strategy_approval" and target_status == "validated":
                raise ValueError("synthetic interruption after draft commit")
            return original_transition(entity_type, identity, target_status, *args, **kwargs)

        monkeypatch.setattr(main.research_store, "transition", fail_approval_validation)
        partial = api.post(f"/v1/product/research/approval-requests/{interrupted_id}/decision", headers=headers,
            json={"schema_version": "byq-product-approval-decision.v1", "decision_key": "decision-interrupted-request",
                  "decision": "approved", "rationale": "Approved exact version; validation interrupted."})
        assert partial.status_code == 200 and partial.json()["request"]["status"] == "needs_attention"
        assert partial.json()["request"]["materialization_error_code"] == "domain_validation_failed"
        request_row = main.research_store.get_product_approval_request(interrupted_id,
            owner=context["owner_principal"], workspace=context["workspace_id"])["request"]
        version_before_get = main.research_store._fetch_one(
            "SELECT version FROM product_approval_requests WHERE request_id=:id", {"id": interrupted_id})["version"]
        exact = api.get(f"/v1/product/research/approval-requests/{interrupted_id}", headers=headers)
        assert exact.status_code == 200 and exact.json()["request"]["status"] == "needs_attention"
        assert exact.json()["request"]["observed_state"] == "draft"
        version_after_get = main.research_store._fetch_one(
            "SELECT version FROM product_approval_requests WHERE request_id=:id", {"id": interrupted_id})["version"]
        assert version_after_get == version_before_get
        assert request_row["status"] == "needs_attention"
        assert "observed_state" not in request_row
        reconciled = api.post(f"/v1/product/research/approval-requests/{interrupted_id}/reconcile",
            headers=headers)
        assert reconciled.status_code == 200 and reconciled.json()["request"]["status"] == "needs_attention"
        assert reconciled.json()["request"]["observed_state"] == "draft"

        uncertain_version = store.create_artifact({"task_id": task_id, "kind": "strategy_version",
            "content": strategy["content"], "lineage": [], "trace_id": context["trace_id"],
            "idempotency_key": "approval-route-strategy-uncertain"})
        uncertain_version = store.transition("artifact", uncertain_version["artifact_id"], "validated",
            "approval-route-strategy-uncertain-valid")
        uncertain = api.post("/v1/product/research/approval-requests", headers=headers,
            json={"schema_version": "byq-product-approval-request.v1", "request_type": "strategy_version",
                "request_key": "approval-route-uncertain-request", "task_id": task_id,
                "strategy_version_artifact_id": uncertain_version["artifact_id"]})
        assert uncertain.status_code == 201, uncertain.text
        uncertain_id = uncertain.json()["request"]["request_id"]
        uncertain_domain_keys.add(f"product-approval-{uncertain_id}")
        unknown = api.post(f"/v1/product/research/approval-requests/{uncertain_id}/decision", headers=headers,
            json={"schema_version": "byq-product-approval-decision.v1", "decision_key": "decision-uncertain-request",
                  "decision": "approved", "rationale": "Approved the exact resource; response was lost."})
        assert unknown.status_code == 200 and unknown.json()["request"]["status"] == "outcome_unknown"
        unknown_replay = api.post(f"/v1/product/research/approval-requests/{uncertain_id}/decision", headers=headers,
            json={"schema_version": "byq-product-approval-decision.v1", "decision_key": "decision-uncertain-request",
                  "decision": "approved", "rationale": "Approved the exact resource; response was lost."})
        assert unknown_replay.status_code == 200 and unknown_replay.json()["request"]["status"] == "outcome_unknown"
        conflicting = api.post(f"/v1/product/research/approval-requests/{uncertain_id}/decision", headers=headers,
            json={"schema_version": "byq-product-approval-decision.v1", "decision_key": "different-uncertain-decision",
                  "decision": "rejected", "rationale": "Conflicting decision must not replace the original."})
        assert conflicting.status_code == 409
        assert calls == {"continuation": 1, "strategy": 4, "ml": 2}
        unknown_version = main.research_store._fetch_one(
            "SELECT version FROM product_approval_requests WHERE request_id=:id", {"id": uncertain_id})["version"]
        unknown_read = api.get(f"/v1/product/research/approval-requests/{uncertain_id}", headers=headers)
        assert unknown_read.status_code == 200
        assert unknown_read.json()["request"]["status"] == "outcome_unknown"
        assert unknown_read.json()["request"]["observed_state"] == "missing"
        assert main.research_store._fetch_one(
            "SELECT version FROM product_approval_requests WHERE request_id=:id", {"id": uncertain_id})["version"] == unknown_version
        unknown_reconciled = api.post(f"/v1/product/research/approval-requests/{uncertain_id}/reconcile",
            headers=headers)
        assert unknown_reconciled.status_code == 200
        assert unknown_reconciled.json()["request"]["status"] == "needs_attention"
        assert unknown_reconciled.json()["request"]["materialization_error_code"] == "domain_fact_missing"
        assert unknown_reconciled.json()["request"]["observed_state"] == "missing"
        assert calls == {"continuation": 1, "strategy": 4, "ml": 2}
    finally:
        api.close()
        store.close()
