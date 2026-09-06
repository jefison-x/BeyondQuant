import copy
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

from tests.dsh_upgrade import live_stack
from tests.dsh_upgrade.fake_hub import Sink, digest


class LiveIsolationTests(unittest.TestCase):
    def test_bounded_runner_cleans_after_success_startup_or_probe_failure(self):
        value = live_stack.manifest("byq-u5-isolation-test", "dsh-0.1.2rc1", 18210)
        for failure_at in (None, 0, 1):
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if len(calls) - 1 == failure_at:
                    raise subprocess.CalledProcessError(1, command)

            with patch.object(live_stack.subprocess, "run", side_effect=run), patch.object(live_stack, "preflight") as check:
                if failure_at is None:
                    live_stack.run_journey(Path("test.json"), value, ["synthetic-up"], {})
                else:
                    with self.assertRaises(subprocess.CalledProcessError):
                        live_stack.run_journey(Path("test.json"), value, ["synthetic-up"], {})
                self.assertEqual(calls[-1][-2:], ["down", "--volumes"])
                self.assertIn(value["name"], calls[-1])
                check.assert_called_with(Path("test.json"), require_healthy=False)

    def test_model_key_reader_accepts_only_one_literal_field(self):
        key = "synthetic-model-key-only"
        for content in (f'DEEPSEEK_API_KEY="{key}"\nOTHER=ignored', f"DEEPSEEK_API_KEY={key}\n"):
            with patch.object(Path, "open", mock_open(read_data=content)):
                self.assertEqual(live_stack.model_key_from_env_file(Path("unused")), key)
        for content in ("OTHER=value", "DEEPSEEK_API_KEY=$(command)",
                        "DEEPSEEK_API_KEY=${OTHER}", f"DEEPSEEK_API_KEY={key}\nDEEPSEEK_API_KEY={key}"):
            with patch.object(Path, "open", mock_open(read_data=content)):
                with self.assertRaises(ValueError):
                    live_stack.model_key_from_env_file(Path("unused"))

    def test_actual_container_drift_is_rejected_before_model_calls(self):
        manifest = live_stack.manifest("byq-u5-isolation-test", "dsh-0.1.2rc1", 18210)
        containers = []
        for name, spec in manifest["services"].items():
            ports = {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18210"}]} if name == "frontend" else {}
            containers.append({
                "Config": {"Labels": {"com.docker.compose.service": name},
                           "Env": [f"{key}={value}" for key, value in spec.get("environment", {}).items()]},
                "State": {"Running": True, "Health": {"Status": "healthy"}},
                "HostConfig": {"Privileged": False},
                "NetworkSettings": {"Networks": {manifest["networks"][key]["name"]: {} for key in spec["networks"]}, "Ports": ports},
                "Mounts": [{"Name": manifest["volumes"][entry.split(":")[0]]["name"], "Destination": entry.split(":")[1]} for entry in spec.get("volumes", [])],
                "Image": "sha256:synthetic",
            })

        def inspect(*args):
            if args[0] == "inspect":
                return actual
            spec = next(value for value in manifest["networks"].values() if value["name"] == args[-1])
            return [{"Internal": spec["internal"], "Labels": spec["labels"]}]

        changes = (
            lambda c: c["NetworkSettings"]["Networks"].update({"production-network": {}}),
            lambda c: c["Config"]["Env"].append("TUSHARE_TOKEN=unexpected"),
            lambda c: c["HostConfig"].update(Privileged=True),
            lambda c: c["Mounts"].append({"Name": None, "Destination": "/production"}),
            lambda c: c["NetworkSettings"]["Ports"].update({"8800/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18211"}]}),
        )
        with patch.object(Path, "read_text", return_value=json.dumps(manifest)), patch.object(
            live_stack.subprocess, "check_output", return_value=" ".join(str(i) for i in range(8))
        ), patch.object(live_stack, "docker_json", side_effect=inspect):
            actual = copy.deepcopy(containers)
            self.assertEqual(live_stack.preflight(Path("unused"))["release"], "dsh-0.1.2rc1")
            for change in changes:
                actual = copy.deepcopy(containers)
                relay = next(c for c in actual if c["Config"]["Labels"]["com.docker.compose.service"] == "feedback-hub-relay")
                change(relay)
                with self.assertRaises(ValueError):
                    live_stack.preflight(Path("unused"))

    def test_fake_hub_validates_hash_and_deduplicates_without_retaining_content(self):
        sink = Sink()
        snapshot = {"schema_version": "submitted-feedback-snapshot.v1", "public_content": {"title": "U5 G6 synthetic"}}
        body = {"schema_version": "central-feedback-intake.v1", "installation_id": "synthetic-installation",
                "event_id": "synthetic-event", "snapshot_hash": digest(snapshot), "snapshot": snapshot}
        receipt = sink.accept(body)
        self.assertEqual(sink.accept(body), receipt)
        self.assertEqual(sink.evidence()["received"], 1)
        self.assertEqual(sink.evidence()["attempts"], 2)
        self.assertEqual(sink.evidence()["published"], 0)
        self.assertNotIn("public_content", json.dumps(sink.receipts))
        body["snapshot_hash"] = "a" * 64
        with self.assertRaises(ValueError):
            sink.accept(body)

    def test_poisoned_environment_cannot_select_production_resources(self):
        poison = {"COMPOSE_FILE": "compose.yml", "COMPOSE_PROJECT_NAME": "beyondquant",
                  "BYQ_FEEDBACK_HUB_URL": "https://real.example", "TUSHARE_TOKEN": "secret",
                  "BYQ_DATABASE_URL": "production", "DEEPSEEK_API_KEY": "model-test-key",
                  "PATH": "/usr/bin", "HOME": "/test"}
        env = live_stack.compose_environment(poison)
        self.assertEqual(set(env), {"PATH", "HOME", "DEEPSEEK_API_KEY"})
        for release in live_stack.RELEASES:
            with patch.dict("os.environ", poison, clear=True):
                manifest = live_stack.manifest("byq-u5-isolation-test", release, 18210)
            serialized = json.dumps(manifest)
            self.assertNotIn("real.example", serialized)
            self.assertNotIn("production", serialized)
            self.assertNotIn("model-test-key", serialized)
            self.assertEqual(set(manifest["services"]), live_stack.SERVICES)
            self.assertTrue(manifest["networks"]["product"]["internal"])
            for service, config in manifest["services"].items():
                expected = ["product", "model"] if service == "runtime-adapter" else ["product", "edge"] if service == "frontend" else ["product"]
                self.assertEqual(config["networks"], expected)
                self.assertEqual(bool(config.get("ports")), service == "frontend")
            self.assertEqual(manifest["services"]["feedback-hub-relay"]["environment"]["BYQ_FEEDBACK_HUB_URL"], "http://fake-hub:8800")

    def test_rejects_broad_resource_names(self):
        for scope in ("beyondquant", "byq-u5-", "byq-u5-x/../prod", "byq-u5-$(pwd)"):
            with self.assertRaises(ValueError):
                live_stack.manifest(scope, "dsh-0.1.2rc1", 18210)

    def test_preflight_rejects_runtime_drift(self):
        manifest = live_stack.manifest("byq-u5-isolation-test", "dsh-0.1.2rc1", 18210)
        live_stack.validate_manifest(manifest)
        for change in (
            lambda m: m["services"]["feedback-hub-relay"]["environment"].update(BYQ_FEEDBACK_HUB_URL="https://real.example"),
            lambda m: m["services"]["feedback-hub-relay"].update(networks=["product", "model"]),
            lambda m: m["networks"]["product"].update(internal=False),
            lambda m: m["services"].update({"feedback-publisher": {}}),
            lambda m: m["volumes"]["postgres"].update(name="beyondquant-postgres-data"),
            lambda m: m["services"]["backend"]["environment"].update(TUSHARE_TOKEN="secret"),
        ):
            mutated = copy.deepcopy(manifest)
            change(mutated)
            with self.assertRaises(ValueError):
                live_stack.validate_manifest(mutated)


if __name__ == "__main__":
    unittest.main()
