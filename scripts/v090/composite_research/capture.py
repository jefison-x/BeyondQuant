#!/usr/bin/env python3
"""Capture-layer helpers for the 0.9 composite research fault regression.

These pure functions turn raw transport/domain observations into receipts and
assertions. They NEVER default to success: a missing response, a non-2xx status,
an empty body or a missing canonical identity all yield ``(None, reason)``.

``legacy_*`` variants reproduce the pre-fix "trust the result" behaviour and are
used only by capture negatives to prove the defect-targeting controls would have
been masked by the old gate.
"""

from __future__ import annotations

import re
from typing import Any

CANONICAL_KEYS = {
    "artifact": "artifact_id",
    "job": "job_id",
    "task": "task_id",
    "run": "run_id",
    "snapshot": "snapshot_id",
    "training_run": "training_run_id",
    "prediction_run": "prediction_run_id",
}

_ID_PATTERNS = {
    "artifact": re.compile(r"^artifact_[0-9a-f]{32}$"),
    "job": re.compile(r"^backtest_[0-9a-f]{32}$"),
    "task": re.compile(r"^task_[0-9a-f]{32}$"),
    "run": re.compile(r"^[0-9a-f]{32}$"),
    "snapshot": re.compile(r"^stock_pool_snapshot_[0-9a-f]{32}$"),
    "training_run": re.compile(r"^ml_training_[0-9a-f]{32}$"),
    "prediction_run": re.compile(r"^ml_prediction_[0-9a-f]{32}$"),
}

TERMINAL_STATES = {"completed", "failed", "cancelled", "timed_out", "rejected", "revoked", "expired"}


def derive_receipt(result: object, *, object_kind: str, task_id: str,
                   idempotency_key: str) -> tuple[dict | None, str | None]:
    """Derive a durable receipt from a real response; never fabricate one."""
    if object_kind not in CANONICAL_KEYS:
        return None, f"unknown object kind {object_kind!r}"
    if not isinstance(result, dict):
        return None, "missing response object"
    if result.get("error"):
        return None, f"transport error: {result['error']}"
    status = result.get("status")
    if not isinstance(status, int) or isinstance(status, bool) or not (200 <= status < 300):
        return None, f"non-success http status {status!r}"
    body = result.get("body")
    if not isinstance(body, dict) or not body:
        return None, "empty response body"
    key = CANONICAL_KEYS[object_kind]
    object_id = body.get(key)
    if not isinstance(object_id, str) or not _ID_PATTERNS[object_kind].match(object_id):
        return None, f"missing canonical {key}"
    return {
        "receipt_id": f"{object_kind}:{object_id}",
        "object_id": object_id,
        "task_id": task_id,
        "idempotency_key": idempotency_key,
    }, None


def derive_original_key_recovery(get_result: object, *, object_kind: str, task_id: str,
                                 idempotency_key: str) -> tuple[dict | None, str | None]:
    """Read-only recovery by the original key; a POST replay is not allowed."""
    if isinstance(get_result, dict) and get_result.get("method", "GET") != "GET":
        return None, "recovery must be a read-only GET by the original key"
    return derive_receipt(get_result, object_kind=object_kind, task_id=task_id,
                          idempotency_key=idempotency_key)


def derive_approval(persisted: object) -> tuple[dict | None, str | None]:
    """Authorize only an explicitly persisted approved decision."""
    if not isinstance(persisted, dict):
        return None, "missing persisted approval"
    decision = persisted.get("decision")
    if decision != "approved":
        return None, f"approval decision {decision!r} does not authorize execution"
    if persisted.get("execution_authorized") is not True:
        return None, "approval is not execution_authorized"
    return {"decision": "approved", "execution_authorized": True,
            "approval_artifact_id": persisted.get("approval_artifact_id")}, None


def check_late_result_no_next_step(next_step_before: int, next_step_after: int) -> tuple[bool, str | None]:
    if not isinstance(next_step_before, int) or not isinstance(next_step_after, int):
        return False, "next-step counts were not measured"
    if next_step_after > next_step_before:
        return False, "a late result created the next journey step"
    return True, None


def check_at_most_once(before: int, after: int) -> tuple[bool, str | None]:
    if not isinstance(before, int) or not isinstance(after, int):
        return False, "authoritative counts were not measured"
    if after - before > 1:
        return False, f"duplicate side effect ({before} -> {after})"
    return True, None


def count_orphans(rows: object) -> tuple[int, str | None]:
    if not isinstance(rows, list):
        return -1, "rows were not measured"
    return sum(1 for row in rows if isinstance(row, dict)
               and row.get("status") not in TERMINAL_STATES), None


def check_attribution(receipt: object, *, task_id: str, owner: str,
                      workspace_id: str, persisted: object) -> tuple[bool, str | None]:
    """A receipt must belong to the exact original owner/workspace/task."""
    if not isinstance(receipt, dict):
        return False, "missing receipt"
    if receipt.get("task_id") != task_id:
        return False, "receipt task does not match the original task"
    if not isinstance(persisted, dict):
        return False, "missing persisted object"
    if persisted.get("owner_principal") != owner:
        return False, "owner attribution mismatch"
    if persisted.get("workspace_id") != workspace_id:
        return False, "workspace attribution mismatch"
    return True, None


# --- legacy (pre-fix) variants: never used for qualification ------------------

def legacy_derive_receipt(result: object, *, object_kind: str = "artifact",
                          task_id: str = "", idempotency_key: str = "") -> tuple[dict | None, str | None]:
    body = result.get("body") if isinstance(result, dict) else None
    body = body if isinstance(body, dict) else {}
    object_id = body.get(CANONICAL_KEYS.get(object_kind, "artifact_id")) or "unknown"
    return {"receipt_id": "fabricated", "object_id": object_id, "task_id": task_id,
            "idempotency_key": idempotency_key}, None


def legacy_derive_approval(persisted: object) -> tuple[dict | None, str | None]:
    decision = persisted.get("decision") if isinstance(persisted, dict) else None
    if decision == "rejected":
        return None, "rejected"
    return {"decision": decision or "approved", "execution_authorized": True}, None


def legacy_check_late_result(next_step_before: int, next_step_after: int) -> tuple[bool, str | None]:
    return True, None


def legacy_check_at_most_once(before: int, after: int) -> tuple[bool, str | None]:
    return True, None


def legacy_count_orphans(rows: object) -> tuple[int, str | None]:
    return 0, None


def legacy_check_attribution(receipt: object, **_: object) -> tuple[bool, str | None]:
    return True, None


def _unused(value: Any) -> Any:  # pragma: no cover - keeps the import explicit
    return value
