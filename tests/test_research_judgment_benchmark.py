"""ADR-0085 P3 offline calibration against the bounded Jev P3 benchmark.

Deterministic, offline, no model/provider/paid API/production database. It reuses
the 60-case ``benchmarks/jev`` oracle and rubric ONLY as a fixture: it proves the
closed stage-input/proposal contract can express (and correctly classify) every
oracle decision, and that no case is representable as raw execution data. The
benchmark is NEVER a BYQ router and no calibration function is imported by
production code.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from packages.contracts.research_judgment import (
    FORBIDDEN_PROPOSAL_FIELDS,
    STAGE_ALLOWED_TOOLS,
    STAGE_INPUT_MAX_BYTES,
    STAGE_INPUT_SCHEMA_VERSION,
    STAGE_PROPOSAL_KINDS,
    TEXT_MAX,
    derive_proposal_commit,
    validate_proposal,
    validate_stage_input,
)
from packages.contracts.research_execution_plan import plan_at_stage

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks/jev/benchmark.v1.jsonl"
RUBRIC = ROOT / "benchmarks/jev/decision-rubric.v1.json"
VALIDATOR = ROOT / "benchmarks/jev/validate_benchmark.py"

CATEGORIES = {
    "three_round_backtest_comparison", "evidence_sufficiency",
    "strategy_revision_direction", "escalation_to_llm",
    "robustness_regime_conflict", "adversarial_calibration",
}

# Rule families whose offline oracle outcome is "do not decide": missing or
# insufficient evidence, missing lineage/coverage, honest block or scope reject.
NO_DECISION_RULES = frozenset({
    "EVID_SAMPLE_01", "EVID_MISSING_OOS_07", "EVID_HONEST_BLOCKED_12",
    "LINEAGE_REQUIRED_10", "REGIME_COVERAGE_11", "SCOPE_REJECT_23", "ESC_NO_DATA_21",
})

STAGE_BY_CATEGORY = {
    "three_round_backtest_comparison": "iteration_comparison",
    "strategy_revision_direction": "iteration_comparison",
    "evidence_sufficiency": "backtest_analysis",
    "escalation_to_llm": "backtest_analysis",
    "robustness_regime_conflict": "backtest_analysis",
    "adversarial_calibration": "backtest_analysis",
}

REVISION_DIRECTION = {
    "A": "none", "B": "tighten_risk", "C": "improve_robustness",
    "D": "extend_evidence", "E": "reduce_turnover", "F": "extend_evidence",
}
REVISION_RULES = frozenset({
    "REV_KEEP_13", "REV_POSITION_14", "REV_STOP_15", "REV_MA_16", "REV_KELLY_17", "REV_RESEARCH_18",
})
RUBRIC_POLICIES = json.loads(RUBRIC.read_text(encoding="utf-8"))["rule_escalation"]


def _cases() -> list[dict]:
    return [json.loads(line) for line in BENCHMARK.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rule(case: dict) -> str:
    return [tag[5:] for tag in case["tags"] if tag.startswith("rule:")][0]


def plan_for(case: dict, stage: str):
    if stage == "iteration_comparison":
        iteration = 2 if _rule(case) in REVISION_RULES else 3
    else:
        iteration = 1
    return plan_at_stage(
        task_id="task_" + "a" * 32, owner_principal="owner_1", workspace_id="ws_1",
        conversation_id="conv_1", task_version=5, stage=stage, iteration=iteration,
        idempotency_key=f"bench-{case['case_id']}")


def stage_input_for(case: dict, stage: str) -> dict:
    return validate_stage_input({
        "schema_version": STAGE_INPUT_SCHEMA_VERSION, "task_id": "task_" + "a" * 32,
        "plan_version": 1, "task_version": 5, "stage": stage,
        "iteration": plan_for(case, stage)["iteration"], "status": "active",
        "objective": str(case["question"])[:TEXT_MAX], "stage_instruction": "judge",
        "proposal_kinds": sorted(STAGE_PROPOSAL_KINDS[stage]),
        "evidence": [{"kind": "metric_summary", "id": f"case_{case['case_id']}",
                      "summary": f"offline_synthetic {case['category']} state"}],
        "allowed_tools": sorted(STAGE_ALLOWED_TOOLS[stage]),
        "model_call_limit": 2, "escalation_allowed": True,
    })


def proposal_for(case: dict, stage: str) -> dict:
    expected = case["expected"]
    rule = _rule(case)
    required = RUBRIC_POLICIES.get(rule) == "required"
    if stage == "iteration_comparison" and rule in REVISION_RULES:
        default_kind = "propose_revision"
    elif stage == "iteration_comparison":
        default_kind = "select_iteration"
    else:
        default_kind = "backtest_analysis"
    proposal = {
        "schema_version": "research-proposal.v1", "task_id": "task_" + "a" * 32,
        "plan_version": 1, "task_version": 5, "stage": stage,
        "iteration": plan_for(case, stage)["iteration"], "proposal_kind": default_kind,
        "evidence_sufficient": True, "escalate": False,
        "summary": f"offline calibration for {case['case_id']}",
    }
    if default_kind == "propose_revision":
        proposal["revision_direction"] = REVISION_DIRECTION.get(expected["preferred_choice"], "extend_evidence")
    elif default_kind == "select_iteration":
        proposal["selected_iteration"] = {"A": 1, "B": 2, "C": 3}.get(expected["preferred_choice"], 3)
    if required:
        proposal["escalate"] = True
    elif rule in NO_DECISION_RULES:
        proposal["evidence_sufficient"] = False
    return validate_proposal(proposal)


class JevBenchmarkCalibrationTests(unittest.TestCase):
    def test_validator_and_dataset_shape(self) -> None:
        completed = subprocess.run([sys.executable, str(VALIDATOR)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        cases = _cases()
        self.assertEqual(len(cases), 60)
        counts: dict[str, int] = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        self.assertEqual(set(counts), CATEGORIES)
        self.assertTrue(all(count == 10 for count in counts.values()), counts)

    def test_rubric_scope_matches_contract_forbidden_authority(self) -> None:
        rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
        self.assertIn("never a BYQ router", rubric["purpose"])
        required = {
            "workflow next_action": {"next_action", "next_stage"},
            "object identity": {"object_id", "business_identity"},
            "approval execution": {"approval"},
            "idempotency key generation": {"idempotency_key"},
            "job routing": {"route", "routing"},
            "recovery or continuation state": {"status", "target_status"},
        }
        for phrase, fields in required.items():
            self.assertIn(phrase, rubric["scope"]["forbidden"])
            self.assertTrue(fields <= FORBIDDEN_PROPOSAL_FIELDS, phrase)
        self.assertIn("orders or trading instructions", rubric["scope"]["forbidden"])
        self.assertFalse(any("order" in field or "trade" in field for field in FORBIDDEN_PROPOSAL_FIELDS))

    def test_every_case_is_representable_within_bounds_and_without_raw_data(self) -> None:
        rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
        state_limit = int(rubric["thresholds"]["bounded_state_max_bytes"])
        for case in _cases():
            with self.subTest(case=case["case_id"]):
                stage = STAGE_BY_CATEGORY[case["category"]]
                value = stage_input_for(case, stage)
                self.assertLessEqual(len(json.dumps(value, separators=(",", ":")).encode()), STAGE_INPUT_MAX_BYTES)
                state_bytes = len(json.dumps(case["state"], separators=(",", ":")).encode())
                self.assertLessEqual(state_bytes, state_limit)

    def test_offline_oracle_decisions_classify_through_the_commit_reducer(self) -> None:
        needs_attention = 0
        advanced = 0
        for case in _cases():
            with self.subTest(case=case["case_id"]):
                stage = STAGE_BY_CATEGORY[case["category"]]
                plan = plan_for(case, stage)
                proposal = proposal_for(case, stage)
                decision = derive_proposal_commit(plan, proposal)
                rule = _rule(case)
                required = RUBRIC_POLICIES.get(rule) == "required"
                should_stop = required or rule in NO_DECISION_RULES
                if should_stop:
                    needs_attention += 1
                    self.assertEqual(decision["outcome"], "needs_attention")
                    self.assertIn(decision["reason"], {"escalation_requested", "insufficient_evidence"})
                else:
                    advanced += 1
                    self.assertEqual(decision["outcome"], "advance")
        self.assertEqual(needs_attention + advanced, 60)
        self.assertGreater(advanced, 0)
        self.assertGreater(needs_attention, 0)

    def test_calibration_is_never_a_router(self) -> None:
        # The offline decisions stay in the test layer; no production module
        # imports the benchmark or a calibration policy.
        for source in (ROOT / "packages/contracts/research_judgment.py",
                       ROOT / "services/backend/app/research_judgment.py"):
            text = source.read_text(encoding="utf-8")
            self.assertNotIn("benchmarks/jev", text)
            self.assertNotIn("decision-rubric", text)
            self.assertNotIn("import benchmarks", text.lower())


if __name__ == "__main__":
    unittest.main()
