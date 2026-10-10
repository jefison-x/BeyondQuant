#!/usr/bin/env python3
"""Qualify the captured ACP batch through the F6 Product/Worker release fixture.

The fixture uses the exact captured 17-image run batch and official rc.2 ACP
Adapter/Product runner. A test-only local provider drives real Product API,
BeyondQuant MCP, Backend, Worker, terminal acknowledgement, restart, and browser
flows. It is integration evidence, not model-quality or production acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
PROJECT_PATTERN = re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z")
PORT_PATTERN = re.compile(r"127\.0\.0\.1:([1-9][0-9]{0,4})\Z")
WORKSPACE_PATTERN = re.compile(r"workspace_[0-9a-f]{32}\Z")
ACP_RELEASE = "dsh-v0.2.0-rc.2"
ACP_FAMILY = "dsh-v0.2.0-rc.2-acp"
CAPTURED_RUNNING_SERVICES = (
    "backend", "gateway", "runtime-adapter", "mcp", "frontend",
    "signal-sandbox", "signal-worker", "acp-product-runner",
    "acp-judgment-runner", "mcp-acp-judgment",
)


class FixtureFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _require(condition: bool, category: str) -> None:
    if not condition:
        raise FixtureFailure(category)


def _read_json(path: Path, category: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        raise FixtureFailure(category) from None
    if not isinstance(value, dict):
        raise FixtureFailure(category)
    return value


def _write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError:
        raise FixtureFailure("evidence_path_collision_or_unavailable") from None
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _run(args: list[str], *, env: dict[str, str], cwd: Path = ROOT,
         timeout: int = 60, category: str) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        raise FixtureFailure(category) from None
    if result.returncode != 0:
        raise FixtureFailure(category)
    return result.stdout


def _compose(files: list[Path], env: dict[str, str], project: str,
             *args: str, category: str = "compose_action_failed", timeout: int = 90) -> str:
    command = [sys.executable, str(ROOT / "scripts/dsh/acp_build.py"), "--",
               "docker", "compose", "-p", project]
    for path in files:
        command.extend(("-f", str(path)))
    command.extend(args)
    selected = dict(env)
    selected["COMPOSE_PROJECT_NAME"] = project
    selected["COMPOSE_FILE"] = os.pathsep.join(str(path) for path in files)
    return _run(command, env=selected, timeout=timeout, category=category)


def _docker_json(args: list[str], *, env: dict[str, str], category: str) -> object:
    output = _run(["docker", *args], env=env, timeout=30, category=category)
    try:
        return json.loads(output)
    except (ValueError, TypeError):
        raise FixtureFailure(category) from None


def _compose_files(environ: dict[str, str]) -> list[Path]:
    raw = environ.get("COMPOSE_FILE", "")
    _require(bool(raw), "compose_file_list_missing")
    files: list[Path] = []
    for item in raw.split(os.pathsep):
        candidate = Path(item).resolve(strict=True)
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            raise FixtureFailure("compose_file_outside_repository") from None
        _require(candidate.is_file(), "compose_file_missing")
        files.append(candidate)
    _require(len(files) >= 2, "managed_acp_compose_files_missing")
    return files


def _captured_batch(project: str, scope: str, env: dict[str, str]) -> tuple[dict, dict, dict]:
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.dsh.authoritative_version import load_authoritative_version
        from scripts.release import images
        selection = load_authoritative_version(ROOT)
        captured = images.read_captured_image_ids(images.capture_manifest_path(scope))
        identity = images.make_dsh_identity(
            selection, captured, images.acp_image_topology_from_compose(_compose_files(env)))
    except Exception:
        raise FixtureFailure("captured_image_manifest_invalid") from None
    _require(selection.get("release_id") == ACP_RELEASE
             and selection.get("compatibility_family") == ACP_FAMILY
             and selection.get("sdk_online_fallback") is False,
             "authoritative_acp_release_invalid")
    _require(len(captured) == 17, "captured_release_batch_incomplete")
    for service, expected in captured.items():
        tag = project + "-" + service
        image = _docker_json(["image", "inspect", tag], env=env,
                             category="captured_release_image_missing")
        _require(isinstance(image, list) and len(image) == 1
                 and isinstance(image[0], dict) and image[0].get("Id") == expected,
                 "captured_release_image_changed")
    return selection, captured, identity


def _authoritative_compose_environment(selection: dict, inherited: dict[str, str]) -> dict[str, str]:
    """Give nested Compose callers the same validated ACP selectors as _compose."""
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.dsh.acp_build import command_environment
        return command_environment(selection, inherited)
    except Exception:
        raise FixtureFailure("authoritative_compose_environment_invalid") from None


def _f6_driver_environment(selection: dict, inherited: dict[str, str],
                           gateway: str, evidence_path: Path) -> dict[str, str]:
    driver_env = _authoritative_compose_environment(selection, inherited)
    driver_env.update({"BYQ_GOLDEN_ORIGIN": gateway,
                       "BYQ_F6_EVIDENCE_PATH": str(evidence_path)})
    return driver_env


def _user_fixture_workspace(receipt: object) -> str:
    _require(isinstance(receipt, dict) and set(receipt) == {"owner", "workspace_id"}
             and receipt.get("owner") == "f6-chain-user"
             and isinstance(receipt.get("workspace_id"), str)
             and WORKSPACE_PATTERN.fullmatch(receipt["workspace_id"]) is not None,
             "f6_user_fixture_identity_invalid")
    return receipt["workspace_id"]


def _fixture_override(project: str) -> dict:
    entrypoint = ROOT / "scripts/evidence/acp-f6-runtime-entrypoint.py"
    tests = ROOT / "services/runtime-adapter/tests"
    _require(entrypoint.is_file() and tests.is_dir(), "acp_f6_fixture_source_missing")
    return {"services": {
        "backend": {"environment": {"BYQ_F6_EXECUTOR_ENABLED": "1"}},
        "gateway": {"environment": {"BYQ_F6_EXECUTOR_ENABLED": "1"}},
        "runtime-adapter": {
            # The unified image dispatcher ignores command for the adapter role.
            # Explicitly replace its entrypoint only in this scoped fixture.
            # The official per-role image also contains this venv interpreter.
            "entrypoint": ["/opt/byq-venv/bin/python3",
                           "/app/acp-f6-runtime-entrypoint.py"],
            # Do not pass the original image command as extra Python arguments.
            "command": [],
            "environment": {
                "BYQ_F6_EXECUTOR_ENABLED": "1",
                "BYQ_ACP_F6_RELEASE_FIXTURE": "1",
                "BYQ_F6_SYNTHETIC_RUNTIME": "1",
                "BYQ_F6_CI_PROJECT": project,
                "COMPOSE_PROJECT_NAME": project,
                "OPENCODE_API_KEY": "f6-synthetic-only",
            },
            "volumes": [
                {"type": "bind", "source": str(entrypoint),
                 "target": "/app/acp-f6-runtime-entrypoint.py", "read_only": True},
                {"type": "bind", "source": str(tests),
                 "target": "/app/tests", "read_only": True},
            ],
        },
    }}


def _container_image(files: list[Path], env: dict[str, str], project: str,
                     service: str, expected: str) -> None:
    raw = _compose(files, env, project, "ps", "-q", service,
                   category="captured_service_container_missing")
    identifiers = [item for item in raw.splitlines() if item]
    _require(len(identifiers) == 1 and re.fullmatch(r"[0-9a-f]{64}", identifiers[0]) is not None,
             "captured_service_container_ambiguous")
    inspected = _docker_json(["inspect", identifiers[0]], env=env,
                             category="captured_service_container_identity_invalid")
    _require(isinstance(inspected, list) and len(inspected) == 1
             and isinstance(inspected[0], dict), "captured_service_container_identity_invalid")
    container = inspected[0]
    labels = container.get("Config", {}).get("Labels") if isinstance(container.get("Config"), dict) else None
    state = container.get("State")
    _require(container.get("Image") == expected and isinstance(labels, dict)
             and isinstance(state, dict) and state.get("Running") is True
             and labels.get("com.docker.compose.project") == project
             and labels.get("com.docker.compose.service") == service,
             "captured_service_container_identity_mismatch")


def _verify_captured_running_services(files: list[Path], env: dict[str, str], project: str,
                                      image_ids: dict[str, str]) -> None:
    # PostgreSQL is a pinned Compose infrastructure image but is not part of
    # the 17-image application release batch. Bind it to the running scoped
    # service and the exact local tag used by compose.yml.
    postgres_images = _docker_json(["image", "inspect", "postgres:16-alpine"],
                                   env=env, category="postgres_image_missing")
    _require(isinstance(postgres_images, list) and len(postgres_images) == 1
             and isinstance(postgres_images[0], dict)
             and re.fullmatch(r"sha256:[0-9a-f]{64}", str(postgres_images[0].get("Id", "")))
             is not None, "postgres_image_identity_invalid")
    _container_image(files, env, project, "postgres", postgres_images[0]["Id"])
    for service in CAPTURED_RUNNING_SERVICES:
        _container_image(files, env, project, service, image_ids[service])


def _runtime_readiness(files: list[Path], env: dict[str, str], project: str,
                       release_id: str) -> None:
    code = ("import json,urllib.request; "
            "print(json.dumps(json.load(urllib.request.urlopen("
            "'http://127.0.0.1:8400/readyz',timeout=3))))")
    output = _compose(files, env, project, "exec", "-T", "runtime-adapter",
                      "python3", "-c", code, category="acp_adapter_readiness_failed")
    try:
        body = json.loads(output)
    except (ValueError, TypeError):
        raise FixtureFailure("acp_adapter_readiness_invalid") from None
    _require(isinstance(body, dict) and body.get("status") == "ok"
             and body.get("runtime_adapter") == "ready"
             and body.get("release_identity") == "matched"
             and body.get("release_id") == release_id
             and body.get("model_provider") == "opencode-go-chat"
             and body.get("model") == "deepseek-v4.1-flash"
             and body.get("process_ownership") == "one-per-root-turn",
             "acp_adapter_readiness_not_qualified")


def _loopback_origin(files: list[Path], env: dict[str, str], project: str,
                     service: str, port: str) -> str:
    raw = _compose(files, env, project, "port", service, port,
                   category="product_endpoint_discovery_failed")
    binding = raw.strip().splitlines()[-1] if raw.strip() else ""
    match = PORT_PATTERN.fullmatch(binding)
    _require(match is not None and int(match.group(1)) <= 65535,
             "product_endpoint_not_loopback")
    return "http://" + binding


def _validate_f6_evidence(primary_path: Path, closeout_path: Path) -> tuple[dict, dict]:
    primary = _read_json(primary_path, "f6_primary_evidence_missing")
    closeout = _read_json(closeout_path, "f6_closeout_evidence_missing")
    _require(primary.get("schema_version") == "f6-current-ci-evidence.v1"
             and primary.get("phase") == "primary" and primary.get("status") == "passed"
             and closeout.get("schema_version") == "f6-current-ci-evidence.v1"
             and closeout.get("phase") == "closeout" and closeout.get("status") == "passed",
             "f6_product_worker_chain_not_passed")
    checks = primary.get("checks")
    required = {
        "foreground_1_structured_audit", "foreground_2_structured_audit",
        "gateway_restart", "worker", "background_answer_and_settlement",
        "background_structured_audit", "request_gate", "background_domain_scope",
    }
    _require(isinstance(checks, dict) and required.issubset(checks)
             and checks.get("revoke") == "one_exact_post_and_get_confirmed_no_second_request",
             "f6_release_checks_incomplete")
    _require(primary.get("uncertain_actions") == [] and closeout.get("uncertain_actions") == [],
             "f6_business_outcome_unknown")
    audits = primary.get("structured_agent_audits")
    _require(isinstance(audits, dict) and set(audits) == {"fg1", "fg2", "background"},
             "f6_terminal_acknowledgements_missing")
    for stage in ("fg1", "fg2", "background"):
        audit = audits[stage]
        _require(isinstance(audit, dict) and audit.get("terminal") == "completed/closed"
                 and isinstance(audit.get("runtime_root_id"), str)
                 and isinstance(audit.get("agent_run_id"), str),
                 "f6_terminal_acknowledgement_invalid")
    return primary, closeout


def _provider_diagnostics(env: dict[str, str], project: str) -> dict:
    output = _run([sys.executable, str(ROOT / "scripts/ci/f6-provider-diagnostics.py"),
                   "--project", project], env=env, timeout=40,
                   category="f6_provider_diagnostics_failed")
    prefix = "F6 provider diagnostics: "
    line = next((row for row in output.splitlines() if row.startswith(prefix)), None)
    if line is None:
        raise FixtureFailure("f6_provider_diagnostics_invalid")
    try:
        report = json.loads(line[len(prefix):])
    except (ValueError, TypeError):
        raise FixtureFailure("f6_provider_diagnostics_invalid") from None
    records = report.get("records") if isinstance(report, dict) else None
    _require(report.get("status") == "validated" and isinstance(records, list)
             and not report.get("overflow"), "f6_provider_diagnostics_unqualified")
    for stage in ("fg1", "fg2", "background"):
        selected = [row for row in records if isinstance(row, dict) and row.get("stage") == stage]
        _require(bool(selected) and all(row.get("outcome") == "response_written" for row in selected),
                 "f6_synthetic_provider_stage_unqualified")
    return report


def _auth_preflight(project: str, frontend: str, evidence_dir: Path,
                    env: dict[str, str]) -> dict:
    auth_dir = evidence_dir / "f6-acp-auth"
    auth_dir.mkdir(mode=0o700)
    minimal = {
        "PATH": env.get("PATH", ""), "HOME": env.get("HOME", "/tmp"),
        "COMPOSE_PROJECT_NAME": project, "BYQ_F6_AUTH_CI_PROJECT": project,
        "BYQ_REAL_BASE_URL": frontend,
        "BYQ_F6_AUTH_EVIDENCE_DIR": str(auth_dir),
        "BYQ_E2E_ADMIN_USERNAME": "f6-chain-user",
        "BYQ_E2E_ADMIN_PASSWORD": "test-password-123",
    }
    if env.get("PLAYWRIGHT_BROWSERS_PATH"):
        minimal["PLAYWRIGHT_BROWSERS_PATH"] = env["PLAYWRIGHT_BROWSERS_PATH"]
    node = shutil.which("node", path=minimal["PATH"])
    _require(node is not None, "f6_browser_runtime_missing")
    _run([node, str(ROOT / "apps/frontend/tests/e2e/f6-auth-preflight.mjs")],
         env=minimal, timeout=70, category="f6_browser_auth_preflight_failed")
    result = _read_json(auth_dir / "browser-result.json", "f6_browser_auth_evidence_missing")
    _require(result.get("status") == "PASS_SCOPED_CI_F6_LOGIN"
             and result.get("login_posts") == 1 and result.get("logout_posts") == 1
             and result.get("me_status") == 200 and result.get("exact_user") is True
             and result.get("workspace_present") is True
             and result.get("logout_status") == 200
             and result.get("logout_receipt_confirmed") is True
             and result.get("logout_readback") == 401
             and result.get("browser_closed") is True
             and result.get("unexpected_writes") == 0
             and result.get("foreign_requests") == 0
             and result.get("page_errors") == 0,
             "f6_browser_auth_closeout_unconfirmed")
    return result


def _playwright(browser_config: Path, evidence_path: Path, frontend: str,
                project: str, output_dir: Path, env: dict[str, str]) -> dict:
    executable = ROOT / "apps/frontend/node_modules/.bin/playwright"
    _require(executable.is_file(), "f6_playwright_binary_missing")
    output_dir.mkdir(mode=0o700)
    minimal = {
        "PATH": env.get("PATH", ""), "HOME": env.get("HOME", "/tmp"),
        "COMPOSE_PROJECT_NAME": project, "BYQ_REAL_BASE_URL": frontend,
        "BYQ_F6_EVIDENCE_PATH": str(evidence_path),
    }
    if env.get("PLAYWRIGHT_BROWSERS_PATH"):
        minimal["PLAYWRIGHT_BROWSERS_PATH"] = env["PLAYWRIGHT_BROWSERS_PATH"]
    output = _run([str(executable), "test", "--config", str(browser_config),
                   "--output", str(output_dir), "--reporter=json"],
                  env=minimal, cwd=ROOT / "apps/frontend", timeout=360,
                  category="f6_product_api_browser_failed")
    try:
        report = json.loads(output)
    except (ValueError, TypeError):
        raise FixtureFailure("f6_product_api_browser_report_invalid") from None
    stats = report.get("stats") if isinstance(report, dict) else None
    _require(isinstance(stats, dict) and stats.get("expected") == 2
             and stats.get("unexpected") == 0 and stats.get("skipped") == 0
             and stats.get("flaky") == 0,
             "f6_product_api_browser_acceptance_incomplete")
    return {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise FixtureFailure("f6_evidence_hash_unavailable") from None


def run() -> dict:
    env = dict(os.environ)
    project = env.get("COMPOSE_PROJECT_NAME", "")
    scope = env.get("BYQ_CI_SCOPE", "")
    _require(PROJECT_PATTERN.fullmatch(project) is not None
             and project == "byq-ci-stack-" + scope,
             "isolated_release_compose_scope_required")
    _require(env.get("BYQ_F6_EXECUTOR_ENABLED") == "0",
             "f6_must_start_disabled_in_base_compose")
    base_files = _compose_files(env)
    # Validate the captured batch before creating any per-run artifacts or
    # inspecting containers. A missing or incomplete release identity must
    # fail without touching the test stack.
    selection, image_ids, dsh_identity = _captured_batch(project, scope, env)
    fixture_env = _authoritative_compose_environment(selection, env)
    evidence_dir = (ROOT / ".ci-artifacts" / scope).resolve()
    try:
        evidence_dir.relative_to(ROOT)
    except ValueError:
        raise FixtureFailure("evidence_directory_outside_repository") from None
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(evidence_dir, 0o700)
    except OSError:
        raise FixtureFailure("evidence_directory_unavailable") from None
    primary_path = evidence_dir / "f6-acp-chain.json"
    closeout_path = evidence_dir / "f6-acp-chain.json.closeout.json"
    result_path = evidence_dir / "f6-acp-release-result.json"
    override_path = evidence_dir / "f6-acp-compose-override.json"
    _require(not any(path.exists() for path in (primary_path, closeout_path, result_path, override_path)),
             "f6_release_evidence_path_already_exists")

    override_content = (json.dumps(_fixture_override(project), sort_keys=True,
                                   separators=(",", ":")) + "\n").encode("utf-8")
    _write_private(override_path, override_content)
    fixture_files = [*base_files, override_path]
    fixture_env["COMPOSE_PROJECT_NAME"] = project
    fixture_env["COMPOSE_FILE"] = os.pathsep.join(str(path) for path in fixture_files)
    fixture_env["BYQ_F6_CI_PROJECT"] = project
    base_env = dict(env)
    base_env["BYQ_F6_EXECUTOR_ENABLED"] = "0"
    base_env.pop("BYQ_ACP_F6_RELEASE_FIXTURE", None)
    base_env.pop("BYQ_F6_SYNTHETIC_RUNTIME", None)
    touched = False
    result: dict | None = None
    failure: FixtureFailure | None = None
    try:
        # Create the isolated test user before choosing the ACP Product slot.
        # A real personal workspace is a random durable identity; the static
        # Compose placeholder cannot authorize this user's Product session.
        _compose(base_files, base_env, project, "cp",
                 str(ROOT / "scripts/evidence/f6-chain-fixture.py"),
                 "backend:/tmp/f6-chain-fixture.py", category="f6_user_fixture_copy_failed")
        user_output = _compose(base_files, base_env, project, "exec", "-T",
                               "-e", "BYQ_F6_FIXTURE=1", "-e", "COMPOSE_PROJECT_NAME=" + project,
                               "-e", "BYQ_F6_CI_PROJECT=" + project,
                               "backend", "python", "/tmp/f6-chain-fixture.py", "user",
                               category="f6_user_fixture_failed")
        try:
            user_receipt = json.loads(user_output)
        except (ValueError, TypeError):
            raise FixtureFailure("f6_user_fixture_receipt_invalid") from None
        prepared_workspace_id = _user_fixture_workspace(user_receipt)
        fixture_env["BYQ_ACP_PRODUCT_WORKSPACE_ID"] = prepared_workspace_id

        # Keep F6 Product data and control volumes separate from the bootstrap
        # admin workspace. The admin stack is restored after the fixture, so
        # sharing these names would let the F6 user overwrite admin slot state.
        product_volume_keys = (
            "BYQ_ACP_PRODUCT_SESSIONS_VOLUME_NAME",
            "BYQ_ACP_PRODUCT_STATE_VOLUME_NAME",
            "BYQ_ACP_PRODUCT_CONTROL_VOLUME_NAME",
        )
        expected_admin_volume_names = (
            project + "-acp-product-sessions",
            project + "-acp-product-state",
            project + "-acp-product-control",
        )
        _require(tuple(base_env.get(key) for key in product_volume_keys)
                 == expected_admin_volume_names,
                 "admin_product_volume_binding_invalid")
        f6_volume_names = (
            project + "-f6-acp-product-sessions",
            project + "-f6-acp-product-state",
            project + "-f6-acp-product-control",
        )
        _require(len(set(f6_volume_names)) == 3
                 and set(f6_volume_names).isdisjoint(expected_admin_volume_names),
                 "f6_product_volume_binding_invalid")
        fixture_env.update(dict(zip(product_volume_keys, f6_volume_names, strict=True)))

        # This F6 opt-in is scoped to the run Compose project. All three DSH
        # roles and every product image stay pinned to the captured batch.
        touched = True
        _compose(fixture_files, fixture_env, project, "up", "-d", "--pull", "never",
                 "--no-build", "--force-recreate", "--no-deps", "--wait",
                 "acp-product-runner", category="acp_f6_product_slot_start_failed", timeout=240)
        _compose(fixture_files, fixture_env, project, "up", "-d", "--pull", "never",
                 "--no-build", "--force-recreate", "--no-deps", "--wait",
                 "backend", "gateway", "runtime-adapter",
                 category="acp_f6_stack_start_failed", timeout=240)
        # The Backend recreation discards the earlier user-preparation script.
        # Copy it into the running fixture Backend for read-only AgentRun audits.
        _compose(fixture_files, fixture_env, project, "cp",
                 str(ROOT / "scripts/evidence/f6-chain-fixture.py"),
                 "backend:/tmp/f6-chain-fixture.py", category="f6_audit_fixture_copy_failed")
        _verify_captured_running_services(fixture_files, fixture_env, project, image_ids)
        _runtime_readiness(fixture_files, fixture_env, project, ACP_RELEASE)
        frontend = _loopback_origin(fixture_files, fixture_env, project, "frontend", "80")
        gateway = _loopback_origin(fixture_files, fixture_env, project, "gateway", "8100")

        _compose(fixture_files, fixture_env, project, "cp",
                 str(ROOT / "scripts/evidence/phase74-seed.py"),
                 "backend:/tmp/f6-market-seed.py", category="f6_market_seed_copy_failed")
        _compose(fixture_files, fixture_env, project, "exec", "-T", "backend",
                 "python", "/tmp/f6-market-seed.py", category="f6_market_seed_failed")

        _auth_preflight(project, frontend, evidence_dir, fixture_env)
        _require(not primary_path.exists() and not closeout_path.exists(),
                 "f6_evidence_path_already_exists")
        driver_env = _f6_driver_environment(selection, fixture_env, gateway, primary_path)
        driver_env["BYQ_F6_PREPARED_WORKSPACE_ID"] = prepared_workspace_id
        _run([sys.executable, str(ROOT / "scripts/evidence/f6-chain-verification.py")],
             env=driver_env, timeout=900, category="f6_product_worker_chain_failed")
        primary, closeout = _validate_f6_evidence(primary_path, closeout_path)
        provider_report = _provider_diagnostics(fixture_env, project)

        browser_result = _playwright(
            ROOT / "apps/frontend/playwright.f6.config.ts", primary_path,
            frontend, project, evidence_dir / "f6-acp-browser", fixture_env)
        result = {
            "schema_version": "byq.acp-f6-release-fixture.v1",
            "status": "PASS_SYNTHETIC_ACP_PRODUCT_WORKER_RELEASE_FIXTURE",
            "project": project,
            "qualification_scope": "captured ACP batch; real Product API, BYQ MCP, Backend, Worker, terminal acknowledgement, Gateway restart and browser; local scripted provider",
            "model_quality": "NOT_RUN",
            "provider_usage": "unknown_synthetic_provider_omits_usage",
            "crash_recovery": "NOT_RUN",
            "negative_cases": {
                "duplicate_or_replayed_continuation": "NOT_RUN",
                "revoke_before_provider_dispatch": "NOT_RUN",
                "insufficient_request_budget": "NOT_RUN",
                "provider_response_lost_unknown_outcome": "NOT_RUN",
                "unfinished_root_restart_reconciliation": "NOT_RUN",
            },
            "gateway_restart": "PASS_exact_original_session_and_same_durable_job_before_worker_completion",
            "browser": browser_result,
            "f6_primary_evidence_sha256": _digest(primary_path),
            "f6_closeout_evidence_sha256": _digest(closeout_path),
            "provider_diagnostics_status": provider_report["status"],
            "provider_stages": sorted({row["stage"] for row in provider_report["records"]}),
            "captured_image_ids": image_ids,
            "dsh_identity": dsh_identity,
            "checks": primary["checks"],
            "closeout_status": closeout["status"],
        }
    except FixtureFailure as error:
        failure = error
    except BaseException:
        failure = FixtureFailure("f6_release_fixture_unexpected_failure")
    finally:
        if touched:
            try:
                _compose(base_files, base_env, project, "up", "-d", "--pull", "never",
                         "--no-build", "--force-recreate", "--no-deps", "--wait",
                         "backend", "gateway", "runtime-adapter", "acp-product-runner",
                         category="f6_default_stack_restore_failed", timeout=240)
            except FixtureFailure:
                if failure is None:
                    failure = FixtureFailure("f6_default_stack_restore_failed")
                else:
                    failure = FixtureFailure("f6_fixture_failed_and_default_stack_restore_failed")
    if failure is not None:
        raise failure
    if result is None:
        raise FixtureFailure("f6_release_fixture_result_missing")
    _write_private(result_path, (json.dumps(result, sort_keys=True,
                                           separators=(",", ":")) + "\n").encode("utf-8"))
    print("ACP F6 release fixture: " + json.dumps({
        "status": result["status"], "project": project,
        "provider_diagnostics_status": result["provider_diagnostics_status"],
        "browser": result["browser"], "captured_image_count": len(image_ids),
        "result": str(result_path.relative_to(ROOT)),
    }, sort_keys=True), flush=True)
    return result


def main() -> int:
    try:
        run()
        return 0
    except FixtureFailure as error:
        print("ACP F6 release fixture failed closed: " + error.category, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
