#!/usr/bin/env python3
"""Fail-able observer for the 0.9 step-5 B1 slice `subagent-child-crash`.

The observer adjudicates a capability-discovery artifact produced by
``child_provider_discovery.mjs``. Separation of concerns:

* ``format_valid`` — the discovery is structurally sound: it matches the contract
  providers, candidate, evidence class, provenance and the native capability gate,
  and it has no boot/registration error.
* ``all_pass`` — B1 is qualified: an OUT-OF-PROCESS provider that implements
  ``prepareContinuable`` is actually present AND a real child-only SIGKILL
  qualification (real child pid death, live parent, truthful failed settlement,
  retained child id, native resume or truthful loss, zero orphans) is recorded.

The observer derives the capability from the provider list and the qualification
record; it never trusts a self-declared ``conclusions`` boolean or the Python
evidence-class string. A discovery that merely *claims* the capability (a
label-only report) always fails ``all_pass``. ``legacy_compute_verdict`` is the
reconstructed pre-fix "result-only" gate, used only to prove the controls are
defect-targeting.

Usage:
  python3 child_provider_remediation_observer.py --selfcheck --out <controls.json>
  python3 child_provider_remediation_observer.py --discovery <discovery.json> \\
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
DEFAULT_CONTRACT = HERE / "child_provider_remediation_contract.v1.json"


class Failure(Exception):
    """Raised only for an unreadable contract/discovery artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _provider_map(discovery: dict) -> dict[str, dict]:
    providers = discovery.get("providers")
    if not isinstance(providers, list):
        return {}
    return {item.get("name"): item for item in providers if isinstance(item, dict)}


def _derive(contract: dict, discovery: dict) -> dict[str, Any]:
    providers = _provider_map(discovery)
    required = contract["required_providers"]

    required_shape_ok = True
    for spec in required:
        record = providers.get(spec["name"])
        if record is None:
            required_shape_ok = False
            continue
        if record.get("package") != spec["package"]:
            required_shape_ok = False
        if record.get("boundary") != spec["boundary"]:
            required_shape_ok = False
        if record.get("in_candidate_bundle") is not spec["in_candidate_bundle"]:
            required_shape_ok = False

    out_of_process_continuable = sorted(
        name for name, record in providers.items()
        if record.get("boundary") == "out-of-process"
        and record.get("prepare_continuable_present") is True)
    in_process_continuable = sorted(
        name for name, record in providers.items()
        if record.get("boundary") == "in-process"
        and record.get("prepare_continuable_present") is True)

    bundled_oop = [spec["name"] for spec in required if spec["boundary"] == "out-of-process"]
    gate = contract["required_gate"]
    oop_rejected = all(
        providers.get(name, {}).get("prepare_continuable_present") is True
        or (
            providers.get(name, {}).get("prepare_continuable_present") is False
            and isinstance(providers.get(name, {}).get("gate"), dict)
            and providers[name]["gate"].get("kind") == "unsupported-capability"
            and providers[name]["gate"].get("errorCode") == gate["out_of_process_rejection_code"]
        )
        for name in bundled_oop)

    qualification = discovery.get("child_crash_qualification")
    qualification_reasons: list[str] = []
    if not isinstance(qualification, dict):
        qualification_reasons.append("no real child-crash qualification record")
    else:
        required_fields = contract["child_crash_qualification_required_fields"]
        for field, expected in required_fields.items():
            if qualification.get(field) != expected:
                qualification_reasons.append(
                    f"child-crash qualification field {field!r} expected {expected!r} "
                    f"got {qualification.get(field)!r}")
        if "substitution" in qualification:
            qualification_reasons.append(
                f"forbidden substitution recorded: {qualification['substitution']!r}")
        if not _is_int(qualification.get("child_pid")) or qualification.get("child_pid") <= 0:
            qualification_reasons.append("child-crash qualification has no real positive child pid")

    return {
        "providers": providers,
        "required_shape_ok": required_shape_ok,
        "out_of_process_continuable": out_of_process_continuable,
        "in_process_continuable": in_process_continuable,
        "out_of_process_rejected": oop_rejected,
        "qualification_ok": not qualification_reasons,
        "qualification_reasons": qualification_reasons,
    }


