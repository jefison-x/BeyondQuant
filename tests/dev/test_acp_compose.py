"""Focused contracts for the canonical ACP Compose build/up helper (ADR-0110)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/dev/acp_compose.py"
spec = importlib.util.spec_from_file_location("byq_dev_acp_compose", SCRIPT)
acp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acp)

UNIFIED = "services/acp_unified/Dockerfile"
ROLE_ENVIRONMENT = {
    "runtime-adapter": "adapter",
    "acp-product-runner": "product",
    "acp-judgment-runner": "judgment",
}
PER_ROLE = {
    "runtime-adapter": "services/runtime-adapter/Dockerfile.acp-0.2.0-rc.2-candidate",
    "acp-product-runner": "services/acp_product_runner/Dockerfile",
    "acp-judgment-runner": "services/acp_judgment_runner/Dockerfile",
}


def config(role_dockerfiles=None, *, image="byq-dev-test-acp-unified"):
    role_dockerfiles = role_dockerfiles or {name: UNIFIED for name in acp.ACP_ROLE_SERVICES}
    services = {
        name: {
            "image": image,
            "build": {"context": ".", "dockerfile": role_dockerfiles[name]},
            "environment": {"BYQ_ACP_ROLE": ROLE_ENVIRONMENT[name]},
        }
        for name in acp.ACP_ROLE_SERVICES
    }
    services["runtime-adapter"]["depends_on"] = {
        "acp-product-runner": {}, "acp-judgment-runner": {}, "mcp-acp-judgment": {},
    }
    services["mcp-acp-judgment"] = {"build": {"context": ".", "dockerfile": "services/mcp/Dockerfile"}}
    for name, dockerfile in (
        ("backend", "services/backend/Dockerfile"),
        ("mcp", "services/mcp/Dockerfile"),
        ("gateway", "services/gateway/Dockerfile"),
    ):
        services[name] = {"build": {"context": ".", "dockerfile": dockerfile}}
    services["postgres"] = {"image": "postgres:16-alpine"}
    return {"services": services}


class AcpComposeHelperTests(unittest.TestCase):
    def test_single_image_topology_and_one_canonical_build_target(self):
        cfg = config()
        self.assertEqual(acp.acp_topology(cfg), acp.SINGLE_IMAGE)
        targets = acp.build_targets(cfg, ["postgres", "backend", "mcp", "runtime-adapter", "gateway"])
        self.assertIn("runtime-adapter", targets)
        for extra in acp.ACP_EXTRA_ROLE_TARGETS:
            self.assertNotIn(extra, targets)
        # All services (no explicit selection) still build the one ACP target.
        all_targets = acp.build_targets(cfg, [])
        self.assertIn("runtime-adapter", all_targets)
        for extra in acp.ACP_EXTRA_ROLE_TARGETS:
            self.assertNotIn(extra, all_targets)
        # Image-only services are never build targets.
        self.assertNotIn("postgres", all_targets)

    def test_dependency_closure_is_built_for_selected_services(self):
        cfg = config()
        targets = acp.build_targets(cfg, ["runtime-adapter"])
        self.assertIn("runtime-adapter", targets)
        # mcp-acp-judgment is a dependency of runtime-adapter and has a build.
        self.assertIn("mcp-acp-judgment", targets)

    def test_non_acp_selected_service_depending_on_a_runner_still_builds_one_canonical_target(self):
        # A non-ACP service can pull a runner into the dependency closure. The
        # "any ACP present" decision must be taken from the closure BEFORE the
        # runner targets are filtered out, so the one shared canonical image is
        # still built exactly once.
        cfg = config()
        cfg["services"]["consumer"] = {
            "build": {"context": ".", "dockerfile": "services/consumer/Dockerfile"},
            "depends_on": {"acp-product-runner": {}},
        }
        targets = acp.build_targets(cfg, ["consumer"])
        self.assertEqual(targets.count("runtime-adapter"), 1)
        self.assertIn("runtime-adapter", targets)
        self.assertIn("consumer", targets)
        for extra in acp.ACP_EXTRA_ROLE_TARGETS:
            self.assertNotIn(extra, targets)

    def test_topology_fails_closed_on_partial_or_missing_roles(self):
        partial = config()
        partial["services"]["acp-judgment-runner"]["build"]["dockerfile"] = (
            "services/acp_judgment_runner/Dockerfile")
        with self.assertRaises(acp.ComposeError):
            acp.acp_topology(partial)
        missing = config()
        del missing["services"]["acp-judgment-runner"]
        with self.assertRaises(acp.ComposeError):
            acp.acp_topology(missing)
        divergent_image = config()
        divergent_image["services"]["acp-product-runner"]["image"] = "other"
        with self.assertRaises(acp.ComposeError):
            acp.acp_topology(divergent_image)

    def test_topology_rejects_unknown_shared_dockerfile_and_divergent_build(self):
        # Three services sharing an unknown (stale per-role) Dockerfile is not
        # the known unified single-image build and must fail closed.
        stale = {name: "services/runtime-adapter/Dockerfile.post-u8-candidate"
                 for name in acp.ACP_ROLE_SERVICES}
        with self.assertRaises(acp.ComposeError):
            acp.acp_topology(config(stale))
        # One shared Dockerfile/image with a divergent effective build mapping
        # (context/args/target) would build different images under one tag.
        divergent = config()
        divergent["services"]["acp-product-runner"]["build"]["args"] = {
            "BYQ_DSH_BUILD_RELEASE_ID": "x"}
        with self.assertRaises(acp.ComposeError):
            acp.acp_topology(divergent)

    def test_topology_rejects_missing_or_wrong_role_dispatch(self):
        wrong = config()
        wrong["services"]["acp-judgment-runner"]["environment"]["BYQ_ACP_ROLE"] = "adapter"
        with self.assertRaises(acp.ComposeError):
            acp.acp_topology(wrong)
        missing = config()
        del missing["services"]["runtime-adapter"]["environment"]
        with self.assertRaises(acp.ComposeError):
            acp.acp_topology(missing)

    def test_per_role_route_keeps_every_role_build_target(self):
        cfg = config(PER_ROLE)
        # A per-role route need not declare a runtime role dispatch.
        for service in cfg["services"].values():
            service.pop("environment", None)
        self.assertEqual(acp.acp_topology(cfg), acp.PER_ROLE_IMAGE)
        targets = acp.build_targets(cfg, [])
        for name in acp.ACP_ROLE_SERVICES:
            self.assertIn(name, targets)

    def test_canonical_up_builds_once_then_starts_without_build(self):
        cfg = config()
        recorded = []

        def fake_run(command, **kwargs):
            recorded.append(command)
            return CompletedProcess(command, 0, "", "")

        with patch.object(acp.subprocess, "run", side_effect=fake_run):
            status = acp.canonical_up(["compose"], cfg, ["postgres", "backend", "runtime-adapter"])
        self.assertEqual(status, 0)
        self.assertEqual(len(recorded), 2, recorded)
        build, up = recorded
        self.assertIn("build", build)
        self.assertIn("runtime-adapter", build)
        self.assertNotIn("acp-product-runner", build)
        self.assertIn("--no-build", up)
        self.assertIn("--wait", up)
        self.assertEqual(up[-1], "runtime-adapter")

    def test_compose_command_is_parsed_with_shlex_without_shell_evaluation(self):
        prefix = acp.parse_compose_command("docker compose -f custom.yml --profile dev")
        self.assertEqual(prefix, ["docker", "compose", "-f", "custom.yml", "--profile", "dev"])
        quoted = acp.parse_compose_command(
            "python3 scripts/dsh/acp_build.py -- docker compose -f 'a b.yml'")
        self.assertEqual(
            quoted,
            ["python3", "scripts/dsh/acp_build.py", "--", "docker", "compose", "-f", "a b.yml"])
        with self.assertRaises(acp.ComposeError):
            acp.parse_compose_command("")
        with self.assertRaises(acp.ComposeError):
            acp.parse_compose_command("docker compose 'unbalanced")

    def test_main_preserves_the_selected_compose_prefix_argv(self):
        recorded = []

        def fake_run(command, **kwargs):
            recorded.append(command)
            return CompletedProcess(command, 0, "", "")

        with patch.object(acp, "parse_config", return_value=config()), \
                patch.object(acp.subprocess, "run", side_effect=fake_run):
            status = acp.main(
                ["--compose-command", "docker compose -f custom.yml", "build"])
        self.assertEqual(status, 0)
        self.assertEqual(
            recorded[0][:4], ["docker", "compose", "-f", "custom.yml"])

    def test_default_compose_prefix_remains_resolver_fed(self):
        prefix = acp.default_compose_prefix()
        self.assertEqual(
            prefix[:4],
            [sys.executable, str(acp.ROOT / "scripts/dsh/acp_build.py"), "--", "docker"])
        self.assertIn(str(acp.ROOT / "compose.yml"), prefix)
        self.assertIn(str(acp.ROOT / "compose.override.yml"), prefix)

    def test_makefile_routes_honor_the_selected_compose_prefix(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn(
            "ACP_COMPOSE ?= python3 scripts/dev/acp_compose.py --compose-command '$(COMPOSE)'",
            makefile)
        self.assertIn("COMPOSE ?= python3 scripts/dsh/acp_build.py -- docker compose", makefile)
        # All four ACP routes (build/up/smoke/test) go through the helper, which
        # receives the selected COMPOSE prefix, including custom -f files.
        lines = makefile.splitlines()
        self.assertIn("\t$(ACP_COMPOSE) build", lines)
        self.assertIn("\t$(ACP_COMPOSE) up", lines)


if __name__ == "__main__":
    unittest.main()
