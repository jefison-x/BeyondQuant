#!/usr/bin/env python3
"""Capture-layer negatives for the 0.9 composite research fault regression.

Unlike the observer's synthetic JSON fixtures, these cases exercise the real
capture-layer helper functions with faulty inputs, then show:

* the PRE-FIX capture (legacy "trust the result" helpers) accepts the fault, and
* the POST-FIX capture emits a failure for the same input.

Exits non-zero unless every post-fix case fails and every pre-fix case passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import capture  # noqa: E402

TASK = "task_" + "a" * 32
OWNER = "v090-composite-user"
WORKSPACE = "workspace_v090_composite"
KEY = "v090-composite-original-key"


def _receipt_case(result: dict) -> tuple[bool, bool]:
    fixed, fixed_error = capture.derive_receipt(result, object_kind="artifact",
                                                task_id=TASK, idempotency_key=KEY)
    legacy, _ = capture.legacy_derive_receipt(result, object_kind="artifact",
                                              task_id=TASK, idempotency_key=KEY)
    return fixed is not None, legacy is not None


def _case(name: str, *, fixed_fail: bool, legacy_pass: bool, detail: str) -> dict:
    return {"name": name, "post_fix_failed": fixed_fail, "pre_fix_legacy_passed": legacy_pass,
            "detail": detail}


def run() -> dict:
    cases: list[dict] = []

    fixed, legacy = _receipt_case({"error": "read timeout after commit"})
    cases.append(_case("transport-timeout-not-a-receipt", fixed_fail=not fixed,
                       legacy_pass=legacy, detail="timeout must not fabricate a receipt"))

    fixed, legacy = _receipt_case({"status": 500, "body": {"artifact_id": "artifact_" + "b" * 32}})
    cases.append(_case("http-500-not-a-receipt", fixed_fail=not fixed, legacy_pass=legacy,
                       detail="5xx must not be projected as success"))

    fixed, legacy = _receipt_case({"status": 201, "body": {}})
    cases.append(_case("empty-body-not-a-receipt", fixed_fail=not fixed, legacy_pass=legacy,
                       detail="empty body must not become a canonical receipt"))

    fixed, legacy = _receipt_case({"status": 200, "body": {"status": "completed"}})
    cases.append(_case("completed-without-identity-not-a-receipt", fixed_fail=not fixed,
                       legacy_pass=legacy, detail="a completion flag without identity is not evidence"))

    recovered, error = capture.derive_original_key_recovery(
        {"method": "POST", "status": 201, "body": {"artifact_id": "artifact_" + "b" * 32}},
        object_kind="artifact", task_id=TASK, idempotency_key=KEY)
    legacy_recovered, _ = capture.legacy_derive_receipt(
        {"status": 201, "body": {"artifact_id": "artifact_" + "b" * 32}},
        object_kind="artifact", task_id=TASK, idempotency_key=KEY)
    cases.append(_case("recovery-must-be-read-only", fixed_fail=recovered is None,
                       legacy_pass=legacy_recovered is not None,
                       detail="recovery replaying a POST is not allowed"))

    fixed_ok, _ = capture.check_at_most_once(1, 3)
    legacy_ok, _ = capture.legacy_check_at_most_once(1, 3)
    cases.append(_case("duplicate-side-effect", fixed_fail=not fixed_ok, legacy_pass=legacy_ok,
                       detail="1 -> 3 side effects is a duplicate"))

    fixed_ok, _ = capture.check_late_result_no_next_step(0, 1)
    legacy_ok, _ = capture.legacy_check_late_result(0, 1)
    cases.append(_case("late-result-created-next-step", fixed_fail=not fixed_ok, legacy_pass=legacy_ok,
                       detail="a late result must not create the next step"))

    fixed_orphans, _ = capture.count_orphans([{"status": "active"}, {"status": "completed"}])
    legacy_orphans, _ = capture.legacy_count_orphans([{"status": "active"}, {"status": "completed"}])
    cases.append(_case("orphan-active-remains", fixed_fail=fixed_orphans != 0,
                       legacy_pass=legacy_orphans == 0, detail="an active orphan must be non-zero"))

    fixed_attr, _ = capture.check_attribution(
        {"task_id": TASK}, task_id=TASK, owner=OWNER, workspace_id=WORKSPACE,
        persisted={"owner_principal": "other-user", "workspace_id": WORKSPACE})
    legacy_attr, _ = capture.legacy_check_attribution({"task_id": TASK})
    cases.append(_case("wrong-owner-attribution", fixed_fail=not fixed_attr, legacy_pass=legacy_attr,
                       detail="owner mismatch must be rejected"))

    fixed_attr, _ = capture.check_attribution(
        {"task_id": TASK}, task_id=TASK, owner=OWNER, workspace_id=WORKSPACE,
        persisted={"owner_principal": OWNER, "workspace_id": "workspace_other"})
    legacy_attr, _ = capture.legacy_check_attribution({"task_id": TASK})
    cases.append(_case("wrong-workspace-attribution", fixed_fail=not fixed_attr, legacy_pass=legacy_attr,
                       detail="workspace mismatch must be rejected"))

    fixed_approval, _ = capture.derive_approval({"decision": "revoked", "execution_authorized": False})
    legacy_approval, _ = capture.legacy_derive_approval({"decision": "revoked", "execution_authorized": False})
    cases.append(_case("revoked-approval-not-authorized", fixed_fail=fixed_approval is None,
                       legacy_pass=legacy_approval is not None,
                       detail="a revoked approval must not authorize execution"))

    fixed_approval, _ = capture.derive_approval({"decision": "approved"})
    legacy_approval, _ = capture.legacy_derive_approval({"decision": "approved"})
    cases.append(_case("stale-approval-missing-authorization", fixed_fail=fixed_approval is None,
                       legacy_pass=legacy_approval is not None,
                       detail="approved without execution_authorized is not authorization"))

    return {
        "schema_version": "byq-v090-composite-research-capture-negatives.v1",
        "case_count": len(cases),
        "all_cases_pass": all(c["post_fix_failed"] and c["pre_fix_legacy_passed"] for c in cases),
        "all_pass": all(c["post_fix_failed"] and c["pre_fix_legacy_passed"] for c in cases),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = run()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
