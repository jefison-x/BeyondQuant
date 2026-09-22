#!/usr/bin/env python3
"""Fail-able observer/verdict for the named D15 superseding assessment.

ADR-0084 replaces the *global* blocking role of the historical D15-G verdict with
the current required gate **BYQ session failure containment and business
recovery**. This observer produces a named, machine-readable, fail-able
superseding assessment that:

* references the historical D15-4/D15-5/D15-G verdicts without rewriting them;
* derives the *current* capability overlay from raw evidence (B1/B2
  ``BLOCKED_EXTERNAL``, B3/B4 candidate-layer ``PASS``);
* independently derives whether the ADR-0084 replacement gate passed and whether
  the coherent DSH ``0.1.5-rc.1`` repository default upgrade passed;
* derives candidate compatibility/promotion for the **actually adopted scope**;
* bounds the permissible R3 scope to the thin-supervisor safe-failure /
  observation / cleanup / new-generation-recovery range and keeps
  ``R3_RESUME = NO``;
* never reports native independent child resume as implemented.

Separation of concerns:

* ``format_valid`` — the assessment artifact is well formed and every required
  source evidence file exists and matches its recorded provenance hash.
* ``honest`` — every claimed component status, the claimed bounded R3 scope and
  the claimed decision equal the values the observer *independently derives* from
  the committed source evidence.
* ``decision`` / ``established`` — the independently derived decision. It is
  ``SUPERSEDING_ASSESSMENT_ESTABLISHED`` only when every required component equals
  its ADR-0084-consistent expected truth.
* ``all_pass`` — ``format_valid`` and ``honest`` and ``established``.

The observer is the gate: it exits non-zero when the assessment overclaims (e.g.
reports a BLOCKED_EXTERNAL capability as PASS, reports native child resume as
implemented, or claims R3 full resume), when a claimed status differs from the
derived status, when the replacement gate or the coherent upgrade did not
actually pass, when source evidence is missing/hash-mismatched or unreadable, or
when the assessment declares its own verdict/coverage fields. Insufficient
evidence fails closed to ``MISSING`` and never defaults to a pass.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"


class Failure(Exception):
    """Raised only for an unreadable contract/assessment/provenance artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _all_status_pass(mapping: object, expected: str = "PASS") -> bool:
    return isinstance(mapping, dict) and bool(mapping) and all(
        value == expected for value in mapping.values())


# ---------------------------------------------------------------------------
# Contract-authoritative derivation from the committed source evidence.
# ---------------------------------------------------------------------------

def _derive_historical_d15_g(sources: dict) -> str:
    verdict = sources.get("d15_g_verdict", {})
    matrix = sources.get("d15_g_capability_matrix", {})
    expected = {
        "subagent-child-crash",
        "subagent-byq-adapter-restart",
        "terminal-adapter-restart",
        "terminal-dsh-runtime-restart",
    }
    if not isinstance(verdict, dict) or not isinstance(matrix, dict):
        return "MISSING"
    derived_blockers = set(verdict.get("derived_blockers") or [])
    named_blockers = set(matrix.get("primary_named_blockers") or [])
    if (verdict.get("verdict") == "NO_GO"
            and verdict.get("all_pass") is False
            and derived_blockers == expected
            and named_blockers == expected):
        return "NO_GO_PRESERVED"
    return "REWRITTEN"


def _derive_replacement_gate(sources: dict) -> str:
    implementation = sources.get("business_recovery_verdict")
    acceptance = sources.get("business_recovery_acceptance_verdict")
    observations = sources.get("business_recovery_acceptance_observations")
    containment = sources.get("session_containment_verdict")
    if not all(isinstance(item, dict) for item in
               (implementation, acceptance, observations, containment)):
        return "MISSING"
    scenarios = acceptance.get("scenarios")
    if isinstance(scenarios, dict):
        scenario_results = [value.get("result") for value in scenarios.values()
                            if isinstance(value, dict)]
    elif isinstance(scenarios, list):
        scenario_results = [value.get("result") for value in scenarios
                            if isinstance(value, dict)]
    else:
        scenario_results = []
    cleanup = observations.get("cleanup")
    ok = (
        implementation.get("format_valid") is True
        and implementation.get("all_pass") is True
        and acceptance.get("format_valid") is True
        and acceptance.get("all_pass") is True
        and acceptance.get("required_count") == 9
        and len(scenario_results) == 9
        and all(result == "PASS" for result in scenario_results)
        and containment.get("format_valid") is True
        and containment.get("all_pass") is True
        and isinstance(cleanup, dict)
        and cleanup.get("production_untouched") is True
        and cleanup.get("containers_remaining") == 0
        and cleanup.get("networks_remaining") == 0
        and cleanup.get("volumes_remaining") == 0
    )
    return "PASS" if ok else "NOT_PASS"


