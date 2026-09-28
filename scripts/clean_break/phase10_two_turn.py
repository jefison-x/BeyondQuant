#!/usr/bin/env python3
"""Preflight or run the isolated pinned-DSH Phase 10 two-turn gate."""
from __future__ import annotations

import argparse
import hashlib
import http.cookies
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "scripts/clean_break/phase10_two_turn.compose.yml"
PROJECT_RE = re.compile(r"byq-p10-two-[0-9a-f]{10}")
DEV_IMAGE_PROJECT_RE = re.compile(r"byq-dev-[0-9a-f]{10}")
SERVICES = {"postgres", "backend", "mcp", "runtime-adapter", "gateway"}


def dev_image_project() -> str:
    return "byq-dev-" + hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:10]


def image_refs(project: str) -> dict[str, str]:
    if DEV_IMAGE_PROJECT_RE.fullmatch(project) is None:
        raise GateError("image project must be a worktree-scoped BYQ dev project")
    return {"postgres": "postgres:16-alpine", **{
        service: f"{project}-{service}:latest"
        for service in ("backend", "mcp", "runtime-adapter", "gateway")
    }}


IMAGES: dict[str, str] = {}
GATEWAY_PROBE = r'''import json,sys,urllib.error,urllib.request
method,path=sys.argv[1:3]; args=json.load(sys.stdin)
headers={"content-type":"application/json"}
if args.get("cookie"): headers["cookie"]=args["cookie"]
data=None if args.get("payload") is None else json.dumps(args["payload"]).encode()
try:
 with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8100"+path,data=data,headers=headers,method=method),timeout=15) as r:
  raw=r.read(); body=json.loads(raw) if raw else None
  print(json.dumps({"status":r.status,"body":body,"set_cookie":r.headers.get("Set-Cookie")}))
except urllib.error.HTTPError as e:
 raw=e.read()
 try: body=json.loads(raw) if raw else None
 except json.JSONDecodeError: body=None
 print(json.dumps({"status":e.code,"body":body}))
'''
OBSERVER_PROBE = r'''import json,sys,urllib.request
token=json.load(sys.stdin)["token"]
request=urllib.request.Request("http://127.0.0.1:8401/__phase10/evidence",headers={"authorization":"Bearer "+token})
with urllib.request.urlopen(request,timeout=5) as response: print(response.read().decode())
'''


class GateError(RuntimeError):
    pass


def run(command: list[str], *, stdin: str | None = None, timeout: int = 60) -> str:
    env = {**os.environ, "COMPOSE_DISABLE_ENV_FILE": "1", "COMPOSE_ENV_FILES": "/dev/null",
           "COMPOSE_PROFILES": "", "DOCKER_CLI_HINTS": "false"}
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, input=stdin, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=True, timeout=timeout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        code = getattr(exc, "returncode", None)
        suffix = f", exit {code}" if isinstance(code, int) else ""
        raise GateError(f"isolated Phase 10 {Path(command[0]).name} operation failed{suffix}") from None
    return result.stdout.strip()


def make_env(images: dict[str, str]) -> tuple[dict[str, str], Path]:
    values = {
        "BYQ_P10_POSTGRES_PASSWORD": secrets.token_hex(24),
        "BYQ_P10_RUNTIME_AUTHORITY_TOKEN": secrets.token_hex(32),
        "BYQ_P10_MCP_TOKEN": secrets.token_hex(32),
        "BYQ_P10_CREDENTIAL_RESOLVER_TOKEN": secrets.token_hex(32),
        "BYQ_P10_PLUGIN_DEPLOYMENT_TOKEN": secrets.token_hex(32),
        "BYQ_P10_PRODUCT_TOKEN": secrets.token_hex(32),
        "BYQ_P10_ADMIN_USERNAME": "p10_" + secrets.token_hex(8),
        "BYQ_P10_ADMIN_PASSWORD": secrets.token_hex(24),
        "BYQ_P10_NONCE": secrets.token_hex(12),
        "BYQ_P10_OBSERVER_TOKEN": secrets.token_hex(32),
        "BYQ_P10_BACKEND_IMAGE": images["backend"],
        "BYQ_P10_MCP_IMAGE": images["mcp"],
        "BYQ_P10_ADAPTER_IMAGE": images["runtime-adapter"],
        "BYQ_P10_GATEWAY_IMAGE": images["gateway"],
    }
    fd, raw_path = tempfile.mkstemp(prefix="byq-p10-two-", suffix=".env")
    path = Path(raw_path)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for key, value in values.items():
            pattern = r"[a-z0-9][a-z0-9_.-]*:latest" if key.endswith("_IMAGE") else r"[A-Za-z0-9_-]+"
            if re.fullmatch(pattern, value) is None:
                raise GateError("synthetic environment value is not safe for Compose")
            handle.write(f"{key}={value}\n")
    return values, path


