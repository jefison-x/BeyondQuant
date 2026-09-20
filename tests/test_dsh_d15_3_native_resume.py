"""D15-3 native session resume qualification: contract, evidence and harness.

The committed ``docs/evidence/d15/d15-3/`` artifacts are produced by the real
DSH 0.1.5-rc.1 session-persistence seam:

- ``native-resume-observations.v1.json`` — raw per-row observations from
  ``scripts/d15/harness/native_resume_harness.mjs`` (one OS process per runtime
  generation, real ``SessionPersistence.create/open``, ``SessionHandle``,
  cross-process ``flock`` write lease and ``readColdSessionLog``).
- ``native-resume-results.v1.json`` — the framework-neutral classification from
  ``scripts/d15/native_resume_qualification.py``.

The deterministic tests validate the public continuity contract, the internal
evidence-only diagnostics, the classifier and the committed evidence. When Node
and the harness dependencies are available the live harness is re-run and its
observed rows are compared with the committed evidence.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from packages.contracts import runtime_continuity as continuity
from scripts.d15 import native_resume_qualification as qualification

ROOT = Path(__file__).resolve().parents[1]
D15_3 = ROOT / "docs/evidence/d15/d15-3"
OBSERVATIONS = D15_3 / "native-resume-observations.v1.json"
RESULTS = D15_3 / "native-resume-results.v1.json"
MANIFEST = ROOT / "docs/evidence/d15/fixtures/manifest.v1.json"
HARNESS = ROOT / "scripts/d15/harness"

EXPECTED_ROWS = [
    "browser-disconnect",
    "frontend-restart",
    "gateway-restart",
    "adapter-restart",
    "dsh-crash",
    "runtime-generation-replacement",
    "host-reboot",
    "executor-takeover",
]
EXPECTED_CONTINUITY = {
    "browser-disconnect": continuity.REATTACHED,
    "frontend-restart": continuity.REATTACHED,
    "gateway-restart": continuity.REATTACHED,
    "adapter-restart": continuity.REHYDRATED,
    "dsh-crash": continuity.INTERRUPTED,
    "runtime-generation-replacement": continuity.REHYDRATED,
    "host-reboot": continuity.REHYDRATED,
    "executor-takeover": continuity.REHYDRATED,
}
EXPECTED_NATIVE = {
    "browser-disconnect": False,
    "frontend-restart": False,
    "gateway-restart": False,
    "adapter-restart": True,
    "dsh-crash": True,
    "runtime-generation-replacement": True,
    "host-reboot": True,
    "executor-takeover": True,
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class D15PublicContractTests(unittest.TestCase):
    def test_public_continuity_vocabulary_is_unchanged(self) -> None:
        self.assertEqual(continuity.CONTINUITY_VERSION, "runtime-continuity.v1")
        self.assertEqual(
            continuity.STATUSES,
            {continuity.FRESH, continuity.REATTACHED, continuity.REHYDRATED, continuity.INTERRUPTED},
        )
        self.assertTrue(all(continuity.valid_continuity(value) for value in continuity.STATUSES))
        self.assertFalse(continuity.valid_continuity("native"))
        self.assertEqual(continuity.normalize_continuity(None), continuity.FRESH)
        with self.assertRaises(ValueError):
            continuity.normalize_continuity("native-resumed")

    def test_internal_diagnostics_are_evidence_only_and_match_the_manifest(self) -> None:
        manifest = load(MANIFEST)
        declared = set(manifest["continuity_diagnostics_internal"]["internal_only_fields"])
        self.assertEqual(declared, set(continuity.DIAGNOSTIC_FIELDS))
        self.assertNotIn("native_resume_used", continuity.STATUSES)
        self.assertNotIn("byq_fallback_used", continuity.STATUSES)
        self.assertEqual(
            set(manifest["continuity_diagnostics_internal"]["public_contract"]),
            set(continuity.STATUSES),
        )


class D15ClassificationTests(unittest.TestCase):
    def test_live_generation_reattaches_and_never_claims_native_resume(self) -> None:
        decision = continuity.classify_generation_transition(
            generation_survived=True, lost_run=False, native_session_persisted=True,
            native_resume_available=True, byq_fallback_available=True,
        )
        self.assertEqual(decision.continuity, continuity.REATTACHED)
        self.assertFalse(decision.diagnostics["native_resume_used"])
        self.assertFalse(decision.diagnostics["byq_fallback_used"])
        self.assertFalse(decision.byq_fallback_required)
        self.assertEqual(decision.diagnostics["previous_generation_state"], continuity.GENERATION_ALIVE)

    def test_native_resume_rehydrate_is_distinct_from_byq_fallback(self) -> None:
        native = continuity.classify_generation_transition(
            generation_survived=False, lost_run=False, native_session_persisted=True,
            native_resume_available=True, byq_fallback_available=True,
        )
        fallback = continuity.classify_generation_transition(
            generation_survived=False, lost_run=False, native_session_persisted=False,
            native_resume_available=False, byq_fallback_available=True,
        )
        # Same public status, different evidence-only mechanism.
        self.assertEqual(native.continuity, continuity.REHYDRATED)
        self.assertEqual(fallback.continuity, continuity.REHYDRATED)
        self.assertTrue(native.diagnostics["native_resume_used"])
        self.assertFalse(native.diagnostics["byq_fallback_used"])
        self.assertFalse(fallback.diagnostics["native_resume_used"])
        self.assertTrue(fallback.diagnostics["byq_fallback_used"])
        self.assertTrue(fallback.byq_fallback_required)
        self.assertFalse(native.byq_fallback_required)

    def test_lost_run_is_interrupted_but_still_reports_the_resume_mechanism(self) -> None:
        decision = continuity.classify_generation_transition(
            generation_survived=False, lost_run=True, native_session_persisted=True,
            native_resume_available=True, byq_fallback_available=True,
        )
        self.assertEqual(decision.continuity, continuity.INTERRUPTED)
        self.assertTrue(decision.diagnostics["native_resume_used"])
        self.assertEqual(decision.diagnostics["previous_generation_state"], continuity.GENERATION_INTERRUPTED)

    def test_no_recovery_path_is_interrupted_not_fabricated(self) -> None:
        decision = continuity.classify_generation_transition(
            generation_survived=False, lost_run=False, native_session_persisted=False,
            native_resume_available=False, byq_fallback_available=False,
        )
        self.assertEqual(decision.continuity, continuity.INTERRUPTED)
        self.assertFalse(decision.diagnostics["native_resume_used"])
        self.assertFalse(decision.diagnostics["byq_fallback_used"])

    def test_classifier_fails_closed_on_invalid_input(self) -> None:
        base = dict(
            generation_survived=False, lost_run=False, native_session_persisted=True,
            native_resume_available=True, byq_fallback_available=True,
        )
        with self.assertRaises(ValueError):
            continuity.classify_generation_transition(**{**base, "generation_survived": "yes"})
        with self.assertRaises(ValueError):
            continuity.classify_generation_transition(**{**base, "lost_run": 1})
        with self.assertRaises(ValueError):
            continuity.classify_generation_transition(
                **base, previous_generation_state="melting")

    def test_every_decision_uses_only_the_closed_public_status_and_internal_fields(self) -> None:
        for survived in (True, False):
            for lost in (True, False):
                for native in (True, False):
                    for fallback in (True, False):
                        decision = continuity.classify_generation_transition(
                            generation_survived=survived, lost_run=lost,
                            native_session_persisted=native, native_resume_available=native,
                            byq_fallback_available=fallback,
                        )
                        self.assertIn(decision.continuity, continuity.STATUSES)
                        self.assertLessEqual(set(decision.diagnostics), continuity.DIAGNOSTIC_FIELDS)
                        self.assertIsInstance(decision.diagnostics["native_session_present"], bool)

    def test_decision_never_carries_a_session_identity(self) -> None:
        decision = continuity.classify_generation_transition(
            generation_survived=False, lost_run=False, native_session_persisted=True,
            native_resume_available=True, byq_fallback_available=True,
        )
        self.assertNotIn("session_id", decision.diagnostics)
        self.assertNotIn("dsh_session_id", decision.diagnostics)


class D15EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observations = load(OBSERVATIONS)
        cls.results = load(RESULTS)
        cls.rows = {row["id"]: row for row in cls.results["rows"]}

    def test_evidence_targets_the_coherent_rc1_pairing(self) -> None:
        self.assertEqual(self.results["schema_version"], "byq-d15-3-native-resume-results.v1")
        target = self.results["target"]
        self.assertEqual(target["release_id"], "dsh-0.1.5rc1")
        self.assertEqual(target["python_sdk"], "0.1.5rc1")
        self.assertEqual(target["bundled_npm_version"], "0.1.5-rc.1")
        self.assertEqual(target["source_tag"], "dsh-v0.1.5-rc.1")
        self.assertEqual(
            self.observations["harness"]["package_versions"]["@deepseek-ai/dsh-session-persistence-jsonl"],
            "0.1.5-rc.1",
        )

    def test_all_eight_failure_rows_are_covered_and_classified(self) -> None:
        failure_rows = [row for row in self.results["rows"] if row["kind"] == "failure_row"]
        self.assertEqual([row["id"] for row in failure_rows], EXPECTED_ROWS)
        for row_id in EXPECTED_ROWS:
            row = self.rows[row_id]
            self.assertEqual(row["classification"]["continuity"], EXPECTED_CONTINUITY[row_id], row_id)
            self.assertEqual(row["classification"]["native_resume_used"], EXPECTED_NATIVE[row_id], row_id)
            self.assertIn(row["classification"]["continuity"], continuity.STATUSES)
            self.assertTrue(row["simulated"] and row["real"], row_id)

    def test_native_resume_observed_for_every_persisted_row(self) -> None:
        for row_id in EXPECTED_ROWS:
            row = self.rows[row_id]
            self.assertTrue(row["dsh_session_persisted"], row_id)
            self.assertTrue(row["native_resume_available"], row_id)
            self.assertTrue(row["native_resume_same_session_id"], row_id)
            self.assertTrue(row["native_resume_sequence_contiguous"], row_id)
            self.assertEqual(row["classification"]["native_session_present"], True, row_id)
        self.assertEqual(self.results["summary"]["native_resume_available_count"], 8)
        self.assertEqual(self.results["summary"]["native_resume_same_session_id_count"], 8)
        self.assertEqual(self.results["summary"]["native_resume_sequence_contiguous_count"], 8)

    def test_crash_and_takeover_rows_show_lease_release_and_fencing(self) -> None:
        crash = self.rows["dsh-crash"]
        self.assertTrue(crash["lost_run"])
        self.assertTrue(crash["open_turn_preserved"])
        self.assertEqual(crash["cold_read_interrupted_closers"], 2)
        self.assertTrue(crash["lease_released_on_process_death"])
        takeover = self.rows["executor-takeover"]
        self.assertTrue(takeover["lease_contention_observed"])
        self.assertTrue(takeover["lease_released_on_process_death"])

    def test_native_unavailable_control_requires_byq_fallback(self) -> None:
        control = self.rows["native-unavailable-control"]
        self.assertEqual(control["kind"], "control")
        self.assertFalse(control["dsh_session_persisted"])
        self.assertFalse(control["native_resume_available"])
        self.assertTrue(control["classification"]["byq_fallback_used"])
        self.assertTrue(control["classification"]["byq_fallback_required"])
        self.assertEqual(control["classification"]["continuity"], continuity.REHYDRATED)
        self.assertTrue(self.results["summary"]["native_unavailable_control_uses_byq_fallback"])

    def test_summary_states_the_r3_and_public_contract_position(self) -> None:
        summary = self.results["summary"]
        self.assertEqual(summary["failure_row_count"], 8)
        self.assertTrue(summary["native_resume_viable"])
        self.assertFalse(summary["r3_should_reimplement_native_session_resume"])
        self.assertEqual(summary["r3_resume"], "NO")
        self.assertTrue(summary["public_contract_unchanged"])
        self.assertEqual(summary["classification_counts"][continuity.REATTACHED], 3)
        self.assertEqual(summary["classification_counts"][continuity.REHYDRATED], 4)
        self.assertEqual(summary["classification_counts"][continuity.INTERRUPTED], 1)
        self.assertEqual(summary["classification_counts"][continuity.FRESH], 0)
        self.assertEqual(summary["byq_fallback_count"], 0)

    def test_results_are_exactly_rederived_from_observations(self) -> None:
        rederived = qualification.build_results(self.observations)
        self.assertEqual(rederived["rows"], self.results["rows"])
        self.assertEqual(rederived["summary"], self.results["summary"])

    def test_committed_observations_carry_no_scratch_paths(self) -> None:
        text = OBSERVATIONS.read_text(encoding="utf-8")
        self.assertNotIn("/tmp/", text)
        self.assertNotIn("mkdtemp", text)
        for label in ("browser", "frontend", "gateway", "adapter", "crash", "reboot", "takeover"):
            self.assertNotIn(f"byq-d15-3-{label}-", text)


@unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "node/npm not available")
class D15LiveHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.live_dir = tempfile.TemporaryDirectory(prefix="byq-d15-3-test-")
        cls.live_observations = Path(cls.live_dir.name) / "observations.json"
        cls.live_results = Path(cls.live_dir.name) / "results.json"

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
            raise AssertionError(f"npm ci failed for the D15-3 harness: {error}") from error
        if not (HARNESS / "node_modules").is_dir():
            raise AssertionError("npm ci did not create the D15-3 harness node_modules")

    def test_live_harness_matches_committed_evidence(self) -> None:
        self._ensure_dependencies()
        completed = subprocess.run(
            ["node", "native_resume_harness.mjs", str(self.live_observations)],
            cwd=HARNESS, capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        subprocess.run(
            ["python3", str(ROOT / "scripts/d15/native_resume_qualification.py"),
             str(self.live_observations), str(self.live_results)],
            cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
        )
        live_observations = load(self.live_observations)
        live_results = load(self.live_results)
        committed_observations = load(OBSERVATIONS)
        committed_results = load(RESULTS)

        def project(row: dict) -> dict:
            return {
                key: row[key] for key in (
                    "id", "generation", "lost_run", "dsh_session_persisted",
                    "native_resume_available", "native_resume_same_session_id",
                    "native_resume_events_preserved", "native_resume_sequence_contiguous",
                    "native_resume_event_count", "lease_contention_observed",
                    "lease_released_on_process_death", "open_turn_preserved",
                    "cold_read_interrupted_closers", "classification_input",
                )
            }

        self.assertEqual(
            [project(row) for row in live_observations["failure_rows"]],
            [project(row) for row in committed_observations["failure_rows"]],
        )
        self.assertEqual(
            [project(row) for row in live_observations["controls"]],
            [project(row) for row in committed_observations["controls"]],
        )
        self.assertEqual(live_results["summary"], committed_results["summary"])
        self.assertEqual(live_results["rows"], committed_results["rows"])


if __name__ == "__main__":
    unittest.main()
