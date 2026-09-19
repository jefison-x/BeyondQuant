"""D15-2 Session V3 migration qualification evidence and live-harness checks.

The committed fixtures under ``docs/evidence/d15/fixtures/sessions`` are
immutable originals; the committed ``migration-results.v1.json`` and
``fail-closed.v1.json`` are produced by the Node harness in
``scripts/d15/harness`` running the real DSH 0.1.5-rc.1 session-format catalog.

The deterministic tests validate fixture hashes, evidence schema, acceptance
language and fail-closed semantics without network access. When Node and the
harness dependencies are available the live harness is re-run and its observed
results are compared with the committed evidence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "docs/evidence/d15/fixtures/sessions"
D15_2 = ROOT / "docs/evidence/d15/d15-2"
INDEX = SESSIONS / "index.v1.json"
RESULTS = D15_2 / "migration-results.v1.json"
FAIL_CLOSED = D15_2 / "fail-closed.v1.json"
HARNESS = ROOT / "scripts/d15/harness"

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
        self.assertEqual(self.results["schema_version"], "byq-d15-2-session-migration-results.v1")
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


@unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "node/npm not available")
class D15LiveHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.live_dir = tempfile.TemporaryDirectory(prefix="byq-d15-2-test-")
        cls.live_results = Path(cls.live_dir.name) / "results.json"
        cls.live_fail_closed = Path(cls.live_dir.name) / "fail-closed.json"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.live_dir.cleanup()

    @classmethod
    def _ensure_dependencies(cls) -> None:
        if (HARNESS / "node_modules").is_dir():
            return
        try:
            subprocess.run(
                ["npm", "ci", "--no-audit", "--no-fund"],
                cwd=HARNESS, check=True, capture_output=True, timeout=420,
            )
        except (subprocess.SubprocessError, OSError) as error:  # pragma: no cover - offline CI
            raise unittest.SkipTest(f"npm ci unavailable for the D15-2 harness: {error}") from error

    def test_live_harness_matches_committed_evidence(self) -> None:
        self._ensure_dependencies()
        before = {item["id"]: item["sha256"] for item in load(INDEX)["fixtures"]}
        completed = subprocess.run(
            ["node", "migration_harness.mjs", str(SESSIONS), str(self.live_results), str(self.live_fail_closed)],
            cwd=HARNESS, capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        live = load(self.live_results)
        committed = load(RESULTS)
        self.assertEqual(live["summary"], committed["summary"])
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


if __name__ == "__main__":
    unittest.main()
