"""Truthful bounded progress helpers shared by durable Product task projections."""

from __future__ import annotations


def progress_percent(completed: int, total: int, *, fallback: int = 0) -> int:
    normalized_completed = max(0, int(completed))
    normalized_total = max(0, int(total))
    if normalized_total == 0:
        return max(0, min(100, int(fallback)))
    if normalized_completed >= normalized_total:
        return 100
    return max(0, min(99, normalized_completed * 100 // normalized_total))


def task_progress(
    completed: int,
    total: int,
    *,
    fallback: int = 0,
    unit: str,
) -> dict[str, object]:
    normalized_completed = max(0, int(completed))
    normalized_total = max(0, int(total))
    return {
        "completed": normalized_completed,
        "total": normalized_total,
        "percent": progress_percent(
            normalized_completed, normalized_total, fallback=fallback,
        ),
        "unit": unit,
    }
