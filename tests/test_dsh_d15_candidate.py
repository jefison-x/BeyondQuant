"""D15-0/D15-1: ledger integrity, candidate isolation and production-default freeze."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.dsh import candidate_registry


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/d15"
LEDGER = EVIDENCE / "compatibility-ledger.v1.json"
RECON = EVIDENCE / "upgrade-recon.v1.json"
FIXTURES = EVIDENCE / "fixtures/manifest.v1.json"
TARGET_DECISION = EVIDENCE / "target-decision.v1.json"
CANDIDATE = "dsh-0.1.5rc1"
DEFAULT = "dsh-0.1.2rc1"
TARGET_TAG = "dsh-v0.1.5-rc.1"


class D15CandidateTests(unittest.TestCase):
    def test_candidate_registry_declares_one_unqualified_isolated_candidate(self) -> None:
        candidates = candidate_registry.load_candidates()
        self.assertEqual(sorted(candidates), [CANDIDATE])
        value = candidates[CANDIDATE]
        self.assertEqual(value["status"], "candidate-unqualified")
        self.assertEqual(value["production_default"], DEFAULT)
        self.assertEqual(value["qualification_target"], TARGET_TAG)
        self.assertEqual(value["target_npm_version"], "0.1.5-rc.1")
        self.assertEqual(value["qualification"]["state"], "not-qualified")
        self.assertTrue(value["qualification"]["live_start_verified"])
        self.assertFalse(value["qualification"]["native_resume_verified"])
        self.assertIsNone(value["qualification"]["blocking_finding"])
        self.assertEqual(value["runtime"]["selector_env"], "BYQ_DSH_COMPATIBILITY_RELEASE")
        self.assertEqual(value["runtime"]["selector_value"], CANDIDATE)
        self.assertTrue(value["runtime"]["isolated"])

    def test_candidate_declares_production_boundary_and_rollback(self) -> None:
        boundary = candidate_registry.load_candidates()[CANDIDATE]["production_boundary"]
        self.assertTrue(boundary["default_release_unchanged"])
        self.assertTrue(boundary["default_env_unchanged"])
        self.assertTrue(boundary["existing_artifacts_untouched"])
        self.assertTrue(boundary["historical_evidence_untouched"])
        self.assertEqual(boundary["database_changes"], "none")
        self.assertEqual(boundary["worker_restarts"], "none")
        self.assertEqual(boundary["rollback_release"], DEFAULT)

    def test_candidate_declaration_rejects_tampering(self) -> None:
        import copy
        import tempfile

        original = candidate_registry.load_candidate(
            ROOT / "config/dsh/candidates" / CANDIDATE / "candidate.json"
        )
        mutations = (
            lambda v: v.update(status="candidate-qualified"),
            lambda v: v["runtime"].update(selector_value="something-else"),
            lambda v: v["runtime"].update(isolated=False),
            lambda v: v["production_boundary"].update(default_release_unchanged=False),
            lambda v: v["production_boundary"].update(database_changes="migrate"),
            lambda v: v["upstream"].update(source_commit="deadbeef"),
            lambda v: v["python"].update(sdk="0.1.5rc2"),
            lambda v: v.update(target_npm_version="0.1.5-rc.2"),
            lambda v: v.update(qualification_target="0.1.5-rc.2"),
            lambda v: v.update(target_decision="docs/evidence/d15/missing.json"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = copy.deepcopy(original)
                mutate(value)
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory) / CANDIDATE
                    root.mkdir()
                    (root / "candidate.json").write_text(json.dumps(value))
                    with self.assertRaises(candidate_registry.CandidateError):
                        candidate_registry.load_candidate(root / "candidate.json")

    def test_selector_routes_only_the_candidate(self) -> None:
        selected = candidate_registry.compatibility_selector(CANDIDATE)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["status"], "candidate-unqualified")
        self.assertEqual(selected["selector_env"], "BYQ_DSH_COMPATIBILITY_RELEASE")
        self.assertTrue(selected["compatibility_module"].endswith("compat/dsh_015.py"))
        self.assertIsNone(candidate_registry.compatibility_selector(DEFAULT))

    def test_production_default_and_images_are_unchanged(self) -> None:
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text())
        self.assertEqual(deployment["default_release"], DEFAULT)
        self.assertEqual(deployment["candidate_releases"], [])
        compose = (ROOT / "compose.yml").read_text()
        self.assertIn("BYQ_DSH_COMPATIBILITY_RELEASE:-dsh-0.1.2rc1", compose)
        self.assertNotIn("BYQ_DSH_COMPATIBILITY_RELEASE:-dsh-0.1.5rc1", compose)
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile.post-u8-candidate").read_text()
        self.assertIn("BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.2rc1", dockerfile)
        self.assertNotIn("BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.5rc1", dockerfile)
        pyproject = (ROOT / "services/runtime-adapter/pyproject.toml").read_text()
        self.assertIn('"deepseek-harness-sdk==0.1.2rc1"', pyproject)
        self.assertIn('"deepseek-harness-runtime-bin==0.1.2rc1"', pyproject)
        # The immutable release registry must not be extended by an unqualified candidate.
        self.assertFalse((ROOT / "config/dsh/releases" / f"{CANDIDATE}.json").exists())

    def test_compat_boundary_exposes_candidate_without_wiring_native_adoption(self) -> None:
        compat = (ROOT / "services/runtime-adapter/app/compat/__init__.py").read_text()
        self.assertIn('if release == "dsh-0.1.2rc1"', compat)
        self.assertIn('if release == "dsh-0.1.5rc1"', compat)
        candidate_module = (
            ROOT / "services/runtime-adapter/app/compat/dsh_015.py"
        ).read_text()
        self.assertIn("class Dsh015Compatibility", candidate_module)
        self.assertIn('family = "dsh-0.1.5"', candidate_module)

    def test_ledger_covers_interfaces_with_consistent_counts(self) -> None:
        ledger = json.loads(LEDGER.read_text())
        self.assertEqual(ledger["baseline_release_id"], "dsh-0.1.2rc1")
        self.assertEqual(ledger["candidate_release_id"], CANDIDATE)
        self.assertEqual(ledger["qualification_target"], TARGET_TAG)
        self.assertEqual(ledger["target_npm_version"], "0.1.5-rc.1")
        self.assertEqual(ledger["requested_npm_version"], "0.1.5-rc.2")
        self.assertEqual(ledger["candidate_npm_version"], "0.1.5-rc.1")
        interfaces = ledger["interfaces"]
        self.assertGreaterEqual(len(interfaces), 25)
        expected = {"unchanged", "compatible", "changed", "removed", "new", "unknown-needs-probe"}
        self.assertTrue({item["status"] for item in interfaces} <= expected)
        counts: dict[str, int] = {status: 0 for status in expected}
        for item in interfaces:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
            self.assertTrue(item["byq_affected_files"] or item["change_class"] == ["no-change"]
                            or "affects-R3-R4-design" in item["change_class"])
        self.assertEqual(counts, ledger["counts"])
        self.assertGreaterEqual(counts.get("changed", 0), 1)
        self.assertGreaterEqual(counts.get("new", 0), 1)
        self.assertEqual(counts.get("unknown-needs-probe", 0), 0)
        self.assertTrue(ledger["probed"])

    def test_target_decision_resolves_d15_f1_to_rc1(self) -> None:
        decision = json.loads(TARGET_DECISION.read_text())
        self.assertEqual(decision["qualification_target"], CANDIDATE)
        self.assertEqual(decision["target_npm_version"], "0.1.5-rc.1")
        self.assertEqual(decision["superseded_request"], "DSH 0.1.5-rc.2")
        self.assertEqual(decision["finding"], "D15-0-F1")
        self.assertEqual(decision["finding_resolution"], "RESOLVED_BY_MAINTAINER_DECISION")
        self.assertIn("not-a-coherent-pairing", decision["rc2_disposition"])

    def test_d15_1_build_and_probe_evidence(self) -> None:
        build = json.loads((EVIDENCE / "d15-1/candidate-build.v1.json").read_text())
        probe_file = EVIDENCE / "d15-1/candidate-start-probe.v1.json"
        probe = json.loads(probe_file.read_text())
        self.assertEqual(build["release_id"], CANDIDATE)
        self.assertEqual(build["qualification_target"], TARGET_TAG)
        self.assertTrue(build["isolated"])
        self.assertFalse(build["image"]["registry_pushed"])
        self.assertFalse(build["image"]["production_traffic"])
        self.assertIn("0.1.5-rc.1", build["observed"]["runtime_version"])
        for key in ("dockerfile", "requirements_lock", "probe"):
            self.assertTrue((ROOT / build["build_inputs"][key]["path"]).is_file())
        self.assertEqual(probe["sdk"], "0.1.5rc1")
        self.assertEqual(probe["runtime_bin"], "0.1.5rc1")
        self.assertEqual(probe["status"], "PASS")
        self.assertEqual(probe["start_status"], "ready")
        self.assertEqual(probe["final_status"], "idle")
        self.assertTrue(probe["event_seq_contiguous"])
        self.assertIn("tool/call", probe["event_types"])
        self.assertIn("tool/result", probe["event_types"])
        self.assertTrue(probe["message_tool_blocked"])

    def test_production_default_selector_unchanged_after_candidate_build(self) -> None:
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text())
        self.assertEqual(deployment["default_release"], DEFAULT)
        self.assertEqual(deployment["candidate_releases"], [])
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-candidate").read_text()
        self.assertIn("BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.5rc1", dockerfile)
        production = (ROOT / "services/runtime-adapter/Dockerfile.post-u8-candidate").read_text()
        self.assertIn("BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.2rc1", production)
        self.assertNotIn("dsh-0.1.5rc1", production)

    def test_recon_records_the_unpaired_rc2_blocker(self) -> None:
        recon = json.loads(RECON.read_text())
        self.assertEqual(recon["baseline_release"], "dsh-0.1.2rc1")
        self.assertEqual(recon["requested_target"], "DSH 0.1.5-rc.2")
        self.assertEqual(recon["qualification_target"], "DSH 0.1.5-rc.1")
        self.assertEqual(recon["target_release_id"], CANDIDATE)
        self.assertEqual(recon["target_npm_version"], "0.1.5-rc.1")
        self.assertEqual(recon["coherent_candidate"], TARGET_TAG)
        finding = recon["finding"]
        self.assertEqual(finding["id"], "D15-0-F1")
        self.assertIn("0.1.5rc2", finding["statement"])
        self.assertEqual(finding["resolution_status"], "RESOLVED_BY_MAINTAINER_DECISION")
        self.assertEqual(
            recon["artifacts"]["candidate_rc1"]["bundled_npm_version"], "0.1.5-rc.1")
        self.assertFalse(recon["pypi"]["deepseek-harness-sdk"]["present"]["0.1.5rc2"])
        self.assertTrue(recon["pypi"]["deepseek-harness-sdk"]["present"]["0.1.5rc1"])

    def test_fixture_manifest_covers_sessions_and_failure_matrix(self) -> None:
        manifest = json.loads(FIXTURES.read_text())
        categories = {item["category"] for item in manifest["session_fixtures"]}
        self.assertEqual(categories, {
            "normal", "completed", "interrupted", "compacted", "large",
            "subagent", "continuable-subagent", "forked",
            "with-old-lifecycle-evidence",
        })
        faults = {item["fault"] for item in manifest["failure_matrix_rows"]}
        self.assertEqual(faults, {
            "Browser disconnect", "Frontend restart", "Gateway restart",
            "Adapter restart", "DSH crash", "RuntimeGeneration replacement",
            "Host reboot", "executor takeover",
        })
        self.assertIn("immutable", manifest["immutability_rule"])
        self.assertEqual(
            manifest["continuity_diagnostics_internal"]["public_contract"],
            ["fresh", "reattached", "rehydrated", "interrupted"],
        )
        self.assertEqual(manifest["authority_boundary"]["byq_owns"][0],
                         "TerminalAttachment identity")

    def test_acceptance_matrix_covers_every_planned_substage(self) -> None:
        matrix = json.loads((EVIDENCE / "acceptance-matrix.v1.json").read_text())
        stages = {item["id"]: item for item in matrix["substages"]}
        self.assertEqual(list(stages), ["D15-2", "D15-3", "D15-4", "D15-5", "D15-G"])
        self.assertEqual(stages["D15-2"]["result"], "PASS")
        for stage_id in ("D15-3", "D15-4", "D15-5", "D15-G"):
            self.assertEqual(stages[stage_id]["result"], "NOT_RUN")
        for stage in stages.values():
            self.assertTrue(stage["criteria"])
            self.assertTrue(stage["evidence_path"].startswith("docs/evidence/d15/"))
        self.assertTrue(stages["D15-2"]["evidence"])
        self.assertTrue(stages["D15-2"]["criterion_results"])
        self.assertEqual(
            stages["D15-3"]["failure_rows"],
            ["Browser disconnect", "Frontend restart", "Gateway restart", "Adapter restart",
             "DSH crash", "RuntimeGeneration replacement", "Host reboot", "executor takeover"],
        )
        self.assertEqual(len(stages["D15-5"]["terminal_faults"]), 7)


if __name__ == "__main__":
    unittest.main()
