#!/usr/bin/env python3
"""Fail-able Product-path proof for exact terminal close and a lost HTTP reply."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse


PROJECT_PATTERN = re.compile(r"byq-p7-term-[0-9a-f]{10}")
ROOT_PATTERN = re.compile(r"[0-9a-f]{32}")
CONVERSATION_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,128}")
ADAPTER_SERVICE = "runtime-adapter"
PROXY_SERVICE = "backend-close-proxy"
REQUIRED_SERVICES = (
    "gateway", ADAPTER_SERVICE, "backend", "mcp", "postgres", PROXY_SERVICE,
)
EXPECTED_CLOSE_SCHEMA = "agent-run-lifecycle-receipt.v1"
EXPECTED_PROXY_FIELDS = {
    "close_requests", "first_forwarded", "dropped_responses",
    "pre_allow_rejections", "pre_allow_status", "withheld_rejections", "retry_forwarded",
    "allow_armed", "allow_count", "first_status", "retry_status",
    "first_receipt", "retry_receipt", "root_run_id",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--override", type=Path, required=True)
    args = parser.parse_args()
    if PROJECT_PATTERN.fullmatch(args.project) is None:
        raise SystemExit("refusing a non-disposable Phase 7 project")
    if not args.env_file.is_file() or not args.override.is_file():
        raise SystemExit("explicit disposable Compose files are required")

    root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "COMPOSE_ENV_FILES": "/dev/null",
        "COMPOSE_PROFILES": "",
    }
    compose = [
        "docker", "compose", "--env-file", str(args.env_file.resolve()),
        "-p", args.project, "-f", "compose.yml", "-f", "compose.override.yml",
        "-f", str(args.override.resolve()),
    ]

    def run(command: list[str], *, timeout: int = 45, stdin: str | None = None) -> str:
        try:
            completed = subprocess.run(
                command, cwd=root, env=env, text=True, input=stdin,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            # Never echo a process environment, request body or captured output.
            operation = Path(command[0]).name if command else "process"
            raise RuntimeError(
                f"isolated Phase 7 {operation} operation failed ({type(exc).__name__})"
            ) from None
        return completed.stdout.strip()

    resolved = json.loads(run(compose + ["config", "--format", "json"]))
    services = resolved.get("services", {})
    if resolved.get("name") != args.project:
        raise AssertionError("resolved Compose project name differs")
    if not set(REQUIRED_SERVICES).issubset(services):
        raise AssertionError("the terminal-close fixture services are incomplete")
    gateway_config = services["gateway"]
    if gateway_config.get("ports", []):
        raise AssertionError("Gateway must remain private")
    if services[PROXY_SERVICE].get("ports", []):
        raise AssertionError("Backend close proxy must remain private")
    if services[ADAPTER_SERVICE].get("command") != [
        "python3", "/probe/phase7_compose_terminal_probe.py",
    ]:
        raise AssertionError("test-only terminal Adapter fixture is missing")
    if services[PROXY_SERVICE].get("command") != [
        "python3", "/probe/phase7_backend_close_proxy.py",
    ]:
        raise AssertionError("test-only Backend close proxy fixture is missing")
    gateway_environment = gateway_config.get("environment", {})
    if gateway_environment.get("BYQ_BACKEND_URL") != "http://backend-close-proxy:8351":
        raise AssertionError("Gateway is not routed through the isolated close proxy")
    adapter_environment = services[ADAPTER_SERVICE].get("environment", {})
    if (adapter_environment.get("BYQ_PHASE7_TERMINAL_FIXTURE") != "1"
            or adapter_environment.get("BYQ_DSH_COMPATIBILITY_RELEASE") != "dsh-0.1.5rc1"
            or services[ADAPTER_SERVICE].get("build", {}).get("dockerfile")
            != "services/runtime-adapter/Dockerfile.post-u8-226-candidate"):
        raise AssertionError("Adapter fixture or pinned DSH selection differs")
    proxy_environment = services[PROXY_SERVICE].get("environment", {})
    if (proxy_environment.get("BYQ_PHASE7_TERMINAL_CLOSE_PROXY") != "1"
            or proxy_environment.get("BYQ_PHASE7_BACKEND_URL") != "http://backend:8000"):
        raise AssertionError("isolated close proxy is not bound to the project Backend")
    database = urlparse(services["backend"].get("environment", {}).get("BYQ_DATABASE_URL", ""))
    if (database.scheme != "postgresql+psycopg" or database.hostname != "postgres"
            or database.path != "/byq_domain"):
        raise AssertionError("Backend is not bound to the disposable project database")
    for resource in (*resolved.get("volumes", {}).values(), *resolved.get("networks", {}).values()):
        if not resource.get("name", "").startswith(args.project + "-") or resource.get("external"):
            raise AssertionError("Compose contains a shared or external resource")

    def inspect(service: str) -> dict:
        name = f"{args.project}-{service}-1"
        item = json.loads(run(["docker", "inspect", name]))[0]
        if item.get("Config", {}).get("Labels", {}).get("com.docker.compose.project") != args.project:
            raise AssertionError(f"{service} is outside the disposable project")
        if item.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") != "no":
            raise AssertionError(f"{service} restart policy differs from the test overlay")
        if not item.get("State", {}).get("Running"):
            raise AssertionError(f"{service} is not running")
        return item

    containers = {service: inspect(service) for service in REQUIRED_SERVICES}
    adapter_container = containers[ADAPTER_SERVICE]
    if adapter_container.get("HostConfig", {}).get("PidMode") not in ("", "private"):
        raise AssertionError("Adapter PID namespace is not private")
    if adapter_container.get("State", {}).get("Pid", 0) <= 0:
        raise AssertionError("Adapter PID 1 is unavailable")
    adapter_container_id = adapter_container["Id"]

    # Requests run inside the private Gateway container. Credentials, cookie,
    # and JSON request bodies cross docker exec only through stdin.
    gateway_probe = r'''
import json, sys, urllib.error, urllib.request
target, method, path = sys.argv[1:4]
arguments = json.load(sys.stdin)
base = {
    "gateway": "http://127.0.0.1:8100",
    "backend": "http://backend:8000",
    "adapter": "http://runtime-adapter:8400",
    "proxy": "http://backend-close-proxy:8351",
}[target]
headers = {"content-type": "application/json"}
if arguments.get("cookie"):
    headers["cookie"] = arguments["cookie"]
payload = arguments.get("payload")
data = None if payload is None else json.dumps(payload).encode()
try:
    with urllib.request.urlopen(urllib.request.Request(
            base + path, data=data, headers=headers, method=method), timeout=8) as response:
        raw = response.read()
        body = json.loads(raw) if raw else None
        print(json.dumps({"status": response.status, "body": body,
                          "set_cookie": response.headers.get("Set-Cookie")}))
except urllib.error.HTTPError as error:
    raw = error.read()
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = None
    print(json.dumps({"status": error.code, "body": body}))
'''

    def gateway_request(
        target: str, method: str, path: str, payload: dict | None = None,
        cookie: str | None = None,
    ) -> dict:
        body = json.dumps(
            {"payload": payload, "cookie": cookie}, separators=(",", ":"),
        )
        output = run(compose + [
            "exec", "-T", "gateway", "python3", "-c", gateway_probe,
            target, method, path,
        ], stdin=body)
        return json.loads(output)

    # The private proxy has no host port. Host-controlled operations use a
    # throwaway Python process in its container and pass JSON over stdin.
    proxy_probe = r'''
import json, sys, urllib.error, urllib.request
method, path = sys.argv[1:3]
arguments = json.load(sys.stdin)
payload = arguments.get("payload")
data = None if payload is None else json.dumps(payload).encode()
try:
    with urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8351" + path, data=data,
            headers={"content-type": "application/json"}, method=method), timeout=6) as response:
        raw = response.read()
        print(json.dumps({"status": response.status, "body": json.loads(raw) if raw else None}))
except urllib.error.HTTPError as error:
    raw = error.read()
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = None
    print(json.dumps({"status": error.code, "body": body}))
'''

    def proxy_request(method: str, path: str, payload: dict | None = None) -> dict:
        output = run(compose + [
            "exec", "-T", PROXY_SERVICE, "python3", "-c", proxy_probe, method, path,
        ], stdin=json.dumps({"payload": payload}, separators=(",", ":")))
        return json.loads(output)

    sql_probe = (
        'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        '-t -A -c "$1"'
    )

    def query(sql: str) -> object:
        result = run(compose + [
            "exec", "-T", "postgres", "sh", "-c", sql_probe, "phase7-sql", sql,
        ])
        return json.loads(result)

    def conversation_record(conversation_id: str) -> dict:
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT conversation_id,runtime_session_id,trace_id FROM product_conversations "
            f"WHERE conversation_id='{conversation_id}') t"
        )
        rows = query(sql)
        if not isinstance(rows, list) or len(rows) != 1:
            raise AssertionError("Product conversation does not have one Backend binding")
        return rows[0]

    def roots(conversation_id: str) -> list[dict]:
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT r.root_run_id,r.status,r.authority_status,r.authority_boot_id,"
            "r.terminal_sequence,r.terminal_event_sha256 "
            "FROM agent_runtime_turns r JOIN product_conversations c "
            "ON c.runtime_session_id=r.session_id "
            f"WHERE c.conversation_id='{conversation_id}' ORDER BY r.root_run_id) t"
        )
        result = query(sql)
        if not isinstance(result, list):
            raise AssertionError("Backend root query did not return a list")
        return result

    def registered_agent_runs(root_id: str) -> list[dict]:
        sql = (
            "SELECT coalesce(json_agg(t), '[]'::json) FROM ("
            "SELECT a.run_id,a.role_id,a.status,a.authority_status,a.authority_boot_id,"
            "a.root_run_id,a.idempotency_key FROM agent_runs a "
            "JOIN agent_runtime_registrations b "
            "ON b.registration_fingerprint=a.runtime_registration_fingerprint "
            "AND b.root_run_id=a.root_run_id "
            f"WHERE a.root_run_id='{root_id}' "
            "AND a.idempotency_key='phase7-terminal-registration' ORDER BY a.run_id) t"
        )
        result = query(sql)
        if not isinstance(result, list):
            raise AssertionError("Backend AgentRun query did not return a list")
        return result

    def adapter_journal_ack(session_id: str, root_id: str) -> dict | None:
        # Read only the exact durable receipt; do not emit the journal or context.
        script = r'''
import json, os, pathlib, sys
session_id, root_id = sys.argv[1:3]
base = pathlib.Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions"))
path = base / "byq-lifecycle-evidence" / (session_id + ".json")
try:
    envelope = json.loads(path.read_text())
    state = envelope["state"]
    receipt = state["terminal_acks"].get(root_id)
except FileNotFoundError:
    receipt = None
print(json.dumps({"receipt": receipt}))
'''
        output = run(compose + [
            "exec", "-T", ADAPTER_SERVICE, "python3", "-c", script, session_id, root_id,
        ])
        reply = json.loads(output)
        return reply.get("receipt")

    def provider_markers() -> list[dict]:
        logs = run(compose + ["logs", "--no-color", ADAPTER_SERVICE])
        markers: list[dict] = []
        for line in logs.splitlines():
            if '"phase7_terminal_fixture":' not in line:
                continue
            start = line.find("{")
            if start < 0:
                continue
            try:
                row = json.loads(line[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and "phase7_terminal_fixture" in row:
                markers.append(row)
        return markers

    def wait_for(description: str, predicate, *, seconds: int = 30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.2)
        raise AssertionError(description)

    def authority_boot_id() -> str:
        reply = gateway_request("adapter", "GET", "/internal/runtime/authority")
        if reply["status"] != 200:
            raise AssertionError("Adapter authority identity is unavailable")
        boot_id = reply["body"].get("boot_id")
        if not isinstance(boot_id, str) or ROOT_PATTERN.fullmatch(boot_id) is None:
            raise AssertionError("Adapter authority identity is malformed")
        return boot_id

    def lifecycle_status(cookie: str) -> dict:
        reply = gateway_request(
            "gateway", "GET",
            f"/v1/agent/sessions/{conversation_id}/lifecycle-delivery", cookie=cookie,
        )
        if reply["status"] != 200 or not isinstance(reply.get("body"), dict):
            raise AssertionError("Gateway lifecycle delivery status is unavailable")
        return reply["body"]

    def proxy_observed() -> dict:
        reply = proxy_request("GET", "/_phase7/observed")
        if reply["status"] != 200 or not isinstance(reply.get("body"), dict):
            raise AssertionError("close proxy observation endpoint is unavailable")
        observed = reply["body"]
        if set(observed) != EXPECTED_PROXY_FIELDS:
            raise AssertionError("close proxy observation schema differs")
        return observed

    # Wait for Gateway readiness without changing any container state.
    wait_for(
        "Gateway never established Adapter authority",
        lambda: gateway_request("gateway", "GET", "/agent-readyz")["status"] == 200,
    )
    boot_id = authority_boot_id()
    settings: dict[str, str] = {}
    for line in args.env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        settings[key.strip()] = value
    username = settings.get("BYQ_BOOTSTRAP_ADMIN_USERNAME")
    password = settings.get("BYQ_BOOTSTRAP_ADMIN_PASSWORD")
    if not username or not password:
        raise AssertionError("generated disposable Product API test credentials are missing")
    login = gateway_request("gateway", "POST", "/api/product/auth/login", {
        "username": username, "password": password,
    })
    if login["status"] != 200 or not isinstance(login.get("set_cookie"), str):
        raise AssertionError("generated disposable Product API test account could not log in")
    cookie = login["set_cookie"].split(";", 1)[0]
    if not cookie.startswith("byq_session="):
        raise AssertionError("Product login did not return a BYQ user session")

    created = gateway_request("gateway", "POST", "/v1/agent/sessions", {}, cookie)
    if created["status"] != 201:
        raise AssertionError("Product API conversation creation failed")
    conversation_id = created["body"].get("session_id")
    if not isinstance(conversation_id, str) or CONVERSATION_PATTERN.fullmatch(conversation_id) is None:
        raise AssertionError("Product API returned an invalid conversation identity")
    conversation = conversation_record(conversation_id)
    runtime_session_id = conversation["runtime_session_id"]
    if not isinstance(runtime_session_id, str) or CONVERSATION_PATTERN.fullmatch(runtime_session_id) is None:
        raise AssertionError("Backend returned an invalid runtime session identity")

    turn = gateway_request(
        "gateway", "POST", f"/v1/agent/sessions/{conversation_id}/turns",
        {"content": "Finish the isolated Phase 7 terminal-close probe."}, cookie,
    )
    if turn["status"] != 202 or turn["body"].get("accepted") is not True:
        raise AssertionError("Product API did not accept the terminal-close probe turn")
    root_id = turn["body"].get("run_id")
    if not isinstance(root_id, str) or ROOT_PATTERN.fullmatch(root_id) is None:
        raise AssertionError("Product API returned an invalid root identity")

    def active_snapshot() -> tuple[list[dict], list[dict], list[dict]]:
        current_roots = roots(conversation_id)
        agent_runs = registered_agent_runs(root_id)
        markers = provider_markers()
        waiting = [row for row in markers
                   if row.get("phase7_terminal_fixture") == "PROVIDER_WAITING"
                   and row.get("request_number") == 2]
        if (len(current_roots) == 1
                and current_roots[0]["root_run_id"] == root_id
                and current_roots[0]["status"] == "active"
                and current_roots[0]["authority_status"] == "active"
                and current_roots[0]["authority_boot_id"] == boot_id
                and current_roots[0]["terminal_sequence"] is None
                and current_roots[0]["terminal_event_sha256"] is None
                and len(agent_runs) == 1
                and agent_runs[0]["role_id"] == "quant_orchestrator"
                and agent_runs[0]["status"] == "active"
                and agent_runs[0]["authority_status"] == "active"
                and agent_runs[0]["authority_boot_id"] == boot_id
                and agent_runs[0]["root_run_id"] == root_id
                and len(waiting) == 1):
            return current_roots, agent_runs, markers
        return []

    current_roots, active_agent_runs, active_markers = wait_for(
        "Product root was not registered and blocked at the second provider request",
        active_snapshot,
    )
    request_markers = [row for row in active_markers
                       if row.get("phase7_terminal_fixture") == "PROVIDER_REQUEST"]
    if len(request_markers) != 2 or any(
            row.get("request_number") != index for index, row in enumerate(request_markers, 1)):
        raise AssertionError("the active root did not make exactly the expected two model requests")
    if any(row.get("pid1") != 1 for row in active_markers if "pid1" in row):
        raise AssertionError("the scripted provider is not owned by Adapter PID 1")

    def active_delivery_ready() -> dict | None:
        status = lifecycle_status(cookie)
        if (status.get("pending_events") == 0
                and status.get("exhausted_events") == 0
                and status.get("rejected_events") == 0
                and status.get("state") == "up_to_date"):
            return status
        return None

    wait_for(
        "Gateway did not acknowledge the active AgentRun registration",
        active_delivery_ready,
    )

    # Signal only the qualified Adapter container. Its PID-1 handler releases
    # one synthetic final completion from the loopback provider.
    current_adapter = inspect(ADAPTER_SERVICE)
    if current_adapter["Id"] != adapter_container_id:
        raise AssertionError("Adapter container changed before the terminal signal")
    run(["docker", "kill", "--signal=USR1", f"{args.project}-{ADAPTER_SERVICE}-1"])
    wait_for(
        "Adapter PID 1 did not release the synthetic final answer",
        lambda: any(row.get("phase7_terminal_fixture") == "FINAL_ANSWER"
                    for row in provider_markers()),
    )

    def first_close_observed() -> dict | None:
        observed = proxy_observed()
        if (observed["root_run_id"] == root_id
                and observed["first_forwarded"] == 1
                and observed["dropped_responses"] == 1
                and observed["first_status"] == 200
                and observed["first_receipt"] is not None):
            return observed
        return None

    before_allow = wait_for(
        "Proxy did not observe the first Backend close and withhold its retry",
        first_close_observed,
        seconds=35,
    )
    first_receipt = before_allow["first_receipt"]
    if (not isinstance(first_receipt, dict)
            or set(first_receipt) != {
                "schema_version", "root_run_id", "sequence", "event_sha256",
            }
            or first_receipt.get("schema_version") != EXPECTED_CLOSE_SCHEMA
            or first_receipt.get("root_run_id") != root_id
            or type(first_receipt.get("sequence")) is not int
            or first_receipt["sequence"] < 1
            or not isinstance(first_receipt.get("event_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", first_receipt["event_sha256"]) is None):
        raise AssertionError("proxy captured a malformed or foreign Backend close receipt")

    terminal_rows = roots(conversation_id)
    terminal_agent_runs = registered_agent_runs(root_id)
    expected_root = {
        "root_run_id": root_id,
        "status": "completed",
        "authority_status": "closed",
        "authority_boot_id": boot_id,
        "terminal_sequence": first_receipt["sequence"],
        "terminal_event_sha256": first_receipt["event_sha256"],
    }
    if terminal_rows != [expected_root]:
        raise AssertionError("Backend root is not closed with the exact first close receipt")
    if (len(terminal_agent_runs) != 1
            or terminal_agent_runs[0]["root_run_id"] != root_id
            or terminal_agent_runs[0]["role_id"] != "quant_orchestrator"
            or terminal_agent_runs[0]["status"] != "completed"
            or terminal_agent_runs[0]["authority_status"] != "closed"
            or terminal_agent_runs[0]["authority_boot_id"] != boot_id):
        raise AssertionError("fingerprint-bound AgentRun did not close with its Backend root")

    adapter_terminal = gateway_request(
        "adapter", "GET",
        "/internal/runtime/sessions/" + runtime_session_id + "/terminal-evidence?"
        + urlencode({"root_run_id": root_id, "boot_id": boot_id}),
    )
    if adapter_terminal["status"] != 200 or not isinstance(adapter_terminal.get("body"), dict):
        raise AssertionError("Adapter did not retain exact terminal evidence")
    terminal_evidence = adapter_terminal["body"]
    if (set(terminal_evidence) != {
            "schema_version", "session_id", "boot_id", "root_run_id",
            "sequence", "outcome", "receipt",
    }
            or terminal_evidence.get("schema_version") != "byq-runtime-terminal-evidence.v1"
            or terminal_evidence.get("session_id") != runtime_session_id
            or terminal_evidence.get("boot_id") != boot_id
            or terminal_evidence.get("root_run_id") != root_id
            or terminal_evidence.get("sequence") != first_receipt["sequence"]
            or terminal_evidence.get("outcome") != "completed"
            or terminal_evidence.get("receipt") != first_receipt):
        raise AssertionError("Adapter terminal evidence differs from Backend's first receipt")

    if adapter_journal_ack(runtime_session_id, root_id) is not None:
        raise AssertionError("Adapter acknowledged a terminal before the lost response was retried")
    delivery_pending = lifecycle_status(cookie)
    if (delivery_pending.get("pending_events") != 1
            or delivery_pending.get("exhausted_events") != 0
            or delivery_pending.get("rejected_events") != 0
            or delivery_pending.get("state") != "pending"):
        raise AssertionError("Gateway did not retain the terminal event as pending")

    # Probe Adapter admission directly while its exact terminal receipt is
    # pending. This is an internal assertion only; it cannot start a new DSH
    # request because the durable cleanup barrier must reject it first.
    blocked = gateway_request(
        "adapter", "POST", f"/internal/runtime/sessions/{runtime_session_id}/prompt",
        {"content": "This prompt must be blocked by pending terminal cleanup.",
         "require_model_key": False},
    )
    if (blocked["status"] != 409
            or not isinstance(blocked.get("body"), dict)
            or blocked["body"].get("detail") != "previous turn domain cleanup is not yet acknowledged"):
        raise AssertionError("Adapter did not block the same-session prompt on pending cleanup")
    if roots(conversation_id) != terminal_rows or registered_agent_runs(root_id) != terminal_agent_runs:
        raise AssertionError("pending-cleanup prompt changed Backend root or AgentRun state")
    markers_before_allow = provider_markers()
    request_count_before_allow = sum(
        row.get("phase7_terminal_fixture") == "PROVIDER_REQUEST"
        for row in markers_before_allow
    )
    if request_count_before_allow != 2:
        raise AssertionError("pending-cleanup prompt triggered another provider request")
    if adapter_journal_ack(runtime_session_id, root_id) is not None:
        raise AssertionError("Adapter journal acquired an ACK before Gateway received the close reply")

    pre_allow_retry = wait_for(
        "proxy did not reject an exact close retry before host release",
        lambda: (
            observed if observed["pre_allow_rejections"] >= 1
            and observed["pre_allow_status"] == 503
            and observed["withheld_rejections"] == observed["pre_allow_rejections"]
            and observed["retry_forwarded"] == 0
            and observed["root_run_id"] == root_id
            and observed["first_receipt"] == first_receipt
            else None
        ) if (observed := proxy_observed()) else None,
    )
    if pre_allow_retry["retry_forwarded"] != 0:
        raise AssertionError("proxy forwarded a retry before host release")

    # Allow only the exact already-observed root. The next byte-identical
    # close reaches Backend and returns the same idempotent receipt.
    allowed = proxy_request("POST", "/_phase7/allow", {"root_run_id": root_id})
    if allowed["status"] != 200 or not isinstance(allowed.get("body"), dict):
        raise AssertionError("proxy did not accept the exact-root retry release")
    if allowed["body"].get("root_run_id") != root_id:
        raise AssertionError("proxy armed a retry for another root")

    def retry_complete() -> tuple[dict, dict, dict] | None:
        observed = proxy_observed()
        ack = adapter_journal_ack(runtime_session_id, root_id)
        delivery = lifecycle_status(cookie)
        if (observed["retry_forwarded"] == 1
                and observed["retry_status"] == 200
                and observed["retry_receipt"] == first_receipt
                and observed["first_receipt"] == first_receipt
                and observed["allow_count"] == 1
                and ack == first_receipt
                and delivery.get("pending_events") == 0
                and delivery.get("exhausted_events") == 0
                and delivery.get("rejected_events") == 0
                and delivery.get("state") == "up_to_date"):
            return observed, ack, delivery
        return None

    final_proxy, final_ack, final_delivery = wait_for(
        "Gateway did not retry and acknowledge the exact Backend terminal receipt",
        retry_complete, seconds=30,
    )
    final_roots = roots(conversation_id)
    final_agent_runs = registered_agent_runs(root_id)
    if final_roots != terminal_rows or final_agent_runs != terminal_agent_runs:
        raise AssertionError("idempotent terminal retry changed root or AgentRun state")
    if final_proxy["close_requests"] < 3 or final_proxy["first_forwarded"] != 1:
        raise AssertionError("expected one first close, a withheld retry and an allowed retry")
    if final_proxy["dropped_responses"] != 1 or final_proxy["retry_forwarded"] != 1:
        raise AssertionError("proxy did not drop only the first reply and forward one retry")
    if (final_proxy["pre_allow_rejections"] < 1
            or final_proxy["withheld_rejections"] != final_proxy["pre_allow_rejections"]
            or final_proxy["allow_count"] != 1):
        raise AssertionError("proxy did not withhold pre-release retries or observed duplicate release")
    if final_ack != first_receipt or final_delivery.get("state") != "up_to_date":
        raise AssertionError("Adapter ACK or Gateway lifecycle delivery differs from the first close")
    final_markers = provider_markers()
    final_provider_requests = sum(
        row.get("phase7_terminal_fixture") == "PROVIDER_REQUEST"
        for row in final_markers
    )
    if final_provider_requests != 2:
        raise AssertionError("lost-response retry created a duplicate provider call")
    if any(row.get("phase7_terminal_fixture") == "FINAL_ANSWER" for row in final_markers) is False:
        raise AssertionError("synthetic terminal answer marker is missing")
    for service in REQUIRED_SERVICES:
        if not inspect(service)["State"]["Running"]:
            raise AssertionError(f"{service} stopped during terminal close delivery")

    print(json.dumps({
        "result": "PASS",
        "project": args.project,
        "conversation_id": conversation_id,
        "root_id": root_id,
        "terminal_outcome": terminal_evidence["outcome"],
        "terminal_sequence": first_receipt["sequence"],
        "terminal_event_sha256": first_receipt["event_sha256"],
        "backend_retry_receipt_exact": True,
        "adapter_terminal_ack_exact": True,
        "pending_prompt_status": blocked["status"],
        "provider_requests": final_provider_requests,
        "gateway_close_requests": final_proxy["close_requests"],
        "backend_forwarded_close_requests": (
            final_proxy["first_forwarded"] + final_proxy["retry_forwarded"]
        ),
    }, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
