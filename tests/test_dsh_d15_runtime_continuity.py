"""D15 runtime-continuity acceptance observer tests (fail-able verdict, v2).

Covers the review fixes: format-valid vs qualification-pass separation, required
NOT_RUN/BLOCKED gating, contract-authoritative continuity rules, honest
pre-fix (legacy algorithm) comparison, and recovery relationship/linkage checks.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OBSERVER = ROOT / "scripts/d15/runtime_continuity/observer.py"
CONTRACT = ROOT / "scripts/d15/runtime_continuity/contract.v3.json"


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_runtime_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_runtime_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_contract_is_closed_and_versioned():
    contract = _contract()
    assert contract["schema_version"] == "byq-d15-runtime-contract.v3"
    ids = [item["id"] for item in contract["required_scenarios"]]
    assert len(ids) == len(set(ids))
    for expected in ("adapter-process-restart", "dsh-process-interruption",
                     "gateway-disconnect-reconnect", "generation-replacement", "executor-takeover"):
        assert expected in ids
    assert contract["required_coverage_gates_qualification"] is True
    optional_ids = [item["id"] for item in contract["optional_scenarios"]]
    assert optional_ids and set(optional_ids).isdisjoint(ids)
    assert contract["candidate"]["release"] == "dsh-0.1.5rc1"


def test_unit_fixture_passes_and_every_negative_control_fails():
    observer = _load_observer()
    contract = _contract()
    verdict = observer.compute_verdict(contract, observer.valid_fixture(contract), allow_unit_fixture=True)
    assert verdict["all_pass"] is True
    assert verdict["format_valid"] is True

    controls = observer.run_selfcheck(contract)
    assert controls["baseline_all_pass"] is True
    assert controls["all_controls_pass"] is True
    assert controls["defect_targeting_pre_fix_passed"] is True
    assert controls["control_count"] >= 35
    for control in controls["controls"]:
        assert control["observed_all_pass"] is False, control
        assert control["observed_exit_code"] == 1, control
        assert control["first_failure"], control


def test_required_not_run_or_blocked_gates_qualification():
    observer = _load_observer()
    contract = _contract()
    for status in ("NOT_RUN", "BLOCKED"):
        fixture = observer.valid_fixture(contract)
        target = next(s for s in fixture["scenarios"] if s["id"] == "generation-replacement")
        target.clear()
        target.update({"id": "generation-replacement", "result": status,
                       "not_run_reason": f"not executed because {status}"})
        verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
        assert verdict["all_pass"] is False
        assert verdict["exit_code"] == 1
        assert verdict["required_coverage"]["generation-replacement"] == status
        assert any("generation-replacement" in item for item in verdict["coverage_failures"])
        # A reasoned non-execution is format-valid but must not be qualification PASS.
        assert verdict["format_valid"] is True


def test_optional_not_run_does_not_gate_required_coverage():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
    assert verdict["all_pass"] is True
    assert verdict["optional_coverage"]["host-reboot"] == "NOT_RUN"
    assert verdict["required_coverage_ok"] is True


def test_observation_cannot_relax_contract_continuity_rules():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    scenario = fixture["scenarios"][0]
    scenario["allowed_continuity"] = ["fresh"]
    scenario["forbidden_continuity"] = []
    scenario["after"]["continuity"] = "fresh"
    verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
    assert verdict["all_pass"] is False
    assert any("may not declare 'allowed_continuity'" in item for item in verdict["failures"])
    assert any("fabricated continuity 'fresh'" in item for item in verdict["failures"])


def test_recovery_relationships_and_linkage_are_enforced():
    observer = _load_observer()
    contract = _contract()
    base = observer.valid_fixture(contract)

    same_pid = copy.deepcopy(base)
    same_pid["scenarios"][0]["after"]["adapter_pid"] = same_pid["scenarios"][0]["before"]["adapter_pid"]
    assert observer.compute_verdict(contract, same_pid, allow_unit_fixture=True)["all_pass"] is False

    same_generation = copy.deepcopy(base)
    repl = next(s for s in same_generation["scenarios"] if s["id"] == "generation-replacement")
    repl["after"]["generation_index"] = repl["before"]["generation_index"]
    repl["after"]["adapter_generation"] = repl["before"]["adapter_generation"]
    assert observer.compute_verdict(contract, same_generation, allow_unit_fixture=True)["all_pass"] is False

    same_epoch = copy.deepcopy(base)
    takeover = next(s for s in same_epoch["scenarios"] if s["id"] == "executor-takeover")
    takeover["after"]["executor_epoch"] = takeover["before"]["executor_epoch"]
    assert observer.compute_verdict(contract, same_epoch, allow_unit_fixture=True)["all_pass"] is False

    broken_link = copy.deepcopy(base)
    broken_link["scenarios"][0]["after"]["goal"]["prompt_receipt"]["root_run_id"] = "9" * 32
    assert observer.compute_verdict(contract, broken_link, allow_unit_fixture=True)["all_pass"] is False


def test_synthetic_fixture_is_not_runtime_evidence():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    # Without allow_unit_fixture the unit fixture must be rejected.
    verdict = observer.compute_verdict(contract, fixture)
    assert verdict["all_pass"] is False
    assert any("not runtime evidence" in item for item in verdict["failures"])


def test_missing_evidence_is_never_an_empty_default_pass():
    observer = _load_observer()
    contract = _contract()
    default = {
        "schema_version": "byq-d15-runtime-observations.v3",
        "evidence_class": contract["required_evidence_class"],
        "candidate": dict(contract["candidate"]),
        "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False},
        "scenarios": [],
    }
    verdict = observer.compute_verdict(contract, default)
    assert verdict["all_pass"] is False
    assert verdict["exit_code"] == 1
    assert any("missing required scenario" in item for item in verdict["failures"])


def test_not_run_requires_a_reason():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0] = {"id": "adapter-process-restart", "result": "NOT_RUN"}
    verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
    assert verdict["all_pass"] is False
    assert any("without a reason" in item for item in verdict["failures"])


def test_observer_cli_fails_on_malformed_observations(tmp_path: Path):
    observer = _load_observer()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert observer.main(["--observations", str(bad)]) == 2


def test_observer_cli_exit_code_tracks_verdict(tmp_path: Path):
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    fixture["evidence_class"] = contract["required_evidence_class"]
    good = tmp_path / "good.json"
    good.write_text(json.dumps(fixture), encoding="utf-8")
    assert observer.main(["--observations", str(good), "--out", str(tmp_path / "v.json")]) == 0


def test_action_receipt_requires_origin_and_measured_count():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0]["after"]["action_receipts"][0]["side_effect_count"] = None
    assert observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"] is False

    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0]["after"]["action_receipts"][0].pop("origin")
    assert observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"] is False


def test_approval_trials_are_required_and_side_effects_fail():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0]["after"]["approval"].pop("trials")
    assert observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"] is False

    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0]["after"]["approval"]["trials"][0]["side_effect_created"] = True
    verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
    assert verdict["all_pass"] is False
    assert any("bypass" in item for item in verdict["failures"])


def test_result_must_be_attributed_to_the_target_run():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0]["after"]["result"]["target_run_id"] = "9" * 32
    assert observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"] is False

    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0]["after"]["result"]["status"] = "incomplete"
    assert observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"] is False


def test_capture_errors_gate_pass():
    observer = _load_observer()
    contract = _contract()
    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0]["after"]["capture_ok"] = False
    fixture["scenarios"][0]["after"]["capture_errors"] = ["journal read failed"]
    verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
    assert verdict["all_pass"] is False
    assert any("capture evidence missing" in item for item in verdict["failures"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