def _derive_coherent_default_upgrade(sources: dict) -> str:
    upgrade = sources.get("default_upgrade")
    rollback = sources.get("default_upgrade_rollback")
    deployment = sources.get("deployment_config")
    if not all(isinstance(item, dict) for item in (upgrade, rollback, deployment)):
        return "MISSING"
    pairing = upgrade.get("pairing", {})
    readiness = upgrade.get("image", {}).get("readiness", {})
    intact = rollback.get("intact_artifacts", {})
    not_claimed = upgrade.get("not_claimed") or []
    ok = (
        upgrade.get("release") == "dsh-0.1.5rc1"
        and pairing.get("python_sdk") == "0.1.5rc1"
        and pairing.get("python_runtime_bin") == "0.1.5rc1"
        and pairing.get("bundled_npm") == "0.1.5-rc.1"
        and pairing.get("upstream_tag") == "dsh-v0.1.5-rc.1"
        and upgrade.get("default_selector", {}).get("selector_value") == "dsh-0.1.5rc1"
        and upgrade.get("default_selector", {}).get("compose_default")
        == "BYQ_DSH_COMPATIBILITY_RELEASE:-dsh-0.1.5rc1"
        and readiness.get("release_identity") == "matched"
        and readiness.get("release_id") == "dsh-0.1.5rc1"
        and rollback.get("prior_baseline") == "dsh-0.1.2rc1"
        and isinstance(intact, dict)
        and "config/dsh/releases/dsh-0.1.2rc1.json" in intact
        and deployment.get("default_release") == "dsh-0.1.5rc1"
        and deployment.get("candidate_releases") == ["dsh-0.1.2rc1"]
        and "production deployment" in not_claimed
        and "release/tag" in not_claimed
    )
    return "PASS" if ok else "FAIL"


def _provider_external_blocked(sources: dict) -> bool:
    for key in ("provider_rc2_verdict", "provider_alpha2_verdict"):
        verdict = sources.get(key)
        if not isinstance(verdict, dict):
            return False
        if verdict.get("external_blocked") is not True or verdict.get("all_pass") is not False:
            return False
        conclusions = verdict.get("conclusions", {})
        if conclusions.get("out_of_process_continuable_provider_available") is not False:
            return False
    return True


def _derive_b1(sources: dict) -> str:
    d15_4 = sources.get("d15_4_verdict", {})
    d15_4 = d15_4 if isinstance(d15_4, dict) else {}
    ok = (
        _provider_external_blocked(sources)
        and d15_4.get("required_coverage", {}).get("child-crash") == "BLOCKED"
    )
    return "BLOCKED_EXTERNAL" if ok else "NOT_BLOCKED"


def _derive_b2(sources: dict) -> str:
    verdict = sources.get("b2_verdict")
    d15_4 = sources.get("d15_4_verdict", {})
    d15_4 = d15_4 if isinstance(d15_4, dict) else {}
    if not isinstance(verdict, dict):
        return "MISSING"
    ok = (
        verdict.get("external_blocked") is True
        and verdict.get("all_pass") is False
        and verdict.get("result") == "BLOCKED"
        and verdict.get("conclusions", {}).get("byq_composition_child_rebind_surface_present")
        is False
        and d15_4.get("required_coverage", {}).get("byq-adapter-restart") == "BLOCKED"
    )
    return "BLOCKED_EXTERNAL" if ok else "NOT_BLOCKED"


