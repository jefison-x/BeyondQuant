#!/usr/bin/env python3
"""Read-only preflight for ADR-0015 auto-merge; unknown is not permission."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

REQUIRED = {"local-ci", "ci-gate"}


def evaluate(repo: dict, protection: dict | None, pr: dict | None = None) -> list[str]:
    problems = []
    if not repo.get("allow_auto_merge"):
        problems.append("GitHub auto-merge is disabled")
    if not repo.get("allow_squash_merge"):
        problems.append("squash merge is disabled")
    required = (protection or {}).get("required_status_checks") or {}
    names = set(required.get("contexts") or []) | {c["context"] for c in required.get("checks") or []}
    if protection is None:
        problems.append("branch protection unavailable/unverified; inspect rulesets with maintainer")
    if not REQUIRED.issubset(names) or not required.get("strict"):
        problems.append("strict server-side local-ci + ci-gate requirements not verified")
    if pr is not None:
        if pr.get("baseRefName") != "main" or pr.get("mergeable") != "MERGEABLE":
            problems.append("PR base/mergeability not verified")
        review_rules = (protection or {}).get("required_pull_request_reviews") or {}
        if review_rules.get("required_approving_review_count", 0) and pr.get("reviewDecision") != "APPROVED":
            problems.append("required independent review is not approved")
        # Reject skipped/neutral checks, old/unfinished runs and all reported failures.
        checks = pr.get("statusCheckRollup") or []
        passed = set()
        for check in checks:
            name = check.get("name") or check.get("context")
            success = (check.get("status") == "COMPLETED" and check.get("conclusion") == "SUCCESS") or check.get("state") == "SUCCESS"
            if success:
                passed.add(name)
            else:
                problems.append(f"check not executed successfully: {name}")
        if not (REQUIRED | names).issubset(passed):
            problems.append("required checks have not actually succeeded on current PR revision")
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
