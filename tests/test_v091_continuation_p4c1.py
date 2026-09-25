"""ADR-0085 P4-C1 governance: frozen fault matrix, fail-able observer, scope.

These run in the architecture lane (no PostgreSQL, no Docker). They assert that
the frozen acceptance matrix matches the closed contract, that the observer is
fail-able (every defect-targeting control is rejected while a legacy
label-trusting gate accepts it), that the committed verdict is honestly derived
from the raw observations, and that the slice stays scoped to Adapter/DSH
fault-safe convergence without claiming P4-C2/P4-D or DSH-native recovery.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "scripts/v091/continuation_p4c1"
CONTRACT_PATH = HERE / "contract.v1.json"
EVIDENCE_DIR = ROOT / "docs/evidence/adr-0085-p4c1-adapter-fault-safe"
MATRIX_PATH = EVIDENCE_DIR / "acceptance-matrix.v1.json"
OBSERVATIONS_PATH = EVIDENCE_DIR / "observations.v1.json"
VERDICT_PATH = EVIDENCE_DIR / "verdict.v1.json"
P4A_VERDICT = ROOT / "docs/evidence/adr-0085-p4-real-journey/verdict.v1.json"
P4B_VERDICT = ROOT / "docs/evidence/adr-0085-p4b-normal-journey/verdict.v1.json"


def _load_observer():
    spec = importlib.util.spec_from_file_location("p4c1_observer", HERE / "observer.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["p4c1_observer"] = module
    spec.loader.exec_module(module)
    return module


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    def test_contract_is_closed_and_versioned(self):
        contract = self.contract
        self.assertEqual(contract["schema_version"], "byq-v091-continuation-p4c1-contract.v1")
        self.assertEqual(contract["slice"], "P4-C1")
        self.assertEqual(contract["required_evidence_class"], "runtime-isolated-stack")
        self.assertEqual(contract["llm_evidence_class"], "scripted-keyless")
        faults = [row["id"] for row in contract["required_fault_rows"]]
        boundary = [row["id"] for row in contract["required_boundary_rows"]]
        self.assertEqual(len(faults), len(set(faults)))
        self.assertEqual(len(boundary), len(set(boundary)))
        self.assertIn("F1-adapter-process-killed-inflight", faults)
        self.assertIn("F5-late-old-attempt-result-isolated", faults)
        self.assertIn("F8-no-durable-progress-converges-needs-attention", faults)
        self.assertIn("B5-convergence-is-contract-allowed", boundary)
        self.assertGreaterEqual(len(contract["required_assertions"]), 10)

    def test_contract_keeps_the_native_recovery_non_claim(self):
        blob = json.dumps(self.contract)
        self.assertIn("does NOT claim DSH-native cross-process", blob)
        self.assertIn("P4-C2", blob)
        self.assertIn("P4-D", blob)
        self.assertEqual(self.contract["in_progress_code"], "research_judgment_in_progress")
        for mode in ("provider_block_child", "provider_delay_child",
                     "provider_no_progress_child", "dsh_child_kill", "adapter_process_kill"):
            self.assertIn(mode, self.contract["fault_injection_modes"])

    def test_matrix_matches_contract_and_is_frozen(self):
        contract, matrix = self.contract, self.matrix
        self.assertTrue(matrix["frozen_before_capture"])
        self.assertEqual([row["id"] for row in matrix["fault_rows"]], [
            row["id"] for row in contract["required_fault_rows"]])
        self.assertEqual([row["id"] for row in matrix["boundary_rows"]], [
            row["id"] for row in contract["required_boundary_rows"]])
        self.assertEqual(matrix["assertion_rows"],
                         [{"id": name, "required": True}
                          for name in contract["required_assertions"]])
        self.assertIn("does NOT claim DSH-native", matrix["non_gating_note"])


class ObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = _load_observer()
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_selfcheck_is_fail_able(self):
        self.assertEqual(self.observer.run_selfcheck(self.contract), 0)
        self.assertGreaterEqual(len(self.observer.DEFECT_TARGETING_CONTROLS), 30)

    def test_legacy_gate_accepts_every_defect_targeting_control(self):
        observer = self.observer
        baseline = observer.compute_verdict(self.contract, observer._base_fixture())
        self.assertTrue(baseline["all_pass"])
        for name, fixture in observer._controls():
            self.assertFalse(observer.compute_verdict(self.contract, fixture)["all_pass"],
                             f"control {name} was accepted by the fixed gate")
            if name in observer.DEFECT_TARGETING_CONTROLS:
                self.assertTrue(observer.legacy_compute_verdict(self.contract, fixture)["all_pass"],
                                f"control {name} is not defect-targeting")

    def test_committed_verdict_matches_a_fresh_derivation(self):
        observations = json.loads(OBSERVATIONS_PATH.read_text(encoding="utf-8"))
        verdict = self.observer.compute_verdict(self.contract, observations)
        committed = json.loads(VERDICT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(verdict["format_valid"], committed["format_valid"])
        self.assertEqual(verdict["all_pass"], committed["all_pass"])
        # A PASS is only allowed when every raw-derived row holds.
        if committed["all_pass"]:
            self.assertTrue(verdict["format_valid"])
            for row, ok in verdict["derived_rows"].items():
                self.assertTrue(ok, f"derived row {row} is not observed")
        else:
            self.assertTrue(committed["failures"] or committed["blocked_rows"])


class FaultProviderTests(unittest.TestCase):
    def test_provider_has_the_closed_fault_modes_and_controls(self):
        source = (HERE / "fault_provider.py").read_text(encoding="utf-8")
        for mode in ('"normal"', '"block_child"', '"delay_child"', '"no_progress_child"'):
            self.assertIn(mode, source)
        for route in ('"/_calls"', '"/_state"', '"/_mode"', '"/_release"'):
            self.assertIn(route, source)
        self.assertIn("BOUNDED_STAGE_INPUT", source)

    def test_driver_reuses_the_committed_stack_and_injects_real_faults(self):
        source = (HERE / "run_faults.py").read_text(encoding="utf-8")
        # Reuses the P4-A/P4-B stack and step runner; no second harness.
        self.assertIn("run_p4_isolated.py", source)
        self.assertIn("continuation_p4b/run_journey.py", source)
        self.assertIn("compose.p4-judgment.yml", source)
        self.assertIn("compose.p4c1.yml", source)
        # Real process faults: docker kill the adapter, SIGKILL the DSH child.
        self.assertIn('"kill", ADAPTER_CONTAINER', source)
        self.assertIn("os.kill(int(sys.argv[1]),9)", source)
        self.assertIn("def kill_dsh_child", source)
        self.assertIn('"research-judgment" in lowered', source)
        # Direct real Backend result seam for late/forged results.
        self.assertIn("/internal/research-judgment/", source)


class SliceBoundaryTests(unittest.TestCase):
    def test_prior_p4_verdicts_are_unchanged(self):
        p4a = json.loads(P4A_VERDICT.read_text(encoding="utf-8"))
        p4b = json.loads(P4B_VERDICT.read_text(encoding="utf-8"))
        self.assertFalse(p4a["all_pass"])
        self.assertTrue(p4b["all_pass"])

    def test_status_marks_p4b_merged_and_p4c1_current(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        self.assertIn("byq:v091-continuation-p4b=merged", status)
        self.assertIn("byq:v091-continuation-p4c1=", status)
        self.assertIn("0.10 与 Phase 100 恢复仍**未授权硬停止**", status)

    def test_no_p4c2_or_p4d_implementation_claim(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertIn("does NOT implement or claim P4-C2", json.dumps(contract))
        readme = (EVIDENCE_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("P4-C2", readme)
        self.assertIn("P4-D", readme)
        self.assertIn("DSH-native", readme)


if __name__ == "__main__":
    unittest.main()
