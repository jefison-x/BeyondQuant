import ast
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
    def test_self_hosted_ci_uses_the_immutable_event_base(self) -> None:
        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()

        self.assertIn("BYQ_CI_BASE_SHA:", workflow)
        self.assertIn('--base="$BYQ_CI_BASE_SHA"', workflow)
        self.assertNotIn("--depth=1 origin main", workflow)
        self.assertIn('git diff --check "$DIFF_BASE" HEAD', local_ci)
        self.assertNotIn('git diff --check "$BASE_SHA"...HEAD', local_ci)

    def test_adr_0019_accepts_a_closed_secret_resolution_boundary(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0019-encrypted-credential-store.md").read_text()
        contract = (ROOT / "docs/contracts/credential-store.md").read_text()
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()

        self.assertIn("- Status: Accepted", adr)
        self.assertIn("AES-256-GCM", adr)
        self.assertIn("dedicated resolver service token", adr)
        self.assertIn("Phase 40 may extract or generalize", adr)
        self.assertIn("BYQ_CREDENTIAL_KEYRING", contract)
        self.assertIn("BYQ_CREDENTIAL_ACTIVE_KEY_ID", contract)
        self.assertIn("BYQ_CREDENTIAL_RESOLVER_TOKEN", contract)
        self.assertIn("A user binding never", contract)
        self.assertIn("Current completed phase: **Phase 43**", status)
        self.assertIn("Phase 40 (Shared components and final parity closure) completed", status)
        self.assertIn(
            "Accepted conversation-first Product experience ADR: **ADR-0024**",
            status,
        )
        self.assertIn("D-0008 is CLOSED", status)
        self.assertNotIn("ADR-0019 remains Proposed", status)

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

    def test_signal_sandbox_is_credential_free_and_privilege_separated(self) -> None:
        sandbox = service_block("signal-sandbox")
        worker = service_block("signal-worker")
        compose = (ROOT / "compose.yml").read_text()
        dockerfile = (ROOT / "services/signal-sandbox/Dockerfile").read_text()

        self.assertIn("read_only: true", sandbox)
        self.assertIn("cap_drop:", sandbox)
        self.assertIn("- ALL", sandbox)
        self.assertIn("no-new-privileges:true", sandbox)
        self.assertIn("pids_limit:", sandbox)
        self.assertIn("mem_limit:", sandbox)
        self.assertNotRegex(sandbox, r"(?i)(database_url|token|password|credential|tushare|dsh|mcp)")
        self.assertNotIn("byq_product", sandbox)
        self.assertIn("byq_signal_sandbox", sandbox)
        self.assertIn("internal: true", compose)
        self.assertIn("BYQ_DATABASE_URL", worker)
        self.assertNotIn("ports:", sandbox)
        self.assertNotIn("COPY services/backend", dockerfile)
        self.assertNotIn("COPY .", dockerfile)

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
        self.assertIn("BYQ_DATABASE_URL", backend)
        self.assertNotIn("BYQ_DOMAIN_DB_PATH", compose)
        self.assertIn("byq_domain_state:/var/lib/byq/domain", backend)
        self.assertIn("byq_domain_state:", compose)
        for service in ("gateway", "runtime-adapter", "mcp"):
            block = service_block(service)
            self.assertNotIn("BYQ_DOMAIN_DB_PATH", block)
            self.assertNotIn("BYQ_DATABASE_URL", block)
            self.assertNotIn("byq_domain_state", block)

        # ADR-0016 Stage 6: SQLite is removed from runtime store code paths; the
        # only remaining sqlite3 import is the read-only migration export tool.
        sqlite_importers = sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "services/backend/app").rglob("*.py")
            if "import sqlite3" in path.read_text()
        )
        self.assertEqual(sqlite_importers, ["services/backend/app/sqlite_export.py"])

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

    def test_phase15_engineering_task_is_not_exposed_to_product_plane(self) -> None:
        mcp = "\n".join(
            path.read_text() for path in (ROOT / "services/mcp/src").rglob("*.ts")
        )
        self.assertNotIn("byq_engineering_", mcp)

        roles = (ROOT / "services/backend/app/agent_research.py").read_text()
        self.assertNotIn("byq_engineering_", roles)

        backend_files = "\n".join(
            path.read_text() for path in (ROOT / "services/backend/app").rglob("*.py")
        )
        self.assertIn("engineering_tasks", backend_files)

    def test_phase16_product_api_is_gateway_owned_and_safe(self) -> None:
        gateway = "\n".join(
            path.read_text() for path in (ROOT / "services/gateway").rglob("*.py")
        )
        self.assertIn("/api/product", gateway)
        self.assertNotIn("BYQ_MCP_TOKEN", gateway)
        self.assertNotIn("deepseek_harness", gateway)
        self.assertNotIn("api.tushare.pro", gateway)

        self.assertIn("BYQ_BACKEND_URL: http://backend:8000", service_block("gateway"))
        openapi = (ROOT / "docs/contracts/product-api.openapi.yaml").read_text()
        self.assertIn("openapi: 3.0.3", openapi)
        self.assertIn("sessionCookie:", openapi)
        self.assertIn("Internal/bootstrap compatibility only", openapi)
        self.assertNotIn("TUSHARE_TOKEN", openapi)
        self.assertNotIn("BYQ_MCP_TOKEN", openapi)

        documented: set[tuple[str, str]] = set()
        current_path: str | None = None
        for line in openapi.splitlines():
            path_match = re.fullmatch(r"  (/[^:]+):", line)
            if path_match:
                current_path = path_match.group(1)
                continue
            method_match = re.fullmatch(r"    (get|post|put|delete):.*", line)
            if current_path and method_match:
                documented.add((method_match.group(1), current_path))

        implemented: set[tuple[str, str]] = set()
        for relative, prefix in (
            ("services/gateway/app/product_api.py", "/api/product"),
            ("services/gateway/app/auth_api.py", "/api/auth"),
        ):
            source = (ROOT / relative).read_text()
            implemented.update(
                (method, prefix + path)
                for method, path in re.findall(
                    r'(?m)^@router\.(get|post|put|delete)\("([^"]+)"',
                    source,
                )
            )
        main_source = (ROOT / "services/gateway/app/main.py").read_text()
        implemented.update(
            (method, path)
            for method, path in re.findall(
                r'(?m)^@app\.(get|post|put|delete)\("([^"]+)"',
                main_source,
            )
            if path.startswith(("/v1/agent", "/v1/workflows"))
        )
        self.assertEqual(documented, implemented)

    def test_phase23_historical_parity_matrix_and_ui_smoke_exist(self) -> None:
        matrix = ROOT / "docs/roadmap/COMMUNITY_FEATURE_PARITY_MATRIX.md"
        self.assertTrue(matrix.exists())
        self.assertIn("Release-candidate conclusion", matrix.read_text())
        e2e = (ROOT / "apps/frontend/tests/e2e/app.spec.ts").read_text()
        self.assertIn("authenticated dashboard shows resource cards", e2e)

    def test_roadmap_truth_sources_are_current_and_consistent(self) -> None:
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        completed = re.search(r"Current completed phase: \*\*Phase (\d+)\*\*", status)
        self.assertIsNotNone(completed)
        completed_phase = int(completed.group(1))

        readme = (ROOT / "README.md").read_text()
        self.assertIn(f"completed project stage is **Phase {completed_phase}**", readme)

        implementation = (ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md").read_text()
        self.assertIn("Phase 34 — Stock Pool depth (`COMPLETE`)", implementation)
        self.assertIn("Phase 35 — Paper Trading depth (`COMPLETE`)", implementation)
        self.assertIn(
            "Phase 36 — Agent workbench depth (`COMPLETE`)",
            implementation,
        )
        self.assertIn("Phase 37 — My Space depth (`COMPLETE`)", implementation)
        self.assertIn(
            "Phase 38 — Operations workbenches (`COMPLETE`)",
            implementation,
        )
        self.assertIn(
            "Phase 39 — Data Center / Data Sync depth (`COMPLETE`)",
            implementation,
        )
        self.assertIn(
            "Phase 40 — Shared components and final parity closure (`COMPLETE`)",
            implementation,
        )
        self.assertIn(
            "Phase 41 — Product experience baseline (`COMPLETE`)",
            implementation,
        )
        self.assertIn(
            "Phase 42 — Conversation-first Product shell (`COMPLETE`)",
            implementation,
        )
        self.assertIn(
            "Phase 43 — Durable conversations and Xiaoba workspace (`COMPLETE`)",
            implementation,
        )
        self.assertIn(
            "Phase 44 — User center and durable appearance (`NEXT`)",
            implementation,
        )

        workflow_card_adr = (
            ROOT
            / "docs/architecture/adr/ADR-0018-workflow-trace-card-contract.md"
        ).read_text()
        self.assertIn("- Status: Accepted", workflow_card_adr)
        self.assertIn("Cards are not commands", workflow_card_adr)
        workflow_card_contract = (
            ROOT / "docs/contracts/workflow-trace-cards.md"
        ).read_text()
        self.assertIn("workflow-card.v1", workflow_card_contract)
        self.assertIn("owner-scoped Product API", workflow_card_contract)

        credential_adr = (
            ROOT
            / "docs/architecture/adr/ADR-0019-encrypted-credential-store.md"
        ).read_text()
        self.assertIn("- Status: Accepted", credential_adr)
        self.assertIn("private Backend-to-Adapter seam", credential_adr)

        stock_pool_adr = (
            ROOT / "docs/architecture/adr/ADR-0020-stock-pool-snapshot-lifecycle.md"
        ).read_text()
        self.assertIn("- Status: Accepted", stock_pool_adr)
        self.assertIn("stock_pool_snapshot_id", stock_pool_adr)
        stock_pool_contract = (ROOT / "docs/contracts/stock-pool.md").read_text()
        self.assertIn("expected_current_snapshot_id", stock_pool_contract)
        self.assertIn("Chrome MCP evidence", stock_pool_contract)
        self.assertTrue(
            (ROOT / "docs/evidence/phase-34/byq-stock-pool/README.md").exists()
        )
        paper_adr = (
            ROOT / "docs/architecture/adr/ADR-0021-paper-trading-account-lifecycle.md"
        ).read_text()
        self.assertIn("- Status: Accepted", paper_adr)
        self.assertTrue(
            (ROOT / "docs/evidence/phase-35/byq-paper-trading/README.md").exists()
        )

        parity_plan = (ROOT / "docs/roadmap/COMMUNITY_FULL_PARITY_PLAN.md").read_text()
        self.assertIn("Status: `COMPLETE`", parity_plan)
        self.assertNotIn("ADR-0017/0018/0019 awaiting review", parity_plan)

        parity_matrix = (ROOT / "docs/roadmap/COMMUNITY_FEATURE_PARITY_MATRIX_V2.md").read_text()
        self.assertIn("superseded on 2026-08-23 by Accepted ADR-0024", parity_matrix)
        self.assertNotIn("not eligible for review", parity_matrix)
        self.assertTrue((ROOT / "docs/evidence/phase-40/GOLDEN_JOURNEY.json").exists())
        signal_adr = (
            ROOT / "docs/architecture/adr/ADR-0023-isolated-signal-producer.md"
        ).read_text()
        self.assertIn("- Status: Accepted", signal_adr)
        experience_adr = (
            ROOT
            / "docs/architecture/adr/ADR-0024-conversation-first-product-experience.md"
        ).read_text()
        self.assertIn("- Status: Accepted", experience_adr)
        self.assertIn(
            "BYQ Backend owns a durable, owner-scoped Product conversation catalog",
            experience_adr,
        )
        self.assertIn(
            "Appearance is a durable, user-scoped BYQ preference",
            experience_adr,
        )
        self.assertTrue(
            (ROOT / "docs/evidence/phase-41/COMMUNITY_FEATURE_CHECKLIST.md").exists()
        )

    def test_completed_phases_have_no_open_deferred_items(self) -> None:
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        completed = re.search(r"Current completed phase: \*\*Phase (\d+)\*\*", status)
        self.assertIsNotNone(completed)
        completed_phase = int(completed.group(1))

        registry = (ROOT / "docs/roadmap/DEFERRED_ITEMS_REGISTRY.md").read_text()
        for match in re.finditer(r"(?ms)^### (D-\d+).*?(?=^### |\Z)", registry):
            block = match.group(0)
            phase = re.search(r"(?m)^- Phase: (\d+)", block)
            item_status = re.search(r"(?m)^- Status: `([A-Z_]+)`", block)
            self.assertIsNotNone(phase, match.group(1))
            self.assertIsNotNone(item_status, match.group(1))
            if int(phase.group(1)) <= completed_phase:
                self.assertIn(item_status.group(1), {"CLOSED", "DROPPED"}, match.group(1))

    def test_local_ci_isolated_mcp_contract_dependency(self) -> None:
        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertIn('CI_PG_NET="byq-ci-network-$BYQ_CI_SCOPE"', local_ci)
        self.assertIn(
            'BYQ_SIGNAL_SANDBOX_NETWORK_NAME="byq-ci-signal-sandbox-$BYQ_CI_SCOPE"',
            local_ci,
        )
        self.assertIn("--network-alias backend", local_ci)
        self.assertIn("ensure_ci_backend", local_ci)
        self.assertNotIn("CI_PG_NET=byq_product", local_ci)
        self.assertNotIn("npm run build >/tmp/byq-mcp-build.log 2>&1", local_ci)

    def test_frontend_ci_uses_locked_dependencies_and_honest_browser_tiers(self) -> None:
        frontend = ROOT / "apps/frontend"
        self.assertTrue((frontend / "package-lock.json").exists())

        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertIn("npm ci --no-audit --no-fund", local_ci)
        self.assertIn("npm audit --audit-level=high", local_ci)
        self.assertNotIn("npm install --no-audit --no-fund --no-package-lock", local_ci)

        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        self.assertIn(
            './scripts/ci/local-ci.sh --base="$BYQ_CI_BASE_SHA" --all --with-e2e --with-smoke',
            workflow,
        )
        self.assertIn("head.repo.full_name == github.repository", workflow)

        dockerfile = (frontend / "Dockerfile").read_text()
        self.assertIn("FROM node:22-bookworm-slim AS build", dockerfile)
        self.assertIn("COPY apps/frontend/package.json apps/frontend/package-lock.json", dockerfile)
        self.assertIn("RUN npm ci --no-audit --no-fund", dockerfile)

        mocked = (frontend / "tests/e2e/app.spec.ts").read_text()
        self.assertIn("mocked UI navigation covers core product routes", mocked)
        self.assertNotIn("golden journey covers login", mocked)

        real = (frontend / "tests/e2e/real-product.spec.ts").read_text()
        self.assertIn("real Product API login and Stock Pool create flow", real)
        self.assertNotIn("page.route(", real)

    def test_compose_smoke_resources_are_ci_isolatable(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        for variable in (
            "BYQ_FRONTEND_BIND",
            "BYQ_GATEWAY_BIND",
            "BYQ_PRODUCT_NETWORK_NAME",
            "BYQ_POSTGRES_VOLUME_NAME",
            "BYQ_DOMAIN_VOLUME_NAME",
            "BYQ_DSH_SESSIONS_VOLUME_NAME",
            "BYQ_WORKFLOW_TRACES_VOLUME_NAME",
        ):
            self.assertIn(variable, compose)

        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertIn('COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"', local_ci)
        self.assertIn('BYQ_FRONTEND_BIND="${BYQ_CI_FRONTEND_BIND:-127.0.0.1:0}"', local_ci)
        self.assertIn('BYQ_GATEWAY_BIND="${BYQ_CI_GATEWAY_BIND:-127.0.0.1:0}"', local_ci)
        self.assertIn("docker compose port frontend 80", local_ci)
        self.assertIn("docker compose port gateway 8100", local_ci)
        self.assertIn("npm run test:e2e:real", local_ci)
        self.assertIn("[ -x node_modules/.bin/playwright ] || npm ci", local_ci)
        self.assertIn("docker compose down --rmi local -v", local_ci)

        smoke = (ROOT / "tests/smoke/run.sh").read_text()
        self.assertNotIn('gateway = "http://127.0.0.1:8100/internal/runtime"', smoke)
        self.assertNotIn('urlopen("http://127.0.0.1:8100/', smoke)
        self.assertGreaterEqual(smoke.count("BYQ_SMOKE_GATEWAY_URL"), 3)

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
        contents = "\n".join(path.read_text() for path in implementation_files)
        self.assertIn("/api/product", contents)
        self.assertNotIn("deepseek_harness", contents)
        self.assertNotIn("session.event", contents)
        self.assertNotIn("BYQ_MCP_TOKEN", contents)
        self.assertNotIn("/mcp/v1", contents)
        readme = (frontend / "README.md").read_text()
        self.assertIn("must not depend directly on DSH internal event schemas", readme)

    def test_product_backend_proxy_calls_always_carry_trusted_context(self) -> None:
        source = (ROOT / "services/gateway/app/product_api.py").read_text()
        tree = ast.parse(source)
        missing_headers: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "_backend_request":
                continue
            if not any(keyword.arg == "headers" for keyword in node.keywords):
                missing_headers.append(node.lineno)
        self.assertEqual(missing_headers, [])

    def test_phase38_operations_stays_admin_only_and_normalized(self) -> None:
        gateway = (ROOT / "services/gateway/app/product_api.py").read_text()
        runtime = (ROOT / "services/runtime-adapter/app/runtime.py").read_text()
        frontend_api = (ROOT / "apps/frontend/src/api/operations.ts").read_text()
        contract = (ROOT / "docs/contracts/operations-api.md").read_text()

        self.assertIn('user.get("role") != "admin"', gateway)
        self.assertIn('/v1/operations/overview', gateway)
        self.assertIn('/internal/runtime/operations', gateway)
        self.assertIn('"raw_dsh_events": False', runtime)
        self.assertIn('"source": "normalized_dsh_token_usage"', runtime)
        self.assertNotIn("notification.payload", frontend_api)
        self.assertNotIn("/v1/operations", frontend_api)
        self.assertNotIn("/internal/runtime", frontend_api)
        self.assertIn("/api/product/operations", frontend_api)
        self.assertIn("Redis", contract)
        self.assertIn("raw DSH", contract)


if __name__ == "__main__":
    unittest.main()