def _candidate_verdict_pass(verdict: object) -> bool:
    if not isinstance(verdict, dict):
        return False
    return (
        verdict.get("all_pass") is True
        and verdict.get("format_valid") is True
        and verdict.get("required_coverage_ok") is True
        and _all_status_pass(verdict.get("required_coverage"))
    )


def _derive_b3(sources: dict) -> str:
    verdict = sources.get("b3_verdict")
    if not isinstance(verdict, dict):
        return "MISSING"
    return "PASS_CANDIDATE" if _candidate_verdict_pass(verdict) else "FAIL"


def _derive_b4(sources: dict) -> str:
    verdict = sources.get("b4_verdict")
    overlay = sources.get("b4_current_overlay", {})
    overlay = overlay if isinstance(overlay, dict) else {}
    current = overlay.get("current_state_after_b4", {})
    historical = overlay.get("historical_snapshot", {}).get("d15_g", {})
    consistent = (
        isinstance(current, dict)
        and str(current.get("terminal_dsh_runtime_restart", "")).startswith("PASS")
        and isinstance(historical, dict)
        and historical.get("verdict") == "NO_GO"
    )
    if not isinstance(verdict, dict):
        return "MISSING"
    return "PASS_CANDIDATE" if (_candidate_verdict_pass(verdict) and consistent) else "FAIL"


def _derive_native_independent_child_resume(sources: dict, derived: dict) -> str:
    if (derived.get("b1_subagent_child_crash") == "BLOCKED_EXTERNAL"
            and derived.get("b2_subagent_byq_adapter_restart") == "BLOCKED_EXTERNAL"
            and _provider_external_blocked(sources)):
        return "NOT_IMPLEMENTED"
    return "IMPLEMENTED"


def _derive_candidate_compatibility(derived: dict) -> str:
    ok = (
        derived.get("replacement_gate_business_recovery") == "PASS"
        and derived.get("coherent_dsh_default_upgrade") == "PASS"
        and derived.get("b3_terminal_adapter_restart") == "PASS_CANDIDATE"
        and derived.get("b4_terminal_dsh_runtime_restart") == "PASS_CANDIDATE"
    )
    return "PASS" if ok else "FAIL"


def _derive_candidate_promotion(sources: dict, derived: dict) -> str:
    deployment = sources.get("deployment_config")
    if not isinstance(deployment, dict):
        return "MISSING"
    ok = (
        deployment.get("default_release") == "dsh-0.1.5rc1"
        and deployment.get("candidate_releases") == ["dsh-0.1.2rc1"]
        and derived.get("coherent_dsh_default_upgrade") == "PASS"
    )
    return "REPO_DEFAULT_PROMOTED" if ok else "NOT_PROMOTED"


def _derive_r3_permitted_scope(contract: dict, derived: dict) -> list[str]:
    if (derived.get("replacement_gate_business_recovery") == "PASS"
            and derived.get("b1_subagent_child_crash") == "BLOCKED_EXTERNAL"
            and derived.get("b2_subagent_byq_adapter_restart") == "BLOCKED_EXTERNAL"):
        return list(contract["r3_permitted_scope_expected"])
    return []


def _derive_r3_resume(derived: dict) -> str:
    # A full unfreeze requires the native independent child capability to be
    # implemented and B1/B2 to no longer be external blockers. Fail closed to NO.
    if (derived.get("b1_subagent_child_crash") == "PASS"
            and derived.get("b2_subagent_byq_adapter_restart") == "PASS"
            and derived.get("native_independent_child_resume") == "IMPLEMENTED"):
        return "YES"
    return "NO"


