#!/usr/bin/env python3
"""Fail-able observer for the v090 REAL business-recovery acceptance.

It never trusts a scenario's ``result`` label: every verdict is re-derived from
the RAW observations (containment identity, process identity, target identity,
authoritative counts, journal events, closed refusal reasons). ``--selfcheck``
mutates a deep copy of the observations with defect-targeting negative controls
and requires the observer to reject each one, so a label-only or not-implemented
result cannot pass.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_OBSERVATIONS = ROOT / "docs/evidence/v090-business-recovery-acceptance/observations.v1.json"
DEFAULT_OUT = ROOT / "docs/evidence/v090-business-recovery-acceptance/verdict.v1.json"
DEFAULT_NEGATIVES = ROOT / "docs/evidence/v090-business-recovery-acceptance/negative-controls.v1.json"
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")
ATTEMPT = re.compile(r"recovery_[0-9a-f]{32}")

REQUIRED = [
    "real-executor-loss-and-recovery",
    "negative-forged-loss-run",
    "negative-snapshot-change-for-existing-trigger",
    "negative-unknown-cost-paused",
    "negative-below-model-call-floor",
    "negative-ordinal-cap",
    "negative-stale-target-epoch",
    "negative-recovery-new-key",
    "negative-recovery-cross-task",
]
CLOSED_REASONS = {
    "negative-forged-loss-run": ("blocked", "lost_run_not_authoritative"),
    "negative-snapshot-change-for-existing-trigger": ("blocked", "snapshot_changed_for_existing_trigger"),
    "negative-unknown-cost-paused": ("paused", "unknown_attempt_charge"),
    "negative-below-model-call-floor": ("blocked", "below_model_call_floor"),
    "negative-ordinal-cap": ("blocked", "ordinal_cap"),
}


def _refusal(scenario: dict, expected_status: int, expected_reason: str | None) -> list[str]:
    failures: list[str] = []
    observed = scenario.get("observed") or {}
    if observed.get("status") != expected_status:
        failures.append(f"expected status {expected_status}, got {observed.get('status')}")
    body = observed.get("body")
    if expected_reason is not None:
        detail = body.get("detail") if isinstance(body, dict) else None
        recovery = body.get("recovery") if isinstance(body, dict) else None
        reason = (detail or {}).get("reason") if isinstance(detail, dict) else None
        if reason is None and isinstance(recovery, dict):
            reason = recovery.get("reason")
        if reason != expected_reason:
            failures.append(f"expected reason {expected_reason}, got {reason}")
    return failures


def verify_happy(scenario: dict) -> list[str]:
    failures: list[str] = []
    o = scenario.get("observed") or {}
    lost, target = o.get("lost_run_id"), o.get("target_run_id")
    attempt = o.get("recovery_attempt") or {}
    containment = o.get("containment") or {}
    latest = containment.get("latest") or {}
    receipt = o.get("adapter_receipt") or {}
    if not isinstance(lost, str) or not HEX32.fullmatch(lost):
        failures.append("lost run is not a canonical 32-hex identity")
    if not isinstance(target, str) or not HEX32.fullmatch(target):
        failures.append("target run is not a canonical 32-hex identity")
    if target == lost:
        failures.append("recovery target run equals the lost run")
    if not ATTEMPT.fullmatch(str(attempt.get("attempt_key", ""))):
        failures.append("attempt key is not a canonical recovery attempt")
    if attempt.get("ordinal") != 1:
        failures.append("first fenced loss did not allocate ordinal 1")
    if containment.get("contained") is not True:
        failures.append("no durable containment was recorded")
    if latest.get("interrupted_run_id") != lost:
        failures.append("containment does not mark the exact interrupted run")
    if latest.get("loss_cause") != "executor-loss":
        failures.append("containment loss cause is not executor-loss")
    if o.get("adapter_pid_before") == o.get("adapter_pid_after"):
        failures.append("the adapter OS process was not really terminated")
    if not (isinstance(o.get("charged_tokens"), int) and o["charged_tokens"] > 0):
        failures.append("no exact guard charge was admitted for the lost run")
    if attempt.get("target_generation") == attempt.get("interrupted_generation"):
        failures.append("recovery reused the interrupted generation")
    if not isinstance(attempt.get("target_executor_epoch"), int) or attempt["target_executor_epoch"] < 1:
        failures.append("target executor epoch is not a live positive integer")
    if receipt.get("status") != "settled" or receipt.get("run_id") != target \
            or receipt.get("outcome") != "completed":
        failures.append("adapter did not settle the recovery run as completed")
    started = o.get("journal_started") or []
    if started.count(target) != 1 or started.count(lost) != 1:
        failures.append("journal does not show exactly one lost and one recovery generation")
    if (o.get("business_counts_before") or {}) != (o.get("business_counts_after") or {}):
        failures.append("a read-only recovery changed authoritative business row counts")
    if (o.get("journal_started_after_retry") or []) != started:
        failures.append("the retry created a second generation")
    if (o.get("retry_prompt") or {}).get("run_id") != target:
        failures.append("the retry did not reuse the exact accepted run")
    retry_attempts = ((o.get("retry_dispatch") or {}).get("recovery_attempt"))
    if retry_attempts is not None and retry_attempts.get("attempt_key") != attempt.get("attempt_key"):
        failures.append("a repeated dispatch changed the attempt key")
    return failures


def verify_negative(scenario: dict, expected_status: int, expected_reason: str | None) -> list[str]:
    failures = _refusal(scenario, expected_status, expected_reason)
    o = scenario.get("observed") or {}
    body = o.get("body")
    recovery = body.get("recovery") if isinstance(body, dict) else None
    if isinstance(recovery, dict) and recovery.get("status") == "eligible":
        failures.append("a fail-closed negative returned eligible")
    return failures


def verify(observations: object) -> dict:
    failures: list[str] = []
    if not isinstance(observations, dict) or observations.get("schema_version") != \
            "byq-v090-business-recovery-acceptance-observations.v1":
        return {"format_valid": False, "all_pass": False,
                "failures": ["invalid observations schema"], "scenarios": {}}
    scenarios = observations.get("scenarios")
    if not isinstance(scenarios, dict):
        return {"format_valid": False, "all_pass": False,
                "failures": ["missing scenarios"], "scenarios": {}}
    per_scenario: dict[str, dict] = {}
    for scenario_id in REQUIRED:
        scenario = scenarios.get(scenario_id)
        if not isinstance(scenario, dict):
            failures.append(f"{scenario_id}: missing")
            per_scenario[scenario_id] = {"result": "MISSING", "derived_failures": ["missing"]}
            continue
        provenance = scenario.get("provenance")
        if not isinstance(provenance, dict) or not provenance.get("source"):
            failures.append(f"{scenario_id}: missing provenance")
        if scenario.get("result") == "BLOCKED":
            reason = scenario.get("not_run_reason")
            derived = [] if reason else ["blocked without a reason"]
        elif scenario_id == "real-executor-loss-and-recovery":
            derived = verify_happy(scenario)
        elif scenario_id in CLOSED_REASONS:
            # Backend dispatch refusals are HTTP 200 with dispatch=false + recovery.
            status, reason = CLOSED_REASONS[scenario_id]
            derived = _dispatch_refusal(scenario, status, reason)
        elif scenario_id == "negative-stale-target-epoch":
            derived = verify_negative(scenario, 409, None)
        else:
            derived = verify_negative(scenario, 409, "recovery_envelope_violation")
        per_scenario[scenario_id] = {"result": scenario.get("result"), "derived_failures": derived}
        if derived:
            failures.extend(f"{scenario_id}: {item}" for item in derived)
    format_valid = all(not item.startswith(("missing scenarios", "invalid observations schema"))
                       for item in failures)
    all_pass = not failures and all(entry["result"] == "PASS" for entry in per_scenario.values())
    return {"schema_version": "byq-v090-business-recovery-acceptance-verdict.v1",
            "format_valid": format_valid, "all_pass": all_pass, "failures": failures,
            "scenarios": per_scenario, "required_count": len(REQUIRED)}


def _dispatch_refusal(scenario: dict, status: str, reason: str) -> list[str]:
    observed = scenario.get("observed") or {}
    failures: list[str] = []
    if observed.get("dispatch") is not False:
        failures.append("backend dispatch was not refused")
    recovery = observed.get("recovery")
    if not isinstance(recovery, dict) or recovery.get("status") != status or recovery.get("reason") != reason:
        failures.append(f"expected {status}/{reason}, got {recovery}")
    return failures


def _mutations(base: dict) -> list[tuple[str, bool, dict]]:
    """Return ``(name, expect_format_invalid, observations)`` controls."""

    controls: list[tuple[str, bool, dict]] = []

    def add(name, mutate, *, format_invalid=False):
        mutated = copy.deepcopy(base)
        mutate(mutated)
        controls.append((name, format_invalid, mutated))

    add("label-only-pass", lambda d: d["scenarios"]["real-executor-loss-and-recovery"].update(
        observed={}, result="PASS"))
    add("target-equals-lost", lambda d: d["scenarios"]["real-executor-loss-and-recovery"]["observed"].update(
        target_run_id=d["scenarios"]["real-executor-loss-and-recovery"]["observed"]["lost_run_id"]))
    add("containment-wrong-run", lambda d: d["scenarios"]["real-executor-loss-and-recovery"]["observed"][
        "containment"]["latest"].update(interrupted_run_id="f" * 32))
    add("no-real-process-termination", lambda d: d["scenarios"]["real-executor-loss-and-recovery"]["observed"].update(
        adapter_pid_after=d["scenarios"]["real-executor-loss-and-recovery"]["observed"]["adapter_pid_before"]))
    add("no-guard-charge", lambda d: d["scenarios"]["real-executor-loss-and-recovery"]["observed"].update(
        charged_tokens=0))
    add("read-only-recovery-wrote-business", lambda d: d["scenarios"]["real-executor-loss-and-recovery"][
        "observed"]["business_counts_after"].update(artifacts=99))
    add("retry-created-second-generation", lambda d: d["scenarios"]["real-executor-loss-and-recovery"][
        "observed"]["journal_started_after_retry"].append("9" * 32))
    add("retry-changed-run", lambda d: d["scenarios"]["real-executor-loss-and-recovery"]["observed"][
        "retry_prompt"].update(run_id="9" * 32))
    add("adapter-not-settled", lambda d: d["scenarios"]["real-executor-loss-and-recovery"]["observed"][
        "adapter_receipt"].update(status="accepted"))
    add("forged-not-refused", lambda d: d["scenarios"]["negative-forged-loss-run"]["observed"].update(
        dispatch=True, recovery={"status": "eligible", "reason": "recovery_attempt"}))
    add("forged-wrong-reason", lambda d: d["scenarios"]["negative-forged-loss-run"]["observed"]["recovery"].update(
        reason="something_else"))
    add("snapshot-change-not-refused", lambda d: d["scenarios"][
        "negative-snapshot-change-for-existing-trigger"]["observed"].update(dispatch=True))
    add("unknown-cost-not-paused", lambda d: d["scenarios"]["negative-unknown-cost-paused"]["observed"].update(
        dispatch=True, recovery={"status": "eligible", "reason": "recovery_attempt"}))
    add("floor-not-blocked", lambda d: d["scenarios"]["negative-below-model-call-floor"]["observed"].update(
        recovery={"status": "eligible", "reason": "known_headroom"}))
    add("ordinal-cap-not-blocked", lambda d: d["scenarios"]["negative-ordinal-cap"]["observed"].update(
        dispatch=True, recovery={"status": "eligible", "reason": "recovery_attempt"}))
    add("stale-target-not-refused", lambda d: d["scenarios"]["negative-stale-target-epoch"]["observed"].update(
        status=200))
    add("new-key-not-refused", lambda d: d["scenarios"]["negative-recovery-new-key"]["observed"].update(
        status=201, body={"detail": {"state": "claimed"}}))
    add("cross-task-not-refused", lambda d: d["scenarios"]["negative-recovery-cross-task"]["observed"]["body"][
        "detail"].update(reason="ok"))
    add("missing-provenance", lambda d: d["scenarios"]["real-executor-loss-and-recovery"].pop("provenance"))
    add("missing-required-scenario", lambda d: d["scenarios"].pop("negative-ordinal-cap"))
    return controls


def run_selfcheck(base: dict) -> dict:
    results = []
    for name, format_invalid, mutated in _mutations(base):
        verdict = verify(mutated)
        rejected = (not verdict["format_valid"]) if format_invalid else (not verdict["all_pass"])
        results.append({"control": name, "rejected": rejected, "format_valid": verdict["format_valid"],
                        "all_pass": verdict["all_pass"]})
    return {"schema_version": "byq-v090-business-recovery-acceptance-negative-controls.v1",
            "control_count": len(results), "defect_targeting_count": len(results),
            "all_controls_rejected": all(item["rejected"] for item in results), "controls": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--negatives", type=Path, default=DEFAULT_NEGATIVES)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)
    base = json.loads(args.observations.read_text(encoding="utf-8"))
    if args.selfcheck:
        controls = run_selfcheck(base)
        args.negatives.write_text(json.dumps(controls, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"selfcheck": controls["all_controls_rejected"],
                          "control_count": controls["control_count"]}, sort_keys=True))
        return 0 if controls["all_controls_rejected"] else 1
    verdict = verify(base)
    args.out.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"format_valid": verdict["format_valid"], "all_pass": verdict["all_pass"],
                      "failures": len(verdict["failures"])}, sort_keys=True))
    return 0 if verdict["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
