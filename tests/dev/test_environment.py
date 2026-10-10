"""Focused safety tests for the isolated developer lifecycle."""
import importlib.util
import json
from pathlib import Path
import stat
import sys
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

    def test_compose_config_requires_authoritative_acp_build_and_workspace_mount(self):
        selection = env.load_authoritative_version(env.ROOT)
        resolved = env.build_environment(selection)
        workspace = "workspace_test000000000000000000000000000"
        leaf = f"{resolved['BYQ_DSH_BUILD_SESSION_ROOT']}/{workspace}"
        dockerfile = f"services/runtime-adapter/Dockerfile.acp-{selection['release_id'].removeprefix('dsh-v')}-candidate"
        mount = {"source": "byq_acp_product_sessions", "target": leaf}
        payload = {"services": {
            "runtime-adapter": {
                "build": {"dockerfile": dockerfile},
                "environment": {
                    "BYQ_DSH_COMPATIBILITY_RELEASE": selection["compatibility_family"],
                    "DSH_SESSION_ROOT": resolved["BYQ_DSH_BUILD_SESSION_ROOT"],
                    "BYQ_DSH_PROVIDER": "opencode-go-chat",
                    "BYQ_DSH_MODEL": "deepseek-v4.1-flash",
                    "BYQ_ACP_PRODUCT_SLOT_BINDINGS": json.dumps({workspace: {
                        "socket_path": "/run/byq-acp-product-runner/control.sock",
                        "control_secret_env": "BYQ_ACP_PRODUCT_SLOT_PRIMARY_SECRET",
                    }}),
                },
                "volumes": [mount],
            },
            "acp-product-runner": {
                "environment": {"BYQ_ACP_PRODUCT_WORKSPACE_ID": workspace},
                "volumes": [mount],
            },
        }}
        values = {"BYQ_ACP_PRODUCT_WORKSPACE_ID": workspace}
        with patch.object(env, "call", return_value=CompletedProcess([], 0, json.dumps(payload), "")):
            env.validated_config(values)
        payload["services"]["runtime-adapter"]["build"]["dockerfile"] = "services/runtime-adapter/Dockerfile.post-u8-candidate"
        with patch.object(env, "call", return_value=CompletedProcess([], 0, json.dumps(payload), "")):
            with self.assertRaisesRegex(env.DevError, "stale Runtime Adapter"):
                env.validated_config(values)

    def test_managed_dev_compose_uses_the_resolver_and_shared_default_overlay(self):
        args = env.compose_args("config")
        self.assertEqual(args[:4], [sys.executable, str(env.ROOT / "scripts/dsh/acp_build.py"), "--", "docker"])
        base = str(env.ROOT / "compose.yml")
        override = str(env.ROOT / "compose.override.yml")
        dev = str(env.ROOT / "compose.dev.yml")
        self.assertIn(base, args)
        self.assertIn(override, args)
        self.assertIn(dev, args)
        self.assertLess(args.index(base), args.index(override))
        self.assertLess(args.index(override), args.index(dev))

    def test_workspace_binding_is_explicit_and_required_for_start(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env.dev"
            scope = env.scope()
            values = {
                "BYQ_DEV_SCOPE": scope, "COMPOSE_PROJECT_NAME": scope,
                "POSTGRES_USER": "byq_app", "POSTGRES_DB": "byq_domain",
                "POSTGRES_PASSWORD": "opaque-db-password",
                "BYQ_DATABASE_URL": "postgresql+psycopg://byq_app:opaque-db-password@postgres:5432/byq_domain",
            }
            for key in (
                "BYQ_MCP_TOKEN", "BYQ_PRODUCT_TOKEN", "BYQ_RUNTIME_AUTHORITY_TOKEN",
                "BYQ_RUNTIME_JUDGMENT_TOKEN", "BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET",
                "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET", "BYQ_MCP_ACP_DISCOVERY_TOKEN",
                "BYQ_MCP_ACP_SIGNING_KEY", "BYQ_MCP_BACKEND_PROOF_TOKEN",
                "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY", "BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN",
                "BYQ_GATEWAY_SERVICE_TOKEN", "BYQ_BOOTSTRAP_ADMIN_PASSWORD",
                "BYQ_CREDENTIAL_KEYRING",
            ):
                values[key] = "opaque-test-value"
            path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
            path.chmod(0o600)
            with patch.object(env, "ENV_FILE", path):
                with self.assertRaisesRegex(env.DevError, "trusted personal Workspace binding"):
                    env.local_env()
                optional = env.local_env(require_workspace=False)
                self.assertEqual(optional.get("BYQ_ACP_PRODUCT_WORKSPACE_ID", ""), "")
                path.write_text(path.read_text() + "BYQ_ACP_PRODUCT_WORKSPACE_ID=workspace_owned123\n")
                self.assertEqual(env.local_env()["BYQ_ACP_PRODUCT_WORKSPACE_ID"], "workspace_owned123")

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
                values = env.local_env(require_workspace=False)
                self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
                self.assertEqual(values["COMPOSE_PROJECT_NAME"], env.scope())
                self.assertIn("@postgres:5432/byq_domain", values["BYQ_DATABASE_URL"])
                self.assertNotEqual(values["BYQ_PRODUCT_TOKEN"], "dev-product-token-change-me")
                self.assertTrue(values["BYQ_RUNTIME_JUDGMENT_TOKEN"])
                self.assertTrue(values["BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET"])
                self.assertEqual(values.get("BYQ_ACP_PRODUCT_WORKSPACE_ID", ""), "")
                self.assertNotIn("BYQ_FEEDBACK_PUBLISHER_TOKEN", values)
                self.assertIn("BYQ_FEEDBACK_HUB_RELAY_TOKEN", values)
                before = config.read_bytes()
                env.init()
                self.assertEqual(config.read_bytes(), before)

    def test_clean_preserves_legacy_sdk_session_volume(self):
        project = env.scope()
        legacy = f"{project}-dsh-sessions"
        targets = {"containers": [], "volumes": [f"{project}-domain-state"],
                   "preserved_volumes": [legacy], "networks": []}
        remaining = {"containers": [], "volumes": [], "preserved_volumes": [legacy], "networks": []}
        with patch.object(env, "inventory", side_effect=[targets, remaining]), \
             patch.object(env, "call", return_value=CompletedProcess([], 0, "", "")) as call, \
             patch.object(env, "docker_lines", return_value=[]), \
             patch.object(env, "docker_json", return_value=[{"Labels": {"com.docker.compose.project": project}}]):
            env.clean({}, True)
        commands = [item.args[0] for item in call.call_args_list]
        self.assertIn(["docker", "volume", "rm", f"{project}-domain-state"], commands)
        self.assertNotIn(["docker", "volume", "rm", legacy], commands)

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

    def test_reset_preserves_legacy_sdk_sessions_and_only_cleans_trace_volume(self):
        project = env.scope()
        with patch.object(env, "inventory", return_value={"containers": [], "volumes": [], "networks": []}), \
             patch.object(env, "call", return_value=CompletedProcess([], 0, "", "")) as call, \
             patch.object(env, "docker_json", return_value=None) as inspect, \
             patch.object(env, "docker_lines", return_value=[]):
            env.reset({"BYQ_DEV_SCOPE": project})
        commands = [item.args[0] for item in call.call_args_list]
        self.assertEqual(commands[0][-2:], ["down", "--remove-orphans"])
        self.assertIn("postgres", commands[1])
        self.assertIn("app.workspace_reset_cli", commands[3])
        self.assertIn("workspace-reset-gc", commands[4])
        self.assertEqual(commands[5][-2:], ["down", "--remove-orphans"])
        self.assertIn("gateway", commands[6])
        self.assertFalse(any("volume rm" in " ".join(command) for command in commands))
        self.assertFalse(any("dsh-sessions" in " ".join(command) for command in commands))
        self.assertTrue(inspect.called)

    def test_reset_rejects_unowned_runtime_volume_before_removal(self):
        project = env.scope()
        unowned = {"Name": f"{project}-workflow-traces",
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
