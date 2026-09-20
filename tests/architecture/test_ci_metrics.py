"""Parser contracts for the low-noise CI timing/duration metrics."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SAMPLE = """\
    plan -> docs=no architecture=yes backend=yes gateway=yes runtime=yes mcp=yes frontend=yes integration=yes unknown=no
#12 [stage 1/3] CACHED
    image identity -> service=backend tag=byq-ci-stack-1-backend id=sha256:deadbeef
==> backend: pytest against clean postgres
============================= slowest 20 durations =============================
65.32s setup    tests/test_a.py::test_x
12.10s call     tests/test_b.py::test_y
1.20s teardown  tests/test_c.py::test_z
793 passed, 3 skipped, 1 warning, 7 subtests passed in 1227.02s
[byq-timing] phase="fresh session setup" seconds=7
[byq-timing] phase="api_key=placeholder-not-a-secret" seconds=1
[byq-timing] phase="backend: pytest against clean postgres" seconds=1230
[byq-timing] total seconds=1300 exit=0
"""


def module(name: str):
    spec = importlib.util.spec_from_file_location("byq_ci_metrics", ROOT / "scripts/ci" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class CiMetricsTests(unittest.TestCase):
    def setUp(self):
        self.metrics = module("ci-metrics")
        self.redact = self.metrics._redactor()

    def test_parses_selection_phases_tests_and_durations(self):
        parsed = self.metrics.parse(SAMPLE, self.redact)
        self.assertIn("integration=yes", parsed["selection"])
        phases = {entry["phase"]: entry["seconds"] for entry in parsed["phase_seconds"]}
        self.assertEqual(phases["backend: pytest against clean postgres"], 1230)
        self.assertEqual(parsed["total"], {"seconds": 1300, "exit_code": 0})
        self.assertEqual(parsed["pytest"][0]["passed"], 793)
        self.assertEqual(parsed["pytest"][0]["skipped"], 3)
        self.assertEqual(parsed["pytest"][0]["collected"], 796)
        self.assertEqual(parsed["pytest"][0]["duration_seconds"], 1227.02)
        self.assertEqual(parsed["slowest"]["setup"][0]["item"], "tests/test_a.py::test_x")
        self.assertEqual(parsed["slowest"]["call"][0]["seconds"], 12.10)
        self.assertEqual(parsed["images"][0]["service"], "backend")
        self.assertGreaterEqual(parsed["cache_cached_lines"], 1)

    def test_reuses_the_shared_redactor(self):
        parsed = self.metrics.parse(SAMPLE, self.redact)
        rendered = json.dumps(parsed)
        self.assertNotIn("placeholder-not-a-secret", rendered)
        self.assertIn("api_key=[REDACTED]", rendered)

    def test_cli_emits_metadata_and_top_bucket(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "checks.log"
            log.write_text(SAMPLE, encoding="utf-8")
            summary = self.metrics.collect(log, None, top=1)
            self.assertEqual(len(summary["slowest"]["setup"]), 1)
        self.metrics  # module import stays side-effect free


if __name__ == "__main__":
    unittest.main()
