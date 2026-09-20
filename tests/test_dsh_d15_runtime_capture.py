"""D15 capture-layer negatives and helper contracts.

These exercise the real capture helper functions (not observer JSON fixtures):
missing durable receipts, replay errors, approval expiry/bypass, trace gaps and
old-only assistant results must never be turned into a success default.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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


def test_capture_negatives_all_fail_and_pre_fix_masked():
    module = _load("d15_capneg", CAPNEG)
    result = module.run()
    assert result["baseline_all_pass"] is True
    assert result["case_count"] >= 5
    assert result["all_cases_pass"] is True
    assert result["all_pass"] is True
    for case in result["cases"]:
        assert case["pre_fix_legacy_all_pass"] is True, case
        assert case["post_fix_all_pass"] is False, case
        assert case["post_fix_first_failure"], case


def test_capture_helpers_never_default_to_success():
    runner = _load("d15_rq_helpers", RUNNER)
    receipt, error = runner.derive_goal_receipt({}, "message-x")
    assert receipt is None and error

    run_id, error = runner.derive_replay_run({"_error": "adapter 500"})
    assert run_id is None and error
    run_id, error = runner.derive_replay_run({})
    assert run_id is None and error
    run_id, error = runner.derive_replay_run({"run_id": "a" * 32})
    assert run_id == "a" * 32 and error is None


def test_trace_gap_is_not_contiguous():
    runner = _load("d15_rq_trace", RUNNER)
    events = [
        {"sequence": 1, "kind": "session.started", "payload": {"run_id": "1" * 32}},
        {"sequence": 3, "kind": "session.result", "payload": {"run_id": "1" * 32}},
    ]
    trace = runner.derive_trace_evidence(events, [], "1" * 32)
    assert trace["trace_contiguous"] is False
    assert trace["errors"]


def test_only_old_assistant_is_not_target_attribution():
    runner = _load("d15_rq_attr", RUNNER)
    events = [
        {"sequence": 1, "kind": "session.started", "payload": {"run_id": "1" * 32}},
        {"sequence": 2, "kind": "session.result", "payload": {"run_id": "1" * 32}},
        {"sequence": 3, "kind": "session.started", "payload": {"run_id": "2" * 32}},
    ]
    messages = [{"role": "assistant", "workflow_sequence": 2}]  # belongs to run 1
    trace = runner.derive_trace_evidence(events, messages, "2" * 32)
    assert trace["completed"] is False
    assert trace["attributed_message_sequence"] is None
    assert trace["errors"]


def test_make_receipt_requires_measured_count_and_origin():
    runner = _load("d15_rq_receipt", RUNNER)
    with pytest.raises(Exception):
        runner.make_receipt("tool", "key", {}, None, runner.ORIGIN_MANUAL)
    with pytest.raises(Exception):
        runner.make_receipt("tool", "key", {}, 1, None)
    receipt = runner.make_receipt("tool", "key", {"state": "accepted"}, 1, runner.ORIGIN_MANUAL)
    assert receipt["side_effect_count"] == 1
    assert receipt["origin"] == runner.ORIGIN_MANUAL


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
