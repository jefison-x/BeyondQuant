#!/usr/bin/env python3
"""Fail-able observer/verdict for the D15-4 native subagent/fork qualification.

Separation of concerns:

* ``format_valid`` — the observations artifact is well formed and every check
  that ran passed. A structurally valid "report" can still be an unqualified run.
* ``all_pass`` — the qualification passed: every REQUIRED scenario is present
  and PASS with all contract assertions true, no scenario FAILed, at least one
  fault was applied where the contract requires it, every negative was rejected,
  and there are no structural violations. A REQUIRED scenario left
  ``NOT_RUN``/``BLOCKED``/``MISSING`` therefore fails the verdict (non-zero exit)
  while its status/reason is preserved.

The contract is the only source of truth for the required scenarios, required
assertions and fault requirements. An observation may not declare its own
continuity/coverage rules. The observer never treats missing evidence as a pass
and never defaults a measured value.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "contract.v1.json"


class Failure(Exception):
    """Raised only for an unreadable contract/observations artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Contract-authoritative assertion derivation from raw observations.
# ---------------------------------------------------------------------------

def _identity(obs: dict) -> dict[str, bool]:
    header = obs.get("header") if isinstance(obs.get("header"), dict) else {}
    children = obs.get("listChildren") if isinstance(obs.get("listChildren"), list) else []
    return {
        "distinct_durable_child": obs.get("distinctIdentity") is True,
        "parent_link_recorded": _is_nonempty_str(header.get("parentSession"))
        and header.get("parentSession") == obs.get("parentId"),
        "origin_subagent": header.get("origin") == "subagent",
        "list_children_continuable": any(
            isinstance(item, dict) and item.get("mode") == "continuable" for item in children),
    }


def _descriptor(obs: dict) -> dict[str, bool]:
    return {
        "descriptor_version_3": obs.get("version") == 3,
        "mode_continuable": obs.get("mode") == "continuable",
        "provider_recorded": _is_nonempty_str(obs.get("provider")),
    }


def _cold_resume(obs: dict) -> dict[str, bool]:
    after = obs.get("descriptorAfter") if isinstance(obs.get("descriptorAfter"), dict) else {}
    return {
        "same_child_id": obs.get("sameChildId") is True,
        "sequence_contiguous": obs.get("sequenceContiguousAcrossResume") is True,
        "settlement_exactly_once": _is_int(obs.get("newSettlements")) and obs.get("newSettlements") == 1,
        "descriptor_reapplied": after.get("mode") == "continuable",
    }


def _fork(obs: dict) -> dict[str, bool]:
    inherited = obs.get("inheritedEventCount")
    return {
        "distinct_identity": obs.get("distinctIdentity") is True,
        "is_seeded": obs.get("isSeeded") is True,
        "inherited_prefix_nonzero": _is_int(inherited) and inherited > 0,
        "parent_unchanged": obs.get("parentUnchanged") is True,
    }


def _inheritance(obs: dict) -> dict[str, bool]:
    descriptor = obs.get("descriptor") if isinstance(obs.get("descriptor"), dict) else {}
    reapplied = obs.get("reappliedChild") if isinstance(obs.get("reappliedChild"), dict) else {}
    return {
        "provider_inherited": descriptor.get("agentProvider") == "mock",
        "model_inherited": descriptor.get("agentModel") == "mock",
        "reasoning_inherited": descriptor.get("agentReasoningEffort") == "max",
        "persona_inherited": _is_nonempty_str(descriptor.get("persona")),
        "reapplied_on_cold_resume": reapplied.get("reasoningEffort") == "max",
    }


def _parent_crash(obs: dict) -> dict[str, bool]:
    crash = obs.get("crash") if isinstance(obs.get("crash"), dict) else {}
    after = obs.get("after") if isinstance(obs.get("after"), dict) else {}
    descriptor = after.get("descriptorAfter") if isinstance(after.get("descriptorAfter"), dict) else {}
    return {
        "executor_crash_observed": crash.get("crashedAsExpected") is True,
        "child_id_retained": after.get("childIdRetained") is True,
        "parent_identity_survived": after.get("parentSurvived") is True,
        "resumable_after_crash": after.get("sameChildId") is True and descriptor.get("mode") == "continuable",
    }