def derive_components(contract: dict, sources: dict) -> dict[str, str]:
    derived: dict[str, str] = {}
    for component in contract["required_components"]:
        cid = component["id"]
        if cid == "historical_d15_g":
            derived[cid] = _derive_historical_d15_g(sources)
        elif cid == "replacement_gate_business_recovery":
            derived[cid] = _derive_replacement_gate(sources)
        elif cid == "coherent_dsh_default_upgrade":
            derived[cid] = _derive_coherent_default_upgrade(sources)
        elif cid == "b1_subagent_child_crash":
            derived[cid] = _derive_b1(sources)
        elif cid == "b2_subagent_byq_adapter_restart":
            derived[cid] = _derive_b2(sources)
        elif cid == "b3_terminal_adapter_restart":
            derived[cid] = _derive_b3(sources)
        elif cid == "b4_terminal_dsh_runtime_restart":
            derived[cid] = _derive_b4(sources)
        elif cid == "native_independent_child_resume":
            derived[cid] = _derive_native_independent_child_resume(sources, derived)
        elif cid == "candidate_compatibility_actual_scope":
            derived[cid] = _derive_candidate_compatibility(derived)
        elif cid == "candidate_promotion_actual_scope":
            derived[cid] = _derive_candidate_promotion(sources, derived)
        elif cid == "r3_resume":
            derived[cid] = _derive_r3_resume(derived)
        else:
            derived[cid] = "MISSING"
    return derived


def compute_assessment(contract: dict, sources: dict, assessment: dict, *,
                       provenance: dict | None = None, root: Path | None = None) -> dict:
    failures: list[str] = []
    honesty_failures: list[str] = []

    if not isinstance(assessment, dict):
        raise Failure("assessment must be an object")

    candidate = contract["candidate"]
    observed_candidate = assessment.get("candidate")
    if (not isinstance(observed_candidate, dict)
            or observed_candidate.get("release") != candidate["release"]):
        failures.append(
            f"candidate mismatch: expected {candidate['release']!r}, got {observed_candidate!r}")

    for forbidden in contract.get("forbidden_assessment_fields", []):
        if forbidden in assessment:
            failures.append(
                f"assessment may not declare its own '{forbidden}' field; the contract is authoritative")

    if assessment.get("assessment_id") != contract.get("assessment_id"):
        failures.append(f"assessment_id mismatch: {assessment.get('assessment_id')!r}")

    claimed_decision = assessment.get("decision")
    if claimed_decision not in contract.get("decision_vocabulary", []):
        failures.append(f"invalid decision {claimed_decision!r}")

    required = {item["id"]: item for item in contract["required_components"]}
    derived_components = derive_components(contract, sources)

    claimed_components = assessment.get("components")
    if not isinstance(claimed_components, dict):
        failures.append("assessment.components must be an object")
        claimed_components = {}
    if set(claimed_components) != set(required):
        missing = sorted(set(required) - set(claimed_components))
        extra = sorted(set(claimed_components) - set(required))
        failures.append(
            f"component set mismatch: missing={missing} extra={extra} (closed set)")
    for cid in sorted(set(required) & set(claimed_components)):
        claimed = claimed_components.get(cid)
        derived = derived_components.get(cid, "MISSING")
        if claimed not in contract.get("status_vocabulary", []):
            failures.append(f"component {cid!r} has invalid claimed status {claimed!r}")
        elif claimed != derived:
            honesty_failures.append(
                f"component {cid!r} claimed {claimed!r} but derived {derived!r}")

    # The bounded R3 scope is derived; a claim may not widen or drop it.
    derived_scope = _derive_r3_permitted_scope(contract, derived_components)
    claimed_scope = assessment.get("r3_permitted_scope")
    if not isinstance(claimed_scope, list) or not all(_is_nonempty_str(item) for item in claimed_scope):
        failures.append("assessment.r3_permitted_scope must be a list of non-empty scope ids")
        claimed_scope = []
    else:
        claimed_scope = list(claimed_scope)
        if claimed_scope != derived_scope:
            honesty_failures.append(
                f"r3_permitted_scope {claimed_scope} does not equal the derived bounded scope {derived_scope}")

    # Every required component must equal its ADR-0084-consistent expected truth.
    expected_mismatch = {
        cid: {"expected": item["expected"], "derived": derived_components.get(cid, "MISSING")}
        for cid, item in required.items()
        if derived_components.get(cid, "MISSING") != item["expected"]
    }
    established = not expected_mismatch
    derived_decision = ("SUPERSEDING_ASSESSMENT_ESTABLISHED" if established
                        else "SUPERSEDING_ASSESSMENT_NOT_ESTABLISHED")

    if (claimed_decision in contract.get("decision_vocabulary", [])
            and claimed_decision != derived_decision):
        honesty_failures.append(
            f"decision claims {claimed_decision!r} but the derived decision is {derived_decision!r}")

    # Provenance-verified source evidence (real run only).
    if provenance is not None:
        entries = provenance.get("artifacts")
        by_path = {}
        if isinstance(entries, list):
            by_path = {item.get("path"): item for item in entries if isinstance(item, dict)}
        base = root or ROOT
        for artifact in contract.get("source_artifacts", []):
            path = base / artifact["path"]
            if not path.is_file():
                failures.append(f"missing source evidence: {artifact['path']}")
                continue
            entry = by_path.get(artifact["path"])
            if entry is None:
                failures.append(f"source evidence not provenance-verified: {artifact['path']}")
            elif entry.get("sha256") != _digest(path):
                failures.append(f"source evidence hash mismatch: {artifact['path']}")

    format_valid = not failures
    honest = not honesty_failures
    assessment_valid = format_valid and honest
    all_pass = assessment_valid and established
    return {
        "schema_version": "byq-d15-superseding-verdict.v1",
        "assessment_id": contract.get("assessment_id"),
        "all_pass": all_pass,
        "assessment_valid": assessment_valid,
        "format_valid": format_valid,
        "honest": honest,
        "established": established,
        "decision": derived_decision,
        "decision_claimed": claimed_decision,
        "expected_component_mismatch": expected_mismatch,
        "candidate": candidate,
        "decision_vocabulary": list(contract.get("decision_vocabulary", [])),
        "required_component_count": len(required),
        "derived_components": derived_components,
        "claimed_components": {key: claimed_components.get(key) for key in required},
        "expected_components": {key: item["expected"] for key, item in required.items()},
        "derived_r3_permitted_scope": derived_scope,
        "claimed_r3_permitted_scope": claimed_scope,
        "constraints": contract.get("constraints", {}),
        "r3_resume": contract.get("constraints", {}).get("r3_resume"),
        "native_independent_child_resume": derived_components.get("native_independent_child_resume"),
        "production_promotion_model": "repository-default-only; production deployment/release/tag remain separate (none claimed)",
        "failures": failures,
        "honesty_failures": honesty_failures,
        "exit_code": 0 if all_pass else 1,
    }


