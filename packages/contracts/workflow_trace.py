"""BYQ-owned WorkflowTrace envelope and structured projection validation."""

from __future__ import annotations

import math
import re
from datetime import datetime
from json import dumps
from typing import Any, Literal, TypedDict, cast


WORKFLOW_CARD_VERSION = "workflow-card.v1"
WORKFLOW_ANSWER_VERSION = "workflow-answer.v1"
WORKFLOW_ACTIVITY_VERSION = "workflow-activity.v1"
MAX_EVENT_PAYLOAD_BYTES = 65_536
MAX_ANSWER_FRAGMENT_BYTES = 8_192
MAX_CARDS_PER_TURN = 32
MAX_ACTIVITIES_PER_TURN = 256

WorkflowSource = Literal["dsh", "runtime-adapter", "byq-domain"]


class WorkflowTraceEvent(TypedDict):
    trace_id: str
    session_id: str
    sequence: int
    timestamp: str
    kind: str
    source: WorkflowSource
    payload: dict[str, Any]


CARD_KINDS = frozenset(
    {
        "agent.card.strategy_draft",
        "agent.card.stock_candidates",
        "agent.card.optimization",
        "agent.card.backtest_context",
        "agent.card.approval",
    }
)
_COMMON_CARD_FIELDS = {
    "schema_version",
    "card_id",
    "revision",
    "authority",
    "title",
    "summary",
    "truncated",
}
_CARD_ID = re.compile(r"card_[0-9a-f]{32,64}")
_ACTIVITY_ID = re.compile(r"activity_[0-9a-f]{32,64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,160}")
_SYMBOL = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)")
_DATE = re.compile(r"[0-9]{8}")
_SECRET_FRAGMENTS = (
    "authorization",
    "credential",
    "password",
    "privatekey",
    "secret",
    "token",
)


def make_workflow_trace_event(
    *,
    trace_id: str,
    session_id: str,
    sequence: int,
    kind: str,
    source: WorkflowSource,
    payload: dict[str, Any],
) -> WorkflowTraceEvent:
    return {
        "trace_id": trace_id,
        "session_id": session_id,
        "sequence": sequence,
        "timestamp": datetime.now().astimezone().isoformat(),
        "kind": kind,
        "source": source,
        "payload": payload,
    }


