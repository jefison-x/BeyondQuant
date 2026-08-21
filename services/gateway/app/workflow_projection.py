"""Gateway-owned WorkflowTrace validation and owner-scoped card hydration."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from typing import Any

from .contracts import (
    WORKFLOW_CARD_VERSION,
    WorkflowTraceEvent,
    validate_workflow_trace_event,
)


BackendGet = Callable[[str], dict[str, object]]
RevisionFor = Callable[[str], int]
_DOMAIN_KINDS = frozenset({"agent.card.backtest_context", "agent.card.approval"})
_METRICS = frozenset(
    {
        "total_return",
        "max_drawdown",
        "sharpe_ratio",
        "volatility",
        "win_rate",
        "trade_count",
        "blocked_trade_count",
    }
)


def project_workflow_event(
    event: object,
    *,
    backend_get: BackendGet,
    revision_for: RevisionFor,
) -> WorkflowTraceEvent:
    """Return one browser-safe event at the original sequence position."""

    if not isinstance(event, dict):
        raise ValueError("workflow trace candidate must be an object")
    kind = event.get("kind")
    try:
        if kind in _DOMAIN_KINDS:
            projected = _hydrate_domain_card(event, backend_get=backend_get, revision_for=revision_for)
            return validate_workflow_trace_event(projected)
        return validate_workflow_trace_event(event)
    except (KeyError, TypeError, ValueError, RuntimeError):
        return validate_workflow_trace_event(_degraded(event))


def _hydrate_domain_card(
    event: dict[str, Any],
    *,
    backend_get: BackendGet,
    revision_for: RevisionFor,
) -> WorkflowTraceEvent:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("domain card reference must be an object")
    kind = event["kind"]
    if kind == "agent.card.backtest_context":
        resource_id = _identifier(payload.get("job_id"))
        body = backend_get(f"/v1/research/backtests/{resource_id}")
        resource = body.get("job")
        card_payload = _backtest_payload(resource_id, resource)
    else:
        resource_id = _identifier(payload.get("approval_id"))
        body = backend_get(f"/v1/agents/approvals/{resource_id}")
        resource = body.get("approval")
        card_payload = _approval_payload(resource_id, resource)
    card_id = _stable_card_id(str(event["trace_id"]), str(kind), resource_id)
    card_payload.update(
        {
            "schema_version": WORKFLOW_CARD_VERSION,
            "card_id": card_id,
            "revision": revision_for(card_id),
            "authority": "domain",
            "truncated": False,
        }
    )
    return {**event, "source": "byq-domain", "payload": card_payload}


def _backtest_payload(resource_id: str, resource: object) -> dict[str, Any]:
    if not isinstance(resource, dict) or resource.get("job_id") != resource_id:
        raise ValueError("owner-scoped backtest hydration returned the wrong resource")
    status = resource.get("status")
    if status not in {"queued", "running", "completed", "failed", "cancelled"}:
        raise ValueError("backtest status is invalid")
    payload: dict[str, Any] = {
        "title": f"回测任务 {resource_id[-8:]}",
        "job_id": resource_id,
        "status": status,
    }
    strategy_id = resource.get("strategy_version_artifact_id")
    result_id = resource.get("result_artifact_id")
    if isinstance(strategy_id, str):
        payload["strategy_artifact_id"] = strategy_id
    if isinstance(result_id, str):
        payload["result_artifact_id"] = result_id
    metrics = _safe_metrics(resource.get("summary"))
    if metrics:
        payload["metrics"] = metrics
    return payload


def _approval_payload(resource_id: str, resource: object) -> dict[str, Any]:
    if not isinstance(resource, dict) or resource.get("approval_id") != resource_id:
        raise ValueError("owner-scoped approval hydration returned the wrong resource")
    action = resource.get("action")
    status = resource.get("status")
    outcome = resource.get("execution_outcome")
    if not isinstance(action, str) or status not in {"pending", "approved", "rejected"}:
        raise ValueError("approval projection is invalid")
    if outcome not in {"not_started", "authorized", "not_authorized"}:
        raise ValueError("approval outcome is invalid")
    payload: dict[str, Any] = {
        "title": "等待审批" if status == "pending" else "审批结果",
        "approval_id": resource_id,
        "action": action,
        "status": status,
        "execution_outcome": outcome,
    }
    reviewer = resource.get("decision_by")
    if isinstance(reviewer, str) and reviewer.strip():
        payload["decided_by_display"] = reviewer[:160]
    return payload


def _safe_metrics(value: object) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    metrics: dict[str, int | float] = {}
    for key in _METRICS:
        candidate = value.get(key)
        if key in {"trade_count", "blocked_trade_count"}:
            if not isinstance(candidate, bool) and isinstance(candidate, int) and candidate >= 0:
                metrics[key] = candidate
        elif (
            not isinstance(candidate, bool)
            and isinstance(candidate, (int, float))
            and math.isfinite(candidate)
        ):
            metrics[key] = candidate
    return metrics


def _degraded(event: dict[str, Any]) -> WorkflowTraceEvent:
    required = ("trace_id", "session_id", "sequence", "timestamp")
    if any(field not in event for field in required):
        raise ValueError("invalid envelope cannot preserve its sequence")
    return {
        "trace_id": event["trace_id"],
        "session_id": event["session_id"],
        "sequence": event["sequence"],
        "timestamp": event["timestamp"],
        "kind": "session.progress",
        "source": "runtime-adapter",
        "payload": {"reason": "projection-rejected", "truncated": False},
    }


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError("domain reference identifier is invalid")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in value):
        raise ValueError("domain reference identifier is invalid")
    return value


def _stable_card_id(trace_id: str, kind: str, resource_id: str) -> str:
    digest = hashlib.sha256(f"{trace_id}\x1f{kind}\x1f{resource_id}".encode()).hexdigest()
    return f"card_{digest}"
