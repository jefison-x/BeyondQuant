"""ADR-0084 BYQ session failure containment and business recovery acceptance.

Runs under ``unittest`` (architecture lane). Asserts the fail-ability of the
observer, the truthfulness of the committed evidence, the source binding, and
that the ADR-0084 boundary changes did not silently rewrite historical D15
verdicts, downgrade B1/B2, unfreeze R3, or claim a superseding assessment.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINMENT = ROOT / "scripts/v090/session_containment"
CONTRACT = CONTAINMENT / "contract.v1.json"
OBSERVER = CONTAINMENT / "observer.py"
CAPTURE = CONTAINMENT / "capture.py"
EVIDENCE = ROOT / "docs/evidence/v090-session-containment"
OBSERVATIONS = EVIDENCE / "observations.v1.json"
VERDICT = EVIDENCE / "verdict.v1.json"
CONTROLS = EVIDENCE / "negative-controls.v1.json"
CURRENT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.190"

B1 = "subagent-child-crash"
B2 = "subagent-byq-adapter-restart"
REQUIRED_SCENARIOS = {
    "executor-loss-interrupted",
    "stale-generation-terminal-fenced",
    "late-success-no-overwrite",
    "duplicate-terminal-rejected",
    "terminal-reopen-rejected",
    "idempotent-no-receipt-one-attempt-lineage",
    "success-receipt-not-replayed",
    "unknown-side-effect-paused",
    "cancel-blocks-recovery",
    "budget-exhausted-blocks",
    "authorization-revoked-blocks",
    "owner-workspace-mismatch-blocks",
    "concurrent-recovery-one-attempt",
    "observer-breakable",
}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class ContractTests(unittest.TestCase):
    def test_contract_declares_every_required_fail_able_scenario(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"],
                         "byq-v090-session-containment-contract.v1")
        declared = {scenario["id"] for scenario in contract["scenarios"]}
        self.assertEqual(declared, REQUIRED_SCENARIOS)
        self.assertTrue(all(scenario["required"] for scenario in contract["scenarios"]))
        self.assertNotIn("raw-dsh-event", contract["provenance_allowed_sources"])


class ObserverFailAbilityTests(unittest.TestCase):
    def test_selfcheck_rejects_every_control_and_pre_fix_defects_are_evidenced(self):
        observer = _load(OBSERVER, "v090_session_containment_observer")
        result = observer.run_selfcheck(_contract())
        self.assertTrue(result["baseline_all_pass"])
        self.assertTrue(result["all_controls_pass"])
        self.assertFalse([item for item in result["controls"] if item["observed_all_pass"]])
        self.assertGreaterEqual(result["defect_targeting_count"], 8)
        self.assertTrue(result["defect_targeting_pre_fix_passed"])
        names = {item["name"] for item in result["controls"]}
        for expected in ("executor-loss-fake-completed", "stale-generation-not-fenced",
                         "duplicate-terminal-not-fenced", "terminal-reopen-not-fenced",
                         "unknown-side-effect-auto-retry", "cancel-recoverable",
                         "success-receipt-replayed", "concurrent-second-attempt",
                         "negative-controls-trusted", "provenance-digest-mismatch"):
            self.assertIn(expected, names)

    def test_committed_evidence_is_breakable_by_a_mutation(self):
        observer = _load(OBSERVER, "v090_session_containment_observer_mut")
        contract = _contract()
        observations = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        self.assertTrue(observer.compute_verdict(contract, observations)["all_pass"])
        broken = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        broken["scenarios"]["executor-loss-interrupted"]["observed"]["status"] = "completed"
        verdict = observer.compute_verdict(contract, broken)
        self.assertFalse(verdict["all_pass"])
        self.assertEqual(verdict["exit_code"], 1)


class CommittedEvidenceTests(unittest.TestCase):
    def test_verdict_is_format_valid_and_all_required_scenarios_pass(self):
        verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["all_pass"])
        self.assertEqual(verdict["exit_code"], 0)
        self.assertEqual(verdict["coverage_failures"], [])
        passed = {item["id"] for item in verdict["scenarios"] if item["verdict"] == "PASS"}
        self.assertEqual(passed, REQUIRED_SCENARIOS)

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads(CONTROLS.read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_pass"])
        self.assertTrue(controls["defect_targeting_pre_fix_passed"])
        self.assertGreater(controls["control_count"], 0)

    def test_observations_are_bound_to_the_current_sources(self):
        observations = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        digests = observations["provenance"]["source_sha256"]
        for relative, expected in digests.items():
            self.assertEqual(expected, _sha256(ROOT / relative), relative)
        self.assertIn("services/runtime-adapter/app/containment.py", digests)
        self.assertIn("services/gateway/app/session_containment.py", digests)

    def test_loss_observation_is_truthful_and_preserves_state(self):
        observed = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))[
            "scenarios"]["executor-loss-interrupted"]["observed"]
        self.assertEqual(observed["status"], "interrupted")
        self.assertEqual(observed["loss_cause"], "executor-loss")
        self.assertTrue(observed["preserved"])
        self.assertTrue(observed["history_unchanged"])
        self.assertEqual(observed["interrupted_run_id"], observed["expected_run"])


class BoundaryTests(unittest.TestCase):
    def test_status_keeps_b1_b2_blocked_external_and_r3_frozen(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        for marker in ("<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->",
                       "<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->",
                       "<!-- byq:v090-session-containment=complete -->",
                       "<!-- byq:build-revision=dsh-0.1.2rc1-post-u8.190 -->"):
            self.assertIn(marker, status)
        self.assertIn("R3_RESUME = NO", status)
        self.assertIn("D15-G", status)

    def test_no_superseding_assessment_is_claimed(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        self.assertNotIn("byq:v090-d15-superseding=passed", status)
        for path in EVIDENCE.rglob("*"):
            if path.is_file():
                self.assertNotIn("superseding_assessment_passed",
                                 path.read_text(encoding="utf-8", errors="ignore"), str(path))

    def test_historical_d15_g_verdict_is_not_rewritten(self):
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")

    def test_no_second_harness_session_store_or_dsh_business_db_access(self):
        for path in (ROOT / "services/runtime-adapter/app/containment.py",
                     ROOT / "services/gateway/app/session_containment.py",
                     ROOT / "packages/contracts/session_failure_containment.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("psycopg", text, str(path))
            self.assertNotIn("asyncpg", text, str(path))
            self.assertNotIn("sqlalchemy", text.lower(), str(path))
            self.assertNotIn("PTY", text, str(path))
            self.assertNotIn("import pty", text, str(path))

    def test_production_selector_is_unchanged(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.2rc1")

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id("dsh-0.1.2rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        self.assertTrue((ROOT / "config/dsh/builds/dsh-0.1.2rc1-post-u8.189.json").is_file())


if __name__ == "__main__":
    unittest.main()