def validate_workflow_trace_event(event: object) -> WorkflowTraceEvent:
    """Validate one browser-safe BYQ event before persistence or streaming."""

    if not isinstance(event, dict):
        raise ValueError("workflow trace event must be an object")
    required = {"trace_id", "session_id", "sequence", "timestamp", "kind", "source", "payload"}
    if set(event) != required:
        raise ValueError("workflow trace event has an invalid field set")
    for field in ("trace_id", "session_id", "timestamp", "kind"):
        _text(event[field], field=field, minimum=1, maximum=256)
    if not _integer(event["sequence"], minimum=1, maximum=2_147_483_647):
        raise ValueError("workflow trace sequence must be a positive integer")
    if event["source"] not in {"dsh", "runtime-adapter", "byq-domain"}:
        raise ValueError("workflow trace source is not supported")
    payload = event["payload"]
    if not isinstance(payload, dict):
        raise ValueError("workflow trace payload must be an object")
    serialized = _serialize_payload(payload)
    if len(serialized.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
        raise ValueError("workflow trace payload exceeds the byte limit")

    kind = cast(str, event["kind"])
    source = cast(WorkflowSource, event["source"])
    if kind in CARD_KINDS:
        _validate_card(kind, source, payload)
    elif kind == "agent.output.delta":
        _validate_answer(payload)
    elif kind == "agent.activity":
        _validate_activity(payload)
    elif source == "byq-domain":
        raise ValueError("byq-domain source is reserved for hydrated cards")
    return cast(WorkflowTraceEvent, event)


def _validate_card(kind: str, source: WorkflowSource, payload: dict[str, Any]) -> None:
    fields_by_kind = {
        "agent.card.strategy_draft": {
            "name", "artifact_id", "strategy_id", "validation_status",
        },
        "agent.card.stock_candidates": {"items", "as_of", "pool_id"},
        "agent.card.optimization": {
            "objective", "changes", "strategy_artifact_id", "baseline_job_id", "metrics",
        },
        "agent.card.backtest_context": {
            "job_id", "status", "metrics", "strategy_artifact_id", "result_artifact_id",
        },
        "agent.card.approval": {
            "approval_id", "action", "status", "execution_outcome", "risk_level",
            "decided_by_display",
        },
    }
    allowed = _COMMON_CARD_FIELDS | fields_by_kind[kind]
    _exact_fields(payload, required=_COMMON_CARD_FIELDS - {"summary"}, allowed=allowed)
    if payload["schema_version"] != WORKFLOW_CARD_VERSION:
        raise ValueError("workflow card schema_version is not supported")
    if not isinstance(payload["card_id"], str) or _CARD_ID.fullmatch(payload["card_id"]) is None:
        raise ValueError("workflow card_id is invalid")
    if not _integer(payload["revision"], minimum=1, maximum=2_147_483_647):
        raise ValueError("workflow card revision is invalid")
    authority = payload["authority"]
    if authority not in {"proposal", "domain"}:
        raise ValueError("workflow card authority is invalid")
    if authority == "domain" and source != "byq-domain":
        raise ValueError("domain cards require byq-domain source")
    if authority == "proposal" and source != "runtime-adapter":
        raise ValueError("proposal cards require runtime-adapter source")
    _text(payload["title"], field="title", minimum=1, maximum=160)
    _optional_text(payload, "summary", maximum=2_000)
    if not isinstance(payload["truncated"], bool):
        raise ValueError("workflow card truncated must be a boolean")

    if kind == "agent.card.strategy_draft":
        _validate_strategy_card(payload)
    elif kind == "agent.card.stock_candidates":
        _validate_stock_card(payload)
    elif kind == "agent.card.optimization":
        _validate_optimization_card(payload)
    elif kind == "agent.card.backtest_context":
        _validate_backtest_card(source, payload)
    else:
        _validate_approval_card(source, payload)


def _validate_strategy_card(payload: dict[str, Any]) -> None:
    _text(payload.get("name"), field="name", minimum=1, maximum=160)
    _text(payload.get("summary"), field="summary", minimum=1, maximum=2_000)
    _optional_identifier(payload, "artifact_id")
    _optional_text(payload, "strategy_id", maximum=128)
    status = payload.get("validation_status")
    if status is not None and status not in {"unknown", "draft", "valid", "invalid", "superseded"}:
        raise ValueError("strategy card validation_status is invalid")
    if payload["authority"] == "proposal" and status not in {None, "unknown", "draft"}:
        raise ValueError("proposal strategy card cannot claim validation")


def _validate_stock_card(payload: dict[str, Any]) -> None:
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("stock candidates must contain 1 to 50 items")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("stock candidate must be an object")
        _exact_fields(item, required={"symbol"}, allowed={"symbol", "name", "reason"})
        symbol = item["symbol"]
        if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None or symbol in seen:
            raise ValueError("stock candidate symbol is invalid or duplicated")
        seen.add(symbol)
        _optional_text(item, "name", maximum=80)
        _optional_text(item, "reason", maximum=500)
    as_of = payload.get("as_of")
    if as_of is not None and (not isinstance(as_of, str) or _DATE.fullmatch(as_of) is None):
        raise ValueError("stock candidates as_of is invalid")
    _optional_identifier(payload, "pool_id")


def _validate_optimization_card(payload: dict[str, Any]) -> None:
    _text(payload.get("objective"), field="objective", minimum=1, maximum=1_000)
    changes = payload.get("changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 20:
        raise ValueError("optimization changes must contain 1 to 20 items")
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("optimization change must be an object")
        _exact_fields(change, required={"area", "after", "reason"}, allowed={"area", "before", "after", "reason"})
        _text(change["area"], field="area", minimum=1, maximum=80)
        _optional_text(change, "before", maximum=500, allow_empty=True)
        _text(change["after"], field="after", minimum=1, maximum=500)
        _text(change["reason"], field="reason", minimum=1, maximum=500)
    _optional_identifier(payload, "strategy_artifact_id")
    _optional_identifier(payload, "baseline_job_id")
    _optional_metrics(payload, {"total_return", "max_drawdown", "sharpe_ratio", "volatility", "win_rate"})


def _validate_backtest_card(source: WorkflowSource, payload: dict[str, Any]) -> None:
    if payload["authority"] != "domain" or source != "byq-domain":
        raise ValueError("backtest cards require owner-scoped domain hydration")
    _identifier(payload.get("job_id"), field="job_id")
    if payload.get("status") not in {"queued", "running", "completed", "failed", "cancelled"}:
        raise ValueError("backtest card status is invalid")
    _optional_identifier(payload, "strategy_artifact_id")
    _optional_identifier(payload, "result_artifact_id")
    _optional_metrics(
        payload,
        {"total_return", "max_drawdown", "sharpe_ratio", "volatility", "win_rate"},
        integer_keys={"trade_count", "blocked_trade_count"},
    )


def _validate_approval_card(source: WorkflowSource, payload: dict[str, Any]) -> None:
    if payload["authority"] != "domain" or source != "byq-domain":
        raise ValueError("approval cards require owner-scoped domain hydration")
    _identifier(payload.get("approval_id"), field="approval_id")
    _text(payload.get("action"), field="action", minimum=1, maximum=128)
    if payload.get("status") not in {"pending", "approved", "rejected"}:
        raise ValueError("approval card status is invalid")
    if payload.get("execution_outcome") not in {"not_started", "authorized", "not_authorized"}:
        raise ValueError("approval card execution_outcome is invalid")
    risk = payload.get("risk_level")
    if risk is not None and risk not in {"low", "medium", "high", "critical"}:
        raise ValueError("approval card risk_level is invalid")
    _optional_text(payload, "decided_by_display", maximum=160)


def _validate_answer(payload: dict[str, Any]) -> None:
    _exact_fields(payload, required={"schema_version", "channel", "delta", "truncated"})
    if payload["schema_version"] != WORKFLOW_ANSWER_VERSION or payload["channel"] != "answer":
        raise ValueError("workflow answer schema is invalid")
    delta = _text(payload["delta"], field="delta", minimum=1, maximum=8_192)
    if len(delta.encode("utf-8")) > MAX_ANSWER_FRAGMENT_BYTES:
        raise ValueError("workflow answer fragment exceeds the byte limit")
    if not isinstance(payload["truncated"], bool):
        raise ValueError("workflow answer truncated must be a boolean")


def _validate_activity(payload: dict[str, Any]) -> None:
    _exact_fields(
        payload,
        required={"schema_version", "activity_id", "phase", "state", "label"},
        allowed={
            "schema_version", "activity_id", "phase", "state", "label", "capability",
            "agent_label", "plugin_label", "skill_label",
        },
    )
    if payload["schema_version"] != WORKFLOW_ACTIVITY_VERSION:
        raise ValueError("workflow activity schema_version is invalid")
    if not isinstance(payload["activity_id"], str) or _ACTIVITY_ID.fullmatch(payload["activity_id"]) is None:
        raise ValueError("workflow activity_id is invalid")
    if payload["phase"] not in {"understand", "select", "strategy", "backtest", "review", "tool"}:
        raise ValueError("workflow activity phase is invalid")
    if payload["state"] not in {"started", "progress", "completed", "failed", "waiting_approval"}:
        raise ValueError("workflow activity state is invalid")
    _text(payload["label"], field="label", minimum=1, maximum=240)
    _optional_text(payload, "capability", maximum=128)
    _optional_text(payload, "agent_label", maximum=80)
    _optional_text(payload, "plugin_label", maximum=80)
    _optional_text(payload, "skill_label", maximum=80)


def _optional_metrics(
    payload: dict[str, Any],
    numeric_keys: set[str],
    *,
    integer_keys: set[str] | None = None,
) -> None:
    metrics = payload.get("metrics")
    if metrics is None:
        return
    if not isinstance(metrics, dict):
        raise ValueError("workflow card metrics must be an object")
    integers = integer_keys or set()
    allowed = numeric_keys | integers
    if not set(metrics) <= allowed:
        raise ValueError("workflow card metrics contain unsupported fields")
    for key, value in metrics.items():
        if key in integers:
            if not _integer(value, minimum=0, maximum=2_147_483_647):
                raise ValueError("workflow card integer metric is invalid")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("workflow card numeric metric must be finite")


def _serialize_payload(payload: dict[str, Any]) -> str:
    _reject_secret_keys(payload)
    try:
        return dumps(payload, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("workflow trace payload must be finite JSON") from exc


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_FRAGMENTS):
                raise ValueError("workflow trace payload contains a credential-shaped field")
            _reject_secret_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested)


def _exact_fields(value: dict[str, Any], *, required: set[str], allowed: set[str] | None = None) -> None:
    permitted = allowed or required
    if not required <= set(value) or not set(value) <= permitted:
        raise ValueError("workflow projection has an invalid field set")


def _text(value: object, *, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"workflow {field} must be text")
    normalized = value.strip()
    if not minimum <= len(normalized) <= maximum:
        raise ValueError(f"workflow {field} has an invalid length")
    return normalized


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"workflow {field} is invalid")
    return value


def _optional_identifier(payload: dict[str, Any], field: str) -> None:
    value = payload.get(field)
    if value is not None:
        _identifier(value, field=field)


def _optional_text(
    payload: dict[str, Any],
    field: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> None:
    value = payload.get(field)
    if value is not None:
        _text(value, field=field, minimum=0 if allow_empty else 1, maximum=maximum)


def _integer(value: object, *, minimum: int, maximum: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and minimum <= value <= maximum