def _format_failures(contract: dict, discovery: dict, derived: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if discovery.get("schema_version") != "byq-v090-d15-child-provider-discovery.v1":
        failures.append("discovery schema_version mismatch")
    candidate = discovery.get("candidate") if isinstance(discovery.get("candidate"), dict) else {}
    for key, expected in contract["candidate"].items():
        if candidate.get(key) != expected:
            failures.append(f"candidate.{key} expected {expected!r} got {candidate.get(key)!r}")
    if discovery.get("evidence_class") != contract["required_evidence_class"]:
        failures.append("discovery evidence class is not native-runtime-isolated")
    if discovery.get("boot_error") is not None:
        failures.append("provider boot error recorded")
    if not derived["providers"]:
        failures.append("no providers recorded")
    if not derived["required_shape_ok"]:
        failures.append("required provider set/shape/boundary/capability mismatch")
    if not derived["out_of_process_rejected"]:
        failures.append("a bundled out-of-process provider was not rejected by the native gate")
    llm = discovery.get("llm") if isinstance(discovery.get("llm"), dict) else {}
    if llm.get("real_llm_quality") is not False:
        failures.append("discovery must not claim real-LLM quality")
    provenance = discovery.get("provenance") if isinstance(discovery.get("provenance"), dict) else {}
    archive = provenance.get("archive")
    if isinstance(archive, dict) and archive.get("matches_declaration") is not True:
        failures.append("candidate source archive sha256 does not match the declaration")
    return failures


def compute_verdict(contract: dict, discovery: dict, *, allow_unit_fixture: bool = False) -> dict:
    derived = _derive(contract, discovery)
    failures = _format_failures(contract, discovery, derived)
    if discovery.get("evidence_class") == "unit-fixture" and not allow_unit_fixture:
        failures.append("unit fixture is not runtime evidence")

    capability_found = bool(derived["out_of_process_continuable"])
    qualification_ok = derived["qualification_ok"]
    format_valid = not failures
    all_pass = format_valid and capability_found and qualification_ok

    blocked_reasons: list[str] = []
    if not capability_found:
        blocked_reasons.append(
            "no out-of-process provider implements SubagentProvider.prepareContinuable in the "
            "0.1.5-rc.1 candidate; the only continuable providers are in-process")
    if not qualification_ok:
        blocked_reasons.extend(derived["qualification_reasons"] or [
            "no real independently-killable child-crash qualification"])

    return {
        "schema_version": "byq-v090-d15-child-provider-remediation-verdict.v1",
        "blocker": contract["blocker"],
        "owner_node": contract["owner_node"],
        "format_valid": format_valid,
        "all_pass": all_pass,
        "qualification_passed": all_pass,
        "result": "PASS" if all_pass else "BLOCKED",
        "exit_code": 0 if all_pass else 1,
        "external_blocked": (not all_pass) and (not capability_found),
        "conclusions": {
            "out_of_process_continuable_provider_available": capability_found,
            "in_process_continuable_providers": derived["in_process_continuable"],
            "out_of_process_continuable_providers": derived["out_of_process_continuable"],
            "child_crash_qualification_ok": qualification_ok,
            "out_of_process_provider_rejected_by_native_gate": derived["out_of_process_rejected"],
        },
        "failures": failures,
        "blocked_reasons": blocked_reasons,
    }


def legacy_compute_verdict(contract: dict, discovery: dict) -> dict:
    """Reconstructed pre-fix result-only gate: trusts self-declared booleans."""
    conclusions = discovery.get("conclusions") if isinstance(discovery.get("conclusions"), dict) else {}
    ok = (
        discovery.get("evidence_class") == contract["required_evidence_class"]
        and conclusions.get("out_of_process_continuable_provider_available") is True
        and conclusions.get("independently_killable_child_available") is True
    )
    return {"all_pass": bool(ok), "format_valid": True, "exit_code": 0 if ok else 1}


def external_blocked_evidence(contract: dict, discovery: dict, verdict: dict) -> dict:
    return {
        "schema_version": "byq-v090-d15-child-provider-remediation-external-blocked.v1",
        "blocker": contract["blocker"],
        "owner_node": contract["owner_node"],
        "status": "BLOCKED",
        "is_external": True,
        "available_in_0_1_5_rc1": False,
        "required_provider": contract["required_capability"]["description"],
        "discovery_evidence": [
            "docs/evidence/v090-d15-child-provider-remediation/capability-discovery.v1.json",
            "docs/evidence/d15/d15-4/routing.v1.json",
            "docs/evidence/d15/d15-4/verdict.v2.json",
        ],
        "discovery_conclusions": verdict["conclusions"],
        "downstream_not_started": [
            "subagent-byq-adapter-restart",
            "terminal-adapter-restart",
            "terminal-dsh-runtime-restart",
            "d15-g-rerun",
            "r3-thin-supervisor",
        ],
        "maintainer_decision_required": {
            "required": True,
            "reason": "a strict serial step-5 order cannot be both honest and executable while B1 "
                      "is an external dependency on an upstream DSH provider",
            "options": ["G-keep", "G-split", "G-reorder", "G-reclassify"],
            "source": "docs/evidence/v090-closeout/DSH-015RC1-CLOSEOUT-SLICES.md#gate-order-options",
        },
        "upstream_resolution": "an upstream out-of-process provider implementing "
                               "SubagentProvider.prepareContinuable must land and be qualified; "
                               "BYQ must not build a second harness or a child-resume bridge",
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
            "No out-of-process continuable provider or prepareContinuable provider",
            "No BYQ child-resume bridge",
            "No same-process provider substitution",
            "No owning-process SIGKILL substitution",
            "No label-only PASS",
            "No D15/R3 unfreeze",
            "No production selector/default switch",
            "No deployment, tag or release",
        ],
    }


