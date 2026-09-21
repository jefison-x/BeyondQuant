#!/usr/bin/env python3
"""Fail-able observer for the independent DSH provider-qualification slice.

This slice answers one monitoring question: **would a future DSH release unblock
the ADR-0082 Option 1 blocker?** It examines published DSH releases (at minimum
`0.1.5-rc.2`, optionally `0.1.6-alpha.2`) and adjudicates a capability inventory
produced by the native probe ``capability_inventory.mjs``.

Separation of concerns:

* ``format_valid`` — the inventory is structurally sound: it matches the contract
  providers, the examined version, the evidence class and the native capability
  gate, and it has no boot error.
* ``all_pass`` — a future DSH release genuinely provides an out-of-process
  provider implementing ``SubagentProvider.prepareContinuable`` with a real
  ``SubagentRuntime.prepareContinuable`` gate pass **and** a complete
  cross-process continuation qualification: child in an independent OS process,
  rediscovery by a new generation after the parent/provider process is SIGKILLed,
  the same durable child id, a durable mailbox, a single-active lease with epoch
  fencing, message delivery/wakeup, at-most-once settlement, original
  goal/delegation lineage, authorization/tool filtering and orphan cleanup.

The observer derives the capability from the provider records and the
qualification record; it never trusts a self-declared ``conclusions`` boolean.
Helper symbols (``out-of-process.d.ts``, ``subprocessRunHandle``) are recorded
but are **not** capability. ``legacy_compute_verdict`` is the reconstructed
pre-fix "result-only" gate, used only to prove the controls are defect-targeting.

Usage:
  python3 provider_qualification_observer.py --selfcheck --out <controls.json>
  python3 provider_qualification_observer.py --inventory <inventory.json> \\
      --out <verdict.json> [--blocked-out <blocked.json>]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "contract.v1.json"
INVENTORY_SCHEMA = "byq-v090-dsh-provider-qualification-capability-inventory.v1"
VERDICT_SCHEMA = "byq-v090-dsh-provider-qualification-verdict.v1"


class Failure(Exception):
    """Raised only for an unreadable contract/inventory artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _provider_map(inventory: dict) -> dict[str, dict]:
    providers = inventory.get("providers")
    if not isinstance(providers, list):
        return {}
    return {item.get("name"): item for item in providers if isinstance(item, dict)}


def _contract_version(contract: dict, version_id: str) -> dict | None:
    for item in contract.get("examined_versions", []):
        if item.get("id") == version_id:
            return item
    return None


def _gate_ok(record: dict) -> bool:
    gate = record.get("gate")
    return (
        isinstance(gate, dict)
        and gate.get("ok") is True
        and gate.get("kind") == "capability-present"
    )


def _qualification_reasons(contract: dict, qualification: object) -> list[str]:
    reasons: list[str] = []
    if not isinstance(qualification, dict):
        return ["no real cross-process continuation qualification recorded"]
    for field, expected in contract["cross_process_qualification_required_fields"].items():
        if qualification.get(field) != expected:
            reasons.append(
                f"cross-process qualification field {field!r} expected {expected!r} "
                f"got {qualification.get(field)!r}")
    for field in contract["required_positive_int_fields"]:
        value = qualification.get(field)
        if not _is_int(value) or value <= 0:
            reasons.append(
                f"cross-process qualification requires a real positive {field!r}; got {value!r}")
    for spec in contract["required_monotonic_fields"]:
        before, after = qualification.get(spec["from"]), qualification.get(spec["to"])
        if not (_is_int(before) and _is_int(after)) or not after > before:
            reasons.append(
                f"cross-process qualification field {spec['from']!r}->{spec['to']!r} must be "
                f"strictly monotonic ({spec['reason']}); got {before!r}->{after!r}")
    for forbidden in contract.get("forbidden_substitutions", []):
        if qualification.get("substitution") == forbidden:
            reasons.append(f"forbidden substitution recorded: {forbidden!r}")
    if qualification.get("substitution") is not None:
        reasons.append(f"forbidden substitution recorded: {qualification['substitution']!r}")
    return reasons


