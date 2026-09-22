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
OBSERVATIONS = EVIDENCE / "observations.v2.json"
VERDICT = EVIDENCE / "verdict.v2.json"
CONTROLS = EVIDENCE / "negative-controls.v2.json"
CURRENT_BUILD_REVISION = "dsh-0.1.5rc1-post-u8.209"

B1 = "subagent-child-crash"
B2 = "subagent-byq-adapter-restart"
REQUIRED_SCENARIOS = {
    "executor-loss-interrupted",
    "late-success-no-overwrite",
    "ordinary-failed-not-interrupted",
    "mismatched-run-not-interrupted",
    "mismatched-trace-not-interrupted",
    "missing-summary-session-not-interrupted",
    "missing-terminal-run-not-interrupted",
    "invalid-terminal-run-not-interrupted",
    "cancelled-not-interrupted",
    "stale-generation-terminal-fenced",
    "duplicate-terminal-rejected",
    "terminal-reopen-rejected",
    "authority-unavailable-pauses",
    "unknown-side-effect-paused",
    "success-receipt-not-replayed",
    "cancel-blocks-recovery",
    "budget-exhausted-blocks",
    "authorization-revoked-blocks",
    "owner-workspace-mismatch-blocks",
    "preservation-not-constant",
    "recovery-endpoint-never-submits",
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
        self.assertEqual(contract["schema_version"], "byq-v090-session-containment-contract.v2")
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
        for expected in ("executor-loss-fake-completed", "before-after-diverged",
                         "ordinary-failed-marked-interrupted", "mismatched-run-marked-interrupted",
                         "mismatched-trace-marked-interrupted",
                         "missing-summary-session-marked-interrupted",
                         "missing-terminal-run-marked-interrupted",
                         "invalid-terminal-run-marked-interrupted", "authority-unavailable-allowed",
                         "preservation-constant-claim", "preservation-boundary-self-verified",
                         "endpoint-source-mismatch", "success-receipt-replayed"):
            self.assertIn(expected, names)

    def test_committed_evidence_is_breakable_by_a_mutation(self):
        observer = _load(OBSERVER, "v090_session_containment_observer_mut")
        contract = _contract()
        observations = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        self.assertTrue(observer.compute_verdict(contract, observations)["all_pass"])
        for mutate in (
            lambda value: value["scenarios"]["executor-loss-interrupted"]["observed"].update(status="completed"),
            lambda value: value["scenarios"]["ordinary-failed-not-interrupted"]["observed"].update(
                adapter_containment={"schema_version": "s", "session_id": "runtime-1", "contained": True,
                    "latest": {"trace_id": "trace-1", "loss_cause": "executor-loss",
                               "interrupted_run_id": "a" * 32, "interrupted_generation": "g",
                               "executor_epoch": 1}}),
            lambda value: value["scenarios"]["preservation-not-constant"]["observed"].update(
                after={"session_started": 0, "prompt_receipts": 0, "run_events": 0}),
            lambda value: value["scenarios"]["missing-summary-session-not-interrupted"]["observed"][
                "adapter_containment"].update(session_id="runtime-1"),
            lambda value: value["scenarios"]["missing-terminal-run-not-interrupted"]["observed"][
                "events"][1].update(payload={"run_id": "a" * 32}),
            lambda value: value["scenarios"]["invalid-terminal-run-not-interrupted"]["observed"][
                "events"][1].update(payload={"run_id": "a" * 32}),
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
        self.assertGreater(controls["control_count"], 0)

    def test_observations_are_bound_to_the_current_sources(self):
        observations = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        digests = observations["provenance"]["source_sha256"]
        for relative, expected in digests.items():
            self.assertEqual(expected, _sha256(ROOT / relative), relative)
        for relative in ("services/runtime-adapter/app/containment.py",
                         "services/gateway/app/session_containment.py",
                         "services/gateway/app/main.py"):
            self.assertIn(relative, digests)

    def test_loss_observation_is_truthful_with_real_before_after_state(self):
        observed = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))[
            "scenarios"]["executor-loss-interrupted"]["observed"]
        self.assertEqual(observed["status"], "interrupted")
        self.assertEqual(observed["loss_cause"], "executor-loss")
        self.assertEqual(observed["before"], observed["after"])
        self.assertGreater(observed["before"]["prompt_receipts"], 0)
        self.assertTrue(observed["history_unchanged"])
        self.assertRegex(observed["interrupted_run_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(observed["trace_id"], observed["expected_trace_id"])

    def test_preservation_is_not_a_constant_claim(self):
        observed = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))[
            "scenarios"]["preservation-not-constant"]["observed"]
        self.assertEqual(observed["before"], observed["after"])
        projection = observed["preservation"]
        self.assertFalse(projection["boundary_verified"])
        self.assertEqual(projection["states"]["durable_job"], "unknown")
        self.assertNotEqual(set(projection["states"].values()), {"preserved"})


