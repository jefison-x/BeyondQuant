#!/usr/bin/env python3
"""Read-only, bounded CI status watcher for an exact PR/head/run/attempt.

This is a *status* tool, not a merge-authorization tool. It never upgrades
missing, expired, forbidden (403), unknown or stale evidence into PASS.

Usage:
  # One bounded read (single-shot, never sleeps, yields control immediately).
  scripts/ci/watch-ci.py --pr 123 --expected-head <sha> --once

  # Short recoverable watch; re-invoke while it reports PENDING.
  scripts/ci/watch-ci.py --pr 123 --expected-head <sha> --budget-seconds 90

  # Bind to one authoritative run/attempt (verified via the Actions API).
  scripts/ci/watch-ci.py --pr 123 --expected-head <sha> --run-id 456 --run-attempt 1 --once

The ``--budget-seconds`` value bounds the whole invocation wall time, including
API reads and bounded failure-log emission. Exit codes: 0 PASS, 1 FAIL,
2 PENDING/budget-exhausted, 3 BLOCKED/STALE.
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
DEFAULT_REPO = "jefison-x/BeyondQuant"
FETCH_TIMEOUT_SECONDS = 60.0
LOG_TIMEOUT_SECONDS = 120.0
TERMINAL_BAD = frozenset(
    {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
)
_RUN_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)(?:/|$)"
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


def _run_id_from_url(url: str, repo: str | None = None) -> str | None:
    """Return the run id only for a well-formed Actions run URL.

    The id must be a complete numeric path segment (so ``123`` never matches
    ``12345``) and, when a repo is supplied, the owner/repo must match.
    """
    match = _RUN_URL_RE.match(url or "")
    if not match:
        return None
    if repo and f"{match.group('owner')}/{match.group('repo')}".lower() != repo.lower():
        return None
    return match.group("run_id")


def _filter_run(checks: list[dict], run_id: str | None,
                repo: str | None = None) -> list[dict] | None:
    if run_id is None:
        return checks
    return [
        check
        for check in checks
        if _run_id_from_url(check.get("detailsUrl") or check.get("details_url") or "", repo)
        == str(run_id)
    ]


def evaluate(
    pr_head: str,
    expected_head: str,
    checks: list[dict],
    required: tuple[str, ...] = REQUIRED_DEFAULT,
    run_id: str | None = None,
    repo: str | None = None,
) -> dict:
    """Classify one rollup observation. Never returns PASS on absent evidence."""
    if pr_head != expected_head:
        return {"result": "STALE", "reason": "PR head no longer matches the expected exact head",
                "pending": [], "failed": []}
    if run_id is not None:
        filtered = _filter_run(checks, run_id, repo)
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
    repo: str | None = DEFAULT_REPO,
) -> tuple[int, dict]:
    """Bounded watch loop. Emits one JSON line per state change plus the final
    state, and returns ``(exit_code, final_state)``. ``extra`` metadata (such as
    the bound run/attempt) is merged into every emitted line.

    ``fetch`` is called as ``fetch(remaining_seconds)`` so each API read can be
    clamped to the remaining wall-time budget; ``once=True`` performs exactly one
    read and never sleeps, even on a retryable API failure."""
    start = clock()
    deadline = start + budget_seconds
    metadata = {"head": expected_head, **(extra or {})}
    emitted_snapshot = object()
    final = {"result": "BLOCKED", "reason": "watch did not run", "pending": [], "failed": []}
    api_failures = 0
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        try:
            observation = fetch(remaining)
        except ApiError as error:
            detail = str(error)
            if forbidden(detail):
                final = {"result": "BLOCKED", "reason": f"forbidden: {detail}",
                         "pending": [], "failed": []}
                break
            if once or not error.retryable or api_failures >= max_api_retries:
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
            repo=repo,
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
    final["elapsed_seconds"] = round(clock() - start, 3)
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


def _gh_json(args: list[str], *, timeout: float = FETCH_TIMEOUT_SECONDS):
    """Run a bounded read-only ``gh`` command, mapping every failure to ApiError."""
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise ApiError(f"gh read timed out after {timeout:.0f}s", True) from error
    except OSError as error:
        raise ApiError(f"gh read failed: {error}", True) from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or "gh read failed"
        raise ApiError(detail, is_retryable(detail))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ApiError(f"malformed gh output: {error}", True) from error


def verify_run_attempt(repo: str, run_id: str, attempt: str, expected_head: str,
                       *, read=None) -> dict:
    """Authoritatively bind the observation to one Actions run attempt.

    Any missing/expired attempt, superseded attempt, wrong repo/workflow or head
    mismatch raises a non-retryable ApiError (fail closed) so a superseded
    attempt can never inherit the latest rollup or a stale green.
    """
    read = read or _gh_json
    expected_attempt = str(attempt)
    attempt_data = read(["api", f"repos/{repo}/actions/runs/{run_id}/attempts/{expected_attempt}"])
    latest = read(["api", f"repos/{repo}/actions/runs/{run_id}"])
    repository = (attempt_data.get("repository") or {}).get("full_name") or ""
    facts = {
        "run_id": str(attempt_data.get("id", "")),
        "run_attempt": str(attempt_data.get("run_attempt", "")),
        "run_number": attempt_data.get("run_number"),
        "head_sha": attempt_data.get("head_sha") or "",
        "workflow": attempt_data.get("name") or "",
        "repository": repository,
        "status": attempt_data.get("status"),
        "conclusion": attempt_data.get("conclusion"),
    }
    if facts["run_id"] != str(run_id):
        raise ApiError(f"run {run_id}: API returned a different run id {facts['run_id']!r}", False)
    if facts["run_attempt"] != expected_attempt:
        raise ApiError(
            f"run {run_id}: attempt {expected_attempt} unavailable; "
            f"API returned attempt {facts['run_attempt']!r}", False)
    if repository.lower() != repo.lower():
        raise ApiError(
            f"run {run_id}: repository {repository!r} does not match {repo!r}", False)
    if not facts["workflow"]:
        raise ApiError(f"run {run_id}: missing workflow name", False)
    if facts["head_sha"] != expected_head:
        raise ApiError(
            f"run {run_id} attempt {expected_attempt}: head {facts['head_sha']!r} "
            f"does not match expected {expected_head!r}", False)
    if str(latest.get("run_attempt")) != expected_attempt:
        raise ApiError(
            f"run {run_id} attempt {expected_attempt} is superseded by attempt "
            f"{latest.get('run_attempt')!r}; refusing the latest rollup", False)
    if str(latest.get("id", "")) != str(run_id):
        raise ApiError(f"run {run_id}: current run id mismatch", False)
    if (latest.get("name") or "") != facts["workflow"]:
        raise ApiError(f"run {run_id}: workflow changed across attempts", False)
    return facts


def fetch_pr(repo: str, pr: int, run_id: str | None, run_attempt: str | None = None,
             expected_head: str | None = None,
             fetch_timeout: float = FETCH_TIMEOUT_SECONDS):
    def fetch(remaining: float | None = None) -> dict:
        deadline = None if remaining is None else time.monotonic() + max(0.0, remaining)

        def read(args: list[str]):
            if deadline is None:
                timeout = fetch_timeout
            else:
                timeout = min(fetch_timeout, max(0.0, deadline - time.monotonic()))
                if timeout <= 0:
                    raise ApiError("gh read budget exhausted", True)
            return _gh_json(args, timeout=timeout)

        run_facts = None
        if run_id and run_attempt:
            run_facts = verify_run_attempt(repo, run_id, run_attempt, expected_head, read=read)
        data = read(["pr", "view", str(pr), "--repo", repo,
                     "--json", "headRefOid,statusCheckRollup"])
        return {"head": data.get("headRefOid", ""),
                "checks": data.get("statusCheckRollup") or [],
                "run_id": run_id,
                "run_attempt": run_attempt,
                "run": run_facts}
    return fetch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-head", required=True,
                        help="exact 40-hex PR head; a changed head is STALE, never PASS")
    parser.add_argument("--run-id", default=None,
                        help="bind observation to one Actions run id present in the rollup")
    parser.add_argument("--run-attempt", default=None,
                        help="bind to this authoritative attempt; verified via the Actions "
                             "API (head/repo/workflow/attempt); requires --run-id")
    parser.add_argument("--required", default=",".join(REQUIRED_DEFAULT),
                        help="comma-separated required check names")
    parser.add_argument("--once", action="store_true",
                        help="single read; never sleeps or retries")
    parser.add_argument("--budget-seconds", type=float, default=90.0,
                        help="hard wall-time bound for the whole invocation; re-invoke on PENDING")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--max-api-retries", type=int, default=4)
    args = parser.parse_args()
    run_id = str(args.run_id) if args.run_id else None
    if args.run_attempt and not run_id:
        parser.error("--run-attempt requires --run-id")
    required = tuple(name.strip() for name in args.required.split(",") if name.strip())
    extra = {"run_id": run_id}
    if args.run_attempt:
        extra["run_attempt"] = str(args.run_attempt)
    fetch = fetch_pr(args.repo, args.pr, run_id, run_attempt=args.run_attempt,
                     expected_head=args.expected_head)
    started = time.monotonic()
    code, _ = run_watch(
        fetch,
        args.expected_head,
        required,
        budget_seconds=args.budget_seconds,
        interval=args.interval,
        once=args.once,
        max_api_retries=args.max_api_retries,
        extra=extra,
        repo=args.repo,
    )
    if code == 1:
        remaining = max(0.0, args.budget_seconds - (time.monotonic() - started))
        _emit_failed_logs(args.repo, run_id, timeout=remaining)
    return code


def _emit_failed_logs(repo: str, run_id: str | None,
                      *, timeout: float = LOG_TIMEOUT_SECONDS) -> None:
    """Bounded, redacted failure diagnostics; never written to disk.

    The whole log path (fetch plus redaction) is bounded by the remaining
    invocation budget and any subprocess timeout/OSError is swallowed so the
    watcher still exits with its structured status."""
    if not run_id:
        return
    budget = min(LOG_TIMEOUT_SECONDS, max(0.0, timeout))
    if budget <= 0:
        return
    deadline = time.monotonic() + budget
    try:
        log = subprocess.run(["gh", "run", "view", run_id, "--repo", repo, "--log-failed"],
                             capture_output=True, text=True,
                             timeout=max(0.0, deadline - time.monotonic()))
    except (subprocess.TimeoutExpired, OSError):
        return
    bounded = "\n".join((log.stdout or "").splitlines()[-100:])
    redactor = Path(__file__).with_name("redact-log.py")
    redact_timeout = max(0.0, deadline - time.monotonic())
    if redact_timeout <= 0:
        return
    try:
        subprocess.run([sys.executable, str(redactor)], input=bounded, text=True,
                       check=False, timeout=redact_timeout)
    except (subprocess.TimeoutExpired, OSError):
        return


if __name__ == "__main__":
    sys.exit(main())
