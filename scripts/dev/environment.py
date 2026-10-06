#!/usr/bin/env python3
"""Worktree-scoped BYQ development lifecycle; never targets the Product stack."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CURRENT_DSH_DOCKERFILE = "services/runtime-adapter/Dockerfile.post-u8-316-candidate"
ENV_FILE = ROOT / ".env.dev"
TEMPLATE = ROOT / ".env.example"
VOLUME_SUFFIXES = ("postgres-data", "domain-state", "ml-model-state", "dsh-sessions", "workflow-traces")
NETWORK_SUFFIXES = ("product", "signal-sandbox")
SERVICES = {
    "core": ("postgres", "backend", "mcp", "runtime-adapter", "gateway"),
    "research": ("postgres", "backend", "mcp", "runtime-adapter", "gateway", "data-worker", "factor-worker"),
    "backtest": ("postgres", "backend", "mcp", "runtime-adapter", "gateway", "signal-sandbox", "signal-worker", "backtest-worker", "optimization-worker", "factor-worker"),
    "ml": ("postgres", "backend", "mcp", "runtime-adapter", "gateway", "ml-worker"),
    "full": ("postgres", "backend", "mcp", "runtime-adapter", "gateway", "data-worker", "signal-sandbox", "signal-worker", "backtest-worker", "optimization-worker", "factor-worker", "ml-worker", "frontend"),
}
FORBIDDEN_OVERRIDES = (
    "BYQ_POSTGRES_VOLUME_NAME", "BYQ_DOMAIN_VOLUME_NAME", "BYQ_ML_MODEL_VOLUME_NAME",
    "BYQ_DSH_SESSIONS_VOLUME_NAME", "BYQ_WORKFLOW_TRACES_VOLUME_NAME",
    "BYQ_PRODUCT_NETWORK_NAME", "BYQ_SIGNAL_SANDBOX_NETWORK_NAME",
)


class DevError(Exception):
    pass


def scope() -> str:
    digest = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:10]
    return f"byq-dev-{digest}"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise DevError("invalid local environment file")
        if key in values:
            raise DevError("duplicate local environment key")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def local_env() -> dict[str, str]:
    if ENV_FILE.is_symlink() or not ENV_FILE.is_file():
        raise DevError("run make dev-init to create this worktree's .env.dev")
    mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
    if mode & 0o077:
        raise DevError(".env.dev must not be accessible by group or others")
    values = read_env(ENV_FILE)
    if values.get("BYQ_DEV_SCOPE") != scope() or values.get("COMPOSE_PROJECT_NAME") != scope():
        raise DevError(".env.dev belongs to a different worktree")
    if values.get("BYQ_POSTGRES_VOLUME_EXTERNAL", "false").lower() not in ("false", "0"):
        raise DevError("external PostgreSQL volume is forbidden in dev stack")
    if any(values.get(key) for key in FORBIDDEN_OVERRIDES):
        raise DevError("shared Docker resource override is forbidden in dev stack")
    binds = ("BYQ_GATEWAY_BIND", "BYQ_FRONTEND_BIND", "BYQ_DEV_MCP_BIND", "BYQ_DEV_BACKEND_BIND", "BYQ_DEV_ADAPTER_BIND")
    if any(values.get(k, "127.0.0.1:0") != "127.0.0.1:0" for k in binds):
        raise DevError("dev ports must use dynamic loopback binding")
    user, db, password = values.get("POSTGRES_USER"), values.get("POSTGRES_DB"), values.get("POSTGRES_PASSWORD")
    expected_db_url = f"postgresql+psycopg://{user}:{password}@postgres:5432/{db}"
    if values.get("BYQ_DATABASE_URL") != expected_db_url:
        raise DevError("dev database URL must target this Compose project's PostgreSQL")
    for key in ("BYQ_MCP_TOKEN", "BYQ_PRODUCT_TOKEN", "BYQ_RUNTIME_AUTHORITY_TOKEN", "POSTGRES_PASSWORD", "BYQ_BOOTSTRAP_ADMIN_PASSWORD", "BYQ_CREDENTIAL_KEYRING"):
        if not values.get(key):
            raise DevError(f"missing required local configuration: {key}")
    return values


def child_env(values: dict[str, str]) -> dict[str, str]:
    result = {k: v for k, v in os.environ.items() if not k.startswith(("BYQ_", "POSTGRES_", "COMPOSE_"))}
    result.update(values)
    return result


def compose_args(*parts: str) -> list[str]:
    return ["docker", "compose", "--project-name", scope(), "--env-file", str(ENV_FILE), "-f", str(ROOT / "compose.yml"), "-f", str(ROOT / "compose.dev.yml"), *parts]


def call(args: list[str], values: dict[str, str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=child_env(values), text=True, capture_output=capture, check=False)


def validated_config(values: dict[str, str]) -> None:
    result = call(compose_args("config", "--format", "json"), values, capture=True)
    if result.returncode:
        raise DevError("Compose configuration failed; check .env.dev and templates without printing secrets")
    try:
        config = json.loads(result.stdout)
        dockerfile = config["services"]["runtime-adapter"]["build"]["dockerfile"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DevError("Compose configuration lacks the Runtime Adapter build") from exc
    if dockerfile != CURRENT_DSH_DOCKERFILE:
        raise DevError("Compose selected a stale Runtime Adapter build")


def init() -> None:
    if ENV_FILE.exists() or ENV_FILE.is_symlink():
        values = local_env()
        validated_config(values)
        print(f"Existing isolated dev config verified: {scope()}")
        return
    template = TEMPLATE.read_text()
    base = read_env(TEMPLATE)
    db = base.get("POSTGRES_DB", "byq_domain")
    user = base.get("POSTGRES_USER", "byq_app")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", db) or not re.fullmatch(r"[a-z][a-z0-9_]*", user):
        raise DevError("invalid development database identity")
    password = secrets.token_hex(24)
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    replacements = {
        "COMPOSE_PROJECT_NAME": scope(), "BYQ_DEV_SCOPE": scope(),
        "BYQ_MCP_TOKEN": secrets.token_hex(32),
        "BYQ_PRODUCT_TOKEN": secrets.token_hex(32),
        "BYQ_RUNTIME_AUTHORITY_TOKEN": secrets.token_hex(32),
        "BYQ_CREDENTIAL_RESOLVER_TOKEN": secrets.token_hex(32),
        "BYQ_PLUGIN_DEPLOYMENT_TOKEN": secrets.token_hex(32),
        "BYQ_FEEDBACK_HUB_RELAY_TOKEN": secrets.token_hex(32),
        "BYQ_BOOTSTRAP_ADMIN_PASSWORD": secrets.token_hex(24),
        "BYQ_CREDENTIAL_KEYRING": "'" + json.dumps({"local-v1": key}, separators=(",", ":")) + "'",
        "BYQ_CREDENTIAL_ACTIVE_KEY_ID": "local-v1",
        "POSTGRES_PASSWORD": password,
        "BYQ_DATABASE_URL": f"postgresql+psycopg://{user}:{password}@postgres:5432/{db}",
        "BYQ_GATEWAY_BIND": "127.0.0.1:0", "BYQ_FRONTEND_BIND": "127.0.0.1:0",
        "BYQ_POSTGRES_SHARED_BUFFERS": "128MB", "BYQ_POSTGRES_EFFECTIVE_CACHE_SIZE": "512MB",
        "BYQ_POSTGRES_MAINTENANCE_WORK_MEM": "64MB",
    }
    lines: list[str] = []
    seen: set[str] = set()
    for line in template.splitlines():
        key = line.split("=", 1)[0] if not line.lstrip().startswith("#") else ""
        if key in replacements:
            line = f"{key}={replacements[key]}"
            seen.add(key)
        lines.append(line)
    for key, value in replacements.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        values = local_env()
        validated_config(values)
    except Exception:
        ENV_FILE.unlink(missing_ok=True)
        raise
    print(f"Created isolated dev config: {scope()}")


def docker_json(args: list[str], values: dict[str], *, absent_ok: bool = False):
    result = call(["docker", *args], values, capture=True)
    if result.returncode:
        missing = (args[0] == "volume" and "no such volume" in result.stderr.lower()) or (args[0] == "network" and ("no such network" in result.stderr.lower() or (args[-1] in result.stderr and "not found" in result.stderr.lower())))
        if absent_ok and missing:
            return None
        raise DevError("Docker inventory failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DevError("invalid Docker inventory") from exc


def docker_lines(args: list[str], values: dict[str]) -> list[str]:
    result = call(["docker", *args], values, capture=True)
    if result.returncode:
        raise DevError("Docker inventory failed")
    return [s for s in result.stdout.splitlines() if s]


def inventory(values: dict[str, str]) -> dict[str, list[str]]:
    project = scope()
    containers = docker_lines(["ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"], values)
    if containers:
        details = docker_json(["inspect", *containers], values)
        for obj in details:
            labels = obj.get("Config", {}).get("Labels") or {}
            if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.service") not in {s for group in SERVICES.values() for s in group}:
                raise DevError("unrecognized project container")
            if not obj.get("Name", "").startswith(f"/{project}-"):
                raise DevError("unrecognized project container name")
            for mount in obj.get("Mounts") or []:
                if mount.get("Type") == "volume" and mount.get("Name") not in {f"{project}-{suffix}" for suffix in VOLUME_SUFFIXES}:
                    raise DevError("project container uses an external volume")
                if mount.get("Type") == "bind" and not Path(mount.get("Source", "/")).resolve().is_relative_to(ROOT.resolve()):
                    raise DevError("project container uses an external bind mount")
            if set((obj.get("NetworkSettings") or {}).get("Networks") or {}) - {f"{project}-{suffix}" for suffix in NETWORK_SUFFIXES}:
                raise DevError("project container uses an external network")
    expected_volumes = [f"{project}-{suffix}" for suffix in VOLUME_SUFFIXES]
    expected_networks = [f"{project}-{suffix}" for suffix in NETWORK_SUFFIXES]
    volumes: list[str] = []
    networks: list[str] = []
    for name in expected_volumes:
        details = docker_json(["volume", "inspect", name], values, absent_ok=True)
        if details:
            obj = details[0]
            if obj.get("Name") != name or (obj.get("Labels") or {}).get("com.docker.compose.project") != project:
                raise DevError("unowned project volume")
            volumes.append(name)
    for name in expected_networks:
        details = docker_json(["network", "inspect", name], values, absent_ok=True)
        if details:
            obj = details[0]
            if obj.get("Name") != name or (obj.get("Labels") or {}).get("com.docker.compose.project") != project:
                raise DevError("unowned project network")
            networks.append(name)
    for kind, allowed in (("volume", set(expected_volumes)), ("network", set(expected_networks))):
        fmt = ["--format", "{{.Name}}"] if kind == "network" else ["-q"]
        listed = docker_lines([kind, "ls", *fmt, "--filter", f"label=com.docker.compose.project={project}"], values)
        if set(listed) - allowed:
            raise DevError(f"unexpected project {kind}")
    return {"containers": containers, "volumes": volumes, "networks": networks}


def clean(values: dict[str, str], apply: bool) -> None:
    targets = inventory(values)
    print(json.dumps({"project": scope(), "mode": "apply" if apply else "dry-run", **targets}, indent=2))
    if not apply:
        return
    # Compose removes only this exact project; do not pass --volumes or prune.
    if call(compose_args("down", "--remove-orphans"), values).returncode:
        raise DevError("project container/network removal failed")
    for name in targets["volumes"]:
        if docker_lines(["ps", "-aq", "--filter", f"volume={name}"], values):
            raise DevError("project volume gained a container reference")
        obj = docker_json(["volume", "inspect", name], values, absent_ok=True)
        if obj and (obj[0].get("Labels") or {}).get("com.docker.compose.project") == scope():
            if call(["docker", "volume", "rm", name], values, capture=True).returncode:
                raise DevError("project volume removal failed")
    remaining = inventory(values)
    if any(remaining.values()):
        raise DevError("project resources remain after cleanup")
    print("Isolated development resources removed; .env.dev and images retained")


def reset(values: dict[str, str], *, runtime_only: bool = False) -> None:
    """Reset only this worktree's disposable runtime and Workspace data."""
    inventory(values)  # Verify every existing resource belongs to this project.
    if call(compose_args("down", "--remove-orphans"), values).returncode:
        raise DevError("isolated services could not be stopped for reset")
    if call(compose_args("up", "-d", "--wait", "postgres"), values).returncode:
        raise DevError("isolated database could not start for reset")
    if not runtime_only:
        if call(compose_args("build", "backend"), values).returncode:
            raise DevError("current backend image could not be built for reset")
        result = call(compose_args("run", "--rm", "--no-deps", "--env", "BYQ_DEV_SCOPE",
                                   "--env", "COMPOSE_PROJECT_NAME",
                                   "backend", "python", "-m", "app.workspace_reset_cli",
                                   "--all-workspaces"), values)
        if result.returncode:
            raise DevError("workspace reset failed; PostgreSQL remains available for diagnosis")
        if call(compose_args("--profile", "maintenance", "run", "--rm", "--no-deps",
                             "workspace-reset-gc"), values).returncode:
            raise DevError("workspace object cleanup failed; rerun to recover orphaned objects")
    if call(compose_args("down", "--remove-orphans"), values).returncode:
        raise DevError("isolated services could not stop before runtime volume cleanup")
    for suffix in ("dsh-sessions", "workflow-traces"):
        name = f"{scope()}-{suffix}"
        obj = docker_json(["volume", "inspect", name], values, absent_ok=True)
        if obj is None:
            continue
        if obj[0].get("Name") != name or (obj[0].get("Labels") or {}).get("com.docker.compose.project") != scope():
            raise DevError("runtime volume is not owned by this isolated worktree")
        if docker_lines(["ps", "-aq", "--filter", f"volume={name}"], values):
            raise DevError("runtime volume still has a container reference")
        if call(["docker", "volume", "rm", name], values, capture=True).returncode:
            raise DevError("isolated runtime volume removal failed")
    if call(compose_args("up", "-d", "--wait", "--build", *SERVICES["core"]), values).returncode:
        raise DevError("isolated core services could not restart after reset")
    print(f"Reset isolated development {'runtime' if runtime_only else 'runtime and Workspaces'}: {scope()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "stop", "reset", "reset-runtime", "seed", "test"):
        sub.add_parser(name)
    start = sub.add_parser("start")
    start.add_argument("--profile", choices=tuple(SERVICES), default="core")
    cleaner = sub.add_parser("clean")
    mode = cleaner.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "init":
            init()
            return 0
        values = local_env()
        validated_config(values)
        if args.command == "start":
            if call(compose_args("up", "-d", "--wait", "--build", *SERVICES[args.profile]), values).returncode:
                raise DevError("isolated dev services failed to start")
            print(f"Started {scope()} profile {args.profile}")
        elif args.command == "stop":
            if call(compose_args("stop"), values).returncode:
                raise DevError("isolated dev services failed to stop")
            print(f"Stopped {scope()} containers; volumes retained")
        elif args.command == "clean":
            clean(values, args.apply)
        elif args.command in ("reset", "reset-runtime"):
            reset(values, runtime_only=args.command == "reset-runtime")
        elif args.command == "seed":
            inventory(values)
            seed_source = ROOT / "scripts/dev/seed_backend.py"
            result = call(compose_args("run", "--rm", "--no-deps",
                                       "--env", "BYQ_DEV_SCOPE", "--env", "COMPOSE_PROJECT_NAME",
                                       "--volume", f"{seed_source}:/tmp/byq-dev-seed.py:ro",
                                       "backend", "python", "/tmp/byq-dev-seed.py"), values)
            if result.returncode:
                raise DevError("isolated development seed failed")
            print(f"Seeded isolated development Workspace: {scope()}")
        elif args.command == "test":
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "docs/clean-break/validation", "-p", "test_*.py"], cwd=ROOT, env=child_env(values), check=False)
            if result.returncode:
                raise DevError("offline Clean Break governance tests failed")
            focused = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests/dev", "-p", "test_*.py"], cwd=ROOT, env=child_env(values), check=False)
            if focused.returncode:
                raise DevError("developer lifecycle tests failed")
            print("PASS: offline governance, lifecycle tests and Compose config; Golden Scenarios NOT_RUN until Phases 15–16")
        return 0
    except DevError as exc:
        print(f"Phase 9 dev environment: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
