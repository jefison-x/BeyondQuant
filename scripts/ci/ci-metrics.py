#!/usr/bin/env python3
"""Summarize one CI run from its already-redacted logs.

Reads the redacted ``checks.log`` (and optional ``cleanup.log``) produced by the
existing entry points, then reports selection, phase wall time, pytest counts
and slow setup/call/teardown items, built image identities and cache state. It
never fetches or uploads logs and re-applies the shared redactor as
defense-in-depth.

Example:
  python3 scripts/ci/ci-metrics.py --log .ci-artifacts/checks.log \
    --sha <40-hex> --run <id> --attempt <n>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

TIMING = re.compile(r'\[byq-timing\] phase="([^"]*)" seconds=(\d+)')
TOTAL = re.compile(r"\[byq-timing\] total seconds=(\d+) exit=(\d+)")
PLAN = re.compile(r"plan -> (.+)")
PYTEST_SUMMARY = re.compile(
    r"(\d+) passed"
    r"(?:, (\d+) skipped)?"
    r"(?:, (\d+) failed)?"
    r"(?:, (\d+) error[s]?)?"
    r"(?:, (\d+) deselected)?"
    r" in ([\d.]+)s"
)
PYTEST_COLLECTED = re.compile(r"collected (\d+) items")
DURATION = re.compile(r"^\s*([\d.]+)s (setup|call|teardown)\s+(\S.*?)\s*$")
IMAGE = re.compile(r"image identity -> service=(\S+) tag=(\S+) id=(\S+)")


def _redactor():
    path = Path(__file__).with_name("redact-log.py")
    spec = importlib.util.spec_from_file_location("byq_redact_log", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.redact


def _safe(redact, value: str) -> str:
    return redact(value)


def parse(text: str, redact) -> dict:
    phases: list[dict] = []
    totals: dict = {}
    selection: str | None = None
    tests: list[dict] = []
    slowest: dict[str, list[dict]] = {"setup": [], "call": [], "teardown": []}
    images: list[dict] = []
    cached_lines = 0
    collected: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if "CACHED" in line:
            cached_lines += 1
        timing = TIMING.search(line)
        if timing:
            phases.append({"phase": _safe(redact, timing.group(1)), "seconds": int(timing.group(2))})
            continue
        total = TOTAL.search(line)
        if total:
            totals = {"seconds": int(total.group(1)), "exit_code": int(total.group(2))}
            continue
        plan = PLAN.search(line)
        if plan:
            selection = _safe(redact, plan.group(1))
            continue
        match = PYTEST_COLLECTED.search(line)
        if match:
            collected = int(match.group(1))
        summary = PYTEST_SUMMARY.search(line)
        if summary:
            passed = int(summary.group(1))
            skipped = int(summary.group(2) or 0)
            failed = int(summary.group(3) or 0)
            errors = int(summary.group(4) or 0)
            tests.append({
                "passed": passed,
                "skipped": skipped,
                "failed": failed,
                "errors": errors,
                "collected": collected if collected is not None else passed + skipped + failed + errors,
                "duration_seconds": float(summary.group(6)),
            })
            collected = None
            continue
        duration = DURATION.match(line)
        if duration:
            slowest[duration.group(2)].append({
                "seconds": float(duration.group(1)),
                "item": _safe(redact, duration.group(3)),
            })
            continue
        image = IMAGE.search(line)
        if image:
            images.append({"service": _safe(redact, image.group(1)),
                           "tag": _safe(redact, image.group(2)),
                           "id": _safe(redact, image.group(3))})
    for bucket in slowest.values():
        bucket.sort(key=lambda item: item["seconds"], reverse=True)
    return {
        "selection": selection,
        "phase_seconds": phases,
        "total": totals,
        "pytest": tests,
        "slowest": slowest,
        "images": images,
        "cache_cached_lines": cached_lines,
    }


def collect(checks_log: Path, cleanup_log: Path | None, top: int) -> dict:
    redact = _redactor()
    checks = checks_log.read_text(encoding="utf-8", errors="replace")
    summary = parse(checks, redact)
    for bucket in summary["slowest"].values():
        del bucket[top:]
    if cleanup_log is not None and cleanup_log.exists():
        cleanup = parse(cleanup_log.read_text(encoding="utf-8", errors="replace"), redact)
        summary["cleanup_phase_seconds"] = cleanup["phase_seconds"]
        summary["cleanup_total"] = cleanup["total"]
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--cleanup-log", type=Path, default=None)
    parser.add_argument("--sha", default=None)
    parser.add_argument("--run", default=None)
    parser.add_argument("--attempt", default=None)
    parser.add_argument("--queue-seconds", type=int, default=None,
                        help="optional queue time from the Actions run API")
    parser.add_argument("--top", type=int, default=10, help="slow items per bucket")
    args = parser.parse_args()
    result = {
        "sha": args.sha,
        "run_id": args.run,
        "run_attempt": args.attempt,
        "queue_seconds": args.queue_seconds,
        **collect(args.log, args.cleanup_log, args.top),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
