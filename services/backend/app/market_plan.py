"""Deterministic aggregate-scope market-data partition planning (ADR-0047).

The 50,000-cell bound is an invariant of one independently assessable and
retryable readiness partition. An aggregate frozen universe/date window is
split into non-overlapping date partitions here, and aggregate readiness is
derived only from the current partition assessments. This module stays free of
HTTP concerns and of any concrete Provider caller.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Protocol

MAX_PLAN_PARTITIONS = 32
MAX_PARTITION_CHUNK_DAYS = 180


class RequirementFactory(Protocol):
    def requirement(
        self, *, symbols: list[str], start_date: str, end_date: str,
        membership_fingerprint: str, security_master_snapshot_id: str,
        data_requirements: dict[str, object] | None = None,
    ) -> dict[str, object]: ...


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def content_sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def partition_market_requirements(
    store: RequirementFactory, *, symbols: list[str], start: datetime, end: datetime,
    membership_fingerprint_value: str, security_master_snapshot_id: str,
    declared: dict[str, object],
) -> list[dict[str, object]]:
    """Create bounded atomic readiness units for one aggregate frozen scope."""
    requirements: list[dict[str, object]] = []
    cursor = start
    max_chunk_days = min(
        MAX_PARTITION_CHUNK_DAYS, max(1, int(50_000 / len(symbols) * 1.25))
    )
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_chunk_days - 1))
        requirements.append(store.requirement(
            symbols=symbols, start_date=cursor.strftime("%Y%m%d"),
            end_date=chunk_end.strftime("%Y%m%d"),
            membership_fingerprint=membership_fingerprint_value,
            security_master_snapshot_id=security_master_snapshot_id,
            data_requirements=declared,
        ))
        cursor = chunk_end + timedelta(days=1)
    if not requirements or len(requirements) > MAX_PLAN_PARTITIONS:
        raise ValueError("market data preparation partition plan exceeds 32 units")
    return requirements


def build_requirement_plan(requirements: list[dict[str, object]]) -> dict[str, object]:
    """Freeze the ordered per-partition requirement identities for persistence."""
    if not requirements or len(requirements) > MAX_PLAN_PARTITIONS:
        raise ValueError("market data preparation partition plan is invalid")
    partitions = [
        {
            "start_date": str(item["start_date"]), "end_date": str(item["end_date"]),
            "requirement_sha256": str(item["requirement_sha256"]),
        }
        for item in requirements
    ]
    plan: dict[str, object] = {
        "schema_version": "market-data-requirement-plan.v1",
        "partition_count": len(requirements),
        "partitions": partitions,
        "requirements": requirements,
    }
    plan["requirement_plan_sha256"] = content_sha256({
        "schema_version": plan["schema_version"], "partition_count": plan["partition_count"],
        "partitions": plan["partitions"],
    })
    return plan


def aggregate_market_readiness(assessments: list[dict[str, object]]) -> dict[str, object]:
    """Derive one aggregate readiness from independent partition assessments."""
    if not assessments:
        raise ValueError("market data preparation has no readiness partitions")
    ready_count = sum(item.get("state") == "ready" for item in assessments)
    missing: list[dict[str, str]] = []
    missing_by_dataset: dict[str, int] = {}
    missing_dates: set[str] = set()
    repair_full: set[str] = set()
    repair_supplements: set[str] = set()
    seen: set[tuple[str, str, str]] = set()
    for assessment in assessments:
        counts = assessment.get("missing_by_dataset", {})
        if isinstance(counts, dict):
            for dataset, count in counts.items():
                missing_by_dataset[str(dataset)] = (
                    missing_by_dataset.get(str(dataset), 0) + int(count or 0)
                )
        for date in assessment.get("missing_trade_dates", []) or []:
            missing_dates.add(str(date))
        repair_plan = assessment.get("repair_plan", {})
        if isinstance(repair_plan, dict):
            repair_full.update(str(item) for item in repair_plan.get("full_sessions", []) or [])
            repair_supplements.update(
                str(item) for item in repair_plan.get("session_supplements", []) or []
            )
        for item in assessment.get("missing", []) or []:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("symbol", "*")), str(item.get("trade_date", "*")),
                str(item.get("dataset", "unknown")),
            )
            if key in seen:
                continue
            seen.add(key)
            missing.append({"symbol": key[0], "trade_date": key[1], "dataset": key[2]})
    ready_hashes = [item.get("ready_input_sha256") for item in assessments]
    all_ready = ready_count == len(assessments)
    return {
        "schema_version": "market-data-readiness.v1",
        "state": "ready" if all_ready else (
            "partial" if any(item.get("state") == "partial" for item in assessments) else "missing"
        ),
        "partition_count": len(assessments),
        "ready_partitions": ready_count,
        "required_session_count": sum(
            int(item.get("required_session_count") or 0) for item in assessments
        ),
        "required_cell_count": sum(
            int(item.get("required_cell_count") or 0) for item in assessments
        ),
        "missing_count": sum(int(item.get("missing_count") or 0) for item in assessments),
        "missing": missing[:200],
        "missing_by_dataset": missing_by_dataset,
        "missing_trade_dates": sorted(missing_dates),
        "repair_plan": {
            "session_supplements": sorted(repair_supplements),
            "full_sessions": sorted(repair_full),
        },
        "calendar_complete": all(bool(item.get("calendar_complete")) for item in assessments),
        "ready_input_sha256": (
            ready_hashes[0] if len(ready_hashes) == 1 else content_sha256(ready_hashes)
        ) if all_ready else None,
    }