def _derive(contract: dict, inventory: dict) -> dict[str, Any]:
    providers = _provider_map(inventory)
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

    out_of_process_continuable = sorted(
        name for name, record in providers.items()
        if record.get("boundary") == "out-of-process"
        and record.get("prepare_continuable_present") is True
        and _gate_ok(record))
    in_process_continuable = sorted(
        name for name, record in providers.items()
        if record.get("boundary") == "in-process"
        and record.get("prepare_continuable_present") is True
        and _gate_ok(record))

    bundled_oop = [spec["name"] for spec in required if spec["boundary"] == "out-of-process"]
    gate = contract["required_gate"]
    oop_rejected = all(
        providers.get(name, {}).get("prepare_continuable_present") is True
        or (
            providers.get(name, {}).get("prepare_continuable_present") is False
            and isinstance(providers.get(name, {}).get("gate"), dict)
            and providers[name]["gate"].get("kind") == "unsupported-capability"
            and providers[name]["gate"].get("errorCode") == gate["out_of_process_rejection_code"])
        for name in bundled_oop)

    # A provider claiming the capability without a passing real gate is a
    # contradiction: never count it and always fail.
    fake_claim = sorted(
        name for name, record in providers.items()
        if record.get("prepare_continuable_present") is True and not _gate_ok(record))

    qualification = inventory.get("cross_process_continuation_qualification")
    qualification_reasons = _qualification_reasons(contract, qualification)

    return {
        "providers": providers,
        "required_shape_ok": required_shape_ok,
        "out_of_process_continuable": out_of_process_continuable,
        "in_process_continuable": in_process_continuable,
        "out_of_process_rejected": oop_rejected,
        "fake_claim": fake_claim,
        "qualification_ok": not qualification_reasons,
        "qualification_reasons": qualification_reasons,
    }


def _format_failures(contract: dict, inventory: dict, derived: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        failures.append("inventory schema_version mismatch")
    examined = inventory.get("examined_version") if isinstance(
        inventory.get("examined_version"), dict) else {}
    spec = _contract_version(contract, examined.get("id"))
    if spec is None:
        failures.append(f"examined version id {examined.get('id')!r} is not a contracted version")
    else:
        if examined.get("npm") != spec["npm"]:
            failures.append(
                f"examined_version.npm expected {spec['npm']!r} got {examined.get('npm')!r}")
    if inventory.get("evidence_class") != contract["required_evidence_class"]:
        failures.append("inventory evidence class is not native-runtime-isolated")
    if inventory.get("boot_error") is not None:
        failures.append("provider boot error recorded")
    if not derived["providers"]:
        failures.append("no providers recorded")
    if not derived["required_shape_ok"]:
        failures.append("required provider set/package/boundary mismatch")
    if not derived["out_of_process_rejected"]:
        failures.append("a bundled out-of-process provider was not rejected by the native gate")
    if derived["fake_claim"]:
        failures.append(
            "provider claims prepareContinuable without a passing native gate: "
            + ", ".join(derived["fake_claim"]))
    npm_version = examined.get("npm")
    for name, record in derived["providers"].items():
        if record.get("version") != npm_version:
            failures.append(
                f"provider {name!r} version {record.get('version')!r} != examined npm {npm_version!r}")
    # A capability found without a qualification is only a BLOCKED reason, not a
    # format failure, so it is deliberately excluded from format_valid here.
    return failures


def compute_verdict(contract: dict, inventory: dict, *, allow_unit_fixture: bool = False) -> dict:
    derived = _derive(contract, inventory)
    failures = _format_failures(contract, inventory, derived)
    if inventory.get("evidence_class") == "unit-fixture" and not allow_unit_fixture:
        failures.append("unit fixture is not runtime evidence")

    capability_found = bool(derived["out_of_process_continuable"])
    qualification_ok = derived["qualification_ok"]
    format_valid = not failures
    all_pass = format_valid and capability_found and qualification_ok

    blocked_reasons: list[str] = []
    if not capability_found:
        blocked_reasons.append(
            "no registerable out-of-process provider implements "
            "SubagentProvider.prepareContinuable in the examined release; the only "
            "continuable providers are in-process and every out-of-process provider "
            "is rejected by the native gate")
    if capability_found and not qualification_ok:
        blocked_reasons.extend(derived["qualification_reasons"] or [
            "no complete cross-process continuation qualification"])
    if not format_valid:
        blocked_reasons.append(
            "the examined release is not a coherent, fully-versioned closure for this "
            "qualification (see failures)")

    return {
        "schema_version": VERDICT_SCHEMA,
        "slice": contract["slice"],
        "blocker": "subagent-child-crash",
        "owner_node": contract["owner_node"],
        "adr": contract["adr"],
        "examined_version": inventory.get("examined_version"),
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
            "cross_process_qualification_ok": qualification_ok,
            "out_of_process_provider_rejected_by_native_gate": derived["out_of_process_rejected"],
        },
        "failures": failures,
        "blocked_reasons": blocked_reasons,
    }