# ---------------------------------------------------------------------------
# Legacy (pre-fix) algorithm: trusts the report's own decision/claims.
# ---------------------------------------------------------------------------

def legacy_compute_assessment(contract: dict, sources: dict, assessment: dict) -> dict:
    """Pre-fix algorithm: the report's claimed decision and component statuses were trusted.

    It never derived component statuses from the source evidence, never bounded the
    R3 scope and never verified the replacement gate, so an overclaiming report
    passed.
    """
    failures: list[str] = []
    if assessment.get("decision") not in contract.get("decision_vocabulary", []):
        failures.append("invalid decision")
    claimed = assessment.get("components")
    if isinstance(claimed, dict):
        for value in claimed.values():
            if value not in contract.get("status_vocabulary", []):
                failures.append(f"invalid claimed status {value!r}")
    else:
        failures.append("missing claimed components")
    all_pass = not failures
    return {"algorithm": "legacy-pre-fix", "all_pass": all_pass,
            "exit_code": 0 if all_pass else 1, "failures": failures}


# ---------------------------------------------------------------------------
# Unit fixtures + negative controls (selfcheck).
# ---------------------------------------------------------------------------

_ALL_PASS_B3 = {"adapter-restart-native-survives": "PASS",
                "adapter-restart-native-lost": "PASS"}
_ALL_PASS_B4 = {"dsh-runtime-restart-terminal-lost": "PASS",
                "surviving-pty-without-attachment-lost": "PASS"}


