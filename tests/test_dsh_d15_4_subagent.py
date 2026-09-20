"""D15-4 native subagent/fork continuity acceptance tests.

Covers the fail-able observer (format-valid vs qualification-pass separation,
required BLOCKED/NOT_RUN gating, contract-authoritative assertions, honest
pre-fix comparison), the committed evidence truthfulness, and the reachability
probe facts. Runs under ``unittest`` (the architecture lane has no pytest).

Set ``BYQ_D15_4_RUN_NATIVE=1`` to additionally execute the real native harness
(requires ``npm ci`` in ``scripts/d15/subagent`` and a Node runtime).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBAGENT = ROOT / "scripts/d15/subagent"
OBSERVER = SUBAGENT / "observer.py"
CONTRACT = SUBAGENT / "contract.v1.json"
EVIDENCE = ROOT / "docs/evidence/d15/d15-4"


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_4_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_4_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


class D15SubagentContractTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-d15-4-contract.v1")
        ids = [item["id"] for item in contract["required_scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        for expected in ("parent-child-identity", "continuable-descriptor", "cold-resume",
                         "fork-lineage", "inheritance", "parent-crash", "child-crash",
                         "byq-adapter-restart"):
            self.assertIn(expected, ids)
        optional = [item["id"] for item in contract["optional_scenarios"]]
        self.assertIn("host-reboot", optional)
        self.assertTrue(set(optional).isdisjoint(ids))
        self.assertTrue(contract["required_coverage_gates_qualification"])
        self.assertTrue(contract["negatives_must_all_be_rejected"])
        self.assertEqual(contract["candidate"]["release"], "dsh-0.1.5rc1")
        self.assertEqual(contract["required_evidence_class"], "native-runtime-isolated")

    def test_fully_qualified_fixture_passes_and_required_blocked_fails(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer._fully_qualified_fixture(contract)
        qualified["evidence_class"] = contract["required_evidence_class"]
        verdict = observer.compute_verdict(contract, qualified)
        self.assertTrue(verdict["all_pass"], verdict["failures"])
        self.assertTrue(verdict["format_valid"])

        blocked = observer.valid_fixture(contract)
        verdict = observer.compute_verdict(contract, blocked, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertIn("child-crash", verdict["reason_uncovered"])
        self.assertIn("byq-adapter-restart", verdict["reason_uncovered"])

    def test_every_negative_control_fails_and_pre_fix_defects_are_evidenced(self):
        observer = _load_observer()
        contract = _contract()
        result = observer.selfcheck(contract)
        self.assertTrue(result["all_controls_pass"])
        self.assertTrue(result["known_good_unit_fixture_format_valid"])
        self.assertTrue(result["known_good_unit_fixture_all_pass"])
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)

    def test_fault_is_required_where_the_contract_demands_it(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer._fully_qualified_fixture(contract)
        qualified["evidence_class"] = contract["required_evidence_class"]
        for scenario in qualified["scenarios"]:
            if scenario["id"] == "parent-crash":
                scenario["fault_applied"] = False
        verdict = observer.compute_verdict(contract, qualified)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("fault_applied" in failure for failure in verdict["failures"]))

    def test_observation_may_not_declare_its_own_coverage(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer._fully_qualified_fixture(contract)
        qualified["evidence_class"] = contract["required_evidence_class"]
        for scenario in qualified["scenarios"]:
            if scenario["id"] == "cold-resume":
                scenario["required"] = False
                scenario["assertions_ok"] = True
        verdict = observer.compute_verdict(contract, qualified)
        self.assertFalse(verdict["format_valid"])
        self.assertTrue(any("may not declare" in failure for failure in verdict["failures"]))


class D15SubagentEvidenceTests(unittest.TestCase):
    def test_committed_verdict_is_truthful_and_not_a_full_pass(self):
        verdict = json.loads((EVIDENCE / "verdict.v1.json").read_text(encoding="utf-8"))
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["negatives_ok"])
        coverage = verdict["required_coverage"]
        for scenario_id in ("parent-child-identity", "continuable-descriptor", "cold-resume",
                            "fork-lineage", "inheritance", "parent-crash"):
            self.assertEqual(coverage[scenario_id], "PASS", scenario_id)
        self.assertEqual(coverage["child-crash"], "BLOCKED")
        self.assertEqual(coverage["byq-adapter-restart"], "BLOCKED")
        self.assertEqual(verdict["optional_coverage"]["host-reboot"], "NOT_RUN")

    def test_reachability_evidence_matches_the_committed_composition(self):
        reachability = json.loads((EVIDENCE / "reachability.v1.json").read_text(encoding="utf-8"))
        facts = reachability["facts"]
        self.assertTrue(facts["composes_subagent_package"])
        self.assertTrue(facts["composes_spawn_provider"])
        self.assertTrue(facts["composes_fork_provider"])
        self.assertEqual(facts["delegate_tool_count"], 5)
        self.assertEqual(facts["enable_run_in_background_false"], 5)
        self.assertEqual(facts["enable_run_in_background_true"], 0)
        self.assertTrue(facts["compat_inherits_0_1_2_contract"])
        by_interface = {item["interface"]: item for item in reachability["interfaces"]}
        self.assertNotEqual(
            by_interface["startContinuable_activation_registry"]["status"], "REACHABLE_FROM_BYQ_COMPOSITION")

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads((EVIDENCE / "negative-controls.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_pass"])
        self.assertGreater(controls["control_count"], 0)


@unittest.skipUnless(os.environ.get("BYQ_D15_4_RUN_NATIVE") == "1",
                     "set BYQ_D15_4_RUN_NATIVE=1 to run the real native harness")
class D15SubagentNativeIntegrationTests(unittest.TestCase):
    def test_native_harness_qualifies_the_reachable_items(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "native-observations.v1.json"
            result = subprocess.run(
                ["node", "native_subagent_harness.mjs", "run", "--out", str(out)],
                cwd=SUBAGENT, capture_output=True, text=True, timeout=600)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            observations = json.loads(out.read_text(encoding="utf-8"))
        by_id = {item["id"]: item["result"] for item in observations["scenarios"]}
        for scenario_id in ("parent-child-identity", "continuable-descriptor", "cold-resume",
                            "fork-lineage", "inheritance", "parent-crash"):
            self.assertEqual(by_id[scenario_id], "PASS", scenario_id)
        self.assertTrue(all(item["rejected"] for item in observations["negatives"]))


if __name__ == "__main__":
    unittest.main()
