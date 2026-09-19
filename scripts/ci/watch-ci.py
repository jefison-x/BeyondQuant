#!/usr/bin/env python3
"""Read-only, bounded CI status watcher for an exact PR/head/run/attempt.

This is a *status* tool, not a merge-authorization tool. It never upgrades
missing, expired, forbidden (403), unknown or stale evidence into PASS.

Usage:
  # One bounded read (does not sleep, yields control immediately).
  scripts/ci/watch-ci.py --pr 123 --expected-head <sha> --once

  # Short recoverable watch; re-invoke while it reports PENDING.
  scripts/ci/watch-ci.py --pr 123 --expected-head <sha> --budget-seconds 90

Exit codes: 0 PASS, 1 FAIL, 2 PENDING/budget-exhausted, 3 BLOCKED/STALE.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REQUIRED_DEFAULT = ("local-ci", "ci-gate")
TERMINAL_BAD = frozenset(
    {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
)


class ApiError(Exception):
    """A gh/API read failure; retryable distinguishes 429/5xx/timeout from 403."""

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def is_retryable(message: str) -> bool:
    text = message.lower()
    if "403" in text or "forbidden" in text:
        return False
    if any(
        token in text
        for token in ("429", "rate limit", "secondary rate", "timeout", "timed out",
                      "connection reset", "temporary", "unavailable", "bad gateway", "gateway timeout")
    ):
        return True
    return bool(re.search(r"\b5\d\d\b", text))


def forbidden(message: str) -> bool:
    text = message.lower()
    return "403" in text or "forbidden" in text


def check_name(check: dict) -> str:
    return check.get("name") or check.get("context") or "?"


def snapshot(checks: list[dict]) -> tuple:
    return tuple(
        sorted(
            (check_name(check), (check.get("status") or "UNKNOWN").upper(),
             (check.get("conclusion") or "").upper())
            for check in checks
        )
    )


def _filter_run(checks: list[dict], run_id: str | None) -> list[dict] | None:
    if run_id is None:
        return checks
    marker = f"/runs/{run_id}"
    return [
        check
        for check in checks
        if marker in (check.get("detailsUrl") or check.get("details_url") or "")
    ]


def evaluate(
    pr_head: str,
    expected_head: str,
    checks: list[dict],
    required: tuple[str, ...] = REQUIRED_DEFAULT,
    run_id: str | None = None,
) -> dict:
    """Classify one rollup observation. Never returns PASS on absent evidence."""
    if pr_head != expected_head:
        return {"result": "STALE", "reason": "PR head no longer matches the expected exact head",
                "pending": [], "failed": []}
    if run_id is not None:
        filtered = _filter_run(checks, run_id)
        if not filtered:
            return {"result": "BLOCKED", "reason": f"run {run_id} not present in the rollup",
                    "pending": [], "failed": []}
        checks = filtered
    if not checks:
        return {"result": "BLOCKED", "reason": "no checks observed", "pending": [], "failed": []}

    failed = sorted({check_name(c) for c in checks
                     if (c.get("conclusion") or "").upper() in TERMINAL_BAD})
    if failed:
        return {"result": "FAIL", "reason": "terminal failing check(s)", "pending": [], "failed": failed}

    completed = [(c, (c.get("conclusion") or "").upper())
                 for c in checks if (c.get("status") or "").upper() == "COMPLETED"]
    not_success = sorted({check_name(c) for c, conclusion in completed if conclusion != "SUCCESS"})
    if not_success:
        # SKIPPED/NEUTRAL/CANCELLED are not successful testing.
        return {"result": "FAIL", "reason": "completed check(s) without success",
                "pending": [], "failed": not_success}

    pending = sorted({check_name(c) for c in checks
                      if (c.get("status") or "").upper() != "COMPLETED"})
    if pending:
        return {"result": "PENDING", "reason": "check(s) still running", "pending": pending, "failed": []}

    names = {check_name(c) for c in checks}
    missing = [name for name in required if name not in names]
    if missing:
        return {"result": "BLOCKED", "reason": "required checks missing: " + ",".join(missing),
                "pending": [], "failed": []}
    return {"result": "PASS", "reason": "all observed checks succeeded", "pending": [], "failed": []}


def backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Finite exponential backoff for retryable API failures."""
    return min(cap, base * (2 ** (max(1, attempt) - 1)))