def _sources(*, acceptance_all_pass: bool = True, upgrade_coherent: bool = True,
             provider_blocked: bool = True, b3_pass: bool = True, b4_pass: bool = True,
             deployment_default: str = "dsh-0.1.5rc1",
             d15_4_child_crash: str = "BLOCKED",
             d15_4_adapter_restart: str = "BLOCKED") -> dict:
    b3_coverage = _ALL_PASS_B3 if b3_pass else {"adapter-restart-native-survives": "PASS",
                                                "adapter-restart-native-lost": "BLOCKED"}
    b4_coverage = _ALL_PASS_B4 if b4_pass else {"dsh-runtime-restart-terminal-lost": "PASS",
                                                "surviving-pty-without-attachment-lost": "BLOCKED"}
    provider_external = provider_blocked
    return {
        "d15_g_verdict": {
            "verdict": "NO_GO", "all_pass": False,
            "derived_blockers": ["subagent-child-crash", "subagent-byq-adapter-restart",
                                 "terminal-adapter-restart", "terminal-dsh-runtime-restart"],
        },
        "d15_g_capability_matrix": {
            "primary_named_blockers": ["subagent-child-crash", "subagent-byq-adapter-restart",
                                       "terminal-adapter-restart",
                                       "terminal-dsh-runtime-restart"],
        },
        "d15_4_verdict": {
            "required_coverage": {"child-crash": d15_4_child_crash,
                                  "byq-adapter-restart": d15_4_adapter_restart},
        },
        "d15_5_verdict": {"required_coverage": {"adapter-restart": "BLOCKED",
                                                "dsh-runtime-restart": "BLOCKED"}},
        "b2_verdict": {
            "external_blocked": True, "all_pass": False, "result": "BLOCKED",
            "conclusions": {"byq_composition_child_rebind_surface_present": False},
        },
        "b3_verdict": {
            "all_pass": b3_pass, "format_valid": True, "required_coverage_ok": b3_pass,
            "required_coverage": b3_coverage,
        },
        "b4_verdict": {
            "all_pass": b4_pass, "format_valid": True, "required_coverage_ok": b4_pass,
            "required_coverage": b4_coverage,
        },
        "b4_current_overlay": {
            "current_state_after_b4": {"terminal_dsh_runtime_restart": "PASS (candidate/qualification layer)"},
            "historical_snapshot": {"d15_g": {"verdict": "NO_GO"}},
        },
        "provider_rc2_verdict": {
            "external_blocked": provider_external, "all_pass": False,
            "conclusions": {"out_of_process_continuable_provider_available": not provider_external},
        },
        "provider_alpha2_verdict": {
            "external_blocked": provider_external, "all_pass": False,
            "conclusions": {"out_of_process_continuable_provider_available": not provider_external},
        },
        "business_recovery_verdict": {"format_valid": True, "all_pass": True},
        "business_recovery_acceptance_verdict": {
            "format_valid": True, "all_pass": acceptance_all_pass, "required_count": 9,
            "scenarios": {f"s{i}": {"result": "PASS" if acceptance_all_pass else "FAIL"}
                          for i in range(9)},
        },
        "business_recovery_acceptance_observations": {
            "cleanup": {"production_untouched": True, "containers_remaining": 0,
                        "networks_remaining": 0, "volumes_remaining": 0},
        },
        "session_containment_verdict": {"format_valid": True, "all_pass": True},
        "default_upgrade": {
            "release": "dsh-0.1.5rc1",
            "pairing": {"python_sdk": "0.1.5rc1", "python_runtime_bin": "0.1.5rc1",
                        "bundled_npm": "0.1.5-rc.1", "upstream_tag": "dsh-v0.1.5-rc.1"},
            "default_selector": {"selector_value": "dsh-0.1.5rc1",
                                 "compose_default": "BYQ_DSH_COMPATIBILITY_RELEASE:-dsh-0.1.5rc1"},
            "image": {"readiness": {
                "release_identity": "matched" if upgrade_coherent else "mismatch",
                "release_id": "dsh-0.1.5rc1" if upgrade_coherent else "dsh-0.1.2rc1"}},
            "not_claimed": ["production deployment", "release/tag", "D15 superseding assessment"],
        },
        "default_upgrade_rollback": {
            "prior_baseline": "dsh-0.1.2rc1",
            "intact_artifacts": {"config/dsh/releases/dsh-0.1.2rc1.json": {"sha256": "x"}},
        },
        "deployment_config": {"default_release": deployment_default,
                              "candidate_releases": ["dsh-0.1.2rc1"]},
    }


