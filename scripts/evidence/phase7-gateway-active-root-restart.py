#!/usr/bin/env python3
"""Fail-able same-boot Gateway restart check in a disposable Phase 7 stack."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--override", type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch(r"byq-p7-root-[0-9a-f]{10}", args.project) is None:
        raise SystemExit("refusing a non-disposable Phase 7 project")
    if not args.env_file.is_file() or not args.override.is_file():
        raise SystemExit("explicit disposable Compose files are required")

    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "COMPOSE_DISABLE_ENV_FILE": "1",
           "COMPOSE_ENV_FILES": "/dev/null", "COMPOSE_PROFILES": ""}
    compose = ["docker", "compose", "--env-file", str(args.env_file), "-p", args.project,
               "-f", "compose.yml", "-f", "compose.override.yml", "-f", str(args.override)]

    def run(command: list[str], *, timeout: int = 45, stdin: str | None = None) -> str:
        completed = subprocess.run(command, cwd=root, env=env, text=True,
                                   input=stdin,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, check=True)
        return completed.stdout.strip()

    resolved = json.loads(run(compose + ["config", "--format", "json"]))
    services = resolved["services"]
    if resolved["name"] != args.project or services["gateway"].get("ports", []):
        raise AssertionError("wrong Compose project or public Gateway port")
    if services["runtime-adapter"]["command"] != [
        "python3", "/probe/phase7_compose_gateway_root_probe.py",
    ]:
        raise AssertionError("test-only Adapter fixture is missing")
    database = urlparse(services["backend"]["environment"].get("BYQ_DATABASE_URL", ""))
    if (database.scheme != "postgresql+psycopg" or database.hostname != "postgres"
            or database.path != "/byq_domain"):
        raise AssertionError("Backend is not bound to the disposable project database")
    if (services["runtime-adapter"]["environment"].get("BYQ_DSH_COMPATIBILITY_RELEASE")
            != "dsh-0.1.5rc1"
            or services["runtime-adapter"]["build"]["dockerfile"]
            != "services/runtime-adapter/Dockerfile.post-u8-226-candidate"):
        raise AssertionError("pinned DSH build selection differs from the qualified test")
    for resource in (*resolved["volumes"].values(), *resolved["networks"].values()):
        if not resource["name"].startswith(args.project + "-") or resource.get("external"):
            raise AssertionError("Compose contains a shared or external resource")

    def inspect(service: str) -> dict:
        name = f"{args.project}-{service}-1"
        result = json.loads(run(["docker", "inspect", name]))[0]
        if result["Config"]["Labels"].get("com.docker.compose.project") != args.project:
            raise AssertionError(f"{service} is outside the disposable project")
        return result

    for service in ("gateway", "runtime-adapter", "backend", "mcp", "postgres"):
        item = inspect(service)
        if item["HostConfig"]["RestartPolicy"]["Name"] != "no":
            raise AssertionError(f"{service} restart policy differs from test overlay")
    adapter = inspect("runtime-adapter")
    if adapter["HostConfig"]["PidMode"] not in ("", "private"):
        raise AssertionError("Adapter PID namespace is not the qualified topology")

    # Requests run *inside* the isolated Gateway container. Its token stays in
    # its environment and is never placed in the host command or check output.
    probe = r'''
import json, os, sys, urllib.error, urllib.request
target, method, path = sys.argv[1:4]
arguments = json.load(sys.stdin)
base = {"gateway":"http://127.0.0.1:8100", "backend":"http://backend:8000",
        "adapter":"http://runtime-adapter:8400"}[target]
headers = {"content-type":"application/json"}
if arguments.get("cookie"):
    headers["cookie"] = arguments["cookie"]
payload = arguments.get("payload")
data = None if payload is None else json.dumps(payload).encode()
try:
    with urllib.request.urlopen(urllib.request.Request(base + path, data=data,
            headers=headers, method=method), timeout=8) as response:
        print(json.dumps({"status":response.status, "body":json.load(response),
                          "set_cookie":response.headers.get("Set-Cookie")}))
except urllib.error.HTTPError as error:
    print(json.dumps({"status":error.code, "body":json.load(error)}))
'''

    def request(target: str, method: str, path: str, payload: dict | None = None,
                cookie: str | None = None) -> dict:
        body = json.dumps({"payload": payload, "cookie": cookie}, separators=(",", ":"))
        return json.loads(run(compose + ["exec", "-T", "gateway", "python", "-c",
                                         probe, target, method, path], stdin=body))

    def authority() -> tuple[str, int]:
        adapter_reply = request("adapter", "GET", "/internal/runtime/authority")
        backend_reply = request("backend", "GET", "/internal/runtime-authority/current")
        if adapter_reply["status"] != 200 or backend_reply["status"] != 200:
            raise AssertionError("runtime authority is unavailable")
        boot = adapter_reply["body"]["boot_id"]
        current = backend_reply["body"]
        if boot != current["boot_id"] or current["status"] != "current":
            raise AssertionError("Adapter and Backend boot identities differ")
        return boot, current["authority_epoch"]

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if request("gateway", "GET", "/agent-readyz")["status"] == 200:
            break
        time.sleep(0.2)
    else:
        raise AssertionError("Gateway never established Adapter authority")

    boot_before, epoch_before = authority()
    settings = dict(line.split("=", 1) for line in args.env_file.read_text().splitlines()
                    if "=" in line and not line.startswith("#"))
    login = request("gateway", "POST", "/api/product/auth/login", {
        "username": settings["BYQ_BOOTSTRAP_ADMIN_USERNAME"],
        "password": settings["BYQ_BOOTSTRAP_ADMIN_PASSWORD"],
    })
    if login["status"] != 200 or not isinstance(login.get("set_cookie"), str):
        raise AssertionError(f"disposable user login failed: {login['status']}")
    cookie = login["set_cookie"].split(";", 1)[0]
    if not cookie.startswith("byq_session="):
        raise AssertionError("login did not return a BYQ user session")
    created = request("gateway", "POST", "/v1/agent/sessions", {}, cookie)
    if created["status"] != 201:
        raise AssertionError(f"Product session create failed: {created['status']}")
    conversation = created["body"]["session_id"]
    if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", conversation) is None:
        raise AssertionError("invalid Product conversation ID")
    turn = request("gateway", "POST", f"/v1/agent/sessions/{conversation}/turns",
                   {"content": "Hold the real Phase 7 root request."}, cookie)
    if turn["status"] != 202 or turn["body"].get("accepted") is not True:
        raise AssertionError(f"Product turn was not accepted: {turn['status']}")
    root_id = turn["body"]["run_id"]
    if re.fullmatch(r"[0-9a-f]{32}", root_id) is None:
        raise AssertionError("invalid DSH root ID")

    def roots() -> list[dict]:
        sql = ("SELECT coalesce(json_agg(t), '[]'::json) FROM ("
               "SELECT r.root_run_id,r.status,r.authority_status,r.authority_boot_id,"
               "r.terminal_sequence,r.terminal_event_sha256 "
               "FROM agent_runtime_turns r JOIN product_conversations c "
               "ON c.runtime_session_id=r.session_id "
               f"WHERE c.conversation_id='{conversation}' ORDER BY r.root_run_id) t")
        result = run(compose + ["exec", "-T", "postgres", "sh", "-c",
                                'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "$1"',
                                "phase7-sql", sql])
        return json.loads(result)

    def registered_agent_runs() -> list[dict]:
        sql = ("SELECT coalesce(json_agg(t), '[]'::json) FROM ("
               "SELECT a.run_id,a.role_id,a.status,a.authority_status,a.authority_boot_id,"
               "a.root_run_id FROM agent_runs a JOIN agent_runtime_registrations b "
               "ON b.registration_fingerprint=a.runtime_registration_fingerprint "
               "AND b.root_run_id=a.root_run_id "
               f"WHERE a.root_run_id='{root_id}' "
               "AND a.idempotency_key='phase7-gateway-root-registration' "
               "ORDER BY a.run_id) t")
        result = run(compose + ["exec", "-T", "postgres", "sh", "-c",
                                'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "$1"',
                                "phase7-sql", sql])
        return json.loads(result)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        current_roots = roots()
        logs = run(compose + ["logs", "--no-color", "--tail", "100", "runtime-adapter"])
        agent_runs = registered_agent_runs()
        if (current_roots == [{"root_run_id": root_id, "status": "active",
                               "authority_status": "active", "authority_boot_id": boot_before,
                               "terminal_sequence": None, "terminal_event_sha256": None}]
                and len(agent_runs) == 1 and agent_runs[0]["role_id"] == "quant_orchestrator"
                and agent_runs[0]["status"] == "active"
                and agent_runs[0]["authority_status"] == "active"
                and agent_runs[0]["authority_boot_id"] == boot_before
                and agent_runs[0]["root_run_id"] == root_id
                and '"phase7_gateway_root_probe": "ROOT_PROVIDER_BLOCKED"' in logs):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("actual Product root was not both registered and blocked")
    logs = run(compose + ["logs", "--no-color", "runtime-adapter"])
    provider_calls_before = logs.count('"phase7_gateway_root_probe": "ROOT_PROVIDER_REQUEST"')
    if provider_calls_before != 2 or logs.count(
            '"phase7_gateway_root_probe": "ROOT_PROVIDER_BLOCKED"') != 1:
        raise AssertionError("expected one registration request and one blocked root request")

    adapter_id = adapter["Id"]
    gateway_pid = inspect("gateway")["State"]["Pid"]
    run(compose + ["restart", "gateway"], timeout=60)
    if inspect("gateway")["State"]["Pid"] == gateway_pid:
        raise AssertionError("Gateway process did not restart")
    if inspect("runtime-adapter")["Id"] != adapter_id:
        raise AssertionError("Adapter container changed during Gateway-only restart")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if request("gateway", "GET", "/agent-readyz")["status"] == 200:
                break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        time.sleep(0.2)
    else:
        raise AssertionError("Gateway did not regain Agent readiness")

    boot_after, epoch_after = authority()
    if (boot_after, epoch_after) != (boot_before, epoch_before):
        raise AssertionError("Gateway-only restart rotated Adapter authority")
    if roots() != current_roots:
        raise AssertionError("active Product root changed during Gateway restart")
    if registered_agent_runs() != agent_runs:
        raise AssertionError("registered AgentRun changed during Gateway restart")
    competing = request("gateway", "POST", f"/v1/agent/sessions/{conversation}/turns",
                        {"content": "Competing second turn must stay blocked."}, cookie)
    if competing["status"] != 409:
        raise AssertionError(f"conflicting Product turn was admitted: {competing['status']}")
    if roots() != current_roots:
        raise AssertionError("conflicting turn changed the active root")
    if registered_agent_runs() != agent_runs:
        raise AssertionError("conflicting turn changed the registered AgentRun")
    logs = run(compose + ["logs", "--no-color", "runtime-adapter"])
    if logs.count('"phase7_gateway_root_probe": "ROOT_PROVIDER_REQUEST"') != provider_calls_before:
        raise AssertionError("provider was called again after Gateway restart")
    if f'/internal/runtime/sessions/' not in logs or '/prompt HTTP/1.1" 409 Conflict' not in logs:
        raise AssertionError("the competing turn was not rejected by Adapter prompt admission")
    for service in ("runtime-adapter", "backend", "mcp", "postgres"):
        if not inspect(service)["State"]["Running"]:
            raise AssertionError(f"{service} stopped during Gateway restart")
    print(json.dumps({"result": "PASS", "project": args.project, "root_id": root_id,
                      "boot_unchanged": True, "epoch_unchanged": True,
                      "root_status": "active", "authority_status": "active",
                      "competing_turn_status": competing["status"],
                      "provider_calls_unchanged": provider_calls_before}, sort_keys=True))


if __name__ == "__main__":
    main()