def run_watch(
    fetch,
    expected_head: str,
    required: tuple[str, ...] = REQUIRED_DEFAULT,
    *,
    budget_seconds: float = 90.0,
    interval: float = 20.0,
    once: bool = False,
    max_api_retries: int = 4,
    backoff_base: float = 5.0,
    backoff_cap: float = 60.0,
    extra: dict | None = None,
    emit=print,
    clock=time.monotonic,
    sleep=time.sleep,
) -> tuple[int, dict]:
    """Bounded watch loop. Emits one JSON line per state change plus the final
    state, and returns ``(exit_code, final_state)``. ``extra`` metadata (such as
    the bound run/attempt) is merged into every emitted line."""
    deadline = clock() + budget_seconds
    metadata = {"head": expected_head, **(extra or {})}
    emitted_snapshot = object()
    final = {"result": "BLOCKED", "reason": "watch did not run", "pending": [], "failed": []}
    api_failures = 0
    while True:
        try:
            observation = fetch()
        except ApiError as error:
            detail = str(error)
            if forbidden(detail):
                final = {"result": "BLOCKED", "reason": f"forbidden: {detail}",
                         "pending": [], "failed": []}
                break
            if not error.retryable or api_failures >= max_api_retries:
                final = {"result": "BLOCKED", "reason": f"api unavailable: {detail}",
                         "pending": [], "failed": []}
                break
            api_failures += 1
            delay = backoff_delay(api_failures, backoff_base, backoff_cap)
            if clock() + delay >= deadline:
                final = {"result": "BLOCKED", "reason": "api retry budget exhausted",
                         "pending": [], "failed": []}
                break
            sleep(delay)
            continue
        api_failures = 0
        final = evaluate(
            observation.get("head", ""),
            expected_head,
            observation.get("checks") or [],
            required,
            run_id=observation.get("run_id"),
        )
        current = (final["result"], tuple(final.get("failed", ())), tuple(final.get("pending", ())))
        if current != emitted_snapshot:
            emit(json.dumps({**metadata, **final}, ensure_ascii=False))
            emitted_snapshot = current
        if final["result"] != "PENDING" or once:
            break
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleep(min(interval, remaining))
    final_snapshot = (final["result"], tuple(final.get("failed", ())), tuple(final.get("pending", ())))
    if final_snapshot != emitted_snapshot:
        emit(json.dumps({**metadata, **final}, ensure_ascii=False))
    if final["result"] == "PASS":
        return 0, final
    if final["result"] == "FAIL":
        return 1, final
    if final["result"] == "PENDING":
        return 2, final
    return 3, final


def _gh_json(args: list[str]):
    result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or "gh read failed"
        raise ApiError(detail, is_retryable(detail))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ApiError(f"malformed gh output: {error}", True) from error


def fetch_pr(repo: str, pr: int, run_id: str | None):
    def fetch() -> dict:
        data = _gh_json(["pr", "view", str(pr), "--repo", repo,
                         "--json", "headRefOid,statusCheckRollup"])
        return {"head": data.get("headRefOid", ""),
                "checks": data.get("statusCheckRollup") or [],
                "run_id": run_id}
    return fetch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="jefison-x/BeyondQuant")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-head", required=True,
                        help="exact 40-hex PR head; a changed head is STALE, never PASS")
    parser.add_argument("--run-id", default=None,
                        help="bind observation to one Actions run id present in the rollup")
    parser.add_argument("--run-attempt", default=None,
                        help="metadata only; recorded alongside the observed run")
    parser.add_argument("--required", default=",".join(REQUIRED_DEFAULT),
                        help="comma-separated required check names")
    parser.add_argument("--once", action="store_true", help="single read; never sleeps")
    parser.add_argument("--budget-seconds", type=float, default=90.0,
                        help="bounded wall time per invocation; re-invoke on PENDING")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--max-api-retries", type=int, default=4)
    args = parser.parse_args()
    run_id = str(args.run_id) if args.run_id else None
    required = tuple(name.strip() for name in args.required.split(",") if name.strip())
    extra = {"run_id": run_id}
    if args.run_attempt:
        extra["run_attempt"] = str(args.run_attempt)
    fetch = fetch_pr(args.repo, args.pr, run_id)
    code, _ = run_watch(
        fetch,
        args.expected_head,
        required,
        budget_seconds=args.budget_seconds,
        interval=args.interval,
        once=args.once,
        max_api_retries=args.max_api_retries,
        extra=extra,
    )
    if code == 1:
        _emit_failed_logs(args.repo, run_id)
    return code


def _emit_failed_logs(repo: str, run_id: str | None) -> None:
    """Bounded, redacted failure diagnostics; never written to disk."""
    if not run_id:
        return
    log = subprocess.run(["gh", "run", "view", run_id, "--repo", repo, "--log-failed"],
                         capture_output=True, text=True, timeout=120)
    bounded = "\n".join((log.stdout or "").splitlines()[-100:])
    redactor = Path(__file__).with_name("redact-log.py")
    subprocess.run([sys.executable, str(redactor)], input=bounded, text=True, check=False)


if __name__ == "__main__":
    sys.exit(main())