def _decision(contract: dict, sources: dict, decision: str | None = None,
              *, component_override: dict | None = None,
              scope_override: list[str] | None = None) -> dict:
    derived = derive_components(contract, sources)
    expected = {c["id"]: c["expected"] for c in contract["required_components"]}
    established = all(derived.get(cid) == expected[cid] for cid in expected)
    derived_scope = _derive_r3_permitted_scope(contract, derived)
    if component_override:
        derived = {**derived, **component_override}
    return {
        "schema_version": "byq-d15-superseding-assessment-input.v1",
        "assessment_id": contract["assessment_id"],
        "candidate": dict(contract["candidate"]),
        "decision": decision or ("SUPERSEDING_ASSESSMENT_ESTABLISHED" if established
                                 else "SUPERSEDING_ASSESSMENT_NOT_ESTABLISHED"),
        "components": {c["id"]: derived[c["id"]] for c in contract["required_components"]},
        "r3_permitted_scope": scope_override if scope_override is not None else list(derived_scope),
        "constraints": dict(contract["constraints"]),
        "provenance": "docs/evidence/d15/d15-superseding/provenance.v1.json",
    }


def good_fixture(contract: dict) -> tuple[dict, dict]:
    sources = _sources()
    return sources, _decision(contract, sources)


def real_fixture(contract: dict) -> tuple[dict, dict]:
    # Same truthful state as the real committed evidence; the harness is used for
    # unit/negative tests only.
    return good_fixture(contract)