def _child_crash(obs: dict) -> dict[str, bool]:
    return {
        "child_id_retained": obs.get("childIdRetained") is True,
        "parent_truthful_failure": obs.get("parentTruthfulFailure") is True,
        "natively_resumable": obs.get("nativelyResumable") is True,
        "no_fabricated_completion": obs.get("fabricatedCompletion") is not True,
    }


def _byq_adapter_restart(obs: dict) -> dict[str, bool]:
    count = obs.get("sideEffectCount")
    return {
        "container_restart_observed": obs.get("containerRestart") is True,
        "child_resumed_natively": obs.get("childResumedNatively") is True,
        "same_child_id": obs.get("sameChildId") is True,
        "no_duplicate_side_effect": _is_int(count) and count == 1,
    }


_ASSERTION_DERIVERS: dict[str, Callable[[dict], dict[str, bool]]] = {
    "parent-child-identity": _identity,
    "continuable-descriptor": _descriptor,
    "cold-resume": _cold_resume,
    "fork-lineage": _fork,
    "inheritance": _inheritance,
    "parent-crash": _parent_crash,
    "child-crash": _child_crash,
    "byq-adapter-restart": _byq_adapter_restart,
}


def _check_scenario(scenario: dict, spec: dict, failures: list[str]) -> dict:
    scenario_id = scenario.get("id")
    ctx = f"scenario[{scenario_id}]"
    result = scenario.get("result")
    required = bool(spec.get("required", False))
    expected_assertions = list(spec.get("assertions", []))
    row: dict[str, Any] = {
        "id": scenario_id,
        "result": result,
        "required": required,
        "assertions": {},
        "assertions_ok": False,
    }

    # Contract criteria are authoritative: an observation may not declare its own
    # coverage or continuity rules.
    for forbidden_field in ("required", "assertions_ok", "coverage", "allowed_continuity", "forbidden_continuity"):
        if forbidden_field in scenario:
            failures.append(
                f"{ctx}: observation may not declare '{forbidden_field}'; the contract is authoritative")

    if result not in {"PASS", "FAIL", "NOT_RUN", "BLOCKED"}:
        failures.append(f"{ctx}: invalid result {result!r}")
        return row

    if result in {"NOT_RUN", "BLOCKED"}:
        if not _is_nonempty_str(scenario.get("not_run_reason")):
            failures.append(f"{ctx}: {result} without a reason")
        row["not_run_reason"] = scenario.get("not_run_reason")
        return row

    if result != "PASS":
        failures.append(f"{ctx}: result {result!r} is not PASS")
        return row

    if spec.get("requires_fault") and scenario.get("fault_applied") is not True:
        failures.append(f"{ctx}: fault_applied is not true (scenario was not actually exercised)")

    observation = scenario.get("observation")
    if not isinstance(observation, dict):
        failures.append(f"{ctx}: PASS without an observation object")
        return row

    deriver = _ASSERTION_DERIVERS.get(scenario_id)
    if deriver is None:
        failures.append(f"{ctx}: no contract deriver for a required PASS scenario")
        return row
    derived = deriver(observation)
    row["assertions"] = {name: bool(derived.get(name)) for name in expected_assertions}
    row["assertions_ok"] = (not expected_assertions) or all(row["assertions"].values())
    if not row["assertions_ok"]:
        false_names = [name for name, value in row["assertions"].items() if not value]
        failures.append(f"{ctx}: false assertions {false_names or 'none-derived'}")
    row["observation_keys"] = sorted(observation.keys())
    return row


def _check_negatives(observations: dict, contract: dict, failures: list[str]) -> list[dict]:
    negatives = observations.get("negatives")
    if not isinstance(negatives, list) or not negatives:
        failures.append("negatives must be a non-empty list")
        return []
    rows = []
    for index, item in enumerate(negatives):
        if not isinstance(item, dict):
            failures.append(f"negatives[{index}] is not an object")
            continue
        rejected = item.get("rejected") is True
        rows.append({"kind": item.get("kind"), "rejected": rejected,
                     "errorCode": item.get("errorCode"), "errorClass": item.get("errorClass")})
        if contract.get("negatives_must_all_be_rejected") and not rejected:
            failures.append(f"negative {item.get('kind')!r} was not rejected")
    return rows


