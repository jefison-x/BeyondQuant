"""Focused safety tests for the isolated developer lifecycle."""
import importlib.util
import json
from pathlib import Path
import stat
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/environment.py"
spec = importlib.util.spec_from_file_location("byq_dev_environment", SCRIPT)
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)


class DevEnvironmentTests(unittest.TestCase):
    def test_backtest_profiles_include_the_optimization_worker(self):
        for profile in ("backtest", "full"):
            self.assertIn("backtest-worker", env.SERVICES[profile])
            self.assertIn("optimization-worker", env.SERVICES[profile])

    def test_compose_config_requires_current_adapter_build(self):
        payload = {"services": {"runtime-adapter": {"build": {"dockerfile": env.CURRENT_DSH_DOCKERFILE}}}}
        with patch.object(env, "call", return_value=CompletedProcess([], 0, json.dumps(payload), "")):
            env.validated_config({})
        payload["services"]["runtime-adapter"]["build"]["dockerfile"] = "services/runtime-adapter/Dockerfile.post-u8-candidate"
        with patch.object(env, "call", return_value=CompletedProcess([], 0, json.dumps(payload), "")):
            with self.assertRaisesRegex(env.DevError, "stale Runtime Adapter"):
                env.validated_config({})

    def test_worktree_scope_is_deterministic_and_distinct(self):
        with patch.object(env, "ROOT", Path("/tmp/worktree-a")):
            first = env.scope()
            self.assertEqual(first, env.scope())
        with patch.object(env, "ROOT", Path("/tmp/worktree-b")):
            second = env.scope()
        self.assertRegex(first, r"^byq-dev-[0-9a-f]{10}$")
        self.assertNotEqual(first, second)

    def test_existing_config_must_match_scope_and_forbid_shared_volume(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env.dev"
            path.write_text("BYQ_DEV_SCOPE=prod\nCOMPOSE_PROJECT_NAME=prod\n")
            path.chmod(0o600)
            with patch.object(env, "ENV_FILE", path):
                with self.assertRaisesRegex(env.DevError, "different worktree"):
                    env.local_env()
                path.write_text(
                    f"BYQ_DEV_SCOPE={env.scope()}\nCOMPOSE_PROJECT_NAME={env.scope()}\n"
                    "BYQ_POSTGRES_VOLUME_EXTERNAL=true\n"
                )
                with self.assertRaisesRegex(env.DevError, "external PostgreSQL"):
                    env.local_env()
                path.write_text(
                    f"BYQ_DEV_SCOPE={env.scope()}\nCOMPOSE_PROJECT_NAME={env.scope()}\n"
                    "POSTGRES_USER=byq_app\nPOSTGRES_DB=byq_domain\nPOSTGRES_PASSWORD=local\n"
                    "BYQ_DATABASE_URL=postgresql+psycopg://byq_app:local@outside:5432/byq_domain\n"
                )
                with self.assertRaisesRegex(env.DevError, "database URL"):
                    env.local_env()
                path.chmod(0o644)
                with self.assertRaisesRegex(env.DevError, "group or others"):
                    env.local_env()

    def test_clean_preview_never_mutates_and_apply_is_exact(self):
        targets = {"containers": ["container-1"], "volumes": ["volume-1"], "networks": ["network-1"]}
        with patch.object(env, "inventory", return_value=targets), patch.object(env, "call") as call:
            env.clean({}, False)
            call.assert_not_called()
        empty = {"containers": [], "volumes": [], "networks": []}
        with patch.object(env, "inventory", side_effect=[targets, empty]), \
             patch.object(env, "call") as call, \
             patch.object(env, "docker_lines", return_value=[]), \
             patch.object(env, "docker_json", return_value=[{"Labels": {"com.docker.compose.project": env.scope()}}]):
            call.return_value.returncode = 0
            env.clean({}, True)
            commands = [c.args[0] for c in call.call_args_list]
            self.assertIn("down", commands[0])
            self.assertNotIn("--volumes", commands[0])
            self.assertEqual(commands[1], ["docker", "volume", "rm", "volume-1"])
            self.assertEqual(len(commands), 2)

    def test_init_creates_private_matching_config_from_template(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            template = root / ".env.example"
            template.write_text("POSTGRES_DB=byq_domain\nPOSTGRES_USER=byq_app\nBYQ_MCP_TOKEN=placeholder\n")
            config = root / ".env.dev"
            with patch.object(env, "ROOT", root), patch.object(env, "TEMPLATE", template), \
                 patch.object(env, "ENV_FILE", config), patch.object(env, "validated_config"):
                env.init()
                values = env.local_env()
                self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
                self.assertEqual(values["COMPOSE_PROJECT_NAME"], env.scope())
                self.assertIn("@postgres:5432/byq_domain", values["BYQ_DATABASE_URL"])
                self.assertNotEqual(values["BYQ_PRODUCT_TOKEN"], "dev-product-token-change-me")
                before = config.read_bytes()
                env.init()
                self.assertEqual(config.read_bytes(), before)

    def test_docker_unavailable_is_not_reported_as_missing(self):
        from subprocess import CompletedProcess
        with patch.object(env, "call", return_value=CompletedProcess([], 1, "", "Cannot connect to Docker daemon")):
            with self.assertRaisesRegex(env.DevError, "Docker inventory failed"):
                env.docker_json(["volume", "inspect", "exact-volume"], {}, absent_ok=True)

    def test_inventory_rejects_unowned_exact_volume(self):
        project = env.scope()
        name = f"{project}-postgres-data"
        def fake_lines(args, _values):
            return []
        def fake_json(args, _values, absent_ok=False):
            if args[:3] == ["volume", "inspect", name]:
                return [{"Name": name, "Labels": {"com.docker.compose.project": "other"}}]
            return None
        with patch.object(env, "docker_lines", side_effect=fake_lines), \
             patch.object(env, "docker_json", side_effect=fake_json):
            with self.assertRaisesRegex(env.DevError, "unowned project volume"):
                env.inventory({})

    def test_reset_stops_writers_before_workspace_cleanup_and_only_removes_owned_runtime_volumes(self):
        project = env.scope()
        owned = {"Name": f"{project}-dsh-sessions",
                 "Labels": {"com.docker.compose.project": project}}
        with patch.object(env, "inventory", return_value={"containers": [], "volumes": [], "networks": []}), \
             patch.object(env, "call", return_value=CompletedProcess([], 0, "", "")) as call, \
             patch.object(env, "docker_json", side_effect=[[owned], None]), \
             patch.object(env, "docker_lines", return_value=[]):
            env.reset({"BYQ_DEV_SCOPE": project})
        commands = [item.args[0] for item in call.call_args_list]
        self.assertEqual(commands[0][-2:], ["down", "--remove-orphans"])
        self.assertIn("postgres", commands[1])
        self.assertIn("app.workspace_reset_cli", commands[3])
        self.assertIn("workspace-reset-gc", commands[4])
        self.assertEqual(commands[5][-2:], ["down", "--remove-orphans"])
        self.assertEqual(commands[6], ["docker", "volume", "rm", f"{project}-dsh-sessions"])
        self.assertIn("gateway", commands[7])
        self.assertFalse(any("postgres-data" in " ".join(command) for command in commands))

    def test_reset_rejects_unowned_runtime_volume_before_removal(self):
        project = env.scope()
        unowned = {"Name": f"{project}-dsh-sessions",
                   "Labels": {"com.docker.compose.project": "another-project"}}
        with patch.object(env, "inventory", return_value={"containers": [], "volumes": [], "networks": []}), \
             patch.object(env, "call", return_value=CompletedProcess([], 0, "", "")), \
             patch.object(env, "docker_json", return_value=[unowned]):
            with self.assertRaisesRegex(env.DevError, "not owned"):
                env.reset({"BYQ_DEV_SCOPE": project})

    def test_runtime_only_reset_never_calls_workspace_cleanup(self):
        with patch.object(env, "inventory", return_value={"containers": [], "volumes": [], "networks": []}), \
             patch.object(env, "call", return_value=CompletedProcess([], 0, "", "")) as call, \
             patch.object(env, "docker_json", return_value=None):
            env.reset({"BYQ_DEV_SCOPE": env.scope()}, runtime_only=True)
        commands = [item.args[0] for item in call.call_args_list]
        self.assertEqual(len(commands), 4)
        self.assertFalse(any("app.workspace_reset_cli" in command for command in commands))

    def test_workspace_reset_failure_leaves_runtime_volumes_untouched(self):
        calls = [CompletedProcess([], 0, "", "") for _ in range(3)]
        calls.append(CompletedProcess([], 1, "", ""))
        with patch.object(env, "inventory", return_value={"containers": [], "volumes": [], "networks": []}), \
             patch.object(env, "call", side_effect=calls) as call, \
             patch.object(env, "docker_json") as inspect:
            with self.assertRaisesRegex(env.DevError, "workspace reset failed"):
                env.reset({"BYQ_DEV_SCOPE": env.scope()})
        inspect.assert_not_called()
        self.assertEqual(len(call.call_args_list), 4)

    def test_object_cleanup_failure_is_retryable_without_runtime_volume_removal(self):
        calls = [CompletedProcess([], 0, "", "") for _ in range(4)]
        calls.append(CompletedProcess([], 1, "", ""))
        with patch.object(env, "inventory", return_value={"containers": [], "volumes": [], "networks": []}), \
             patch.object(env, "call", side_effect=calls) as call, \
             patch.object(env, "docker_json") as inspect:
            with self.assertRaisesRegex(env.DevError, "object cleanup failed"):
                env.reset({"BYQ_DEV_SCOPE": env.scope()})
        inspect.assert_not_called()
        self.assertEqual(len(call.call_args_list), 5)


if __name__ == "__main__":
    unittest.main()
