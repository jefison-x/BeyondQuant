"""Offline Compose contract for a test-only second static ACP workspace slot."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "compose.yml"
DEFAULT_OVERRIDE = ROOT / "compose.override.yml"
QUALIFICATION = ROOT / "tests/fixtures/compose.acp-two-user-qualification.yml"
SECONDARY_WORKSPACE = "workspace_" + "b" * 32


def _fake_environment() -> dict[str, str]:
    """Only return synthetic interpolation values; never inherit local secrets."""
    return {
        "PATH": os.defpath,
        "COMPOSE_PROJECT_NAME": "acp-two-user-qualification-test",
        "BYQ_PRODUCT_TOKEN": "test-only-product-token",
        "BYQ_RUNTIME_AUTHORITY_TOKEN": "test-only-runtime-authority",
        "BYQ_RUNTIME_JUDGMENT_TOKEN": "test-only-runtime-judgment",
        "BYQ_ACP_PRODUCT_WORKSPACE_ID": "workspace_" + "a" * 32,
        "BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET": "test-only-primary-runner-secret",
        "BYQ_QUAL_ACP_PRODUCT_SECONDARY_WORKSPACE_ID": SECONDARY_WORKSPACE,
        "BYQ_QUAL_ACP_PRODUCT_SECONDARY_SECRET": "test-only-secondary-runner-secret",
        "BYQ_MCP_ACP_DISCOVERY_TOKEN": "test-only-acp-discovery-token",
        "BYQ_MCP_ACP_SIGNING_KEY": "test-only-acp-signing-key",
        "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY": "test-only-judgment-signing-key",
        "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET": "test-only-judgment-runner-secret",
        "BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN": "test-only-judgment-proof-token",
        "BYQ_MCP_BACKEND_PROOF_TOKEN": "test-only-backend-proof-token",
        "BYQ_GATEWAY_SERVICE_TOKEN": "test-only-gateway-token",
        "BYQ_MCP_TOKEN": "test-only-mcp-token",
    }


class AcpTwoUserQualificationComposeTests(unittest.TestCase):
    def _compose_command(self, docker: str, *, include_qualification: bool) -> list[str]:
        command = [
            sys.executable, str(ROOT / "scripts/dsh/acp_build.py"), "--",
            docker, "compose", "--env-file", "/dev/null",
            "--project-directory", str(ROOT),
            "-f", str(BASE), "-f", str(DEFAULT_OVERRIDE),
        ]
        if include_qualification:
            command.extend(("-f", str(QUALIFICATION)))
        command.extend(("config", "--format", "json"))
        return command

    def _config(
        self, *, include_qualification: bool = True, omit: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        docker = shutil.which("docker", path=os.defpath)
        if docker is None:
            self.skipTest("Docker Compose is unavailable for merged-config validation")
        version = subprocess.run(
            [docker, "compose", "version"], capture_output=True, check=False,
            env={"PATH": os.defpath}, timeout=10,
        )
        if version.returncode != 0:
            self.skipTest("Docker Compose plugin is unavailable for merged-config validation")
        environment = _fake_environment()
        if omit is not None:
            environment.pop(omit)
        return subprocess.run(
            self._compose_command(docker, include_qualification=include_qualification),
            cwd=ROOT, env=environment, capture_output=True, text=True,
            check=False, timeout=30,
        )

    def test_second_static_slot_is_isolated_and_keeps_the_product_role_profile(self) -> None:
        baseline_result = self._config(include_qualification=False)
        self.assertEqual(baseline_result.returncode, 0,
                         "default Compose chain rejected the synthetic baseline")
        result = self._config()
        self.assertEqual(result.returncode, 0, "Compose config rejected the synthetic fixture")
        baseline = json.loads(baseline_result.stdout)
        config = json.loads(result.stdout)
        services = config["services"]
        baseline_services = baseline["services"]
        adapter = services["runtime-adapter"]
        baseline_adapter = baseline_services["runtime-adapter"]
        primary = services["acp-product-runner"]
        baseline_primary = baseline_services["acp-product-runner"]
        secondary = services["acp-product-runner-secondary"]
        bindings = json.loads(adapter["environment"]["BYQ_ACP_PRODUCT_SLOT_BINDINGS"])
        baseline_bindings = json.loads(
            baseline_adapter["environment"]["BYQ_ACP_PRODUCT_SLOT_BINDINGS"]
        )
        primary_workspace = _fake_environment()["BYQ_ACP_PRODUCT_WORKSPACE_ID"]
        primary_socket = "/run/byq-acp-product-runner/control.sock"
        primary_secret_name = "BYQ_ACP_PRODUCT_SLOT_PRIMARY_SECRET"
        self.assertEqual(baseline_bindings, {
            primary_workspace: {
                "socket_path": primary_socket,
                "control_secret_env": primary_secret_name,
            },
        })
        self.assertEqual(bindings[primary_workspace], baseline_bindings[primary_workspace])
        self.assertEqual(primary["environment"]["BYQ_ACP_PRODUCT_WORKSPACE_ID"],
                         primary_workspace)
        self.assertEqual(primary["environment"]["BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET"],
                         adapter["environment"][primary_secret_name])
        self.assertEqual(primary, baseline_primary)
        self.assertEqual(adapter["environment"][primary_secret_name],
                         baseline_adapter["environment"][primary_secret_name])

        root = adapter["environment"]["DSH_SESSION_ROOT"]
        primary_session_target = f"{root}/{primary_workspace}"
        primary_runner_mounts = {
            item["source"]: (item["target"], item["type"])
            for item in primary["volumes"]
        }
        self.assertEqual(primary_runner_mounts, {
            "byq_acp_product_sessions": (primary_session_target, "volume"),
            "byq_acp_product_state": ("/var/lib/byq/acp-product-runner-state", "volume"),
            "byq_acp_product_control": ("/run/byq-acp-product-runner", "volume"),
        })
        baseline_adapter_mounts = {
            (item["source"], item["target"], item["type"])
            for item in baseline_adapter["volumes"]
        }
        adapter_mounts = {
            (item["source"], item["target"], item["type"])
            for item in adapter["volumes"]
        }
        for source, target in (
            ("byq_acp_product_sessions", primary_session_target),
            ("byq_acp_product_control", "/run/byq-acp-product-runner"),
        ):
            self.assertIn((source, target, "volume"), baseline_adapter_mounts)
            self.assertIn((source, target, "volume"), adapter_mounts)

        self.assertEqual(set(bindings), {primary_workspace, SECONDARY_WORKSPACE})
        self.assertEqual(
            bindings[SECONDARY_WORKSPACE],
            {
                "socket_path": "/run/byq-acp-product-runner-secondary/control.sock",
                "control_secret_env": "BYQ_ACP_PRODUCT_SLOT_SECONDARY_SECRET",
            },
        )
        self.assertNotEqual(bindings[primary_workspace]["socket_path"],
                            bindings[SECONDARY_WORKSPACE]["socket_path"])
        self.assertEqual(
            adapter["environment"]["BYQ_ACP_PRODUCT_SLOT_SECONDARY_SECRET"],
            "test-only-secondary-runner-secret",
        )
        self.assertNotEqual(adapter["environment"]["BYQ_ACP_PRODUCT_SLOT_PRIMARY_SECRET"],
                            adapter["environment"]["BYQ_ACP_PRODUCT_SLOT_SECONDARY_SECRET"])
        self.assertNotEqual(
            adapter["environment"]["BYQ_ACP_PRODUCT_SLOT_SECONDARY_SECRET"],
            adapter["environment"]["BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET"],
        )
        self.assertNotEqual(
            adapter["environment"]["BYQ_ACP_PRODUCT_SLOT_PRIMARY_SECRET"],
            adapter["environment"]["BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET"],
        )
        self.assertEqual(secondary["environment"]["BYQ_ACP_PRODUCT_WORKSPACE_ID"],
                         SECONDARY_WORKSPACE)
        self.assertEqual(secondary["environment"]["BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET"],
                         "test-only-secondary-runner-secret")

        self.assertEqual(primary["image"], secondary["image"])
        self.assertNotIn("build", secondary)
        self.assertEqual(secondary["environment"]["BYQ_ACP_ROLE"], "product")
        for name in ("BYQ_DSH_PROCESS_OWNERSHIP", "BYQ_DSH_COMPOSITION",
                     "BYQ_DSH_COMPOSITION_IDENTITY", "BYQ_DSH_RELEASE_IDENTITY",
                     "DSH_MAX_TOKENS_AS_SUCCESS"):
            self.assertEqual(secondary["environment"][name], primary["environment"][name])
        for name in ("user", "read_only", "cap_drop", "cap_add", "security_opt", "tmpfs"):
            self.assertEqual(secondary[name], primary[name], name)
        self.assertEqual(set(secondary["networks"]), {"byq_product"})

        volumes = config["volumes"]
        expected_mounts = {
            "byq_acp_two_user_qualification_secondary_sessions":
                (f"{root}/{SECONDARY_WORKSPACE}", "volume"),
            "byq_acp_two_user_qualification_secondary_state":
                ("/var/lib/byq/acp-product-runner-state", "volume"),
            "byq_acp_two_user_qualification_secondary_control":
                ("/run/byq-acp-product-runner", "volume"),
        }
        runner_mounts = {
            item["source"]: (item["target"], item["type"])
            for item in secondary["volumes"]
        }
        self.assertEqual(runner_mounts, expected_mounts)
        self.assertEqual(len(secondary["volumes"]), 3)
        expected_volume_names = {
            "byq_acp_two_user_qualification_secondary_sessions":
                "acp-two-user-qualification-test-acp-two-user-qualification-secondary-sessions",
            "byq_acp_two_user_qualification_secondary_state":
                "acp-two-user-qualification-test-acp-two-user-qualification-secondary-state",
            "byq_acp_two_user_qualification_secondary_control":
                "acp-two-user-qualification-test-acp-two-user-qualification-secondary-control",
        }
        for source, name in expected_volume_names.items():
            self.assertEqual(volumes[source]["name"], name)
            self.assertNotIn(source, primary_runner_mounts)
        self.assertIn(("byq_acp_two_user_qualification_secondary_sessions",
                       expected_mounts["byq_acp_two_user_qualification_secondary_sessions"][0],
                       "volume"), adapter_mounts)
        self.assertIn(("byq_acp_two_user_qualification_secondary_control",
                       "/run/byq-acp-product-runner-secondary", "volume"), adapter_mounts)
        self.assertIn("acp-product-runner-secondary", adapter["depends_on"])

        forbidden_targets = {"/var/lib/postgresql/data", "/run/byq-acp-runner",
                             "/var/lib/byq/acp-judgment-sessions"}
        self.assertFalse(forbidden_targets.intersection(
            target for target, _kind in runner_mounts.values()
        ))
        self.assertFalse(secondary.get("privileged", False))
        self.assertNotIn("pid", secondary)
        self.assertFalse(any(item["type"] != "volume" for item in secondary["volumes"]))
        for name in (
            "BYQ_MCP_ACP_DISCOVERY_TOKEN", "BYQ_MCP_ACP_SIGNING_KEY",
            "BYQ_RUNTIME_AUTHORITY_TOKEN", "BYQ_RUNTIME_JUDGMENT_TOKEN",
            "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET", "OPENCODE_API_KEY",
            "DEEPSEEK_API_KEY", "OPENCODE_API_KEY_UPSTREAM",
            "DEEPSEEK_API_KEY_UPSTREAM",
        ):
            self.assertNotIn(name, secondary["environment"])

    def test_qualification_overlay_is_not_in_default_dev_release_or_ci_routes(self) -> None:
        overlay_name = QUALIFICATION.relative_to(ROOT).as_posix()
        for path in (
            ROOT / "compose.override.yml",
            ROOT / "scripts/dev/acp_compose.py",
            ROOT / "scripts/release/images.py",
            ROOT / "scripts/ci/local-ci.sh",
        ):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn(overlay_name, path.read_text(encoding="utf-8"))

    def test_missing_secondary_binding_inputs_fail_compose_interpolation(self) -> None:
        for name, message in (
            ("BYQ_QUAL_ACP_PRODUCT_SECONDARY_WORKSPACE_ID", "secondary workspace is required"),
            ("BYQ_QUAL_ACP_PRODUCT_SECONDARY_SECRET", "secondary runner secret is required"),
        ):
            with self.subTest(missing=name):
                result = self._config(omit=name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
