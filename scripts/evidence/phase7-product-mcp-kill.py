#!/usr/bin/env python3
"""Fail-able host check for the isolated Phase 7 Product MCP kill boundary.

The disposable stack must already be running with the Phase 7 child probe and
independent MCP observer. This script kills only that project's Adapter; it
does not create, restore, or clean any Docker resource.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--override", type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch(r"byq-p7-mcp-[0-9a-f]{10}", args.project) is None:
        raise SystemExit("refusing a non-disposable Phase 7 project")
    if not args.env_file.is_file() or not args.override.is_file():
        raise SystemExit("explicit disposable Compose files are required")

    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "COMPOSE_DISABLE_ENV_FILE": "1",
           "COMPOSE_ENV_FILES": "/dev/null", "COMPOSE_PROFILES": ""}
    compose = ["docker", "compose", "--env-file", str(args.env_file),
               "-p", args.project, "-f", "compose.yml", "-f", "compose.override.yml",
               "-f", str(args.override)]

    def run(command: list[str], *, timeout: int = 45) -> str:
        completed = subprocess.run(command, cwd=root, env=env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, check=True)
        return completed.stdout

    resolved = json.loads(run(compose + ["config", "--format", "json"]))
    services = resolved["services"]
    if resolved["name"] != args.project:
        raise AssertionError("Compose resolved a different project")
    if services["gateway"].get("ports", []) or services["runtime-adapter"]["command"] != [
        "python3", "/probe/phase7_compose_child_probe.py",
    ] or services["mcp-observer"]["command"] != [
        "python3", "/probe/phase7_product_mcp_observer.py",
    ]:
        raise AssertionError("test-only services or private Gateway port are not configured")
    if (services["runtime-adapter"]["environment"].get("BYQ_PHASE7_PRODUCT_MCP_OBSERVER_URL")
            != "http://mcp-observer:8350/mcp/v1"):
        raise AssertionError("Adapter does not target the independent MCP observer")
    for resource in (*resolved["volumes"].values(), *resolved["networks"].values()):
        if not resource["name"].startswith(args.project + "-") or resource.get("external"):
            raise AssertionError("Compose contains a shared/external volume or network")

    def inspect(service: str) -> dict:
        name = f"{args.project}-{service}-1"
        result = json.loads(run(["docker", "inspect", name]))[0]
        if result["Config"]["Labels"].get("com.docker.compose.project") != args.project:
            raise AssertionError(f"{service} is outside the disposable project")
        return result

    adapter = inspect("runtime-adapter")
    if (adapter["HostConfig"]["RestartPolicy"]["Name"] != "no"
            or adapter["HostConfig"]["PidMode"] not in ("", "private")):
        raise AssertionError("Adapter PID namespace/restart policy is not the qualified test topology")

    gateway_probe = (
        'import urllib.request,urllib.error; u="http://127.0.0.1:8100/agent-readyz";'
        '\ntry:\n r=urllib.request.urlopen(u,timeout=3); print(r.status)'
        '\nexcept urllib.error.HTTPError as e: print(e.code)'
    )

    def gateway_status() -> int:
        return int(run(compose + ["exec", "-T", "gateway", "python", "-c", gateway_probe]).strip())

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if gateway_status() == 200:
            break
        time.sleep(0.2)
    else:
        raise AssertionError("Gateway never established this Adapter boot")

    status_code = ('import json,urllib.request; print(json.dumps(json.load('
                   'urllib.request.urlopen("http://mcp-observer:8350/_phase7/observed",timeout=5))))')

    def observed() -> dict:
        return json.loads(run(compose + ["exec", "-T", "gateway", "python", "-c", status_code]))

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        logs = run(compose + ["logs", "--no-color", "--tail", "80", "runtime-adapter"])
        before = observed()
        if ('"phase7_child_probe": "BLOCKED_CHILD_LIVE"' in logs
                and before["role_successes"] == 1 and before["tools_call_count"] == 1):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("real Product MCP success and live DSH child were not both observed")

    process_lines = run(["docker", "top", f"{args.project}-runtime-adapter-1",
                         "-eo", "pid,ppid,comm,args"]).splitlines()[1:]
    pids = [int(line.split()[0]) for line in process_lines if line.strip()]
    if len(pids) < 2 or not any("deepseek-harness-sdk-runtime" in line for line in process_lines):
        raise AssertionError("pinned DSH runtime process was not live at Adapter kill")

    run(compose + ["kill", "-s", "SIGKILL", "runtime-adapter"])
    stopped = inspect("runtime-adapter")["State"]
    if stopped["Running"] or stopped["ExitCode"] != 137:
        raise AssertionError("Adapter did not stop under SIGKILL with restart disabled")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(Path(f"/proc/{pid}").exists() for pid in pids):
        time.sleep(0.1)
    if any(Path(f"/proc/{pid}").exists() for pid in pids):
        raise AssertionError("an old Adapter/DSH host PID survived")
    if gateway_status() != 503:
        raise AssertionError("Gateway admitted Agent traffic after Adapter death")

    time.sleep(3)
    after = observed()
    for field in ("count", "tools_call_count", "role_successes"):
        if after[field] != before[field]:
            raise AssertionError(f"independent Product MCP observer changed after death: {field}")
    for service in ("mcp", "mcp-observer", "backend", "gateway"):
        if not inspect(service)["State"]["Running"]:
            raise AssertionError(f"{service} stopped during the Adapter kill check")
    print(json.dumps({"result": "PASS", "project": args.project,
                      "role_successes": before["role_successes"],
                      "tools_call_count": before["tools_call_count"],
                      "observer_before": before["count"], "observer_after": after["count"],
                      "adapter_exit_code": 137, "old_processes_gone": len(pids),
                      "gateway_after_kill": 503, "quiet_seconds": 3}, sort_keys=True))


if __name__ == "__main__":
    main()
