"""D15-5 persistent-terminal (PTY) acceptance tests.

Covers the framework-neutral TerminalAttachment contract (the four existence
dimensions and the BYQ/DSH ownership split), the fail-able observer
(format-valid vs qualification-pass separation, required BLOCKED gating, false
reattach rejection, contract-authoritative assertions, honest pre-fix
comparison), the committed evidence truthfulness, and the BYQ wiring probe.
Runs under ``unittest`` (the architecture lane has no pytest).

Set ``BYQ_D15_5_RUN_NATIVE=1`` to additionally execute the real native terminal
harness (requires ``npm ci`` in ``scripts/d15/terminal`` and a Node runtime).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from packages.contracts import terminal_attachment as terminal

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = ROOT / "scripts/d15/terminal"
OBSERVER = TERMINAL / "observer.py"
CONTRACT = TERMINAL / "contract.v1.json"
EVIDENCE = ROOT / "docs/evidence/d15/d15-5"


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_5_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_5_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


class TerminalAttachmentContractTests(unittest.TestCase):
    def test_closed_vocabulary_and_dimensions(self):
        self.assertEqual(terminal.TERMINAL_ATTACHMENT_VERSION, "terminal-attachment.v1")
        self.assertEqual(terminal.STATUSES, frozenset(
            {"attached", "reattached", "rehydrated", "lost", "interrupted", "fenced"}))
        self.assertEqual(terminal.EXISTENCE_DIMENSIONS,
                         ("pty_process", "attachment", "io_rebind", "terminal_identity"))
        with self.assertRaises(ValueError):
            terminal.normalize_status("not-a-status")

    def test_ownership_boundary_is_byq_attachment_dsh_pty(self):
        self.assertEqual(terminal.BYQ_OWNED,
                         frozenset({"attachment_identity", "attachment_state", "authorization", "reconnect"}))
        self.assertEqual(terminal.DSH_OWNED, frozenset({"pty_process", "shell", "io"}))
        self.assertFalse(terminal.BYQ_BUILDS_PTY_RUNTIME)
        self.assertFalse(terminal.TERMINAL_LIFETIME_DEFINES_CONVERSATION)

    def test_attachment_record_rejects_self_declared_identity(self):
        record = terminal.TerminalAttachmentRecord(
            attachment_id="att-1", owner_principal="owner", generation=1, executor_epoch=1)
        self.assertEqual(record.status, terminal.ATTACHED)
        with self.assertRaises(ValueError):
            terminal.TerminalAttachmentRecord(attachment_id="", owner_principal="owner",
                                              generation=1, executor_epoch=1)
        with self.assertRaises(ValueError):
            terminal.TerminalAttachmentRecord(attachment_id="att-1", owner_principal="",
                                              generation=1, executor_epoch=1)

    def test_classification_never_fabricates_reattach(self):
        # A surviving PTY with no BYQ attachment is unreachable, not reattached.
        decision = terminal.classify_terminal_transition(
            attachment_survived=False, pty_process_alive=True, io_rebind_available=False,
            terminal_identity_stable=False, native_session_survived=False, faulted=True)
        self.assertEqual(decision.status, terminal.LOST)
        # A real in-process rebind is reattached only when identity is stable.
        decision = terminal.classify_terminal_transition(
            attachment_survived=True, pty_process_alive=True, io_rebind_available=True,
            terminal_identity_stable=True, native_session_survived=True, faulted=True)
        self.assertEqual(decision.status, terminal.REATTACHED)
        # Native rehydrate requires a surviving native session AND a rebind.
        decision = terminal.classify_terminal_transition(
            attachment_survived=False, pty_process_alive=True, io_rebind_available=True,
            terminal_identity_stable=True, native_session_survived=True, faulted=True)
        self.assertEqual(decision.status, terminal.REHYDRATED)

    def test_stale_generation_and_epoch_are_fenced(self):
        for kwargs in ({"stale_generation": True}, {"stale_epoch": True}):
            decision = terminal.classify_terminal_transition(
                attachment_survived=True, pty_process_alive=True, io_rebind_available=True,
                terminal_identity_stable=True, native_session_survived=True, faulted=True, **kwargs)
            self.assertEqual(decision.status, terminal.FENCED)
            self.assertTrue(decision.diagnostics["byq_attachment_survived"])

    def test_diagnostics_are_evidence_only(self):
        decision = terminal.classify_terminal_transition(
            attachment_survived=True, pty_process_alive=True, io_rebind_available=True,
            terminal_identity_stable=True, native_session_survived=True)
        self.assertTrue(terminal.valid_status(decision.status))
        self.assertLessEqual(set(decision.diagnostics), terminal.DIAGNOSTIC_FIELDS)
        with self.assertRaises(ValueError):
            terminal.TerminalAttachmentDecision(status="fine", diagnostics={"leak": True})


class D15TerminalObserverTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-d15-5-contract.v1")
        ids = [item["id"] for item in contract["required_fault_rows"]]
        self.assertEqual(len(ids), len(set(ids)))
        for expected in ("page-refresh", "browser-disconnect", "frontend-restart",
                         "gateway-restart", "adapter-restart", "dsh-runtime-restart"):
            self.assertIn(expected, ids)
        optional = [item["id"] for item in contract["optional_fault_rows"]]
        self.assertIn("host-reboot", optional)
        self.assertTrue(set(optional).isdisjoint(ids))
        checks = {item["id"] for item in contract["required_cross_checks"]}
        self.assertEqual(checks, {"pty-attachment-separation", "unique-marker-once",
                                  "permission-boundary", "wrong-terminal-rejected",
                                  "stale-generation-fenced", "cleanup-no-orphans"})
        self.assertEqual(contract["candidate"]["release"], "dsh-0.1.5rc1")
        self.assertEqual(contract["required_evidence_class"], "native-runtime-isolated")
        self.assertEqual(contract["existence_dimensions"],
                         ["pty_process", "attachment", "io_rebind", "terminal_identity"])
        # adapter/dsh restart are required and must not pass by removal.
        by_id = {item["id"]: item for item in contract["required_fault_rows"]}
        for required_id in ("adapter-restart", "dsh-runtime-restart"):
            self.assertTrue(by_id[required_id]["required"])

    def test_fully_qualified_fixture_passes_and_required_blocked_fails(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer._fully_qualified_fixture(contract)
        qualified["evidence_class"] = contract["required_evidence_class"]
        verdict = observer.compute_verdict(contract, qualified)
        self.assertTrue(verdict["all_pass"], verdict["failures"])
        self.assertTrue(verdict["format_valid"])

        blocked = observer.valid_fixture(contract)
        for row in blocked["scenarios"]:
            if row["id"] in {"adapter-restart", "dsh-runtime-restart"}:
                row.update({"result": "BLOCKED", "fault_applied": True,
                            "not_run_reason": "injected required blocked"})
                row.pop("observation", None)
        verdict = observer.compute_verdict(contract, blocked, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertIn("adapter-restart", verdict["reason_uncovered"])
        self.assertIn("dsh-runtime-restart", verdict["reason_uncovered"])

    def test_every_negative_control_fails_and_pre_fix_defects_are_evidenced(self):
        observer = _load_observer()
        contract = _contract()
        result = observer.selfcheck(contract)
        self.assertTrue(result["all_controls_pass"])
        self.assertTrue(result["known_good_unit_fixture_format_valid"])
        self.assertTrue(result["known_good_unit_fixture_all_pass"])
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)

    def test_false_reattach_and_missing_dimensions_fail(self):
        observer = _load_observer()
        contract = _contract()
        baseline = observer._fully_qualified_fixture(contract)
        baseline["evidence_class"] = contract["required_evidence_class"]

        import copy
        drift = copy.deepcopy(baseline)
        row = next(item for item in drift["scenarios"] if item["id"] == "page-refresh")
        row["observation"]["observedSessionId"] = "pty-999"
        verdict = observer.compute_verdict(contract, drift)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("false reattach" in failure for failure in verdict["failures"]))

        missing = copy.deepcopy(baseline)
        row = next(item for item in missing["scenarios"] if item["id"] == "browser-disconnect")
        row["dimensions"].pop("io_rebind")
        verdict = observer.compute_verdict(contract, missing)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("four-way dimensions" in failure for failure in verdict["failures"]))

    def test_fault_is_required_where_the_contract_demands_it(self):
        observer = _load_observer()
        contract = _contract()
        baseline = observer._fully_qualified_fixture(contract)
        baseline["evidence_class"] = contract["required_evidence_class"]
        for row in baseline["scenarios"]:
            if row["id"] == "page-refresh":
                row["fault_applied"] = False
        verdict = observer.compute_verdict(contract, baseline)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("fault_applied" in failure for failure in verdict["failures"]))

    def test_observation_may_not_declare_its_own_coverage(self):
        observer = _load_observer()
        contract = _contract()
        baseline = observer._fully_qualified_fixture(contract)
        baseline["evidence_class"] = contract["required_evidence_class"]
        for row in baseline["scenarios"]:
            if row["id"] == "gateway-restart":
                row["required"] = False
                row["assertions_ok"] = True
        verdict = observer.compute_verdict(contract, baseline)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("may not declare" in failure for failure in verdict["failures"]))


class D15TerminalEvidenceTests(unittest.TestCase):
    def test_committed_verdict_is_truthful_and_not_a_full_pass(self):
        verdict = json.loads((EVIDENCE / "verdict.v1.json").read_text(encoding="utf-8"))
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["negatives_ok"])
        self.assertTrue(verdict["cross_checks_ok"])
        coverage = verdict["required_coverage"]
        for row_id in ("page-refresh", "browser-disconnect", "frontend-restart", "gateway-restart"):
            self.assertEqual(coverage[row_id], "PASS", row_id)
        self.assertEqual(coverage["adapter-restart"], "BLOCKED")
        self.assertEqual(coverage["dsh-runtime-restart"], "BLOCKED")
        self.assertEqual(verdict["optional_coverage"]["host-reboot"], "NOT_RUN")
        self.assertIn("adapter-restart", verdict["reason_uncovered"])
        self.assertIn("dsh-runtime-restart", verdict["reason_uncovered"])

    def test_observations_record_the_four_way_distinction(self):
        observations = json.loads(
            (EVIDENCE / "native-terminal-observations.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(observations["evidence_class"], "native-runtime-isolated")
        self.assertFalse(observations["llm"]["real_llm_quality"])
        rows = {item["id"]: item for item in observations["scenarios"]}
        for row_id in ("page-refresh", "browser-disconnect", "frontend-restart", "gateway-restart"):
            row = rows[row_id]
            self.assertEqual(row["result"], "PASS")
            self.assertEqual(row["dimensions"]["pty_process"], "present")
            self.assertEqual(row["dimensions"]["attachment"], "present")
            self.assertEqual(row["dimensions"]["io_rebind"], "ok")
            self.assertEqual(row["dimensions"]["terminal_identity"], "stable")
            obs = row["observation"]
            self.assertTrue(obs["sameAttachment"] and obs["sameSession"] and obs["samePtyPid"])
            self.assertEqual(obs["observedPid"], obs["expectedPid"])
        for row_id in ("adapter-restart", "dsh-runtime-restart"):
            row = rows[row_id]
            self.assertEqual(row["result"], "BLOCKED")
            self.assertTrue(row["observation"]["rebindOk"] is False)
            self.assertEqual(row["dimensions"]["terminal_identity"], "lost")
        self.assertEqual(rows["host-reboot"]["result"], "NOT_RUN")

    def test_unique_marker_and_separation_evidence_is_real(self):
        observations = json.loads(
            (EVIDENCE / "native-terminal-observations.v1.json").read_text(encoding="utf-8"))
        checks = {item["id"]: item for item in observations["cross_checks"]}
        marker = checks["unique-marker-once"]["observation"]
        self.assertNotEqual(marker["marker1"], marker["marker2"])
        self.assertEqual(marker["marker1InFirstViewport"], 1)
        self.assertEqual(marker["marker1InRebindSendDelta"], 0)
        self.assertEqual(marker["marker1InScrollback"], 1)
        self.assertEqual(marker["marker2InRebindSendDelta"], 1)
        separation = checks["pty-attachment-separation"]["observation"]
        self.assertTrue(separation["ptyCmdlineBefore"])
        self.assertIn("bash", separation["ptyCmdlineBefore"])
        self.assertTrue(separation["attachmentId"] != separation["sessionId"])
        self.assertEqual(separation["rebindErrorAfterDetach"], "ATTACHMENT_DETACHED")
        self.assertTrue(separation["ptyAliveAfterAttachmentLoss"])
        self.assertTrue(separation["sessionKillEndedPty"])

    def test_permissions_stale_and_cleanup_are_real_rejections(self):
        observations = json.loads(
            (EVIDENCE / "native-terminal-observations.v1.json").read_text(encoding="utf-8"))
        checks = {item["id"]: item for item in observations["cross_checks"]}
        self.assertEqual(checks["permission-boundary"]["observation"]["foreignSendError"], "FOREIGN_SESSION")
        self.assertEqual(checks["permission-boundary"]["observation"]["foreignReadError"], "FOREIGN_SESSION")
        self.assertEqual(checks["permission-boundary"]["observation"]["foreignPrincipalError"],
                         "UNAUTHORIZED_PRINCIPAL")
        self.assertEqual(checks["wrong-terminal-rejected"]["observation"]["errorCode"], "NO_SESSION")
        stale = checks["stale-generation-fenced"]["observation"]
        self.assertEqual(stale["staleGenerationError"], "STALE_GENERATION")
        self.assertEqual(stale["staleEpochError"], "STALE_EPOCH")
        cleanup = checks["cleanup-no-orphans"]["observation"]
        self.assertEqual(cleanup["orphanCount"], 0)
        self.assertEqual(cleanup["runtimeShutdownOrphans"], 0)
        self.assertFalse(cleanup["pidAliveAfterKill"])
        negatives = {item["kind"]: item for item in observations["negatives"]}
        self.assertTrue(all(item["rejected"] for item in negatives.values()))
        self.assertEqual(negatives["foreign-owner-send"]["errorCode"], "FOREIGN_SESSION")
        self.assertEqual(negatives["unknown-terminal"]["errorCode"], "NO_SESSION")

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads((EVIDENCE / "negative-controls.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_pass"])
        self.assertGreater(controls["defect_targeting_pre_fix_passed_count"], 0)
        names = {item["name"] for item in controls["controls"]}
        for expected in ("fabricated-reattach-session-drift", "fabricated-reattach-pid-drift",
                         "fabricated-reattach-attachment-drift", "false-identity-claim",
                         "missing-dimension", "marker-replayed", "marker-lost",
                         "permission-bypass", "stale-not-fenced", "orphan-left"):
            self.assertIn(expected, names)

    def test_interface_probe_shows_no_byq_terminal_wiring(self):
        probe = json.loads((EVIDENCE / "interface-probe.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(probe["schema_version"], "byq-d15-5-interface-probe.v1")
        conclusions = probe["conclusions"]
        self.assertTrue(conclusions["native_terminal_capability_present_in_candidate"])
        self.assertTrue(conclusions["native_sessions_documented_process_local"])
        self.assertFalse(conclusions["byq_composes_terminal_service"])
        self.assertFalse(conclusions["byq_exposes_terminal_surface"])
        self.assertFalse(conclusions["byq_persists_terminal_attachment"])
        self.assertFalse(conclusions["byq_can_reattach_after_runtime_restart"])
        by_id = {item["id"]: item for item in probe["blocked_items"]}
        for blocked in ("byq-terminal-product-surface", "byq-adapter-restart-rebind",
                        "dsh-runtime-restart-rebind"):
            self.assertEqual(by_id[blocked]["status"], "BLOCKED")

    def test_evidence_is_v1_and_not_overwritten(self):
        for name in ("native-terminal-observations.v1.json", "verdict.v1.json",
                     "negative-controls.v1.json", "interface-probe.v1.json", "README.md"):
            self.assertTrue((EVIDENCE / name).is_file(), name)


@unittest.skipUnless(os.environ.get("BYQ_D15_5_RUN_NATIVE") == "1",
                     "set BYQ_D15_5_RUN_NATIVE=1 to run the real native terminal harness")
class D15TerminalNativeIntegrationTests(unittest.TestCase):
    def test_native_harness_qualifies_the_reachable_rows(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "native-terminal-observations.v1.json"
            result = subprocess.run(
                ["node", "native_terminal_harness.mjs", "run", "--out", str(out)],
                cwd=TERMINAL, capture_output=True, text=True, timeout=600)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            observations = json.loads(out.read_text(encoding="utf-8"))
        by_id = {item["id"]: item["result"] for item in observations["scenarios"]}
        for row_id in ("page-refresh", "browser-disconnect", "frontend-restart", "gateway-restart"):
            self.assertEqual(by_id[row_id], "PASS", row_id)
        self.assertEqual(by_id["adapter-restart"], "BLOCKED")
        self.assertEqual(by_id["dsh-runtime-restart"], "BLOCKED")
        self.assertEqual(by_id["host-reboot"], "NOT_RUN")
        self.assertTrue(all(item["rejected"] for item in observations["negatives"]))
        self.assertEqual(observations["cleanup"]["temp_root_removed"], True)

    def test_native_observer_verdict_is_truthful(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "observations.json"
            verdict = Path(tmp) / "verdict.json"
            run = subprocess.run(
                ["node", "native_terminal_harness.mjs", "run", "--out", str(obs)],
                cwd=TERMINAL, capture_output=True, text=True, timeout=600)
            self.assertEqual(run.returncode, 0, run.stderr[-2000:])
            result = subprocess.run(
                [sys.executable, "observer.py", "--observations", str(obs), "--out", str(verdict)],
                cwd=TERMINAL, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 1, result.stdout[-2000:])
            data = json.loads(verdict.read_text(encoding="utf-8"))
        self.assertFalse(data["all_pass"])
        self.assertTrue(data["format_valid"])
        self.assertEqual(data["required_coverage"]["adapter-restart"], "BLOCKED")
        self.assertEqual(data["required_coverage"]["dsh-runtime-restart"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
