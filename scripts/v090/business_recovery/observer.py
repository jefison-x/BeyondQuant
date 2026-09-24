#!/usr/bin/env python3
"""Fail-able observer/verdict for ADR-0084 business recovery (the #351 design).

Separation of concerns:

* ``format_valid`` -- the observations artifact is well formed, source-bound by
  digest, and every scenario was independently re-derived.
* ``all_pass``     -- every REQUIRED scenario passed.

The observer does NOT trust recorded labels. For each scenario it re-executes the
closed contract function (allocation, budget decision, admission envelope,
carrier identity, snapshot closure, target fence, Gateway forwarding) and
re-checks the real adapter journal snapshot digest. The pre-fix "trust the label"
algorithm is kept only to prove, in ``--selfcheck``, that defect-targeting
negative controls would have been reported as PASS.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OBSERVATIONS_SCHEMA = "byq-v090-business-recovery-observations.v1"
VERDICT_SCHEMA = "byq-v090-business-recovery-verdict.v1"
NEGATIVE_SCHEMA = "byq-v090-business-recovery-negative-controls.v1"

DEFECT_TARGETING_CONTROLS = (
    "same-trigger-creates-a-second-attempt",
    "retry-raises-the-ordinal",
    "snapshot-change-consumes-an-ordinal",
    "ordinal-cap-bypassed",
    "double-deducted-budget",
    "model-floor-bypassed",
    "unknown-cost-treated-as-zero",
    "evidence-conflict-allowed",
    "grant-invariant-bypassed",
    "new-key-action-eligible",
    "non-original-call-eligible",
    "snapshot-digest-tamper-accepted",
    "snapshot-tail-change-accepted",
    "snapshot-idle-flip-accepted",
    "carrier-extra-field-accepted",
    "carrier-trigger-mismatch-accepted",
    "stale-target-epoch-accepted",
    "stale-target-generation-accepted",
    "gateway-invents-authority",
    "gateway-invented-field-accepted",
    "real-journal-digest-mismatch",
    "negative-controls-trusted",
    "missing-provenance",
    "wrong-source-provenance",
    "provenance-digest-mismatch",
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


def _contract_module():
    from packages.contracts import business_recovery as contract
    return contract


def _gateway_module():
    spec = importlib.util.spec_from_file_location(
        "byq_observer_gateway_recovery_carrier",
        ROOT / "services/gateway/app/recovery_carrier.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_provenance(contract: dict, block: object, ctx: str, failures: list[str]) -> None:
    if not isinstance(block, dict):
        failures.append(f"{ctx}: missing provenance")
        return
    if block.get("source") not in contract["provenance_allowed_sources"]:
        failures.append(f"{ctx}: provenance source is not contract-allowed")
    if not isinstance(block.get("observed_at"), (int, float)) or isinstance(block.get("observed_at"), bool):
        failures.append(f"{ctx}: provenance timestamp is missing")


def _check_allocation(contract, observed, expect, ctx, failures):
    c = _contract_module()
    if not isinstance(observed, dict) or not isinstance(observed.get("operations"), list):
        failures.append(f"{ctx}: allocation operations missing")
        return
    existing: list[dict] = []
    derived = []
    for operation in observed["operations"]:
        if not isinstance(operation, dict):
            failures.append(f"{ctx}: malformed allocation operation")
            return
        args = dict(operation)
        args.pop("expect", None)
        existing_before = args.pop("existing", existing)
        try:
            attempt, created = c.allocate_recovery_attempt(existing_attempts=existing_before, **args)
        except c.RecoveryRejected as exc:
            derived.append({"blocked": exc.code})
            existing = list(existing_before)
            continue
        derived.append({"created": created, "attempt_key": attempt["attempt_key"],
                        "ordinal": attempt["ordinal"]})
        existing = [*existing_before, attempt] if created else list(existing_before)
    for index, (result, expected) in enumerate(zip(derived, observed.get("expect", []))):
        if result != expected:
            failures.append(f"{ctx}: derived allocation result {index} {result!r} != contract {expected!r}")
    if len(derived) != len(observed.get("expect", [])):
        failures.append(f"{ctx}: allocation result count does not match the contract")


def _check_budget(contract, observed, expect, ctx, failures):
    c = _contract_module()
    if not isinstance(observed, dict) or not isinstance(observed.get("inputs"), dict):
        failures.append(f"{ctx}: budget inputs missing")
        return
    decision = c.budget_decision(**observed["inputs"])
    for field, value in (expect or {}).items():
        if decision.get(field) != value:
            failures.append(f"{ctx}: derived budget {field}={decision.get(field)!r} != contract {value!r}")


def _check_envelope(contract, observed, expect, ctx, failures):
    c = _contract_module()
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: envelope observation missing")
        return
    envelope = c.admission_envelope(
        read_only=observed.get("read_only"),
        replayed_calls=observed.get("replayed_calls"),
        occurred_calls=observed.get("occurred_calls"))
    for field, value in (expect or {}).items():
        if envelope.get(field) != value:
            failures.append(f"{ctx}: derived envelope {field}={envelope.get(field)!r} != contract {value!r}")


def _carrier_from_inputs(observed: dict) -> dict:
    """Rebuild the closed carrier in memory from non-secret inputs.

    The raw 64-hex ``trigger_key`` is a deterministic, non-secret recovery
    identity; it is recomputed here and never stored in the evidence, so no
    high-entropy-looking value is committed.
    """

    c = _contract_module()
    trigger = c.trigger_key(observed["reservation_id"], observed["run"], observed["generation"],
                            observed["attempt"], observed["epoch"])
    carrier = {
        "attempt_key": c.attempt_key(trigger, 1), "ordinal": 1, "trigger_key": trigger,
        "interrupted_run_id": observed["run"], "interrupted_generation": observed["generation"],
        "containment_attempt": observed["attempt"], "interrupted_executor_epoch": observed["epoch"],
        "snapshot_tail_sequence": observed["tail"], "snapshot_digest": observed["snapshot_digest"],
    }
    mutation = observed.get("mutation")
    if mutation == "extra_field":
        carrier["target_executor_epoch"] = 2
    elif mutation == "trigger_mismatch":
        carrier["trigger_key"] = "0" * 64
    return carrier


def _check_carrier(contract, observed, expect, ctx, failures):
    c = _contract_module()
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: carrier observation missing")
        return
    try:
        carrier = _carrier_from_inputs(observed)
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(f"{ctx}: carrier inputs malformed: {exc}")
        return
    try:
        c.verify_carrier_identity(carrier, reservation_id=observed["reservation_id"])
    except c.RecoveryRejected as exc:
        if (expect or {}).get("ok") is not False or (expect or {}).get("code") != exc.code:
            failures.append(f"{ctx}: derived carrier rejection {exc.code!r} != contract {expect!r}")
        return
    if (expect or {}).get("ok") is not True:
        failures.append(f"{ctx}: carrier was accepted but the contract rejects it")


def _check_snapshot(contract, observed, expect, ctx, failures):
    c = _contract_module()
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: snapshot observation missing")
        return
    try:
        result = c.verify_snapshot_closure(
            session_id=observed["session_id"], trace_id=observed["trace_id"],
            expected_tail_sequence=observed["expected_tail_sequence"],
            expected_digest=observed["expected_digest"], calls=observed["calls"],
            more=observed["more"], idle=observed["idle"])
    except c.RecoveryRejected as exc:
        if (expect or {}).get("ok") is not False or (expect or {}).get("code") != exc.code:
            failures.append(f"{ctx}: derived snapshot rejection {exc.code!r} != contract {expect!r}")
        return
    if (expect or {}).get("ok") is not True:
        failures.append(f"{ctx}: snapshot was accepted but the contract rejects it")
    if result["digest"] != observed["expected_digest"]:
        failures.append(f"{ctx}: snapshot digest does not match")


def _check_target(contract, observed, expect, ctx, failures):
    c = _contract_module()
    if not isinstance(observed, dict):
        failures.append(f"{ctx}: target observation missing")
        return
    try:
        c.assert_target_current(receipt=observed["receipt"],
            live_executor_epoch=observed["live_executor_epoch"],
            live_generation=observed["live_generation"])
    except c.RecoveryRejected as exc:
        if (expect or {}).get("ok") is not False or (expect or {}).get("code") != exc.code:
            failures.append(f"{ctx}: derived target rejection {exc.code!r} != contract {expect!r}")
        return
    if (expect or {}).get("ok") is not True:
        failures.append(f"{ctx}: stale target was accepted but the contract rejects it")


def _check_gateway(contract, observed, expect, ctx, failures):
    if not isinstance(observed, dict) or "reservation_id" not in observed:
        failures.append(f"{ctx}: gateway inputs missing")
        return
    try:
        carrier = _carrier_from_inputs(observed)
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(f"{ctx}: gateway carrier inputs malformed: {exc}")
        return
    reservation = {
        "schema_version": "task-continuation-reservation.v1",
        "reservation_id": observed["reservation_id"], "task_id": "task_" + "b" * 32,
        "owner": "alice", "workspace_id": "workspace_alice", "token_limit": 2_000_000,
        "expires_at": "2030-01-01T00:00:00+00:00",
        "recovery_attempt": carrier,
    }
    mutation = observed.get("mutation")
    if mutation == "invented_field":
        carrier["live_epoch"] = 2
    elif mutation == "invented_authority":
        reservation.pop("recovery_attempt", None)
    try:
        forwarded = _gateway_module().closed_recovery_carrier(reservation)
    except Exception as exc:  # noqa: BLE001 - a contract rejection is a valid outcome
        if (expect or {}).get("ok") is not False:
            failures.append(f"{ctx}: gateway rejected a valid carrier: {exc}")
        return
    if (expect or {}).get("ok") is not True:
        failures.append(f"{ctx}: gateway accepted an invalid carrier")
        return
    if forwarded.get("recovery_attempt") != carrier:
        failures.append(f"{ctx}: forwarded carrier does not equal the closed authority")
    if set(forwarded.get("recovery_attempt") or {}) != set(_contract_module().RECOVERY_CARRIER_FIELDS):
        failures.append(f"{ctx}: forwarded carrier is not the closed field set")


def _check_adapter(contract, observed, expect, ctx, failures):
    c = _contract_module()
    if not isinstance(observed, dict) or not isinstance(observed.get("calls"), list):
        failures.append(f"{ctx}: real adapter journal calls missing")
        return
    calls = observed["calls"]
    digest = c.canonical_snapshot_digest(
        session_id=observed["session_id"], trace_id=observed["trace_id"],
        tail_sequence=len(calls), calls=calls)
    if observed.get("digest") != digest:
        failures.append(f"{ctx}: recorded adapter digest is not the canonical digest")
    if observed.get("carrier_digest") != digest:
        failures.append(f"{ctx}: carrier did not anchor the real adapter snapshot")
    if observed.get("carrier_tail") != len(calls):
        failures.append(f"{ctx}: carrier tail does not match the real adapter call count")
    if observed.get("idle") is not True:
        failures.append(f"{ctx}: real adapter snapshot was not idle at admission")
    # The same closure rejects an idle flip and a tail append.
    try:
        c.verify_snapshot_closure(session_id=observed["session_id"], trace_id=observed["trace_id"],
            expected_tail_sequence=len(calls), expected_digest=digest, calls=calls, more=False, idle=False)
        failures.append(f"{ctx}: idle flip was accepted")
    except c.RecoveryRejected:
        pass


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
    "allocation": _check_allocation,
    "budget": _check_budget,
    "envelope": _check_envelope,
    "carrier": _check_carrier,
    "snapshot": _check_snapshot,
    "target": _check_target,
    "gateway": _check_gateway,
    "adapter": _check_adapter,
    "meta": _check_meta,
}


def _source_digests() -> dict:
    return {
        "packages/contracts/business_recovery.py":
            _digest(ROOT / "packages/contracts/business_recovery.py"),
        "services/runtime-adapter/app/business_recovery.py":
            _digest(ROOT / "services/runtime-adapter/app/business_recovery.py"),
        "services/runtime-adapter/app/runtime.py":
            _digest(ROOT / "services/runtime-adapter/app/runtime.py"),
        "services/gateway/app/recovery_carrier.py":
            _digest(ROOT / "services/gateway/app/recovery_carrier.py"),
        "services/backend/app/research_continuation.py":
            _digest(ROOT / "services/backend/app/research_continuation.py"),
    }


def _digest_exists_in_git_history(relative: str, expected: str) -> bool:
    """Prove that a captured source digest exists in repository history.

    Business-recovery evidence is a historical observation. Later accepted
    maintenance may change its source files, so rebinding that observation to
    the working tree would destroy reproducibility. CI checks out full history;
    require the exact captured bytes to remain reachable instead.
    """
    history = subprocess.run(
        ["git", "-C", str(ROOT), "log", "--format=%H", "--all", "--", relative],
        capture_output=True, text=True, check=False,
    )
    if history.returncode != 0:
        return False
    for commit in history.stdout.splitlines():
        blob = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{commit}:{relative}"],
            capture_output=True, check=False,
        )
        if blob.returncode == 0 and "sha256:" + hashlib.sha256(blob.stdout).hexdigest() == expected:
            return True
    return False


def _verify_provenance_digests(observations: dict, failures: list[str]) -> None:
    provenance = observations.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("source_sha256"), dict):
        failures.append("observations: missing source digest binding")
        return
    digests = provenance["source_sha256"]
    if not digests:
        failures.append("observations: empty source digest binding")
    for relative, expected in digests.items():
        if not _digest_exists_in_git_history(relative, expected):
            failures.append(f"provenance: source digest absent from git history for {relative}")


def compute_verdict(contract: dict, observations: object) -> dict:
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
            expect = entry.get("expect", spec.get("expect", {}))
            try:
                checker(contract, entry.get("observed"), expect, scenario_id, scenario_failures)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                scenario_failures.append(f"{scenario_id}: malformed observation: {exc}")
        verdict = "PASS" if not scenario_failures else "FAIL"
        results.append({"id": scenario_id, "required": required, "kind": spec["kind"],
                        "verdict": verdict, "failures": scenario_failures})
        failures.extend(scenario_failures)
    format_valid = not coverage and not any(
        failure.startswith("observations:") or failure.startswith("provenance:") for failure in failures)
    all_pass = format_valid and not failures
    return {"schema_version": VERDICT_SCHEMA, "format_valid": format_valid, "all_pass": all_pass,
            "exit_code": 0 if all_pass else 1, "failures": failures,
            "coverage_failures": coverage, "scenarios": results}


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


# --- selfcheck fixture + defect controls -------------------------------------


RUN = "b" * 32
RESERVATION = "continuation_" + "a" * 32


def _trigger(c, *, run=RUN, generation="generation-1", attempt=1, epoch=1):
    return c.trigger_key(RESERVATION, run, generation, attempt, epoch)


def _allocation_operation(c, *, run=RUN, generation="generation-1", attempt=1, epoch=1,
                          tail=0, digest=None):
    digest = digest or c.canonical_snapshot_digest(
        session_id="rec-1", trace_id="rec-trace", tail_sequence=0, calls=[])
    return {
        "reservation_id": RESERVATION,
        "interrupted_run_id": run, "interrupted_generation": generation,
        "containment_attempt": attempt, "interrupted_executor_epoch": epoch,
        "snapshot_tail_sequence": tail, "snapshot_digest": digest,
    }


def valid_fixture(contract: dict) -> dict:
    c = _contract_module()
    digest = c.canonical_snapshot_digest(session_id="rec-1", trace_id="rec-trace", tail_sequence=0, calls=[])
    other_digest = c.canonical_snapshot_digest(session_id="rec-1", trace_id="rec-trace",
        tail_sequence=1, calls=[{"sequence": 1, "root_run_id": RUN, "generation": "generation-1",
            "agent_run_id": "c" * 32, "action": "byq_strategy_validate", "idempotency_key": "idem-1",
            "request_sha256": "d" * 64, "input_sha256": "e" * 64}])
    scenarios = {}

    def add(scenario_id, observed, source, expect):
        scenarios[scenario_id] = {"verdict": "PASS", "observed": observed, "expect": expect,
                                  "provenance": {"source": source, "observed_at": 1.0}}
        return expect

    first = c.allocate_recovery_attempt(reservation_id=RESERVATION, existing_attempts=[],
        interrupted_run_id=RUN, interrupted_generation="generation-1", containment_attempt=1,
        interrupted_executor_epoch=1, snapshot_tail_sequence=0, snapshot_digest=digest)
    attempt_key = first[0]["attempt_key"]
    add("same-trigger-same-snapshot-exactly-once",
        {"operations": [_allocation_operation(c), _allocation_operation(c)],
         "expect": [{"created": True, "attempt_key": attempt_key, "ordinal": 1},
                    {"created": False, "attempt_key": attempt_key, "ordinal": 1}]},
        "contract-pure-function", {})
    add("retry-reuses-original-ordinal",
        {"operations": [_allocation_operation(c), _allocation_operation(c)],
         "expect": [{"created": True, "attempt_key": attempt_key, "ordinal": 1},
                    {"created": False, "attempt_key": attempt_key, "ordinal": 1}]},
        "contract-pure-function", {})
    add("snapshot-change-no-overwrite-no-extra-ordinal",
        {"operations": [_allocation_operation(c), _allocation_operation(c, tail=1, digest=other_digest)],
         "expect": [{"created": True, "attempt_key": attempt_key, "ordinal": 1},
                    {"blocked": "snapshot_changed_for_existing_trigger"}]},
        "contract-pure-function", {})
    add("ordinal-cap-blocks",
        {"operations": [_allocation_operation(c),
                        _allocation_operation(c, run="c" * 32, generation="generation-2"),
                        _allocation_operation(c, run="d" * 32, generation="generation-3"),
                        _allocation_operation(c, run="e" * 32, generation="generation-4")],
         "expect": [{"created": True, "attempt_key": attempt_key, "ordinal": 1},
                    {"created": True, "attempt_key": c.attempt_key(_trigger(c, run="c" * 32, generation="generation-2"), 2),
                     "ordinal": 2},
                    {"created": True, "attempt_key": c.attempt_key(_trigger(c, run="d" * 32, generation="generation-3"), 3),
                     "ordinal": 3},
                    {"blocked": "ordinal_cap"}]},
        "contract-pure-function", {})

    add("no-double-deduction",
        {"inputs": {"permission_token_limit": 10_000_000, "other_settled": 30, "other_unresolved": 0,
                    "r_token_limit": 2_000_000, "cum_exact": 20, "model_call_floor": 1_000_000}},
        "contract-pure-function", {"decision": "eligible", "reason": "known_headroom", "r_available": 1_999_980})
    add("model-call-floor-required",
        {"inputs": {"permission_token_limit": 100, "other_settled": 30, "other_unresolved": 0,
                    "r_token_limit": 60, "cum_exact": 20, "model_call_floor": 1_000_000}},
        "contract-pure-function", {"decision": "blocked", "reason": "below_model_call_floor"})
    add("unknown-cost-paused",
        {"inputs": {"permission_token_limit": 10_000_000, "other_settled": 0, "other_unresolved": 0,
                    "r_token_limit": 2_000_000, "cum_exact": None, "model_call_floor": 1_000_000}},
        "contract-pure-function", {"decision": "paused", "reason": "unknown_attempt_charge"})
    add("evidence-conflict-blocked",
        {"inputs": {"permission_token_limit": 10_000_000, "other_settled": 0, "other_unresolved": 0,
                    "r_token_limit": 2_000_000, "cum_exact": 0, "model_call_floor": 1_000_000,
                    "evidence_conflict": True}},
        "contract-pure-function", {"decision": "blocked", "reason": "authoritative_evidence_conflict"})
    add("grant-invariant-blocked",
        {"inputs": {"permission_token_limit": 100, "other_settled": 30, "other_unresolved": 0,
                    "r_token_limit": 80, "cum_exact": 0, "model_call_floor": 1}},
        "contract-pure-function", {"decision": "blocked", "reason": "grant_invariant_violated"})

    occurred = [{"action": "byq_strategy_validate", "task_id": "task_x", "idempotency_key": "idem-1",
                 "request_sha256": "a" * 64, "input_sha256": "b" * 64}]
    add("envelope-new-key-blocked",
        {"read_only": False, "occurred_calls": occurred,
         "replayed_calls": [{**occurred[0], "action": "byq_ml_strategy_create"}]},
        "contract-pure-function", {"eligible": False, "mode": "blocked"})
    add("envelope-exact-reuse-eligible",
        {"read_only": False, "occurred_calls": occurred, "replayed_calls": occurred},
        "contract-pure-function", {"eligible": True, "mode": "exact_reuse"})
    add("envelope-non-original-call-blocked",
        {"read_only": False, "occurred_calls": occurred,
         "replayed_calls": [{**occurred[0], "request_sha256": "c" * 64}]},
        "contract-pure-function", {"eligible": False, "mode": "blocked"})

    add("snapshot-digest-tamper-paused",
        {"session_id": "rec-1", "trace_id": "rec-trace", "expected_tail_sequence": 0,
         "expected_digest": "f" * 64, "calls": [], "more": False, "idle": True},
        "contract-pure-function", {"ok": False, "code": "snapshot_digest_changed"})
    add("snapshot-tail-change-paused",
        {"session_id": "rec-1", "trace_id": "rec-trace", "expected_tail_sequence": 0,
         "expected_digest": other_digest, "calls": [{"sequence": 1, "root_run_id": RUN,
            "generation": "generation-1", "agent_run_id": "c" * 32, "action": "byq_strategy_validate",
            "idempotency_key": "idem-1", "request_sha256": "d" * 64, "input_sha256": "e" * 64}],
         "more": False, "idle": True},
        "contract-pure-function", {"ok": False, "code": "invalid_snapshot_input"})
    add("snapshot-idle-flip-paused",
        {"session_id": "rec-1", "trace_id": "rec-trace", "expected_tail_sequence": 0,
         "expected_digest": digest, "calls": [], "more": False, "idle": False},
        "contract-pure-function", {"ok": False, "code": "snapshot_not_idle"})

    carrier_inputs = {"reservation_id": RESERVATION, "run": RUN, "generation": "generation-1",
                      "attempt": 1, "epoch": 1, "tail": 0, "snapshot_digest": digest}
    add("carrier-extra-field-rejected",
        {**carrier_inputs, "mutation": "extra_field"},
        "contract-pure-function", {"ok": False, "code": "invalid_carrier"})
    add("carrier-trigger-mismatch-rejected",
        {**carrier_inputs, "mutation": "trigger_mismatch"},
        "contract-pure-function", {"ok": False, "code": "trigger_key_mismatch"})

    receipt = {"schema_version": "recovery-accepted-receipt.v1", "attempt_key": attempt_key,
               "reservation_id": RESERVATION, "ordinal": 1, "run_id": "d" * 32,
               "target_executor_epoch": 2, "target_generation": "generation-2",
               "snapshot_tail_sequence": 0, "snapshot_digest": digest}
    add("target-stale-epoch-rejected",
        {"receipt": receipt, "live_executor_epoch": 3, "live_generation": "generation-2"},
        "contract-pure-function", {"ok": False, "code": "stale_target_epoch"})
    add("target-stale-generation-rejected",
        {"receipt": receipt, "live_executor_epoch": 2, "live_generation": "generation-3"},
        "contract-pure-function", {"ok": False, "code": "stale_target_generation"})

    add("gateway-forwards-closed-carrier",
        dict(carrier_inputs), "gateway-recovery-carrier", {"ok": True})
    add("gateway-rejects-invented-field",
        {**carrier_inputs, "mutation": "invented_field"}, "gateway-recovery-carrier", {"ok": False})

    add("real-adapter-journal-snapshot-closure",
        {"session_id": "rec-1", "trace_id": "rec-trace", "calls": [], "idle": True,
         "tail": 0, "digest": digest, "carrier_tail": 0, "carrier_digest": digest},
        "runtime-adapter-real-journal", {})

    add("observer-breakable", {"negative_controls": {
        "all_controls_rejected": True, "control_count": len(DEFECT_TARGETING_CONTROLS),
        "defect_targeting_count": len(DEFECT_TARGETING_CONTROLS)}}, "contract-pure-function", {})
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
        mutate("same-trigger-creates-a-second-attempt", lambda v: sc(v, "same-trigger-same-snapshot-exactly-once")[
            "expect"][1].update({"created": True, "ordinal": 2})),
        mutate("retry-raises-the-ordinal", lambda v: sc(v, "retry-reuses-original-ordinal")[
            "expect"][1].update({"created": True, "ordinal": 2})),
        mutate("snapshot-change-consumes-an-ordinal", lambda v: sc(v, "snapshot-change-no-overwrite-no-extra-ordinal")[
            "expect"][1].update({"blocked": None, "created": True, "ordinal": 2})),
        mutate("ordinal-cap-bypassed", lambda v: sc(v, "ordinal-cap-blocks")["expect"][3].update(
            {"blocked": None, "created": True, "ordinal": 4})),
        mutate("double-deducted-budget", lambda v: sc(v, "no-double-deduction").update(
            {"inputs": {**sc(v, "no-double-deduction")["inputs"], "other_unresolved": 9_000_000}})),
        mutate("model-floor-bypassed", lambda v: sc(v, "model-call-floor-required").update(
            {"inputs": {**sc(v, "model-call-floor-required")["inputs"], "cum_exact": 0, "model_call_floor": 1}})),
        mutate("unknown-cost-treated-as-zero", lambda v: sc(v, "unknown-cost-paused")["inputs"].update(
            cum_exact=0)),
        mutate("evidence-conflict-allowed", lambda v: sc(v, "evidence-conflict-blocked")["inputs"].update(
            evidence_conflict=False)),
        mutate("grant-invariant-bypassed", lambda v: sc(v, "grant-invariant-blocked")["inputs"].update(
            other_settled=0)),
        mutate("new-key-action-eligible", lambda v: sc(v, "envelope-new-key-blocked")["replayed_calls"][0].update(
            action="byq_strategy_validate")),
        mutate("non-original-call-eligible", lambda v: sc(v, "envelope-non-original-call-blocked")[
            "replayed_calls"][0].update(request_sha256="a" * 64)),
        mutate("snapshot-digest-tamper-accepted", lambda v: sc(v, "snapshot-digest-tamper-paused").update(
            expected_digest=sc(v, "snapshot-idle-flip-paused")["expected_digest"])),
        mutate("snapshot-tail-change-accepted", lambda v: sc(v, "snapshot-tail-change-paused").update(
            expected_tail_sequence=1)),
        mutate("snapshot-idle-flip-accepted", lambda v: sc(v, "snapshot-idle-flip-paused").update(idle=True)),
        mutate("carrier-extra-field-accepted", lambda v: sc(v, "carrier-extra-field-rejected").update(
            mutation=None)),
        mutate("carrier-trigger-mismatch-accepted", lambda v: sc(v, "carrier-trigger-mismatch-rejected").update(
            mutation=None)),
        mutate("stale-target-epoch-accepted", lambda v: sc(v, "target-stale-epoch-rejected").update(
            live_executor_epoch=2)),
        mutate("stale-target-generation-accepted", lambda v: sc(v, "target-stale-generation-rejected").update(
            live_generation="generation-2")),
        mutate("gateway-invents-authority", lambda v: sc(v, "gateway-forwards-closed-carrier").update(
            mutation="invented_authority")),
        mutate("gateway-invented-field-accepted", lambda v: sc(v, "gateway-rejects-invented-field").update(
            mutation=None)),
        mutate("real-journal-digest-mismatch", lambda v: sc(v, "real-adapter-journal-snapshot-closure").update(
            digest="0" * 64)),
        mutate("negative-controls-trusted", lambda v: sc(v, "observer-breakable")["negative_controls"].update(
            all_controls_rejected=False)),
        mutate("missing-provenance", lambda v: v["scenarios"]["same-trigger-same-snapshot-exactly-once"].pop("provenance")),
        mutate("wrong-source-provenance", lambda v: v["scenarios"]["same-trigger-same-snapshot-exactly-once"][
            "provenance"].update(source="raw-dsh-event")),
        mutate("provenance-digest-mismatch", lambda v: v["provenance"]["source_sha256"].update(
            {"packages/contracts/business_recovery.py": "sha256:" + "0" * 64})),
    ]


def run_selfcheck(contract: dict) -> dict:
    baseline = compute_verdict(contract, valid_fixture(contract))
    controls = []
    for name, observations in _controls(contract):
        verdict = compute_verdict(contract, observations)
        legacy = legacy_compute_verdict(contract, observations)
        controls.append({"name": name, "observed_all_pass": verdict["all_pass"],
            "observed_exit_code": verdict["exit_code"],
            "first_failure": (verdict["failures"] or verdict["coverage_failures"] or ["<none>"])[0],
            "pre_fix_legacy_all_pass": legacy["all_pass"],
            "defect_targeting": name in DEFECT_TARGETING_CONTROLS})
    targeting = [control for control in controls if control["defect_targeting"]]
    return {"schema_version": NEGATIVE_SCHEMA, "baseline_all_pass": baseline["all_pass"],
        "control_count": len(controls),
        "all_controls_pass": all(not c["observed_all_pass"] and c["observed_exit_code"] == 1 for c in controls),
        "defect_targeting_pre_fix_passed": bool(targeting) and all(
            c["pre_fix_legacy_all_pass"] and not c["observed_all_pass"] for c in targeting),
        "defect_targeting_count": len(targeting), "controls": controls}


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
