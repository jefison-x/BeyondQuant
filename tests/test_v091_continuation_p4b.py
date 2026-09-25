"""ADR-0085 P4-B governance: frozen matrix, fail-able observer, gate boundaries.

These run in the architecture lane (no PostgreSQL, no Docker). They assert that
the frozen acceptance matrix matches the closed contract, that the observer is
fail-able (every defect-targeting control is rejected while a legacy
label-trusting gate accepts it), that the committed verdict is honestly derived,
that the ADR-0086 request-scoped gate is request-scoped (never a cross-process
fixed max-2) and that the slice stays scoped to the normal path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "scripts/v091/continuation_p4b"
CONTRACT_PATH = HERE / "contract.v1.json"
EVIDENCE_DIR = ROOT / "docs/evidence/adr-0085-p4b-normal-journey"
MATRIX_PATH = EVIDENCE_DIR / "acceptance-matrix.v1.json"
OBSERVATIONS_PATH = EVIDENCE_DIR / "observations.v1.json"
VERDICT_PATH = EVIDENCE_DIR / "verdict.v1.json"
P4A_VERDICT = ROOT / "docs/evidence/adr-0085-p4-real-journey/verdict.v1.json"


def _load_observer():
    spec = importlib.util.spec_from_file_location("p4b_observer", HERE / "observer.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["p4b_observer"] = module
    spec.loader.exec_module(module)
    return module


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    def test_contract_is_closed_and_versioned(self):
        contract = self.contract
        self.assertEqual(contract["schema_version"], "byq-v091-continuation-p4b-contract.v1")
        self.assertEqual(contract["slice"], "P4-B")
        self.assertEqual(contract["required_evidence_class"], "runtime-isolated-stack")
        journey = [row["id"] for row in contract["required_journey_steps"]]
        self.assertEqual(len(journey), len(set(journey)))
        self.assertIn("paper-account", journey)
        self.assertIn("task-completed", journey)
        gate = [row["id"] for row in contract["required_gate_rows"]]
        self.assertEqual(len(gate), len(set(gate)))
        self.assertIn("gate-usage-actual-vs-ceiling", gate)
        self.assertGreaterEqual(len(contract["required_assertions"]), 8)

    def test_matrix_matches_contract_and_is_frozen(self):
        contract, matrix = self.contract, self.matrix
        self.assertTrue(matrix["frozen_before_capture"])
        self.assertEqual([row["id"] for row in matrix["journey_rows"]], [
            row["id"] for row in contract["required_journey_steps"]])
        self.assertEqual([row["id"] for row in matrix["gate_rows"]], [
            row["id"] for row in contract["required_gate_rows"]])
        self.assertEqual([row for row in matrix["assertion_rows"]],
                         [{"id": name, "required": True}
                          for name in contract["required_assertions"]])
        self.assertIn("never claims an overall P4 all_pass", matrix["non_gating_note"])


class ObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = _load_observer()
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_selfcheck_is_fail_able(self):
        self.assertEqual(self.observer.run_selfcheck(self.contract), 0)
        self.assertGreaterEqual(len(self.observer.DEFECT_TARGETING_CONTROLS), 15)

    def test_legacy_gate_accepts_every_defect_targeting_control(self):
        observer = self.observer
        baseline = observer.compute_verdict(self.contract, observer._base_fixture())
        self.assertTrue(baseline["all_pass"])
        for name, fixture in observer._controls():
            self.assertFalse(observer.compute_verdict(self.contract, fixture)["all_pass"],
                             f"control {name} was accepted by the fixed gate")
            if name in observer.DEFECT_TARGETING_CONTROLS:
                self.assertTrue(observer.legacy_compute_verdict(self.contract, fixture)["all_pass"],
                                f"control {name} is not defect-targeting")

    def test_committed_verdict_matches_a_fresh_derivation(self):
        observations = json.loads(OBSERVATIONS_PATH.read_text(encoding="utf-8"))
        verdict = self.observer.compute_verdict(self.contract, observations)
        committed = json.loads(VERDICT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(verdict["format_valid"], committed["format_valid"])
        self.assertEqual(verdict["all_pass"], committed["all_pass"])
        # With ADR-0087 the paper-account row is bound, so the P4-B scoped verdict
        # is all_pass=true (still scoped to P4-B only).
        self.assertTrue(committed["format_valid"])
        self.assertTrue(committed["all_pass"])
        self.assertTrue(verdict["derived_rows"]["journey:paper-account"])
        self.assertTrue(verdict["derived_rows"]["journey:task-completed"])
        self.assertEqual(committed["blocked_rows"], {})

    def test_adr_0087_closed_paper_account_vocabulary(self):
        from packages.contracts.research_execution_plan import (
            ACTION_APPROVAL, APPROVAL_WAIT_STAGES, NEXT_ACTIONS, STAGES)
        self.assertIn("waiting_for_paper_account_approval", STAGES)
        self.assertIn("ready_to_create_paper_account", STAGES)
        self.assertIn("waiting_for_paper_account_approval", APPROVAL_WAIT_STAGES)
        self.assertIn("request_paper_account_approval", NEXT_ACTIONS)
        self.assertIn("create_paper_account", NEXT_ACTIONS)
        self.assertEqual(ACTION_APPROVAL["create_paper_account"],
                         {"action": "create_paper_account", "resource_kind": "research_task"})
        adr = (ROOT / "docs/architecture/adr/"
               "ADR-0087-deterministic-paper-account-approval.md").read_text(encoding="utf-8")
        self.assertIn("Status: **Accepted**", adr)
        self.assertIn("模型只能提出", adr)

    def test_paper_account_without_a_bound_approval_cannot_pass(self):
        observer = self.observer
        fixture = observer._base_fixture()
        fixture["raw"]["paper_account"]["approval_object_present"] = False
        fixture["raw"]["paper_account"]["approval_binding"] = None
        verdict = observer.compute_verdict(self.contract, fixture)
        self.assertFalse(verdict["all_pass"])
        self.assertFalse(verdict["derived_rows"]["journey:paper-account"])


class RequestGateTests(unittest.TestCase):
    def test_contract_blocks_every_dimension(self):
        from packages.contracts.research_request_budget import (
            request_budget_decision, stage_request_limits,
        )
        limits = stage_request_limits("strategy_draft", request_id="byq-judgment-x",
                                      started_at_ms=1000)
        base = {"provider_calls": 1, "input_bytes": 1, "declared_max_output_tokens": 1,
                "tool_payload_bytes": 1, "attempts": 1, "concurrent": 1,
                "now_ms": 1001, "cancelled": False}
        self.assertTrue(request_budget_decision(limits, base)["admit"])
        for field, value in (("provider_calls", 4), ("input_bytes", limits["max_input_bytes"] + 1),
                             ("declared_max_output_tokens", limits["max_output_tokens"] + 1),
                             ("tool_payload_bytes", limits["max_tool_payload_bytes"] + 1),
                             ("attempts", 4), ("concurrent", 2)):
            self.assertFalse(request_budget_decision(limits, {**base, field: value})["admit"])
        self.assertFalse(request_budget_decision(
            limits, {**base, "cancelled": True})["admit"])

    def test_profiles_are_per_stage_closed_and_not_a_global_constant(self):
        from packages.contracts.research_request_budget import (
            JUDGMENT_STAGES, REQUEST_PROFILES, STAGE_PROFILES, stage_request_limits,
            validate_request_budget,
        )
        ids = {stage_request_limits(stage, request_id="byq-judgment-x", started_at_ms=1000)[
            "profile_id"] for stage in JUDGMENT_STAGES}
        self.assertEqual(len(ids), len(JUDGMENT_STAGES))
        self.assertTrue(ids <= set(REQUEST_PROFILES))
        for stage in JUDGMENT_STAGES:
            budget = stage_request_limits(stage, request_id="byq-judgment-x", started_at_ms=1000)
            self.assertEqual(STAGE_PROFILES[stage], budget["profile_id"])
            self.assertTrue(budget["evidence"])
        with self.assertRaises(ValueError):
            stage_request_limits("strategy_draft", request_id="byq-judgment-x",
                                 started_at_ms=1000, profile="final-selection-bounded.v1")
        limits = stage_request_limits("strategy_draft", request_id="byq-judgment-x",
                                      started_at_ms=1000)
        with self.assertRaises(ValueError):
            validate_request_budget({**limits, "max_provider_calls": 99})
        source = (ROOT / "packages/contracts/research_request_budget.py").read_text()
        self.assertNotIn("PROVIDER_CALL_LIMIT =", source)
        self.assertIn("REQUEST_PROFILES", source)

    def test_unknown_actual_usage_fails_closed(self):
        source = (ROOT / "services/runtime-adapter/app/research_request_gate.py").read_text()
        self.assertIn("actual_usage_unknown", source)
        self.assertIn("COMPLETION_REASONS", source)
        # No artificial timeout floor that could outlive the remaining deadline.
        self.assertNotIn("max(0.1, remaining)", source)

    def test_gate_is_request_scoped_not_a_cross_process_fixed_two(self):
        budget = (ROOT / "packages/contracts/research_request_budget.py").read_text()
        gate = (ROOT / "services/runtime-adapter/app/research_request_gate.py").read_text()
        # No cross-process persistent business balance; fresh request-scoped gate.
        self.assertIn("request-scoped", budget)
        self.assertNotIn("continuation_budget", gate)
        self.assertIn("RequestGateProxy", gate)
        # The durable stage-call admission ledger keeps its own semantics.
        self.assertNotIn("research_judgment_stage_calls", gate)
        # No second harness / no direct DB access in the gate.
        for forbidden in ("psycopg", "sqlalchemy", "deepseek_harness", "subagent"):
            self.assertNotIn(forbidden, gate.lower())

    def test_gate_covers_root_and_child_before_the_request(self):
        turn = (ROOT / "services/runtime-adapter/app/research_judgment_turn.py").read_text()
        self.assertIn("RequestGateProxy", turn)
        self.assertIn("DEEPSEEK_BASE_URL", turn)
        # The gate is opened for the admission's own stage/identity (request scoped).
        self.assertIn("build_request_gate", turn)

    def test_negative_control_module_exists_and_covers_dimensions(self):
        source = (HERE / "request_gate_negative_control.py").read_text()
        for name in ("provider_call_limit", "input_bytes_limit", "tool_payload_limit",
                     "deadline_exceeded", "cancelled", "concurrency_limit",
                     "output_tokens_exceeded", "deadline_upstream_timeout",
                     "actual_usage_unknown", "declared_output_limit_missing",
                     "declared_output_limit_invalid", "declared_output_limit_conflict",
                     "declared_output_limit_exceeds_profile", "profile_forged_evidence",
                     "profile_caller_override"):
            self.assertIn(name, source)
        self.assertIn("request_scoped_fresh_counters", source)

    def test_header_allowlist_and_declared_cap_are_closed(self):
        gate = (ROOT / "services/runtime-adapter/app/research_request_gate.py").read_text()
        self.assertIn("_FORWARDED_REQUEST_HEADERS", gate)
        self.assertIn("forwarded_request_headers", gate)
        self.assertIn("resolve_declared_output_tokens", gate)
        self.assertIn("declared_output_limit_missing", gate)
        self.assertIn("declared_output_limit_conflict", gate)
        # BYQ internal tokens / cookies / hop-by-hop headers are never forwarded.
        for forbidden in ("x-byq", "cookie", "proxy-authorization"):
            self.assertNotIn(forbidden, gate.split("_FORWARDED_REQUEST_HEADERS")[1].split("\n")[0])


class SliceBoundaryTests(unittest.TestCase):
    def test_p4a_verdict_is_unchanged_and_not_all_pass(self):
        verdict = json.loads(P4A_VERDICT.read_text(encoding="utf-8"))
        self.assertFalse(verdict["all_pass"])

    def test_production_seams_for_the_normal_journey(self):
        judgment = (ROOT / "services/backend/app/research_judgment.py").read_text()
        # Completion starts a still-planned task in the same transaction, so the
        # deterministic plan journey can converge a running -> completed task.
        self.assertIn('"running"', judgment)
        self.assertIn("_complete_research_task", judgment)
        api = (ROOT / "services/runtime-adapter/app/research_judgment_api.py").read_text()
        # Each named judgment request gets its own DSH home.
        self.assertIn('call_identity', api)
        self.assertIn('session_root', api)

    def test_status_marks_p4b_candidate_and_keeps_hard_stops(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        self.assertIn("byq:v091-continuation-p4b=merged", status)
        self.assertIn("0.10 与 Phase 100 恢复仍**未授权硬停止**", status)
        self.assertIn("byq:v090-d15-superseding-assessment=established", status)


if __name__ == "__main__":
    unittest.main()