def _valid_providers() -> list[dict]:
    def provider(name: str, package: str, boundary: str, present: bool, code: str | None) -> dict:
        gate = ({"ok": True, "kind": "capability-present", "spec": {}}
                if present else
                {"ok": False, "kind": "unsupported-capability",
                 "errorClass": "SubagentError", "errorCode": code,
                 "message": f"subagent provider \"{name}\" does not support continuable children"})
        return {
            "name": name, "package": package, "boundary": boundary,
            "in_candidate_bundle": True, "import_ok": True, "version": "0.1.5-rc.1",
            "prepare_continuable_present": present, "capabilities": {}, "gate": gate,
        }

    return [
        provider("spawn", "@deepseek-ai/dsh-subagent-spawn-in-process", "in-process", True, None),
        provider("fork", "@deepseek-ai/dsh-subagent-fork-in-process", "in-process", True, None),
        provider("acp", "@deepseek-ai/dsh-subagent-acp", "out-of-process", False, "UNSUPPORTED_CAPABILITY"),
        provider("codex", "@deepseek-ai/dsh-subagent-codex", "out-of-process", False, "UNSUPPORTED_CAPABILITY"),
        provider("claude-code", "@deepseek-ai/dsh-subagent-claude-code", "out-of-process", False,
                 "UNSUPPORTED_CAPABILITY"),
    ]


def valid_fixture(contract: dict) -> dict:
    """Synthetic UNIT fixture of the real BLOCKED discovery. Never runtime evidence."""
    return {
        "schema_version": "byq-v090-d15-child-provider-discovery.v1",
        "candidate": dict(contract["candidate"]),
        "provenance": {"archive": {"matches_declaration": True}},
        "evidence_class": "unit-fixture",
        "llm": {"class": "no-llm", "real_llm_quality": False},
        "boot_error": None,
        "providers": _valid_providers(),
        "conclusions": {
            "out_of_process_continuable_provider_available": False,
            "in_process_continuable_provider_available": True,
            "independently_killable_child_available": False,
        },
        "child_crash_qualification": None,
    }