def compose(project: str, env_file: Path) -> list[str]:
    return ["docker", "compose", "--env-file", str(env_file), "-p", project,
            "-f", str(COMPOSE_FILE)]


def validate_config(compose_args: list[str], project: str) -> dict[str, object]:
    config = json.loads(run(compose_args + ["config", "--format", "json"]))
    services = config.get("services", {})
    if config.get("name") != project or set(services) != SERVICES:
        raise GateError("resolved Compose project or service set differs from the isolated fixture")
    for name, expected in IMAGES.items():
        service = services[name]
        if (service.get("image") != expected or service.get("build")
                or service.get("ports") or service.get("restart") != "no"
                or service.get("pull_policy") != "never"):
            raise GateError(f"{name} must use its existing image, remain private, and run once")
        try:
            run(["docker", "image", "inspect", expected], timeout=15)
        except GateError as exc:
            raise GateError(f"local image for {name} is missing; run make dev-start DEV_PROFILE=core in the selected worktree") from exc
    if services["runtime-adapter"].get("command") != ["python3", "/probe/phase10_two_turn_probe.py"]:
        raise GateError("test-only PID-1 Adapter probe is not selected")
    for name in ("runtime-adapter", "gateway"):
        mounts = {Path(item.get("source", "")).resolve(): item
                  for item in services[name].get("volumes", []) if item.get("type") == "bind"}
        app = ROOT / ("services/runtime-adapter/app" if name == "runtime-adapter" else "services/gateway/app")
        expected = {
            app.resolve(): "/app/app",
            (ROOT / "packages/contracts").resolve(): "/app/packages/contracts",
            (ROOT / "packages/operations").resolve(): "/app/packages/operations",
        }
        for source, target in expected.items():
            mount = mounts.get(source)
            if mount is None or mount.get("target") != target or mount.get("read_only") is not True:
                raise GateError(f"{name} current source/package mounts must be read-only")
    probe = ROOT / "services/runtime-adapter/tests/phase10_two_turn_probe.py"
    probe_mounts = services["runtime-adapter"].get("volumes", [])
    if not any(item.get("type") == "bind" and Path(item.get("source", "")).resolve() == probe.resolve()
               and item.get("target") == "/probe/phase10_two_turn_probe.py"
               and item.get("read_only") is True for item in probe_mounts):
        raise GateError("the opt-in probe source must be mounted read-only")
    adapter_env = services["runtime-adapter"].get("environment", {})
    if adapter_env.get("BYQ_DSH_COMPATIBILITY_RELEASE") != "dsh-0.1.5rc1":
        raise GateError("the qualified DSH release pin differs")
    if config.get("networks", {}).get("byq_product", {}).get("internal") is not True:
        raise GateError("fixture network must be isolated from external networks")
    for resource in (*config.get("volumes", {}).values(), *config.get("networks", {}).values()):
        if resource.get("external") or not str(resource.get("name", "")).startswith(project + "_"):
            raise GateError("Compose contains an external or shared resource")
    return config


def resource_ids(project: str) -> dict[str, list[str]]:
    return {
        "containers": run(["docker", "container", "ls", "-aq", "--filter",
                           f"label=com.docker.compose.project={project}"]).splitlines(),
        "networks": run(["docker", "network", "ls", "-q", "--filter",
                         f"label=com.docker.compose.project={project}"]).splitlines(),
        "volumes": run(["docker", "volume", "ls", "-q", "--filter",
                        f"label=com.docker.compose.project={project}"]).splitlines(),
    }


def safe_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value) is None:
        raise GateError("Product API returned an invalid identifier")
    return value


def gateway(compose_args: list[str], method: str, path: str,
            payload: dict[str, object] | None = None, cookie: str | None = None) -> dict[str, object]:
    args = json.dumps({"payload": payload, "cookie": cookie}, separators=(",", ":"))
    output = run(compose_args + ["exec", "-T", "gateway", "python3", "-c", GATEWAY_PROBE,
                                 method, path], stdin=args)
    value = json.loads(output)
    if not isinstance(value, dict):
        raise GateError("Gateway returned malformed Product API response")
    return value


def product(compose_args: list[str], method: str, path: str,
            payload: dict[str, object] | None = None, cookie: str | None = None) -> dict[str, object]:
    result = gateway(compose_args, method, path, payload, cookie)
    if not 200 <= int(result.get("status", 0)) < 300 or not isinstance(result.get("body"), dict):
        raise GateError(f"Gateway Product API {method} {path} was rejected")
    return result["body"]


