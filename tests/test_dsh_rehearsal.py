import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.dsh_upgrade.rehearsal import Rehearsal, OLD, NEW
from tests.dsh_upgrade.live_stack import validate_manifest


class RehearsalTests(unittest.TestCase):
    def test_idle_followup_uses_normal_product_turn_not_resume(self):
        runner = Rehearsal(Path("/tmp/byq-u6-abcdefgh"), {})
        calls = []

        class Client:
            def call(self, method, path, *payload):
                calls.append((method, path))
                return {"messages": [{"role": "assistant", "content": "synthetic completed answer"}]}

        with patch.object(runner, "check"), patch.object(runner, "wait_answer"), \
                patch("tests.dsh_upgrade.rehearsal.counts", return_value={"feedback": 1}):
            runner.followup(Client(), "conversation-synthetic")
        self.assertEqual(calls, [("GET", "/v1/agent/sessions/conversation-synthetic"),
                                  ("POST", "/v1/agent/sessions/conversation-synthetic/turns")])

    def test_only_scoped_synthetic_directory_can_be_prepared(self):
        self.assertEqual(Rehearsal(Path("/tmp/byq-u6-5_lofi4s"), {}).scope, "byq-u5-u6-5-lofi4s")
        for scope in ("beyondquant", "main", "../escape", "local-u6-test;command"):
            with self.assertRaises(ValueError):
                Rehearsal(Path("/tmp/byq-u6-abcdefgh"), {}, scope)
        for path in ("/", "/tmp", "/home/jefison/projects/BeyondQuant", "/tmp/byq-u6-abcdefgh/.."):
            with self.assertRaises(ValueError):
                Rehearsal(Path(path), {})
        with tempfile.TemporaryDirectory(prefix="byq-u6-") as temporary:
            runner = Rehearsal(Path(temporary), {})
            runner.prepare()
            self.assertEqual(runner.gate.read_text(), "closed\n")
            for path in runner.files.values():
                validate_manifest(json.loads(path.read_text()))
            self.assertEqual((Path(temporary) / "backups").stat().st_mode & 0o777, 0o700)

    def test_invalid_accounting_aborts_before_switch(self):
        runner = Rehearsal(Path("/tmp/byq-u6-abcdefgh"), {})
        with patch.object(runner, "check"), patch("tests.dsh_upgrade.rehearsal.set_state") as state, \
                patch.object(runner, "runtime", return_value={"sessions": {"active_prompts": False}}), \
                patch.object(runner, "run_command") as command:
            with self.assertRaises(AssertionError):
                runner.switch(NEW)
            state.assert_called_once_with(runner.gate, "closed", timeout=30)
            command.assert_not_called()
            self.assertEqual(runner.release, OLD)

    def test_cleanup_requires_isolation_check_and_detects_stopped_containers(self):
        runner = Rehearsal(Path("/tmp/byq-u6-abcdefgh"), {})
        with patch.object(Path, "exists", return_value=True), \
                patch("tests.dsh_upgrade.rehearsal.live_stack.preflight", side_effect=ValueError("drift")), \
                patch.object(runner, "run_command") as command:
            with self.assertRaises(ValueError):
                runner.cleanup()
            command.assert_not_called()
        with patch.object(Path, "exists", return_value=False), \
                patch("tests.dsh_upgrade.rehearsal.subprocess.check_output", return_value="stopped-test-container") as query:
            with self.assertRaises(AssertionError):
                runner.cleanup()
            self.assertIn("-a", query.call_args.args[0])

    def test_additional_scenarios_are_fixed_bounded_and_fail_without_retry(self):
        runner = Rehearsal(Path("/tmp/byq-u6-abcdefgh"), {})
        runner.result["domain_fixture"] = {"backtest_job_id": "backtest_" + "a" * 32}
        from types import SimpleNamespace
        outputs = [SimpleNamespace(returncode=0, stdout=json.dumps({"scenario": name, "result": "PASS"}))
                   for name in ("G1", "G2", "G3", "G4")]
        with patch.object(runner, "switch") as switch, patch.object(runner, "check"), \
                patch.object(runner, "drain"), patch("tests.dsh_upgrade.rehearsal.emit"), \
                patch("tests.dsh_upgrade.rehearsal.live_stack.compose_environment",
                      return_value={"PATH": "/usr/bin", "DEEPSEEK_API_KEY": "test-sentinel-not-a-secret"}), \
                patch("tests.dsh_upgrade.rehearsal.subprocess.run", side_effect=outputs) as run:
            runner.qualify_remaining_scenarios()
            self.assertEqual([call.args[0] for call in switch.call_args_list], [NEW, OLD])
            self.assertEqual(len(runner.result["additional_model_scenarios"]), 4)
            for index, call in enumerate(run.call_args_list):
                self.assertEqual("--approve" in call.args[0], index == 2)
                self.assertEqual("--backtest-id" in call.args[0], index == 1)
                self.assertEqual(call.kwargs["timeout"], 1020)
                self.assertNotIn("DEEPSEEK_API_KEY", call.kwargs["env"])
        with patch.object(runner, "switch"), patch.object(runner, "check"), \
                patch("tests.dsh_upgrade.rehearsal.emit"), \
                patch("tests.dsh_upgrade.rehearsal.subprocess.run",
                      return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaises(AssertionError):
                runner.qualify_remaining_scenarios()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(runner.result["additional_model_scenarios"][0]["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
