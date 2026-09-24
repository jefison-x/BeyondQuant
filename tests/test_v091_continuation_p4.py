"""ADR-0085 P4 governance: frozen matrix, fail-able observer, seam boundaries.

These run in the architecture lane (no PostgreSQL, no Docker). They assert that
the frozen acceptance matrix matches the closed contract, that the observer is
fail-able (every defect-targeting control is rejected while a legacy
result-trusting gate would accept it), that the minimal P4 production seam is
read-only where it must be and has no generic plan/event write route, and that
the governance markers remain truthful.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "scripts/v091/continuation_p4"
CONTRACT_PATH = HERE / "contract.v1.json"
MATRIX_PATH = ROOT / "docs/evidence/adr-0085-p4-real-journey/acceptance-matrix.v1.json"
EVIDENCE_DIR = ROOT / "docs/evidence/adr-0085-p4-real-journey"


def _load_observer():
    spec = importlib.util.spec_from_file_location("p4_observer", HERE / "observer.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["p4_observer"] = module
    spec.loader.exec_module(module)
    return module


def _load_probe():
    spec = importlib.util.spec_from_file_location(
        "p4_carrier_readonly_mcp_probe", HERE / "carrier_readonly_mcp_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    def test_contract_is_closed_and_versioned(self):
        contract = self.contract
        self.assertEqual(contract["schema_version"], "byq-v091-continuation-p4-contract.v1")
        self.assertEqual(contract["slice"], "P4")
        self.assertEqual(contract["required_evidence_class"], "runtime-isolated-stack")
        self.assertEqual(contract["llm_evidence_class"], "scripted-keyless")
        journey = [row["id"] for row in contract["required_journey_steps"]]
        faults = [row["id"] for row in contract["required_fault_scenarios"]]
        self.assertEqual(len(journey), len(set(journey)))
        self.assertEqual(len(faults), len(set(faults)))
        self.assertGreaterEqual(len(faults), 8)
        # Every fault row names a real component boundary.
        for row in contract["required_fault_scenarios"]:
            self.assertIn(row["boundary"], contract["provenance_allowed_sources"]["boundary"])
        # The model-visible raw execution fields are explicitly forbidden.
        for field in ("bars_frame", "date_index", "raw_signal_snapshot", "full_execution_snapshot"):
            self.assertIn(field, contract["forbidden_model_visible_fields"])

    def test_matrix_matches_contract_and_is_frozen(self):
        contract, matrix = self.contract, self.matrix
        self.assertTrue(matrix["frozen_before_capture"])
        self.assertEqual(
            [row["id"] for row in matrix["journey_rows"]],
            [row["id"] for row in contract["required_journey_steps"]])
        self.assertEqual(
            [row["id"] for row in matrix["fault_rows"]],
            [row["id"] for row in contract["required_fault_scenarios"]])
        self.assertEqual(
            [row for row in matrix["assertion_rows"]],
            [{"id": name, "required": True} for name in contract["required_assertions"]])
        # A paid-real-model claim must never be forced to PASS.
        self.assertIn("maintainer_canary_required", matrix["non_gating_note"])


class ObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = _load_observer()
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    def test_selfcheck_is_fail_able(self):
        self.assertEqual(self.observer.run_selfcheck(self.contract, self.matrix), 0)

    def test_legacy_gate_would_accept_every_defect_targeting_control(self):
        observer = self.observer
        baseline = observer.compute_verdict(
            self.contract, self.matrix, observer._base_fixture(self.contract))
        self.assertTrue(baseline["all_pass"])
        self.assertGreaterEqual(len(observer.DEFECT_TARGETING_CONTROLS), 20)
        for name, fixture in observer._controls(self.contract):
            self.assertFalse(observer.compute_verdict(self.contract, self.matrix, fixture)["all_pass"],
                             f"control {name} was accepted by the fixed gate")
            if name in observer.DEFECT_TARGETING_CONTROLS:
                self.assertTrue(
                    observer.legacy_compute_verdict(self.contract, self.matrix, fixture)["all_pass"],
                    f"control {name} is not defect-targeting")

    def test_missing_required_row_is_a_structural_failure(self):
        observer = self.observer
        fixture = observer._base_fixture(self.contract)
        fixture["journey"]["steps"] = fixture["journey"]["steps"][1:]
        verdict = observer.compute_verdict(self.contract, self.matrix, fixture)
        self.assertFalse(verdict["format_valid"])
        self.assertFalse(verdict["all_pass"])

    def test_committed_observations_verdict_when_present(self):
        observations_path = EVIDENCE_DIR / "observations.v1.json"
        verdict_path = EVIDENCE_DIR / "verdict.v1.json"
        if not observations_path.exists():
            self.skipTest("no committed observations yet")
        observations = json.loads(observations_path.read_text(encoding="utf-8"))
        verdict = self.observer.compute_verdict(self.contract, self.matrix, observations)
        committed = json.loads(verdict_path.read_text(encoding="utf-8"))
        # The committed verdict must match a fresh re-derivation exactly.
        self.assertEqual(verdict["format_valid"], committed["format_valid"])
        self.assertEqual(verdict["all_pass"], committed["all_pass"])


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "p4_run_journey", HERE / "run_journey.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["p4_run_journey"] = module
    spec.loader.exec_module(module)
    return module


class DriverNegativeTests(unittest.TestCase):
    """The real-stack driver must fail closed on the named fake-journey defects."""

    @classmethod
    def setUpClass(cls):
        cls.driver = _load_driver()

    def test_empty_or_non_loopback_gateway_fails(self):
        for value in ("", None, "http://0.0.0.0:8100", "https://example.com"):
            with self.assertRaises(self.driver.DriverError):
                self.driver.require_gateway(value)
        self.assertEqual(self.driver.require_gateway("http://127.0.0.1:8123"),
                         "http://127.0.0.1:8123")

    def test_zero_real_http_business_calls_fail(self):
        with self.assertRaises(self.driver.DriverError):
            self.driver.require_http(0)
        self.assertEqual(self.driver.require_http(3), 3)

    def test_restart_without_pid_change_or_without_recovery_fails(self):
        good = {"task_status": "running", "plan": {"stage": "waiting_for_data"}}
        with self.assertRaises(self.driver.DriverError):
            self.driver.require_recovered(100, 100, good, good)
        with self.assertRaises(self.driver.DriverError):
            self.driver.require_recovered(0, 200, good, good)
        with self.assertRaises(self.driver.DriverError):
            self.driver.require_recovered(100, 200, good,
                                          {"task_status": "failed", "plan": None})
        self.driver.require_recovered(100, 200, good,
                                      {"task_status": "running",
                                       "plan": {"stage": "waiting_for_task_execute_approval"}})

    def test_placeholder_raw_facts_fail(self):
        with self.assertRaises(self.driver.DriverError):
            self.driver.require_real_raw({"counts": {"research_tasks": 1},
                                          "plan": self.driver.PLACEHOLDER})
        with self.assertRaises(self.driver.DriverError):
            self.driver.require_real_raw({"stage_input_serialized_bytes": "UNKNOWN"})
        self.driver.require_real_raw({"counts": {"research_tasks": 1}, "plan": {"stage": "x"}})

    def test_hardcoded_pass_without_raw_facts_is_rejected_by_the_observer(self):
        observer = _load_observer()
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        fixture = observer._base_fixture(contract)
        # A hardcoded PASS label cannot survive the observer's raw re-derivation.
        fixture["raw"]["counts"]["research_tasks"] = 0
        fixture["journey"]["steps"][0]["status"] = "PASS"
        verdict = observer.compute_verdict(contract, matrix, fixture)
        self.assertFalse(verdict["all_pass"])


class P3ToP4InvocationSeamAuditTests(unittest.TestCase):
    """ADR-0085 P4: the bounded-judgment invocation is a BYQ P3->P4 wiring gap.

    DSH 0.1.5rc1 has no host-named role/tool API and no root tool filter / MCP
    tool allowlist, so the ADR-required mechanism is a dedicated static bounded
    composition with a minimal read-only MCP subset. This is feasible; the P3
    turn_runner is simply unconnected. No BYQ endpoint or generic-prompt
    workaround may be added to bypass the real composition.
    """

    AUDIT = EVIDENCE_DIR / "p3-to-p4-invocation-seam-audit.v1.json"

    def test_seam_audit_records_the_wiring_gap(self):
        self.assertTrue(self.AUDIT.is_file(), "seam audit evidence missing")
        audit = json.loads(self.AUDIT.read_text(encoding="utf-8"))
        self.assertFalse(audit["host_named_role_api_available"])
        self.assertFalse(audit["root_level_tool_filter_supported"])
        self.assertFalse(audit["mcp_client_tool_allowlist_supported"])
        self.assertFalse(audit["p3_turn_runner_wired_in_production"])
        self.assertTrue(audit["root_surface_without_mcp_proven"])
        self.assertEqual(audit["full_feasibility"], "READ_ONLY_MCP_AND_CHILD_PERSONA_PROVEN")
        self.assertEqual(audit["feasibility_status"], "PROVEN_BY_CARRIER_PROBE")
        self.assertEqual(audit["feasibility_evidence"],
                         ["carrier-feasibility.v1.json", "carrier-readonly-mcp-child.v1.json"])
        self.assertGreaterEqual(len(audit["remaining_unproven"]), 3)
        self.assertEqual(audit["conclusion"], "P3_TO_P4_WIRING_GAP_NOT_UPSTREAM_BLOCKER")
        self.assertTrue(audit["composition"]["background_disabled"])
        self.assertTrue(audit["composition"]["persona_registered_as_model_facing_tool"])
        self.assertTrue(audit["composition"]["bounded_single_delegation_level"])
        self.assertEqual(audit["composition"]["max_depth"], 1)
        self.assertNotIn("enable_run_in_background", audit["composition"])

    def test_carrier_probe_raw_facts_show_bounded_root_surface_only(self):
        # Verify the RAW probe facts, not a self-written PASS label: the probe
        # proves only the no-MCP root surface; full feasibility is UNPROVEN.
        feasibility = json.loads(
            (EVIDENCE_DIR / "carrier-feasibility.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(feasibility["proven"]["root_surface_with_no_mcp"])
        self.assertGreaterEqual(len(feasibility["remaining_unproven"]), 3)
        self.assertNotIn("feasibility", feasibility)
        bounded = next(run for run in feasibility["runs"]
                       if run["tool_count"] == 1)
        self.assertEqual(bounded["tool_names"], ["byq_research_judgment_turn"])
        self.assertTrue(bounded["started"] and bounded["run_ok"])
        # The full product composition exposes extra capabilities that the
        # dedicated composition removes; agent-spine built-ins are disabled.
        full = next(run for run in feasibility["runs"] if run["tool_count"] > 1)
        self.assertIn("skill", full["tool_names"])
        for builtin in ("tool-bash", "tool-fs", "tool-jobs", "tool-pwsh"):
            self.assertNotIn(builtin, full["tool_names"])
        # The dedicated composition is committed and is foreground one-shot.
        composition = (ROOT / feasibility["bounded_composition"]["path"]).read_text(
            encoding="utf-8")
        self.assertIn("toolName: byq_research_judgment_turn", composition)
        self.assertIn("enableRunInBackground: false", composition)
        self.assertIn("backgroundMode: one-shot", composition)
        self.assertNotIn("byq_delegate_", composition)
        # The full Product MCP entry is replaced by an isolated read-only entry
        # that reads ONLY the dedicated read-only endpoint/token.
        self.assertNotIn("- id: mcp-byq\n", composition)
        self.assertIn("- id: mcp-byq-readonly\n", composition)
        self.assertIn("process.env.BYQ_MCP_READ_ONLY_URL", composition)
        self.assertNotIn("process.env.BYQ_MCP_URL", composition)
        self.assertNotIn("process.env.BYQ_MCP_TOKEN", composition)
        self.assertIn("failOnStartupError: true", composition)

    def test_carrier_readonly_mcp_child_raw_facts(self):
        # Verify the RAW real-carrier facts, not a PASS label: with the isolated
        # read-only MCP loaded, the real carrier invokes the bounded child persona
        # and neither the root nor the child sees any write/approval/execute/
        # routing tool.
        evidence = json.loads(
            (EVIDENCE_DIR / "carrier-readonly-mcp-child.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(evidence["started"] and evidence["run_ok"])
        self.assertTrue(evidence["child_invoked"])
        self.assertTrue(evidence["all_observed"])
        self.assertEqual(evidence["violations"], [])
        read_only = [
            "mcp__byq__byq_agent_context",
            "mcp__byq__byq_backtest_analysis_get",
            "mcp__byq__byq_backtest_task_get",
            "mcp__byq__byq_research_get",
            "mcp__byq__byq_research_stage_input_get",
        ]
        self.assertEqual(evidence["child_tool_arrays"], [sorted(read_only)])
        self.assertEqual(
            evidence["mcp_tools_list"],
            [name.replace("mcp__byq__", "") for name in read_only])
        self.assertEqual([r["role"] for r in evidence["requests"]], ["root", "child", "root"])
        # The root surface is EXACTLY the persona plus the five read-only MCP
        # tools: a strict equality (not a bare-name substring check) so a leaked
        # prefixed write tool can never pass.
        expected_root = sorted(["byq_research_judgment_turn", *read_only])
        for tool_array in evidence["root_tool_arrays"]:
            self.assertEqual(tool_array, expected_root)
        # The child returned a closed result to the root; the root did not.
        self.assertIn("closed bounded judgment", evidence["requests"][2]["last_tool_excerpt"])

    def test_carrier_probe_evaluator_is_fail_able(self):
        probe = _load_probe()
        read_only = sorted(probe.READ_ONLY_TOOLS)
        good = {
            "started": True, "run_ok": True, "child_invoked": True,
            "mcp_tools_list": [name.replace("mcp__byq__", "") for name in read_only],
            "root_tool_arrays": [sorted([probe.PERSONA_TOOL, *read_only])],
            "child_tool_arrays": [read_only],
            "requests": [{"role": "root", "tool_names": sorted([probe.PERSONA_TOOL, *read_only])},
                         {"role": "child", "tool_names": read_only},
                         {"role": "root", "tool_names": sorted([probe.PERSONA_TOOL, *read_only])}],
        }
        self.assertEqual(probe.evaluate_observations(good), [])
        # A full Product MCP surface (82 tools) or a leaked write tool must be a
        # non-empty violation, and the probe must exit non-zero on it.
        full_surface = dict(good, mcp_tools_list=["byq_health", *read_only],
                            child_invoked=False, child_tool_arrays=[])
        self.assertTrue(probe.evaluate_observations(full_surface))
        leaked = dict(good, root_tool_arrays=[sorted(
            [probe.PERSONA_TOOL, *read_only, "mcp__byq__byq_strategy_version_create"])])
        self.assertTrue(probe.evaluate_observations(leaked))
        # A read-only endpoint/credential collision or a missing value fails closed
        # before the carrier starts.
        with self.assertRaises(ValueError):
            probe.resolve_probe_env({"BYQ_MCP_READ_ONLY_URL": "http://mcp:8300/mcp/v1",
                                     "BYQ_MCP_READ_ONLY_TOKEN": "ro", "BYQ_MCP_URL": "http://mcp:8300/mcp/v1"})
        with self.assertRaises(ValueError):
            probe.resolve_probe_env({})

    def test_dedicated_composition_uses_only_the_read_only_endpoint(self):
        composition = (
            ROOT / "plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/"
                   "byq-research-judgment.patch.yml").read_text(encoding="utf-8")
        self.assertIn("process.env.BYQ_MCP_READ_ONLY_URL", composition)
        self.assertIn("process.env.BYQ_MCP_READ_ONLY_TOKEN", composition)
        # No generic Product endpoint/token is read by the bounded composition.
        self.assertNotIn("process.env.BYQ_MCP_URL", composition)
        self.assertNotIn("process.env.BYQ_MCP_TOKEN", composition)

    def test_carrier_turn_runner_real_facts(self):
        # The REAL Runtime Adapter turn_runner built the real DSH harness over the
        # dedicated composition and extracted the closed result from the real
        # subagent.finished notification; no forbidden tool was exposed.
        evidence = json.loads(
            (EVIDENCE_DIR / "carrier-turn-runner.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(evidence["runner_ok"])
        self.assertTrue(evidence["child_invoked"])
        self.assertTrue(evidence["all_observed"])
        self.assertEqual(evidence["violations"], [])
        self.assertEqual(evidence["forbidden_exposed"], [])
        self.assertEqual(evidence["closed_result"]["proposal"]["proposal_kind"],
                         "backtest_analysis")
        self.assertEqual([r["role"] for r in evidence["requests"]], ["root", "child", "root"])
        # The adapter turn_runner resolves a trusted absolute dedicated composition
        # and derives the read-only endpoint from the trusted guard.
        turn_module = (ROOT / "services/runtime-adapter/app/research_judgment_turn.py").read_text(
            encoding="utf-8")
        self.assertIn("resolve_read_only_mcp_endpoint", turn_module)
        self.assertIn("resolve_judgment_composition", turn_module)
        self.assertIn('DEDICATED_COMPOSITION_PATH = "/opt/byq/profiles/', turn_module)

    def test_isolated_four_boundary_first_real_loop(self):
        # The REAL isolated non-production four-boundary NORMAL strategy_draft loop.
        evidence = json.loads(
            (EVIDENCE_DIR / "isolated-four-boundary.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(evidence["all_observed"])
        self.assertEqual(evidence["violations"], [])
        controls = evidence["negative_controls"]
        self.assertEqual(controls["no_token_status"], 401)
        self.assertEqual(controls["forged_token_status"], 401)
        self.assertEqual(controls["stage_calls_before"], 0)
        self.assertEqual(controls["stage_calls_after"], 0)
        self.assertEqual(evidence["boundary2_adapter"]["status"], 200)
        invocation = evidence["boundary2_adapter"]["response"]["adapter_invocation"]
        self.assertTrue(invocation["call_identity"].startswith("byq-judgment-"))
        self.assertTrue(invocation["id"].startswith("byq-adapter-"))
        self.assertEqual(invocation["attempt"], "1:strategy_draft:1")
        self.assertEqual(
            evidence["boundary2_adapter"]["response"]["dsh_generation"]["status"],
            "not_available")
        dsh = evidence["boundary3_dsh"]
        provider = dsh["provider"]
        self.assertGreaterEqual(provider["root_calls"], 1)
        self.assertGreaterEqual(provider["child_calls"], 1)
        self.assertEqual(dsh["positive_provider_delta"], 3)
        backend = evidence["boundary4_backend"]
        rows = backend["stage_call_rows"]
        self.assertTrue(rows and rows[0][1] == "completed" and rows[0][2] == "1")
        # Normal branch: waiting_for_strategy_approval, approval bound to the exact
        # user-confirmed validated strategy_version.
        self.assertEqual(backend["final_plan"][1], "waiting_for_strategy_approval")
        approval = backend["plan_approval"]
        self.assertEqual(approval["action"], "strategy_approve")
        self.assertEqual(approval["resource_kind"], "strategy_version")
        self.assertEqual(approval["resource_id"],
                         evidence["boundary1_product_api"]["confirmed_strategy_version"])
        self.assertEqual(
            backend["plan_references"]["strategy_version"]["strategy_version"],
            evidence["boundary1_product_api"]["confirmed_strategy_version"])
        # The ACTUAL model-visible bounded input (provider-observed), cross-checked
        # against the trusted Backend stage input.
        projection = evidence["boundary_stage_projection"]
        observed = projection["observed_by_provider"]
        self.assertEqual(observed["forbidden_raw_hits"], [])
        self.assertLessEqual(observed["bounded_input_bytes"], 65536)
        self.assertEqual(observed["bounded_input_digest"], projection["trusted_backend"]["digest"])
        self.assertEqual(observed["input_stage"], "strategy_draft")
        self.assertTrue(set(observed["child_tools"]).issubset({
            "mcp__byq__byq_agent_context", "mcp__byq__byq_research_get",
            "mcp__byq__byq_research_stage_input_get", "mcp__byq__byq_backtest_task_get",
            "mcp__byq__byq_backtest_analysis_get"}))
        # Negative controls never reached the provider.
        controls = evidence["negative_controls"]
        self.assertEqual(controls["provider_calls_after"], controls["provider_calls_before"])
        # A duplicate completed request only replays with zero extra TOTAL calls.
        replay = evidence["replay"]
        self.assertEqual(replay["status"], 200)
        self.assertTrue(replay["replayed"] and replay["model_turn_skipped"])
        self.assertEqual(replay["provider_calls_after"], replay["provider_calls_before"])
        self.assertEqual(replay["stage_calls"], "1")
        # Real approval handoff: user decision advances the plan deterministically
        # to the next gate with zero model calls and no duplicate objects on replay.
        handoff = evidence["approval_handoff"]
        self.assertTrue(handoff["approval_id"].startswith("agent_approval_"))
        self.assertEqual(handoff["decision_status"], "approved")
        self.assertEqual(handoff["plan_after_decision"][1], "waiting_for_task_create_approval")
        self.assertEqual(handoff["event_count"], 1)
        self.assertEqual(handoff["plan_after_replay"], handoff["plan_after_decision"])
        self.assertEqual(handoff["event_count_after_replay"], handoff["event_count"])
        self.assertEqual(handoff["provider_calls_after"], handoff["provider_calls_before"])
        # Per-task provider accounting: the real judgment turn made exactly 3 calls
        # and the deterministic handoffs made ZERO extra model calls.
        self.assertEqual(dsh["task_provider_calls"], 3)
        self.assertEqual(handoff["task_provider_calls_before_handoff"], 3)
        self.assertEqual(handoff["task_provider_calls_after_handoff"], 3)
        # Second real deterministic handoff: the task-create approval advances to
        # ready_to_create_backtest_task and the trusted deterministic
        # create_backtest_task action advances to waiting_for_data; an idempotent
        # replay changes nothing.
        nxt = evidence["next_handoff"]
        self.assertTrue(nxt["task_create_approval_id"].startswith("agent_approval_"))
        self.assertEqual(nxt["plan_after_task_create_approval"][1],
                         "ready_to_create_backtest_task")
        self.assertEqual(nxt["plan_after_action"][1], "waiting_for_data")
        self.assertEqual(nxt["plan_after_action_replay"], nxt["plan_after_action"])
        self.assertTrue(nxt["signal_job_created"])
        self.assertEqual(nxt["task_provider_calls"], 3)

    def test_no_byq_endpoint_or_workaround_bypasses_the_composition(self):
        # ADR-0085 P4: the Runtime Adapter may expose exactly ONE named trusted
        # internal judgment entry; it must delegate to the real bounded
        # turn_runner and must never accept a caller-supplied model result or a
        # generic prompt route.
        adapter = (ROOT / "services/runtime-adapter/app/main.py").read_text(encoding="utf-8")
        self.assertIn("research_judgment_router", adapter)
        api = (ROOT / "services/runtime-adapter/app/research_judgment_api.py").read_text(
            encoding="utf-8")
        self.assertIn("/internal/runtime/research-judgment/{task_id}/run", api)
        self.assertIn("run_stage_judgment", api)
        # No caller-supplied model result and no request-body parsing.
        self.assertNotIn("model_result", api)
        self.assertNotIn("next_action", api)
        self.assertNotIn("request.json()", api)
        # The driver must not assemble a model result itself.
        driver = (HERE / "run_journey.py").read_text(encoding="utf-8")
        self.assertNotIn("model_result", driver)
        self.assertNotIn("proposal", driver)
        # The only production caller is the trusted internal entry, which derives
        # everything server-side and delegates to the real bounded turn_runner.
        entry = (ROOT / "services/runtime-adapter/app/research_judgment_entry.py").read_text(
            encoding="utf-8")
        self.assertIn("run_bounded_research_judgment", entry)
        self.assertIn("DshBoundedTurnRunner", entry)
        self.assertNotIn("deepseek_harness", entry)
        self.assertNotIn("model_result", entry)


class SeamBoundaryTests(unittest.TestCase):
    def test_plan_continuation_seam_has_no_generic_write_route(self):
        backend_main = (ROOT / "services/backend/app/main.py").read_text(encoding="utf-8")
        for forbidden in ("/v1/research/execution-plans", "/v1/research/continuation-events",
                          "record_continuation_event"):
            self.assertNotIn(forbidden, backend_main)
        module = (ROOT / "services/backend/app/research_plan_continuation.py").read_text(encoding="utf-8")
        # The dispatch descriptor never exposes a write capability to the model.
        self.assertIn("bounded_projection_only", module)
        self.assertNotIn("bars_frame", module)
        self.assertNotIn("date_index", module)

    def test_grant_creates_plan_and_approval_route_advances_it(self):
        continuation = (ROOT / "services/backend/app/research_continuation.py").read_text(encoding="utf-8")
        self.assertIn("self.ensure_execution_plan(task_id, trusted_context=trusted_context)", continuation)
        backend_main = (ROOT / "services/backend/app/main.py").read_text(encoding="utf-8")
        self.assertIn("_advance_plan_after_approval(approval_id, context)", backend_main)
        self.assertIn("record_plan_approval_event", backend_main)

    def test_no_second_generic_harness_or_session_store(self):
        module = (ROOT / "services/backend/app/research_plan_continuation.py").read_text(encoding="utf-8")
        for forbidden in ("psycopg", "asyncpg", "sqlalchemy", "pty", "session_store", "subagent"):
            self.assertNotIn(forbidden, module.lower())

    def test_status_marks_p4_current_and_keeps_hard_stops(self):
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        self.assertIn("byq:harness-continuation=", status)
        self.assertIn("p4", status)
        self.assertIn("0.10 与 Phase 100 恢复仍**未授权硬停止**", status)
        # Historical D15 verdicts are never rewritten by this slice.
        self.assertIn("byq:v090-d15-superseding-assessment=established", status)


if __name__ == "__main__":
    unittest.main()
