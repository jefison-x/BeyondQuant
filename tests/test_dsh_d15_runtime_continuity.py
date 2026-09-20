"""D15 runtime-continuity acceptance observer tests (fail-able verdict, v3).

Covers the review fixes: format-valid vs qualification-pass separation, required
NOT_RUN/BLOCKED gating, contract-authoritative continuity rules, honest pre-fix
(legacy algorithm) comparison, recovery relationship/linkage checks, and the
capture-layer evidence requirements. Runs under ``unittest`` (the architecture
lane has no pytest).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBSERVER = ROOT / "scripts/d15/runtime_continuity/observer.py"
CONTRACT = ROOT / "scripts/d15/runtime_continuity/contract.v5.json"


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_runtime_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_runtime_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


class D15RuntimeContinuityObserverTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-d15-runtime-contract.v5")
        ids = [item["id"] for item in contract["required_scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        for expected in ("adapter-process-restart", "dsh-process-interruption",
                         "gateway-disconnect-reconnect", "generation-replacement", "executor-takeover"):
            self.assertIn(expected, ids)
        self.assertTrue(contract["required_coverage_gates_qualification"])
        optional_ids = [item["id"] for item in contract["optional_scenarios"]]
        self.assertTrue(optional_ids)
        self.assertTrue(set(optional_ids).isdisjoint(ids))
        self.assertEqual(contract["candidate"]["release"], "dsh-0.1.5rc1")

    def test_unit_fixture_passes_and_every_negative_control_fails(self):
        observer = _load_observer()
        contract = _contract()
        verdict = observer.compute_verdict(contract, observer.valid_fixture(contract), allow_unit_fixture=True)
        self.assertTrue(verdict["all_pass"])
        self.assertTrue(verdict["format_valid"])

        controls = observer.run_selfcheck(contract)
        self.assertTrue(controls["baseline_all_pass"])
        self.assertTrue(controls["all_controls_pass"])
        self.assertTrue(controls["defect_targeting_pre_fix_passed"])
        self.assertGreaterEqual(controls["control_count"], 42)
        for control in controls["controls"]:
            self.assertFalse(control["observed_all_pass"], control)
            self.assertEqual(control["observed_exit_code"], 1, control)
            self.assertTrue(control["first_failure"], control)

    def test_required_not_run_or_blocked_gates_qualification(self):
        observer = _load_observer()
        contract = _contract()
        for status in ("NOT_RUN", "BLOCKED"):
            fixture = observer.valid_fixture(contract)
            target = next(s for s in fixture["scenarios"] if s["id"] == "generation-replacement")
            target.clear()
            target.update({"id": "generation-replacement", "result": status,
                           "not_run_reason": f"not executed because {status}"})
            verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
            self.assertFalse(verdict["all_pass"])
            self.assertEqual(verdict["exit_code"], 1)
            self.assertEqual(verdict["required_coverage"]["generation-replacement"], status)
            self.assertTrue(any("generation-replacement" in item for item in verdict["coverage_failures"]))
            self.assertTrue(verdict["format_valid"])

    def test_optional_not_run_does_not_gate_required_coverage(self):
        observer = _load_observer()
        contract = _contract()
        verdict = observer.compute_verdict(contract, observer.valid_fixture(contract), allow_unit_fixture=True)
        self.assertTrue(verdict["all_pass"])
        self.assertEqual(verdict["optional_coverage"]["host-reboot"], "NOT_RUN")
        self.assertTrue(verdict["required_coverage_ok"])

    def test_observation_cannot_relax_contract_continuity_rules(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        scenario = fixture["scenarios"][0]
        scenario["allowed_continuity"] = ["fresh"]
        scenario["forbidden_continuity"] = []
        scenario["after"]["continuity"] = "fresh"
        verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("may not declare 'allowed_continuity'" in item for item in verdict["failures"]))
        self.assertTrue(any("fabricated continuity 'fresh'" in item for item in verdict["failures"]))

    def test_recovery_relationships_and_linkage_are_enforced(self):
        observer = _load_observer()
        contract = _contract()
        base = observer.valid_fixture(contract)

        same_pid = copy.deepcopy(base)
        same_pid["scenarios"][0]["after"]["adapter_pid"] = same_pid["scenarios"][0]["before"]["adapter_pid"]
        self.assertFalse(observer.compute_verdict(contract, same_pid, allow_unit_fixture=True)["all_pass"])

        same_generation = copy.deepcopy(base)
        repl = next(s for s in same_generation["scenarios"] if s["id"] == "generation-replacement")
        repl["after"]["generation_index"] = repl["before"]["generation_index"]
        repl["after"]["adapter_generation"] = repl["before"]["adapter_generation"]
        self.assertFalse(observer.compute_verdict(contract, same_generation, allow_unit_fixture=True)["all_pass"])

        same_epoch = copy.deepcopy(base)
        takeover = next(s for s in same_epoch["scenarios"] if s["id"] == "executor-takeover")
        takeover["after"]["executor_epoch"] = takeover["before"]["executor_epoch"]
        self.assertFalse(observer.compute_verdict(contract, same_epoch, allow_unit_fixture=True)["all_pass"])

        broken_link = copy.deepcopy(base)
        broken_link["scenarios"][0]["after"]["goal"]["prompt_receipt"]["root_run_id"] = "9" * 32
        self.assertFalse(observer.compute_verdict(contract, broken_link, allow_unit_fixture=True)["all_pass"])

    def test_synthetic_fixture_is_not_runtime_evidence(self):
        observer = _load_observer()
        contract = _contract()
        verdict = observer.compute_verdict(contract, observer.valid_fixture(contract))
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("not runtime evidence" in item for item in verdict["failures"]))

    def test_missing_evidence_is_never_an_empty_default_pass(self):
        observer = _load_observer()
        contract = _contract()
        default = {
            "schema_version": "byq-d15-runtime-observations.v5",
            "evidence_class": contract["required_evidence_class"],
            "candidate": dict(contract["candidate"]),
            "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False},
            "scenarios": [],
        }
        verdict = observer.compute_verdict(contract, default)
        self.assertFalse(verdict["all_pass"])
        self.assertEqual(verdict["exit_code"], 1)
        self.assertTrue(any("missing required scenario" in item for item in verdict["failures"]))

    def test_not_run_requires_a_reason(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0] = {"id": "adapter-process-restart", "result": "NOT_RUN"}
        verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("without a reason" in item for item in verdict["failures"]))

    def test_action_receipt_requires_origin_and_measured_count(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["action_receipts"][0]["side_effect_count"] = None
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["action_receipts"][0].pop("origin")
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

    def test_approval_trials_are_required_and_side_effects_fail(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["approval"].pop("trials")
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["approval"]["trials"][0]["side_effect_created"] = True
        verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("bypass" in item for item in verdict["failures"]))

    def test_result_must_be_attributed_to_the_target_run(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["result"]["target_run_id"] = "9" * 32
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["result"]["status"] = "incomplete"
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

    def test_capture_errors_gate_pass(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["capture_ok"] = False
        fixture["scenarios"][0]["after"]["capture_errors"] = ["journal read failed"]
        verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("capture evidence missing" in item for item in verdict["failures"]))

    def test_agent_mcp_at_most_once_is_required(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"].remove(
            next(s for s in fixture["scenarios"] if s["id"] == "agent-mcp-domain-at-most-once"))
        verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("agent-mcp-domain-at-most-once" in item
                            for item in verdict["coverage_failures"]))

    def test_approval_protected_trial_requirements(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["approval"]["trials"][1].update({"http_status": 500})
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["approval"]["trials"][2].update({"after_count": 1})
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

        # A pre-fault proof must not be reported as a post-fault attempt.
        fixture = observer.valid_fixture(contract)
        fixture["scenarios"][0]["after"]["approval"]["trials"][1].update({"phase": "pre-fault"})
        verdict = observer.compute_verdict(contract, fixture, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("post-fault" in item for item in verdict["failures"]))

    def test_agent_mcp_two_run_replay_is_enforced(self):
        observer = _load_observer()
        contract = _contract()

        def agent_after(fixture):
            return next(s for s in fixture["scenarios"]
                        if s["id"] == "agent-mcp-domain-at-most-once")["after"]

        fixture = observer.valid_fixture(contract)
        agent_after(fixture)["agent_mcp_runs"].pop("second", None)
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

        fixture = observer.valid_fixture(contract)
        agent_after(fixture)["agent_mcp_runs"]["second"].update({"mcp_status": "error"})
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

        fixture = observer.valid_fixture(contract)
        first = agent_after(fixture)["agent_mcp_runs"]["first"]
        agent_after(fixture)["agent_mcp_runs"]["second"].update(
            {"run_id": first["run_id"], "tool_call_id": first["tool_call_id"]})
        self.assertFalse(observer.compute_verdict(contract, fixture, allow_unit_fixture=True)["all_pass"])

    def test_observer_cli_fails_on_malformed_observations(self):
        observer = _load_observer()
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(observer.main(["--observations", str(bad)]), 2)

    def test_observer_cli_exit_code_tracks_verdict(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer.valid_fixture(contract)
        fixture["evidence_class"] = contract["required_evidence_class"]
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "good.json"
            good.write_text(json.dumps(fixture), encoding="utf-8")
            self.assertEqual(
                observer.main(["--observations", str(good), "--out", str(Path(directory) / "v.json")]), 0)


if __name__ == "__main__":
    unittest.main()