def _mutations(contract: dict) -> list[tuple[str, dict, dict]]:
    good_sources, good = good_fixture(contract)
    mutations: list[tuple[str, dict, dict]] = []

    def add(name: str, mutate, *, sources: dict | None = None) -> None:
        value = copy.deepcopy(good)
        mutate(value)
        mutations.append((name, sources or good_sources, value))

    # Overclaims: report a BLOCKED_EXTERNAL item as PASS.
    add("claim-b1-pass", lambda v: v["components"].update({"b1_subagent_child_crash": "PASS"}))
    add("claim-b2-pass",
        lambda v: v["components"].update({"b2_subagent_byq_adapter_restart": "PASS"}))
    # Claim native independent child resume implemented.
    add("claim-native-child-resume-implemented",
        lambda v: v["components"].update({"native_independent_child_resume": "IMPLEMENTED"}))
    # Overclaim the replacement gate / coherent upgrade.
    add("claim-replacement-gate-pass-when-source-failed",
        lambda v: v["components"].update({"replacement_gate_business_recovery": "PASS"}),
        sources=_sources(acceptance_all_pass=False))
    add("claim-upgrade-pass-when-source-incoherent",
        lambda v: v["components"].update({"coherent_dsh_default_upgrade": "PASS"}),
        sources=_sources(upgrade_coherent=False))
    # Claim B3/B4 PASS while their sources are not.
    add("claim-b3-pass-when-source-blocked",
        lambda v: v["components"].update({"b3_terminal_adapter_restart": "PASS_CANDIDATE"}),
        sources=_sources(b3_pass=False))
    add("claim-b4-pass-when-source-blocked",
        lambda v: v["components"].update({"b4_terminal_dsh_runtime_restart": "PASS_CANDIDATE"}),
        sources=_sources(b4_pass=False))
    # Rewrite the historical D15-G verdict as a GO/pass.
    rewritten = copy.deepcopy(good_sources)
    rewritten["d15_g_verdict"] = {"verdict": "GO", "all_pass": True, "derived_blockers": []}
    rewritten["d15_g_capability_matrix"] = {"primary_named_blockers": []}
    add("rewrite-historical-d15-g", lambda v: None, sources=rewritten)
    # Claim R3 full resume.
    add("claim-r3-resume-yes", lambda v: v["components"].update({"r3_resume": "YES"}))
    # Widen / drop the bounded R3 scope.
    add("widen-r3-scope",
        lambda v: v.update({"r3_permitted_scope": ["safe_failure", "observation", "cleanup",
                                                   "new_generation_recovery", "full_runtime_continuity"]}))
    add("drop-r3-scope", lambda v: v.update({"r3_permitted_scope": []}))
    # Claim promotion beyond the repository default.
    add("claim-production-promotion",
        lambda v: v["components"].update({"candidate_promotion_actual_scope": "PRODUCTION_PROMOTED"}))
    # Candidate mismatch / invalid decision.
    add("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    add("invalid-decision", lambda v: v.update({"decision": "MAYBE"}))
    # Self-declared verdict/coverage/established fields.
    add("self-declared-verdict", lambda v: v.update({"self_declared_verdict": "ESTABLISHED"}))
    add("self-declared-established", lambda v: v.update({"assessment_established": True}))
    add("self-declared-coverage", lambda v: v.update({"coverage": {"all": "PASS"}}))
    # Missing / extra component (closed set).
    add("drop-required-component", lambda v: v["components"].pop("r3_resume"))
    add("extra-component", lambda v: v["components"].update({"unknown": "PASS"}))
    # A not-established source set claimed ESTABLISHED.
    blocked_sources = _sources(d15_4_child_crash="PASS", d15_4_adapter_restart="PASS",
                               provider_blocked=False)
    add("claim-established-when-not", lambda v: None, sources=blocked_sources)
    # Missing deployment default (not promoted).
    add("claim-promoted-when-not",
        lambda v: v["components"].update({"candidate_promotion_actual_scope": "REPO_DEFAULT_PROMOTED"}),
        sources=_sources(deployment_default="dsh-0.1.2rc1"))
    return mutations


def selfcheck(contract: dict) -> dict:
    good_sources, good_decision = good_fixture(contract)
    good = compute_assessment(contract, good_sources, good_decision)

    controls = []
    for name, sources, assessment in _mutations(contract):
        fixed = compute_assessment(contract, sources, assessment)
        legacy = legacy_compute_assessment(contract, sources, assessment)
        controls.append({
            "name": name,
            "fixed_all_pass": fixed["all_pass"],
            "fixed_exit_code": fixed["exit_code"],
            "fixed_decision": fixed["decision"],
            "legacy_all_pass": legacy["all_pass"],
        })
    all_controls_rejected = all(not item["fixed_all_pass"] for item in controls)
    defect_targeting = [item for item in controls
                        if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-d15-superseding-negative-controls.v1",
        "known_good_fixture_all_pass": good["all_pass"],
        "known_good_fixture_decision": good["decision"],
        "known_good_fixture_components": good["derived_components"],
        "control_count": len(controls),
        "controls": controls,
        "all_controls_rejected": all_controls_rejected,
        "defect_targeting_pre_fix_passed_count": len(defect_targeting),
        "defect_targeting_pre_fix_passed": [item["name"] for item in defect_targeting],
    }


def load_sources(contract: dict, root: Path) -> dict:
    sources: dict[str, Any] = {}
    for artifact in contract.get("source_artifacts", []):
        sources[artifact["id"]] = _load(root / artifact["path"])
    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--assessment", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.selfcheck:
        result = selfcheck(contract)
        code = 0 if (result["all_controls_rejected"]
                     and result["known_good_fixture_all_pass"]) else 1
    else:
        if args.assessment is None:
            parser.error("--assessment is required unless --selfcheck")
        sources = load_sources(contract, args.root)
        provenance = _load(args.provenance) if args.provenance else None
        result = compute_assessment(contract, sources, _load(args.assessment),
                                    provenance=provenance, root=args.root)
        code = result["exit_code"]
        print(json.dumps({
            "assessment_id": result["assessment_id"],
            "decision": result["decision"],
            "all_pass": result["all_pass"],
            "established": result["established"],
            "honest": result["honest"],
            "format_valid": result["format_valid"],
            "derived_r3_permitted_scope": result["derived_r3_permitted_scope"],
            "expected_component_mismatch": result["expected_component_mismatch"],
            "failures": result["failures"],
            "honesty_failures": result["honesty_failures"],
        }, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