class BoundaryTests(unittest.TestCase):
    def test_recovery_endpoint_cannot_submit(self):
        source = (ROOT / "services/gateway/app/main.py").read_text(encoding="utf-8")
        start = source.index("def get_recovery_classification(")
        end = source.index("@app.", start)
        body = source[start:end]
        self.assertNotIn("_adapter_post", body)
        self.assertNotIn("/prompt", body)
        self.assertNotIn("_runtime_recovery_payload", body)
        self.assertIn('"submitted": False', body)
        self.assertFalse((ROOT / "services/gateway/app/session_containment.py").read_text(
            encoding="utf-8").count("RecoveryAttemptStore"))

    def test_status_keeps_b1_b2_blocked_external_and_r3_frozen(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        for marker in ("<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->",
                       "<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->",
                       "<!-- byq:v090-session-containment=containment-classification-delivered -->",
                       "<!-- byq:session-failure-containment=real-recovery-acceptance-passed -->",
                       "<!-- byq:session-failure-containment-next=v090-final-development-closeout -->",
                       "<!-- byq:build-revision=dsh-0.1.5rc1-post-u8.209 -->"):
            self.assertIn(marker, status)
        self.assertIn("R3_RESUME = NO", status)
        self.assertIn("D15-G", status)

    def test_status_rejects_complete_next_contradiction(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        # The full ADR-0084 gate is NOT complete: a `complete` value for it, or a
        # slice `complete` marker alongside a `next` marker for the same gate, is
        # the self-contradiction this rectification removed.
        self.assertNotIn("<!-- byq:session-failure-containment=complete -->", status)
        self.assertNotIn("<!-- byq:session-failure-containment=next -->", status)
        self.assertNotIn("<!-- byq:v090-session-containment=complete -->", status)
        self.assertIn("IN_PROGRESS / BLOCKED_INTERNAL", status)
        self.assertIn("authoritative server-side step-safety + budget binding", status)
        # A `next` marker must exist precisely because the gate is not complete.
        self.assertIn("<!-- byq:session-failure-containment-next=", status)

    def test_no_superseding_assessment_while_full_gate_unpassed(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        self.assertNotIn("byq:v090-d15-superseding=passed", status)
        # The document must explicitly refuse the claim while the full gate is
        # unpassed, rather than assert a passed superseding assessment.
        self.assertIn("不生成也不声称", status)
        self.assertNotIn("superseding assessment 已通过", status)
        self.assertNotIn("superseding assessment passed", status)
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

    def test_no_tmp_authority_ledger_remains(self):
        for path in (ROOT / "services/gateway/app").rglob("*.py"):
            self.assertNotIn("byq-recovery-attempts", path.read_text(encoding="utf-8"), str(path))
            self.assertNotIn("RecoveryAttemptStore", path.read_text(encoding="utf-8"), str(path))

    def test_production_selector_is_promoted_with_historical_rollback(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.5rc1")
        self.assertIn("dsh-0.1.2rc1", deployment["candidate_releases"])

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id("dsh-0.1.5rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        self.assertTrue((ROOT / "config/dsh/builds/dsh-0.1.2rc1-post-u8.189.json").is_file())


if __name__ == "__main__":
    unittest.main()