def compute_verdict(contract: dict, observations: dict, *, allow_unit_fixture: bool = False) -> dict:
    failures: list[str] = []
    coverage_failures: list[str] = []

    if not isinstance(observations, dict):
        raise Failure("observations must be an object")

    candidate = contract["candidate"]
    observed_candidate = observations.get("candidate")
    if not isinstance(observed_candidate, dict) or observed_candidate.get("release") != candidate["release"]:
        failures.append(f"candidate mismatch: expected {candidate['release']!r}, got {observed_candidate!r}")

    required_class = contract.get("required_evidence_class")
    observed_class = observations.get("evidence_class")
    if allow_unit_fixture:
        if not _is_nonempty_str(observed_class):
            failures.append("evidence_class must be declared")
    elif observed_class != required_class:
        failures.append(
            f"evidence_class {observed_class!r} is not native runtime evidence {required_class!r}; "
            "a synthetic/unit fixture or a format-layer artifact is not a D15-4 pass")

    llm = observations.get("llm")
    if not isinstance(llm, dict) or llm.get("class") != contract["llm_evidence_class"] \
            or llm.get("real_llm_quality") is not False:
        failures.append("LLM evidence class must be explicitly scripted/keyless with real_llm_quality=false")

    required = {item["id"]: item for item in contract.get("required_scenarios", [])}
    optional = {item["id"]: item for item in contract.get("optional_scenarios", [])}
    specs = {**required, **optional}

    scenarios_value = observations.get("scenarios")
    if not isinstance(scenarios_value, list):
        failures.append("scenarios must be a list")
        scenarios_value = []

    observed_ids = [item.get("id") if isinstance(item, dict) else None for item in scenarios_value]
    if len(observed_ids) != len(set(map(str, observed_ids))):
        failures.append("duplicate scenario id in observations")
    if contract.get("closed_scenario_set"):
        for scenario_id in observed_ids:
            if scenario_id not in specs:
                failures.append(f"unknown scenario id {scenario_id!r} (closed set)")

    scenario_results = []
    for item in scenarios_value:
        if not isinstance(item, dict):
            failures.append("scenario entry is not an object")
            continue
        spec = specs.get(item.get("id"), {"required": False})
        scenario_results.append(_check_scenario(item, spec, failures))

    seen_ids = set(observed_ids)
    for scenario_id in required:
        if scenario_id not in seen_ids:
            failures.append(f"missing required scenario {scenario_id!r}")

    rows = {row["id"]: row for row in scenario_results}
    required_coverage: dict[str, str] = {}
    for scenario_id in required:
        row = rows.get(scenario_id)
        required_coverage[scenario_id] = row["result"] if row is not None else "MISSING"
        if row is None or row["result"] != "PASS" or not row.get("assertions_ok"):
            coverage_failures.append(
                f"required scenario {scenario_id!r} is not covered by a PASS "
                f"(observed {required_coverage[scenario_id]})")
    optional_coverage: dict[str, str] = {}
    for scenario_id in optional:
        row = rows.get(scenario_id)
        optional_coverage[scenario_id] = row["result"] if row is not None else "MISSING"

    required_coverage_ok = contract.get("required_coverage_gates_qualification", True) \
        and all(value == "PASS" for value in required_coverage.values()) \
        and len(required_coverage) == len(required) \
        and all(row.get("assertions_ok") for row in scenario_results
                if row["id"] in required)

    negatives = _check_negatives(observations, contract, failures)
    negatives_ok = bool(negatives) and all(item["rejected"] for item in negatives)

    failed = [row["id"] for row in scenario_results if row["result"] == "FAIL"]
    pass_scenarios = [row for row in scenario_results if row["result"] == "PASS"]
    uncovered = [row["id"] for row in scenario_results if row["result"] in {"NOT_RUN", "BLOCKED"}]
    reason_uncovered = [scenario_id for scenario_id, value in required_coverage.items()
                        if value in {"NOT_RUN", "BLOCKED", "MISSING"}]

    format_valid = not failures
    all_pass = format_valid and not failed and required_coverage_ok and negatives_ok
    return {
        "schema_version": "byq-d15-4-verdict.v1",
        "all_pass": all_pass,
        "format_valid": format_valid,
        "qualification_passed": all_pass,
        "exit_code": 0 if all_pass else 1,
        "candidate": candidate,
        "evidence_class": observed_class,
        "llm_evidence_class": contract["llm_evidence_class"],
        "required_scenario_count": len(required),
        "optional_scenario_count": len(optional),
        "required_coverage": required_coverage,
        "required_coverage_ok": required_coverage_ok,
        "optional_coverage": optional_coverage,
        "pass_scenarios": [row["id"] for row in pass_scenarios],
        "failed_scenarios": failed,
        "uncovered_scenarios": uncovered,
        "reason_uncovered": reason_uncovered,
        "negatives": negatives,
        "negatives_ok": negatives_ok,
        "scenarios": scenario_results,
        "failures": failures,
        "coverage_failures": coverage_failures,
    }