def _fully_qualified_fixture(contract: dict) -> dict:
    """Synthetic fully-qualified discovery: an out-of-process continuable provider
    with a real child-only SIGKILL qualification. Proves the observer can PASS when
    the evidence is real."""
    fixture = valid_fixture(contract)
    fixture["evidence_class"] = contract["required_evidence_class"]
    acp = next(item for item in fixture["providers"] if item["name"] == "acp")
    acp["prepare_continuable_present"] = True
    acp["gate"] = {"ok": True, "kind": "capability-present", "spec": {}}
    fixture["conclusions"].update({
        "out_of_process_continuable_provider_available": True,
        "independently_killable_child_available": True,
    })
    fixture["child_crash_qualification"] = {
        "method": "child-sigkill",
        "child_pid": 424242,
        "child_pid_death_observed": True,
        "parent_alive_during_kill": True,
        "parent_truthful_failed_settlement": True,
        "child_id_retained": True,
        "natively_resumed_or_loss_marked": True,
        "orphan_processes": 0,
    }
    return fixture


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    mutations: list[tuple[str, dict]] = []

    def add(name: str, mutate) -> None:
        value = copy.deepcopy(fixture)
        mutate(value)
        mutations.append((name, value))

    def provider(value: dict, name: str) -> dict:
        return next(item for item in value["providers"] if item["name"] == name)

    def qualification(value: dict) -> dict:
        return value["child_crash_qualification"]

    add("capability-absent-but-claimed", lambda v: (
        provider(v, "acp").update({"prepare_continuable_present": False,
                                   "gate": {"ok": False, "kind": "unsupported-capability",
                                            "errorCode": "UNSUPPORTED_CAPABILITY"}})))
    add("same-process-provider-substituted", lambda v: provider(v, "acp").update({"boundary": "in-process"}))
    add("owning-process-sigkill-as-child-crash", lambda v: qualification(v).update(
        {"method": "owning-process-sigkill", "child_pid": None, "parent_alive_during_kill": False}))
    add("child-pid-not-dead", lambda v: qualification(v).update({"child_pid_death_observed": False}))
    add("child-pid-missing", lambda v: qualification(v).update({"child_pid": None}))
    add("parent-not-alive-during-kill", lambda v: qualification(v).update({"parent_alive_during_kill": False}))
    add("settlement-fabricated", lambda v: qualification(v).update({"parent_truthful_failed_settlement": False}))
    add("child-id-lost", lambda v: qualification(v).update({"child_id_retained": False}))
    add("no-native-resume", lambda v: qualification(v).update({"natively_resumed_or_loss_marked": False}))
    add("orphan-left-behind", lambda v: qualification(v).update({"orphan_processes": 1}))
    add("forbidden-substitution-bridge", lambda v: qualification(v).update({"substitution": "byq-child-resume-bridge"}))
    add("provider-capability-gate-contradiction", lambda v: provider(v, "acp").update(
        {"prepare_continuable_present": False, "gate": {"ok": True, "kind": "capability-present"}}))
    add("out-of-process-not-rejected", lambda v: provider(v, "acp").update(
        {"prepare_continuable_present": False,
         "gate": {"ok": False, "kind": "other-error", "errorCode": "SOMETHING_ELSE"}}))
    add("missing-out-of-process-provider", lambda v: v["providers"].remove(provider(v, "acp")))
    add("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    add("non-native-evidence-class", lambda v: v.update({"evidence_class": "format-layer"}))
    add("boot-error", lambda v: v.update({"boot_error": {"name": "Error", "message": "injected"}}))
    add("archive-mismatch", lambda v: v["provenance"]["archive"].update({"matches_declaration": False}))
    add("no-providers", lambda v: v.update({"providers": []}))
    add("llm-claims-real-quality", lambda v: v["llm"].update({"real_llm_quality": True}))
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

    # The real blocked discovery claims nothing and must not pass the fixed gate.
    record("blocked-fixture-pre-fix-passes", valid_fixture(contract), strict=False)
    for name, mutated in _mutations(baseline):
        record(name, mutated, strict=True)

    all_controls_pass = strict_good["all_pass"] and all(
        (not item["fixed_all_pass"]) for item in controls)
    defect_targeting = [item for item in controls
                        if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-v090-d15-child-provider-remediation-negative-controls.v1",
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
    parser.add_argument("--discovery", type=Path)
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
        if args.discovery is None:
            parser.error("--discovery is required unless --selfcheck")
        discovery = _load(args.discovery)
        result = compute_verdict(contract, discovery, allow_unit_fixture=args.allow_unit_fixture)
        code = result["exit_code"]
        if args.blocked_out is not None and result["external_blocked"]:
            blocked = external_blocked_evidence(contract, discovery, result)
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
