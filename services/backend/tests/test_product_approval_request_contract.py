"""Pure contract checks for the closed, typed Product approval requests."""

import pytest

from app.product_approval_requests import normalize_request
from packages.contracts.product_approval_requests import (
    DECISION_SCHEMA,
    REQUEST_SCHEMA,
    validate_decision_shape,
    validate_request_shape,
)


TASK = "task_" + "a" * 32
ARTIFACT = "artifact_" + "b" * 32


@pytest.mark.parametrize(("kind", "field"), [
    ("strategy_version", "strategy_version_artifact_id"),
    ("ml_strategy_version", "ml_strategy_artifact_id"),
])
def test_strategy_approval_request_types_are_closed_and_resource_specific(kind, field):
    value = {"schema_version": REQUEST_SCHEMA, "request_type": kind,
             "request_key": "stable-request-key", "task_id": TASK, field: ARTIFACT}
    assert validate_request_shape(value) == value
    assert normalize_request(value)[0:3] == (kind, TASK, "stable-request-key")
    with pytest.raises(ValueError):
        validate_request_shape({**value, "owner_principal": "client-controlled"})


def test_continuation_request_is_bound_to_the_one_validated_profile():
    value = {"schema_version": REQUEST_SCHEMA, "request_type": "continuation_consent",
             "request_key": "stable-request-key", "task_id": TASK,
             "confirmed_artifact_ids": [ARTIFACT], "execution_profile_id": "task-ready-read.v1"}
    kind, task, key, artifacts, body, _ = normalize_request(value)
    assert (kind, task, key, artifacts) == ("continuation_consent", TASK, "stable-request-key", [ARTIFACT])
    assert body["max_turns"] == 1
    assert body["execution_profile"]["profile_id"] == "task-ready-read.v1"
    assert body["request_limits"]
    with pytest.raises(ValueError):
        validate_request_shape({**value, "max_turns": 10})


def test_decision_contract_requires_stable_key_and_closed_decision_shape():
    value = {"schema_version": DECISION_SCHEMA, "decision_key": "stable-decision-key",
             "decision": "approved", "rationale": "Reviewed the exact resource."}
    assert validate_decision_shape(value) == value
    with pytest.raises(ValueError):
        validate_decision_shape({**value, "idempotency_key": "rotate-me"})
    with pytest.raises(ValueError):
        validate_decision_shape({**value, "decision": "maybe"})


def test_unknown_draft_reconciliation_reads_exact_fact_without_replaying_domain_write(monkeypatch):
    from app import main

    class Store:
        def __init__(self):
            self.finished = []

        def get_product_approval_domain_artifact(self, request_id, *, owner, workspace):
            assert request_id == "approval_request_" + "c" * 32
            assert (owner, workspace) == ("owner", "workspace")
            return {"artifact_id": "artifact_" + "d" * 32, "kind": "strategy_approval", "status": "draft",
                    "content": {"strategy_version_artifact_id": ARTIFACT, "decision": "approved",
                                "execution_authorized": True}}

        def get_artifact(self, artifact_id):
            assert artifact_id == ARTIFACT
            return {"status": "validated", "owner_principal": "owner", "workspace_id": "workspace",
                    "content_sha256": "e" * 64}

        def finish_product_approval_decision(self, request_id, *, owner, workspace, status,
                                             domain_artifact_id=None, permission=None,
                                             materialization_error_code=None):
            self.finished.append((status, domain_artifact_id, materialization_error_code))
            return {"schema_version": "byq-product-approval-request.v1", "request": {
                "request_id": request_id, "status": status,
                "materialization_error_code": materialization_error_code}}

    store = Store()
    monkeypatch.setattr(main, "research_store", store)
    result = main._settle_product_approval_reconciliation({
        "schema_version": "byq-product-approval-request.v1",
        "request": {"request_id": "approval_request_" + "c" * 32, "request_type": "strategy_version",
            "status": "outcome_unknown", "decision": "approved", "decision_by": "owner",
            "rationale": "approved", "resource_artifact_id": ARTIFACT, "content_sha256": "e" * 64,
            "strategy_version_artifact_id": ARTIFACT},
    }, {"owner_principal": "owner", "workspace_id": "workspace"})
    assert result["request"]["status"] == "needs_attention"
    assert result["request"]["observed_state"] == "draft"
    assert store.finished == [("needs_attention", None, "domain_fact_draft")]
