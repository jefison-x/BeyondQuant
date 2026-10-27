#!/usr/bin/env python3
"""Run one disposable synthetic stale-ACP-root request through MCP to Backend.

This is an isolated protocol/control-plane probe. It does not start DSH, Gateway,
or a model and does not establish that DSH naturally emitted a delayed request.
All containers use exact local image digests, an internal Docker network and a
fresh PostgreSQL tmpfs; no Docker volume or host port is created.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any


DEFAULT_POSTGRES_IMAGE = "sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"
DEFAULT_BACKEND_IMAGE = "sha256:753662c496721f9cb3b411850351ba1ddfb08ec6661e7fe8716710c33661b281"
DEFAULT_MCP_IMAGE = "sha256:0980003d2c9c632598e51434257f7c631ddcd3bb11d8ddbd915b3a84fe577b8b"
SCOPE_PATTERN = re.compile(r"byq-acp-late-[0-9a-f]{10}\Z")
IMAGE_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
ROOT_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
RUN_PATTERN = re.compile(r"agent_run_[0-9a-f]{32}\Z")
NATIVE_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
LABEL_KEY = "byq.acp.late_root_probe"
BACKEND_DB_URL = "postgresql+psycopg://byq_test:byq-test-dev@postgres:5432/byq_domain_test"
RESULT_SCHEMA = "byq-acp-late-root-mcp-probe-result.v2"
FAILURE_STAGES = {
    "none", "image_preflight", "resource_preflight", "network_create",
    "postgres_container_start", "postgres_readiness", "fixture_seed",
    "seed_helper_import", "seed_registered_schema_init", "seed_schema_init",
    "seed_runtime_boot_rotate",
    "seed_product_context", "seed_old_root_create", "seed_old_root_bind",
    "seed_bootstrap_ingress_observe", "seed_bootstrap_ingress_settle",
    "seed_old_root_close", "seed_new_root_create", "seed_new_root_bind",
    "seed_state_readback", "seed_store_close", "seed_fixture_emit", "fixture_parse",
    "fixture_validation", "backend_container_start",
    "backend_readiness", "mcp_build_and_http_probe", "backend_http_evidence",
    "database_readback", "scoped_cleanup",
}
FAILURE_KINDS = {
    "none", "docker_cli_unavailable", "docker_command_timeout",
    "docker_nonzero_exit", "readiness_timeout", "fixture_invalid",
    "mcp_assertion_failed", "backend_fence_missing",
    "database_state_mismatch", "cleanup_failed", "probe_internal_error",
    "seed_step_failed",
}
SEED_FAILURE_STAGES = {
    "seed_helper_import", "seed_registered_schema_init", "seed_schema_init",
    "seed_runtime_boot_rotate",
    "seed_product_context", "seed_old_root_create", "seed_old_root_bind",
    "seed_bootstrap_ingress_observe", "seed_bootstrap_ingress_settle",
    "seed_old_root_close", "seed_new_root_create", "seed_new_root_bind",
    "seed_state_readback", "seed_store_close", "seed_fixture_emit",
}

# Deliberately synthetic, mutually distinct test-only values. These are not
# loaded from the host, a BYQ container, or a credential store.
TEST_VALUES = {
    "legacy": "late-root-mcp-legacy-test-token-4af291d6",
    "discovery": "late-root-mcp-discovery-test-token-8c71a5e2",
    "signing": "late-root-mcp-signing-test-key-32bytes-1b7d9a6c",
    "backend_proof": "late-root-mcp-backend-proof-test-7da843c1",
    "runtime_authority": "late-root-runtime-authority-test-2f6c9e4a",
}

SEED_PROGRAM = r'''import json
from uuid import uuid4

seed_stage = "seed_helper_import"
store = None
try:
    from tests.conftest import REGISTERED_SCHEMA_DDL
    from app.db import create_db_engine, run_ddl
    from app.agent_research import AgentResearchStore
    from tests.test_acp_domain_call_proof import (
        _bind, _context, _observe_tool, _open_root, _settle_tool,
    )

    # Match the PostgreSQL-backed test fixture: WorkspaceTenancyStore installs
    # write triggers across the registered store schema, not just Agent tables.
    # This disposable database is newly created, so it needs the registry DDL
    # but not the fixture's DROP SCHEMA reset.
    seed_stage = "seed_registered_schema_init"
    schema_engine = create_db_engine()
    try:
        with schema_engine.begin() as connection:
            run_ddl(connection, REGISTERED_SCHEMA_DDL)
    finally:
        schema_engine.dispose()

    seed_stage = "seed_schema_init"
    store = AgentResearchStore()
    seed_stage = "seed_runtime_boot_rotate"
    authority = store.rotate_runtime_authority(uuid4().hex)
    seed_stage = "seed_product_context"
    old_context = _context("late-http")
    old_context["x-byq-runtime-boot-id"] = authority["boot_id"]
    native_id = str(uuid4())

    seed_stage = "seed_old_root_create"
    old_root, old_identity = _open_root(
        store, old_context, "late-old-" + uuid4().hex, native_id, sequence=1)
    seed_stage = "seed_old_root_bind"
    _bind(store, old_context, old_identity)

    # Seed one settled, side-effect-free bootstrap ingress so the old root has
    # ordinary terminal evidence before the next root is admitted.
    seed_stage = "seed_bootstrap_ingress_observe"
    prior = _observe_tool(store, old_context, old_identity, "byq_agent_context", {})
    seed_stage = "seed_bootstrap_ingress_settle"
    _settle_tool(store, old_context, old_identity, prior)
    seed_stage = "seed_old_root_close"
    store.consume_runtime_lifecycle_event({
        "schema_version": "agent-run-lifecycle.v1",
        "root_run_id": old_root,
        "sequence": 2,
        "outcome": "completed",
    }, trusted_owner=old_context["x-byq-owner-principal"],
       trusted_workspace=old_context["x-byq-workspace-id"],
       trusted_session_id=old_context["x-byq-session-id"],
       trusted_trace_id=old_context["x-byq-trace-id"],
       trusted_boot_id=authority["boot_id"])

    new_context = {
        **old_context,
        "x-byq-dsh-run-id": "generation-acp-late-" + uuid4().hex[:16],
    }
    seed_stage = "seed_new_root_create"
    new_root, new_identity = _open_root(
        store, new_context, "late-new-" + uuid4().hex, native_id, sequence=3)
    seed_stage = "seed_new_root_bind"
    _bind(store, new_context, new_identity)

    seed_stage = "seed_state_readback"
    old_count = store._fetch_one(
        "SELECT count(*) AS n FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root",
        {"root": old_root},)["n"]
    new_count = store._fetch_one(
        "SELECT count(*) AS n FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root",
        {"root": new_root},)["n"]
    old_row = store._fetch_one(
        "SELECT status FROM agent_runtime_turns WHERE root_run_id=:root", {"root": old_root})
    new_row = store._fetch_one(
        "SELECT status FROM agent_runtime_turns WHERE root_run_id=:root", {"root": new_root})
    old_run = store._fetch_one(
        "SELECT status FROM agent_runs WHERE run_id=:run", {"run": old_identity["agent_run_id"]})
    new_run = store._fetch_one(
        "SELECT status FROM agent_runs WHERE run_id=:run", {"run": new_identity["agent_run_id"]})
    if (old_count != 1 or new_count != 0 or old_row["status"] != "completed"
            or new_row["status"] != "active" or old_run["status"] != "completed"
            or new_run["status"] != "active"):
        raise RuntimeError("synthetic fixture did not reach the exact old-closed/new-active state")

    claims = {
        "root_run_id": old_root,
        "runtime_boot_id": old_context["x-byq-runtime-boot-id"],
        "owner_principal": old_context["x-byq-owner-principal"],
        "workspace_id": old_context["x-byq-workspace-id"],
        "actor_principal": old_context["x-byq-actor-principal"],
        "trace_id": old_context["x-byq-trace-id"],
        "session_id": old_context["x-byq-session-id"],
        "dsh_run_id": old_context["x-byq-dsh-run-id"],
    }
    seed_stage = "seed_store_close"
    store.close()
    store = None
    seed_stage = "seed_fixture_emit"
    print(json.dumps({
        "schema_version": "byq-acp-late-root-fixture.v1",
        "claims": claims,
        "old_root_run_id": old_root,
        "new_root_run_id": new_root,
        "native_root_session_id": native_id,
        "old_agent_run_id": old_identity["agent_run_id"],
        "new_agent_run_id": new_identity["agent_run_id"],
        "old_ingress_count": old_count,
        "new_ingress_count": new_count,
    }, sort_keys=True, separators=(",", ":")))
except Exception:
    print(json.dumps({
        "schema_version": "byq-acp-late-root-seed-status.v1",
        "status": "fail",
        "failure_stage": seed_stage,
    }, sort_keys=True, separators=(",", ":")))
    raise
finally:
    if store is not None:
        store.close()
'''

VERIFY_PROGRAM = r'''import json
import os
from app.agent_research import AgentResearchStore

fixture = json.loads(os.environ["BYQ_ACP_LATE_ROOT_FIXTURE_JSON"])
store = AgentResearchStore()
try:
    old_root = fixture["old_root_run_id"]
    new_root = fixture["new_root_run_id"]
    old_run_id = fixture["old_agent_run_id"]
    new_run_id = fixture["new_agent_run_id"]
    old = store._fetch_one("SELECT status FROM agent_runtime_turns WHERE root_run_id=:root",
        {"root": old_root})
    new = store._fetch_one("SELECT status FROM agent_runtime_turns WHERE root_run_id=:root",
        {"root": new_root})
    old_run = store._fetch_one("SELECT status FROM agent_runs WHERE run_id=:run",
        {"run": old_run_id})
    new_run = store._fetch_one("SELECT status FROM agent_runs WHERE run_id=:run",
        {"run": new_run_id})
    old_binding = store._fetch_one("""SELECT native_root_session_id
        FROM agent_acp_native_agent_registrations
        WHERE root_run_id=:root AND native_agent_session_id=:native""",
        {"root": old_root, "native": fixture["native_root_session_id"]})
    new_binding = store._fetch_one("""SELECT native_root_session_id
        FROM agent_acp_native_agent_registrations
        WHERE root_run_id=:root AND native_agent_session_id=:native""",
        {"root": new_root, "native": fixture["native_root_session_id"]})
    old_count = store._fetch_one("SELECT count(*) AS n FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root",
        {"root": old_root})["n"]
    new_count = store._fetch_one("SELECT count(*) AS n FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root",
        {"root": new_root})["n"]
    print(json.dumps({
        "schema_version": "byq-acp-late-root-verification.v1",
        "old_root_closed": bool(old and old["status"] == "completed"),
        "new_root_active": bool(new and new["status"] == "active"),
        "agent_runs_distinct": old_run_id != new_run_id,
        "agent_run_statuses_exact": bool(old_run and old_run["status"] == "completed"
            and new_run and new_run["status"] == "active"),
        "shared_native_root": fixture["claims"]["root_run_id"] == old_root
            and bool(old_binding and old_binding["native_root_session_id"] == fixture["native_root_session_id"])
            and bool(new_binding and new_binding["native_root_session_id"] == fixture["native_root_session_id"]),
        "ingress_rows_unchanged": old_count == fixture["old_ingress_count"]
            and new_count == fixture["new_ingress_count"],
        "old_ingress_count": old_count,
        "new_ingress_count": new_count,
    }, sort_keys=True, separators=(",", ":")))
finally:
    store.close()
'''


class ProbeFailure(RuntimeError):
    def __init__(self, reason: str, *, kind: str = "none", exit_code: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.kind = kind
        self.exit_code = exit_code


def emit(*, status: str, reason: str, cleanup_verified: bool | None,
         failure_stage: str = "none", failure_kind: str = "none",
         docker_exit_code: int | None = None,
         mcp_call_rejected: bool | None = None,
         backend_observe_409: bool | None = None,
         backend_abort_409: bool | None = None,
         ingress_rows_unchanged: bool | None = None,
         old_root_closed: bool | None = None,
         new_root_active: bool | None = None,
         shared_native_root: bool | None = None,
         agent_runs_distinct: bool | None = None) -> None:
    allowed_status = {"plan_only", "pass", "fail", "not_run"}
    allowed_reason = {
        "none", "execution_flag_required", "invalid_scope", "image_missing",
        "resource_name_in_use", "container_setup_failed", "fixture_failed",
        "service_not_ready", "mcp_probe_failed", "backend_fence_not_observed",
        "database_state_mismatch", "cleanup_failed",
    }
    if (status not in allowed_status or reason not in allowed_reason
            or failure_stage not in FAILURE_STAGES or failure_kind not in FAILURE_KINDS
            or (docker_exit_code is not None and (not isinstance(docker_exit_code, int)
                or docker_exit_code < -255 or docker_exit_code > 255))):
        status, reason = "fail", "container_setup_failed"
        failure_stage, failure_kind, docker_exit_code = "none", "none", None
    print(json.dumps({
        "schema_version": RESULT_SCHEMA,
        "status": status,
        "reason": reason,
        "failure_stage": failure_stage,
        "failure_kind": failure_kind,
        "docker_exit_code": docker_exit_code,
        "scope": "disposable_internal_network_and_postgres_tmpfs",
        "synthetic_hmac": True,
        "synthetic_seeded_roots": True,
        "model_calls": 0,
        "provider_credentials_used": False,
        "mcp_call_rejected": mcp_call_rejected,
        "backend_observe_409": backend_observe_409,
        "backend_abort_409": backend_abort_409,
        "ingress_rows_unchanged": ingress_rows_unchanged,
        "old_root_closed": old_root_closed,
        "new_root_active": new_root_active,
        "shared_native_root": shared_native_root,
        "agent_runs_distinct": agent_runs_distinct,
        "docker_volumes_created": 0,
        "host_ports_published": 0,
        "cleanup_verified": cleanup_verified,
    }, sort_keys=True, separators=(",", ":")))


def run(command: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(command, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=timeout, check=False)
    except OSError:
        raise ProbeFailure("container_setup_failed", kind="docker_cli_unavailable") from None
    except subprocess.TimeoutExpired:
        raise ProbeFailure("container_setup_failed", kind="docker_command_timeout") from None
    if check and completed.returncode != 0:
        raise ProbeFailure("container_setup_failed", kind="docker_nonzero_exit",
                           exit_code=completed.returncode)
    return completed


def exists(kind: str, name: str) -> bool:
    result = run(["docker", kind, "inspect", name], timeout=10, check=False)
    if result.returncode == 0:
        return True
    # Only Docker's explicit missing-resource response proves absence. A
    # daemon/permission/CLI failure is unknown and must not count as cleanup.
    missing = {
        f"Error: No such {kind}: {name}",
        f"Error response from daemon: {kind} {name} not found",
        f"Error response from daemon: No such {kind}: {name}",
    }
    if result.returncode == 1 and result.stdout.strip() in {"", "[]"} and result.stderr.strip() in missing:
        return False
    raise ProbeFailure("container_setup_failed", kind="docker_nonzero_exit",
                       exit_code=result.returncode)


def image_available(image: str) -> bool:
    if IMAGE_PATTERN.fullmatch(image) is None:
        return False
    return run(["docker", "image", "inspect", image], timeout=15, check=False).returncode == 0


def label_value(kind: str, name: str) -> str | None:
    if kind == "container":
        template = "{{ index .Config.Labels \"" + LABEL_KEY + "\" }}"
    else:
        template = "{{ index .Labels \"" + LABEL_KEY + "\" }}"
    result = run(["docker", kind, "inspect", "--format", template, name], timeout=10, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def wait_for_postgres(name: str) -> bool:
    for _ in range(45):
        if run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1",
                "-U", "byq_app", "-d", "byq_domain"], timeout=5, check=False).returncode == 0:
            return True
        time.sleep(1)
    return False


def wait_for_backend(name: str) -> bool:
    probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"
    for _ in range(45):
        if run(["docker", "exec", name, "python", "-c", probe], timeout=5, check=False).returncode == 0:
            return True
        time.sleep(1)
    return False


def validate_fixture(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "claims", "old_root_run_id", "new_root_run_id",
        "native_root_session_id", "old_agent_run_id", "new_agent_run_id",
        "old_ingress_count", "new_ingress_count",
    }:
        return False
    claims = value["claims"]
    return (value["schema_version"] == "byq-acp-late-root-fixture.v1"
            and isinstance(claims, dict)
            and set(claims) == {"root_run_id", "runtime_boot_id", "owner_principal",
                "workspace_id", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
            and ROOT_PATTERN.fullmatch(str(value["old_root_run_id"])) is not None
            and ROOT_PATTERN.fullmatch(str(value["new_root_run_id"])) is not None
            and value["old_root_run_id"] != value["new_root_run_id"]
            and NATIVE_PATTERN.fullmatch(str(value["native_root_session_id"])) is not None
            and RUN_PATTERN.fullmatch(str(value["old_agent_run_id"])) is not None
            and RUN_PATTERN.fullmatch(str(value["new_agent_run_id"])) is not None
            and value["old_agent_run_id"] != value["new_agent_run_id"]
            and claims["root_run_id"] == value["old_root_run_id"]
            and isinstance(value["old_ingress_count"], int)
            and isinstance(value["new_ingress_count"], int)
            and value["old_ingress_count"] == 1 and value["new_ingress_count"] == 0)


def parse_exact_json_line(value: str, schema: str, fields: set[str]) -> dict[str, Any] | None:
    for line in reversed([item for item in value.splitlines() if item.strip()]):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(parsed, dict) and parsed.get("schema_version") == schema
                and set(parsed) == fields):
            return parsed
    return None


def cleanup_container(name: str, scope: str) -> bool:
    if not exists("container", name):
        return True
    if label_value("container", name) != scope:
        return False
    return run(["docker", "rm", "--force", name], timeout=20, check=False).returncode == 0


def cleanup_network(name: str, scope: str) -> bool:
    if not exists("network", name):
        return True
    if label_value("network", name) != scope:
        return False
    return run(["docker", "network", "rm", name], timeout=20, check=False).returncode == 0


REPO_ROOT: Path


def main() -> None:
    global REPO_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True,
                        help="absolute checkout root for this probe's read-only source mounts")
    parser.add_argument("--execute", action="store_true",
                        help="create and remove only this probe's disposable containers/network")
    parser.add_argument("--scope", default="byq-acp-late-" + uuid.uuid4().hex[:10])
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--backend-image", default=DEFAULT_BACKEND_IMAGE)
    parser.add_argument("--mcp-image", default=DEFAULT_MCP_IMAGE)
    args = parser.parse_args()
    if (not args.repo_root.is_absolute() or not args.repo_root.is_dir()
            or not all((args.repo_root / path).is_dir() for path in (
                "infra/postgres/init", "services/mcp/src", "services/mcp/tests"))):
        parser.error("--repo-root must be an absolute checkout with the three source mount directories")
    REPO_ROOT = args.repo_root.resolve()
    if SCOPE_PATTERN.fullmatch(args.scope) is None:
        emit(status="not_run", reason="invalid_scope", cleanup_verified=None,
             failure_stage="resource_preflight")
        return
    if not args.execute:
        emit(status="plan_only", reason="execution_flag_required", cleanup_verified=None)
        return

    failure_stage = "image_preflight"
    images = (args.postgres_image, args.backend_image, args.mcp_image)
    try:
        images_present = all(image_available(image) for image in images)
    except ProbeFailure as exc:
        emit(status="not_run", reason="container_setup_failed", cleanup_verified=None,
             failure_stage=failure_stage, failure_kind=exc.kind, docker_exit_code=exc.exit_code)
        return
    if not images_present:
        emit(status="not_run", reason="image_missing", cleanup_verified=None,
             failure_stage=failure_stage)
        return

    project = args.scope
    network = project + "-net"
    names = {
        "postgres": project + "-pg",
        "seed": project + "-seed",
        "backend": project + "-backend",
        "mcp": project + "-mcp-test",
        "verify": project + "-verify",
    }
    try:
        resource_collision = exists("network", network) or any(
            exists("container", name) for name in names.values())
    except ProbeFailure as exc:
        emit(status="not_run", reason="container_setup_failed", cleanup_verified=None,
             failure_stage="resource_preflight", failure_kind=exc.kind,
             docker_exit_code=exc.exit_code)
        return
    if resource_collision:
        emit(status="not_run", reason="resource_name_in_use", cleanup_verified=None,
             failure_stage="resource_preflight")
        return

    network_attempted = False
    failure = "none"
    failure_kind = "none"
    docker_exit_code: int | None = None
    result_values: dict[str, bool | None] = {}
    try:
        failure_stage = "network_create"
        network_attempted = True
        run(["docker", "network", "create", "--internal", "--label", f"{LABEL_KEY}={project}", network],
            timeout=15)

        failure_stage = "postgres_container_start"
        run([
            "docker", "run", "--detach", "--name", names["postgres"], "--label", f"{LABEL_KEY}={project}",
            "--network", network, "--network-alias", "postgres",
            "--env", "POSTGRES_DB=byq_domain", "--env", "POSTGRES_USER=byq_app",
            "--env", "POSTGRES_PASSWORD=byq-late-root-test-only",
            "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,nodev,size=512m",
            "--mount", f"type=bind,source={args.repo_root / 'infra/postgres/init'},target=/docker-entrypoint-initdb.d,readonly",
            args.postgres_image, "postgres", "-c", "max_connections=100",
        ], timeout=30)
        failure_stage = "postgres_readiness"
        if not wait_for_postgres(names["postgres"]):
            raise ProbeFailure("service_not_ready", kind="readiness_timeout")

        failure_stage = "fixture_seed"
        seed_command = [
            "docker", "run", "--rm", "--name", names["seed"], "--label", f"{LABEL_KEY}={project}",
            "--network", network, "--env", f"BYQ_DATABASE_URL={BACKEND_DB_URL}",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--entrypoint", "python",
            args.backend_image, "-c", SEED_PROGRAM,
        ]
        seeded = run(seed_command, timeout=45, check=False)
        if seeded.returncode != 0:
            seed_failure = parse_exact_json_line(seeded.stdout,
                "byq-acp-late-root-seed-status.v1",
                {"schema_version", "status", "failure_stage"})
            if (seed_failure is not None and seed_failure.get("status") == "fail"
                    and seed_failure.get("failure_stage") in SEED_FAILURE_STAGES):
                failure_stage = seed_failure["failure_stage"]
                raise ProbeFailure("fixture_failed", kind="seed_step_failed",
                                   exit_code=seeded.returncode)
            raise ProbeFailure("container_setup_failed", kind="docker_nonzero_exit",
                               exit_code=seeded.returncode)
        failure_stage = "fixture_parse"
        fixture = json.loads(seeded.stdout)
        failure_stage = "fixture_validation"
        if not validate_fixture(fixture):
            raise ProbeFailure("fixture_failed", kind="fixture_invalid")

        failure_stage = "backend_container_start"
        backend_env = [
            "--env", f"BYQ_DATABASE_URL={BACKEND_DB_URL}",
            "--env", f"BYQ_MCP_BACKEND_PROOF_TOKEN={TEST_VALUES['backend_proof']}",
            "--env", f"BYQ_RUNTIME_AUTHORITY_TOKEN={TEST_VALUES['runtime_authority']}",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
        ]
        run([
            "docker", "run", "--detach", "--name", names["backend"], "--label", f"{LABEL_KEY}={project}",
            "--network", network, "--network-alias", "backend", *backend_env,
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m", "--entrypoint", "uvicorn",
            args.backend_image, "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--access-log",
        ], timeout=30)
        failure_stage = "backend_readiness"
        if not wait_for_backend(names["backend"]):
            raise ProbeFailure("service_not_ready", kind="readiness_timeout")

        failure_stage = "mcp_build_and_http_probe"
        test_env = [
            "--env", f"BYQ_MCP_TOKEN={TEST_VALUES['legacy']}",
            "--env", f"BYQ_MCP_ACP_DISCOVERY_TOKEN={TEST_VALUES['discovery']}",
            "--env", f"BYQ_MCP_ACP_SIGNING_KEY={TEST_VALUES['signing']}",
            "--env", f"BYQ_MCP_BACKEND_PROOF_TOKEN={TEST_VALUES['backend_proof']}",
            "--env", "BYQ_BACKEND_URL=http://backend:8000",
            "--env", "BYQ_MCP_TEST_FIXTURE_JSON=" + json.dumps(fixture, sort_keys=True, separators=(",", ":")),
        ]
        mcp_result = run([
            "docker", "run", "--name", names["mcp"], "--label", f"{LABEL_KEY}={project}",
            "--network", network, "--user", "0", *test_env,
            "--mount", f"type=bind,source={args.repo_root / 'services/mcp/src'},target=/app/src,readonly",
            "--mount", f"type=bind,source={args.repo_root / 'services/mcp/tests'},target=/app/tests,readonly",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--workdir", "/app",
            "--entrypoint", "sh", args.mcp_image, "-ec",
            "npm run build >/dev/null && node dist/tests/acp-late-root-http-test.js",
        ], timeout=90, check=False)
        mcp_summary = parse_exact_json_line(mcp_result.stdout,
            "byq-acp-late-root-mcp-client-result.v1", {
                "schema_version", "status", "synthetic_hmac", "tool_call_rejected",
                "expected_error", "model_calls",
            })
        result_values["mcp_call_rejected"] = bool(
            mcp_result.returncode == 0 and mcp_summary
            and mcp_summary.get("status") == "pass"
            and mcp_summary.get("synthetic_hmac") is True
            and mcp_summary.get("tool_call_rejected") is True
            and mcp_summary.get("expected_error") is True
            and mcp_summary.get("model_calls") == 0)
        if not result_values["mcp_call_rejected"]:
            raise ProbeFailure("mcp_probe_failed", kind="mcp_assertion_failed")

        failure_stage = "backend_http_evidence"
        access_log = run(["docker", "logs", names["backend"]], timeout=20, check=False).stdout
        observe_409 = [line for line in access_log.splitlines()
            if re.search(r'"POST /internal/acp/tool-ingress-observe HTTP/1\.1"\s+409\b', line)]
        abort_409 = [line for line in access_log.splitlines()
            if re.search(r'"POST /internal/acp/tool-ingress-abort HTTP/1\.1"\s+409\b', line)]
        result_values["backend_observe_409"] = len(observe_409) == 1
        result_values["backend_abort_409"] = len(abort_409) == 1
        if not result_values["backend_observe_409"] or not result_values["backend_abort_409"]:
            raise ProbeFailure("backend_fence_not_observed", kind="backend_fence_missing")

        failure_stage = "database_readback"
        fixture_json = json.dumps(fixture, sort_keys=True, separators=(",", ":"))
        verified = run([
            "docker", "run", "--rm", "--name", names["verify"], "--label", f"{LABEL_KEY}={project}",
            "--network", network, "--env", f"BYQ_DATABASE_URL={BACKEND_DB_URL}",
            "--env", f"BYQ_ACP_LATE_ROOT_FIXTURE_JSON={fixture_json}",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--entrypoint", "python",
            args.backend_image, "-c", VERIFY_PROGRAM,
        ], timeout=45)
        verification = parse_exact_json_line(verified.stdout,
            "byq-acp-late-root-verification.v1", {
                "schema_version", "old_root_closed", "new_root_active", "agent_runs_distinct",
                "agent_run_statuses_exact", "shared_native_root", "ingress_rows_unchanged",
                "old_ingress_count", "new_ingress_count",
            })
        if verification is None:
            raise ProbeFailure("database_state_mismatch", kind="database_state_mismatch")
        result_values.update({
            "old_root_closed": verification["old_root_closed"] is True,
            "new_root_active": verification["new_root_active"] is True,
            "shared_native_root": verification["shared_native_root"] is True,
            "agent_runs_distinct": verification["agent_runs_distinct"] is True
                and verification["agent_run_statuses_exact"] is True,
            "ingress_rows_unchanged": verification["ingress_rows_unchanged"] is True
                and verification["old_ingress_count"] == fixture["old_ingress_count"]
                and verification["new_ingress_count"] == fixture["new_ingress_count"],
        })
        if not all(result_values.get(field) is True for field in (
                "old_root_closed", "new_root_active", "shared_native_root",
                "agent_runs_distinct", "ingress_rows_unchanged")):
            raise ProbeFailure("database_state_mismatch", kind="database_state_mismatch")
    except ProbeFailure as exc:
        failure = exc.reason
        failure_kind = exc.kind
        docker_exit_code = exc.exit_code
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        failure = "fixture_failed"
        failure_kind = "fixture_invalid"
    except Exception:
        failure = "container_setup_failed"
        failure_kind = "probe_internal_error"
    finally:
        cleanup_ok = True
        try:
            for name in reversed(tuple(names.values())):
                cleanup_ok = cleanup_container(name, project) and cleanup_ok
            if network_attempted:
                cleanup_ok = cleanup_network(network, project) and cleanup_ok
            # Verify only this label/scope. No volume is ever created by this script.
            leftovers = run(["docker", "ps", "-aq", "--filter", f"label={LABEL_KEY}={project}"],
                            timeout=10).stdout.strip()
            network_left = run(["docker", "network", "ls", "-q", "--filter", f"label={LABEL_KEY}={project}"],
                               timeout=10).stdout.strip()
            cleanup_ok = cleanup_ok and not leftovers and not network_left
        except ProbeFailure:
            cleanup_ok = False
        except Exception:
            cleanup_ok = False

    passed = failure == "none" and cleanup_ok
    if not cleanup_ok and failure == "none":
        failure_stage = "scoped_cleanup"
        failure_kind = "cleanup_failed"
    emit(status="pass" if passed else "fail",
         reason="none" if passed else ("cleanup_failed" if not cleanup_ok else failure),
         cleanup_verified=cleanup_ok,
         failure_stage=failure_stage if not passed else "none",
         failure_kind=failure_kind if not passed else "none",
         docker_exit_code=docker_exit_code,
         mcp_call_rejected=result_values.get("mcp_call_rejected"),
         backend_observe_409=result_values.get("backend_observe_409"),
         backend_abort_409=result_values.get("backend_abort_409"),
         ingress_rows_unchanged=result_values.get("ingress_rows_unchanged"),
         old_root_closed=result_values.get("old_root_closed"),
         new_root_active=result_values.get("new_root_active"),
         shared_native_root=result_values.get("shared_native_root"),
         agent_runs_distinct=result_values.get("agent_runs_distinct"))


if __name__ == "__main__":
    main()