def observe(compose_args: list[str], token: str) -> dict[str, object]:
    output = run(compose_args + ["exec", "-T", "runtime-adapter", "python3", "-c", OBSERVER_PROBE],
                 stdin=json.dumps({"token": token}), timeout=10)
    body = json.loads(output)
    if not isinstance(body, dict):
        raise GateError("private Adapter observer returned malformed evidence")
    return body


def db(compose_args: list[str], sql: str) -> object:
    statement = "BEGIN READ ONLY; " + sql + "; COMMIT;"
    output = run(compose_args + ["exec", "-T", "postgres", "psql", "-X", "-qAt",
                                 "-U", "byq_app", "-d", "byq_domain", "-c", statement])
    return json.loads(output)


def roots(compose_args: list[str], runtime_session: str) -> list[dict[str, object]]:
    value = db(compose_args, "SELECT coalesce(json_agg(t ORDER BY t.created_at), '[]'::json) FROM ("
        "SELECT root_run_id,status,authority_status,terminal_sequence,terminal_event_sha256,created_at "
        "FROM agent_runtime_turns WHERE session_id='" + runtime_session + "') t")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise GateError("Backend returned malformed root lifecycle state")
    return value


def exact_ack(evidence: dict[str, object], runtime_session: str,
              root: dict[str, object]) -> dict[str, object] | None:
    acks = evidence.get("terminal_acks", [])
    for item in acks if isinstance(acks, list) else []:
        if not isinstance(item, dict) or item.get("session_id") != runtime_session or item.get("exact_ack") is not True:
            continue
        receipt = item.get("receipt")
        if (isinstance(receipt, dict) and receipt.get("schema_version") == "agent-run-lifecycle-receipt.v1"
                and receipt.get("root_run_id") == root.get("root_run_id")
                and receipt.get("sequence") == root.get("terminal_sequence")
                and receipt.get("event_sha256") == root.get("terminal_event_sha256")):
            return receipt
    return None


def wait_turn(compose_args: list[str], observer_token: str, cookie: str,
              conversation: str, runtime_session: str, answer: str, count: int):
    end = time.monotonic() + 90
    while time.monotonic() < end:
        session = product(compose_args, "GET", f"/v1/agent/sessions/{conversation}", cookie=cookie)
        evidence = observe(compose_args, observer_token)
        lifecycle = roots(compose_args, runtime_session)
        messages = session.get("messages", [])
        persisted = any(isinstance(item, dict) and item.get("role") == "assistant"
                        and item.get("content") == answer for item in messages) if isinstance(messages, list) else False
        if (persisted and len(lifecycle) == count
                and all(item.get("status") == "completed" and item.get("authority_status") == "closed"
                        and exact_ack(evidence, runtime_session, item) is not None for item in lifecycle)):
            return session, lifecycle, evidence
        time.sleep(0.5)
    raise GateError(f"Product turn {count} did not persist and receive its exact close ACK")


def verify_containers(compose_args: list[str], project: str) -> None:
    names = set(run(["docker", "container", "ls", "-a", "--filter",
                     f"label=com.docker.compose.project={project}", "--format", "{{.Names}}"]
                    ).splitlines())
    if names != {f"{project}-{name}-1" for name in SERVICES}:
        raise GateError("container inventory differs from the exact isolated Compose project")
    for service, image in IMAGES.items():
        item = json.loads(run(["docker", "inspect", f"{project}-{service}-1"]))[0]
        labels = item.get("Config", {}).get("Labels", {})
        if (labels.get("com.docker.compose.project") != project
                or labels.get("com.docker.compose.service") != service
                or item.get("Config", {}).get("Image") != image
                or item.get("HostConfig", {}).get("PortBindings") not in (None, {})
                or not item.get("State", {}).get("Running")):
            raise GateError(f"{service} is not running privately from its expected image")
    run(compose_args + ["exec", "-T", "runtime-adapter", "python3", "-c",
                        "from importlib.metadata import version; assert version('deepseek-harness-sdk') == '0.1.5rc1'; assert version('deepseek-harness-runtime-bin') == '0.1.5rc1'"])


