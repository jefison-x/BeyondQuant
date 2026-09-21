"""0.9 composite research fault-regression contract/observer tests (v2).

Runs under ``unittest`` (the architecture lane has no pytest). These tests prove
the observer is fail-able against fabricated provenance, over-claimed scenarios
and loose gates; the capture layer never defaults to success; and the frozen
acceptance matrix stays consistent with the closed contract.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts/v090/composite_research"
CONTRACT = HARNESS / "contract.v2.json"
MATRIX = ROOT / "docs/evidence/v090-composite-research/acceptance-matrix.v2.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _observer():
    return _load("v090_observer_v2", HARNESS / "observer.py")


def _capture_negatives():
    return _load("v090_capture_negatives_v2", HARNESS / "capture_negatives.py")


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


class V090CompositeResearchTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-v090-composite-research-contract.v2")
        ids = [item["id"] for item in contract["required_scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 17)
        optional_ids = [item["id"] for item in contract["optional_scenarios"]]
        self.assertTrue(set(optional_ids).isdisjoint(ids))
        self.assertTrue(contract["required_coverage_gates_qualification"])
        self.assertTrue(contract["closed_scenario_set"])
        for spec in contract["required_scenarios"]:
            self.assertIn("boundary", spec, spec["id"])
        for expected in ("process-restart-gateway", "process-restart-ml-worker",
                         "approval-rejected", "approval-revoked", "approval-stale-reuse",
                         "cancel-terminal", "timeout-terminal", "queue-worker-resume",
                         "bounded-continuation-exactly-once", "data-ready-continuation",
                         "runtime-adapter-tool-boundary"):
            self.assertIn(expected, ids)
        steps = [s["id"] for s in contract["composite_journey"]["required_steps"]]
        self.assertEqual(len(steps), 9)
        self.assertIn("execute-original-key-after-approval", steps)
        self.assertIn("old-vs-new-comparison", steps)

    def test_acceptance_matrix_matches_contract(self):
        contract = _contract()
        matrix = _matrix()
        self.assertTrue(matrix["frozen"])
        self.assertTrue(matrix["frozen_before_execution"])
        self.assertEqual(matrix["composite_journey"]["id"], contract["composite_journey"]["id"])
        self.assertEqual(matrix["composite_journey"]["required_steps"],
                         [s["id"] for s in contract["composite_journey"]["required_steps"]])
        matrix_rows = [row["id"] for row in matrix["fault_matrix"]["rows"]]
        contract_rows = [row["id"] for row in contract["required_scenarios"]]
        self.assertEqual(matrix_rows, contract_rows)
        self.assertEqual(matrix["fault_matrix"]["required_assertions"],
                         contract["required_assertions"])
        for key in ("contract", "observer", "capture_negatives", "driver",
                    "observations_path", "verdict_path", "negative_controls_path"):
            self.assertTrue((ROOT / matrix[key]).exists(), key)

    def test_observer_selfcheck_is_fail_able(self):
        observer = _observer()
        result = observer.run_selfcheck(_contract())
        self.assertTrue(result["baseline_all_pass"])
        self.assertTrue(result["all_controls_pass"])
        self.assertTrue(result["defect_targeting_pre_fix_passed"])
        self.assertGreaterEqual(result["control_count"], 55)
        self.assertGreaterEqual(result["defect_targeting_count"], 18)
        for control in result["controls"]:
            self.assertFalse(control["observed_all_pass"], control)
            self.assertEqual(control["observed_exit_code"], 1, control)
            self.assertTrue(control["first_failure"], control)

    def test_unit_fixture_passes_full_verdict(self):
        observer = _observer()
        verdict = observer.compute_verdict(_contract(), observer.valid_fixture(_contract()))
        self.assertTrue(verdict["all_pass"])
        self.assertTrue(verdict["format_valid"])

    def test_required_not_run_or_blocked_gates_qualification(self):
        observer = _observer()
        contract = _contract()
        for status in ("NOT_RUN", "BLOCKED"):
            fixture = observer.valid_fixture(contract)
            target = next(s for s in fixture["scenarios"] if s["id"] == "process-restart-gateway")
            target["result"] = status
            target["not_run_reason"] = f"not executed because {status}"
            verdict = observer.compute_verdict(contract, fixture)
            self.assertFalse(verdict["all_pass"], status)
            self.assertTrue(verdict["format_valid"], status)
            self.assertTrue(any(status in item for item in verdict["coverage_failures"]), status)

    def test_missing_required_scenario_is_a_structural_failure(self):
        observer = _observer()
        fixture = observer.valid_fixture(_contract())
        fixture["scenarios"] = [s for s in fixture["scenarios"] if s["id"] != "duplicate-delivery"]
        verdict = observer.compute_verdict(_contract(), fixture)
        self.assertFalse(verdict["format_valid"])
        self.assertFalse(verdict["all_pass"])

    def test_observations_cannot_relax_contract(self):
        observer = _observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        scenario = next(s for s in fixture["scenarios"] if s["id"] == "late-success")
        scenario["allowed_final_states"] = ["late_result_created_next_step"]
        scenario["final_state"] = "late_result_created_next_step"
        verdict = observer.compute_verdict(contract, fixture)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("override" in failure for failure in verdict["failures"]))

    def test_fabricated_provenance_is_rejected(self):
        observer = _observer()
        contract = _contract()
        for mutation in (
            lambda s: s.pop("provenance"),
            lambda s: s["provenance"].update({"generation": {"value": 2}}),
            lambda s: s["provenance"].update({"generation": {"value": 2, "source": "made.up"}}),
            lambda s: s["provenance"].update({"epoch": {"value": "not_applicable"}}),
            lambda s: s["provenance"]["trace"].update({"object_id": "mlrun_" + "0" * 32}),
        ):
            fixture = observer.valid_fixture(contract)
            target = next(s for s in fixture["scenarios"] if s["id"] == "process-restart-backend")
            mutation(target)
            verdict = observer.compute_verdict(contract, fixture)
            self.assertFalse(verdict["all_pass"], mutation)

    def test_restart_requires_actual_pid_change(self):
        observer = _observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        target = next(s for s in fixture["scenarios"] if s["id"] == "process-restart-backend")
        target["pid_after"] = target["pid_before"]
        target["provenance"]["pid"] = {"value": "measured", "service": "backend",
                                       "before": target["pid_before"], "after": target["pid_before"],
                                       "changed": False}
        verdict = observer.compute_verdict(contract, fixture)
        self.assertFalse(verdict["all_pass"])

    def test_loose_gates_are_rejected(self):
        observer = _observer()
        contract = _contract()
        # cancel that actually completed
        fixture = observer.valid_fixture(contract)
        next(s for s in fixture["scenarios"] if s["id"] == "cancel-terminal")["terminal_recheck"] = "completed_terminal"
        self.assertFalse(observer.compute_verdict(contract, fixture)["all_pass"])
        # late result created one next step
        fixture = observer.valid_fixture(contract)
        target = next(s for s in fixture["scenarios"] if s["id"] == "late-success")
        target["db_counts_before"]["ml_prediction_runs"] = 1
        target["db_counts_after"]["ml_prediction_runs"] = 2
        self.assertFalse(observer.compute_verdict(contract, fixture)["all_pass"])
        # ordinary queue impersonating the ADR-0077 data-ready path
        fixture = observer.valid_fixture(contract)
        next(s for s in fixture["scenarios"] if s["id"] == "queue-worker-resume")["mode"] = "waiting_for_data"
        self.assertFalse(observer.compute_verdict(contract, fixture)["all_pass"])
        # a missing Gateway/adapter boundary scenario
        for missing in ("process-restart-gateway", "runtime-adapter-tool-boundary"):
            fixture = observer.valid_fixture(contract)
            fixture["scenarios"] = [s for s in fixture["scenarios"] if s["id"] != missing]
            self.assertFalse(observer.compute_verdict(contract, fixture)["all_pass"], missing)

    def test_runtime_evidence_class_is_required_without_unit_fixture(self):
        observer = _observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["evidence_class"] = "unit-fixture"
        verdict = observer.compute_verdict(contract, fixture)
        self.assertFalse(verdict["all_pass"])

    def test_capture_negatives_all_fail_post_fix_and_pass_pre_fix(self):
        negatives = _capture_negatives()
        result = negatives.run()
        self.assertTrue(result["all_pass"])
        self.assertGreaterEqual(result["case_count"], 12)
        for case in result["cases"]:
            self.assertTrue(case["post_fix_failed"], case)
            self.assertTrue(case["pre_fix_legacy_passed"], case)

    def test_legacy_algorithm_is_masked_by_defect_targeting_controls(self):
        observer = _observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        next(s for s in fixture["scenarios"] if s["id"] == "duplicate-delivery")["assertions"]["at_most_once"] = False
        legacy = observer.legacy_compute_verdict(contract, fixture)
        fixed = observer.compute_verdict(contract, fixture)
        self.assertTrue(legacy["all_pass"])
        self.assertFalse(fixed["all_pass"])


if __name__ == "__main__":
    unittest.main()
