#!/usr/bin/env python3
"""Fail-able Product MCP unknown-claim proof for a running disposable stack.

The script does not create or remove Compose resources. It verifies the scoped
project, creates one real Product session/turn, releases the private Backend
fixture after its callback begins, checks MCP ``outcome_unknown``, kills Adapter PID 1, then
checks the replacement boot and durable business claim through PostgreSQL.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


PROJECT = re.compile(r"byq-p7-unknown-[0-9a-f]{10}")
ROOT_ID = re.compile(r"[0-9a-f]{32}")
CONVERSATION_ID = re.compile(r"[A-Za-z0-9_-]{8,128}")
BOOT_ID = re.compile(r"[0-9a-f]{32}")
AGENT_RUN_ID = re.compile(r"agent_run_[0-9a-f]{32}")
EXPECTED_TOOLS = {
    "byq_agent_context", "byq_agent_run_start",
    "byq_research_task_create", "byq_strategy_validate",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--override", type=Path, default=Path(
        "scripts/evidence/phase7-product-mcp-unknown-claim.compose.yml"))
    args = parser.parse_args()
    if PROJECT.fullmatch(args.project) is None:
        raise SystemExit("refusing a non-disposable Phase 7 project")
    if not args.env_file.is_file() or not args.override.is_file():
        raise SystemExit("explicit disposable Compose files are required")

    repo = Path(__file__).resolve().parents[2]
    env = {**os.environ, "COMPOSE_DISABLE_ENV_FILE": "1",
           "COMPOSE_ENV_FILES": "/dev/null", "COMPOSE_PROFILES": ""}
    compose = [
        "docker", "compose", "--env-file", str(args.env_file.resolve()),
        "-p", args.project, "-f", "compose.yml", "-f", "compose.override.yml",
        "-f", "scripts/evidence/phase7-product-mcp.compose.yml",
        "-f", str(args.override.resolve()),
    ]

    def run(command: list[str], *, timeout: int = 45, stdin: str | None = None) -> str:
        try:
            completed = subprocess.run(command, cwd=repo, env=env, text=True, input=stdin,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=timeout, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
            # Captured output may contain generated secrets or tool payloads.
            raise RuntimeError(f"isolated Phase 7 operation failed ({type(error).__name__})") from None
        return completed.stdout.strip()

    def compose_run(*parts: str, timeout: int = 45, stdin: str | None = None) -> str:
        return run(compose + list(parts), timeout=timeout, stdin=stdin)

    resolved = json.loads(compose_run("config", "--format", "json"))
    services = resolved.get("services", {})
    required = {"gateway", "runtime-adapter", "backend", "mcp", "mcp-observer", "postgres"}
    if resolved.get("name") != args.project or not required.issubset(services):
        raise AssertionError("resolved Compose project or service set differs")
    if services["gateway"].get("ports", []) or services["mcp-observer"].get("ports", []):
        raise AssertionError("Gateway and MCP observer must have no host ports")
    if services["runtime-adapter"].get("command") != [
            "python3", "/probe/phase7_compose_unknown_claim_probe.py"]:
        raise AssertionError("test-only Adapter probe is missing")
    if services["backend"].get("command") != [
            "python3", "/probe/phase7_compose_unknown_claim_backend.py"]:
        raise AssertionError("test-only Backend callback gate is missing")
    if services["mcp-observer"].get("command") != [
            "python3", "/probe/phase7_product_mcp_observer.py"]:
        raise AssertionError("independent Product MCP observer is missing")
    if (services["runtime-adapter"].get("environment", {}).get("BYQ_MCP_URL")
            != "http://mcp-observer:8350/mcp/v1"):
        raise AssertionError("Adapter is not routed through the scoped MCP observer")
    database = urlparse(services["backend"].get("environment", {}).get("BYQ_DATABASE_URL", ""))
    if (database.scheme != "postgresql+psycopg" or database.hostname != "postgres"
            or database.path != "/byq_domain"):
        raise AssertionError("Backend is not bound to the project PostgreSQL database")
    for service_name in required:
        service = services[service_name]
        if service.get("ports", []):
            raise AssertionError(f"{service_name} unexpectedly publishes a host port")
    for resource in (*resolved.get("volumes", {}).values(), *resolved.get("networks", {}).values()):
        if not resource.get("name", "").startswith(args.project + "-") or resource.get("external"):
            raise AssertionError("Compose contains a shared or external resource")

    def inspect(service: str) -> dict:
        name = f"{args.project}-{service}-1"
        value = json.loads(run(["docker", "inspect", name]))[0]
        labels = value.get("Config", {}).get("Labels", {})
        if labels.get("com.docker.compose.project") != args.project:
            raise AssertionError(f"{service} is outside the disposable Compose project")
        return value

    def gateway_request(target: str, method: str, path: str,
                        payload: dict | None = None, cookie: str | None = None) -> dict:
        script = r'''
import json, sys, urllib.error, urllib.request
target, method, path = sys.argv[1:4]
args = json.load(sys.stdin)
base = {"gateway":"http://127.0.0.1:8100", "adapter":"http://runtime-adapter:8400",
        "backend":"http://backend:8000", "observer":"http://mcp-observer:8350"}[target]
headers = {"content-type":"application/json"}
if args.get("cookie"):
    headers["cookie"] = args["cookie"]
body = None if args.get("payload") is None else json.dumps(args["payload"]).encode()
try:
    with urllib.request.urlopen(urllib.request.Request(base+path, data=body,
            headers=headers, method=method), timeout=8) as response:
        raw=response.read()
        print(json.dumps({"status":response.status,"body":json.loads(raw) if raw else None,
                          "set_cookie":response.headers.get("Set-Cookie")}))
except urllib.error.HTTPError as error:
    raw=error.read()
    try: value=json.loads(raw) if raw else None
    except json.JSONDecodeError: value=None
    print(json.dumps({"status":error.code,"body":value}))
'''
        input_body = json.dumps({"payload": payload, "cookie": cookie}, separators=(",", ":"))
        output = run(compose + ["exec", "-T", "gateway", "python", "-c", script,
                                target, method, path], stdin=input_body)
        return json.loads(output)

    def backend_control(method: str, path: str) -> dict:
        script = r'''
import json, sys, urllib.error, urllib.request
method, path = sys.argv[1:3]
try:
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8351"+path,
            data=b"{}" if method=="POST" else None,
            headers={"content-type":"application/json"},method=method),timeout=5) as response:
        print(json.dumps({"status":response.status,"body":json.load(response)}))
except urllib.error.HTTPError as error:
    print(json.dumps({"status":error.code,"body":json.load(error)}))
'''
        output = run(compose + ["exec", "-T", "backend", "python", "-c", script,
                                method, path])
        return json.loads(output)

    def query(sql: str) -> object:
        command = ["docker", "compose", "--env-file", str(args.env_file.resolve()),
                   "-p", args.project, "-f", "compose.yml", "-f", "compose.override.yml",
                   "-f", "scripts/evidence/phase7-product-mcp.compose.yml", "-f",
                   str(args.override.resolve()), "exec", "-T", "postgres", "sh", "-c",
                   'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "$1"',
                   "phase7-sql", sql]
        return json.loads(run(command))

    def adapter_boot() -> str:
        reply = gateway_request("adapter", "GET", "/internal/runtime/authority")
        boot = (reply.get("body") or {}).get("boot_id")
        if reply.get("status") != 200 or not isinstance(boot, str) or BOOT_ID.fullmatch(boot) is None:
            raise AssertionError("Adapter boot identity is unavailable")
        return boot

    def backend_authority() -> dict:
        reply = gateway_request("backend", "GET", "/internal/runtime-authority/current")
        if reply.get("status") != 200 or not isinstance(reply.get("body"), dict):
            raise AssertionError("Backend current runtime authority is unavailable")
        return reply["body"]

    def observed() -> dict:
        reply = gateway_request("observer", "GET", "/_phase7/observed")
        if reply.get("status") != 200 or not isinstance(reply.get("body"), dict):
            raise AssertionError("independent MCP observer is unavailable")
        return reply["body"]

    def marker(service: str, key: str, expected: str) -> dict | None:
        output = compose_run("logs", "--no-color", service)
        for line in output.splitlines():
            if key not in line or expected not in line:
                continue
            start = line.find("{")
            if start >= 0:
                try:
                    payload = json.loads(line[start:])
                except json.JSONDecodeError:
                    continue
                if payload.get(key) == expected:
                    return payload
        return None

    def wait_for(description: str, predicate, seconds: int = 60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.25)
        raise AssertionError(description)

    def claims(root_id: str) -> list[dict]:
        if ROOT_ID.fullmatch(root_id) is None:
            raise AssertionError("invalid root identity")
        sql = ("SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT claim_id,root_run_id,"
               "task_id,action,idempotency_key,status FROM agent_domain_call_claims "
               f"WHERE root_run_id='{root_id}' ORDER BY claim_id) t")
        value = query(sql)
        if not isinstance(value, list):
            raise AssertionError("Backend claim query returned an invalid shape")
        return value

    def root_rows(root_id: str) -> list[dict]:
        sql = ("SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT root_run_id,status,"
               "authority_status,authority_boot_id FROM agent_runtime_turns "
               f"WHERE root_run_id='{root_id}') t")
        value = query(sql)
        if not isinstance(value, list):
            raise AssertionError("Backend root query returned an invalid shape")
        return value

    def agent_rows(root_id: str) -> list[dict]:
        sql = ("SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT run_id,root_run_id,status,"
               "authority_status,authority_boot_id FROM agent_runs "
               f"WHERE root_run_id='{root_id}') t")
        value = query(sql)
        if not isinstance(value, list):
            raise AssertionError("Backend AgentRun query returned an invalid shape")
        return value

    def artifact_count(task_id: str) -> int:
        if re.fullmatch(r"task_[0-9a-f]{32}", task_id) is None:
            raise AssertionError("invalid ResearchTask identity")
        value = query(f"SELECT count(*) FROM artifacts WHERE task_id='{task_id}'")
        return int(value)

    def read_env_file() -> dict[str, str]:
        values: dict[str, str] = {}
        for source_line in args.env_file.read_text().splitlines():
            line = source_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
        return values

    # Static scope check first; do not disclose resolved environment or config.
    containers = {name: inspect(name) for name in required}
    for name, item in containers.items():
        if item.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") != "no":
            raise AssertionError(f"{name} restart policy is not disabled")
    adapter_container = containers["runtime-adapter"]
    if adapter_container.get("HostConfig", {}).get("PidMode") not in ("", "private"):
        raise AssertionError("Adapter PID namespace is not private")
    if not adapter_container.get("State", {}).get("Running"):
        raise AssertionError("disposable Adapter is not running")
    old_adapter_id = adapter_container["Id"]
    wait_for("Gateway did not become Agent ready", lambda:
        gateway_request("gateway", "GET", "/agent-readyz").get("status") == 200)
    old_boot = adapter_boot()
    authority = backend_authority()
    if authority.get("boot_id") != old_boot or authority.get("status") != "current":
        raise AssertionError("initial Adapter and Backend authority differ")

    settings = read_env_file()
    login = gateway_request("gateway", "POST", "/api/product/auth/login", {
        "username": settings.get("BYQ_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": settings.get("BYQ_BOOTSTRAP_ADMIN_PASSWORD", "password"),
    })
    set_cookie = login.get("set_cookie")
    if login.get("status") != 200 or not isinstance(set_cookie, str):
        raise AssertionError("disposable BYQ user login failed")
    cookie = set_cookie.split(";", 1)[0]
    if not cookie.startswith("byq_session="):
        raise AssertionError("Product login did not create a durable BYQ session")
    session = gateway_request("gateway", "POST", "/v1/agent/sessions", {}, cookie)
    if session.get("status") != 201:
        raise AssertionError("Product Agent session creation failed")
    conversation_id = (session.get("body") or {}).get("session_id")
    if not isinstance(conversation_id, str) or CONVERSATION_ID.fullmatch(conversation_id) is None:
        raise AssertionError("Product session identity is invalid")
    turn = gateway_request("gateway", "POST", f"/v1/agent/sessions/{conversation_id}/turns",
                           {"content": "Run the isolated Phase 7 unknown-claim probe."}, cookie)
    if turn.get("status") != 202 or (turn.get("body") or {}).get("accepted") is not True:
        raise AssertionError("Product turn was not accepted")
    root_id = (turn.get("body") or {}).get("run_id")
    if not isinstance(root_id, str) or ROOT_ID.fullmatch(root_id) is None:
        raise AssertionError("Product turn root identity is invalid")

    control = wait_for("Backend domain callback was not entered",
                       lambda: (status if (status := backend_control("GET", "/_phase7/unknown-claim"))
                                and status.get("body", {}).get("entered") else None))
    # The callback intentionally holds the mutation request. It must be
    # released before MCP can return the unknown result to DSH.
    released = backend_control("POST", "/_phase7/unknown-claim/release")
    if released.get("status") != 200:
        raise AssertionError("private Backend callback release failed")
    wait_for("Backend callback transaction did not exit",
             lambda: (status if (status := backend_control("GET", "/_phase7/unknown-claim"))
                      and status.get("body", {}).get("finished") else None))
    unknown_marker = wait_for(
        "real Product MCP did not return non-retryable outcome_unknown",
        lambda: marker("runtime-adapter", "phase7_unknown_claim_probe", "MCP_OUTCOME_UNKNOWN"),
        seconds=120,
    )
    if (unknown_marker.get("status_is_outcome_unknown") is not True
            or unknown_marker.get("retryable_is_false") is not True):
        raise AssertionError("Adapter probe did not observe the exact MCP unknown result")
    before_observer = observed()
    tool_calls = [item for item in before_observer.get("requests", [])
                  if item.get("method") == "tools/call"]
    counts = Counter(item.get("tool") for item in tool_calls)
    if counts != Counter({name: 1 for name in EXPECTED_TOOLS}):
        raise AssertionError("Product MCP did not observe exactly the required four tool calls")
    if any(item.get("http_status") != "200" or item.get("mcp_error") != "false"
           for item in tool_calls):
        raise AssertionError("one Product MCP tool call did not return a successful transport result")
    initial_roots = root_rows(root_id)
    initial_runs = agent_rows(root_id)
    current_claims = claims(root_id)
    if (len(initial_roots) != 1 or initial_roots[0].get("status") != "active"
            or initial_roots[0].get("authority_status") != "active"
            or initial_roots[0].get("authority_boot_id") != old_boot):
        raise AssertionError("Product root was not active on the original Adapter boot")
    if (len(initial_runs) != 1 or AGENT_RUN_ID.fullmatch(initial_runs[0].get("run_id", "")) is None
            or initial_runs[0].get("status") != "active"
            or initial_runs[0].get("authority_status") != "active"
            or initial_runs[0].get("authority_boot_id") != old_boot):
        raise AssertionError("registered AgentRun was not active on the original boot")
    if (len(current_claims) != 1 or current_claims[0].get("action") != "byq_strategy_validate"
            or current_claims[0].get("status") != "executing"):
        raise AssertionError("expected exactly one executing strategy-validation claim")
    task_id = current_claims[0].get("task_id")
    if not isinstance(task_id, str) or artifact_count(task_id) != 0:
        raise AssertionError("a StrategyDraft artifact exists for the unknown claim")

    if claims(root_id) != current_claims or artifact_count(task_id) != 0:
        raise AssertionError("callback release changed the durable unknown claim or created an artifact")

    process_output = run(["docker", "top", f"{args.project}-runtime-adapter-1",
                          "-eo", "pid,ppid,comm,args"])
    process_lines = process_output.splitlines()[1:]
    pids = [int(line.split()[0]) for line in process_lines if line.strip()]
    if len(pids) < 2 or not any("deepseek-harness-sdk-runtime" in line for line in process_lines):
        raise AssertionError("pinned DSH runtime process was not live before Adapter PID-1 kill")
    compose_run("kill", "-s", "SIGKILL", "runtime-adapter")
    stopped = inspect("runtime-adapter").get("State", {})
    if stopped.get("Running") or stopped.get("ExitCode") != 137:
        raise AssertionError("Adapter PID 1 did not stop under SIGKILL")
    wait_for("Adapter/DSH host processes survived PID-1 death",
             lambda: not any(Path(f"/proc/{pid}").exists() for pid in pids), seconds=10)
    wait_for("Gateway stayed ready after Adapter death",
             lambda: gateway_request("gateway", "GET", "/agent-readyz").get("status") == 503,
             seconds=30)
    if observed() != before_observer:
        raise AssertionError("old DSH issued another Product MCP request after Adapter death")
    for service in ("backend", "mcp", "mcp-observer", "postgres", "gateway"):
        if not inspect(service).get("State", {}).get("Running"):
            raise AssertionError(f"{service} stopped during Adapter death")

    compose_run("up", "-d", "--no-deps", "--force-recreate", "runtime-adapter", timeout=180)
    new_adapter = wait_for("replacement Adapter container did not start",
                           lambda: (item if (item := inspect("runtime-adapter"))
                                    and item.get("State", {}).get("Running")
                                    and item.get("Id") != old_adapter_id else None), seconds=90)
    if new_adapter.get("HostConfig", {}).get("PidMode") not in ("", "private"):
        raise AssertionError("replacement Adapter PID namespace is not private")
    wait_for("Gateway did not become ready after authority rotation",
             lambda: gateway_request("gateway", "GET", "/agent-readyz").get("status") == 200,
             seconds=90)
    new_boot = adapter_boot()
    if new_boot == old_boot or backend_authority().get("boot_id") != new_boot:
        raise AssertionError("replacement Adapter did not establish a fresh Backend boot")

    final_roots = root_rows(root_id)
    final_runs = agent_rows(root_id)
    final_claims = claims(root_id)
    after_observer = observed()
    if (len(final_roots) != 1 or final_roots[0].get("authority_status") != "authority_revoked_unconfirmed"
            or final_roots[0].get("authority_boot_id") != old_boot):
        raise AssertionError("old root was not revoked_unconfirmed under its original boot")
    if (len(final_runs) != 1 or final_runs[0].get("authority_status") != "authority_revoked_unconfirmed"
            or final_runs[0].get("authority_boot_id") != old_boot):
        raise AssertionError("old AgentRun was not revoked_unconfirmed under its original boot")
    if (len(final_claims) != 1 or final_claims[0].get("claim_id") != current_claims[0].get("claim_id")
            or final_claims[0].get("status") != "executing"):
        raise AssertionError("claim changed or a new claim appeared after boot rotation")
    if artifact_count(task_id) != 0:
        raise AssertionError("an artifact appeared after boot rotation")
    if after_observer != before_observer:
        raise AssertionError("Adapter replacement replayed a Product MCP tool")
    if not inspect("runtime-adapter").get("State", {}).get("Running"):
        raise AssertionError("replacement Adapter is not running")

    print(json.dumps({"result": "PASS", "project": args.project,
                      "mcp_tool_calls": dict(sorted(counts.items())),
                      "outcome_unknown": True, "retryable": False,
                      "claim_count": len(final_claims), "claim_status": final_claims[0]["status"],
                      "artifact_count": 0, "adapter_exit_code": 137,
                      "old_dsh_processes_gone": len(pids), "boot_rotated": new_boot != old_boot,
                      "old_root_authority": final_roots[0]["authority_status"],
                      "old_run_authority": final_runs[0]["authority_status"],
                      "mcp_replay_count": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