def cleanup(compose_args: list[str], project: str) -> None:
    names = set(run(["docker", "container", "ls", "-a", "--filter",
                     f"label=com.docker.compose.project={project}", "--format", "{{.Names}}"]
                    ).splitlines())
    if not names.issubset({f"{project}-{name}-1" for name in SERVICES}):
        raise GateError("refusing cleanup: disposable project has an unknown container")
    for kind in ("network", "volume"):
        ids = run(["docker", kind, "ls", "-q", "--filter",
                   f"label=com.docker.compose.project={project}"]).splitlines()
        for resource_id in ids:
            item = json.loads(run(["docker", kind, "inspect", resource_id]))[0]
            if item.get("Labels", {}).get("com.docker.compose.project") != project:
                raise GateError("refusing cleanup: resource is not owned by the exact Compose project")
    if any(resource_ids(project).values()):
        run(compose_args + ["down", "--volumes", "--remove-orphans"], timeout=90)
    if any(resource_ids(project).values()):
        raise GateError("Phase 10 disposable resources remain after cleanup")


def run_gate(project: str, env_file: Path, values: dict[str, str]) -> dict[str, object]:
    args = compose(project, env_file)
    validate_config(args, project)
    if any(resource_ids(project).values()):
        raise GateError("random disposable project already has Docker resources")
    run(args + ["up", "-d", "--wait", "--wait-timeout", "180", *sorted(SERVICES)], timeout=240)
    verify_containers(args, project)
    login = gateway(args, "POST", "/api/product/auth/login", {
        "username": values["BYQ_P10_ADMIN_USERNAME"],
        "password": values["BYQ_P10_ADMIN_PASSWORD"],
    })
    if login.get("status") != 200 or not isinstance(login.get("set_cookie"), str):
        raise GateError("durable Product API login failed")
    parsed = http.cookies.SimpleCookie()
    parsed.load(str(login["set_cookie"]))
    session_cookie = parsed.get("byq_session")
    if session_cookie is None or not session_cookie.value:
        raise GateError("Product login did not issue a durable session cookie")
    cookie = "byq_session=" + session_cookie.value
    me = product(args, "GET", "/api/product/auth/me", cookie=cookie)
    if me.get("subject") != values["BYQ_P10_ADMIN_USERNAME"] or not isinstance(me.get("workspace"), dict):
        raise GateError("Product login did not resolve its synthetic durable user and workspace")
    created = product(args, "POST", "/v1/agent/sessions", payload={}, cookie=cookie)
    conversation = safe_id(created.get("session_id"))
    rowset = db(args, "SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT runtime_session_id "
                    "FROM product_conversations WHERE conversation_id='" + conversation + "') t")
    if not isinstance(rowset, list) or len(rowset) != 1 or not isinstance(rowset[0], dict):
        raise GateError("Product conversation was not durably created")
    runtime_session = safe_id(rowset[0].get("runtime_session_id"))
    nonce = values["BYQ_P10_NONCE"]
    first_prompt = "P10_FIRST_PUBLIC_PROMPT_" + nonce
    first_answer = "P10_COMPLETED_PUBLIC_ANSWER_" + nonce
    second_prompt = "P10_SECOND_CURRENT_PROMPT_" + nonce
    second_answer = "P10_SECOND_COMPLETED_" + nonce
    session_path = f"/v1/agent/sessions/{quote(conversation, safe='')}"
    product(args, "POST", session_path + "/turns", {"content": first_prompt}, cookie)
    session, first_roots, evidence = wait_turn(
        args, values["BYQ_P10_OBSERVER_TOKEN"], cookie, conversation,
        runtime_session, first_answer, 1)
    first_root = first_roots[0]
    if not any(isinstance(item, dict) and item.get("role") == "user"
               and item.get("content") == first_prompt for item in session.get("messages", [])):
        raise GateError("first Product prompt was not durably persisted")
    first_ack = exact_ack(evidence, runtime_session, first_root)
    if first_ack is None:
        raise GateError("first exact Backend terminal receipt was not ACKed")

    # The second ordinary Product turn is submitted only after the first
    # persisted answer, Backend close row and exact Adapter ACK were observed.
    product(args, "POST", session_path + "/turns", {"content": second_prompt}, cookie)
    second_session, lifecycle, evidence = wait_turn(
        args, values["BYQ_P10_OBSERVER_TOKEN"], cookie, conversation,
        runtime_session, second_answer, 2)
    if not any(isinstance(item, dict) and item.get("role") == "user"
               and item.get("content") == second_prompt for item in second_session.get("messages", [])):
        raise GateError("second Product prompt was not durably persisted")
    if len(lifecycle) != 2 or lifecycle[0].get("root_run_id") == lifecycle[1].get("root_run_id"):
        raise GateError("two Product turns did not create distinct Backend roots")
    if any(row.get("status") != "completed" or row.get("authority_status") != "closed"
           for row in lifecycle):
        raise GateError("a Backend root did not finish with closed authority")
    receipts = [exact_ack(evidence, runtime_session, row) for row in lifecycle]
    if any(receipt is None for receipt in receipts):
        raise GateError("a Backend root close is missing its exact Adapter ACK")
    root_ids = [row.get("root_run_id") for row in lifecycle]
    if any(not isinstance(root, str) or re.fullmatch(r"[0-9a-f]{32}", root) is None
           for root in root_ids):
        raise GateError("Backend returned an invalid runtime root identifier")
    runs_json = ",".join("'" + root + "'" for root in root_ids)
    registrations = db(args, "SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT root_run_id,role_id "
        "FROM agent_runs WHERE root_run_id IN (" + runs_json + ")) t")
    if (not isinstance(registrations, list) or len(registrations) != 2
            or {row.get("root_run_id") for row in registrations if isinstance(row, dict)} != set(root_ids)):
        raise GateError("Product MCP registration caused a missing or duplicate domain action")

    requests = evidence.get("provider_requests", [])
    if not isinstance(requests, list) or len(requests) != 4:
        raise GateError("pinned DSH did not make two scripted model calls for each root")
    grouped = {turn: [row for row in requests if isinstance(row, dict) and row.get("turn") == turn]
               for turn in ("first", "second")}
    for turn, rows in grouped.items():
        if (len(rows) != 2 or sum(row.get("initial") is True for row in rows) != 1
                or not all(row.get("exact_public_input") is True for row in rows)):
            safe = [{key: row.get(key) for key in (
                "initial", "exact_public_input", "user_message_count",
                "current_prompt_present", "first_answer_present", "user_text_length",
            )} for row in rows]
            raise GateError(f"{turn} DSH root did not receive the expected exact Product input: {safe}")
    second_initial = next(row for row in grouped["second"] if row.get("initial") is True)
    if (second_initial.get("prior_private_tool_absent") is not True
            or second_initial.get("no_recovery_or_failed_envelope") is not True
            or second_initial.get("other_registration_present") is True):
        raise GateError("second DSH root received private, recovery, failed or prior-action state")
    pids = {turn: {row.get("caller_pid") for row in rows} for turn, rows in grouped.items()}
    if (any(len(group) != 1 or None in group for group in pids.values())
            or next(iter(pids["first"])) == next(iter(pids["second"]))):
        raise GateError("the two turns did not use distinct observed native DSH process IDs")
    prepared = evidence.get("prepared_roots", [])
    bound = [row for row in prepared if isinstance(row, dict) and row.get("root_run_id") in set(root_ids)]
    if (len(bound) != 2 or {row.get("root_run_id") for row in bound} != set(root_ids)
            or len({row.get("native_session_id") for row in bound}) != 2
            or len({row.get("generation_id") for row in bound}) != 2):
        raise GateError("the two DSH roots did not use distinct native sessions and Adapter generations")
    return {
        "result": "PASS", "project": project, "conversation_id": conversation,
        "persisted_first_answer": True, "first_backend_close_ack_before_second_turn": True,
        "backend_roots": root_ids,
        "native_dsh_process_ids": [next(iter(pids[turn])) for turn in ("first", "second")],
        "bounded_public_input_exact": True,
        "prior_private_failed_recovery_context_absent": True,
        "registered_domain_actions": len(registrations), "pinned_images_rebuilt": False,
    }


def main() -> int:
    global IMAGES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"))
    parser.add_argument("--image-project", default=dev_image_project(),
                        help="worktree-scoped image project from a completed Phase 9 core build")
    args = parser.parse_args()
    IMAGES = image_refs(args.image_project)
    if not COMPOSE_FILE.is_file():
        raise GateError("Phase 10 Compose file is missing")
    values, env_file = make_env(IMAGES)
    try:
        project = "byq-p10-two-" + secrets.token_hex(5)
        if PROJECT_RE.fullmatch(project) is None:
            raise GateError("generated disposable project name is invalid")
        compose_args = compose(project, env_file)
        validate_config(compose_args, project)
        if args.command == "preflight":
            print(json.dumps({"result": "PREFLIGHT_PASS", "project": project,
                              "services": sorted(SERVICES), "images": IMAGES,
                              "stack_started": False}, sort_keys=True))
            return 0
        if any(resource_ids(project).values()):
            raise GateError("random disposable project already has Docker resources")
        try:
            result = run_gate(project, env_file, values)
        finally:
            if any(resource_ids(project).values()):
                cleanup(compose_args, project)
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    finally:
        env_file.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
