import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dsh/release.py"
SPEC = importlib.util.spec_from_file_location("dsh_release_qualification", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_evidence(scope: str = "preproduction") -> dict[str, object]:
    pass_through = 37 if scope == "preproduction" else 30 if scope == "keyless" else 40
    checks = []
    for number in range(1, 41):
        passed = number <= pass_through
        checks.append({
            "id": f"T{number:02d}",
            "layer": "L1" if number <= 30 else "L3" if number <= 37 else "L2",
            "result": "PASS" if passed else "NOT_RUN",
            "test_name": f"qualification.test_t{number:02d}",
            "evidence_reference": "docs/evidence/dsh-012rc1/u5/VALIDATION.md",
            "failure_category": None if passed else "later_stage",
        })
    return {
        "schema_version": "dsh-qualification-evidence.v1",
        "release_id": "dsh-0.1.2rc1",
        "baseline_release_id": "dsh-0.1.1rc1",
        "git_commit": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "artifact_hashes": {
            "candidate_descriptor": MODULE.digest(MODULE.RELEASE_ROOT / "dsh-0.1.2rc1.json"),
            "baseline_descriptor": MODULE.digest(MODULE.RELEASE_ROOT / "dsh-0.1.1rc1.json"),
            "candidate_identity": MODULE.digest(MODULE.candidate_output_path("dsh-0.1.2rc1")),
        },
        "composition_hash": MODULE.load_json(
            MODULE.RELEASE_ROOT / "dsh-0.1.2rc1.json"
        )["profile"]["composition_hash"],
        "policy_hash": MODULE.digest(
            MODULE.CONFIG_ROOT / "generated/dsh-0.1.2rc1.web-evidence-provenance.json"
        ),
        "started_at": "2026-09-06T00:00:00Z",
        "finished_at": "2026-09-06T00:10:00Z",
        "platform": {"os": "linux", "arch": "x86_64"},
        "provider_model_metadata_without_secrets": [
            {"provider": "deepseek-official", "model": "deepseek-v4-flash", "protocol": "openai-completions", "runs": 12}
        ],
        "checks": checks,
        "metrics": {
            "raw_sample_counts": {"baseline_l1": 10, "candidate_l1": 10, "lifecycle_cycles": 20},
            "timing_summary": {"baseline_median_seconds": 1.0, "candidate_median_seconds": 1.5},
            "peak_rss_mib": {"baseline": 100.0, "candidate": 140.0},
            "cleanup_counts": {"containers": 0, "networks": 0, "volumes": 0, "owned_processes": 0},
        },
        "capability_diff": [],
        "dependency_diff": ["deepseek-harness-sdk: 0.1.1rc1 -> 0.1.2rc1"],
        "limitations": ["T38-T40 remain later-stage gates"],
        "threshold_exceptions": [],
        "qualification_scope": scope,
    }


class DshQualificationReportTests(unittest.TestCase):
    def test_actual_u5_evidence_cannot_qualify_after_external_isolation_failure(self) -> None:
        evidence = MODULE.load_json(
            ROOT / "docs/evidence/dsh-012rc1/u5/qualification-evidence.json"
        )
        self.assertEqual(evidence["checks"][34]["failure_category"],
                         "feedback_external_isolation_failed")
        self.assertEqual(evidence["checks"][34]["result"], "FAIL")
        self.assertEqual(evidence["checks"][35]["failure_category"],
                         "candidate_chrome_mcp_review_missing")
        with self.assertRaisesRegex(MODULE.ReleaseError, "requires T01-T37 PASS"):
            MODULE.render_qualification_report("dsh-0.1.2rc1", "dsh-0.1.1rc1", evidence)
        self.assertFalse((ROOT / "docs/evidence/dsh-012rc1/u5/report-preproduction/qualification-report.json").exists())

    def test_preproduction_report_requires_exact_complete_matrix(self) -> None:
        evidence = valid_evidence()
        report = MODULE.render_qualification_report(
            "dsh-0.1.2rc1", "dsh-0.1.1rc1", evidence
        )
        value = json.loads(report)
        self.assertEqual(value["qualification_scope"], "preproduction")
        self.assertEqual(len(value["checks"]), 40)
        self.assertEqual(value["checks"][36]["result"], "PASS")
        self.assertEqual(value["checks"][37]["result"], "NOT_RUN")

    def test_missing_failed_or_falsely_completed_gate_fails_closed(self) -> None:
        for mutation, message in (
            (lambda value: value["checks"].pop(), "exactly T01-T40"),
            (lambda value: value["checks"][30].update(result="BLOCKED", failure_category="provider"), "requires T01-T37 PASS"),
            (lambda value: value["checks"][39].update(result="PASS", failure_category=None), "requires T38-T40 NOT_RUN"),
            (lambda value: value["metrics"]["cleanup_counts"].update(containers=1), "cleanup counts must be zero"),
        ):
            evidence = valid_evidence()
            mutation(evidence)
            with self.assertRaisesRegex(MODULE.ReleaseError, message):
                MODULE.render_qualification_report(
                    "dsh-0.1.2rc1", "dsh-0.1.1rc1", evidence
                )

    def test_identity_performance_and_secret_checks_fail_closed(self) -> None:
        cases = []
        wrong_release = valid_evidence()
        wrong_release["release_id"] = "dsh-0.1.1rc1"
        cases.append((wrong_release, "release identity mismatch"))
        slow = valid_evidence()
        slow["metrics"]["timing_summary"]["candidate_median_seconds"] = 2.3
        cases.append((slow, "performance threshold"))
        leaky = valid_evidence()
        leaky["limitations"] = ["Bearer should-not-appear"]
        cases.append((leaky, "secret-like material"))
        wrong_hash = valid_evidence()
        wrong_hash["artifact_hashes"]["candidate_descriptor"] = "sha256:" + "c" * 64
        cases.append((wrong_hash, "do not match registered release files"))
        secret_field = valid_evidence()
        secret_field["provider_model_metadata_without_secrets"][0]["api_key"] = "redacted"
        cases.append((secret_field, "invalid closed schema"))
        for evidence, message in cases:
            with self.assertRaisesRegex(MODULE.ReleaseError, message):
                MODULE.render_qualification_report(
                    "dsh-0.1.2rc1", "dsh-0.1.1rc1", evidence
                )

    def test_exact_explained_threshold_exception_is_accepted(self) -> None:
        evidence = valid_evidence()
        evidence["metrics"]["timing_summary"]["candidate_median_seconds"] = 2.3
        evidence["threshold_exceptions"] = [{
            "metric": "median_latency_seconds",
            "observed": 2.3,
            "threshold": 2.2,
            "reason": "The exact official carrier adds bounded startup work; all lifecycle cleanup checks remain zero.",
        }]
        MODULE.render_qualification_report(
            "dsh-0.1.2rc1", "dsh-0.1.1rc1", evidence
        )

    def test_qualify_output_is_new_and_does_not_change_default_release(self) -> None:
        deployment_before = MODULE.DEPLOYMENT_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "qualification"
            MODULE.write_new_output(
                output,
                "qualification-report.json",
                MODULE.render_qualification_report(
                    "dsh-0.1.2rc1", "dsh-0.1.1rc1", valid_evidence()
                ),
            )
            self.assertTrue((output / "qualification-report.json").is_file())
            with self.assertRaisesRegex(MODULE.ReleaseError, "refusing to overwrite"):
                MODULE.write_new_output(output, "qualification-report.json", "{}\n")
        self.assertEqual(MODULE.DEPLOYMENT_PATH.read_bytes(), deployment_before)


if __name__ == "__main__":
    unittest.main()
