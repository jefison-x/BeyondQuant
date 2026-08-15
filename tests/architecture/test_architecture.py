import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def service_block(name: str, compose_file: str = "compose.yml") -> str:
    compose = (ROOT / compose_file).read_text()
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        compose,
    )
    if match is None:
        raise AssertionError(f"service {name!r} is missing from {compose_file}")
    return match.group(1)


def dsh_service_block() -> str:
    return service_block("dsh", "compose.dsh-web.yml")


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_base_compose_uses_runtime_adapter_as_the_only_product_dsh_path(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        self.assertNotRegex(compose, r"(?m)^  dsh:")
        self.assertIn("byq_dsh_sessions:", compose)
        runtime = service_block("runtime-adapter")
        self.assertIn("byq_dsh_sessions:/var/lib/byq/dsh-sessions", runtime)
        self.assertNotIn("/app", runtime)
        self.assertNotIn("/opt/dsh-runtime", runtime.split("volumes:", 1)[-1])
        self.assertNotIn("/opt/byq", runtime.split("volumes:", 1)[-1])

    def test_dsh_web_is_diagnostic_profile_only(self) -> None:
        diagnostic = (ROOT / "compose.dsh-web.yml").read_text()
        self.assertIn('profiles: ["dsh-web"]', diagnostic)
        self.assertIn("dockerfile: services/dsh/Dockerfile", diagnostic)
        self.assertNotIn("ports:", diagnostic)

    def test_runtime_image_keeps_application_and_config_root_owned(self) -> None:
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile").read_text()
        self.assertIn("chown -R byq:byq /var/lib/byq/dsh-sessions", dockerfile)
        self.assertNotIn("chown -R byq:byq /app", dockerfile)
        self.assertNotIn("chown -R byq:byq /opt/dsh-runtime", dockerfile)
        self.assertNotIn("chown -R byq:byq /opt/byq", dockerfile)

    def test_product_dsh_has_no_source_mount(self) -> None:
        dsh = dsh_service_block()
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
        self.assertNotIn("privileged:", dsh_service_block())

    def test_dsh_is_container_local_and_not_host_published(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        dsh = dsh_service_block()
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
        contents = compose + "\n" + (ROOT / "compose.dsh-web.yml").read_text() + "\n" + "\n".join(path.read_text() for path in dsh_files)
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
        dsh = dsh_service_block()
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
        self.assertIn("mcp:\n        condition: service_healthy", dsh_service_block())
        self.assertIn("backend:\n        condition: service_healthy", service_block("mcp"))
        self.assertIn("runtime-adapter:\n        condition: service_healthy", service_block("gateway"))
        self.assertNotIn("dsh:", service_block("gateway"))

    def test_gateway_does_not_import_or_parse_dsh_types(self) -> None:
        gateway = "\n".join(
            path.read_text()
            for path in (ROOT / "services/gateway").rglob("*.py")
        )
        self.assertNotIn("deepseek_harness", gateway)
        self.assertNotIn("Notification", gateway)
        self.assertNotIn("session.event", gateway)

    def test_phase7_auth_and_model_secret_boundaries_are_separate(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        gateway = service_block("gateway")
        runtime = service_block("runtime-adapter")
        self.assertIn("BYQ_PRODUCT_TOKEN", gateway)
        self.assertNotIn("DEEPSEEK_API_KEY", gateway)
        self.assertIn("DEEPSEEK_API_KEY", runtime)
        self.assertNotIn("BYQ_PRODUCT_TOKEN", runtime)
        self.assertIn("byq_workflow_traces", compose)

        workflow = (ROOT / "docs/contracts/workflow-trace.md").read_text()
        self.assertIn("Last-Event-ID", workflow)
        self.assertIn("DSH's durable session log", workflow)

    def test_phase8_tushare_secret_is_backend_only_and_data_uses_mcp(self) -> None:
        backend = service_block("backend")
        self.assertIn("TUSHARE_TOKEN", backend)
        for service in ("gateway", "runtime-adapter", "mcp"):
            self.assertNotIn("TUSHARE_TOKEN", service_block(service))

        mcp = "\n".join(
            path.read_text() for path in (ROOT / "services/mcp/src").rglob("*.ts")
        )
        self.assertIn("byq_market_daily", mcp)
        self.assertNotIn("api.tushare.pro", mcp)

    def test_phase9_domain_state_is_backend_owned_and_mcp_only(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        backend = service_block("backend")
        self.assertIn("BYQ_DOMAIN_DB_PATH: /var/lib/byq/domain/byq.sqlite3", backend)
        self.assertIn("byq_domain_state:/var/lib/byq/domain", backend)
        self.assertIn("byq_domain_state:", compose)
        for service in ("gateway", "runtime-adapter", "mcp"):
            block = service_block(service)
            self.assertNotIn("BYQ_DOMAIN_DB_PATH", block)
            self.assertNotIn("byq_domain_state", block)

        mcp = "\n".join(
            path.read_text() for path in (ROOT / "services/mcp/src").rglob("*.ts")
        )
        self.assertIn("byq_research_task_create", (ROOT / "services/mcp/src/server.ts").read_text())
        self.assertNotIn("sqlite", mcp.lower())
        backend_files = "\n".join(
            path.read_text() for path in (ROOT / "services/backend/app").rglob("*.py")
        )
        self.assertNotIn("WorkflowTraceEvent", backend_files)

    def test_phase14_learning_loop_is_backend_owned_and_mcp_only(self) -> None:
        mcp = "\n".join(
            path.read_text() for path in (ROOT / "services/mcp/src").rglob("*.ts")
        )
        self.assertIn("byq_learning_run_start", mcp)
        self.assertIn("byq_lesson_propose", mcp)
        self.assertNotIn("sqlite", mcp.lower())

        backend_files = "\n".join(
            path.read_text() for path in (ROOT / "services/backend/app").rglob("*.py")
        )
        self.assertIn("learning_runs", backend_files)
        self.assertIn("evaluation_signals", backend_files)
        self.assertIn("lessons", backend_files)

    def test_runtime_adapter_owns_the_official_sdk_and_explicit_runtime(self) -> None:
        adapter = "\n".join(
            path.read_text()
            for path in (ROOT / "services/runtime-adapter").rglob("*.py")
        )
        self.assertIn("DeepSeekHarnessConfig", adapter)
        self.assertIn("launch_args_override", adapter)
        self.assertNotIn("DeepSeekHarness()", adapter)

        pyproject = (ROOT / "services/runtime-adapter/pyproject.toml").read_text()
        self.assertIn('"deepseek-harness-sdk==0.1.0rc6"', pyproject)
        self.assertIn('"deepseek-harness-runtime-bin==0.1.0rc6"', pyproject)

        composition = (ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").read_text()
        self.assertIn("@deepseek-ai/dsh-sdk-jsonrpc-server", composition)
        self.assertIn("@deepseek-ai/dsh-mcp-client", composition)
        self.assertIn("toolBash: false", composition)
        self.assertIn("toolJobs: false", composition)
        self.assertIn("enabled: false", composition)
        self.assertNotRegex(
            composition,
            r"(?m)^\s+name:\s+['\"]?@deepseek-ai/dsh-(tool-bash|tool-fs|tool-str-replace-editor|terminal)",
        )

        runtime_package = json.loads(
            (ROOT / "services/runtime-adapter/runtime/package.json").read_text()
        )
        for dependency in (
            "@deepseek-ai/dsh-agent-spine-demo",
            "@deepseek-ai/dsh-mcp-client",
            "@deepseek-ai/dsh-session-checkpoint-policy",
            "@deepseek-ai/dsh-session-persistence-jsonl",
            "@deepseek-ai/dsh-sdk-jsonrpc-demo",
            "@deepseek-ai/dsh-sdk-jsonrpc-server",
        ):
            self.assertEqual(runtime_package["dependencies"][dependency], "0.1.0-rc.6")

    def test_runtime_adapter_does_not_mount_application_source(self) -> None:
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile").read_text()
        copy_lines = [line for line in dockerfile.splitlines() if line.startswith("COPY")]
        self.assertNotIn("COPY .", dockerfile)
        self.assertIn("packages/contracts", "\n".join(copy_lines))
        self.assertIn("plugins/dsh-byq/compositions", "\n".join(copy_lines))
        self.assertNotIn("services/backend", dockerfile)
        self.assertNotIn(".git", dockerfile)

    def test_sdk_runtime_does_not_use_bundled_zero_config(self) -> None:
        adapter = (ROOT / "services/runtime-adapter/app/runtime.py").read_text()
        self.assertIn("launch_args_override=self.runtime_command", adapter)
        self.assertIn("cordis=str(self._composition)", adapter)
        self.assertNotIn("resolve_bundled_launch_args", adapter)

    def test_runtime_adapter_does_not_bypass_mcp(self) -> None:
        composition = (ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").read_text()
        self.assertIn("name: '@deepseek-ai/dsh-mcp-client'", composition)
        self.assertIn("failOnStartupError: true", composition)
        self.assertNotIn("postgres", composition.lower())
        self.assertNotIn("redis", composition.lower())

    def test_phase13_roles_use_official_dsh_seams_and_bounded_capabilities(self) -> None:
        composition = (ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").read_text()
        self.assertIn("@deepseek-ai/dsh-skill-filesystem", composition)
        self.assertIn("@deepseek-ai/dsh-subagent-spawn-in-process", composition)
        self.assertIn("@deepseek-ai/dsh-tool-subagent", composition)
        self.assertIn("maxDepth: 1", composition)
        self.assertIn("customSkillDirs:", composition)
        self.assertIn("/opt/dsh/bundles/dsh-byq/skills", composition)
        self.assertNotIn("byq_strategy_approve", composition)
        self.assertNotIn("byq_backtest_cancel", composition)

        role_contract = (ROOT / "services/backend/app/agent_research.py").read_text()
        self.assertIn("ROLE_CATALOG", role_contract)
        self.assertIn("agent_approvals", role_contract)
        self.assertIn("agent_audit", role_contract)
        self.assertNotIn("psycopg", role_contract.lower())

        runtime_dockerfile = (ROOT / "services/runtime-adapter/Dockerfile").read_text()
        self.assertIn("plugins/dsh-byq/skills /opt/dsh/bundles/dsh-byq/skills", runtime_dockerfile)

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
