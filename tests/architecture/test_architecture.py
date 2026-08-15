import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def service_block(name: str) -> str:
    compose = (ROOT / "compose.yml").read_text()
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        compose,
    )
    if match is None:
        raise AssertionError(f"service {name!r} is missing from compose.yml")
    return match.group(1)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_product_dsh_has_no_source_mount(self) -> None:
        dsh = service_block("dsh")
        self.assertNotIn("volumes:", dsh)
        self.assertNotRegex(dsh, r"(?:^|:)\.?\.?/.*workspace")
        self.assertNotIn("BeyondQuant", dsh)
        self.assertNotIn("docker.sock", dsh)

        dockerfile = (ROOT / "services/dsh/Dockerfile").read_text()
        copy_lines = [line for line in dockerfile.splitlines() if line.startswith("COPY")]
        self.assertEqual(len(copy_lines), 1)
        self.assertIn("plugins/dsh-byq", copy_lines[0])
        self.assertNotIn("COPY .", dockerfile)

    def test_product_dsh_has_no_docker_socket_or_privileged_mode(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        self.assertNotIn("docker.sock", compose)
        self.assertNotIn("privileged:", service_block("dsh"))

    def test_dsh_is_container_local_and_not_host_published(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        dsh = service_block("dsh")
        gateway = service_block("gateway")

        self.assertNotIn("ports:", dsh)
        self.assertNotIn("3080:3080", compose)
        self.assertNotIn("network_mode: host", compose)
        self.assertNotIn("BYQ_DSH_URL", gateway)
        self.assertNotIn("dsh:", gateway)
        dockerfile = (ROOT / "services/dsh/Dockerfile").read_text()
        self.assertIn("127.0.0.1", dockerfile)
        self.assertIn('"3080"', dockerfile)
        self.assertNotIn("0.0.0.0", dockerfile)

        dev = (ROOT / "compose.dev.yml").read_text()
        self.assertNotIn("3080:3080", dev)

    def test_dsh_has_no_engineering_credentials_or_web_bypass(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        dsh_files = [
            ROOT / "services/dsh/Dockerfile",
            ROOT / "services/dsh/README.md",
            ROOT / "plugins/dsh-byq/cordis.patch.yml",
        ]
        contents = compose + "\n" + "\n".join(path.read_text() for path in dsh_files)
        self.assertNotRegex(contents, r"(?i)(github_token|gh_token|codex_auth|docker_host)")
        self.assertNotRegex(contents, r"(?i)(socat|nginx|iptables|network namespace|host network)")

    def test_dsh_version_is_exact_rc6(self) -> None:
        dockerfile = (ROOT / "services/dsh/Dockerfile").read_text()
        self.assertIn("@deepseek-ai/dsh@0.1.0-rc.6", dockerfile)
        self.assertNotRegex(dockerfile, r"@deepseek-ai/dsh@(latest|[\^~*])")
        self.assertNotIn("@deepseek-ai/dsh@0.1.0-rc.5", dockerfile)

    def test_dsh_byq_uses_streamable_http_and_exact_client(self) -> None:
        bundle = json.loads((ROOT / "plugins/dsh-byq/package.json").read_text())
        self.assertEqual(bundle["dependencies"]["@deepseek-ai/dsh-mcp-client"], "0.1.0-rc.6")
        self.assertEqual(bundle["dsh"]["bundle"]["patch"], "./cordis.patch.yml")

        patch = (ROOT / "plugins/dsh-byq/cordis.patch.yml").read_text()
        self.assertIn("name: '@deepseek-ai/dsh-mcp-client'", patch)
        self.assertIn("serverName: byq", patch)
        self.assertIn("transport: streamable-http", patch)
        self.assertIn("url: http://mcp:8300/mcp/v1", patch)
        self.assertIn("failOnStartupError: true", patch)
        self.assertNotIn("latest", patch)
        self.assertNotRegex(patch, r"(?m)^\s+Authorization:\s+Bearer\s+")

    def test_product_preset_roster_is_byq_only(self) -> None:
        patch = (ROOT / "plugins/dsh-byq/cordis.patch.yml").read_text()
        self.assertIn("default: byq-product", patch)
        self.assertIn("path: /opt/dsh/bundles/dsh-byq/presets", patch)
        self.assertIn("includeUserRoot: false", patch)
        self.assertNotRegex(patch, r"(?m)^\s+default:\s+(standard|minimal|code|cordis)$")

        preset_root = ROOT / "plugins/dsh-byq/presets"
        self.assertEqual(sorted(path.name for path in preset_root.iterdir()), ["byq-product"])
        composition = (preset_root / "byq-product/agent.cordis.yml").read_text()
        self.assertEqual(composition.strip(), "[]")
        self.assertNotRegex(
            composition,
            r"(?i)(bash|pwsh|terminal|edit|write|str_replace_editor|filesystem|git|codex|subagent|mutation)",
        )
        self.assertNotRegex(composition, r"(?m)^\s*name:\s+['\"]?(standard|minimal|code|cordis)")

    def test_runtime_images_use_non_root_users(self) -> None:
        for service, user in (("gateway", "byq"), ("backend", "byq"), ("mcp", "node")):
            dockerfile = (ROOT / f"services/{service}/Dockerfile").read_text()
            self.assertRegex(dockerfile, rf"(?m)^USER {user}$")

        dsh = (ROOT / "services/dsh/Dockerfile").read_text()
        self.assertRegex(dsh, r"(?m)^USER node$")

    def test_dsh_does_not_reference_postgres_or_redis(self) -> None:
        dsh_files = [
            ROOT / "services/dsh/Dockerfile",
            ROOT / "plugins/dsh-byq/cordis.patch.yml",
        ]
        dsh = service_block("dsh")
        contents = dsh + "\n" + "\n".join(path.read_text() for path in dsh_files)
        self.assertNotRegex(contents, r"(?i)(postgres|postgresql|redis)")

    def test_dsh_has_no_engineering_credentials(self) -> None:
        dsh_files = [
            ROOT / "services/dsh/Dockerfile",
            ROOT / "services/dsh/README.md",
            ROOT / "plugins/dsh-byq/cordis.patch.yml",
        ]
        contents = "\n".join(path.read_text() for path in dsh_files)
        self.assertNotRegex(contents, r"(?i)(github_token|gh_token|codex_auth|docker_host)")

    def test_compose_dependency_direction_is_dsh_outbound_to_mcp(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        self.assertIn("mcp:\n        condition: service_healthy", service_block("dsh"))
        self.assertIn("backend:\n        condition: service_healthy", service_block("mcp"))
        self.assertNotIn("depends_on:", service_block("gateway"))

    def test_frontend_has_no_dsh_event_schema_dependency(self) -> None:
        frontend = ROOT / "apps/frontend"
        implementation_files = [
            path
            for path in frontend.rglob("*")
            if path.is_file() and path.suffix in {".py", ".js", ".ts", ".tsx", ".vue"}
        ]
        self.assertEqual(implementation_files, [])
        readme = (frontend / "README.md").read_text()
        self.assertIn("must not depend directly on DSH internal event schemas", readme)


if __name__ == "__main__":
    unittest.main()
