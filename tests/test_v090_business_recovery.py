"""ADR-0084 business-recovery vertical slice acceptance (the #351 minimal design).

Runs under ``unittest`` (architecture lane). Asserts the real contract logic, the
fail-ability of the observer, the truthfulness of the committed evidence, the
source binding, and that the slice introduced no new store/migration/cross-Plane
authority/trust subject, did not switch the production selector, did not advance
B1/B2, and did not generate a D15 superseding assessment.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts/v090/business_recovery"
CONTRACT = HARNESS / "contract.v1.json"
OBSERVER = HARNESS / "observer.py"
EVIDENCE = ROOT / "docs/evidence/v090-business-recovery"
OBSERVATIONS = EVIDENCE / "observations.v1.json"
VERDICT = EVIDENCE / "verdict.v1.json"
CONTROLS = EVIDENCE / "negative-controls.v1.json"
CURRENT_BUILD_REVISION = "dsh-0.1.5rc1-post-u8.210"

REQUIRED_SCENARIOS = {
    "same-trigger-same-snapshot-exactly-once",
    "retry-reuses-original-ordinal",
    "snapshot-change-no-overwrite-no-extra-ordinal",
    "ordinal-cap-blocks",
    "no-double-deduction",
    "model-call-floor-required",
    "unknown-cost-paused",
    "evidence-conflict-blocked",
    "grant-invariant-blocked",
    "envelope-new-key-blocked",
    "envelope-exact-reuse-eligible",
    "envelope-non-original-call-blocked",
    "snapshot-digest-tamper-paused",
    "snapshot-tail-change-paused",
    "snapshot-idle-flip-paused",
    "carrier-extra-field-rejected",
    "carrier-trigger-mismatch-rejected",
    "target-stale-epoch-rejected",
    "target-stale-generation-rejected",
    "gateway-forwards-closed-carrier",
    "gateway-rejects-invented-field",
    "real-adapter-journal-snapshot-closure",
    "observer-breakable",
}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class ContractTests(unittest.TestCase):
    def test_historical_contract_declares_every_recorded_scenario(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-v090-business-recovery-contract.v1")
        declared = {scenario["id"] for scenario in contract["scenarios"]}
        self.assertEqual(declared, REQUIRED_SCENARIOS)
        self.assertTrue(all(scenario["required"] for scenario in contract["scenarios"]))


class ObserverFailAbilityTests(unittest.TestCase):
    def test_committed_evidence_is_breakable_by_a_mutation(self):
        observer = _load(OBSERVER, "v090_business_recovery_observer_mut")
        contract = _contract()
        observations = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        self.assertTrue(observer.compute_verdict(contract, observations)["all_pass"])
        for mutate in (
            lambda value: value["scenarios"]["same-trigger-same-snapshot-exactly-once"]["observed"][
                "expect"][1].update({"created": True, "ordinal": 2}),
            lambda value: value["scenarios"]["no-double-deduction"]["observed"]["inputs"].update(cum_exact=0),
            lambda value: value["scenarios"]["snapshot-idle-flip-paused"]["observed"].update(idle=True),
            lambda value: value["scenarios"]["gateway-rejects-invented-field"]["observed"].update(
                mutation=None),
            lambda value: value["scenarios"]["real-adapter-journal-snapshot-closure"]["observed"].update(
                digest="0" * 64),
        ):
            broken = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
            mutate(broken)
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
        self.assertGreaterEqual(controls["defect_targeting_count"], 20)

    def test_observations_are_bound_to_reachable_historical_sources(self):
        observer = _load(OBSERVER, "v090_business_recovery_observer_history")
        observations = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        digests = observations["provenance"]["source_sha256"]
        for relative, expected in digests.items():
            self.assertTrue(
                observer._digest_exists_in_git_history(relative, expected), relative
            )
        for relative in ("packages/contracts/business_recovery.py",
                         "services/runtime-adapter/app/business_recovery.py",
                         "services/gateway/app/recovery_carrier.py",
                         "services/backend/app/research_continuation.py"):
            self.assertIn(relative, digests)

class BoundaryTests(unittest.TestCase):
    def test_no_new_store_migration_cross_plane_authority_or_trust_subject(self):
        self.assertFalse((ROOT / "services/gateway/app/recovery_carrier.py").exists())
        for relative in ("packages/contracts/business_recovery.py",):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("psycopg", text, relative)
            self.assertNotIn("asyncpg", text, relative)
            self.assertNotIn("sqlalchemy", text.lower(), relative)
            self.assertNotIn("CREATE TABLE", text, relative)
            self.assertNotIn("byq-recovery-attempt-store", text, relative)
        # The attempt aggregate is an in-row JSONB addition, not a new table.
        self.assertNotIn("recovery_attempt", (ROOT / "services/backend/app/db.py").read_text(encoding="utf-8"))

    def test_runtime_adapter_has_no_recovery_attempt_admission(self):
        runtime = (ROOT / "services/runtime-adapter/app/runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("business_recovery", runtime)
        self.assertNotIn("recovery_receipts", runtime)
        self.assertNotIn("_recovery_anchor", runtime)
        adapter_contract = (ROOT / "services/runtime-adapter/app/continuation_budget.py").read_text(encoding="utf-8")
        self.assertNotIn("recovery_attempt", adapter_contract)

    def test_status_records_recovery_acceptance_and_b1_b2_unchanged(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        for marker in ("<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->",
                       "<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->",
                       "<!-- byq:session-failure-containment=real-recovery-acceptance-passed -->",
                       "<!-- byq:v090-business-recovery=implementation-delivered -->",
                       "<!-- byq:session-failure-containment-next=v090-final-development-closeout -->",
                       ):
            self.assertIn(marker, status)
        self.assertRegex(status, r"<!-- byq:build-revision=dsh-0\.1\.5rc1-post-u8\.\d+ -->")
        self.assertIn("R3_RESUME = NO", status)
        self.assertIn("IN_PROGRESS / BLOCKED_INTERNAL", status)

    def test_no_superseding_assessment_generated(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        self.assertNotIn("byq:v090-d15-superseding=passed", status)
        self.assertIn("尚未生成", status)
        for path in EVIDENCE.rglob("*"):
            if path.is_file():
                self.assertNotIn("superseding_assessment_passed",
                                 path.read_text(encoding="utf-8", errors="ignore"), str(path))

    def test_production_selector_is_promoted_with_historical_rollback(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.5rc1")
        self.assertIn("dsh-0.1.2rc1", deployment["candidate_releases"])
        pyproject = (ROOT / "services/runtime-adapter/pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("deepseek-harness-sdk==0.1.5rc1", pyproject)
        self.assertIn("deepseek-harness-runtime-bin==0.1.5rc1", pyproject)

    def test_historical_d15_g_verdict_is_not_rewritten(self):
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertRegex(builds.selected_build_id("dsh-0.1.5rc1"),
                         r"^dsh-0\.1\.5rc1-post-u8\.\d+$")
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        self.assertTrue((ROOT / "config/dsh/builds/dsh-0.1.2rc1-post-u8.196.json").is_file())


if __name__ == "__main__":
    unittest.main()
