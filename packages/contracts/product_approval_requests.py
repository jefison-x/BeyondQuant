"""Closed Product approval-request wire contracts; no generic workflow engine."""
from __future__ import annotations

import re
from typing import Literal, TypedDict, Union

REQUEST_SCHEMA = "byq-product-approval-request.v1"
LIST_SCHEMA = "byq-product-approval-request-list.v1"
DECISION_SCHEMA = "byq-product-approval-decision.v1"
REQUEST_TYPES = frozenset({"continuation_consent", "strategy_version", "ml_strategy_version"})
REQUEST_STATUSES = frozenset({"pending", "decision_recorded", "approved", "rejected", "outcome_unknown", "needs_attention"})
REQUEST_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
TASK_ID = re.compile(r"^task_[0-9a-f]{32}$")
ARTIFACT_ID = re.compile(r"^artifact_[0-9a-f]{32}$")


class ContinuationConsentRequest(TypedDict):
    schema_version: Literal["byq-product-approval-request.v1"]
    request_type: Literal["continuation_consent"]
    request_key: str
    task_id: str
    confirmed_artifact_ids: list[str]
    execution_profile_id: Literal["task-ready-read.v1"]


class StrategyVersionApprovalRequest(TypedDict):
    schema_version: Literal["byq-product-approval-request.v1"]
    request_type: Literal["strategy_version"]
    request_key: str
    task_id: str
    strategy_version_artifact_id: str


class MLStrategyVersionApprovalRequest(TypedDict):
    schema_version: Literal["byq-product-approval-request.v1"]
    request_type: Literal["ml_strategy_version"]
    request_key: str
    task_id: str
    ml_strategy_artifact_id: str


ProductApprovalRequest = Union[
    ContinuationConsentRequest, StrategyVersionApprovalRequest, MLStrategyVersionApprovalRequest,
]


class ProductApprovalDecision(TypedDict):
    schema_version: Literal["byq-product-approval-decision.v1"]
    decision_key: str
    decision: Literal["approved", "rejected"]
    rationale: str


class ProductApprovalRequestItem(TypedDict, total=False):
    request_id: str
    request_type: Literal["continuation_consent", "strategy_version", "ml_strategy_version"]
    status: Literal["pending", "decision_recorded", "approved", "rejected", "outcome_unknown", "needs_attention"]
    owner_principal: str
    workspace_id: str
    task_id: str
    resource_artifact_id: str | None
    content_sha256: str
    request_key: str
    created_at: str
    updated_at: str
    decision: Literal["approved", "rejected"]
    decision_key: str
    decision_by: str
    decision_at: str
    rationale: str
    domain_artifact_id: str
    permission: dict
    materialization_error_code: str
    observed_state: str


class ProductApprovalRequestEnvelope(TypedDict):
    schema_version: Literal["byq-product-approval-request.v1"]
    request: ProductApprovalRequestItem


class ProductApprovalRequestList(TypedDict):
    schema_version: Literal["byq-product-approval-request-list.v1"]
    requests: list[ProductApprovalRequestItem]
    total: int
    pending_count: int
    attention_count: int
    limit: int
    offset: int


def validate_request_shape(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("approval request schema is invalid")
    kind = value.get("request_type")
    if kind not in REQUEST_TYPES:
        raise ValueError("approval request type is unsupported")
    key = value.get("request_key")
    task = value.get("task_id")
    if not isinstance(key, str) or REQUEST_KEY.fullmatch(key) is None:
        raise ValueError("request_key is invalid")
    if not isinstance(task, str) or TASK_ID.fullmatch(task) is None:
        raise ValueError("task_id is invalid")
    if kind == "continuation_consent":
        expected = {"schema_version", "request_type", "request_key", "task_id",
                    "confirmed_artifact_ids", "execution_profile_id"}
        if set(value) != expected or value.get("execution_profile_id") != "task-ready-read.v1":
            raise ValueError("continuation consent request fields are invalid")
        artifacts = value.get("confirmed_artifact_ids")
        if (not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 16
                or any(not isinstance(item, str) or ARTIFACT_ID.fullmatch(item) is None for item in artifacts)
                or len(set(artifacts)) != len(artifacts)):
            raise ValueError("confirmed_artifact_ids is invalid")
    else:
        field = "strategy_version_artifact_id" if kind == "strategy_version" else "ml_strategy_artifact_id"
        if set(value) != {"schema_version", "request_type", "request_key", "task_id", field}:
            raise ValueError("strategy approval request fields are invalid")
        if not isinstance(value.get(field), str) or ARTIFACT_ID.fullmatch(value[field]) is None:
            raise ValueError(f"{field} is invalid")
    return dict(value)


def validate_decision_shape(value: object) -> dict:
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "decision_key", "decision", "rationale"}
            or value.get("schema_version") != DECISION_SCHEMA
            or value.get("decision") not in {"approved", "rejected"}
            or not isinstance(value.get("decision_key"), str)
            or REQUEST_KEY.fullmatch(value["decision_key"]) is None
            or not isinstance(value.get("rationale"), str) or len(value["rationale"]) > 2000):
        raise ValueError("approval decision fields are invalid")
    return dict(value)
