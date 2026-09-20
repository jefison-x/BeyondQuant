"""D15 capture-layer negatives and helper contracts.

These exercise the real capture helper functions (not observer JSON fixtures):
missing durable receipts, replay errors, approval expiry/bypass, trace gaps and
old-only assistant results must never be turned into a success default. Runs
under ``unittest`` (the architecture lane has no pytest).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPNEG = ROOT / "scripts/d15/runtime_continuity/capture_negatives.py"
RUNNER = ROOT / "scripts/d15/runtime_continuity/run_qualification.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class D15RuntimeCaptureTests(unittest.TestCase):
    def test_capture_negatives_all_fail_and_pre_fix_masked(self):
        module = _load("d15_capneg", CAPNEG)
        result = module.run()
        self.assertTrue(result["baseline_all_pass"])
        self.assertGreaterEqual(result["case_count"], 10)
        self.assertTrue(result["all_cases_pass"])
        self.assertTrue(result["all_pass"])
        for case in result["cases"]:
            self.assertTrue(case["pre_fix_legacy_all_pass"], case)
            self.assertFalse(case["post_fix_all_pass"], case)
            self.assertTrue(case["post_fix_first_failure"], case)

    def test_capture_helpers_never_default_to_success(self):
        runner = _load("d15_rq_helpers", RUNNER)
        receipt, error = runner.derive_goal_receipt({}, "message-x")
        self.assertIsNone(receipt)
        self.assertTrue(error)

        run_id, error = runner.derive_replay_run({"_error": "adapter 500"})
        self.assertIsNone(run_id)
        self.assertTrue(error)
        run_id, error = runner.derive_replay_run({})
        self.assertIsNone(run_id)
        self.assertTrue(error)
        run_id, error = runner.derive_replay_run({"run_id": "a" * 32})
        self.assertEqual(run_id, "a" * 32)
        self.assertIsNone(error)

    def test_trace_gap_is_not_contiguous(self):
        runner = _load("d15_rq_trace", RUNNER)
        events = [
            {"sequence": 1, "kind": "session.started", "payload": {"run_id": "1" * 32}},
            {"sequence": 3, "kind": "session.result", "payload": {"run_id": "1" * 32}},
        ]
        trace = runner.derive_trace_evidence(events, [], "1" * 32)
        self.assertFalse(trace["trace_contiguous"])
        self.assertTrue(trace["errors"])

    def test_only_old_assistant_is_not_target_attribution(self):
        runner = _load("d15_rq_attr", RUNNER)
        events = [
            {"sequence": 1, "kind": "session.started", "payload": {"run_id": "1" * 32}},
            {"sequence": 2, "kind": "session.result", "payload": {"run_id": "1" * 32}},
            {"sequence": 3, "kind": "session.started", "payload": {"run_id": "2" * 32}},
        ]
        messages = [{"role": "assistant", "workflow_sequence": 2}]  # belongs to run 1
        trace = runner.derive_trace_evidence(events, messages, "2" * 32)
        self.assertFalse(trace["completed"])
        self.assertIsNone(trace["attributed_message_sequence"])
        self.assertTrue(trace["errors"])

    def test_make_receipt_requires_measured_count_and_origin(self):
        runner = _load("d15_rq_receipt", RUNNER)
        with self.assertRaises(Exception):
            runner.make_receipt("tool", "key", {}, None, runner.ORIGIN_MANUAL)
        with self.assertRaises(Exception):
            runner.make_receipt("tool", "key", {}, 1, None)
        receipt = runner.make_receipt("tool", "key", {"state": "accepted"}, 1, runner.ORIGIN_MANUAL)
        self.assertEqual(receipt["side_effect_count"], 1)
        self.assertEqual(receipt["origin"], runner.ORIGIN_MANUAL)


if __name__ == "__main__":
    unittest.main()
