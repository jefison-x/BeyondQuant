#!/usr/bin/env python3
"""Fail-able observer for the 0.9 step-5 B2 slice `subagent-byq-adapter-restart`.

It adjudicates a composition/restart observation produced by
``byq_adapter_restart_probe.py`` (generation A + generation B + process
identity). Separation of concerns:

* ``format_valid`` — the observation is structurally sound: it matches the
  contract candidate, owner node, evidence class, isolation constraints and
  contains both generations plus the process identity.
* ``all_pass`` — B2 is qualified: generation A really reached `startContinuable`
  and persisted exactly one child linked to the original delegation/goal, AND a
  FRESH OS process rebound that same child through a committed BYQ composition
  surface, delivered a message with a message id, settled exactly once, was
  owner/generation/epoch fail-closed, created no extra child and no second
  session store, and left no orphan.

The observer derives the rebind capability from the enumerated surfaces and the
composition's own forbidden-tool list; it never trusts a self-declared boolean
or a label. A discovery that merely *claims* a rebind (label-only) always fails
``all_pass``. ``legacy_compute_verdict`` is the reconstructed pre-fix
result-trusting gate, used only to prove the controls are defect-targeting.

Usage:
  python3 byq_adapter_restart_observer.py --selfcheck --out <controls.json>
  python3 byq_adapter_restart_observer.py --observation <obs.json> \\
      --out <verdict.json> [--blocked-out <external-blocked.json>]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "byq_adapter_restart_contract.v1.json"


class Failure(Exception):
    """Raised only for an unreadable contract/observation artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _generation_a_reasons(gen_a: dict) -> list[str]:
    reasons: list[str] = []
    if gen_a.get("start_continuable_reached") is not True:
        reasons.append("generation A did not reach a real startContinuable path")
    if not _nonempty(gen_a.get("child_id")):
        reasons.append("generation A has no precise persisted child id")
    if gen_a.get("child_persisted") is not True:
        reasons.append("generation A did not persist the child session")
    if gen_a.get("child_linked_to_root") is not True:
        reasons.append("the persisted child is not linked to the original delegation/goal")
    if gen_a.get("started_child_count") != 1:
        reasons.append("generation A did not start exactly one child")
    if not _nonempty(gen_a.get("delegation_call_id")):
        reasons.append("generation A has no delegation call id")
    return reasons


def _surfaces(observation: dict, gen_b: dict) -> tuple[list[str], set[str]]:
    surfaces = gen_b.get("byq_adapter_surfaces")
    surfaces = surfaces if isinstance(surfaces, dict) else {}
    composition = observation.get("composition") if isinstance(observation.get("composition"), dict) else {}
    forbidden = set(surfaces.get("forbidden_tools") or composition.get("forbidden_tools") or [])
    candidates = [item for item in (gen_b.get("child_rebind_candidates") or [])
                  if isinstance(item, str)]
    return candidates, forbidden


def _derive(contract: dict, observation: dict) -> dict[str, Any]:
    gen_a = observation.get("generation_a") if isinstance(observation.get("generation_a"), dict) else {}
    gen_b = observation.get("generation_b") if isinstance(observation.get("generation_b"), dict) else {}
    identity = observation.get("process_identity") if isinstance(
        observation.get("process_identity"), dict) else {}
    candidates, forbidden = _surfaces(observation, gen_b)

    # A committed BYQ composition surface exists only if a candidate is not
    # itself disabled by the composition's own forbidden-tool list.
    allowed_candidates = sorted(item for item in candidates if item not in forbidden)
    surface_present = bool(allowed_candidates)

    fresh_process = identity.get("new_os_process") is True and identity.get("fresh_container") is True
    message_id = gen_b.get("message_id")
    delivered = gen_b.get("child_message_delivered") is True and _nonempty(message_id)
    rebind = gen_b.get("child_rebind_via_byq_composition") is True and surface_present and delivered
    settlement_ok = gen_b.get("exactly_once_settlement_on_resumed_turn") is True
    fencing_ok = gen_b.get("owner_generation_epoch_fail_closed") is True
    same_child = gen_b.get("child_persisted_same_id") is True
    no_extra = (gen_b.get("extra_child_created") is False
                and gen_a.get("started_child_count") == 1)
    no_second_store = gen_b.get("second_session_store_created") is False
    orphans_ok = gen_b.get("orphans") == 0

    generation_a_reasons = _generation_a_reasons(gen_a)
    generation_b_reasons: list[str] = []
    if not fresh_process:
        generation_b_reasons.append("generation B is not a fresh OS process")
    if not surface_present:
        generation_b_reasons.append(
            "no committed BYQ composition surface can rebind the persisted continuable child")
    elif not rebind:
        generation_b_reasons.append(
            "a declared composition surface did not actually rebind and deliver to the child")
    if not same_child:
        generation_b_reasons.append("the persisted child id is not retained")
    if not settlement_ok:
        generation_b_reasons.append("the resumed child turn does not settle exactly once")
    if not fencing_ok:
        generation_b_reasons.append("owner/generation/epoch fencing is not fail-closed")
    if not no_extra:
        generation_b_reasons.append("an extra child was created")
    if not no_second_store:
        generation_b_reasons.append("a second session store was introduced")
    if not orphans_ok:
        generation_b_reasons.append("orphan processes/sessions remain after cleanup")

    return {
        "surface_present": surface_present,
        "allowed_candidates": allowed_candidates,
        "forbidden_tools": sorted(forbidden),
        "fresh_process": fresh_process,
        "rebind": rebind,
        "delivered": delivered,
        "settlement_ok": settlement_ok,
        "fencing_ok": fencing_ok,
        "same_child": same_child,
        "no_extra": no_extra,
        "no_second_store": no_second_store,
        "orphans_ok": orphans_ok,
        "generation_a_reasons": generation_a_reasons,
        "generation_b_reasons": generation_b_reasons,
    }


