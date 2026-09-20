#!/usr/bin/env python3
"""Fail-able observer/verdict for the D15-4 candidate continuable wiring.

Two separate questions are answered:

* ``wiring_ok`` / ``format_valid`` — the candidate-specific profile is exactly the
  contract's continuable wiring, the production 0.1.2 profile is still the
  foreground one-shot wiring (byte-identical to a fresh generation), and every
  delegate keeps its ``provider: spawn``, tool filter and MCP boundary. This is a
  deterministic source check.
* ``all_pass`` — the qualification passed: every REQUIRED scenario is present and
  PASS with all contract assertions derived from raw observations, no scenario
  FAILed, every fault-requiring scenario applied a fault, every negative was
  rejected, and there are no structural violations. A REQUIRED scenario left
  ``NOT_RUN``/``BLOCKED``/``MISSING`` fails the verdict while preserving its
  reason.

The contract is the only source of truth for required scenarios, required
assertions and fault requirements. An observation may not declare its own
coverage/continuity rules. Missing evidence is never a pass and a measured value
is never defaulted.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "continuable_wiring_contract.v1.json"


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
# deterministic source-level wiring checks
# ---------------------------------------------------------------------------

def _delegate_blocks(patch_text: str) -> dict[str, dict[str, str]]:
    """Group the patch by `- id: delegate-*` blocks and extract delegate keys.

    `provider` precedes `toolName` in the generated block, so grouping by the
    delegate id (not by toolName) is required to capture it.
    """

    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in patch_text.splitlines():
        line = raw.strip()
        if line.startswith("- id: delegate"):
            current = {}
            continue
        if line.startswith("- id: ") and current is not None:
            current = None
            continue
        if current is None or ":" not in line or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key == "toolName":
            current["__toolName"] = value.strip()
        elif key in {"provider", "enableRunInBackground", "backgroundMode", "maxDepth"}:
            current[key] = value.strip()
        if current.get("__toolName") is not None:
            blocks[current["__toolName"]] = current
    return blocks


def _allowlists(patch_text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    in_allow = False
    for raw in patch_text.splitlines():
        line = raw.strip()
        if line.startswith("toolName: "):
            current = line.split("toolName: ", 1)[1].strip()
        elif line == "allow:" and current is not None:
            in_allow = True
            result.setdefault(current, [])
        elif in_allow and line.startswith("- "):
            result[current].append(line[2:].strip())
        elif in_allow and line and not line.startswith("- "):
            in_allow = False
    return result


def check_wiring(contract: dict) -> dict[str, Any]:
    failures: list[str] = []
    candidate_path = ROOT / contract["candidate_patch"]
    production_path = ROOT / contract["production_patch"]
    candidate_text = candidate_path.read_text(encoding="utf-8")
    production_text = production_path.read_text(encoding="utf-8")
    expected = contract["expected_candidate_wiring"]
    delegates = list(contract["delegates"])

    candidate_blocks = _delegate_blocks(candidate_text)
    for delegate in delegates:
        block = candidate_blocks.get(delegate)
        if block is None:
            failures.append(f"candidate patch is missing delegate {delegate}")
            continue
        if block.get("provider") != expected["provider"]:
            failures.append(f"{delegate}: provider {block.get('provider')!r} != {expected['provider']!r}")
        if block.get("backgroundMode") != expected["backgroundMode"]:
            failures.append(f"{delegate}: backgroundMode {block.get('backgroundMode')!r} != continuable")
        if block.get("enableRunInBackground") != str(expected["enableRunInBackground"]).lower():
            failures.append(f"{delegate}: enableRunInBackground not true")

    production = contract["expected_production_wiring"]
    production_blocks = _delegate_blocks(production_text)
    for delegate in delegates:
        block = production_blocks.get(delegate)
        if block is None:
            failures.append(f"production patch is missing delegate {delegate}")
            continue
        if block.get("backgroundMode") != production["backgroundMode"]:
            failures.append(f"production {delegate}: backgroundMode changed to {block.get('backgroundMode')!r}")
        if block.get("enableRunInBackground") != str(production["enableRunInBackground"]).lower():
            failures.append(f"production {delegate}: enableRunInBackground changed")

    # Permission/MCP boundary preservation: both profiles must expose the same
    # delegate allow-lists and the same fail-closed MCP client.
    candidate_allow = _allowlists(candidate_text)
    production_allow = _allowlists(production_text)
    if candidate_allow != production_allow:
        failures.append("candidate delegate tool filters differ from the production profile")
    for marker in ("failOnStartupError: true", "name: '@deepseek-ai/dsh-mcp-client'",
                   "serverName: byq"):
        if marker not in candidate_text:
            failures.append(f"candidate patch lost MCP boundary marker {marker!r}")
    # Only the 5 delegates may be continuable; no unexpected continuable tool.
    continuable_lines = [line.strip() for line in candidate_text.splitlines()
                         if line.strip() == "backgroundMode: continuable"]
    if len(continuable_lines) != len(delegates):
        failures.append(f"candidate patch has {len(continuable_lines)} continuable delegates, expected {len(delegates)}")

    return {
        "wiring_ok": not failures,
        "failures": failures,
        "candidate_patch": contract["candidate_patch"],
        "production_patch": contract["production_patch"],
        "delegates": delegates,
        "candidate_blocks": candidate_blocks,
        "production_blocks": production_blocks,
        "candidate_allowlists": candidate_allow,
        "production_allowlists": production_allow,
    }


def production_patch_is_regenerated() -> dict[str, Any]:
    """Prove the production profile was not changed by the continuable wiring."""

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/dsh/candidate_profile.py"), "check"],
        capture_output=True, text=True, timeout=60,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip()[-400:]}


# ---------------------------------------------------------------------------
# contract-authoritative assertion derivation from raw observations
# ---------------------------------------------------------------------------

def _result_shape(obs: dict) -> dict[str, bool]:
    return {
        "continuable_result_kind": obs.get("resultKind") == "continuable",
        "subagent_id_present": _is_nonempty_str(obs.get("subagentId")),
        "start_continuable_reached": _is_int(obs.get("startContinuableCalls"))
        and obs.get("startContinuableCalls") == 1,
        "provider_spawn_preserved": obs.get("provider") == "spawn",
    }


def _child_persistence(obs: dict) -> dict[str, bool]:
    return {
        "child_store_exists": obs.get("childStoreExists") is True,
        "descriptor_mode_continuable": obs.get("descriptorMode") == "continuable",
        "parent_link_recorded": _is_nonempty_str(obs.get("parentSession"))
        and obs.get("parentSession") == obs.get("parentId"),
        "origin_subagent": obs.get("origin") == "subagent",
    }


def _settlement_exactly_once(obs: dict) -> dict[str, bool]:
    count = obs.get("settlementCount")
    turns = obs.get("childTurnCount")
    return {
        "settlement_count_matches_child_turns": _is_int(count) and _is_int(turns)
        and count == turns and count >= 1,
        "no_duplicate_settlement": obs.get("duplicateSettlement") is False,
    }


def _lease_goal(obs: dict) -> dict[str, bool]:
    return {
        "delegation_call_id_recorded": _is_nonempty_str(obs.get("delegationCallId")),
        "original_goal_recorded": _is_nonempty_str(obs.get("originalGoalId")),
        "child_linked_to_goal": obs.get("linkedToOriginalGoal") is True,
    }


def _no_orphan(obs: dict) -> dict[str, bool]:
    return {
        "parent_run_ended": obs.get("parentRunEnded") is True,
        "no_unsettled_child": _is_int(obs.get("unsettledChildCount"))
        and obs.get("unsettledChildCount") == 0,
        "child_remains_addressable": obs.get("childRemainsAddressable") is True,
    }


def _adapter_restart_cold_resume(obs: dict) -> dict[str, bool]:
    count = obs.get("resumedSettlementCount")
    return {
        "new_os_process": obs.get("newOsProcess") is True
        and _is_int(obs.get("generationAProcessId")) and _is_int(obs.get("generationBProcessId"))
        and obs.get("generationAProcessId") != obs.get("generationBProcessId"),
        "same_child_id": obs.get("sameChildId") is True,
        "sequence_contiguous": obs.get("sequenceContiguous") is True,
        "settlement_exactly_once": _is_int(count) and count == 1,
        "no_duplicate_settlement": obs.get("duplicateSettlement") is False,
    }


def _child_crash(obs: dict) -> dict[str, bool]:
    return {
        "child_id_retained": obs.get("childIdRetained") is True,
        "truthful_failure": obs.get("truthfulFailure") is True,
        "natively_resumable": obs.get("nativelyResumable") is True,
        "no_fabricated_completion": obs.get("fabricatedCompletion") is not True,
    }


def _byq_compose_restart(obs: dict) -> dict[str, bool]:
    return {
        "container_restart_observed": obs.get("containerRestart") is True,
        "child_resumed_via_byq_surface": obs.get("childResumedViaByqSurface") is True,
        "same_child_id": obs.get("sameChildId") is True,
        "no_duplicate_settlement": obs.get("duplicateSettlement") is False,
    }


def _child_run_fault(obs: dict) -> dict[str, bool]:
    resume = obs.get("resume") if isinstance(obs.get("resume"), dict) else {}
    return {
        "child_id_retained": obs.get("childIdRetained") is True,
        "parent_truthful_failure": obs.get("parentTruthfulFailure") is True,
        "natively_resumable": resume.get("nativelyResumable") is True,
        "no_fabricated_completion": obs.get("fabricatedCompletion") is not True,
    }


_ASSERTION_DERIVERS: dict[str, Callable[[dict], dict[str, bool]]] = {
    "delegate-result-shape": _result_shape,
    "child-id-persistence": _child_persistence,
    "settlement-exactly-once": _settlement_exactly_once,
    "lease-linked-to-original-goal": _lease_goal,
    "no-orphan-after-parent-end": _no_orphan,
    "adapter-restart-cold-resume": _adapter_restart_cold_resume,
    "child-crash": _child_crash,
    "byq-compose-adapter-restart": _byq_compose_restart,
    "child-run-fault": _child_run_fault,
}


def _check_scenario(scenario: dict, spec: dict, failures: list[str]) -> dict:
    scenario_id = scenario.get("id")
    ctx = f"scenario[{scenario_id}]"
    result = scenario.get("result")
    required = bool(spec.get("required", False))
    expected_assertions = list(spec.get("assertions", []))
    row: dict[str, Any] = {"id": scenario_id, "result": result, "required": required,
                           "assertions": {}, "assertions_ok": False}

    for forbidden_field in ("required", "assertions_ok", "coverage",
                            "allowed_continuity", "forbidden_continuity"):
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
        failures.append(f"{ctx}: false assertions {false_names}")
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


def compute_verdict(contract: dict, observations: dict, *, allow_unit_fixture: bool = False,
                    include_wiring: bool = True) -> dict:
    failures: list[str] = []
    coverage_failures: list[str] = []

    if not isinstance(observations, dict):
        raise Failure("observations must be an object")

    wiring = check_wiring(contract) if include_wiring else {"wiring_ok": True, "failures": []}
    if include_wiring and not wiring["wiring_ok"]:
        failures.extend(f"wiring: {item}" for item in wiring["failures"])

    candidate = contract["candidate"]
    observed_candidate = observations.get("candidate")
    if not isinstance(observed_candidate, dict) or observed_candidate.get("release") != candidate["release"]:
        failures.append(f"candidate mismatch: expected {candidate['release']!r}, got {observed_candidate!r}")
    if observations.get("evidence_class") != contract["evidence_class"]:
        failures.append(f"evidence_class mismatch: {observations.get('evidence_class')!r}")
    llm = observations.get("llm") if isinstance(observations.get("llm"), dict) else {}
    if llm.get("class") != contract["llm_evidence_class"]:
        failures.append(f"llm class mismatch: {llm.get('class')!r}")
    if llm.get("real_llm_quality") is not False:
        failures.append("llm evidence must explicitly claim real_llm_quality=false")

    required = {spec["id"]: spec for spec in contract["required_scenarios"]}
    optional = {spec["id"]: spec for spec in contract["optional_scenarios"]}
    known = set(required) | set(optional)

    scenarios = observations.get("scenarios")
    if not isinstance(scenarios, list):
        raise Failure("observations.scenarios must be a list")
    seen: set[str] = set()
    rows: list[dict] = []
    coverage: dict[str, str] = {}
    optional_coverage: dict[str, str] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            failures.append("scenario entry is not an object")
            continue
        scenario_id = scenario.get("id")
        if scenario_id in seen:
            failures.append(f"duplicate scenario id {scenario_id!r}")
            continue
        if scenario_id not in known:
            failures.append(f"unknown scenario id {scenario_id!r} (closed set)")
            continue
        seen.add(scenario_id)
        spec = required.get(scenario_id) or optional[scenario_id]
        row = _check_scenario(scenario, spec, failures)
        rows.append(row)
        if scenario_id in required:
            coverage[scenario_id] = row["result"]
        else:
            optional_coverage[scenario_id] = row["result"]

    for scenario_id in required:
        if scenario_id not in seen:
            coverage[scenario_id] = "MISSING"
            coverage_failures.append(f"required scenario {scenario_id!r} is missing")
    for scenario_id, spec in required.items():
        if coverage.get(scenario_id) != "PASS":
            coverage_failures.append(
                f"required scenario {scenario_id!r} is {coverage.get(scenario_id)}")
    for scenario_id, spec in optional.items():
        if scenario_id not in seen:
            optional_coverage[scenario_id] = "MISSING"

    negative_rows = _check_negatives(observations, contract, failures)

    format_valid = not failures
    all_pass = format_valid and not coverage_failures
    return {
        "schema_version": "byq-d15-4-continuable-verdict.v1",
        "format_valid": format_valid,
        "all_pass": all_pass,
        "wiring_ok": wiring["wiring_ok"],
        "wiring": wiring if include_wiring else None,
        "candidate": candidate,
        "required_coverage": coverage,
        "optional_coverage": optional_coverage,
        "required_coverage_ok": not coverage_failures,
        "reason_uncovered": coverage_failures,
        "failures": failures,
        "scenarios": rows,
        "negatives": negative_rows,
        "explicit_non_claims": [
            "no full D15-4 pass unless every required scenario is PASS",
            "no independent child-process capability; no new provider; R3_RESUME = NO",
            "scripted keyless provider: not real-LLM-quality semantic evidence",
        ],
    }


def legacy_compute_verdict(contract: dict, observations: dict) -> dict:
    """The pre-fix result-only gate: PASS if every observed scenario says PASS.

    It ignores required coverage, contract assertions, fault requirements and
    negatives. Used only by the selfcheck to prove defect targeting.
    """

    scenarios = observations.get("scenarios") or []
    # The pre-fix gate only re-read the observed result column: no required
    # coverage, no contract assertions, no fault requirement, no negatives.
    ok = bool(scenarios) and not any(item.get("result") == "FAIL" for item in scenarios)
    return {"all_pass": ok, "legacy": True}


# ---------------------------------------------------------------------------
# fixtures + negative controls
# ---------------------------------------------------------------------------

def _obs_identity() -> dict:
    return {"resultKind": "continuable", "subagentId": "child-1", "startContinuableCalls": 1,
            "provider": "spawn"}


def valid_fixture(contract: dict) -> dict:
    evidence = contract["evidence_class"]
    base_obs = {
        "delegate-result-shape": _obs_identity(),
        "child-id-persistence": {"childStoreExists": True, "descriptorMode": "continuable",
                                 "parentSession": "d15-4-parent", "parentId": "d15-4-parent",
                                 "origin": "subagent"},
        "settlement-exactly-once": {"settlementCount": 1, "childTurnCount": 1,
                                    "duplicateSettlement": False},
        "lease-linked-to-original-goal": {"delegationCallId": "call-1",
                                          "originalGoalId": "goal-1",
                                          "linkedToOriginalGoal": True},
        "no-orphan-after-parent-end": {"parentRunEnded": True, "unsettledChildCount": 0,
                                       "childRemainsAddressable": True},
        "adapter-restart-cold-resume": {"newOsProcess": True, "generationAProcessId": 111,
                                        "generationBProcessId": 222, "sameChildId": True,
                                        "sequenceContiguous": True, "resumedSettlementCount": 1,
                                        "duplicateSettlement": False},
        "child-crash": {"childIdRetained": True, "truthfulFailure": True,
                        "nativelyResumable": True, "fabricatedCompletion": False},
        "byq-compose-adapter-restart": {"containerRestart": True,
                                        "childResumedViaByqSurface": True,
                                        "sameChildId": True, "duplicateSettlement": False},
        "child-run-fault": {"childIdRetained": True, "parentTruthfulFailure": True,
                            "resume": {"nativelyResumable": True}, "fabricatedCompletion": False},
    }
    scenarios = []
    for spec in contract["required_scenarios"]:
        scenarios.append({"id": spec["id"], "result": "PASS", "fault_applied": True,
                          "observation": copy.deepcopy(base_obs[spec["id"]])})
    for spec in contract["optional_scenarios"]:
        if spec["id"] in base_obs:
            scenarios.append({"id": spec["id"], "result": "PASS", "fault_applied": True,
                              "observation": copy.deepcopy(base_obs[spec["id"]])})
        else:
            scenarios.append({"id": spec["id"], "result": "NOT_RUN",
                              "not_run_reason": "host reboot not authorized"})
    negatives = [{"kind": f"negative-{index}", "rejected": True, "errorCode": "X"}
                 for index in range(3)]
    return {"schema_version": "byq-d15-4-continuable-observations.v1",
            "evidence_class": evidence,
            "candidate": dict(contract["candidate"]),
            "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False},
            "scenarios": scenarios, "negatives": negatives}


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    """Named single-defect mutations; each must make the fixed gate fail."""
    mutations: list[tuple[str, dict]] = []

    def mutate(name: str, fn: Callable[[dict], None]) -> None:
        item = copy.deepcopy(fixture)
        fn(item)
        mutations.append((name, item))

    def scenario_id(item: dict, scenario_id: str) -> dict:
        return next(s for s in item["scenarios"] if s["id"] == scenario_id)

    mutate("result-kind-foreground", lambda i: scenario_id(i, "delegate-result-shape")[
        "observation"].__setitem__("resultKind", "foreground"))
    mutate("child-not-persisted", lambda i: scenario_id(i, "child-id-persistence")[
        "observation"].__setitem__("childStoreExists", False))
    mutate("descriptor-not-continuable", lambda i: scenario_id(i, "child-id-persistence")[
        "observation"].__setitem__("descriptorMode", "one-shot"))
    mutate("parent-link-wrong", lambda i: scenario_id(i, "child-id-persistence")[
        "observation"].__setitem__("parentSession", "other-parent"))
    mutate("duplicate-settlement", lambda i: scenario_id(i, "settlement-exactly-once")[
        "observation"].__setitem__("duplicateSettlement", True))
    mutate("settlement-count-mismatch", lambda i: scenario_id(i, "settlement-exactly-once")[
        "observation"].__setitem__("childTurnCount", 2))
    mutate("goal-link-missing", lambda i: scenario_id(i, "lease-linked-to-original-goal")[
        "observation"].__setitem__("linkedToOriginalGoal", False))
    mutate("orphan-child", lambda i: scenario_id(i, "no-orphan-after-parent-end")[
        "observation"].__setitem__("unsettledChildCount", 1))
    mutate("same-os-process", lambda i: scenario_id(i, "adapter-restart-cold-resume")[
        "observation"].__setitem__("generationBProcessId", 111))
    mutate("cold-resume-not-contiguous", lambda i: scenario_id(i, "adapter-restart-cold-resume")[
        "observation"].__setitem__("sequenceContiguous", False))
    mutate("cold-resume-duplicate-settlement", lambda i: scenario_id(i, "adapter-restart-cold-resume")[
        "observation"].__setitem__("duplicateSettlement", True))
    mutate("child-crash-fabricated-completion", lambda i: scenario_id(i, "child-crash")[
        "observation"].__setitem__("fabricatedCompletion", True))
    mutate("compose-not-restarted", lambda i: scenario_id(i, "byq-compose-adapter-restart")[
        "observation"].__setitem__("containerRestart", False))
    mutate("compose-no-byq-surface", lambda i: scenario_id(i, "byq-compose-adapter-restart")[
        "observation"].__setitem__("childResumedViaByqSurface", False))
    mutate("required-blocked", lambda i: scenario_id(i, "adapter-restart-cold-resume").update(
        {"result": "BLOCKED", "not_run_reason": "not run"}))
    mutate("required-not-run", lambda i: scenario_id(i, "child-crash").update(
        {"result": "NOT_RUN", "not_run_reason": "not run"}))
    mutate("required-missing", lambda i: i.__setitem__(
        "scenarios", [s for s in i["scenarios"] if s["id"] != "child-id-persistence"]))
    mutate("fault-not-applied", lambda i: scenario_id(i, "adapter-restart-cold-resume").__setitem__(
        "fault_applied", False))
    mutate("false-llm-quality", lambda i: i["llm"].__setitem__("real_llm_quality", True))
    mutate("non-native-evidence", lambda i: i.__setitem__("evidence_class", "format-layer"))
    mutate("candidate-mismatch", lambda i: i["candidate"].__setitem__("release", "dsh-0.1.2rc1"))
    mutate("negative-not-rejected", lambda i: i["negatives"][0].__setitem__("rejected", False))
    mutate("self-declared-coverage", lambda i: scenario_id(i, "child-crash").__setitem__(
        "required", False))
    mutate("duplicate-scenario-id", lambda i: i["scenarios"].append(
        copy.deepcopy(scenario_id(i, "child-crash"))))
    mutate("unknown-scenario-id", lambda i: i["scenarios"].append(
        {"id": "totally-unknown", "result": "PASS", "observation": {}}))
    return mutations


def selfcheck(contract: dict) -> dict:
    good = valid_fixture(contract)
    good_verdict = compute_verdict(contract, good)
    controls = []
    for name, mutated in _mutations(good):
        fixed = compute_verdict(contract, mutated)
        legacy = legacy_compute_verdict(contract, mutated)
        controls.append({
            "name": name,
            "fixed_all_pass": fixed["all_pass"],
            "legacy_all_pass": legacy["all_pass"],
        })
    defect_targeting = [item for item in controls if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-d15-4-continuable-negative-controls.v1",
        "control_count": len(controls),
        "all_controls_pass": all(not item["fixed_all_pass"] for item in controls),
        "known_good_fixture_all_pass": good_verdict["all_pass"],
        "defect_targeting_pre_fix_passed_count": len(defect_targeting),
        "controls": controls,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--wiring", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.wiring:
        wiring = check_wiring(contract)
        wiring["production_patch_regenerated"] = production_patch_is_regenerated()
        wiring["schema_version"] = "byq-d15-4-continuable-wiring.v1"
        wiring["candidate"] = contract["candidate"]
        wiring["expected_candidate_wiring"] = contract["expected_candidate_wiring"]
        wiring["expected_production_wiring"] = contract["expected_production_wiring"]
        text = json.dumps(wiring, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(text)
        regenerated_ok = wiring["production_patch_regenerated"]["returncode"] == 0
        return 0 if wiring["wiring_ok"] and regenerated_ok else 1

    if args.selfcheck:
        result = selfcheck(contract)
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(text)
        return 0 if result["all_controls_pass"] and result["known_good_fixture_all_pass"] else 1

    if args.observations is None:
        parser.error("--observations is required unless --selfcheck")
    observations = _load(args.observations)
    verdict = compute_verdict(contract, observations)
    text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps({"all_pass": verdict["all_pass"], "format_valid": verdict["format_valid"],
                      "wiring_ok": verdict["wiring_ok"],
                      "reason_uncovered": verdict["reason_uncovered"]}, indent=2))
    return 0 if verdict["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
