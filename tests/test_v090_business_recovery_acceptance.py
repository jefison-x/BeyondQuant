"""v090 REAL business-recovery acceptance of the merged #352 vertical slice.

Asserts the committed RAW observations are self-consistent and fail-able: the
observer re-derives every verdict from raw fields (not the PASS label), the
negative controls are all rejected, the cleanup proof is zero, and the minimal
#352 defect fix is present. Runs under ``unittest`` (architecture lane); the
capture itself is Docker-gated and is not part of this lane.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts/v090/business_recovery_acceptance"
CONTRACT = HARNESS / "contract.v1.json"
OBSERVER = HARNESS / "observer.py"
EVIDENCE = ROOT / "docs/evidence/v090-business-recovery-acceptance"
OBSERVATIONS = EVIDENCE / "observations.v1.json"
VERDICT = EVIDENCE / "verdict.v1.json"
CONTROLS = EVIDENCE / "negative-controls.v1.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _observer():
    return _load(OBSERVER, "v090_business_recovery_acceptance_observer")


class ContractTests(unittest.TestCase):
    def test_contract_matches_observer_required_scenarios(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        observer = _observer()
        self.assertEqual(contract["schema_version"],
                         "byq-v090-business-recovery-acceptance-contract.v1")
        self.assertEqual({item["id"] for item in contract["required_scenarios"]},
                         set(observer.REQUIRED))
        self.assertTrue(all(item["required"] for item in contract["required_scenarios"]))


class ObserverFailAbilityTests(unittest.TestCase):
    def test_selfcheck_rejects_every_defect_targeting_control(self):
        base = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        controls = _observer().run_selfcheck(base)
        self.assertTrue(controls["all_controls_rejected"])
        self.assertGreaterEqual(controls["defect_targeting_count"], 20)
        self.assertFalse([item for item in controls["controls"] if not item["rejected"]])
        names = {item["control"] for item in controls["controls"]}
        for expected in ("label-only-pass", "target-equals-lost", "containment-wrong-run",
                         "no-real-process-termination", "no-guard-charge",
                         "read-only-recovery-wrote-business", "retry-created-second-generation",
                         "forged-not-refused", "unknown-cost-not-paused", "floor-not-blocked",
                         "ordinal-cap-not-blocked", "stale-target-not-refused",
                         "new-key-not-refused", "cross-task-not-refused", "missing-provenance"):
            self.assertIn(expected, names)

    def test_committed_observations_are_breakable_by_a_mutation(self):
        observer = _observer()
        base = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        self.assertTrue(observer.verify(base)["all_pass"])
        for mutate in (
            lambda value: value["scenarios"]["real-executor-loss-and-recovery"]["observed"].update(
                target_run_id=value["scenarios"]["real-executor-loss-and-recovery"]["observed"]["lost_run_id"]),
            lambda value: value["scenarios"]["real-executor-loss-and-recovery"]["observed"][
                "containment"]["latest"].update(interrupted_run_id="f" * 32),
            lambda value: value["scenarios"]["negative-unknown-cost-paused"]["observed"].update(
                dispatch=True, recovery={"status": "eligible", "reason": "recovery_attempt"}),
            lambda value: value["scenarios"]["negative-recovery-new-key"]["observed"].update(status=201),
        ):
            broken = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
            mutate(broken)
            self.assertFalse(observer.verify(broken)["all_pass"])


class CommittedEvidenceTests(unittest.TestCase):
    def test_verdict_is_format_valid_and_all_required_scenarios_pass(self):
        verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["all_pass"])
        self.assertEqual(verdict["failures"], [])
        observer = _observer()
        self.assertEqual(set(verdict["scenarios"]), set(observer.REQUIRED))

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads(CONTROLS.read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_rejected"])
        self.assertGreaterEqual(controls["defect_targeting_count"], 20)

    def test_cleanup_proof_is_zero_and_production_untouched(self):
        cleanup = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))["cleanup"]
        self.assertEqual(cleanup["containers_remaining"], 0)
        self.assertEqual(cleanup["networks_remaining"], 0)
        self.assertEqual(cleanup["volumes_remaining"], 0)
        self.assertTrue(cleanup["production_untouched"])

    def test_observations_are_bound_to_the_real_stack(self):
        observations = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        self.assertEqual(observations["schema_version"],
                         "byq-v090-business-recovery-acceptance-observations.v1")
        for scenario in observations["scenarios"].values():
            self.assertEqual(scenario["provenance"]["source"], "real-isolated-services")
        happy = observations["scenarios"]["real-executor-loss-and-recovery"]["observed"]
        self.assertNotEqual(happy["adapter_pid_before"], happy["adapter_pid_after"])
        self.assertEqual(happy["containment"]["latest"]["loss_cause"], "executor-loss")
        self.assertEqual(happy["business_counts_before"], happy["business_counts_after"])


class DefectFixTests(unittest.TestCase):
    def test_lost_original_prompt_is_not_reconciled_as_accepted(self):
        runtime = (ROOT / "services/runtime-adapter/app/runtime.py").read_text(encoding="utf-8")
        self.assertIn("_reconcile_lost_receipt", runtime)
        self.assertIn("interrupted_run_id", runtime)


class BoundaryTests(unittest.TestCase):
    def test_status_keeps_gate_in_progress_and_b1_b2_unchanged(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        for marker in ("<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->",
                       "<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->",
                       "<!-- byq:session-failure-containment=real-recovery-acceptance-passed -->",
                       "<!-- byq:v090-business-recovery=implementation-delivered -->"):
            self.assertIn(marker, status)
        self.assertIn("R3_RESUME = NO", status)

    def test_production_selector_is_promoted_with_historical_rollback(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.5rc1")
        self.assertIn("dsh-0.1.2rc1", deployment["candidate_releases"])
        pyproject = (ROOT / "services/runtime-adapter/pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("deepseek-harness-sdk==0.1.5rc1", pyproject)

    def test_historical_d15_g_verdict_is_not_rewritten(self):
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")

    def test_no_superseding_assessment_generated(self):
        for path in EVIDENCE.rglob("*"):
            if path.is_file():
                self.assertNotIn("superseding_assessment_passed",
                                 path.read_text(encoding="utf-8", errors="ignore"), str(path))


if __name__ == "__main__":
    unittest.main()
