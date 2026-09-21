#!/usr/bin/env python3
"""Fail-able observer/verdict for BYQ session failure containment (ADR-0084).

Separation of concerns:

* ``format_valid`` -- the observations artifact is well formed, source-bound by
  digest, and every required scenario was independently re-derived.
* ``all_pass``     -- every REQUIRED scenario passed.

The observer does NOT trust recorded labels. For each scenario it re-executes the
contract function (classification, fencing, loss evidence, preservation) or
re-checks the recorded adapter/loss invariants and real before/after state. The
pre-fix "trust the label" algorithm is kept only to prove, in ``--selfcheck``,
that defect-targeting negative controls would have been reported as PASS.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"

OBSERVATIONS_SCHEMA = "byq-v090-session-containment-observations.v2"
VERDICT_SCHEMA = "byq-v090-session-containment-verdict.v2"
NEGATIVE_SCHEMA = "byq-v090-session-containment-negative-controls.v2"

DEFECT_TARGETING_CONTROLS = (
    "executor-loss-fake-completed",
    "loss-cause-wrong",
    "before-after-diverged",
    "ordinary-failed-marked-interrupted",
    "mismatched-run-marked-interrupted",
    "mismatched-trace-marked-interrupted",
    "missing-summary-session-marked-interrupted",
    "missing-terminal-run-marked-interrupted",
    "invalid-terminal-run-marked-interrupted",
    "stale-generation-not-fenced",
    "duplicate-terminal-not-fenced",
    "terminal-reopen-not-fenced",
    "authority-unavailable-allowed",
    "unknown-side-effect-auto-retry",
    "cancel-recoverable",
    "budget-blocks-bypassed",
    "auth-revoked-bypassed",
    "owner-mismatch-bypassed",
    "success-receipt-replayed",
    "preservation-constant-claim",
    "preservation-boundary-self-verified",
    "endpoint-source-mismatch",
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


def _gateway_module():
    spec = importlib.util.spec_from_file_location(
        "byq_observer_gateway_session_containment",
        ROOT / "services/gateway/app/session_containment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    if block.get("source") not in contract["provenance_allowed_sources"]:
        failures.append(f"{ctx}: provenance source is not contract-allowed")
    if not isinstance(block.get("observed_at"), (int, float)) or isinstance(block.get("observed_at"), bool):
        failures.append(f"{ctx}: provenance timestamp is missing")


def _check_classification(contract, observed, expect, ctx, failures):
    if not isinstance(observed, dict) or not isinstance(observed.get("inputs"), dict):
        failures.append(f"{ctx}: classification inputs missing")
        return
    decision = observed.get("decision")
    if not isinstance(decision, dict):
        failures.append(f"{ctx}: classification decision missing")
        return
    derived = _classify(observed["inputs"]).view()
    for field, value in expect.items():
        if derived.get(field) != value:
            failures.append(f"{ctx}: derived {field}={derived.get(field)!r} != contract {value!r}")
    if decision.get("status") != derived["status"] or decision.get("reason") != derived["reason"]:
        failures.append(f"{ctx}: recorded decision does not match the re-derived decision")
    if decision.get("auto_retry") != derived["auto_retry"]:
        failures.append(f"{ctx}: recorded auto_retry does not match the re-derived decision")


def _check_fencing(contract, observed, expect, ctx, failures):
    if not isinstance(observed, dict) or not isinstance(observed.get("call"), dict):
        failures.append(f"{ctx}: fencing call missing")
        return
    try:
        raised = _run_fencing_call(observed["call"])
    except (ValueError, TypeError, KeyError) as exc:
        failures.append(f"{ctx}: fencing call is malformed: {exc}")
        return
    if raised is not bool(expect.get("fenced")):
        failures.append(f"{ctx}: fence raised={raised} != contract fenced={expect.get('fenced')}")


def _check_loss_evidence(contract, observed, expect, ctx, failures):
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    for field in ("events", "session_id", "trace_id"):
        if field not in observed:
            failures.append(f"{ctx}: missing {field}")
            return
    try:
        loss = _gateway_module().loss_from_evidence(
            observed["events"], observed["session_id"], observed["trace_id"],
            observed.get("adapter_containment"))
    except (ValueError, TypeError, KeyError) as exc:
        failures.append(f"{ctx}: loss evidence is malformed: {exc}")
        return
    if loss["status"] != expect.get("status"):
        failures.append(f"{ctx}: status={loss['status']!r} != contract {expect.get('status')!r}")
    if loss["interrupted"] is not bool(expect.get("interrupted")):
        failures.append(f"{ctx}: interrupted={loss['interrupted']} != contract {expect.get('interrupted')}")


def _check_adapter_loss(contract, observed, expect, ctx, failures):
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    pattern = re.compile(contract["identity"]["run_pattern"])
    if observed.get("status") != expect.get("status"):
        failures.append(f"{ctx}: status={observed.get('status')!r} != contract {expect.get('status')!r}")
    if expect.get("loss_cause") is not None and observed.get("loss_cause") != expect.get("loss_cause"):
        failures.append(f"{ctx}: loss_cause mismatch")
    if expect.get("before_after_equal") and observed.get("before") != observed.get("after"):
        failures.append(f"{ctx}: real before/after state diverged")
    if not observed.get("before"):
        failures.append(f"{ctx}: no real before state captured")
    if observed.get("history_unchanged") is not True:
        failures.append(f"{ctx}: newer generation history was overwritten")
    run = observed.get("interrupted_run_id")
    if not isinstance(run, str) or pattern.fullmatch(run) is None:
        failures.append(f"{ctx}: interrupted run identity is not canonical")
    if observed.get("trace_id") != observed.get("expected_trace_id"):
        failures.append(f"{ctx}: containment trace binding does not match the session trace")


def _check_preservation(contract, observed, expect, ctx, failures):
    from packages.contracts import session_failure_containment as c

    if not isinstance(observed, dict):
        failures.append(f"{ctx}: missing observation")
        return
    if observed.get("before") != observed.get("after"):
        failures.append(f"{ctx}: real before/after preservation state diverged")
    if not observed.get("before"):
        failures.append(f"{ctx}: no real before state captured")
    projection = observed.get("preservation")
    try:
        c.validate_preservation(projection)
    except ValueError as exc:
        failures.append(f"{ctx}: preservation projection invalid: {exc}")
        return
    if projection["boundary_verified"] is not False:
        failures.append(f"{ctx}: boundary invariant was self-verified")
    states = projection["states"]
    if all(state == "preserved" for state in states.values()):
        failures.append(f"{ctx}: preservation is a constant all-preserved claim")
    if states.get("durable_job") not in {"unknown", "unavailable"}:
        failures.append(f"{ctx}: durable_job was claimed without an authoritative source")


def _recovery_endpoint_body() -> str:
    source = (ROOT / "services/gateway/app/main.py").read_text(encoding="utf-8")
    match = re.search(r"^def get_recovery_classification\(.*?(?=^@app\.|\Z)",
                      source, flags=re.DOTALL | re.MULTILINE)
    return match.group(0) if match else ""


def _check_no_submit(contract, observed, expect, ctx, failures):
    body = _recovery_endpoint_body()
    if not body:
        failures.append(f"{ctx}: recovery endpoint not found")
        return
    if "_adapter_post" in body:
        failures.append(f"{ctx}: recovery endpoint can submit an adapter prompt")
    for marker in ("/prompt", "_runtime_recovery_payload", "idempotency_key"):
        if marker in body:
            failures.append(f"{ctx}: recovery endpoint references a prompt submission")
    if '"submitted": False' not in body:
        failures.append(f"{ctx}: recovery endpoint does not declare no submission")
    if isinstance(observed, dict) and observed.get("source_sha256") != _digest(
            ROOT / "services/gateway/app/main.py"):
        failures.append(f"{ctx}: observed source digest does not match the current endpoint")


def _check_meta(contract, observed, expect, ctx, failures):
    if not isinstance(observed, dict) or not isinstance(observed.get("negative_controls"), dict):
        failures.append(f"{ctx}: negative controls missing")
        return
    controls = observed["negative_controls"]
    if controls.get("all_controls_rejected") is not True:
        failures.append(f"{ctx}: observer is not breakable by negative controls")
    if not isinstance(controls.get("control_count"), int) or controls["control_count"] < 1:
        failures.append(f"{ctx}: negative control set is empty")
    if not isinstance(controls.get("defect_targeting_count"), int) or controls["defect_targeting_count"] < 8:
        failures.append(f"{ctx}: too few defect-targeting controls")


_CHECKERS = {
    "classification": _check_classification,
    "fencing": _check_fencing,
    "loss_evidence": _check_loss_evidence,
    "adapter_loss": _check_adapter_loss,
    "preservation": _check_preservation,
    "no_submit": _check_no_submit,
    "meta": _check_meta,
}


def _source_digests() -> dict:
    return {
        "packages/contracts/session_failure_containment.py":
            _digest(ROOT / "packages/contracts/session_failure_containment.py"),
        "services/runtime-adapter/app/containment.py":
            _digest(ROOT / "services/runtime-adapter/app/containment.py"),
        "services/runtime-adapter/app/runtime.py":
            _digest(ROOT / "services/runtime-adapter/app/runtime.py"),
        "services/gateway/app/session_containment.py":
            _digest(ROOT / "services/gateway/app/session_containment.py"),
        "services/gateway/app/main.py":
            _digest(ROOT / "services/gateway/app/main.py"),
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
        _check_provenance(contract, entry.get("provenance"), scenario_id, failures)
        scenario_failures: list[str] = []
        checker = _CHECKERS.get(spec["kind"])
        if checker is None:
            scenario_failures.append(f"{scenario_id}: unsupported scenario kind {spec['kind']!r}")
        else:
            checker(contract, entry.get("observed"), spec.get("expect", {}), scenario_id, scenario_failures)
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


def _base_inputs(**overrides):
    values = dict(cancelled=False, authorization_current=True, owner_matches=True,
                  workspace_matches=True, budget_available=True, success_receipt_present=False,
                  receipt_queryable=True, step_declared_idempotent=True,
                  step_result_verifiable=True, previous_run_id="a" * 32)
    values.update(overrides)
    return values


def valid_fixture(contract: dict) -> dict:
    run_a, run_b = "a" * 32, "b" * 32
    scenarios = {}

    def add(scenario_id, observed, source="contract-pure-function"):
        scenarios[scenario_id] = {"verdict": "PASS", "observed": observed,
                                  "provenance": {"source": source, "observed_at": 1.0}}

    before = {"session.started": 1, "session.closed": 1, "prompt_receipts": 1}
    events = [{"trace_id": "trace-1", "session_id": "runtime-1", "sequence": 1,
               "timestamp": "t", "kind": "session.started", "source": "runtime-adapter",
               "payload": {"run_id": run_a}},
              {"trace_id": "trace-1", "session_id": "runtime-1", "sequence": 2,
               "timestamp": "t", "kind": "session.failed", "source": "runtime-adapter",
               "payload": {"run_id": run_a}}]
    match = {"schema_version": "session-containment-summary.v1", "session_id": "runtime-1",
             "contained": True, "latest": {"trace_id": "trace-1", "loss_cause": "executor-loss",
             "interrupted_run_id": run_a, "interrupted_generation": "g", "executor_epoch": 1}}
    add("executor-loss-interrupted", {
        "status": "interrupted", "loss_cause": "executor-loss", "before": before, "after": before,
        "history_unchanged": True, "interrupted_run_id": run_a, "trace_id": "trace-1",
        "expected_trace_id": "trace-1"}, source="runtime-adapter-test-harness")
    add("late-success-no-overwrite", {
        "status": "interrupted", "loss_cause": "executor-loss", "before": before, "after": before,
        "history_unchanged": True, "interrupted_run_id": run_a, "trace_id": "trace-1",
        "expected_trace_id": "trace-1"}, source="runtime-adapter-test-harness")
    add("ordinary-failed-not-interrupted",
        {"events": events, "session_id": "runtime-1", "trace_id": "trace-1",
         "adapter_containment": {"schema_version": "s", "session_id": "runtime-1", "contained": True,
             "latest": {"trace_id": "trace-1", "loss_cause": "executor-loss",
                        "interrupted_run_id": run_b, "interrupted_generation": "g", "executor_epoch": 1}}},
        source="gateway-session-containment")
    add("mismatched-run-not-interrupted",
        {"events": events, "session_id": "runtime-1", "trace_id": "trace-1",
         "adapter_containment": {"schema_version": "s", "session_id": "runtime-1", "contained": True,
             "latest": {"trace_id": "trace-1", "loss_cause": "executor-loss",
                        "interrupted_run_id": run_b, "interrupted_generation": "g", "executor_epoch": 1}}},
        source="gateway-session-containment")
    add("mismatched-trace-not-interrupted",
        {"events": events, "session_id": "runtime-1", "trace_id": "trace-1",
         "adapter_containment": {"schema_version": "s", "session_id": "runtime-1", "contained": True,
             "latest": {"trace_id": "trace-other", "loss_cause": "executor-loss",
                        "interrupted_run_id": run_a, "interrupted_generation": "g", "executor_epoch": 1}}},
        source="gateway-session-containment")
    add("missing-summary-session-not-interrupted",
        {"events": events, "session_id": "runtime-1", "trace_id": "trace-1",
         "adapter_containment": {"schema_version": "s", "contained": True,
             "latest": {"trace_id": "trace-1", "loss_cause": "executor-loss",
                        "interrupted_run_id": run_a, "interrupted_generation": "g", "executor_epoch": 1}}},
        source="gateway-session-containment")
    add("missing-terminal-run-not-interrupted",
        {"events": [events[0], {**events[1], "payload": {}}], "session_id": "runtime-1",
         "trace_id": "trace-1",
         "adapter_containment": {"schema_version": "s", "session_id": "runtime-1", "contained": True,
             "latest": {"trace_id": "trace-1", "loss_cause": "executor-loss",
                        "interrupted_run_id": run_a, "interrupted_generation": "g", "executor_epoch": 1}}},
        source="gateway-session-containment")
    add("invalid-terminal-run-not-interrupted",
        {"events": [events[0], {**events[1], "payload": {"run_id": "not-a-run"}}],
         "session_id": "runtime-1", "trace_id": "trace-1",
         "adapter_containment": {"schema_version": "s", "session_id": "runtime-1", "contained": True,
             "latest": {"trace_id": "trace-1", "loss_cause": "executor-loss",
                        "interrupted_run_id": run_a, "interrupted_generation": "g", "executor_epoch": 1}}},
        source="gateway-session-containment")
    add("cancelled-not-interrupted",
        {"events": [{**events[0]}, {**events[1], "kind": "session.cancelled"}],
         "session_id": "runtime-1", "trace_id": "trace-1", "adapter_containment": None},
        source="gateway-session-containment")
    add("stale-generation-terminal-fenced", {"call": {"function": "assert_generation_fenced", "kwargs": {
        "authoritative_epoch": 2, "authoritative_generation": "g2",
        "write_epoch": 1, "write_generation": "g1"}}})
    add("duplicate-terminal-rejected", {"call": {"function": "assert_terminal_settlement", "kwargs": {
        "settled": {"1": "interrupted"}, "write_attempt": 1, "write_terminal": "interrupted"}}})
    add("terminal-reopen-rejected", {"call": {"function": "assert_terminal_settlement", "kwargs": {
        "settled": {"1": "interrupted"}, "write_attempt": 1, "write_terminal": "completed"}}})
    for scenario_id, inputs in (
        ("authority-unavailable-pauses", _base_inputs(budget_available=None)),
        ("unknown-side-effect-paused", _base_inputs(step_declared_idempotent=False)),
        ("success-receipt-not-replayed", _base_inputs(success_receipt_present=True)),
        ("cancel-blocks-recovery", _base_inputs(cancelled=True)),
        ("budget-exhausted-blocks", _base_inputs(budget_available=False)),
        ("authorization-revoked-blocks", _base_inputs(authorization_current=False)),
        ("owner-workspace-mismatch-blocks", _base_inputs(owner_matches=False)),
    ):
        add(scenario_id, {"inputs": inputs,
                          "decision": {k: _classify(inputs).view()[k]
                                       for k in ("status", "reason", "auto_retry")}})
    from packages.contracts import session_failure_containment as c
    states = {field: "unknown" for field in c.PRESERVED_FIELDS}
    states["conversation"] = "preserved"
    states["workflow_trace"] = "preserved"
    add("preservation-not-constant", {
        "before": before, "after": before,
        "preservation": {"schema_version": c.PRESERVATION_SCHEMA_VERSION, "states": states,
                         "boundary_invariant": c.BOUNDARY_INVARIANT, "boundary_verified": False,
                         "sources": {"conversation": "backend-product-catalog",
                                     "workflow_trace": "gateway-trace-store"}}})
    add("recovery-endpoint-never-submits", {
        "source_sha256": _digest(ROOT / "services/gateway/app/main.py")})
    add("observer-breakable", {"negative_controls": {
        "all_controls_rejected": True, "control_count": len(DEFECT_TARGETING_CONTROLS),
        "defect_targeting_count": len(DEFECT_TARGETING_CONTROLS)}})
    return {"schema_version": OBSERVATIONS_SCHEMA,
            "provenance": {"source_sha256": _source_digests(), "harness": "selfcheck"},
            "scenarios": scenarios}


def _controls(contract: dict) -> list[tuple[str, dict]]:
    fixture = valid_fixture(contract)

    def mutate(name, change):
        value = copy.deepcopy(fixture)
        change(value)
        for scenario in value["scenarios"].values():
            scenario["verdict"] = "PASS"
        return name, value

    def sc(value, scenario_id):
        return value["scenarios"][scenario_id]["observed"]

    return [
        mutate("executor-loss-fake-completed", lambda v: sc(v, "executor-loss-interrupted").update(status="completed")),
        mutate("loss-cause-wrong", lambda v: sc(v, "executor-loss-interrupted").update(loss_cause="runtime-loss")),
        mutate("before-after-diverged", lambda v: sc(v, "executor-loss-interrupted").update(
            after={"session.started": 1, "session.closed": 1, "prompt_receipts": 0})),
        mutate("ordinary-failed-marked-interrupted", lambda v: sc(v, "ordinary-failed-not-interrupted").update(
            adapter_containment={**sc(v, "ordinary-failed-not-interrupted")["adapter_containment"],
                "latest": {**sc(v, "ordinary-failed-not-interrupted")["adapter_containment"]["latest"],
                           "interrupted_run_id": "a" * 32}})),
        mutate("mismatched-run-marked-interrupted", lambda v: sc(v, "mismatched-run-not-interrupted")["events"][1].update(
            payload={"run_id": "b" * 32})),
        mutate("mismatched-trace-marked-interrupted", lambda v: sc(v, "mismatched-trace-not-interrupted")[
            "adapter_containment"]["latest"].update(trace_id="trace-1")),
        mutate("missing-summary-session-marked-interrupted", lambda v: sc(v, "missing-summary-session-not-interrupted")[
            "adapter_containment"].update(session_id="runtime-1")),
        mutate("missing-terminal-run-marked-interrupted", lambda v: sc(v, "missing-terminal-run-not-interrupted")[
            "events"][1].update(payload={"run_id": "a" * 32})),
        mutate("invalid-terminal-run-marked-interrupted", lambda v: sc(v, "invalid-terminal-run-not-interrupted")[
            "events"][1].update(payload={"run_id": "a" * 32})),
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
        mutate("authority-unavailable-allowed", lambda v: sc(v, "authority-unavailable-pauses")["inputs"].update(
            budget_available=True)),
        mutate("unknown-side-effect-auto-retry", lambda v: sc(v, "unknown-side-effect-paused")["inputs"].update(
            step_declared_idempotent=True)),
        mutate("cancel-recoverable", lambda v: sc(v, "cancel-blocks-recovery")["inputs"].update(cancelled=False)),
        mutate("budget-blocks-bypassed", lambda v: sc(v, "budget-exhausted-blocks")["inputs"].update(budget_available=True)),
        mutate("auth-revoked-bypassed", lambda v: sc(v, "authorization-revoked-blocks")["inputs"].update(
            authorization_current=True)),
        mutate("owner-mismatch-bypassed", lambda v: sc(v, "owner-workspace-mismatch-blocks")["inputs"].update(
            owner_matches=True)),
        mutate("success-receipt-replayed", lambda v: sc(v, "success-receipt-not-replayed")["inputs"].update(
            success_receipt_present=False)),
        mutate("preservation-constant-claim", lambda v: sc(v, "preservation-not-constant")["preservation"].update(
            states={field: "preserved" for field in sc(v, "preservation-not-constant")["preservation"]["states"]})),
        mutate("preservation-boundary-self-verified", lambda v: sc(v, "preservation-not-constant")[
            "preservation"].update(boundary_verified=True)),
        mutate("endpoint-source-mismatch", lambda v: sc(v, "recovery-endpoint-never-submits").update(
            source_sha256="sha256:" + "0" * 64)),
        mutate("negative-controls-trusted", lambda v: sc(v, "observer-breakable")["negative_controls"].update(
            all_controls_rejected=False)),
        mutate("missing-provenance", lambda v: v["scenarios"]["executor-loss-interrupted"].pop("provenance")),
        mutate("wrong-source-provenance", lambda v: v["scenarios"]["executor-loss-interrupted"]["provenance"].update(
            source="raw-dsh-event")),
        mutate("provenance-digest-mismatch", lambda v: v["provenance"]["source_sha256"].update(
            {"packages/contracts/session_failure_containment.py": "sha256:" + "0" * 64})),
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
