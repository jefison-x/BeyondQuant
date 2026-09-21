#!/usr/bin/env python3
"""Read-only preflight for ADR-0015 auto-merge; unknown is not permission.

The merge gate evaluates ONLY the latest valid BeyondQuant CI workflow run for
the exact PR head. A newer run supersedes an older cancelled/failed run on the
same head (the workflow uses ``cancel-in-progress``), so an older cancelled
check suite must not pollute the conclusion. Selection is by run identity (the
``/actions/runs/<id>`` in each check's details URL), never by check name, so an
older generic matrix ``checks`` context cannot shadow the newer expanded lane
names. Fail-closed: a missing/unconfirmable run, a run for a different head, any
non-success/cancelled/skipped/incomplete check, or a missing required context is
BLOCKED.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys

REQUIRED = {"local-ci", "ci-gate"}
BEYONDQUANT_WORKFLOW = "BeyondQuant CI"
RUN_URL = re.compile(r"/actions/runs/(\d+)")


def check_run_id(check: dict) -> str | None:
    url = check.get("detailsUrl") or check.get("details_url") or ""
    match = RUN_URL.search(str(url))
    return match.group(1) if match else None


def check_success(check: dict) -> bool:
    return ((check.get("status") == "COMPLETED" and check.get("conclusion") == "SUCCESS")
            or check.get("state") == "SUCCESS")


def _timestamp(value: object) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_recency(checks: list[dict]) -> datetime.datetime:
    stamps = [stamp for check in checks
              for stamp in (_timestamp(check.get("startedAt")), _timestamp(check.get("completedAt")))
              if stamp is not None]
    return max(stamps) if stamps else datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def _latest_run(groups: dict[str, list[dict]], required: set[str]) -> str | None:
    qualifying = {run_id: checks for run_id, checks in groups.items()
                  if any((check.get("name") or check.get("context")) in required for check in checks)}
    if not qualifying:
        return None
    return max(qualifying, key=lambda run_id: _run_recency(qualifying[run_id]))


def evaluate(repo: dict, protection: dict | None, pr: dict | None = None) -> list[str]:
    problems = []
    if not repo.get("allow_auto_merge"):
        problems.append("GitHub auto-merge is disabled")
    if not repo.get("allow_squash_merge"):
        problems.append("squash merge is disabled")
    required_checks = (protection or {}).get("required_status_checks") or {}
    names = set(required_checks.get("contexts") or []) | {
        c["context"] for c in required_checks.get("checks") or []}
    if protection is None:
        problems.append("branch protection unavailable/unverified; inspect rulesets with maintainer")
    if not REQUIRED.issubset(names) or not required_checks.get("strict"):
        problems.append("strict server-side local-ci + ci-gate requirements not verified")
    if pr is not None:
        if pr.get("baseRefName") != "main" or pr.get("mergeable") != "MERGEABLE":
            problems.append("PR base/mergeability not verified")
        review_rules = (protection or {}).get("required_pull_request_reviews") or {}
        if review_rules.get("required_approving_review_count", 0) and pr.get("reviewDecision") != "APPROVED":
            problems.append("required independent review is not approved")
        required = REQUIRED | names
        checks = pr.get("statusCheckRollup") or []
        groups: dict[str, list[dict]] = {}
        runless: list[dict] = []
        for check in checks:
            run_id = check_run_id(check)
            if run_id is None:
                runless.append(check)
            else:
                groups.setdefault(run_id, []).append(check)
        latest = _latest_run(groups, required)
        if latest is None:
            problems.append("no BeyondQuant CI check suite found for the current PR revision")
        else:
            run = (pr.get("runs") or {}).get(latest)
            if not isinstance(run, dict):
                problems.append(f"workflow run {latest} ownership is unconfirmed")
            else:
                if run.get("head_sha") != pr.get("headRefOid"):
                    problems.append(f"workflow run {latest} is not for the current PR revision")
                if run.get("name") != BEYONDQUANT_WORKFLOW:
                    problems.append(f"workflow run {latest} is not the BeyondQuant CI workflow")
                if run.get("status") != "completed" or run.get("conclusion") != "success":
                    problems.append(f"latest BeyondQuant CI run {latest} did not complete successfully")
            passed = set()
            for check in groups[latest]:
                name = check.get("name") or check.get("context")
                if check_success(check):
                    passed.add(name)
                else:
                    problems.append(f"check not executed successfully: {name}")
            if not required.issubset(passed):
                problems.append("required checks have not actually succeeded on current PR revision")
        for check in runless:
            name = check.get("name") or check.get("context")
            if name in required:
                problems.append(f"required check {name} has no confirmable workflow run")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int)
    args = parser.parse_args()
    def gh(*parts: str):
        try:
            result = subprocess.run(["gh", *parts], capture_output=True, text=True, timeout=30)
            return json.loads(result.stdout) if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None
    repo = gh("api", f"repos/{args.repo}")
    if repo is None:
        print("BLOCKED: repository metadata unavailable")
        return 1
    protection = gh("api", f"repos/{args.repo}/branches/main/protection")
    pr = None
    if args.pr is not None:
        pr = gh("pr", "view", str(args.pr), "--repo", args.repo, "--json",
                "headRefOid,baseRefName,mergeable,reviewDecision,statusCheckRollup")
        if pr is None:
            print("BLOCKED: PR evidence unavailable")
            return 1
        run_ids = sorted({run_id for check in pr.get("statusCheckRollup") or []
                          for run_id in (check_run_id(check),) if run_id})
        runs = {}
        for run_id in run_ids:
            metadata = gh("api", f"repos/{args.repo}/actions/runs/{run_id}")
            if metadata is not None:
                runs[run_id] = {"head_sha": metadata.get("head_sha"), "status": metadata.get("status"),
                                "conclusion": metadata.get("conclusion"), "name": metadata.get("name")}
        pr["runs"] = runs
        print(f"Observed PR head: {pr['headRefOid']}; recheck immediately before any authorized merge")
    problems = evaluate(repo, protection, pr)
    if not problems and pr is not None:
        try:
            contribution = subprocess.run([sys.executable, str(Path(__file__).with_name("check-contribution.py")),
                "--repo", args.repo, "--pr", str(args.pr), "--expected-head", pr["headRefOid"]], timeout=120)
            if contribution.returncode:
                problems.append("fresh contribution authorization preflight failed")
        except (OSError, subprocess.TimeoutExpired):
            problems.append("fresh contribution authorization preflight unavailable")
    for problem in problems:
        print(f"BLOCKED: {problem}")
    if not problems:
        print("Configuration/check preflight PASS; this is not authorization and performs no merge")
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())