def legacy_compute_verdict(contract: dict, inventory: dict) -> dict:
    """Reconstructed pre-fix result-only gate: trusts self-declared booleans."""
    conclusions = inventory.get("conclusions") if isinstance(
        inventory.get("conclusions"), dict) else {}
    ok = (
        inventory.get("evidence_class") == contract["required_evidence_class"]
        and conclusions.get("out_of_process_continuable_provider_available") is True
        and conclusions.get("cross_process_qualification_ok") is True
    )
    return {"all_pass": bool(ok), "format_valid": True, "exit_code": 0 if ok else 1}


def external_blocked_evidence(contract: dict, inventory: dict, verdict: dict) -> dict:
    return {
        "schema_version": "byq-v090-dsh-provider-qualification-external-blocked.v1",
        "slice": contract["slice"],
        "blocker": "subagent-child-crash",
        "owner_node": contract["owner_node"],
        "examined_version": verdict.get("examined_version"),
        "status": "BLOCKED",
        "is_external": True,
        "required_provider": contract["required_capability"]["description"],
        "required_capability": contract["required_capability"]["id"],
        "upstream_resolution": "an upstream out-of-process provider implementing "
                               "SubagentProvider.prepareContinuable, with a durable mailbox and "
                               "a cross-process lease protocol, must land and be qualified; BYQ "
                               "must not build a second harness or a child-resume bridge",
        "evidence": contract.get("closeout_slices"),
        "constraints": contract["constraints"],
        "non_actions": [
            "No DSH fork or patch",
            "No BYQ provider or child-resume bridge",
            "No second session store",
            "No production selector/default upgrade",
            "No dependency upgrade",
            "No deployment, tag or release",
            "No Phase 100 or #338 work",
            "No D15-G re-run or R3 unfreeze"
        ],
    }


def _provider(name: str, package: str, boundary: str, present: bool,
              version: str) -> dict:
    if present:
        gate = {"ok": True, "kind": "capability-present", "spec": {}}
    else:
        gate = {"ok": False, "kind": "unsupported-capability",
                "errorClass": "SubagentError", "errorCode": "UNSUPPORTED_CAPABILITY",
                "message": f"subagent provider \"{name}\" does not support continuable children"}
    return {
        "name": name, "package": package, "boundary": boundary,
        "import_ok": True, "version": version,
        "prepare_continuable_present": present, "capabilities": {}, "gate": gate,
    }


def _all_providers(version: str) -> list[dict]:
    return [
        _provider("spawn", "@deepseek-ai/dsh-subagent-spawn-in-process", "in-process", True, version),
        _provider("fork", "@deepseek-ai/dsh-subagent-fork-in-process", "in-process", True, version),
        _provider("acp", "@deepseek-ai/dsh-subagent-acp", "out-of-process", False, version),
        _provider("codex", "@deepseek-ai/dsh-subagent-codex", "out-of-process", False, version),
        _provider("claude-code", "@deepseek-ai/dsh-subagent-claude-code", "out-of-process", False,
                  version),
        _provider("dsh-sdk", "@deepseek-ai/dsh-subagent-dsh-sdk", "out-of-process", False, version),
    ]


