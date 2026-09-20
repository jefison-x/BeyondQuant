"""D15-2 Session V3 migration qualification evidence and live-harness checks.

The committed fixtures under ``docs/evidence/d15/fixtures/sessions`` are
immutable originals. The current ``migration-results.v2.json``,
``fail-closed.v2.json``, ``verdict.v2.json`` and ``negative-controls.v2.json``
are produced by the Node harness in ``scripts/d15/harness`` running the real DSH
0.1.5-rc.1 session-format catalog. The original v1 artifacts are preserved as
historical format-layer evidence.

The deterministic tests validate fixture hashes, evidence schema, acceptance
language, the invariant verdict, the negative controls and fail-closed semantics
without network access. When Node and the harness dependencies are available the
live harness is re-run and its observed results are compared with the committed
evidence; a dependency installation failure is a hard failure, never a skip.

This is format-layer evidence only. It does not prove runtime recovery or the
continuity of an AgentSession goal, approval, domain action or result.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "docs/evidence/d15/fixtures/sessions"
D15_2 = ROOT / "docs/evidence/d15/d15-2"
INDEX = SESSIONS / "index.v1.json"
ACCEPTANCE_MATRIX = ROOT / "docs/evidence/d15/acceptance-matrix.v1.json"
RESULTS = D15_2 / "migration-results.v3.json"
FAIL_CLOSED = D15_2 / "fail-closed.v3.json"
VERDICT = D15_2 / "verdict.v3.json"
NEGATIVE_CONTROLS = D15_2 / "negative-controls.v3.json"
RESULTS_V1 = D15_2 / "migration-results.v1.json"
FAIL_CLOSED_V1 = D15_2 / "fail-closed.v1.json"
RESULTS_V2 = D15_2 / "migration-results.v2.json"
VERDICT_V2 = D15_2 / "verdict.v2.json"
NEGATIVE_CONTROLS_V2 = D15_2 / "negative-controls.v2.json"
HARNESS = ROOT / "scripts/d15/harness"
REQUIRED_STAGES = ["read", "resume", "append", "close", "reopen"]
REQUIRED_FAIL_CLOSED_CASES = [
    "unknown-future-format", "unclassified-event", "malformed-header",
    "refused-surface-migration",
]

EXPECTED_FIXTURES = [
    "f-normal", "f-completed", "f-interrupted", "f-compacted", "f-large",
    "f-subagent", "f-continuable", "f-forked", "f-old-lifecycle",
]
EXPECTED_CATEGORIES = {
    "f-normal": "normal", "f-completed": "completed", "f-interrupted": "interrupted",
    "f-compacted": "compacted", "f-large": "large", "f-subagent": "subagent",
    "f-continuable": "continuable-subagent", "f-forked": "forked",
    "f-old-lifecycle": "with-old-lifecycle-evidence",
}
UNSUPPORTED = "SessionFormatUnsupportedMigrationError"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class D15FixtureIntegrityTests(unittest.TestCase):
    def test_fixture_index_is_complete_and_immutable(self) -> None:
        index = load(INDEX)
        self.assertEqual(index["schema_version"], "byq-d15-2-fixture-index.v1")
        by_id = {item["id"]: item for item in index["fixtures"]}
        self.assertEqual(list(by_id), EXPECTED_FIXTURES)
        for fixture_id in EXPECTED_FIXTURES:
            entry = by_id[fixture_id]
            self.assertEqual(entry["category"], EXPECTED_CATEGORIES[fixture_id])
            self.assertTrue(entry["immutable"])
            path = SESSIONS / fixture_id / "session.jsonl"
            self.assertEqual(sha256_file(path), entry["sha256"], fixture_id)
            rows = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), entry["rows"], fixture_id)
            self.assertEqual(json.loads(rows[0])["version"], entry["source_format"], fixture_id)
            self.assertIn("provenance", entry)
        self.assertIn("REAL", by_id["f-normal"]["provenance"])
        self.assertEqual(by_id["f-normal"]["source_format"], 0)

    def test_old_lifecycle_sibling_is_recorded_and_untouched(self) -> None:
        index = load(INDEX)
        entry = next(item for item in index["fixtures"] if item["id"] == "f-old-lifecycle")
        siblings = {item["name"]: item for item in entry["sibling_files"]}
        self.assertIn("byq-lifecycle-evidence.json", siblings)
        sibling = SESSIONS / "f-old-lifecycle" / "byq-lifecycle-evidence.json"
        self.assertEqual(sha256_file(sibling), siblings["byq-lifecycle-evidence.json"]["sha256"])
        evidence = load(sibling)
        self.assertEqual(evidence["session_id"], "fx-old-lifecycle")
        # The migration harness only ever reads session.jsonl; it never reads or
        # mutates the BYQ lifecycle journal.
        harness_source = (HARNESS / "migration_harness.mjs").read_text(encoding="utf-8")
        self.assertNotIn("byq-lifecycle-evidence", harness_source)


class D15MigrationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = load(RESULTS)
        cls.by_id = {item["id"]: item for item in cls.results["fixtures"]}

    def test_evidence_covers_target_and_every_fixture(self) -> None:
        self.assertEqual(self.results["schema_version"], "byq-d15-2-session-migration-results.v3")
        target = self.results["target"]
        self.assertEqual(target["release_id"], "dsh-0.1.5rc1")
        self.assertEqual(target["python_sdk"], "0.1.5rc1")
        self.assertEqual(target["bundled_npm_version"], "0.1.5-rc.1")
        self.assertEqual(target["source_tag"], "dsh-v0.1.5-rc.1")
        self.assertEqual(list(self.by_id), EXPECTED_FIXTURES)
        self.assertEqual(self.results["harness"]["package_versions"]["@deepseek-ai/dsh-session-format-v2-to-v3"], "0.1.5-rc.1")

    def test_every_fixture_reads_resumes_appends_closes_and_reopens(self) -> None:
        for fixture_id, fixture in self.by_id.items():
            with self.subTest(fixture=fixture_id):
                self.assertIn(fixture["migration"]["status"], {"migrated", "current"})
                self.assertIn(fixture["migration"]["from_version"], {0, 2, 3})
                self.assertIsNone(fixture["migration"]["error_name"])
                for stage in ("read", "resume", "append", "close", "reopen"):
                    self.assertEqual(fixture[stage]["status"], "pass", f"{fixture_id}.{stage}")
                self.assertEqual(fixture["blockers"], [])
                evidence = fixture["evidence"]
                self.assertTrue(evidence["sequence_continuity"], fixture_id)
                self.assertEqual(evidence["message_id_preservation"]["missing_from_target"], [])
                self.assertEqual(evidence["message_id_preservation"]["missing_from_reopen"], [])
                self.assertTrue(evidence["ids"]["identical"], fixture_id)
                if fixture_id == "f-normal":
                    self.assertTrue(evidence["ids"]["source_session_id"].startswith("d15-probe-"), fixture_id)
                else:
                    self.assertEqual(evidence["ids"]["source_session_id"], fixture_id.replace("f-", "fx-"))

    def test_summary_has_no_blockers_and_no_downgrade(self) -> None:
        summary = self.results["summary"]
        self.assertEqual(summary["fixture_count"], 9)
        self.assertEqual(summary["blocked_count"], 0)
        self.assertTrue(summary["all_post_migration_stages_pass"])
        self.assertEqual(summary["downgradable_count"], 0)
        self.assertEqual(summary["non_downgradable_count"], 9)
        for fixture in self.by_id.values():
            self.assertIs(fixture["downgrade"]["feasible"], False, fixture["id"])
            self.assertIn("NOT downgradable", fixture["downgrade"]["reason"])

    def test_fork_prefix_and_inherited_count_are_preserved(self) -> None:
        forked = self.by_id["f-forked"]
        inherited = forked["evidence"]["inherited_event_count"]
        self.assertEqual(inherited["source_marker"], 7)
        self.assertEqual(inherited["target"], 9)
        source_header = json.loads((SESSIONS / "f-forked" / "session.jsonl").read_text().splitlines()[0])
        self.assertTrue(source_header["isSeeded"])
        self.assertEqual(source_header["parentSession"], "fork-parent-0002")

    def test_migration_preserves_sessions_rather_than_fabricating_new_ones(self) -> None:
        for fixture in self.by_id.values():
            self.assertNotEqual(fixture["migration"]["status"], "blocked", fixture["id"])
            self.assertEqual(fixture["read"]["header_id"], fixture["evidence"]["ids"]["source_session_id"])
            self.assertEqual(fixture["reopen"]["header_id"], fixture["evidence"]["ids"]["source_session_id"])
            self.assertEqual(fixture["resume"]["session_id"], fixture["evidence"]["ids"]["source_session_id"])


class D15FailClosedTests(unittest.TestCase):
    def test_fail_closed_cases_refuse_instead_of_starting_new_sessions(self) -> None:
        document = load(FAIL_CLOSED)
        self.assertEqual(document["schema_version"], "byq-d15-2-fail-closed.v1")
        by_id = {case["id"]: case for case in document["cases"]}
        self.assertEqual(set(by_id), {
            "unknown-future-format", "unclassified-event", "malformed-header",
            "refused-surface-migration",
        })
        for case_id, case in by_id.items():
            with self.subTest(case=case_id):
                self.assertTrue(case["refused"], case_id)
                self.assertTrue(case["documented_refusal"], case_id)
                self.assertFalse(case["treated_as_new_session"], case_id)
                self.assertFalse(case["successor_generation_written"], case_id)
        for case_id in ("unknown-future-format", "unclassified-event", "refused-surface-migration"):
            self.assertEqual(by_id[case_id]["error_name"], UNSUPPORTED, case_id)
        self.assertEqual(by_id["malformed-header"]["catalog_status"], "malformed")


class D15HistoricalEvidenceTests(unittest.TestCase):
    def test_earlier_format_layer_evidence_is_preserved_unchanged(self) -> None:
        for path in (RESULTS_V1, FAIL_CLOSED_V1, RESULTS_V2, VERDICT_V2, NEGATIVE_CONTROLS_V2):
            self.assertTrue(path.is_file(), path)
        self.assertEqual(load(RESULTS_V1)["schema_version"], "byq-d15-2-session-migration-results.v1")
        self.assertEqual(load(FAIL_CLOSED_V1)["schema_version"], "byq-d15-2-fail-closed.v1")
        self.assertEqual(load(RESULTS_V2)["schema_version"], "byq-d15-2-session-migration-results.v2")
        self.assertEqual(load(VERDICT_V2)["schema_version"], "byq-d15-2-verdict.v2")
        self.assertEqual(load(NEGATIVE_CONTROLS_V2)["schema_version"], "byq-d15-2-negative-controls.v2")


class D15RequirementsManifestTests(unittest.TestCase):
    def test_requirements_come_from_the_single_acceptance_matrix(self) -> None:
        requirements = load(ACCEPTANCE_MATRIX)["requirements"]
        self.assertEqual(requirements["schema_version"], "byq-d15-2-requirements.v1")
        self.assertEqual(requirements["fixtures"], EXPECTED_FIXTURES)
        self.assertEqual(requirements["stages"], REQUIRED_STAGES)
        self.assertEqual(requirements["fail_closed_cases"], REQUIRED_FAIL_CLOSED_CASES)

    def test_required_fixtures_match_the_immutable_index(self) -> None:
        requirements = load(ACCEPTANCE_MATRIX)["requirements"]
        index_ids = [item["id"] for item in load(INDEX)["fixtures"]]
        self.assertEqual(requirements["fixtures"], index_ids)


class D15VerdictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = load(VERDICT)
        cls.verdict = cls.document["verdict"]

    def test_verdict_shape_and_overall_pass(self) -> None:
        self.assertEqual(self.document["schema_version"], "byq-d15-2-verdict.v3")
        self.assertEqual(self.verdict["schema_version"], "byq-d15-2-verdict.v3")
        self.assertEqual(self.verdict["requirements_schema_version"], "byq-d15-2-requirements.v1")
        self.assertTrue(self.verdict["all_pass"])
        self.assertEqual(self.verdict["exit_code"], 0)
        self.assertEqual(self.verdict["blocked_count"], 0)
        self.assertEqual(self.verdict["blockers"], [])
        self.assertEqual(self.verdict["fixture_count"], 9)

    def test_every_required_invariant_passes(self) -> None:
        invariants = self.verdict["invariants"]
        self.assertEqual(set(invariants), {
            "manifest_conformance", "migration_completed", "stage_states",
            "sequence_continuity", "id_continuity", "context_preservation",
            "append_reopen", "non_downgradable", "no_blockers",
        })
        for name, value in invariants.items():
            with self.subTest(invariant=name):
                self.assertTrue(value["pass"], name)
                self.assertEqual(value["failures"], [], name)

    def test_manifest_conformance_covers_the_required_sets(self) -> None:
        conformance = self.verdict["invariants"]["manifest_conformance"]
        self.assertTrue(conformance["pass"])
        self.assertEqual(conformance["failures"], [])

    def test_fail_closed_rejections_are_part_of_the_verdict(self) -> None:
        rejected = self.verdict["fail_closed"]
        self.assertTrue(rejected["pass"])
        self.assertEqual(rejected["case_count"], 4)
        self.assertEqual(rejected["failures"], [])

    def test_pre_fix_stage_only_gate_is_recorded_for_contrast(self) -> None:
        self.assertTrue(self.verdict["legacy_all_post_migration_stages_pass"])
        self.assertEqual(self.verdict["legacy_exit_code"], 0)


class D15MessageExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = load(RESULTS)
        cls.normal = next(item for item in cls.results["fixtures"] if item["id"] == "f-normal")

    def test_message_ids_cover_the_released_event_shapes(self) -> None:
        sources = self.normal["evidence"]["message_id_preservation"]["id_sources"]
        self.assertIn("user/message", sources["source"])
        self.assertIn("assistant/message:messageId", sources["source"])
        self.assertIn("tool/result:messageId", sources["source"])
        self.assertIn("agent/inbox/spliced", sources["source"])
        self.assertIn("system/message:messageId", sources["target"])

    def test_no_message_id_is_lost_across_migration_or_reopen(self) -> None:
        preservation = self.normal["evidence"]["message_id_preservation"]
        self.assertEqual(preservation["missing_from_target"], [])
        self.assertEqual(preservation["missing_from_reopen"], [])
        self.assertEqual(preservation["appended_missing_from_reopen"], [])

    def test_context_preservation_records_system_messages(self) -> None:
        context = self.normal["evidence"]["context_preservation"]
        self.assertTrue(context["source_system_prompts"])
        self.assertTrue(context["target_system_prompts"])
        self.assertEqual(context["missing_system_prompts"], [])
        self.assertEqual(context["missing_provider_models"], [])


class D15NegativeControlEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = load(NEGATIVE_CONTROLS)
        cls.controls = {control["fault"]: control for control in cls.document["controls"]}

    def test_all_negative_controls_pass(self) -> None:
        self.assertEqual(self.document["schema_version"], "byq-d15-2-negative-controls.v3")
        self.assertTrue(self.document["all_controls_pass"])
        self.assertEqual(len(self.document["controls"]), 17)
        self.assertTrue(all(control["control_pass"] for control in self.document["controls"]))

    def test_review_repro_is_fixed(self) -> None:
        repro = self.document["repro"]
        self.assertTrue(repro["repro_fixed"])
        # Pre-fix: zero fixtures + one valid rejection case passed.
        self.assertTrue(repro["pre_fix_observed"]["all_pass"])
        self.assertEqual(repro["pre_fix_observed"]["exit_code"], 0)
        # Post-fix: the same input fails on manifest conformance.
        self.assertFalse(repro["post_fix_observed"]["all_pass"])
        self.assertEqual(repro["post_fix_observed"]["exit_code"], 1)
        self.assertEqual(repro["post_fix_observed"]["failing_invariants"], ["manifest_conformance"])

    def test_default_run_passes(self) -> None:
        observed = self.controls[None]["observed"]
        self.assertEqual(observed["exit_code"], 0)
        self.assertTrue(observed["all_pass"])
        self.assertTrue(observed["legacy_all_post_migration_stages_pass"])

    def test_broken_invariants_fail_but_legacy_gate_would_pass(self) -> None:
        for fault in ("sequence", "ids", "context", "reopen", "blockers", "fail_closed"):
            with self.subTest(fault=fault):
                observed = self.controls[fault]["observed"]
                self.assertEqual(observed["exit_code"], 1, fault)
                self.assertFalse(observed["all_pass"], fault)
                # Pre-fix stage-only logic would have reported PASS / exit 0.
                self.assertTrue(observed["legacy_all_post_migration_stages_pass"], fault)
                self.assertEqual(observed["legacy_exit_code"], 0, fault)

    def test_sequence_id_context_reopen_and_blocker_map_to_their_invariant(self) -> None:
        expected = {
            "sequence": "sequence_continuity",
            "ids": "id_continuity",
            "context": "context_preservation",
            "reopen": "append_reopen",
            "blockers": "no_blockers",
        }
        for fault, invariant in expected.items():
            with self.subTest(fault=fault):
                self.assertIn(invariant, self.controls[fault]["observed"]["failing_invariants"])

    def test_completeness_faults_fail_manifest_conformance(self) -> None:
        for fault in ("empty_fixtures", "drop_fixture", "duplicate_fixture",
                      "drop_fail_closed", "extra_fail_closed", "requirements_missing"):
            with self.subTest(fault=fault):
                observed = self.controls[fault]["observed"]
                self.assertEqual(observed["exit_code"], 1, fault)
                self.assertFalse(observed["all_pass"], fault)
                self.assertIn("manifest_conformance", observed["failing_invariants"], fault)
        # Unexpected fixture and missing evidence fail their explicit checks too.
        self.assertIn("manifest_conformance", self.controls["extra_fixture"]["observed"]["failing_invariants"])
        self.assertIn("id_continuity", self.controls["missing_evidence"]["observed"]["failing_invariants"])
        self.assertIn("append_reopen", self.controls["missing_evidence"]["observed"]["failing_invariants"])

    def test_stage_failure_fails_the_stage_state_check(self) -> None:
        observed = self.controls["stage_failure"]["observed"]
        self.assertEqual(observed["exit_code"], 1)
        self.assertIn("stage_states", observed["failing_invariants"])

    def test_real_blocked_migration_fails_the_gate(self) -> None:
        observed = self.controls["blocked_migration"]["observed"]
        self.assertEqual(observed["exit_code"], 1)
        self.assertFalse(observed["all_pass"])
        self.assertEqual(observed["blocked_count"], 1)
        self.assertIn("migration_completed", observed["failing_invariants"])
        self.assertIn("no_blockers", observed["failing_invariants"])


@unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "node/npm not available")
class D15LiveHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.live_dir = tempfile.TemporaryDirectory(prefix="byq-d15-2-test-")
        cls.live_results = Path(cls.live_dir.name) / "results.json"
        cls.live_fail_closed = Path(cls.live_dir.name) / "fail-closed.json"
        cls.live_verdict = Path(cls.live_dir.name) / "verdict.json"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.live_dir.cleanup()

    @classmethod
    def _ensure_dependencies(cls) -> None:
        # A required gate must never silently skip a failed dependency install
        # and then report PASS; an install failure is a hard test failure.
        if (HARNESS / "node_modules").is_dir():
            return
        try:
            subprocess.run(
                ["npm", "ci", "--no-audit", "--no-fund"],
                cwd=HARNESS, check=True, capture_output=True, timeout=420,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise AssertionError(f"npm ci failed for the D15-2 harness: {error}") from error
        if not (HARNESS / "node_modules").is_dir():
            raise AssertionError("npm ci did not create the D15-2 harness node_modules")

    def _run_harness(self, results: Path, fail_closed: Path, verdict: Path, fault: str = "") -> subprocess.CompletedProcess:
        environment = {**os.environ, "BYQ_D15_2_FAULT": fault}
        return subprocess.run(
            ["node", "migration_harness.mjs", str(SESSIONS), str(results), str(fail_closed), str(verdict)],
            cwd=HARNESS, capture_output=True, text=True, timeout=600, env=environment,
        )

    def test_live_harness_matches_committed_evidence(self) -> None:
        self._ensure_dependencies()
        before = {item["id"]: item["sha256"] for item in load(INDEX)["fixtures"]}
        completed = self._run_harness(self.live_results, self.live_fail_closed, self.live_verdict)
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        live = load(self.live_results)
        committed = load(RESULTS)
        self.assertEqual(live["summary"], committed["summary"])
        self.assertEqual(live["verdict"]["all_pass"], True)
        self.assertEqual(live["verdict"], committed["verdict"])
        live_by_id = {item["id"]: item for item in live["fixtures"]}
        for fixture_id, fixture in {item["id"]: item for item in committed["fixtures"]}.items():
            observed = live_by_id[fixture_id]
            for stage in ("read", "resume", "append", "close", "reopen"):
                self.assertEqual(observed[stage]["status"], fixture[stage]["status"], f"{fixture_id}.{stage}")
            self.assertEqual(observed["migration"]["status"], fixture["migration"]["status"], fixture_id)
            self.assertEqual(observed["downgrade"]["feasible"], False, fixture_id)
        live_fail = load(self.live_fail_closed)
        committed_fail = load(FAIL_CLOSED)
        self.assertEqual(
            [case["documented_refusal"] for case in live_fail["cases"]],
            [case["documented_refusal"] for case in committed_fail["cases"]],
        )
        after = {item["id"]: sha256_file(SESSIONS / item["id"] / "session.jsonl") for item in load(INDEX)["fixtures"]}
        self.assertEqual(before, after, "the harness mutated an immutable fixture original")

    def test_live_injected_faults_fail_the_verdict_and_the_exit_code(self) -> None:
        self._ensure_dependencies()
        faults = (
            "sequence", "ids", "context", "reopen", "blockers", "fail_closed", "blocked_migration",
            "empty_fixtures", "drop_fixture", "duplicate_fixture", "extra_fixture",
            "drop_fail_closed", "extra_fail_closed", "missing_evidence", "stage_failure",
            "requirements_missing",
        )
        for fault in faults:
            with self.subTest(fault=fault):
                directory = Path(tempfile.mkdtemp(prefix=f"byq-d15-2-fault-{fault}-", dir=self.live_dir.name))
                completed = self._run_harness(
                    directory / "results.json", directory / "fail-closed.json",
                    directory / "verdict.json", fault,
                )
                self.assertEqual(completed.returncode, 1, completed.stderr[-2000:])
                document = load(directory / "verdict.json")
                self.assertFalse(document["verdict"]["all_pass"], fault)
                self.assertEqual(document["verdict"]["exit_code"], 1, fault)


if __name__ == "__main__":
    unittest.main()