# ---------------------------------------------------------------------------
# Legacy (pre-fix) algorithm, executed only to prove the pre-fix behaviour.
# ---------------------------------------------------------------------------

def legacy_compute_verdict(contract: dict, observations: dict) -> dict:
    """Pre-fix algorithm: the result string alone decided, coverage never gated.

    It ignored assertions and fault application, and a required
    NOT_RUN/BLOCKED did not gate the overall result (the D15-4 equivalent of the
    D15-3R pre-fix bug), so a report with an unqualified required scenario or a
    PASS carrying false assertions still passed.
    """
    failures: list[str] = []
    scenarios = observations.get("scenarios") if isinstance(observations.get("scenarios"), list) else []
    rows = []
    for item in scenarios:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        rows.append({"id": item.get("id"), "result": result})
        if result == "FAIL":
            failures.append(f"scenario {item.get('id')!r} FAIL")
        elif result in {"NOT_RUN", "BLOCKED"}:
            if not _is_nonempty_str(item.get("not_run_reason")):
                failures.append(f"scenario {item.get('id')!r} {result} without reason")
            # Pre-fix bug: an unqualified required scenario did NOT gate PASS.
        elif result == "PASS":
            # Pre-fix bug: assertions and fault application were never checked.
            pass
        else:
            failures.append(f"scenario {item.get('id')!r} invalid result {result!r}")
    all_pass = not failures
    return {"algorithm": "legacy-pre-fix", "all_pass": all_pass, "exit_code": 0 if all_pass else 1,
            "failures": failures}


# ---------------------------------------------------------------------------
# Unit fixture + negative controls (selfcheck).
# ---------------------------------------------------------------------------

def _obs_identity() -> dict:
    return {
        "parentId": "d15-4-parent", "childId": "child-0001", "distinctIdentity": True,
        "header": {"id": "child-0001", "parentSession": "d15-4-parent", "origin": "subagent",
                   "isSeeded": False, "delegationDepth": 1},
        "descriptor": {"version": 3, "mode": "continuable", "provider": "spawn"},
        "listChildren": [{"id": "child-0001", "mode": "continuable", "kind": "child"}],
    }