def valid_fixture(contract: dict, version_id: str = "rc2") -> dict:
    """Synthetic UNIT fixture of a real BLOCKED inventory. Never runtime evidence."""
    spec = _contract_version(contract, version_id) or contract["examined_versions"][0]
    return {
        "schema_version": INVENTORY_SCHEMA,
        "examined_version": {"id": spec["id"], "npm": spec["npm"], "channel": spec["channel"]},
        "evidence_class": "unit-fixture",
        "boot_error": None,
        "providers": _all_providers(spec["npm"]),
        "declared_limitations": {
            "process_local_residency": True,
            "durable_mailbox_absent": True,
            "cross_process_lease_absent": True,
            "acp_one_shot": True,
        },
        "out_of_process_helpers": ["NO_START_CAPABILITIES", "subprocessRunHandle"],
        "cross_process_continuation_qualification": None,
        "cross_process_continuation_qualification_reason":
            "no out-of-process continuable provider exists to qualify",
        "conclusions": {
            "out_of_process_continuable_provider_available": False,
            "in_process_continuable_provider_available": True,
            "cross_process_qualification_ok": False,
        },
    }


def _fully_qualified_fixture(contract: dict, version_id: str = "rc2") -> dict:
    """Synthetic fully-qualified inventory: a real out-of-process continuable
    provider plus a complete cross-process continuation qualification. Proves the
    observer can PASS when the evidence is real, and anchors the defects."""
    fixture = valid_fixture(contract, version_id)
    spec = _contract_version(contract, version_id) or contract["examined_versions"][0]
    fixture["evidence_class"] = contract["required_evidence_class"]
    acp = next(item for item in fixture["providers"] if item["name"] == "acp")
    acp["prepare_continuable_present"] = True
    acp["gate"] = {"ok": True, "kind": "capability-present", "spec": {}}
    fixture["declared_limitations"]["durable_mailbox_absent"] = False
    fixture["declared_limitations"]["cross_process_lease_absent"] = False
    fixture["cross_process_continuation_qualification"] = {
        "method": "cross-process-continuation",
        "child_os_process_id": 424242,
        "parent_os_process_id": 424100,
        "generation_b_os_process_id": 424300,
        "child_independent_os_process": True,
        "parent_os_process_sigkilled": True,
        "new_generation_discovered_child": True,
        "discovery_child_id_matches": True,
        "durable_mailbox_present": True,
        "message_delivered": True,
        "wakeup_delivered": True,
        "single_active_lease": True,
        "lease_takeover": True,
        "lease_epoch_before": 1,
        "lease_epoch_after": 2,
        "stale_epoch_rejected": True,
        "at_most_once_settlement": True,
        "settlement_count": 1,
        "original_goal_lineage_preserved": True,
        "delegation_lineage_preserved": True,
        "authorization_enforced": True,
        "tool_filter_enforced": True,
        "orphan_processes": 0,
        "orphan_sessions": 0,
    }
    fixture["conclusions"] = {
        "out_of_process_continuable_provider_available": True,
        "in_process_continuable_provider_available": True,
        "cross_process_qualification_ok": True,
    }
    # version guard for readability (spec is the examined version).
    assert spec["npm"] == acp["version"]
    return fixture


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    mutations: list[tuple[str, dict]] = []

    def add(name: str, mutate) -> None:
        value = copy.deepcopy(fixture)
        mutate(value)
        mutations.append((name, value))

    def provider(value: dict, name: str) -> dict:
        return next(item for item in value["providers"] if item["name"] == name)

    def qual(value: dict) -> dict:
        return value["cross_process_continuation_qualification"]

    # The six required defect families from the slice acceptance.
    add("fake-provider-claimed", lambda v: provider(v, "acp").update(
        {"prepare_continuable_present": True,
         "gate": {"ok": False, "kind": "unsupported-capability",
                  "errorCode": "UNSUPPORTED_CAPABILITY"}}))
    add("in-process-provider-substituted", lambda v: provider(v, "acp").update(
        {"boundary": "in-process"}))
    add("one-shot-provider-as-continuable", lambda v: provider(v, "acp").update(
        {"prepare_continuable_present": False,
         "gate": {"ok": False, "kind": "unsupported-capability",
                  "errorCode": "UNSUPPORTED_CAPABILITY"}}))
    add("no-durable-mailbox", lambda v: qual(v).update({"durable_mailbox_present": False}))
    add("double-active-lease", lambda v: qual(v).update(
        {"single_active_lease": False, "lease_epoch_before": 2, "lease_epoch_after": 2}))
    add("duplicate-settlement", lambda v: qual(v).update(
        {"at_most_once_settlement": False, "settlement_count": 2}))

    # Remaining cross-process invariants.
    add("helper-symbols-only-no-capability", lambda v: provider(v, "acp").update(
        {"prepare_continuable_present": False,
         "gate": {"ok": False, "kind": "unsupported-capability",
                  "errorCode": "UNSUPPORTED_CAPABILITY"}}))
    add("child-shared-os-process", lambda v: qual(v).update(
        {"child_independent_os_process": False, "parent_os_process_id": 424242}))
    add("parent-not-sigkilled", lambda v: qual(v).update({"parent_os_process_sigkilled": False}))
    add("new-generation-cannot-discover-child", lambda v: qual(v).update(
        {"new_generation_discovered_child": False}))
    add("different-child-id-after-restart", lambda v: qual(v).update(
        {"discovery_child_id_matches": False}))
    add("no-message-delivery", lambda v: qual(v).update({"message_delivered": False}))
    add("no-wakeup", lambda v: qual(v).update({"wakeup_delivered": False}))
    add("no-lease-takeover", lambda v: qual(v).update({"lease_takeover": False}))
    add("stale-epoch-accepted", lambda v: qual(v).update({"stale_epoch_rejected": False}))
    add("epoch-not-monotonic", lambda v: qual(v).update(
        {"lease_epoch_before": 3, "lease_epoch_after": 3}))
    add("no-real-child-pid", lambda v: qual(v).update({"child_os_process_id": 0}))
    add("goal-lineage-lost", lambda v: qual(v).update(
        {"original_goal_lineage_preserved": False}))
    add("delegation-lineage-lost", lambda v: qual(v).update(
        {"delegation_lineage_preserved": False}))
    add("authorization-bypassed", lambda v: qual(v).update({"authorization_enforced": False}))
    add("tool-filter-bypassed", lambda v: qual(v).update({"tool_filter_enforced": False}))
    add("orphan-process-left", lambda v: qual(v).update({"orphan_processes": 1}))
    add("orphan-session-left", lambda v: qual(v).update({"orphan_sessions": 1}))
    add("forbidden-substitution-bridge", lambda v: qual(v).update(
        {"substitution": "BYQ child-resume bridge (ADR-0082 Option 2, rejected)"}))

    # Format / provenance defects.
    add("out-of-process-not-rejected", lambda v: provider(v, "acp").update(
        {"gate": {"ok": False, "kind": "other-error", "errorCode": "SOMETHING_ELSE"}}))
    add("missing-out-of-process-provider", lambda v: v["providers"].remove(provider(v, "acp")))
    add("examined-version-mismatch", lambda v: v["examined_version"].update({"npm": "0.1.2-rc.1"}))
    add("provider-version-mismatch", lambda v: provider(v, "acp").update({"version": "0.1.2-rc.1"}))
    add("non-native-evidence-class", lambda v: v.update({"evidence_class": "format-layer"}))
    add("boot-error", lambda v: v.update({"boot_error": {"name": "Error", "message": "injected"}}))
    add("no-providers", lambda v: v.update({"providers": []}))
    add("capability-absent-but-claimed", lambda v: provider(v, "acp").update(
        {"prepare_continuable_present": False,
         "gate": {"ok": True, "kind": "capability-present"}}))
    return mutations


def selfcheck(contract: dict) -> dict:
    baseline = _fully_qualified_fixture(contract, "rc2")
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
        "schema_version": "byq-v090-dsh-provider-qualification-negative-controls.v1",
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
    parser.add_argument("--inventory", type=Path)
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
        if args.inventory is None:
            parser.error("--inventory is required unless --selfcheck")
        inventory = _load(args.inventory)
        result = compute_verdict(contract, inventory, allow_unit_fixture=args.allow_unit_fixture)
        code = result["exit_code"]
        if args.blocked_out is not None and result["external_blocked"]:
            blocked = external_blocked_evidence(contract, inventory, result)
            args.blocked_out.parent.mkdir(parents=True, exist_ok=True)
            args.blocked_out.write_text(json.dumps(blocked, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8")

    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps({
        "result": result.get("result", "SELFCHECK"),
        "examined_version": result.get("examined_version"),
        "format_valid": result.get("format_valid"),
        "all_pass": result.get("all_pass"),
        "all_controls_pass": result.get("all_controls_pass"),
        "blocked_reasons": result.get("blocked_reasons", []),
        "control_count": result.get("control_count"),
    }, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
