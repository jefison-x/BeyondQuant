"""Focused safety tests for the isolated developer lifecycle."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/environment.py"
spec = importlib.util.spec_from_file_location("byq_dev_environment", SCRIPT)
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)


class DevEnvironmentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