def valid_fixture(contract: dict) -> dict:
    """Synthetic UNIT fixture. Never runtime PASS evidence (evidence_class=unit-fixture)."""
    scenarios = [
        {"id": "parent-child-identity", "result": "PASS", "fault_applied": False,
         "observation": _obs_identity(), "evidence": ["docs/evidence/d15/d15-4/scenarios/parent-child-identity.v1.json"]},
        {"id": "continuable-descriptor", "result": "PASS", "fault_applied": False,
         "observation": {"version": 3, "mode": "continuable", "provider": "spawn"}},
        {"id": "cold-resume", "result": "PASS", "fault_applied": True,
         "observation": {"sameChildId": True, "sequenceContiguousAcrossResume": True, "newSettlements": 1,
                         "descriptorAfter": {"mode": "continuable"}}},
        {"id": "fork-lineage", "result": "PASS", "fault_applied": True,
         "observation": {"distinctIdentity": True, "isSeeded": True, "inheritedEventCount": 11,
                         "parentUnchanged": True}},
        {"id": "inheritance", "result": "PASS", "fault_applied": True,
         "observation": {"descriptor": {"agentProvider": "mock", "agentModel": "mock",
                                        "agentReasoningEffort": "max", "persona": "persona"},
                         "reappliedChild": {"reasoningEffort": "max"}}},
        {"id": "parent-crash", "result": "PASS", "fault_applied": True,
         "observation": {"crash": {"crashedAsExpected": True},
                         "after": {"childIdRetained": True, "parentSurvived": True, "sameChildId": True,
                                   "descriptorAfter": {"mode": "continuable"}}}},
        {"id": "child-crash", "result": "BLOCKED", "fault_applied": False,
         "not_run_reason": "in-process child is not isolatable as a child-only crash"},
        {"id": "byq-adapter-restart", "result": "BLOCKED", "fault_applied": False,
         "not_run_reason": "no BYQ composition path reaches startContinuable in this batch"},
        {"id": "host-reboot", "result": "NOT_RUN", "fault_applied": False,
         "not_run_reason": "host reboot is not authorized and is not a container restart"},
    ]
    return {
        "schema_version": "byq-d15-4-native-observations.v1",
        "evidence_class": "unit-fixture",
        "candidate": dict(contract["candidate"]),
        "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False,
                "note": "negative-control unit fixture (not runtime evidence)"},
        "scenarios": scenarios,
        "negatives": [
            {"kind": "non-direct-parent", "rejected": True, "errorCode": "UNAUTHORIZED"},
            {"kind": "stale-parent", "rejected": True, "errorCode": "UNAUTHORIZED"},
            {"kind": "unmaterialized", "rejected": True, "errorCode": "NOT_RESUMABLE"},
            {"kind": "max-depth", "rejected": True, "errorClass": "SubagentDepthError"},
        ],
    }


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    mutations: list[tuple[str, dict]] = []

    def add(name: str, mutate) -> None:
        value = copy.deepcopy(fixture)
        mutate(value)
        mutations.append((name, value))

    def scenario(value: dict, scenario_id: str) -> dict:
        return next(item for item in value["scenarios"] if item["id"] == scenario_id)

    add("missing-required-scenario", lambda v: v["scenarios"].pop(0))
    add("duplicate-scenario-id", lambda v: v["scenarios"].append(copy.deepcopy(v["scenarios"][0])))
    add("unknown-scenario-id", lambda v: v["scenarios"][0].update({"id": "invented-scenario"}))
    add("required-blocked", lambda v: scenario(v, "cold-resume").update(
        {"result": "BLOCKED", "not_run_reason": "injected"}))
    add("required-not-run", lambda v: scenario(v, "cold-resume").update(
        {"result": "NOT_RUN", "not_run_reason": "injected"}))
    add("blocked-without-reason", lambda v: scenario(v, "host-reboot").update(
        {"result": "BLOCKED", "fault_applied": False, "not_run_reason": ""}))
    add("false-assertion-same-child-id", lambda v: scenario(v, "cold-resume")["observation"].update(
        {"sameChildId": False}))
    add("duplicate-settlement", lambda v: scenario(v, "cold-resume")["observation"].update(
        {"newSettlements": 2}))
    add("fork-inherited-off-by-one-zero", lambda v: scenario(v, "fork-lineage")["observation"].update(
        {"inheritedEventCount": 0}))
    add("fork-not-seeded", lambda v: scenario(v, "fork-lineage")["observation"].update({"isSeeded": False}))
    add("fork-parent-mutated", lambda v: scenario(v, "fork-lineage")["observation"].update(
        {"parentUnchanged": False}))
    add("descriptor-wrong-version", lambda v: scenario(v, "continuable-descriptor")["observation"].update(
        {"version": 2}))
    add("reasoning-drift", lambda v: scenario(v, "inheritance")["observation"]["descriptor"].update(
        {"agentReasoningEffort": "low"}))
    add("persona-dropped", lambda v: scenario(v, "inheritance")["observation"]["descriptor"].pop("persona"))
    add("fault-not-applied", lambda v: scenario(v, "parent-crash").update({"fault_applied": False}))
    add("parent-identity-replaced", lambda v: scenario(v, "parent-crash")["observation"]["after"].update(
        {"parentSurvived": False}))
    add("negative-not-rejected", lambda v: v["negatives"][0].update({"rejected": False}))
    add("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    add("non-native-evidence-class", lambda v: v.update({"evidence_class": "format-layer"}))
    add("llm-claims-real-quality", lambda v: v["llm"].update({"class": "real-llm", "real_llm_quality": True}))
    add("pass-without-observation", lambda v: scenario(v, "cold-resume").pop("observation"))
    add("self-declared-coverage", lambda v: scenario(v, "cold-resume").update(
        {"required": False, "assertions_ok": True}))
    return mutations


def _fully_qualified_fixture(contract: dict) -> dict:
    fixture = valid_fixture(contract)
    for scenario in fixture["scenarios"]:
        if scenario["id"] == "child-crash":
            scenario.update({"result": "PASS", "fault_applied": True, "not_run_reason": None,
                             "observation": {"childIdRetained": True, "parentTruthfulFailure": True,
                                             "nativelyResumable": True, "fabricatedCompletion": False}})
        if scenario["id"] == "byq-adapter-restart":
            scenario.update({"result": "PASS", "fault_applied": True, "not_run_reason": None,
                             "observation": {"containerRestart": True, "childResumedNatively": True,
                                             "sameChildId": True, "sideEffectCount": 1}})
    return fixture


def selfcheck(contract: dict) -> dict:
    baseline = _fully_qualified_fixture(contract)
    fixture_with_required_blocked = valid_fixture(contract)
    good = compute_verdict(contract, baseline, allow_unit_fixture=True)

    # Controls run against the strict (non-unit) adjudicator so the evidence-class
    # and LLM-class gates are actually exercised: relabel the synthetic baseline to
    # the contract evidence class for the control set only.
    strict_baseline = copy.deepcopy(baseline)
    strict_baseline["evidence_class"] = contract["required_evidence_class"]
    strict_good = compute_verdict(contract, strict_baseline, allow_unit_fixture=False)
    controls = []

    def record(name: str, mutated: dict, *, strict: bool = True) -> None:
        fixed = compute_verdict(contract, mutated, allow_unit_fixture=not strict)
        legacy = legacy_compute_verdict(contract, mutated)
        controls.append({
            "name": name,
            "fixed_all_pass": fixed["all_pass"],
            "fixed_exit_code": fixed["exit_code"],
            "legacy_all_pass": legacy["all_pass"],
        })

    # The baseline is a fully covered report: the fixed adjudicator must accept it,
    # proving the observer is not trivially rejecting everything.
    # The required-blocked fixture proves the pre-fix coverage bug: the pre-fix
    # result-only gate wrongly passed a report with two required BLOCKED scenarios.
    record("required-blocked-fixture-pre-fix-passes", fixture_with_required_blocked, strict=False)
    for name, mutated in _mutations(strict_baseline):
        record(name, mutated, strict=True)
    all_controls_pass = strict_good["format_valid"] and strict_good["all_pass"] and all(
        (not item["fixed_all_pass"]) for item in controls)
    defect_targeting = [item for item in controls
                        if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-d15-4-negative-controls.v1",
        "known_good_unit_fixture_format_valid": good["format_valid"],
        "known_good_unit_fixture_all_pass": good["all_pass"],
        "control_count": len(controls),
        "controls": controls,
        "all_controls_pass": all_controls_pass,
        "defect_targeting_pre_fix_passed_count": len(defect_targeting),
        "defect_targeting_pre_fix_passed": [item["name"] for item in defect_targeting],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--allow-unit-fixture", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.selfcheck:
        result = selfcheck(contract)
        code = 0 if result["all_controls_pass"] and result["known_good_unit_fixture_format_valid"] else 1
    else:
        if args.observations is None:
            parser.error("--observations is required unless --selfcheck")
        observations = _load(args.observations)
        result = compute_verdict(contract, observations, allow_unit_fixture=args.allow_unit_fixture)
        code = result["exit_code"]
        print(json.dumps({"all_pass": result["all_pass"], "format_valid": result["format_valid"],
                          "required_coverage": result["required_coverage"],
                          "failed_scenarios": result["failed_scenarios"],
                          "uncovered_scenarios": result["uncovered_scenarios"],
                          "negatives_ok": result["negatives_ok"],
                          "failures": result["failures"],
                          "coverage_failures": result["coverage_failures"]}, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
