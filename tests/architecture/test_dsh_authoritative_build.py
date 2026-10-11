"""Offline contracts for resolver-fed ACP DSH container builds."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from scripts.dsh.acp_build import (
    build_environment,
    command_environment,
    docker_build_arguments,
    verify_build_inputs,
)
from scripts.dsh.authoritative_version import (
    AuthoritativeVersionError,
    load_authoritative_version,
)

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "compose.yml",
    ROOT / "compose.override.yml",
)
DOCKERFILES = {
    "adapter": ROOT / "services/runtime-adapter/Dockerfile.acp-0.2.0-rc.2-candidate",
    "ordinary_runner": ROOT / "services/acp_product_runner/Dockerfile",
    "judgment_runner": ROOT / "services/acp_judgment_runner/Dockerfile",
}
ROLE_ARTIFACTS = {
    "adapter": ("product", "product_identity", "release_identity"),
    "ordinary_runner": ("product", "product_identity", "release_identity"),
    "judgment_runner": ("judgment", "judgment_identity", None),
}
ROLE_ENV_PREFIX = {
    "adapter": "BYQ_DSH_BUILD_ADAPTER",
    "ordinary_runner": "BYQ_DSH_BUILD_ORDINARY_RUNNER",
    "judgment_runner": "BYQ_DSH_BUILD_JUDGMENT_RUNNER",
}
# ADR-0110 single-image topology (additive candidate overlay; the operative
# three-image lane stays until every adoption gate is met).
ACP_ROLE_SERVICES = ("runtime-adapter", "acp-product-runner", "acp-judgment-runner")
UNIFIED_OVERLAY = ROOT / "compose.dsh-acp-single-image-candidate.yml"
UNIFIED_DOCKERFILE = ROOT / "services/acp_unified/Dockerfile"


class DshAuthoritativeBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.selection = load_authoritative_version(ROOT)
        cls.build_env = build_environment(cls.selection)

    def test_host_helper_exports_resolver_values_for_each_role(self) -> None:
        self.assertEqual(
            self.build_env["BYQ_DSH_BUILD_RELEASE_ID"], self.selection["release_id"]
        )
        self.assertEqual(
            self.build_env["BYQ_DSH_BUILD_SOURCE_COMMIT"], self.selection["source_commit"]
        )
        self.assertEqual(
            self.build_env["BYQ_DSH_BUILD_PNPM_LOCK_SHA256"],
            self.selection["pnpm_lock_sha256"],
        )
        for role, (profile, identity, release_identity) in ROLE_ARTIFACTS.items():
            prefix = {
                "adapter": "BYQ_DSH_BUILD_ADAPTER",
                "ordinary_runner": "BYQ_DSH_BUILD_ORDINARY_RUNNER",
                "judgment_runner": "BYQ_DSH_BUILD_JUDGMENT_RUNNER",
            }[role]
            for suffix, key in (("PROFILE", profile), ("PROFILE_IDENTITY", identity)):
                self.assertEqual(
                    self.build_env[f"{prefix}_{suffix}_PATH"],
                    self.selection["profiles"][key]["path"],
                )
                self.assertEqual(
                    self.build_env[f"{prefix}_{suffix}_SHA256"],
                    self.selection["profiles"][key]["sha256"],
                )
            if release_identity:
                self.assertEqual(
                    self.build_env[f"{prefix}_RELEASE_IDENTITY_SHA256"],
                    self.selection["profiles"][release_identity]["sha256"],
                )

    def test_compose_inputs_and_dockerfiles_use_the_shared_interface(self) -> None:
        compose = (ROOT / "compose.dsh-acp-rc2-candidate.yml").read_text()
        default_override = (ROOT / "compose.override.yml").read_text()
        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertIn("compose.dsh-acp-rc2-candidate.yml", default_override)
        self.assertIn('python3 "$REPO_ROOT/scripts/dsh/acp_build.py" --', local_ci)
        self.assertIn("BYQ_DSH_BUILD_ADAPTER_PROFILE_PATH", compose)
        self.assertIn("BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_PATH", compose)
        self.assertIn("BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_PATH", compose)
        self.assertIn(
            "BYQ_DSH_COMPATIBILITY_RELEASE: ${BYQ_DSH_BUILD_COMPATIBILITY_FAMILY:?",
            compose,
        )
        self.assertIn(
            "DSH_SESSION_ROOT: ${BYQ_DSH_BUILD_SESSION_ROOT:?", compose
        )
        for name in (
            "BYQ_DSH_BUILD_RELEASE_ID",
            "BYQ_DSH_BUILD_SOURCE_COMMIT",
            "BYQ_DSH_BUILD_PNPM_LOCK_SHA256",
            "BYQ_DSH_BUILD_COMPATIBILITY_FAMILY",
        ):
            self.assertIn(f"{name}: ${{{name}-}}", compose)
        # ADR-0110 adoption: the default route passes the resolver-fed role
        # artifacts directly to the one unified build (no per-role generic
        # remapping). The unified Dockerfile verifies all three roles.
        for role, (_, _, release_identity) in ROLE_ARTIFACTS.items():
            prefix = ROLE_ENV_PREFIX[role]
            arguments = (
                f"{prefix}_PROFILE_PATH",
                f"{prefix}_PROFILE_SHA256",
                f"{prefix}_PROFILE_IDENTITY_PATH",
                f"{prefix}_PROFILE_IDENTITY_SHA256",
            )
            if release_identity:
                arguments += (
                    f"{prefix}_RELEASE_IDENTITY_PATH",
                    f"{prefix}_RELEASE_IDENTITY_SHA256",
                )
            for argument in arguments:
                self.assertIn(f"{argument}: ${{{argument}-}}", compose)
        self.assertIn("dockerfile: services/acp_unified/Dockerfile", compose)
        self.assertEqual(compose.count("build: *acp-unified-build"), 3)
        self.assertEqual(
            compose.count("image: ${COMPOSE_PROJECT_NAME:-beyondquant}-acp-unified"), 3
        )
        for role in ("adapter", "product", "judgment"):
            self.assertIn(f"BYQ_ACP_ROLE: {role}", compose)

        for role, dockerfile_path in DOCKERFILES.items():
            source = dockerfile_path.read_text()
            for name in docker_build_arguments(self.selection, role):
                self.assertIn(f"ARG {name}", source)
            verify_at = source.index(f"--verify-build-inputs --role {role} --root /opt/byq-authoritative")
            clone_at = source.index('git clone --depth 1 --branch "$BYQ_DSH_BUILD_RELEASE_ID"')
            self.assertLess(verify_at, clone_at)
            self.assertIn('--branch "$BYQ_DSH_BUILD_RELEASE_ID"', source)
            self.assertIn('= "$BYQ_DSH_BUILD_SOURCE_COMMIT"', source)
            self.assertIn('"$BYQ_DSH_BUILD_PNPM_LOCK_SHA256  pnpm-lock.yaml"', source)
            self.assertIn("git rev-parse HEAD > .byq-source-commit", source)
            self.assertIn("sha256sum /opt/dsh-runtime/pnpm-lock.yaml", source)
            if role in {"adapter", "ordinary_runner"}:
                self.assertIn(
                    "BYQ_DSH_COMPATIBILITY_RELEASE=${BYQ_DSH_BUILD_COMPATIBILITY_FAMILY}",
                    source,
                )
            profile, identity, release_identity = ROLE_ARTIFACTS[role]
            for key in (profile, identity):
                relative = self.selection["profiles"][key]["path"]
                self.assertIn(f"COPY {relative} ", source)
                self.assertNotIn(self.selection["profiles"][key]["sha256"], source)
            self.assertIn("$BYQ_DSH_BUILD_PROFILE_SHA256", source)
            self.assertIn("$BYQ_DSH_BUILD_PROFILE_IDENTITY_SHA256", source)
            if release_identity:
                relative = self.selection["profiles"][release_identity]["path"]
                self.assertIn(f"COPY {relative} ", source)
                self.assertIn("$BYQ_DSH_BUILD_RELEASE_IDENTITY_SHA256", source)
                self.assertNotIn(self.selection["profiles"][release_identity]["sha256"], source)
            self.assertNotIn("639ed015397290b3745d163aafe02ffee4aa3f84", source)
            self.assertNotIn("80fe05eae33582ae26839afd05f1965f9b0e4be11034ddf9797af6085d5ba9b1", source)

    def test_docker_build_rejects_missing_or_mismatched_identity(self) -> None:
        for role in ROLE_ARTIFACTS:
            with self.subTest(role=role):
                verify_build_inputs(
                    self.selection, role, docker_build_arguments(self.selection, role)
                )
        missing = docker_build_arguments(self.selection, "adapter")
        del missing["BYQ_DSH_BUILD_SOURCE_COMMIT"]
        with self.assertRaises(AuthoritativeVersionError):
            verify_build_inputs(self.selection, "adapter", missing)
        mismatched = docker_build_arguments(self.selection, "adapter")
        mismatched["BYQ_DSH_BUILD_PROFILE_SHA256"] = "0" * 64
        with self.assertRaises(AuthoritativeVersionError):
            verify_build_inputs(self.selection, "adapter", mismatched)
        wrong_role = docker_build_arguments(self.selection, "judgment_runner")
        wrong_role["BYQ_DSH_BUILD_PROFILE_PATH"] = self.selection["profiles"]["product"]["path"]
        with self.assertRaises(AuthoritativeVersionError):
            verify_build_inputs(self.selection, "judgment_runner", wrong_role)

    def test_single_image_topology_is_one_build_and_one_digest_for_three_roles(self) -> None:
        # ADR-0110: the adapter / ordinary-runner / judgment-runner roles declare
        # one build (the unified Dockerfile) and one image expression, so one
        # build yields one image id shared by all three roles. Role selection is
        # a runtime parameter (BYQ_ACP_ROLE), not a distinct artifact.
        #
        # The adopted default route is compose.dsh-acp-rc2-candidate.yml; the
        # additive candidate overlay stays a separate isolated evaluation file.
        for source in (
            ROOT / "compose.dsh-acp-rc2-candidate.yml",
            UNIFIED_OVERLAY,
        ):
            with self.subTest(route=source.name):
                overlay = yaml.safe_load(source.read_text(encoding="utf-8"))
                services = overlay["services"]
                self.assertTrue(set(ACP_ROLE_SERVICES) <= set(services))
                images = {name: services[name]["image"] for name in ACP_ROLE_SERVICES}
                self.assertEqual(len(set(images.values())), 1, images)
                builds = [services[name].get("build") for name in ACP_ROLE_SERVICES]
                self.assertTrue(all(isinstance(build, dict) for build in builds), builds)
                self.assertEqual(
                    {build["dockerfile"] for build in builds},
                    {"services/acp_unified/Dockerfile"},
                )
                for build in builds:
                    self.assertEqual(build["context"], ".")
                # ADR-0110: the one shared image is only valid when all three
                # role services declare the exact same build (context/args/etc.).
                self.assertTrue(
                    all(build == builds[0] for build in builds),
                    "the three single-image ACP builds must be identical",
                )

        # The one unified Dockerfile verifies ALL THREE roles before any clone
        # and reads the build identity back from the resolver, never from a
        # hard-coded literal.
        source = UNIFIED_DOCKERFILE.read_text(encoding="utf-8")
        clone_at = source.index('git clone --depth 1 --branch "$BYQ_DSH_BUILD_RELEASE_ID"')
        for role in ("adapter", "ordinary_runner", "judgment_runner"):
            marker = f"--verify-build-inputs --role {role} --root /opt/byq-authoritative"
            self.assertIn(marker, source, role)
            self.assertLess(source.index(marker), clone_at, role)
        self.assertNotIn(self.selection["source_commit"], source)
        self.assertIn('"$BYQ_DSH_BUILD_SOURCE_COMMIT"', source)
        # The image default identity is the fail-closed unprivileged adapter
        # identity; the root PID-1 runner roles set user: "0:0" in Compose.
        self.assertEqual(
            [line.strip() for line in source.splitlines() if line.strip().startswith("USER ")],
            ["USER byq"],
        )

    def test_wrapper_replaces_ambient_build_selectors_only(self) -> None:
        inherited = {
            "BYQ_DSH_BUILD_RELEASE_ID": "dsh-0.1.5rc1",
            "BYQ_DSH_BUILD_UNRECOGNIZED": "ambient-value",
            "BYQ_DSH_BUILD_COMPATIBILITY_FAMILY": "dsh-0.1.5rc1",
            "BYQ_DSH_BUILD_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1",
            "BYQ_DSH_COMPATIBILITY_RELEASE": "dsh-0.1.5rc1",
            "BYQ_DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1",
            "DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1",
            "BYQ_RUNTIME_AUTHORITY_TOKEN": "opaque-token",
        }
        resolved = command_environment(self.selection, inherited)
        self.assertEqual(resolved["BYQ_DSH_BUILD_RELEASE_ID"], self.selection["release_id"])
        self.assertNotIn("BYQ_DSH_BUILD_UNRECOGNIZED", resolved)
        self.assertEqual(resolved["BYQ_RUNTIME_AUTHORITY_TOKEN"], "opaque-token")
        family = self.selection["compatibility_family"]
        session_root = f"/var/lib/byq/dsh-sessions/{family}"
        self.assertEqual(resolved["BYQ_DSH_BUILD_COMPATIBILITY_FAMILY"], family)
        self.assertEqual(resolved["BYQ_DSH_BUILD_SESSION_ROOT"], session_root)
        self.assertEqual(resolved["BYQ_DSH_COMPATIBILITY_RELEASE"], family)
        self.assertEqual(resolved["BYQ_DSH_SESSION_ROOT"], session_root)
        self.assertEqual(resolved["DSH_SESSION_ROOT"], session_root)

    @staticmethod
    def _compose_test_environment() -> dict[str, str]:
        """Return only fake interpolation inputs; no local env file or secrets."""
        env = {
            "PATH": os.environ.get("PATH", ""),
            "COMPOSE_PROJECT_NAME": "acp-resolver-merge-test",
            "BYQ_PRODUCT_TOKEN": "test-only-product-token",
            "BYQ_RUNTIME_AUTHORITY_TOKEN": "test-only-runtime-authority",
            "BYQ_RUNTIME_JUDGMENT_TOKEN": "test-only-runtime-judgment",
            "BYQ_ACP_PRODUCT_WORKSPACE_ID": "workspace_test000000000000000000000000000",
            "BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET": "test-only-product-runner-secret",
            "BYQ_MCP_ACP_DISCOVERY_TOKEN": "test-only-acp-discovery-token",
            "BYQ_MCP_ACP_SIGNING_KEY": "test-only-acp-signing-key",
            "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY": "test-only-judgment-signing-key",
            "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET": "test-only-judgment-runner-secret",
            "BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN": "test-only-judgment-proof-token",
            "BYQ_MCP_BACKEND_PROOF_TOKEN": "test-only-backend-proof-token",
            "BYQ_GATEWAY_SERVICE_TOKEN": "test-only-gateway-token",
            "BYQ_MCP_TOKEN": "test-only-mcp-token",
        }
        return env

    def _compose_config_command(self, docker: str) -> list[str]:
        return [
            docker,
            "compose",
            "--env-file",
            "/dev/null",
            "--project-directory",
            str(ROOT),
            "-f",
            str(COMPOSE_FILES[0]),
            "-f",
            str(COMPOSE_FILES[1]),
            "config",
            "--format",
            "json",
        ]

    def test_merged_compose_uses_resolver_family_and_root_over_inherited_sdk(self) -> None:
        docker = shutil.which("docker")
        if docker is None:
            self.skipTest("Docker Compose is unavailable for merged-config validation")
        version = subprocess.run(
            [docker, "compose", "version"], capture_output=True, check=False
        )
        if version.returncode != 0:
            self.skipTest("Docker Compose plugin is unavailable for merged-config validation")

        env = self._compose_test_environment()
        env.update(
            {
                "BYQ_DSH_COMPATIBILITY_RELEASE": "dsh-0.1.5rc1",
                "BYQ_DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1",
                "BYQ_DSH_BUILD_COMPATIBILITY_FAMILY": "dsh-0.1.5rc1",
                "BYQ_DSH_BUILD_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1",
                "BYQ_DSH_BUILD_RELEASE_ID": "dsh-0.1.5rc1",
                "BYQ_DSH_BUILD_UNRECOGNIZED": "must-be-removed",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/dsh/acp_build.py"),
                "--",
                *self._compose_config_command(docker),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, "resolver-wrapped Compose config failed")
        merged = json.loads(result.stdout)
        services = merged["services"]
        self.assertEqual(len(services), 18)
        self.assertEqual(sum("build" in service for service in services.values()), 17)
        family = self.selection["compatibility_family"]
        session_root = f"/var/lib/byq/dsh-sessions/{family}"
        # ADR-0110 adoption: the default route is the one unified build; the
        # three ACP role services share its Dockerfile and image reference.
        expected_dockerfile = "services/acp_unified/Dockerfile"
        runtime = services["runtime-adapter"]
        runtime_environment = runtime["environment"]
        self.assertEqual(runtime["build"]["dockerfile"], expected_dockerfile)
        acp_images = {
            services[name]["image"]
            for name in ("runtime-adapter", "acp-product-runner", "acp-judgment-runner")
        }
        self.assertEqual(len(acp_images), 1, acp_images)
        self.assertEqual(
            {services[name]["build"]["dockerfile"] for name in
             ("runtime-adapter", "acp-product-runner", "acp-judgment-runner")},
            {expected_dockerfile},
        )
        self.assertEqual(runtime_environment["BYQ_ACP_ROLE"], "adapter")
        self.assertEqual(runtime_environment["BYQ_DSH_COMPATIBILITY_RELEASE"], family)
        self.assertEqual(runtime_environment["DSH_SESSION_ROOT"], session_root)
        self.assertEqual(runtime_environment["BYQ_DSH_PROVIDER"], "opencode-go-chat")
        self.assertEqual(runtime_environment["BYQ_DSH_MODEL"], "deepseek-v4.1-flash")
        workspace = env["BYQ_ACP_PRODUCT_WORKSPACE_ID"]
        expected_leaf = f"{session_root}/{workspace}"
        self.assertFalse(any(mount.get("source") == "byq_dsh_sessions" for mount in runtime.get("volumes", [])))
        self.assertTrue(any(mount.get("source") == "byq_acp_product_sessions" and mount.get("target") == expected_leaf for mount in runtime.get("volumes", [])))
        runner = services["acp-product-runner"]
        self.assertTrue(any(mount.get("source") == "byq_acp_product_sessions" and mount.get("target") == expected_leaf for mount in runner.get("volumes", [])))
        self.assertEqual(runner["environment"]["BYQ_ACP_PRODUCT_WORKSPACE_ID"], workspace)
        bindings = json.loads(runtime_environment["BYQ_ACP_PRODUCT_SLOT_BINDINGS"])
        self.assertEqual(set(bindings), {workspace})
        self.assertEqual(bindings[workspace], {"socket_path": "/run/byq-acp-product-runner/control.sock", "control_secret_env": "BYQ_ACP_PRODUCT_SLOT_PRIMARY_SECRET"})

    def test_candidate_compose_fails_closed_without_helper_resolver_values(self) -> None:
        docker = shutil.which("docker")
        if docker is None:
            self.skipTest("Docker Compose is unavailable for fail-closed validation")
        version = subprocess.run(
            [docker, "compose", "version"], capture_output=True, check=False
        )
        if version.returncode != 0:
            self.skipTest("Docker Compose plugin is unavailable for fail-closed validation")

        env = self._compose_test_environment()
        env.update(
            {
                "BYQ_DSH_COMPATIBILITY_RELEASE": "dsh-0.1.5rc1",
                "BYQ_DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1",
            }
        )
        result = subprocess.run(
            self._compose_config_command(docker),
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
