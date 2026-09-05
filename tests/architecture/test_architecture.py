import ast
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def markdown_marker(contents: str, name: str) -> str:
    match = re.search(rf"(?m)^<!-- byq:{re.escape(name)}=([^ ]+) -->$", contents)
    if match is None:
        raise AssertionError(f"missing Markdown marker: {name}")
    return match.group(1)


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
    def test_frontend_proxy_does_not_buffer_workflow_sse(self) -> None:
        nginx = (ROOT / "apps/frontend/nginx.conf").read_text()
        self.assertIn("location /v1/workflows/", nginx)
        self.assertIn("proxy_buffering off", nginx)
        self.assertIn("proxy_cache off", nginx)
        self.assertIn("proxy_read_timeout 1h", nginx)

    def test_self_hosted_ci_uses_the_immutable_event_base(self) -> None:
        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()

        self.assertIn("BYQ_CI_BASE_SHA:", workflow)
        self.assertIn('--base="$BYQ_CI_BASE_SHA"', workflow)
        self.assertNotIn("--depth=1 origin main", workflow)
        self.assertIn('hygiene_command=(git diff --check "$DIFF_BASE" HEAD)', local_ci)
        self.assertIn('hygiene_command=(git diff --check "$DIFF_BASE")', local_ci)
        self.assertNotIn('git diff --check "$BASE_SHA"...HEAD', local_ci)

    def test_adr_0019_accepts_a_closed_secret_resolution_boundary(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0019-encrypted-credential-store.md").read_text()
        contract = (ROOT / "docs/contracts/credential-store.md").read_text()
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()

        self.assertIn("- Status: Accepted", adr)
        self.assertIn("AES-256-GCM", adr)
        self.assertIn("model_api_key", adr)
        self.assertIn("tushare_token", adr)
        self.assertIn("BYQ_CREDENTIAL_KEYRING", contract)
        self.assertIn("BYQ_CREDENTIAL_ACTIVE_KEY_ID", contract)
        self.assertIn("BYQ_CREDENTIAL_RESOLVER_TOKEN", contract)
        self.assertIn("credential-envelope.v1", contract)
        self.assertEqual(markdown_marker(status, "current-completed-phase"), "97")
        for adr_id in ("ADR-0024", "ADR-0025", "ADR-0026", "ADR-0027", "ADR-0034", "ADR-0035", "ADR-0037", "ADR-0038", "ADR-0039", "ADR-0040", "ADR-0041", "ADR-0042", "ADR-0043", "ADR-0044", "ADR-0048", "ADR-0049"):
            self.assertRegex(status, rf"(?m)^- .*\*\*{adr_id}\*\*")
        self.assertIn("D-0008", status)

    def test_phase72_keeps_lightgbm_in_the_isolated_credential_free_worker(self) -> None:
        adr = (
            ROOT
            / "docs/architecture/adr/ADR-0043-auditable-machine-learning-research-pipeline.md"
        ).read_text()
        contract = (ROOT / "docs/contracts/machine-learning-research.md").read_text()
        plan = (ROOT / "docs/roadmap/MACHINE_LEARNING_STRATEGY_PLAN.md").read_text()
        inventory = (ROOT / "docs/migration/COMMUNITY_MIGRATION_INVENTORY.md").read_text()
        backend_dependencies = (ROOT / "services/backend/pyproject.toml").read_text()
        compose = (ROOT / "compose.yml").read_text()
        worker_dockerfile = (ROOT / "workers/ml/Dockerfile").read_text()
        worker_source = (ROOT / "workers/ml/worker.py").read_text()
        prediction_source = (ROOT / "services/backend/app/ml_prediction.py").read_text()

        self.assertIn("- Status: Accepted", adr)
        self.assertIn("LightGBM 4.7.0", adr)
        self.assertIn("trusted ML Worker", adr)
        self.assertIn("Backtest Worker 继续只消费", adr)
        for schema in (
            "ml-strategy-version.v1",
            "ml-training-run.v1",
            "ml-feature-snapshot.v1",
            "ml-model-artifact.v1",
            "ml-prediction-snapshot.v1",
        ):
            self.assertIn(schema, contract)
        self.assertIn("Phase 71 — Contract baseline（`COMPLETE`）", plan)
        self.assertIn("Phase 72 — Trusted training and model artifact（`COMPLETE`）", plan)
        self.assertIn("Phase 73 — Out-of-sample prediction and signal closure（`COMPLETE`）", plan)
        self.assertIn("Phase 74 — Product closure（`COMPLETE`）", plan)
        self.assertIn("LightGBM golden journey 已通过 Phase 74 验收，但 HIST 尚未授权", plan)

        self.assertIn("Phase 71 machine-learning strategy pre-implementation audit", inventory)
        self.assertIn("`REFERENCE_ONLY` / `REPLACE`", inventory)
        self.assertNotIn('"lightgbm', backend_dependencies.lower())
        self.assertRegex(compose, r"(?m)^  ml-worker:")
        ml_worker = service_block("ml-worker")
        self.assertIn("workers/ml/Dockerfile", ml_worker)
        self.assertIn("byq_ml_model_state:/var/lib/byq/ml-objects", ml_worker)
        self.assertNotIn("byq_domain_state", ml_worker)
        self.assertIn("no-new-privileges:true", ml_worker)
        self.assertIn("cap_drop:", ml_worker)
        for secret in ("TUSHARE", "MODEL_API", "MCP_TOKEN", "CREDENTIAL"):
            self.assertNotIn(secret, ml_worker.upper())
        self.assertIn('"lightgbm==4.7.0"', worker_dockerfile)
        self.assertIn('"numpy==2.3.3"', worker_dockerfile)
        self.assertIn("libgomp1", worker_dockerfile)
        self.assertIn("USER byq", worker_dockerfile)
        self.assertIn('CMD ["python", "worker.py", "--healthcheck"]', worker_dockerfile)
        self.assertNotIn("pickle", worker_source.lower())
        self.assertNotIn("joblib", worker_source.lower())
        self.assertIn('PREDICTION_SCHEMA = "ml-prediction-snapshot.v1"', prediction_source)
        self.assertIn("score DESC, symbol ASC", contract)
        self.assertIn("normalize_signal_snapshot", prediction_source)
        self.assertNotIn("import lightgbm", prediction_source.lower())
        self.assertNotIn("import numpy", prediction_source.lower())
        self.assertIn("class LightGBMPredictor", worker_source)

    def test_phase83_freezes_extensible_ml_without_widening_runtime(self) -> None:
        adr = (
            ROOT
            / "docs/architecture/adr/ADR-0048-extensible-machine-learning-research.md"
        ).read_text()
        contract = (ROOT / "docs/contracts/machine-learning-extensibility.md").read_text()
        plan = (ROOT / "docs/roadmap/MACHINE_LEARNING_EXTENSIBILITY_PLAN.md").read_text()
        inventory = (ROOT / "docs/migration/COMMUNITY_MIGRATION_INVENTORY.md").read_text()

        self.assertIn("- Status: Accepted", adr)
        for identity in (
            "ml-capability-registry.v2",
            "ml-strategy-version.v2",
            "walk-forward-purged-v1",
            "byq-ridge-cpu-v1",
            "ml-regime-snapshot.v1",
            "ml-model-bundle.v1",
            "ml-routing-policy.v1",
        ):
            self.assertIn(identity, adr + contract)
        self.assertIn("v1-compat", contract)
        self.assertIn("000300.SH", contract)
        self.assertIn("Phase 83 — Extensibility contract baseline（`COMPLETE`）", plan)
        self.assertIn("Phase 84 — Capability registry, Ridge and walk-forward（`COMPLETE`）", plan)
        self.assertIn("Phase 83 extensible machine-learning classification", inventory)
        for prohibited in ("pickle/joblib", "AutoML", "在线学习"):
            self.assertIn(prohibited, adr)

    def test_phase84_qualifies_profiles_only_inside_the_ml_worker(self) -> None:
        registry = (ROOT / "services/backend/app/ml_capabilities.py").read_text()
        strategy = (ROOT / "services/backend/app/ml_strategy.py").read_text()
        training = (ROOT / "services/backend/app/ml_training.py").read_text()
        worker = (ROOT / "workers/ml/worker.py").read_text()
        backend_dependencies = (ROOT / "services/backend/pyproject.toml").read_text()
        plan = (ROOT / "docs/roadmap/MACHINE_LEARNING_EXTENSIBILITY_PLAN.md").read_text()
        evidence = (ROOT / "docs/evidence/phase-84/README.md").read_text()

        for identity in (
            "ml-capability-registry.v2", "walk-forward-purged-v1",
            "byq-lightgbm-cpu-v1", "byq-ridge-cpu-v1", "ridge-linear-json-v1",
        ):
            self.assertIn(identity, registry + worker)
        self.assertIn("validate_registry", registry)
        self.assertIn("capability_lock", registry)
        self.assertIn("generate_walk_forward_folds", training)
        self.assertIn("class QualifiedTrainer", worker)
        self.assertIn("class RidgeTrainer", worker)
        self.assertNotIn("pickle", worker.lower())
        self.assertNotIn("joblib", worker.lower())
        self.assertNotIn('"numpy', backend_dependencies.lower())
        self.assertNotIn('"lightgbm', backend_dependencies.lower())
        self.assertIn("Phase 84 — Capability registry, Ridge and walk-forward（`COMPLETE`）", plan)
        self.assertIn("Phase 85 — Regime snapshot, expert bundle and routing（`COMPLETE`）", plan)
        self.assertIn("v2 prediction fails closed", evidence)

    def test_phase85_freezes_regime_bundle_and_routes_before_backtest(self) -> None:
        registry = (ROOT / "services/backend/app/ml_capabilities.py").read_text()
        regime = (ROOT / "services/backend/app/ml_regime.py").read_text()
        training = (ROOT / "services/backend/app/ml_training.py").read_text()
        prediction = (ROOT / "services/backend/app/ml_prediction.py").read_text()
        worker = (ROOT / "workers/ml/worker.py").read_text()
        plan = (ROOT / "docs/roadmap/MACHINE_LEARNING_EXTENSIBILITY_PLAN.md").read_text()
        evidence = (ROOT / "docs/evidence/phase-85/README.md").read_text()

        for identity in (
            "hs300-trend-volatility-v1", "regime-expert-map-v1",
            "ml-regime-snapshot.v1", "ml-model-bundle.v1",
            "ml-prediction-snapshot.v2",
        ):
            self.assertIn(identity, registry + regime + training + prediction)
        self.assertIn("class QualifiedPredictor", worker)
        self.assertIn("RidgePredictor", worker)
        self.assertNotIn("import lightgbm", prediction.lower())
        self.assertNotIn("import numpy", prediction.lower())
        self.assertIn("Phase 85 — Regime snapshot, expert bundle and routing（`COMPLETE`）", plan)
        self.assertIn("Phase 86 — Product and Xiaoba closure（`COMPLETE`）", plan)
        self.assertIn("Backtest only consumes the frozen signal", evidence)

    def test_phase86_uses_dynamic_paged_product_and_mcp_ml_surfaces(self) -> None:
        frontend = (ROOT / "apps/frontend/src/components/MLResearchWorkbench.vue").read_text()
        gateway = (ROOT / "services/gateway/app/product_api.py").read_text()
        mcp = (ROOT / "services/mcp/src/server.ts").read_text()
        skill = (ROOT / "plugins/dsh-byq/skills/byq-ml-researcher/SKILL.md").read_text()
        evidence = (ROOT / "docs/evidence/phase-86/README.md").read_text()

        self.assertIn("getMLCapabilities", frontend)
        self.assertIn("getMLStudies", frontend)
        self.assertIn("getMLStudy", frontend)
        self.assertNotIn("getMLWorkspace", frontend)
        self.assertIn('@router.get("/ml/studies")', gateway)
        self.assertIn('@router.get("/ml/studies/{strategy_artifact_id}")', gateway)
        self.assertIn('"byq_ml_studies"', mcp)
        self.assertIn('"byq_ml_study_get"', mcp)
        self.assertIn("system supports", skill)
        self.assertIn("this study configures", skill)
        self.assertIn("this run succeeded", skill)
        self.assertIn("Initial load made no detail or prediction-row request", evidence)

    def test_phase87_freezes_feedback_before_external_publication(self) -> None:
        adr = (
            ROOT
            / "docs/architecture/adr/ADR-0049-product-feedback-trusted-github-publisher.md"
        ).read_text()
        contract = (ROOT / "docs/contracts/product-feedback.md").read_text()
        plan = (ROOT / "docs/roadmap/PRODUCT_FEEDBACK_DELIVERY_PLAN.md").read_text()
        inventory = (ROOT / "docs/migration/COMMUNITY_MIGRATION_INVENTORY.md").read_text()
        evidence = (ROOT / "docs/evidence/phase-87/README.md").read_text()
        architecture = (ROOT / "ARCHITECTURE.md").read_text()

        self.assertIn("- Status: Accepted", adr)
        for invariant in (
            "Product Feedback domain",
            "transactional outbox",
            "feedback-publisher",
            "Issues: write",
            "普通用户永远不填写 GitHub",
            "Product DSH 不接收 GitHub 凭据",
        ):
            self.assertIn(invariant, adr)
        for schema in (
            "product-feedback.v1",
            "feedback-publication.v1",
            "feedback-outbox.v1",
            "feedback_fingerprint.v1",
        ):
            self.assertIn(schema, contract)
        self.assertIn("preview_hash", contract)
        self.assertIn("publisher_unconfigured", contract)
        self.assertIn("normal users configure no github", evidence.lower())
        self.assertIn("Phase 87 — Feedback contract and trusted-publisher baseline（`COMPLETE`）", plan)
        self.assertIn("Phase 88 — Durable feedback domain and Product API（`COMPLETE`）", plan)
        self.assertIn("Phase 87 Product Feedback pre-implementation audit", inventory)
        self.assertIn("`PORT_UX` + `PORT_TESTS`", inventory)
        self.assertIn("## P. Product Feedback 与外部 Issue 发布", architecture)
        self.assertIn("Frontend、Gateway、MCP 和 Backend MUST NOT 持有 GitHub credential", architecture)

    def test_phase88_keeps_feedback_durable_paged_and_github_free(self) -> None:
        backend = (ROOT / "services/backend/app/product_feedback.py").read_text()
        backend_api = (ROOT / "services/backend/app/main.py").read_text()
        gateway = (ROOT / "services/gateway/app/product_api.py").read_text()
        workspace = (ROOT / "services/backend/app/workspace_tenancy.py").read_text()
        openapi = (ROOT / "docs/contracts/product-api.openapi.yaml").read_text()
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        plan = (ROOT / "docs/roadmap/PRODUCT_FEEDBACK_DELIVERY_PLAN.md").read_text()
        evidence = (ROOT / "docs/evidence/phase-88/README.md").read_text()

        for table in (
            "product_feedback", "product_feedback_revisions", "product_feedback_audit",
            "product_feedback_publications", "product_feedback_outbox", "product_feedback_commands",
        ):
            self.assertIn(table, backend)
        self.assertIn("feedback-publication-preview.v1", backend)
        self.assertIn("submitted-feedback-snapshot.v1", backend)
        self.assertIn("publisher_unconfigured", backend)
        self.assertIn("FOR UPDATE", backend)
        self.assertNotIn("import httpx", backend)
        self.assertNotIn("import requests", backend)
        self.assertNotIn("api.github.com", backend)
        self.assertIn('@app.post("/v1/feedback/items/{feedback_id}/submit")', backend_api)
        self.assertIn('@app.post("/v1/feedback/moderation/items/{feedback_id}/{action}")', backend_api)
        self.assertIn('@router.get("/feedback/items")', gateway)
        self.assertIn('"product_feedback", "product_feedback_revisions", "product_feedback_audit"', workspace)
        self.assertIn("/api/product/feedback/items:", openapi)
        self.assertIn("<!-- byq:current-completed-phase=97 -->", status)
        self.assertIn("Phase 88 — Durable feedback domain and Product API（`COMPLETE`）", plan)
        self.assertIn("Phase 89 — Trusted GitHub publisher and operations（`COMPLETE`）", plan)
        self.assertIn("transaction rollback", evidence.lower())
        self.assertIn('@router.get("/feedback/moderation/items")', gateway)
        self.assertIn("_feedback_moderator_headers", gateway)
        self.assertIn('"product_feedback", "product_feedback_revisions", "product_feedback_audit"', workspace)
        self.assertIn("/api/product/feedback/items:", openapi)
        self.assertIn("/api/product/feedback/moderation/items:", openapi)

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
        self.assertIn("backend:\n        condition: service_healthy", worker)
        self.assertNotIn("ports:", sandbox)
        self.assertNotIn("COPY services/backend", dockerfile)
        self.assertNotIn("COPY .", dockerfile)

    def test_data_worker_is_trusted_but_not_an_agent_or_browser_boundary(self) -> None:
        worker = service_block("data-worker")
        dockerfile = (ROOT / "workers/data/Dockerfile").read_text()
        source = (ROOT / "workers/data/worker.py").read_text()

        self.assertIn("BYQ_DATABASE_URL", worker)
        self.assertIn("TUSHARE_TOKEN", worker)
        self.assertIn("no-new-privileges:true", worker)
        self.assertNotIn("ports:", worker)
        self.assertNotRegex(worker + source, r"(?i)(BYQ_MCP|DSH_|MODEL_API|docker\.sock)")
        self.assertIn("COPY services/backend/app", dockerfile)
        self.assertNotIn("COPY .", dockerfile)
        self.assertRegex(dockerfile, r"(?m)^USER byq$")

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
        compose = service_block("runtime-adapter") + service_block("mcp")
        dsh_files = [
            ROOT / "services/dsh/Dockerfile",
            ROOT / "services/dsh/README.md",
            ROOT / "plugins/dsh-byq/cordis.patch.yml",
        ]
        contents = compose + "\n" + (ROOT / "compose.dsh-web.yml").read_text() + "\n" + "\n".join(path.read_text() for path in dsh_files)
        self.assertNotRegex(contents, r"(?i)(github_token|gh_token|codex_auth|docker_host)")
        self.assertNotRegex(contents, r"(?i)(socat|nginx|iptables|network namespace|host network)")

    def test_phase89_isolates_the_only_github_credential_in_publisher(self) -> None:
        compose = (ROOT / "compose.yml").read_text()
        publisher = service_block("feedback-publisher")
        worker = (ROOT / "workers/feedback-publisher/publisher.py").read_text()
        dockerfile = (ROOT / "workers/feedback-publisher/Dockerfile").read_text()
        plan = (ROOT / "docs/roadmap/PRODUCT_FEEDBACK_DELIVERY_PLAN.md").read_text()
        evidence = (ROOT / "docs/evidence/phase-89/README.md").read_text()
        for service in ("frontend", "gateway", "runtime-adapter", "mcp", "backend", "data-worker", "signal-worker", "ml-worker"):
            self.assertNotRegex(service_block(service), r"(?i)(feedback_github_token|feedback_github_app_private)")
        self.assertIn("BYQ_FEEDBACK_GITHUB_TOKEN", publisher)
        self.assertIn("profiles:", publisher)
        self.assertIn("read_only: true", publisher)
        self.assertIn("cap_drop:", publisher)
        self.assertNotIn("BYQ_DATABASE_URL", publisher)
        self.assertNotIn("volumes:", publisher)
        self.assertNotRegex(publisher, r"(?i)(docker.sock|/workspace|/src|dsh)")
        self.assertIn("USER 10006:10006", dockerfile)
        self.assertNotRegex(worker, r"(?i)(subprocess|os.system|git |docker|postgres|psycopg|sqlalchemy)")
        self.assertIn("https://api.github.com", worker)
        self.assertIn("/repos/{config.repository}/issues", worker)
        self.assertIn("/internal/feedback-publications/claim", worker)
        self.assertNotIn("/pulls", worker)
        self.assertNotIn("/contents", worker)
        self.assertEqual(compose.count("BYQ_FEEDBACK_GITHUB_TOKEN"), 2)
        self.assertIn("Phase 89 — Trusted GitHub publisher and operations（`COMPLETE`）", plan)
        self.assertIn("Phase 90 — Product UI and Xiaoba closure（`COMPLETE`）", plan)
        self.assertIn("zero real github writes", evidence.lower())

    def test_phase92_central_feedback_hub_preserves_product_and_github_boundaries(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0052-central-feedback-hub-and-conversation-submission.md").read_text()
        backend = (ROOT / "services/backend/app/product_feedback.py").read_text()
        backend_api = (ROOT / "services/backend/app/main.py").read_text()
        hub = "\n".join(
            (ROOT / path).read_text()
            for path in (
                "services/feedback-hub-cloudflare/src/index.ts",
                "services/feedback-hub-cloudflare/src/contracts.ts",
            )
        )
        relay = (ROOT / "workers/feedback-hub-relay/relay.py").read_text()
        deployment = (ROOT / "deploy/feedback-hub-cloudflare/wrangler.hub.jsonc").read_text()
        skill = (ROOT / "plugins/dsh-byq/skills/byq-product-feedback/SKILL.md").read_text()
        self.assertIn("- Status: Accepted", adr)
        self.assertIn("product_feedback_hub_outbox", backend)
        self.assertIn('expected_action="byq_feedback_submit"', backend_api)
        self.assertIn('expected_resource_type="product_feedback"', backend_api)
        self.assertIn("central-feedback-intake.v1", hub)
        self.assertIn("HOURLY_LIMIT", hub)
        self.assertNotRegex(hub + relay, r"(?i)(dsh|codex|subprocess|os\.system|docker\.sock)")
        self.assertNotRegex(relay, r"(?i)(github_token|github_app|postgres|psycopg|sqlalchemy)")
        self.assertIn("jefison-x/BeyondQuant", deployment)
        self.assertIn("agent_approval_id", skill)
        self.assertIn("global approval", skill)

    def test_phase93_cloudflare_hub_keeps_github_credentials_in_queue_publisher(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0053-cloudflare-native-central-feedback-hub.md").read_text()
        hub = (ROOT / "services/feedback-hub-cloudflare/src/index.ts").read_text()
        publisher = (ROOT / "workers/feedback-publisher-cloudflare/src/index.ts").read_text()
        hub_config = (ROOT / "deploy/feedback-hub-cloudflare/wrangler.hub.jsonc").read_text()
        publisher_config = (ROOT / "deploy/feedback-hub-cloudflare/wrangler.publisher.jsonc").read_text()
        migration = (ROOT / "deploy/feedback-hub-cloudflare/migrations/0001_central_feedback.sql").read_text()
        self.assertIn("- Status: Accepted", adr)
        self.assertIn('"d1_databases"', hub_config)
        self.assertIn('"durable_objects"', hub_config)
        self.assertIn('"producers"', hub_config)
        self.assertIn('"consumers"', publisher_config)
        self.assertIn('"dead_letter_queue"', publisher_config)
        self.assertIn('"workers_dev": false', publisher_config)
        self.assertNotIn("BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY", hub + hub_config)
        self.assertNotRegex(publisher + publisher_config, r"(?i)(BYQ_DATABASE_URL|postgres|psycopg|sqlalchemy|docker\.sock|/contents|/pulls)")
        self.assertIn("BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY", publisher)
        self.assertIn("https://api.github.com", publisher)
        self.assertIn("jefison-x/BeyondQuant", publisher_config)
        self.assertIn("central_feedback_outbox", migration)
        self.assertIn("dispatchDue", hub)

    def test_phase94_cloudflare_git_deploy_is_two_project_fail_closed_and_portable(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0054-cloudflare-github-deployment.md").read_text()
        package = json.loads((ROOT / "deploy/feedback-hub-cloudflare/package.json").read_text())
        hub = json.loads((ROOT / "deploy/feedback-hub-cloudflare/wrangler.hub.jsonc").read_text())
        publisher = json.loads((ROOT / "deploy/feedback-hub-cloudflare/wrangler.publisher.jsonc").read_text())
        verifier = (ROOT / "deploy/feedback-hub-cloudflare/scripts/verify-git-deploy.mjs").read_text()
        hub_deploy = (ROOT / "deploy/feedback-hub-cloudflare/scripts/deploy-hub.mjs").read_text()
        runbook = (ROOT / "docs/operations/central-feedback-hub.md").read_text()
        workflows = "\n".join(path.read_text() for path in (ROOT / ".github/workflows").glob("*.yml"))
        self.assertIn("- Status: Accepted", adr)
        self.assertNotIn("database_id", hub["d1_databases"][0])
        self.assertEqual(hub["name"], "byq-feedback-hub")
        self.assertEqual(publisher["name"], "byq-feedback-publisher")
        self.assertNotIn("BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY", hub["secrets"]["required"])
        self.assertIn("BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY", publisher["secrets"]["required"])
        self.assertEqual(package["scripts"]["cloudflare:deploy:hub"], "node scripts/deploy-hub.mjs")
        self.assertIn('["d1", "list", "--json", "--config", config]', hub_deploy)
        self.assertIn('["d1", "create", databaseName, "--config", config]', hub_deploy)
        self.assertIn('["d1", "migrations", "apply", "DB", "--remote", "--config", config]', hub_deploy)
        self.assertIn('["deploy", "--config", config]', hub_deploy)
        self.assertNotIn("shell:", hub_deploy)
        self.assertIn("wrangler deploy --config wrangler.publisher.jsonc", package["scripts"]["cloudflare:deploy:publisher"])
        self.assertIn("D1 must remain eligible for automatic provisioning", verifier)
        self.assertIn("Production branch", runbook)
        self.assertIn("`main`", runbook)
        self.assertIn("npm run cloudflare:deploy:hub", runbook)
        self.assertIn("npm run cloudflare:deploy:publisher", runbook)
        self.assertNotRegex(workflows, r"(?i)(CLOUDFLARE_API_TOKEN|wrangler deploy)")

    def test_phase95_central_feedback_console_keeps_operator_secrets_and_issue_writes_isolated(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0055-central-feedback-moderation-console.md").read_text()
        hub = (ROOT / "services/feedback-hub-cloudflare/src/index.ts").read_text()
        console = (ROOT / "services/feedback-hub-cloudflare/src/admin-console.ts").read_text()
        publisher = (ROOT / "workers/feedback-publisher-cloudflare/src/index.ts").read_text()
        hub_config = json.loads((ROOT / "deploy/feedback-hub-cloudflare/wrangler.hub.jsonc").read_text())
        runbook = (ROOT / "docs/operations/central-feedback-hub.md").read_text()
        self.assertIn("- Status: Accepted", adr)
        self.assertEqual(hub_config["workers_dev"], False)
        self.assertIn("/admin", hub)
        self.assertIn("HttpOnly", hub)
        self.assertIn("SameSite=Strict", hub)
        self.assertIn("sameOriginUiRequest", hub)
        self.assertIn("content-security-policy", console)
        self.assertIn("textContent", console)
        self.assertNotIn("innerHTML", console)
        self.assertNotIn("localStorage", console)
        self.assertNotIn("sessionStorage", console)
        self.assertNotIn("BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY", hub + console + json.dumps(hub_config))
        self.assertNotIn("api.github.com", hub + console)
        self.assertIn("api.github.com", publisher)
        self.assertIn("/admin*", runbook)
        self.assertIn("/v1/admin/*", runbook)

    def test_phase96_direct_admin_password_is_throttled_without_making_access_mandatory(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0056-direct-admin-password-and-login-throttling.md").read_text()
        architecture = (ROOT / "ARCHITECTURE.md").read_text()
        hub = (ROOT / "services/feedback-hub-cloudflare/src/index.ts").read_text()
        console = (ROOT / "services/feedback-hub-cloudflare/src/admin-console.ts").read_text()
        hub_config = json.loads((ROOT / "deploy/feedback-hub-cloudflare/wrangler.hub.jsonc").read_text())
        runbook = (ROOT / "docs/operations/central-feedback-hub.md").read_text()
        self.assertIn("- Status: Accepted", adr)
        self.assertIn(
            {"name": "ADMIN_LOGIN_GATE", "class_name": "AdminLoginGate"},
            hub_config["durable_objects"]["bindings"],
        )
        self.assertEqual(
            hub_config["migrations"][-1],
            {"tag": "v2", "new_sqlite_classes": ["AdminLoginGate"]},
        )
        self.assertIn("ADMIN_LOGIN_MAX_FAILURES = 5", hub)
        self.assertIn("ADMIN_LOGIN_WINDOW_MS = 15 * 60 * 1000", hub)
        self.assertIn("ADMIN_LOGIN_LOCK_MS = 15 * 60 * 1000", hub)
        self.assertIn("transaction.setAlarm", hub)
        self.assertIn("async alarm()", hub)
        self.assertIn('request.headers.get("cf-connecting-ip")', hub)
        self.assertNotIn("x-forwarded-for", hub.lower())
        self.assertIn("central-feedback-admin-password.v1", hub)
        self.assertIn("central-feedback-admin-session.v2", hub)
        self.assertIn("管理员密码", console)
        self.assertNotIn("Hub Admin Token", console)
        self.assertIn("Cloudflare Access/Zero Trust 不是运行必需项", runbook)
        self.assertIn("Cloudflare Access MAY", architecture)
        self.assertNotIn("MUST 同时受\nCloudflare Access", architecture)

    def test_phase97_backtest_names_are_catalogue_metadata_not_execution_identity(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0057-backtest-readable-name-and-catalog-identity.md").read_text()
        backend = (ROOT / "services/backend/app/backtest.py").read_text()
        task_projection = (ROOT / "services/backend/app/backtest_task.py").read_text()
        frontend = (ROOT / "apps/frontend/src/views/BacktestView.vue").read_text()
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        evidence = (ROOT / "docs/evidence/phase-97/README.md").read_text()
        self.assertIn("- Status: Accepted", adr)
        self.assertIn("name TEXT NOT NULL DEFAULT '回测任务'", backend)
        self.assertIn('if key not in {"idempotency_key", "name"}', backend)
        self.assertIn("(name ILIKE :query OR job_id ILIKE :query)", backend)
        self.assertIn('"name": backtest_job.get("name")', task_projection)
        self.assertIn('label="回测名称"', frontend)
        self.assertIn('label="回测 ID"', frontend)
        self.assertIn('placeholder="搜索回测名称或 ID"', frontend)
        self.assertEqual(markdown_marker(status, "current-completed-phase"), "97")
        self.assertIn("real Product API", evidence)


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
        self.assertIn("WorkflowTraceEvent", workflow)

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
        self.assertIn("bearerBootstrap:", openapi)
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
        self.assertIn("Phase 23", matrix.read_text())
        e2e = (ROOT / "apps/frontend/tests/e2e/app.spec.ts").read_text()
        self.assertIn("authenticated dashboard shows resource cards", e2e)

    def test_roadmap_truth_sources_are_current_and_consistent(self) -> None:
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        completed_phase = int(markdown_marker(status, "current-completed-phase"))

        readme = (ROOT / "README.md").read_text()
        self.assertEqual(
            markdown_marker(readme, "current-completed-phase"),
            str(completed_phase),
        )

        implementation = (ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md").read_text()
        for phase in range(34, 58):
            self.assertRegex(
                implementation,
                rf"(?m)^###? Phase {phase}\b.*\(`COMPLETE`\)$",
            )

        workspace_adr = (
            ROOT
            / "docs/architecture/adr/ADR-0025-personal-workspace-tenancy.md"
        ).read_text()
        self.assertIn("- Status: Accepted", workspace_adr)
        self.assertIn("personal-workspace.v1", workspace_adr)
        self.assertIn("workspace_id", workspace_adr)
        workspace_contract = (
            ROOT / "docs/contracts/personal-workspace.md"
        ).read_text()
        self.assertIn("personal-workspace.v1", workspace_contract)
        self.assertIn('"membership_role": "owner"', workspace_contract)
        self.assertIn("Gateway/Product API", workspace_contract)

        workspace_source = (
            ROOT / "services/backend/app/workspace_tenancy.py"
        ).read_text()
        self.assertIn("workspace_migration_quarantine", workspace_source)
        self.assertIn("owner_has_no_exact_durable_user_workspace", workspace_source)
        workspace_table_block = workspace_source.split("WORKSPACE_TABLES", 1)[1].split(")", 1)[0]
        self.assertNotIn('"credentials"', workspace_table_block)

        workflow_card_adr = (
            ROOT
            / "docs/architecture/adr/ADR-0018-workflow-trace-card-contract.md"
        ).read_text()
        self.assertIn("- Status: Accepted", workflow_card_adr)
        self.assertIn("workflow-card.v1", workflow_card_adr)
        workflow_card_contract = (
            ROOT / "docs/contracts/workflow-trace-cards.md"
        ).read_text()
        self.assertIn("workflow-card.v1", workflow_card_contract)
        self.assertIn("schema_version", workflow_card_contract)

        credential_adr = (
            ROOT
            / "docs/architecture/adr/ADR-0019-encrypted-credential-store.md"
        ).read_text()
        self.assertIn("- Status: Accepted", credential_adr)
        self.assertIn("model_api_key", credential_adr)
        self.assertIn("tushare_token", credential_adr)

        stock_pool_adr = (
            ROOT / "docs/architecture/adr/ADR-0020-stock-pool-snapshot-lifecycle.md"
        ).read_text()
        self.assertIn("- Status: Accepted", stock_pool_adr)
        self.assertIn("stock_pool_snapshot_id", stock_pool_adr)
        stock_pool_contract = (ROOT / "docs/contracts/stock-pool.md").read_text()
        self.assertIn("expected_current_snapshot_id", stock_pool_contract)
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

        parity_matrix = (ROOT / "docs/roadmap/COMMUNITY_FEATURE_PARITY_MATRIX_V2.md").read_text()
        self.assertIn("ADR-0024", parity_matrix)
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
        self.assertIn("session_id", experience_adr)
        self.assertIn("color_mode", experience_adr)
        self.assertTrue(
            (ROOT / "docs/evidence/phase-41/COMMUNITY_FEATURE_CHECKLIST.md").exists()
        )

    def test_completed_phases_have_no_open_deferred_items(self) -> None:
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        completed_phase = int(markdown_marker(status, "current-completed-phase"))

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
        self.assertIn(
            "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml:/opt/byq/compositions/byq-product-sdk.cordis.yml:ro",
            local_ci,
        )
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
            './scripts/ci/local-ci.sh --base="$BYQ_CI_BASE_SHA" --with-e2e --auto-smoke',
            workflow,
        )
        self.assertIn('--all --with-e2e --with-smoke', workflow)
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
            "BYQ_POSTGRES_VOLUME_EXTERNAL",
            "BYQ_DOMAIN_VOLUME_NAME",
            "BYQ_DSH_SESSIONS_VOLUME_NAME",
            "BYQ_WORKFLOW_TRACES_VOLUME_NAME",
        ):
            self.assertIn(variable, compose)
        self.assertGreaterEqual(compose.count("COMPOSE_PROJECT_NAME"), 6)
        self.assertNotIn("BYQ_POSTGRES_VOLUME_NAME:-byq_postgres_data", compose)

        local_ci = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertIn('COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"', local_ci)
        self.assertIn('BYQ_FRONTEND_BIND="${BYQ_CI_FRONTEND_BIND:-127.0.0.1:0}"', local_ci)
        self.assertIn('BYQ_GATEWAY_BIND="${BYQ_CI_GATEWAY_BIND:-127.0.0.1:0}"', local_ci)
        self.assertIn("docker compose port frontend 80", local_ci)
        self.assertIn("docker compose port gateway 8100", local_ci)
        self.assertIn("npm run test:e2e:real", local_ci)
        self.assertIn("[ -x node_modules/.bin/playwright ] || npm ci", local_ci)
        cleanup = (ROOT / "scripts/ci/cleanup-resources.sh").read_text()
        self.assertIn("docker compose --profile feedback-publisher down --rmi local -v --remove-orphans", cleanup)

    def test_postgres_memory_baseline_is_bounded_and_configurable(self) -> None:
        compose = service_block("postgres")
        expected = {
            "shared_buffers=${BYQ_POSTGRES_SHARED_BUFFERS:-1GB}",
            "effective_cache_size=${BYQ_POSTGRES_EFFECTIVE_CACHE_SIZE:-4GB}",
            "maintenance_work_mem=${BYQ_POSTGRES_MAINTENANCE_WORK_MEM:-256MB}",
            "work_mem=${BYQ_POSTGRES_WORK_MEM:-4MB}",
        }
        for setting in expected:
            self.assertIn(setting, compose)
        self.assertNotIn("max_connections=", compose)

        example = (ROOT / ".env.example").read_text()
        for variable in (
            "BYQ_POSTGRES_SHARED_BUFFERS=1GB",
            "BYQ_POSTGRES_EFFECTIVE_CACHE_SIZE=4GB",
            "BYQ_POSTGRES_MAINTENANCE_WORK_MEM=256MB",
            "BYQ_POSTGRES_WORK_MEM=4MB",
        ):
            self.assertIn(variable, example)

        runbook = (ROOT / "docs/operations/postgresql-memory-tuning.md").read_text()
        self.assertIn("pg_stat_database", runbook)
        self.assertIn("回滚", runbook)

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
        self.assertIn('"deepseek-harness-sdk==0.1.1rc1"', pyproject)
        self.assertIn('"deepseek-harness-runtime-bin==0.1.1rc1"', pyproject)

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
            self.assertEqual(runtime_package["dependencies"][dependency], "0.1.1-rc.1")

        runtime_lock = json.loads(
            (ROOT / "services/runtime-adapter/runtime/package-lock.json").read_text()
        )
        deepseek_lock_packages = {
            path.removeprefix("node_modules/"): metadata["version"]
            for path, metadata in runtime_lock["packages"].items()
            if path.startswith("node_modules/@deepseek-ai/")
        }
        self.assertEqual(deepseek_lock_packages, runtime_package["dependencies"])
        dsh_versions = {
            version
            for name, version in deepseek_lock_packages.items()
            if name.startswith("@deepseek-ai/dsh-")
        }
        self.assertEqual(dsh_versions, {"0.1.1-rc.1"})
        self.assertTrue(
            all(
                not value.startswith(("^", "~"))
                for value in runtime_package["dependencies"].values()
            )
        )

    def test_runtime_adapter_does_not_mount_application_source(self) -> None:
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile").read_text()
        copy_lines = [line for line in dockerfile.splitlines() if line.startswith("COPY")]
        self.assertNotIn("COPY .", dockerfile)
        self.assertIn("packages/contracts", "\n".join(copy_lines))
        self.assertIn("BYQ_DSH_COMPOSITION_SOURCE=plugins/dsh-byq/compositions", dockerfile)
        self.assertIn("COPY ${BYQ_DSH_COMPOSITION_SOURCE}", "\n".join(copy_lines))
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
        self.assertNotIn("- byq_backtest_cancel\n", composition)

        role_contract = (ROOT / "services/backend/app/agent_research.py").read_text()
        self.assertIn("ROLE_CATALOG", role_contract)
        self.assertIn("agent_approvals", role_contract)
        self.assertIn("agent_audit", role_contract)
        self.assertNotIn("psycopg", role_contract.lower())

        runtime_dockerfile = (ROOT / "services/runtime-adapter/Dockerfile").read_text()
        self.assertIn("plugins/dsh-byq/skills /opt/dsh/bundles/dsh-byq/skills", runtime_dockerfile)

    def test_phase58_agent_actions_are_bounded_and_user_facing(self) -> None:
        role_skill = (ROOT / "plugins/dsh-byq/skills/byq-role-contracts/SKILL.md").read_text()
        market_skill = (ROOT / "plugins/dsh-byq/skills/byq-market-researcher/SKILL.md").read_text()
        strategy_skill = (ROOT / "plugins/dsh-byq/skills/byq-strategy-researcher/SKILL.md").read_text()
        strategy_mcp = (ROOT / "services/mcp/src/strategy.ts").read_text()
        adr = (ROOT / "docs/architecture/adr/ADR-0031-agent-domain-action-contract.md").read_text()

        self.assertIn("exact MCP tool name", role_skill)
        self.assertIn("Audit every distinct authorized", role_skill)
        self.assertIn("domain action separately", role_skill)
        self.assertIn("Never narrate role", role_skill)
        self.assertIn("IDs, skill loading", role_skill)
        self.assertIn("Authorize `byq_market_daily`", market_skill)
        self.assertIn("Cross-check every signed return", market_skill)
        self.assertIn("with exactly", strategy_skill)
        self.assertIn("one synchronous output method", strategy_skill)
        self.assertIn("retry once", strategy_skill)
        self.assertIn("`byq_strategy_version_create` separately", strategy_skill)
        self.assertIn("If no research task exists", strategy_skill)
        self.assertIn("do not reorder", strategy_skill)
        self.assertIn("strategyValidationInputSchema", strategy_mcp)
        self.assertIn("repair_limit: 1", strategy_mcp)
        self.assertIn("byq_pool_create", adr)

    def test_phase59_market_research_is_persisted_bounded_and_point_in_time(self) -> None:
        backend = (ROOT / "services/backend/app/market_readiness.py").read_text()
        mcp = (ROOT / "services/mcp/src/server.ts").read_text()
        translator = (ROOT / "services/mcp/src/market-data.ts").read_text()
        roles = (ROOT / "services/backend/app/agent_research.py").read_text()
        skill = (ROOT / "plugins/dsh-byq/skills/byq-market-researcher/SKILL.md").read_text()
        adr = (ROOT / "docs/architecture/adr/ADR-0032-agent-point-in-time-market-research.md").read_text()

        self.assertIn('"market-valuation-research.v1"', backend)
        self.assertIn('"market-fundamentals-research.v1"', backend)
        self.assertIn("effective_date<=:as_of_date", backend)
        self.assertIn("MAX_AGENT_RESEARCH_SYMBOLS = 20", backend)
        self.assertIn('"byq_market_valuation"', mcp)
        self.assertIn('"byq_market_fundamentals"', mcp)
        self.assertIn("/v1/data/research/valuation", translator)
        self.assertIn("/v1/data/research/fundamentals", translator)
        self.assertNotIn("tushare", translator.lower())
        self.assertIn('role_id="market_researcher"', roles)
        self.assertIn('version="2.0.0"', roles)
        self.assertIn("coverage.usable", skill)
        self.assertIn("Status: Accepted", adr)
        for prohibited in ("BaoStock", "AKShare", "VectorBT", "PydanticAI", "Hermes"):
            self.assertIn(prohibited, adr)

    def test_trusted_time_is_split_between_dsh_clock_and_byq_market_facts(self) -> None:
        plugin = (ROOT / "plugins/dsh-byq/runtime/byq-runtime-time-context.js").read_text()
        composition = (ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").read_text()
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile").read_text()
        verifier = (ROOT / "services/runtime-adapter/runtime/verify-time-context.mjs").read_text()
        backend = (ROOT / "services/backend/app/market_automation.py").read_text()
        mcp = (ROOT / "services/mcp/src/server.ts").read_text()
        roles = (ROOT / "services/backend/app/agent_research.py").read_text()
        adr = (ROOT / "docs/architecture/adr/ADR-0037-trusted-runtime-market-time.md").read_text()
        inventory = (ROOT / "docs/migration/COMMUNITY_MIGRATION_INVENTORY.md").read_text()

        self.assertIn("ctx.systemPrompt.context", plugin)
        self.assertIn("text: () => formatRuntimeClockContext(new Date(), timezone)", plugin)
        self.assertIn("不得据此推断交易日", plugin)
        self.assertIn("name: '../runtime/byq-runtime-time-context.js'", composition)
        self.assertIn("timezone: Asia/Shanghai", composition)
        self.assertIn("COPY plugins/dsh-byq/runtime /opt/byq/runtime", dockerfile)
        self.assertIn("node verify-time-context.mjs", dockerfile)
        self.assertIn("renderContextSnapshot", verifier)
        self.assertIn('"market-session-context.v1"', backend)
        self.assertIn('"byq_market_session_context"', mcp)
        self.assertIn('"byq_market_session_context"', roles)
        self.assertNotIn("fetch_trading_calendar", backend.split("def market_session_context", 1)[1].split("def ", 1)[0])
        self.assertIn("- Status: Accepted", adr)
        self.assertIn("PydanticAI", adr)
        self.assertIn("Post-Phase 62 trusted-time maintenance audit", inventory)

    def test_phase63_product_plugins_are_generated_and_cannot_online_install(self) -> None:
        composition = (ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").read_text()
        template = (ROOT / "plugins/dsh-byq/compositions/templates/byq-product-sdk.cordis.yml").read_text()
        runtime_source = "\n".join(
            path.read_text(errors="ignore")
            for path in (ROOT / "services/runtime-adapter").rglob("*")
            if path.is_file() and "package-lock" not in path.name
        )
        self.assertTrue(composition.startswith("# GENERATED by scripts/dsh/plugin_registry.py"))
        self.assertIn("# @byq-plugin-entries@", template)
        self.assertNotIn("npm install", runtime_source)
        self.assertNotIn("legacy-peer-deps", runtime_source)
        for prohibited in (
            "@deepseek-ai/dsh-shell", "@deepseek-ai/dsh-terminal",
            "@deepseek-ai/dsh-tool-bash", "@deepseek-ai/dsh-tool-fs",
            "@deepseek-ai/dsh-code-runtime", "@deepseek-ai/dsh-subprocess",
            "@deepseek-ai/dsh-tool-cordis",
        ):
            self.assertNotIn(prohibited, composition)
        self.assertNotIn("web_fetch", composition)
        self.assertIn("fetch: false", composition)

    def test_phase64_web_evidence_stays_research_only_and_mcp_owned(self) -> None:
        validator = (ROOT / "services/backend/app/web_research.py").read_text()
        research = (ROOT / "services/backend/app/research.py").read_text()
        mcp = (ROOT / "services/mcp/src/server.ts").read_text()
        skill = (ROOT / "plugins/dsh-byq/skills/byq-market-researcher/SKILL.md").read_text()
        composition = (ROOT / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml").read_text()
        adr = (ROOT / "docs/architecture/adr/ADR-0039-market-research-web-evidence.md").read_text()

        self.assertIn('SCHEMA_VERSION = "web-research-evidence.v1"', validator)
        self.assertIn('"deterministic_input": False', validator)
        self.assertIn('"authoritative_market_data": False', validator)
        self.assertIn("validate_web_research_evidence", research)
        self.assertIn('"byq_web_evidence_create"', mcp)
        self.assertIn("现有证据无法建立原因", skill)
        self.assertIn("`web_fetch` is unavailable", skill)
        self.assertNotIn("web_fetch", composition)
        self.assertIn("fetch: false", composition)
        self.assertIn("- Status: Accepted", adr)
        deterministic_consumers = "\n".join(
            (ROOT / relative).read_text()
            for relative in (
                "services/backend/app/factor_research.py",
                "services/backend/app/strategy_artifact.py",
                "services/backend/app/backtest.py",
                "services/backend/app/signal_producer.py",
            )
        )
        self.assertNotIn("web_research_evidence", deterministic_consumers)

    def test_phase65_plugin_center_has_no_install_or_runtime_control_path(self) -> None:
        backend = (ROOT / "services/backend/app/plugin_center.py").read_text()
        gateway = (ROOT / "services/gateway/app/product_api.py").read_text()
        frontend = (ROOT / "apps/frontend/src/api/plugins.ts").read_text()
        adr = (ROOT / "docs/architecture/adr/ADR-0040-plugin-center-deployment-control-plane.md").read_text()
        self.assertIn("awaiting_generation", backend)
        self.assertIn("expected_version", backend)
        self.assertIn("idempotency_key", backend)
        self.assertIn('qualification != "QUALIFIED"', backend)
        self.assertIn("_PROHIBITED", backend)
        self.assertIn('user.get("role") != "admin"', gateway)
        self.assertIn("desired_matches_active_plugins", gateway)
        self.assertIn("/api/product/plugins", frontend)
        self.assertNotIn("runtime-adapter", frontend)
        self.assertNotIn("/v1/plugin-center", frontend)
        for forbidden in ("npm install", "legacy-peer-deps", "docker.sock", "subprocess.", "os.system("):
            self.assertNotIn(forbidden, backend.lower())
            self.assertNotIn(forbidden, gateway.lower())
        self.assertIn("Status: Accepted", adr)

    def test_phase66_stock_pool_producer_contract_keeps_trusted_boundary(self) -> None:
        adr = (ROOT / "docs/architecture/adr/ADR-0041-trusted-stock-pool-producers.md").read_text()
        contract = (ROOT / "docs/contracts/stock-pool-producer.md").read_text()
        inventory = (ROOT / "docs/migration/COMMUNITY_MIGRATION_INVENTORY.md").read_text()
        self.assertIn("- Status: Accepted", adr)
        self.assertIn("stock_pool_materialization_runs", adr)
        self.assertIn("latest", adr)
        self.assertIn("arbitrary Python", adr)
        self.assertIn("Atomic promotion", contract)
        self.assertIn("Browser 不得", contract)
        self.assertIn("动态计数固定为零", inventory)
        self.assertIn("分类为 `DROP`", inventory)

    def test_phase67_index_pool_materializer_is_provider_free_and_product_normalized(self) -> None:
        producer = (ROOT / "services/backend/app/stock_pool_producer.py").read_text()
        worker = (ROOT / "workers/data/worker.py").read_text()
        gateway = (ROOT / "services/gateway/app/product_api.py").read_text()
        frontend = (ROOT / "apps/frontend/src/api/paper.ts").read_text()
        self.assertIn("market_index_weights", producer)
        self.assertIn("stock_pool_materialization_runs", producer)
        self.assertIn("snapshot_date<=:requested", producer)
        self.assertIn("materialize_claimed", worker)
        self.assertIn("/paper/index-pools", gateway)
        self.assertIn("/index-pools", frontend)
        self.assertNotIn("TushareProvider", producer)
        self.assertNotIn("fetch_index_weights", producer)
        self.assertNotIn("/v1/paper", frontend)

    def test_phase68_dynamic_pool_rule_is_closed_and_runs_in_trusted_worker(self) -> None:
        evaluator = (ROOT / "services/backend/app/dynamic_stock_pool.py").read_text()
        producer = (ROOT / "services/backend/app/stock_pool_producer.py").read_text()
        worker = (ROOT / "workers/data/worker.py").read_text()
        gateway = (ROOT / "services/gateway/app/product_api.py").read_text()
        frontend = (ROOT / "apps/frontend/src/api/paper.ts").read_text()
        self.assertIn("dynamic-stock-pool-rule.v1", evaluator)
        self.assertIn("MAX_FILTERS = 20", evaluator)
        self.assertIn("evaluate_dynamic_rule", producer)
        self.assertIn("enqueue_due_dynamic_runs", worker)
        self.assertIn("/paper/dynamic-pools/preview", gateway)
        self.assertIn("/dynamic-pools/preview", frontend)
        for forbidden in ("eval(", "exec(", "subprocess", "requests.", "http://", "https://"):
            self.assertNotIn(forbidden, evaluator)

    def test_phase69_stock_pool_closure_is_normalized_and_imports_are_inactive(self) -> None:
        producer = (ROOT / "services/backend/app/stock_pool_producer.py").read_text()
        paper = (ROOT / "services/backend/app/paper_trading.py").read_text()
        operations = (ROOT / "services/backend/app/operations.py").read_text()
        gateway = (ROOT / "services/gateway/app/product_api.py").read_text()
        frontend = (ROOT / "apps/frontend/src/api/paper.ts").read_text()
        self.assertIn("stock-pool-readiness.v1", producer)
        self.assertIn("import_inactive_definition", producer)
        self.assertIn("'pending',:provenance,:now,:now,'inactive',1", producer)
        self.assertIn("'draft',:fingerprint", producer)
        self.assertIn("stock-pool-snapshot-diff.v1", paper)
        self.assertIn('"raw_worker_payload": False', operations)
        self.assertIn("/paper/producer-imports", gateway)
        self.assertIn("/snapshot-diff", frontend)
        self.assertNotIn("/v1/paper", frontend)

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
        for boundary_name in (
            "Gateway",
            "Product API",
            "Backend",
            "MCP",
            "DSH",
            "PostgreSQL",
            "Redis",
        ):
            self.assertIn(boundary_name, readme)

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
