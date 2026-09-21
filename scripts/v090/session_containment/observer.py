#!/usr/bin/env python3
"""Fail-able observer/verdict for BYQ session failure containment (ADR-0084).

Separation of concerns:

* ``format_valid`` -- the observations artifact is well formed, source-bound by
  digest, and every required scenario was independently re-derived.
* ``all_pass``     -- every REQUIRED scenario passed. A missing, NOT_RUN or
  blocked required scenario fails the verdict with a non-zero exit while keeping
  its status visible.

The observer does NOT trust the recorded ``verdict`` labels. For each scenario it
re-executes the contract function (classification, fencing, attempt ledger) or
re-checks the recorded adapter/loss invariants from the raw observations. The
pre-fix "trust the label" algorithm is kept only to prove, in ``--selfcheck``,
that defect-targeting negative controls would have been reported as PASS.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"

OBSERVATIONS_SCHEMA = "byq-v090-session-containment-observations.v1"
VERDICT_SCHEMA = "byq-v090-session-containment-verdict.v1"
NEGATIVE_SCHEMA = "byq-v090-session-containment-negative-controls.v1"

DEFECT_TARGETING_CONTROLS = (
    "executor-loss-fake-completed",
    "loss-cause-wrong",
    "preserved-false",
    "stale-generation-not-fenced",
    "duplicate-terminal-not-fenced",
    "terminal-reopen-not-fenced",
    "unknown-side-effect-auto-retry",
    "cancel-recoverable",
    "budget-blocks-bypassed",
    "auth-revoked-bypassed",
    "owner-mismatch-bypassed",
    "success-receipt-replayed",
    "attempt-lineage-forked",
    "concurrent-second-attempt",
    "negative-controls-trusted",
    "missing-provenance",
    "wrong-source-provenance",
    "provenance-digest-mismatch",
    "scenario-verdict-label-only",
)


class Failure(Exception):
    """Raised only for an unreadable contract/observations artifact."""


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _classify(inputs: dict):
    from packages.contracts.session_failure_containment import classify_recovery

    return classify_recovery(**inputs)


def _run_fencing_call(call: dict) -> bool:
    from packages.contracts import session_failure_containment as c

    name = call.get("function")
    kwargs = dict(call.get("kwargs") or {})
    if name == "assert_generation_fenced":
        function = c.assert_generation_fenced
    elif name == "assert_terminal_settlement":
        function = c.assert_terminal_settlement
        if isinstance(kwargs.get("settled"), dict):
            kwargs["settled"] = {int(key): value for key, value in kwargs["settled"].items()}
    elif name == "assert_fenced":
        function = c.assert_fenced
    else:
        raise ValueError("unsupported fencing function")
    try:
        function(**kwargs)
    except c.FencedWrite:
        return True
    return False


def _check_provenance(contract: dict, block: object, ctx: str, failures: list[str]) -> None:
    if not isinstance(block, dict):
        failures.append(f"{ctx}: missing provenance")
        return
    source = block.get("source")
    if source not in contract["provenance_allowed_sources"]:
        failures.append(f"{ctx}: provenance source is not contract-allowed")
    if not isinstance(block.get("observed_at"), (int, float)) or isinstance(block.get("observed_at"), bool):
        failures.append(f"{ctx}: provenance timestamp is missing")


def _check_classification(contract: dict, observed: object, expect: dict, ctx: str,
                          failures: list[str]) -> None:
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    inputs = observed.get("inputs")
    decision = observed.get("decision")
    if not isinstance(inputs, dict) or not isinstance(decision, dict):
        failures.append(f"{ctx}: classification inputs/decision missing")
        return
    derived = _classify(inputs).view()
    for field, value in expect.items():
        if derived.get(field) != value:
            failures.append(f"{ctx}: derived {field}={derived.get(field)!r} != contract {value!r}")
    if decision.get("status") != derived["status"] or decision.get("reason") != derived["reason"]:
        failures.append(f"{ctx}: recorded decision does not match the re-derived decision")
    if decision.get("auto_retry") != derived["auto_retry"]:
        failures.append(f"{ctx}: recorded auto_retry does not match the re-derived decision")


def _check_fencing(contract: dict, observed: object, expect: dict, ctx: str,
                   failures: list[str]) -> None:
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    call = observed.get("call")
    if not isinstance(call, dict):
        failures.append(f"{ctx}: fencing call missing")
        return
    try:
        raised = _run_fencing_call(call)
    except (ValueError, TypeError, KeyError) as exc:
        failures.append(f"{ctx}: fencing call is malformed: {exc}")
        return
    if raised is not bool(expect.get("fenced")):
        failures.append(f"{ctx}: fence raised={raised} != contract fenced={expect.get('fenced')}")


def _check_attempt(contract: dict, observed: object, expect: dict, ctx: str,
                   failures: list[str]) -> None:
    from packages.contracts.session_failure_containment import validate_attempt_ledger

    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    ledger = observed.get("ledger")
    if not isinstance(ledger, dict):
        failures.append(f"{ctx}: attempt ledger missing")
        return
    try:
        validate_attempt_ledger(ledger)
    except ValueError as exc:
        failures.append(f"{ctx}: attempt ledger invalid: {exc}")
        return
    rows = ledger["attempts"]
    if len(rows) != expect.get("attempts"):
        failures.append(f"{ctx}: attempts={len(rows)} != contract {expect.get('attempts')}")
    if expect.get("lineage_chained") and len(rows) >= 2:
        if rows[1]["previous_run_id"] != rows[0]["new_run_id"]:
            failures.append(f"{ctx}: recovery attempt lineage is not chained")
    if expect.get("auto_retry"):
        inputs = observed.get("inputs")
        if not isinstance(inputs, dict) or _classify(inputs).auto_retry is not True:
            failures.append(f"{ctx}: eligible attempt is not auto-retryable")
    if expect.get("conflict") and observed.get("conflict_raised") is not True:
        failures.append(f"{ctx}: concurrent recovery did not raise a conflict")


def _check_adapter_loss(contract: dict, observed: object, expect: dict, ctx: str,
                        failures: list[str]) -> None:
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    pattern = re.compile(contract["identity"]["run_pattern"])
    if observed.get("status") != expect.get("status"):
        failures.append(f"{ctx}: status={observed.get('status')!r} != contract {expect.get('status')!r}")
    if expect.get("loss_cause") is not None and observed.get("loss_cause") != expect.get("loss_cause"):
        failures.append(f"{ctx}: loss_cause mismatch")
    if expect.get("preserved") and observed.get("preserved") is not True:
        failures.append(f"{ctx}: business state was not attested preserved")
    if expect.get("history_unchanged") and observed.get("history_unchanged") is not True:
        failures.append(f"{ctx}: newer generation history was overwritten")
    run = observed.get("interrupted_run_id")
    if not isinstance(run, str) or pattern.fullmatch(run) is None:
        failures.append(f"{ctx}: interrupted run identity is not canonical")


def _check_meta(contract: dict, observed: object, expect: dict, ctx: str,
                failures: list[str]) -> None:
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    controls = observed.get("negative_controls")
    if not isinstance(controls, dict):
        failures.append(f"{ctx}: negative controls missing")
        return
    if controls.get("all_controls_rejected") is not True:
        failures.append(f"{ctx}: observer is not breakable by negative controls")
    if not isinstance(controls.get("control_count"), int) or controls["control_count"] < 1:
        failures.append(f"{ctx}: negative control set is empty")
    if not isinstance(controls.get("defect_targeting_count"), int) or controls["defect_targeting_count"] < 8:
        failures.append(f"{ctx}: too few defect-targeting controls")
    if expect.get("breakable") and controls.get("all_controls_rejected") is not True:
        failures.append(f"{ctx}: verdict is a PASS label, not a breakable verdict")


_CHECKERS = {
    "classification": _check_classification,
    "fencing": _check_fencing,
    "attempt": _check_attempt,
    "adapter_loss": _check_adapter_loss,
    "meta": _check_meta,
}


def _verify_provenance_digests(observations: dict, failures: list[str]) -> None:
    provenance = observations.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("source_sha256"), dict):
        failures.append("observations: missing source digest binding")
        return
    digests = provenance["source_sha256"]
    if not digests:
        failures.append("observations: empty source digest binding")
    for relative, expected in digests.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"provenance: missing source {relative}")
            continue
        if _digest(path) != expected:
            failures.append(f"provenance: source digest mismatch for {relative}")


def compute_verdict(contract: dict, observations: object, *, allow_unit_fixture: bool = False) -> dict:
    failures: list[str] = []
    coverage: list[str] = []
    results: list[dict] = []
    if not isinstance(observations, dict) or observations.get("schema_version") != OBSERVATIONS_SCHEMA:
        return {"schema_version": VERDICT_SCHEMA, "format_valid": False, "all_pass": False,
                "exit_code": 2, "failures": ["observations artifact has an invalid schema"],
                "coverage_failures": [], "scenarios": []}

    _verify_provenance_digests(observations, failures)
    scenarios = observations.get("scenarios")
    if not isinstance(scenarios, dict):
        return {"schema_version": VERDICT_SCHEMA, "format_valid": False, "all_pass": False,
                "exit_code": 2, "failures": ["observations.scenarios must be an object"],
                "coverage_failures": [], "scenarios": []}

    for spec in contract["scenarios"]:
        scenario_id = spec["id"]
        required = bool(spec.get("required"))
        if scenario_id not in scenarios:
            if required:
                coverage.append(f"missing required scenario: {scenario_id}")
            continue
        entry = scenarios[scenario_id]
        if not isinstance(entry, dict):
            failures.append(f"{scenario_id}: scenario entry must be an object")
            continue
        observed = entry.get("observed")
        _check_provenance(contract, entry.get("provenance"), scenario_id, failures)
        scenario_failures: list[str] = []
        checker = _CHECKERS.get(spec["kind"])
        if checker is None:
            scenario_failures.append(f"{scenario_id}: unsupported scenario kind {spec['kind']!r}")
        else:
            checker(contract, observed, spec.get("expect", {}), scenario_id, scenario_failures)
        verdict = "PASS" if not scenario_failures else "FAIL"
        results.append({"id": scenario_id, "required": required, "kind": spec["kind"],
                        "verdict": verdict, "failures": scenario_failures})
        failures.extend(scenario_failures)

    format_valid = not coverage and not any(
        failure.startswith("observations:") or failure.startswith("provenance:") for failure in failures)
    all_pass = format_valid and not failures
    return {
        "schema_version": VERDICT_SCHEMA,
        "format_valid": format_valid,
        "all_pass": all_pass,
        "exit_code": 0 if all_pass else 1,
        "failures": failures,
        "coverage_failures": coverage,
        "scenarios": results,
    }


def legacy_compute_verdict(contract: dict, observations: object) -> dict:
    """Pre-fix behaviour: trust the recorded verdict labels and presence only."""

    if not isinstance(observations, dict) or observations.get("schema_version") != OBSERVATIONS_SCHEMA:
        return {"all_pass": False}
    scenarios = observations.get("scenarios")
    if not isinstance(scenarios, dict):
        return {"all_pass": False}
    for spec in contract["scenarios"]:
        if not spec.get("required"):
            continue
        entry = scenarios.get(spec["id"])
        if not isinstance(entry, dict) or entry.get("verdict") != "PASS":
            return {"all_pass": False}
    return {"all_pass": True}


def valid_fixture(contract: dict) -> dict:
    """A synthetic, fully-passing observations artifact used for selfcheck."""

    run_a, run_b = "a" * 32, "b" * 32
    base = dict(cancelled=False, authorization_current=True, owner_matches=True,
                workspace_matches=True, budget_available=True, success_receipt_present=False,
                receipt_queryable=True, step_declared_idempotent=True,
                step_result_verifiable=True, attempt_in_progress=False, attempts_used=0,
                previous_run_id=run_a)
    scenarios = {}

    def add(scenario_id, observed, source="contract-pure-function"):
        scenarios[scenario_id] = {"verdict": "PASS", "observed": observed,
                                  "provenance": {"source": source, "observed_at": 1.0}}

    add("executor-loss-interrupted", {
        "status": "interrupted", "loss_cause": "executor-loss", "preserved": True,
        "history_unchanged": True, "interrupted_run_id": run_a},
        source="runtime-adapter-test-harness")
    add("late-success-no-overwrite", {
        "status": "interrupted", "loss_cause": "executor-loss", "preserved": True,
        "history_unchanged": True, "interrupted_run_id": run_a},
        source="runtime-adapter-test-harness")
    add("stale-generation-terminal-fenced", {"call": {"function": "assert_generation_fenced", "kwargs": {
        "authoritative_epoch": 2, "authoritative_generation": "g2",
        "write_epoch": 1, "write_generation": "g1"}}})
    add("duplicate-terminal-rejected", {"call": {"function": "assert_terminal_settlement", "kwargs": {
        "settled": {"1": "interrupted"}, "write_attempt": 1, "write_terminal": "interrupted"}}})
    add("terminal-reopen-rejected", {"call": {"function": "assert_terminal_settlement", "kwargs": {
        "settled": {"1": "interrupted"}, "write_attempt": 1, "write_terminal": "completed"}}})
    add("idempotent-no-receipt-one-attempt-lineage", {
        "ledger": {"schema_version": "session-recovery-attempts.v1", "session_id": "conversation_1",
                   "max_attempts": 3, "attempts": [{"attempt": 1, "previous_run_id": run_a,
                       "new_run_id": run_b, "generation": run_b,
                       "idempotency_key": "original-key-1", "state": "in_progress", "created_at": 1.0}]},
        "inputs": dict(base)},
        source="gateway-attempt-ledger")
    add("concurrent-recovery-one-attempt", {
        "ledger": {"schema_version": "session-recovery-attempts.v1", "session_id": "conversation_1",
                   "max_attempts": 3, "attempts": [{"attempt": 1, "previous_run_id": run_a,
                       "new_run_id": run_b, "generation": run_b,
                       "idempotency_key": "original-key-1", "state": "in_progress", "created_at": 1.0}]},
        "conflict_raised": True},
        source="gateway-attempt-ledger")
    add("success-receipt-not-replayed", {"inputs": {**base, "success_receipt_present": True},
        "decision": {"status": "settled", "reason": "existing_success_receipt", "auto_retry": False}})
    add("unknown-side-effect-paused", {"inputs": {**base, "step_declared_idempotent": False},
        "decision": {"status": "paused", "reason": "non_idempotent_step", "auto_retry": False}})
    add("cancel-blocks-recovery", {"inputs": {**base, "cancelled": True},
        "decision": {"status": "blocked", "reason": "cancelled", "auto_retry": False}})
    add("budget-exhausted-blocks", {"inputs": {**base, "budget_available": False},
        "decision": {"status": "blocked", "reason": "budget_exhausted", "auto_retry": False}})
    add("authorization-revoked-blocks", {"inputs": {**base, "authorization_current": False},
        "decision": {"status": "blocked", "reason": "authorization_revoked", "auto_retry": False}})
    add("owner-workspace-mismatch-blocks", {"inputs": {**base, "owner_matches": False},
        "decision": {"status": "blocked", "reason": "owner_workspace_mismatch", "auto_retry": False}})
    add("observer-breakable", {"negative_controls": {"all_controls_rejected": True,
        "control_count": len(DEFECT_TARGETING_CONTROLS), "defect_targeting_count": len(DEFECT_TARGETING_CONTROLS)}})
    return {"schema_version": OBSERVATIONS_SCHEMA,
            "provenance": {"source_sha256": _source_digests(), "harness": "selfcheck"},
            "scenarios": scenarios}


def _source_digests() -> dict:
    return {
        "packages/contracts/session_failure_containment.py":
            _digest(ROOT / "packages/contracts/session_failure_containment.py"),
        "services/runtime-adapter/app/containment.py":
            _digest(ROOT / "services/runtime-adapter/app/containment.py"),
        "services/gateway/app/session_containment.py":
            _digest(ROOT / "services/gateway/app/session_containment.py"),
    }


def _controls(contract: dict) -> list[tuple[str, dict]]:
    fixture = valid_fixture(contract)

    def mutate(name, change):
        value = copy.deepcopy(fixture)
        change(value)
        value["scenarios"][next(iter(value["scenarios"]))]["verdict"] = "PASS"
        return name, value

    def sc(value, scenario_id):
        return value["scenarios"][scenario_id]["observed"]

    def fork_lineage(value):
        observed = sc(value, "idempotent-no-receipt-one-attempt-lineage")
        first = {**observed["ledger"]["attempts"][0], "state": "failed"}
        second = {**first, "attempt": 2, "previous_run_id": "c" * 32,
                  "new_run_id": "d" * 32, "generation": "d" * 32, "state": "in_progress"}
        observed["ledger"]["attempts"] = [first, second]

    return [
        mutate("executor-loss-fake-completed", lambda v: sc(v, "executor-loss-interrupted").update(status="completed")),
        mutate("loss-cause-wrong", lambda v: sc(v, "executor-loss-interrupted").update(loss_cause="runtime-loss")),
        mutate("preserved-false", lambda v: sc(v, "executor-loss-interrupted").update(preserved=False)),
        mutate("stale-generation-not-fenced", lambda v: sc(v, "stale-generation-terminal-fenced").update(
            call={"function": "assert_generation_fenced", "kwargs": {
                "authoritative_epoch": 2, "authoritative_generation": "g2",
                "write_epoch": 2, "write_generation": "g2"}})),
        mutate("duplicate-terminal-not-fenced", lambda v: sc(v, "duplicate-terminal-rejected").update(
            call={"function": "assert_terminal_settlement", "kwargs": {
                "settled": {}, "write_attempt": 1, "write_terminal": "interrupted"}})),
        mutate("terminal-reopen-not-fenced", lambda v: sc(v, "terminal-reopen-rejected").update(
            call={"function": "assert_terminal_settlement", "kwargs": {
                "settled": {"1": "interrupted"}, "write_attempt": 2, "write_terminal": "completed"}})),
        mutate("unknown-side-effect-auto-retry", lambda v: sc(v, "unknown-side-effect-paused")["inputs"].update(
            step_declared_idempotent=True)),
        mutate("cancel-recoverable", lambda v: sc(v, "cancel-blocks-recovery")["inputs"].update(cancelled=False)),
        mutate("budget-blocks-bypassed", lambda v: sc(v, "budget-exhausted-blocks")["inputs"].update(budget_available=True)),
        mutate("auth-revoked-bypassed", lambda v: sc(v, "authorization-revoked-blocks")["inputs"].update(authorization_current=True)),
        mutate("owner-mismatch-bypassed", lambda v: sc(v, "owner-workspace-mismatch-blocks")["inputs"].update(owner_matches=True)),
        mutate("success-receipt-replayed", lambda v: sc(v, "success-receipt-not-replayed")["inputs"].update(
            success_receipt_present=False)),
        mutate("attempt-lineage-forked", lambda v: fork_lineage(v)),
        mutate("concurrent-second-attempt", lambda v: sc(v, "concurrent-recovery-one-attempt").update(
            conflict_raised=False)),
        mutate("negative-controls-trusted", lambda v: sc(v, "observer-breakable")["negative_controls"].update(
            all_controls_rejected=False)),
        mutate("missing-provenance", lambda v: v["scenarios"]["executor-loss-interrupted"].pop("provenance")),
        mutate("wrong-source-provenance", lambda v: v["scenarios"]["executor-loss-interrupted"]["provenance"].update(
            source="raw-dsh-event")),
        mutate("provenance-digest-mismatch", lambda v: v["provenance"]["source_sha256"].update(
            {"packages/contracts/session_failure_containment.py": "sha256:" + "0" * 64})),
        mutate("dropped-scenario", lambda v: v["scenarios"].pop("cancel-blocks-recovery")),
        mutate("scenario-verdict-label-only", lambda v: sc(v, "unknown-side-effect-paused").update(
            decision={"status": "eligible", "reason": "idempotent_result_verifiable", "auto_retry": True})),
    ]


def run_selfcheck(contract: dict) -> dict:
    baseline = compute_verdict(contract, valid_fixture(contract))
    controls = []
    for name, observations in _controls(contract):
        verdict = compute_verdict(contract, observations)
        legacy = legacy_compute_verdict(contract, observations)
        controls.append({
            "name": name,
            "observed_all_pass": verdict["all_pass"],
            "observed_exit_code": verdict["exit_code"],
            "first_failure": (verdict["failures"] or verdict["coverage_failures"] or ["<none>"])[0],
            "pre_fix_legacy_all_pass": legacy["all_pass"],
            "defect_targeting": name in DEFECT_TARGETING_CONTROLS,
        })
    targeting = [control for control in controls if control["defect_targeting"]]
    return {
        "schema_version": NEGATIVE_SCHEMA,
        "baseline_all_pass": baseline["all_pass"],
        "control_count": len(controls),
        "all_controls_pass": all(not c["observed_all_pass"] and c["observed_exit_code"] == 1
                                 for c in controls),
        "defect_targeting_pre_fix_passed": bool(targeting) and all(
            c["pre_fix_legacy_all_pass"] and not c["observed_all_pass"] for c in targeting),
        "defect_targeting_count": len(targeting),
        "controls": controls,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.selfcheck:
        result = run_selfcheck(contract)
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(text)
        return 0 if (result["baseline_all_pass"] and result["all_controls_pass"]
                     and result["defect_targeting_pre_fix_passed"]) else 1

    if args.observations is None:
        parser.error("--observations is required unless --selfcheck is used")
    verdict = compute_verdict(contract, _load(args.observations))
    text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return verdict["exit_code"]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as error:
        print(json.dumps({"error": str(error), "exit_code": 2}), file=sys.stderr)
        sys.exit(2)
