#!/usr/bin/env python3
"""Hermetic, test-only G6 stack; never inherit the deployment Compose or .env."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys

try:
    from scripts.dsh import build_revision
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.dsh import build_revision

ROOT = Path(__file__).resolve().parents[2]
RELEASES = {"dsh-0.1.1rc1", "dsh-0.1.2rc1"}
SERVICES = {"postgres", "backend", "mcp", "runtime-adapter", "gateway", "frontend", "fake-hub", "feedback-hub-relay"}
LABEL = "org.beyondquant.u5-test-scope"


def compose_environment(source=None):
    source = os.environ if source is None else source
    return {key: source[key] for key in ("PATH", "HOME", "DEEPSEEK_API_KEY") if key in source}


def model_key_from_env_file(path: Path) -> str:
    # Read one explicitly authorized field; do not source shell syntax or
    # propagate the developer deployment's other configuration or credentials.
    values = []
    with path.open() as source:
        for line in source:
            if line.startswith("DEEPSEEK_API_KEY="):
                value = line.partition("=")[2].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values.append(value)
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_.-]{16,256}", values[0]):
        raise ValueError("exactly one literal model credential is required; no interpolation")
    return values[0]


def manifest(scope: str, release: str, port: int, *, rehearsal_gate: str | None = None) -> dict:
    if not re.fullmatch(r"byq-u5-[a-z0-9][a-z0-9-]{2,44}", scope):
        raise ValueError("dedicated byq-u5 scope required")
    if release not in RELEASES or type(port) is not int or not 18000 <= port <= 18990:
        raise ValueError("invalid fixed release or isolated port range")
    labels = {LABEL: scope}
    result = {"name": scope, "x-byq-release": release, "x-byq-port": port,
              "networks": {"product": {"name": f"{scope}-product", "internal": True, "labels": labels},
                           "edge": {"name": f"{scope}-edge", "internal": False, "labels": labels},
                           "model": {"name": f"{scope}-model", "internal": False, "labels": labels}},
              "volumes": {name: {"name": f"{scope}-{name}", "labels": labels}
                          for name in ("postgres", "domain", "sessions", "traces")}, "services": {}}
    services = result["services"]

    def service(name, dockerfile=None, environment=None, port_number=None, health_path="/healthz"):
        value = {"labels": labels, "networks": ["product"], "restart": "no",
                 "security_opt": ["no-new-privileges:true"], "cap_drop": ["ALL"], "pids_limit": 256}
        if dockerfile:
            value.update(image=f"{scope}-{name}:qualification", build={"context": str(ROOT), "dockerfile": dockerfile})
        if environment:
            value["environment"] = environment
        if port_number:
            if name in {"mcp", "frontend"}:
                command = (["node", "-e", f"fetch('http://127.0.0.1:{port_number}{health_path}').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
                           if name == "mcp" else ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"])
            else:
                command = ["python3", "-c", f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port_number}{health_path}', timeout=3)"]
            value["healthcheck"] = {"test": ["CMD", *command], "interval": "3s", "timeout": "5s", "retries": 60}
        services[name] = value
        return value

    postgres = service("postgres", environment={"POSTGRES_USER": "byq_app", "POSTGRES_PASSWORD": "u5-synthetic-db-only", "POSTGRES_DB": "byq_domain"})
    postgres.update(image="postgres:16-alpine", volumes=["postgres:/var/lib/postgresql/data"],
                    cap_drop=[], healthcheck={"test": ["CMD", "pg_isready", "-U", "byq_app", "-d", "byq_domain"], "interval": "3s", "timeout": "5s", "retries": 60})
    policy = "/app/dsh-0.1.2rc1.web-evidence-provenance.json" if release.endswith("2rc1") else "/app/web-evidence-provenance.json"
    backend = service("backend", "services/backend/Dockerfile", {
        "BYQ_DATABASE_URL": "postgresql+psycopg://byq_app:u5-synthetic-db-only@postgres:5432/byq_domain",
        "BYQ_BACKTEST_OBJECT_ROOT": "/var/lib/byq/domain/backtest-objects",
        "BYQ_BOOTSTRAP_ADMIN_USERNAME": "u5-admin", "BYQ_BOOTSTRAP_ADMIN_PASSWORD": "U5AdminTestOnly123",
        "BYQ_CREDENTIAL_RESOLVER_TOKEN": "u5-synthetic-resolver-only",
        "BYQ_FEEDBACK_HUB_RELAY_TOKEN": "u5-synthetic-relay-only", "BYQ_FEEDBACK_HUB_ALLOW_HTTP": "1",
        "BYQ_WEB_EVIDENCE_PROVENANCE_POLICY": policy,
    }, 8000)
    backend.update(volumes=["domain:/var/lib/byq/domain"], depends_on={"postgres": {"condition": "service_healthy"}})
    mcp = service("mcp", "services/mcp/Dockerfile", {"BYQ_BACKEND_URL": "http://backend:8000", "BYQ_MCP_TOKEN": "u5-synthetic-mcp-only", "BYQ_WEB_EVIDENCE_PROVENANCE_POLICY": policy}, 8300)
    mcp["depends_on"] = {"backend": {"condition": "service_healthy"}}
    runtime = service("runtime-adapter", "services/runtime-adapter/Dockerfile.u6-candidate" if release.endswith("2rc1") else "services/runtime-adapter/Dockerfile.u6", {
        "BYQ_MCP_URL": "http://mcp:8300/mcp/v1", "BYQ_MCP_TOKEN": "u5-synthetic-mcp-only",
        "BYQ_BACKEND_URL": "http://backend:8000", "BYQ_CREDENTIAL_RESOLVER_TOKEN": "u5-synthetic-resolver-only",
        "DEEPSEEK_API_KEY": "${DEEPSEEK_API_KEY:-}", "DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions",
    }, 8400, "/readyz")
    runtime.update(networks=["product", "model"], volumes=["sessions:/var/lib/byq/dsh-sessions"], depends_on={"mcp": {"condition": "service_healthy"}})
    gateway = service("gateway", "services/gateway/Dockerfile", {
        "BYQ_PRODUCT_TOKEN": "u5-synthetic-product-only", "BYQ_BACKEND_URL": "http://backend:8000",
        "BYQ_WORKFLOW_TRACE_ROOT": "/var/lib/byq/workflow-traces",
    }, 8100, "/readyz")
    gateway.update(volumes=["traces:/var/lib/byq/workflow-traces"], depends_on={"runtime-adapter": {"condition": "service_healthy"}})
    frontend = service("frontend", "apps/frontend/Dockerfile", port_number=80)
    # nginx's entrypoint/master need their image-default capabilities.
    frontend.update(cap_drop=[], networks=["product", "edge"], ports=[f"127.0.0.1:{port}:80"], depends_on={"gateway": {"condition": "service_healthy"}})
    fake = service("fake-hub", "tests/dsh_upgrade/Dockerfile.fake-hub", port_number=8800)
    fake.update(read_only=True)
    relay = service("feedback-hub-relay", "workers/feedback-hub-relay/Dockerfile", {
        "BYQ_FEEDBACK_BACKEND_URL": "http://backend:8000", "BYQ_FEEDBACK_HUB_RELAY_TOKEN": "u5-synthetic-relay-only",
        "BYQ_FEEDBACK_HUB_URL": "http://fake-hub:8800", "BYQ_FEEDBACK_HUB_ALLOW_HTTP": "1", "BYQ_FEEDBACK_HUB_POLL_SECONDS": "5",
    }, 8750)
    relay.update(read_only=True, depends_on={"backend": {"condition": "service_healthy"}, "fake-hub": {"condition": "service_healthy"}})
    if rehearsal_gate is not None:
        # U6 reuses this closed synthetic stack. This is not a general-purpose
        # bind-mount escape hatch and never accepts a production gate path.
        if (not scope.startswith("byq-u5-u6-") or not isinstance(rehearsal_gate, str)
                or re.fullmatch(r"/tmp/byq-u6-[a-z0-9_]{8}/gate", rehearsal_gate) is None):
            raise ValueError("dedicated U6 temporary gate and scope required")
        result["x-byq-rehearsal-gate"] = rehearsal_gate
        for member in (gateway, runtime):
            member["environment"]["BYQ_CHAT_ADMISSION_FILE"] = "/run/byq-admission/admission.state"
            member["volumes"].append({"type": "bind", "source": rehearsal_gate,
                                      "target": "/run/byq-admission", "read_only": True,
                                      "bind": {"create_host_path": False}})
        # Keep compatibility preparation services stable while replacing only
        # Runtime. Both releases retain disjoint homes in the synthetic volume.
        for member in (backend, mcp):
            member["environment"]["BYQ_WEB_EVIDENCE_PROVENANCE_POLICY"] = "/app/dsh-0.1.2rc1.web-evidence-provenance.json"
        runtime["environment"]["DSH_SESSION_ROOT"] = f"/var/lib/byq/dsh-sessions/{release}"
        runtime["image"] = f"{scope}-runtime-adapter-{release}:qualification"
    return result


def validate_manifest(value):
    try:
        expected = manifest(value["name"], value["x-byq-release"], value["x-byq-port"],
                            rehearsal_gate=value.get("x-byq-rehearsal-gate"))
        if value != expected:
            raise ValueError("test manifest differs from the closed service/resource/credential allowlist")
    except (KeyError, TypeError) as error:
        raise ValueError("invalid test manifest") from error


def docker_json(*args):
    return json.loads(subprocess.check_output(["docker", *args], env=compose_environment(), text=True))


def attest_runtime_build(path: Path) -> dict:
    value = json.loads(path.read_text())
    validate_manifest(value)
    build_id = build_revision.selected_build_id(value["x-byq-release"])
    expected = build_revision.check(build_id)
    container = f"{value['name']}-runtime-adapter-1"
    observed = json.loads(subprocess.check_output([
        "docker", "exec", container, "python3", "-c",
        "from pathlib import Path; print(Path('/opt/byq/builds/build.identity.json').read_text())",
    ], env=compose_environment(), text=True, timeout=10))
    if observed != expected:
        raise ValueError("actual image embeds a different or historical build manifest")
    return {"build_id": build_id, "manifest_hash": build_revision.digest(build_revision.BUILDS / f"{build_id}.json")}


def preflight(path: Path, *, require_healthy=True) -> dict:
    value = json.loads(path.read_text())
    validate_manifest(value)
    scope = value["name"]
    ids = subprocess.check_output(["docker", "ps", "-aq", "--filter", f"label={LABEL}={scope}"], env=compose_environment(), text=True).split()
    if require_healthy and len(ids) != len(SERVICES):
        raise ValueError("exactly the allowlisted test containers must exist")
    containers = docker_json("inspect", *ids) if ids else []
    observed = set()
    images = {}
    for container in containers:
        name = container["Config"]["Labels"].get("com.docker.compose.service")
        if name not in SERVICES or name in observed:
            raise ValueError("unexpected or duplicate service")
        observed.add(name)
        spec = value["services"][name]
        if require_healthy and (not container["State"]["Running"] or container["State"].get("Health", {}).get("Status") != "healthy"):
            raise ValueError("all isolated services must be healthy")
        if container["HostConfig"]["Privileged"] or container["HostConfig"].get("PidMode") == "host":
            raise ValueError("privileged or host process access is forbidden")
        networks = set(container["NetworkSettings"]["Networks"])
        expected_networks = {value["networks"][key]["name"] for key in spec["networks"]}
        if (require_healthy and networks != expected_networks) or not networks <= expected_networks:
            raise ValueError("service network isolation drift")
        actual_env = dict(item.split("=", 1) for item in container["Config"]["Env"])
        for key, expected in spec.get("environment", {}).items():
            if key == "DEEPSEEK_API_KEY":
                continue
            if actual_env.get(key) != expected:
                raise ValueError(f"service environment drift: {name}/{key}")
        for key, content in actual_env.items():
            if content and re.search(r"TOKEN|SECRET|API_KEY|PRIVATE_KEY|DATABASE_URL|CREDENTIAL_KEYRING", key) and key not in spec.get("environment", {}):
                raise ValueError(f"unexpected credential field: {name}/{key}")
        expected_mounts = {(value["volumes"][entry.split(":")[0]]["name"], entry.split(":")[1])
                           if isinstance(entry, str) else (None, entry["target"])
                           for entry in spec.get("volumes", [])}
        if {(mount.get("Name"), mount["Destination"]) for mount in container["Mounts"]} != expected_mounts:
            raise ValueError("unexpected host bind or data volume")
        for mount in container["Mounts"]:
            if mount.get("Name") is None:
                source = value.get("x-byq-rehearsal-gate")
                if (source is None or mount.get("Type") != "bind" or mount.get("Source") != source
                        or mount.get("RW") is not False or Path(source).resolve() != Path(source)):
                    raise ValueError("rehearsal gate mount must be exact, canonical and read-only")
        for bindings in container["NetworkSettings"].get("Ports", {}).values():
            if bindings and any(binding["HostIp"] != "127.0.0.1" for binding in bindings):
                raise ValueError("non-loopback test port")
        if require_healthy:
            published = {key: bindings for key, bindings in container["NetworkSettings"].get("Ports", {}).items() if bindings}
            expected_ports = {}
            for entry in spec.get("ports", []):
                host, host_port, target = entry.split(":")
                expected_ports[target + "/tcp"] = [{"HostIp": host, "HostPort": host_port}]
            if published != expected_ports:
                raise ValueError("expected test ingress port is not actually published")
        images[name] = container["Image"]
    for key, spec in value["networks"].items():
        if not require_healthy:
            # Down remains usable after a partial startup failure. Compose
            # checks resource ownership and the closed manifest fixes names.
            continue
        network = docker_json("network", "inspect", spec["name"])[0]
        if network["Internal"] != spec["internal"] or network["Labels"].get(LABEL) != scope:
            raise ValueError("actual network isolation drift")
    return {"scope": scope, "release": value["x-byq-release"], "frontend": f"http://127.0.0.1:{value['x-byq-port']}",
            "gateway": f"http://127.0.0.1:{value['x-byq-port']}", "fake_hub_container": f"{scope}-fake-hub-1", "images": images}


def run_journey(path: Path, value: dict, command: list[str], environment: dict):
    """Default bounded G6 workflow holds the caller's heavy lock until cleanup."""
    try:
        subprocess.run(command, env=environment, check=True)
        preflight(path)
        subprocess.run([
            sys.executable, str(ROOT / "tests/dsh_upgrade/live_model_probe.py"),
            "G6", "--release", value["x-byq-release"], "--approve", "--stack-file", str(path.resolve()),
        ], env=environment, check=True, timeout=960)
    finally:
        # A partial startup can be cleaned, but resource drift must never
        # broaden deletion. A failed ownership check deliberately stops here.
        preflight(path, require_healthy=False)
        subprocess.run([
            "docker", "compose", "--env-file", "/dev/null", "-p", value["name"],
            "-f", str(path.resolve()), "down", "--volumes",
        ], env=environment, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("render", "run", "up", "preflight", "down"),
                        help="run includes G6 and always-cleanup; up/down are explicit diagnostic lifecycle controls")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--scope")
    parser.add_argument("--release", choices=sorted(RELEASES))
    parser.add_argument("--port", type=int, default=18210)
    parser.add_argument("--model-key-env-file", type=Path)
    parser.add_argument("--rehearsal-gate")
    args = parser.parse_args()
    if args.action == "render":
        value = manifest(args.scope, args.release, args.port, rehearsal_gate=args.rehearsal_gate)
        with args.file.open("x") as output:
            json.dump(value, output, indent=2)
        print(json.dumps({"rendered": str(args.file), "scope": args.scope}))
        return
    value = json.loads(args.file.read_text())
    validate_manifest(value)
    if args.action == "preflight":
        print(json.dumps(preflight(args.file), sort_keys=True))
        return
    command = ["docker", "compose", "--env-file", "/dev/null", "-p", value["name"], "-f", str(args.file.resolve())]
    if args.action in {"up", "run"}:
        command += ["up", "-d", "--build", "--wait", "--wait-timeout", "240", *sorted(SERVICES)]
    else:
        # Only exact resources from this closed, byq-u5-prefixed manifest.
        preflight(args.file, require_healthy=False)
        command += ["down", "--volumes"]
    environment = compose_environment()
    if args.action in {"up", "run"}:
        if args.model_key_env_file:
            environment["DEEPSEEK_API_KEY"] = model_key_from_env_file(args.model_key_env_file)
        available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
        if available < 3145728:
            raise ValueError("insufficient available memory for isolated live stack")
        with open("/tmp/byq-ci-heavy.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "run":
                run_journey(args.file, value, command, environment)
            else:
                subprocess.run(command, env=environment, check=True)
    else:
        subprocess.run(command, env=environment, check=True)


if __name__ == "__main__":
    main()
