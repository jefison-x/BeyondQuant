#!/usr/bin/env python3
"""Read-only, exact-revision CLA and maintainer review preflight."""
import argparse
import base64
import hashlib
import json
import re
import subprocess

MAINTAINER = "jefison-x"
REPOSITORY = "jefison-x/BeyondQuant"
STATEMENTS = (
    "我已阅读并同意 BYQ-ICLA-1.0，包括授予维护者商业使用和再许可权；我保留我的版权。",
    "我作为个人确认拥有本次贡献所需权利，并已披露第三方内容及任何权利限制。",
)


def acceptance(number, head, digest):
    return "\n".join(("BYQ-ICLA-1.0 ACCEPT", f"PR: {number}", f"HEAD: {head}",
                      f"AGREEMENT-SHA256: {digest}", *STATEMENTS))


def evaluate(pr, commits, comments, reviews, digest, expected_head):
    problems = []
    if (pr.get("state") != "open" or pr.get("base", {}).get("ref") != "main"
            or pr.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY):
        problems.append("not an open upstream main PR")
    head = pr.get("head", {}).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", head) or head != expected_head:
        problems.append("PR revision changed or invalid")
    author = pr.get("user") or {}
    if author.get("type") != "User" or not author.get("login"):
        problems.append("PR author is not an identified individual account")
    contributors = {author.get("login", "")}
    if not commits:
        problems.append("commit authors unavailable")
    for commit in commits:
        identity = commit.get("author") or {}
        if identity.get("type") != "User" or not identity.get("login"):
            problems.append("unmapped/bot commit author requires human rights resolution")
        else:
            contributors.add(identity["login"])
        # Arbitrary email/name text is not a verified GitHub co-author identity.
        if re.search(r"(?im)^Co-authored-by:", commit.get("commit", {}).get("message", "")):
            problems.append("co-author trailers require separate human authorization review")
    accepted = set()
    for comment in comments:
        identity = comment.get("user") or {}
        if identity.get("type") == "User" and (comment.get("body") or "").replace("\r\n", "\n").strip() == acceptance(pr.get("number"), head, digest):
            accepted.add(identity.get("login"))
    for login in sorted(contributors - {MAINTAINER, ""}):
        if login not in accepted:
            problems.append(f"missing exact-head CLA acceptance: {login}")
    latest = {}
    for review in sorted(reviews, key=lambda r: r.get("submitted_at") or ""):
        if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[(review.get("user") or {}).get("login")] = review
    if any(r.get("state") == "CHANGES_REQUESTED" for r in latest.values()):
        problems.append("outstanding change request")
    if contributors - {MAINTAINER, ""}:
        review = latest.get(MAINTAINER, {})
        if review.get("state") != "APPROVED" or review.get("commit_id") != head:
            problems.append("maintainer approval of exact head and provenance required")
    return problems


def api(endpoint, paginate=False):
    command = ["gh", "api", endpoint]
    if paginate:
        command.append("--paginate")
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise ValueError("GitHub read unavailable")
    if not paginate:
        return json.loads(result.stdout)
    decoder = json.JSONDecoder()
    data = result.stdout.strip()
    items = []
    while data:
        page, end = decoder.raw_decode(data)
        if not isinstance(page, list):
            raise ValueError("unexpected GitHub pagination")
        items.extend(page)
        if len(items) > 3000:
            raise ValueError("review payload exceeds bounded automated audit; human review required")
        data = data[end:].lstrip()
    return items


def verify(repo, number, expected_head):
    if repo != REPOSITORY:
        raise ValueError("upstream contribution policy requires the upstream repository")
    prefix = f"repos/{repo}"
    pr = api(f"{prefix}/pulls/{number}")
    base = pr["base"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("invalid base revision")
    content = api(f"{prefix}/contents/CONTRIBUTOR_LICENSE_AGREEMENT.md?ref={base}")
    if content.get("encoding") != "base64":
        raise ValueError("base CLA unavailable")
    digest = hashlib.sha256(base64.b64decode(content["content"])).hexdigest()
    commits = api(f"{prefix}/pulls/{number}/commits?per_page=100", True)
    comments = api(f"{prefix}/issues/{number}/comments?per_page=100", True)
    reviews = api(f"{prefix}/pulls/{number}/reviews?per_page=100", True)
    problems = evaluate(pr, commits, comments, reviews, digest, expected_head)
    # Close the observation window: a moving PR cannot inherit old authorization.
    if api(f"{prefix}/pulls/{number}")["head"]["sha"] != expected_head:
        problems.append("PR head changed during authorization audit")
    return problems, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    try:
        problems, digest = verify(args.repo, args.pr, args.expected_head)
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired):
        print("BLOCKED: contribution evidence unavailable or malformed; no bypass")
        return 1
    for problem in problems:
        print(f"BLOCKED: {problem}")
    if not problems:
        print(f"Contribution preflight PASS; PR {args.pr}; head {args.expected_head}; CLA SHA256 {digest}")
        print("Account records do not prove ownership. Maintainer provenance review remains mandatory.")
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())