def _format_failures(contract: dict, observation: dict, derived: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if observation.get("schema_version") != "byq-v090-step5-b2-adapter-restart-observation.v1":
        failures.append("observation schema_version mismatch")
    if observation.get("blocker") != contract["blocker"]:
        failures.append("observation blocker mismatch")
    if observation.get("owner_node") != contract["owner_node"]:
        failures.append("observation owner_node mismatch")
    candidate = observation.get("candidate") if isinstance(observation.get("candidate"), dict) else {}
    for key, expected in contract["candidate"].items():
        if candidate.get(key) != expected:
            failures.append(f"candidate.{key} expected {expected!r} got {candidate.get(key)!r}")
    if observation.get("evidence_class") != contract["required_evidence_class"]:
        if observation.get("evidence_class") != "unit-fixture":
            failures.append("observation evidence class is not a real isolated candidate observation")
    llm = observation.get("llm") if isinstance(observation.get("llm"), dict) else {}
    if llm.get("real_llm_quality") is not False:
        failures.append("observation must not claim real-LLM quality")
    isolation = observation.get("isolation") if isinstance(observation.get("isolation"), dict) else {}
    if isolation.get("production_selector_changed") is not False:
        failures.append("observation must not change the production selector")
    if isolation.get("fork_or_patch_of_dsh") is not False:
        failures.append("observation must not fork or patch DSH")
    if not isinstance(observation.get("generation_a"), dict):
        failures.append("missing generation A record")
    if not isinstance(observation.get("generation_b"), dict):
        failures.append("missing generation B record")
    if not isinstance(observation.get("process_identity"), dict):
        failures.append("missing process identity record")
    substitutions = observation.get("substitutions_rejected")
    if not isinstance(substitutions, list) or not substitutions:
        failures.append("observation must record the rejected substitutions")
    gen_b = observation.get("generation_b") if isinstance(observation.get("generation_b"), dict) else {}
    if gen_b.get("substitution"):
        failures.append(f"a forbidden substitution was recorded: {gen_b['substitution']!r}")
    return failures


def compute_verdict(contract: dict, observation: dict, *, allow_unit_fixture: bool = False) -> dict:
    derived = _derive(contract, observation)
    failures = _format_failures(contract, observation, derived)
    if observation.get("evidence_class") == "unit-fixture" and not allow_unit_fixture:
        failures.append("unit fixture is not runtime evidence")

    format_valid = not failures
    all_pass = (
        format_valid
        and not derived["generation_a_reasons"]
        and derived["fresh_process"]
        and derived["surface_present"]
        and derived["rebind"]
        and derived["settlement_ok"]
        and derived["fencing_ok"]
        and derived["same_child"]
        and derived["no_extra"]
        and derived["no_second_store"]
        and derived["orphans_ok"]
    )

    blocked_reasons: list[str] = []
    if derived["generation_a_reasons"]:
        blocked_reasons.extend(derived["generation_a_reasons"])
    blocked_reasons.extend(derived["generation_b_reasons"])
    if not blocked_reasons:
        blocked_reasons.append("no qualifying BYQ composition child rebind was observed")

    return {
        "schema_version": "byq-v090-step5-b2-adapter-restart-verdict.v1",
        "blocker": contract["blocker"],
        "owner_node": contract["owner_node"],
        "format_valid": format_valid,
        "all_pass": all_pass,
        "qualification_passed": all_pass,
        "result": "PASS" if all_pass else "BLOCKED",
        "exit_code": 0 if all_pass else 1,
        "external_blocked": (not all_pass) and (not derived["surface_present"]),
        "conclusions": {
            "generation_a_ok": not derived["generation_a_reasons"],
            "fresh_os_process": derived["fresh_process"],
            "byq_composition_child_rebind_surface_present": derived["surface_present"],
            "allowed_child_rebind_surfaces": derived["allowed_candidates"],
            "composition_forbidden_tools": derived["forbidden_tools"],
            "child_rebound_from_fresh_process": derived["rebind"],
            "settlement_exactly_once": derived["settlement_ok"],
            "owner_generation_epoch_fail_closed": derived["fencing_ok"],
        },
        "failures": failures,
        "blocked_reasons": blocked_reasons,
    }


def legacy_compute_verdict(contract: dict, observation: dict) -> dict:
    """Reconstructed pre-fix result-trusting gate: trusts self-declared booleans."""
    gen_b = observation.get("generation_b") if isinstance(observation.get("generation_b"), dict) else {}
    conclusions = observation.get("conclusions") if isinstance(observation.get("conclusions"), dict) else {}
    ok = (
        observation.get("evidence_class") == contract["required_evidence_class"]
        and (observation.get("status") == "PASS"
             or conclusions.get("child_rebound_from_fresh_process") is True
             or gen_b.get("child_rebind_via_byq_composition") is True)
    )
    return {"all_pass": bool(ok), "format_valid": True, "exit_code": 0 if ok else 1}


def external_blocked_evidence(contract: dict, observation: dict, verdict: dict) -> dict:
    return {
        "schema_version": "byq-v090-step5-b2-adapter-restart-external-blocked.v1",
        "blocker": contract["blocker"],
        "owner_node": contract["owner_node"],
        "status": "BLOCKED",
        "is_external": True,
        "available_in_0_1_5_rc1": False,
        "required_provider": contract["external_dependency"]["option_1"],
        "rejected_option": contract["external_dependency"]["option_2"],
        "composition_evidence": [
            "docs/evidence/v090-step5-b2-adapter-restart/composition-restart.v1.json",
            "plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/byq-product.identity.json",
            "docs/evidence/d15/d15-4/continuable/continuable-adapter-restart.v1.json",
        ],
        "observations": verdict["conclusions"],
        "downstream_not_started": [
            "terminal-adapter-restart",
            "terminal-dsh-runtime-restart",
            "d15-g-rerun",
            "r3-thin-supervisor",
        ],
        "external_dependency_resolution": "an upstream out-of-process provider implementing "
                                          "SubagentProvider.prepareContinuable must land and be qualified; "
                                          "BYQ must not build a second harness or a child-resume bridge",
        "upstream_resolution": "ADR-0082 Option 1 (future upstream DSH provider); Option 2 rejected",
        "constraints": {
            "r3_resume": "NO",
            "d15_frozen": True,
            "r3_frozen": True,
            "production_selector": "dsh-0.1.2rc1",
            "deployment": "none",
            "release_or_tag_created": False,
            "fork_or_patch_of_dsh": False,
        },
        "non_actions": [
            "No BYQ child-resume bridge (ADR-0082 Option 2 rejected)",
            "No second session store and no second generic harness",
            "No in-process child or owning-process restart used as a rebind",
            "No root resume_session presented as a child rebind",
            "No D15/R3 unfreeze",
            "No production selector/default switch",
            "No deployment, tag or release",
        ],
    }


def _valid_generation_a() -> dict:
    return {
        "status": "PASS",
        "start_continuable_reached": True,
        "child_id": "11111111-2222-3333-4444-555555555555",
        "child_persisted": True,
        "child_linked_to_root": True,
        "child_parent_session": "root-session",
        "started_child_count": 1,
        "delegation_call_id": "delegate-call-1",
        "original_goal_ref": "root-session",
        "settlement_count": 1,
        "duplicate_settlement": False,
    }


def _valid_generation_b() -> dict:
    return {
        "status": "BLOCKED",
        "byq_adapter_surfaces": {
            "adapter_public_surfaces": ["resume_session", "submit_prompt"],
            "child_rebind_candidates": [],
            "forbidden_tools": ["subagent", "send_message", "list_agents"],
        },
        "child_rebind_candidates": [],
        "child_rebind_via_byq_composition": False,
        "child_message_delivered": False,
        "message_id": None,
        "owner_generation_epoch_fail_closed": "no_rebind_surface_to_fence",
        "child_persisted_same_id": True,
        "extra_child_created": False,
        "second_session_store_created": False,
        "orphans": 0,
    }


def valid_fixture(contract: dict) -> dict:
    """Synthetic UNIT fixture of the real BLOCKED observation. Never runtime evidence."""
    return {
        "schema_version": "byq-v090-step5-b2-adapter-restart-observation.v1",
        "blocker": contract["blocker"],
        "owner_node": contract["owner_node"],
        "candidate": dict(contract["candidate"]),
        "evidence_class": "unit-fixture",
        "llm": {"class": "scripted-keyless", "real_llm_quality": False},
        "isolation": {"production_selector_changed": False, "fork_or_patch_of_dsh": False},
        "composition": {"profile": "byq-product-continuable-candidate",
                        "forbidden_tools": ["subagent", "send_message", "list_agents"]},
        "generation_a": _valid_generation_a(),
        "generation_b": _valid_generation_b(),
        "process_identity": {"generation_a_pid": 101, "generation_b_pid": 202,
                             "new_os_process": True, "fresh_container": True},
        "substitutions_rejected": ["byq-child-resume-bridge", "root-resume-as-child-rebind"],
    }


def _fully_qualified_fixture(contract: dict) -> dict:
    """Synthetic fully-qualified observation: a real BYQ composition surface
    rebinds the same child from a fresh OS process with exactly-once settlement.
    Proves the observer can PASS when the evidence is real."""
    fixture = valid_fixture(contract)
    fixture["evidence_class"] = contract["required_evidence_class"]
    fixture["generation_a"]["settlement_count"] = 1
    fixture["generation_b"].update({
        "status": "PASS",
        "child_rebind_candidates": ["composition_rebind_continuable_child"],
        "child_rebind_via_byq_composition": True,
        "child_message_delivered": True,
        "message_id": "msg-b2-1",
        "exactly_once_settlement_on_resumed_turn": True,
        "owner_generation_epoch_fail_closed": True,
        "child_persisted_same_id": True,
        "extra_child_created": False,
        "second_session_store_created": False,
        "orphans": 0,
    })
    fixture["generation_b"]["byq_adapter_surfaces"] = {
        "adapter_public_surfaces": ["resume_session", "composition_rebind_continuable_child"],
        "child_rebind_candidates": ["composition_rebind_continuable_child"],
        "forbidden_tools": ["subagent", "send_message", "list_agents"],
    }
    return fixture


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    mutations: list[tuple[str, dict]] = []

    def add(name: str, mutate) -> None:
        value = copy.deepcopy(fixture)
        mutate(value)
        mutations.append((name, value))

    def gen_b(value: dict) -> dict:
        return value["generation_b"]

    def gen_a(value: dict) -> dict:
        return value["generation_a"]

    add("label-only-claim", lambda v: gen_b(v).update(
        {"child_rebind_candidates": [], "message_id": None, "child_message_delivered": False,
         "child_rebind_via_byq_composition": True}))
    add("no-rebind-candidates", lambda v: (
        gen_b(v).update({"child_rebind_candidates": []}),
        gen_b(v)["byq_adapter_surfaces"].update({"child_rebind_candidates": []})))
    add("same-os-process", lambda v: v["process_identity"].update(
        {"new_os_process": False, "generation_a_pid": 7, "generation_b_pid": 7}))
    add("same-container-not-fresh", lambda v: v["process_identity"].update({"fresh_container": False}))
    add("no-child-persistence", lambda v: gen_a(v).update({"child_persisted": False}))
    add("child-not-linked-to-goal", lambda v: gen_a(v).update({"child_linked_to_root": False}))
    add("extra-child-created", lambda v: (gen_a(v).update({"started_child_count": 2}),
                                          gen_b(v).update({"extra_child_created": True})))
    add("second-session-store", lambda v: gen_b(v).update({"second_session_store_created": True}))
    add("orphan-left-behind", lambda v: gen_b(v).update({"orphans": 1}))
    add("duplicate-settlement-on-resume", lambda v: gen_b(v).update(
        {"exactly_once_settlement_on_resumed_turn": False}))
    add("rebind-without-message-id", lambda v: gen_b(v).update({"message_id": None}))
    add("rebind-without-delivery", lambda v: gen_b(v).update({"child_message_delivered": False}))
    add("fencing-not-fail-closed", lambda v: gen_b(v).update(
        {"owner_generation_epoch_fail_closed": "stale_epoch_accepted"}))
    add("stale-epoch-rebind-accepted", lambda v: gen_b(v).update(
        {"owner_generation_epoch_fail_closed": "accepted_stale_generation"}))
    add("composition-forbids-but-claims-surface", lambda v: (
        gen_b(v).update({"child_rebind_candidates": ["send_message"]}),
        gen_b(v)["byq_adapter_surfaces"].update(
            {"child_rebind_candidates": ["send_message"],
             "forbidden_tools": ["send_message", "list_agents", "subagent"]})))
    add("generation-a-no-startContinuable", lambda v: gen_a(v).update(
        {"start_continuable_reached": False, "delegate_result": {"kind": "foreground"}}))
    add("generation-a-no-child-id", lambda v: gen_a(v).update({"child_id": None}))
    add("generation-a-no-delegation-call", lambda v: gen_a(v).update({"delegation_call_id": None}))
    add("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    add("non-real-evidence-class", lambda v: v.update({"evidence_class": "format-layer"}))
    add("llm-claims-real-quality", lambda v: v["llm"].update({"real_llm_quality": True}))
    add("production-selector-changed", lambda v: v["isolation"].update(
        {"production_selector_changed": True}))
    add("fork-or-patch-of-dsh", lambda v: v["isolation"].update({"fork_or_patch_of_dsh": True}))
    add("forbidden-substitution-bridge", lambda v: gen_b(v).update(
        {"substitution": "byq-child-resume-bridge"}))
    add("wrong-owner-node", lambda v: v.update({"owner_node": "r6-full-runtime-continuity"}))
    add("no-substitutions-recorded", lambda v: v.update({"substitutions_rejected": []}))
    return mutations


def selfcheck(contract: dict) -> dict:
    baseline = _fully_qualified_fixture(contract)
    strict_good = compute_verdict(contract, baseline, allow_unit_fixture=False)
    controls: list[dict] = []

    def record(name: str, mutated: dict, *, strict: bool = True) -> None:
        fixed = compute_verdict(contract, mutated, allow_unit_fixture=not strict)
        legacy = legacy_compute_verdict(contract, mutated)
        controls.append({
            "name": name,
            "fixed_all_pass": fixed["all_pass"],
            "fixed_exit_code": fixed["exit_code"],
            "legacy_all_pass": legacy["all_pass"],
        })

    record("blocked-fixture-pre-fix-passes", valid_fixture(contract), strict=False)
    for name, mutated in _mutations(baseline):
        record(name, mutated, strict=True)

    all_controls_pass = strict_good["all_pass"] and all(
        (not item["fixed_all_pass"]) for item in controls)
    defect_targeting = [item for item in controls
                        if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-v090-step5-b2-adapter-restart-negative-controls.v1",
        "known_good_unit_fixture_all_pass": strict_good["all_pass"],
        "control_count": len(controls),
        "controls": controls,
        "all_controls_pass": all_controls_pass,
        "defect_targeting_pre_fix_passed_count": len(defect_targeting),
        "defect_targeting_pre_fix_passed": [item["name"] for item in defect_targeting],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--blocked-out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--allow-unit-fixture", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.selfcheck:
        result = selfcheck(contract)
        code = 0 if result["all_controls_pass"] else 1
    else:
        if args.observation is None:
            parser.error("--observation is required unless --selfcheck")
        observation = _load(args.observation)
        result = compute_verdict(contract, observation, allow_unit_fixture=args.allow_unit_fixture)
        code = result["exit_code"]
        if args.blocked_out is not None and result["external_blocked"]:
            blocked = external_blocked_evidence(contract, observation, result)
            args.blocked_out.parent.mkdir(parents=True, exist_ok=True)
            args.blocked_out.write_text(json.dumps(blocked, indent=2) + "\n", encoding="utf-8")

    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps({
        "result": result.get("result", "SELFCHECK"),
        "format_valid": result.get("format_valid"),
        "all_pass": result.get("all_pass"),
        "all_controls_pass": result.get("all_controls_pass"),
        "blocked_reasons": result.get("blocked_reasons", []),
        "control_count": result.get("control_count"),
    }, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
