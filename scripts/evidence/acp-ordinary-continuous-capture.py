#!/usr/bin/env python3
"""One-off capture for an already browser-created ordinary two-turn ACP chat.

This tool never sends model prompts or creates business Jobs. Durable login
writes auth_sessions, and SSE reads may renew consumer leases. Run preflight
before the browser sends anything, capture-turn after each browser answer, then finish.
Credentials are read only from BYQ_E2E_ADMIN_USERNAME/PASSWORD and never saved.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "byq-dev-e8b02b5475"
WORKSPACE = "workspace_4c5b803209d549019b7804976f6930c6"
SESSION_ROOT = "/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp"
ORIGIN = "http://127.0.0.1:32784"
BATCH_SECONDS = 240
IO_TIMEOUT = 20
ROOT_RE = re.compile(r"[0-9a-f]{32}\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
PROJECTOR_SHA256 = "88703ff77934153095606ce81d3be1befc3b8eb79528e18e9c20074e1418ae36"
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}\Z")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
TERMINALS = {"session.result", "session.failed", "session.cancelled", "session.result.discarded"}


class Stop(RuntimeError):
    pass


def _session_project_key(cwd: str) -> str:
    """Match the pinned DSH session-store projectKey for this Linux cwd."""
    readable: list[str] = []
    separator = False
    for char in cwd:
        if char in "/\\:":
            if not separator:
                readable.append("-")
            separator = True
        elif char != "~" and char.isascii() and (char.isalnum() or char in "._-"):
            readable.append(char)
            separator = False
        else:
            code = ord(char)
            if code > 0xFFFF:
                raise Stop("native_cwd_non_bmp")
            readable.append(f"~{code:04X}")
            separator = False
    return "--" + ("".join(readable).lstrip("-") or "root")[:251] + "--"


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def _json_write(path: Path, value: object) -> None:
    _write(path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def _json_read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Stop("capture_input_invalid") from exc


def _request(opener, method: str, path: str, body: dict | None = None, *, timeout: int = 8,
             deadline: float | None = None):
    timeout = _remaining(deadline, timeout)
    data = None if body is None else json.dumps(body).encode()
    request = Request(ORIGIN + path, data=data, method=method,
                      headers={"accept": "application/json", "content-type": "application/json"})
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            _remaining(deadline, timeout)
            if len(raw) > 8 * 1024 * 1024:
                raise Stop("gateway_response_oversize")
            if "text/event-stream" in response.headers.get("content-type", ""):
                return response, raw
            try:
                return response.status, json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise Stop("gateway_response_invalid_json") from exc
    except HTTPError as exc:
        raise Stop(f"gateway_http_{exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise Stop(f"gateway_transport_{type(exc).__name__}") from None


def _login(*, deadline: float | None = None):
    username, password = os.environ.get("BYQ_E2E_ADMIN_USERNAME"), os.environ.get("BYQ_E2E_ADMIN_PASSWORD")
    if not username or not password:
        raise Stop("durable_login_credentials_missing")
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    status, body = _request(opener, "POST", "/api/auth/login", {"username": username, "password": password}, deadline=deadline)
    if status != 200 or not isinstance(body, dict) or not any(c.name == "byq_session" for c in jar):
        raise Stop("durable_login_rejected")
    status, identity = _request(opener, "GET", "/api/auth/me", deadline=deadline)
    workspace = identity.get("workspace") if isinstance(identity, dict) else None
    if (status != 200 or not isinstance(workspace, dict)
            or identity.get("subject") != username or workspace.get("workspace_id") != WORKSPACE):
        raise Stop("durable_identity_workspace_mismatch")
    # Never serialize cookie jar, credentials, display name, or user profile.
    return opener, {"subject": identity["subject"], "role": identity.get("role"),
                    "workspace_id": workspace["workspace_id"]}


def _remaining(deadline: float | None, timeout: int) -> int:
    if deadline is None:
        return timeout
    left = int(deadline - time.monotonic())
    if left < 1:
        raise Stop("stage_deadline_exceeded")
    return min(timeout, left)


def _boot_id() -> str:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise Stop("linux_boot_id_unavailable") from exc
    if not re.fullmatch(r"[0-9a-f-]{36}", value):
        raise Stop("linux_boot_id_invalid")
    return value


def _batch_deadline(out: Path) -> tuple[float, dict]:
    clock = _json_read(out / "batch-clock.json")
    if (not isinstance(clock, dict) or clock.get("schema_version") != "byq-ordinary-capture-clock.v1"
            or clock.get("boot_id") != _boot_id() or type(clock.get("deadline_monotonic_ns")) is not int):
        raise Stop("batch_clock_invalid_or_rebooted")
    deadline = clock["deadline_monotonic_ns"] / 1_000_000_000
    _remaining(deadline, IO_TIMEOUT)
    return deadline, clock


def _action_start(out: Path, action: str) -> float:
    if (out / "capture-stop.json").exists():
        raise Stop("batch_already_stopped")
    deadline, _clock = _batch_deadline(out)
    prior = {"turn-1": "preflight", "turn-2": "turn-1", "finish": "turn-2"}.get(action)
    if prior and not (out / f"checkpoint-{prior}-pass.json").is_file():
        raise Stop("previous_action_not_complete")
    _json_write(out / f"checkpoint-{action}-start.json", {
        "action": action, "started_monotonic_ns": time.monotonic_ns()})
    return deadline


def _checkpoint_pass(out: Path, action: str, *, deadline: float) -> None:
    _remaining(deadline, IO_TIMEOUT)
    _json_write(out / f"checkpoint-{action}-pass.json", {
        "action": action, "completed_monotonic_ns": time.monotonic_ns(), "status": "PASS"})
    _remaining(deadline, IO_TIMEOUT)


def _command(out: Path, label: str, argv: list[str], *, timeout: int = 20,
             input_bytes: bytes | None = None, deadline: float | None = None) -> bytes:
    timeout = _remaining(deadline, timeout)
    start = time.monotonic()
    try:
        proc = subprocess.run(argv, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        if isinstance(stdout, str): stdout = stdout.encode()
        if isinstance(stderr, str): stderr = stderr.encode()
        _write(out / "commands" / f"{label}.stdout.raw", stdout)
        _write(out / "commands" / f"{label}.stderr.raw", stderr)
        _json_write(out / "commands" / f"{label}.json", {
            "argv": argv, "returncode": None, "elapsed_ms": int((time.monotonic() - start) * 1000),
            "stdout_bytes": len(stdout), "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_bytes": len(stderr), "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "error": "TimeoutExpired", "timeout_seconds": timeout,
        })
        raise Stop(f"{label}_TimeoutExpired") from None
    except OSError as exc:
        _json_write(out / "commands" / f"{label}.json", {
            "argv": argv, "returncode": None, "elapsed_ms": int((time.monotonic() - start) * 1000),
            "stdout_bytes": 0, "stderr_bytes": 0, "error": type(exc).__name__,
            "timeout_seconds": timeout,
        })
        raise Stop(f"{label}_{type(exc).__name__}") from None
    stdout, stderr = proc.stdout, proc.stderr
    _write(out / "commands" / f"{label}.stdout.raw", stdout)
    _write(out / "commands" / f"{label}.stderr.raw", stderr)
    _json_write(out / "commands" / f"{label}.json", {
        "argv": argv, "returncode": proc.returncode,
        "elapsed_ms": int((time.monotonic() - start) * 1000),
        "stdout_bytes": len(stdout), "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_bytes": len(stderr), "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "timeout_seconds": timeout,
    })
    _remaining(deadline, timeout)
    if proc.returncode != 0 or stderr:
        # Retain the failed raw output, but never parse partial output.
        raise Stop(f"{label}_process_failed")
    return proc.stdout


def _owned_container(out: Path, label: str, container_id: str, service: str,
                     *, deadline: float | None = None) -> dict:
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise Stop("container_id_invalid")
    fmt = "{{.Id}}|{{.Image}}|{{.State.StartedAt}}|{{.State.Running}}|{{index .Config.Labels \"com.docker.compose.project\"}}|{{index .Config.Labels \"com.docker.compose.service\"}}"
    raw = _command(out, f"container-{label}", ["docker", "inspect", "--format", fmt, container_id], deadline=deadline)
    fields = raw.decode().strip().split("|")
    if len(fields) != 6:
        raise Stop("container_inspect_invalid")
    facts = dict(zip(("id", "image_id", "started_at", "running", "project", "service"), fields))
    if (facts["project"] != PROJECT or facts["service"] != service or facts["running"] != "true"
            or not facts["id"].startswith(container_id)):
        raise Stop(f"container_{label}_scope_mismatch")
    return facts


def _container_snapshot(args, out: Path, stage: str, *, deadline: float) -> dict:
    entries = (("gateway", args.gateway_id, "gateway"), ("adapter", args.adapter_id, "runtime-adapter"),
               ("runner", args.runner_id, "acp-product-runner"), ("postgres", args.postgres_id, "postgres"))
    facts = {name: _owned_container(out, f"{stage}-{name}", cid, service, deadline=deadline)
             for name, cid, service in entries}
    return {"project": PROJECT, "requested_ids": {name: cid for name, cid, _ in entries}, "containers": facts}


def _native_runtime_preflight(args, out: Path, *, deadline: float) -> None:
    source = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    projector = next((ast.literal_eval(node.value) for node in ast.walk(source)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "projector" for target in node.targets)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)), None)
    if not isinstance(projector, str) or hashlib.sha256(projector.encode()).hexdigest() != PROJECTOR_SHA256:
        raise Stop("native_projector_source_changed")
    code = r'''import ctypes,hashlib,json,os,pathlib,sys
root=pathlib.Path(sys.argv[1]); workspace=pathlib.Path(sys.argv[2]); expected=root/workspace.name
if os.geteuid()!=10002 or os.getegid()!=10002: raise SystemExit("native_reader_identity_mismatch")
if root!=pathlib.Path("/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp") or not workspace.is_dir() or workspace.resolve()!=expected.resolve(): raise SystemExit("native_mount_scope_invalid")
runtime=pathlib.Path("/opt/dsh-runtime"); profile=pathlib.Path("/opt/byq/profiles/byq-product.patch.yml"); identity=pathlib.Path("/opt/byq/profiles/byq-product.identity.json")
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
source_commit=(runtime/".byq-source-commit").read_text().strip()
store_manifest=json.loads((runtime/"packages/session/session-persistence-jsonl/package.json").read_text())
store_sha=digest(runtime/"packages/session/session-persistence-jsonl/lib/index.js")
schema_sha=digest(runtime/"packages/core/session/lib/index.js")
base_sha=digest(runtime/"packages/bundle/base/cordis.patch.yml")
profile_sha=digest(profile); identity_sha=digest(identity); profile_identity=json.loads(identity.read_text())
if (source_commit!="639ed015397290b3745d163aafe02ffee4aa3f84" or store_manifest.get("version")!="0.2.0-rc.2"
 or store_sha!="0845707017acc2b4a8a75eab2244fa3fd88587b8094ab32014321dce7ca1e31b"
 or schema_sha!="87ea85e2fb5318bf1f826db9a1c88c1b26d3ea328027a7f32b211880c4d62b9d"
 or base_sha!="9c2be64f46a193eff3cca190c26e697e8e8eee25c9b40149dfdb56f8142c252d"
 or profile_sha!="10396c708651b24e3012df51e13cbb0e1eaf8178cda9547c91d682c189eacd45"
 or identity_sha!="0e1f5494f99b4fba433f5f86653b6848377372c7308561bceaaddc3ea3f2f69b"
 or profile_identity.get("profile")!="byq-product-acp-0.2.0-rc.2"
 or profile_identity.get("composition_hash")!="sha256:"+profile_sha): raise SystemExit("native_source_identity_mismatch")
lib=ctypes.CDLL("libzstd.so.1")
if not all(hasattr(lib,n) for n in ("ZSTD_createDStream","ZSTD_initDStream","ZSTD_decompressStream","ZSTD_isError")): raise SystemExit("native_zstd_stream_unavailable")
print(json.dumps({"schema_version":"byq-native-projector-preflight.v1","workspace_mount":str(workspace),"zstd_stream_api":True,"reader_uid":os.geteuid(),"reader_gid":os.getegid(),"dsh_source_commit":source_commit,"store_package_version":store_manifest["version"],"store_source_sha256":store_sha,"header_schema_source_sha256":schema_sha,"base_profile_source_sha256":base_sha,"product_profile_sha256":profile_sha,"product_profile_identity_sha256":identity_sha,"product_profile":profile_identity["profile"],"product_composition_hash":profile_identity["composition_hash"],"dsh_home_contract":"binding.cwd","store_root_contract":"dshHomePath(sessions)"},separators=(",",":")))'''
    raw = _command(out, "native-runtime-preflight", ["docker", "exec", "--user", "10002:10002", "--workdir", "/app",
        args.runner_id, "python3", "-I", "-c", code, args.session_root,
        str(Path(args.session_root) / WORKSPACE)], timeout=15, deadline=deadline)
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get("schema_version") != "byq-native-projector-preflight.v1"
            or value.get("workspace_mount") != str(Path(args.session_root) / WORKSPACE)
            or value.get("reader_uid") != 10002 or value.get("reader_gid") != 10002
            or value.get("dsh_source_commit") != "639ed015397290b3745d163aafe02ffee4aa3f84"
            or value.get("store_package_version") != "0.2.0-rc.2"
            or value.get("store_source_sha256") != "0845707017acc2b4a8a75eab2244fa3fd88587b8094ab32014321dce7ca1e31b"
            or value.get("header_schema_source_sha256") != "87ea85e2fb5318bf1f826db9a1c88c1b26d3ea328027a7f32b211880c4d62b9d"
            or value.get("base_profile_source_sha256") != "9c2be64f46a193eff3cca190c26e697e8e8eee25c9b40149dfdb56f8142c252d"
            or value.get("product_profile_sha256") != "10396c708651b24e3012df51e13cbb0e1eaf8178cda9547c91d682c189eacd45"
            or value.get("product_profile_identity_sha256") != "0e1f5494f99b4fba433f5f86653b6848377372c7308561bceaaddc3ea3f2f69b"
            or value.get("product_profile") != "byq-product-acp-0.2.0-rc.2"
            or value.get("product_composition_hash") != "sha256:10396c708651b24e3012df51e13cbb0e1eaf8178cda9547c91d682c189eacd45"
            or value.get("dsh_home_contract") != "binding.cwd"
            or value.get("store_root_contract") != "dshHomePath(sessions)"
            or value.get("zstd_stream_api") is not True):
        raise Stop("native_runtime_preflight_invalid")
    command_record = _json_read(out / "commands" / "native-runtime-preflight.json")
    if (not isinstance(command_record, dict) or command_record.get("returncode") != 0
            or not isinstance(command_record.get("argv"), list)
            or not isinstance(command_record.get("stdout_sha256"), str)):
        raise Stop("native_runtime_preflight_command_receipt_invalid")
    value["source_read_command_sha256"] = hashlib.sha256(json.dumps(
        command_record["argv"], separators=(",", ":")).encode()).hexdigest()
    value["source_read_returncode"] = command_record["returncode"]
    value["source_read_stdout_sha256"] = command_record["stdout_sha256"]
    value["source_read_command_receipt_sha256"] = hashlib.sha256(json.dumps(
        command_record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _json_write(out / "native-runtime-preflight.json", value)


def _verify_container_snapshot(args, out: Path, stage: str, *, deadline: float) -> None:
    baseline = _json_read(out / "container-facts-preflight.json")
    requested = {"gateway": args.gateway_id, "adapter": args.adapter_id,
                 "runner": args.runner_id, "postgres": args.postgres_id}
    if not isinstance(baseline, dict) or baseline.get("requested_ids") != requested:
        raise Stop("container_arguments_changed")
    current = _container_snapshot(args, out, stage, deadline=deadline)
    _json_write(out / f"container-facts-{stage}.json", current)
    if current != baseline:
        raise Stop("container_identity_or_start_changed")


def _pg(out: Path, pg_id: str, label: str, sql: str, *, deadline: float | None = None) -> object:
    argv = ["docker", "exec", "-i", pg_id, "sh", "-c",
            'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"',
            "capture", sql]
    raw = _command(out, label, argv, timeout=20, deadline=deadline)
    try:
        return json.loads(raw.decode().strip())
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Stop(f"{label}_invalid_json") from exc


def _job_counts_sql() -> str:
    # Fixed, source-reviewed table set. Authentication sessions are deliberately
    # excluded: durable Gateway login creates them during this observation.
    tables = ("backtest_jobs", "data_sync_jobs", "factor_jobs", "market_session_sync_jobs",
              "ml_prediction_runs", "ml_training_runs", "optimization_jobs",
              "security_master_sync_jobs", "signal_producer_jobs", "research_tasks", "artifacts")
    fields = ",".join(f"'{name}',(SELECT count(*) FROM {name})" for name in tables)
    return f"BEGIN READ ONLY; SELECT json_build_object({fields})::text; COMMIT;"


def _runtime_scope_sql(conversation_id: str, owner: str, workspace: str,
                       created_after: str, expected_user_messages: int) -> str:
    if not ID_RE.fullmatch(conversation_id) or not OWNER_RE.fullmatch(owner) or not ID_RE.fullmatch(workspace):
        raise Stop("conversation_scope_invalid")
    quote = lambda x: "'" + x.replace("'", "''") + "'"
    if expected_user_messages not in (1, 2):
        raise Stop("conversation_turn_count_invalid")
    return f"""BEGIN READ ONLY; SELECT json_build_object(
'conversation_id',c.conversation_id,'runtime_session_id',c.runtime_session_id,
'trace_id',c.trace_id,'owner_principal',c.owner_principal,'workspace_id',w.workspace_id,
'created_at',c.created_at,'status',c.status,
'user_message_count',(SELECT count(*) FROM product_conversation_messages pm
 WHERE pm.conversation_id=c.conversation_id AND pm.owner_principal=c.owner_principal AND pm.role='user'))::text
FROM product_conversations c JOIN users u ON u.username=c.owner_principal
JOIN workspaces w ON w.owner_user_id=u.user_id
JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
WHERE c.conversation_id={quote(conversation_id)} AND c.owner_principal={quote(owner)}
AND c.created_at >= {quote(created_after)}::timestamptz
AND c.status='active' AND u.status='active' AND w.kind='personal' AND w.status='active'
AND w.workspace_id={quote(workspace)} AND m.role='owner' AND m.status='active'
AND (SELECT count(*) FROM product_conversation_messages pm
 WHERE pm.conversation_id=c.conversation_id AND pm.owner_principal=c.owner_principal AND pm.role='user')={expected_user_messages}; COMMIT;"""


def _roots_sql(scope: dict, created_after: str) -> str:
    quote = lambda x: "'" + x.replace("'", "''") + "'"
    return f"""BEGIN READ ONLY; SELECT json_build_object('schema_version','byq-business-root-status.v1','roots',COALESCE(json_agg(json_build_object('root_run_id',root_run_id,'status',status,'authority_status',authority_status,'terminal_sequence',terminal_sequence,'terminal_event_sha256',terminal_event_sha256,'terminal_acp_ingress_sequence',terminal_acp_ingress_sequence,'terminal_acp_ingress_sha256',terminal_acp_ingress_sha256,'terminal_unknown_claim_count',terminal_unknown_claim_count,'terminal_unknown_claims_sha256',terminal_unknown_claims_sha256) ORDER BY root_run_id),'[]'::json))::text FROM agent_runtime_turns WHERE owner_principal={quote(scope['owner_principal'])} AND workspace_id={quote(scope['workspace_id'])} AND session_id={quote(scope['runtime_session_id'])} AND trace_id={quote(scope['trace_id'])} AND created_at >= {quote(created_after)}::timestamptz; COMMIT;"""


def _sse_events(opener, conversation_id: str, after: int, terminal_index: int,
                *, deadline: float) -> list[dict]:
    if not ID_RE.fullmatch(conversation_id):
        raise Stop("conversation_id_invalid")
    path = f"/v1/workflows/{conversation_id}/events"
    request = Request(ORIGIN + path, headers={"accept": "text/event-stream", "Last-Event-ID": str(after)})
    try:
        response = opener.open(request, timeout=_remaining(deadline, BATCH_SECONDS))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise Stop(f"workflow_sse_{type(exc).__name__}") from None
    events, data, kind = [], [], None
    terminals = 0
    try:
        while time.monotonic() < deadline:
            line = response.readline()
            _remaining(deadline, IO_TIMEOUT)
            if not line:
                break
            text = line.decode("utf-8", "strict").rstrip("\r\n")
            if text.startswith("event:"):
                kind = text[6:].strip()
            elif text.startswith("data:"):
                data.append(text[5:].lstrip())
            elif text == "":
                if kind == "workflow-trace" and data:
                    row = json.loads("\n".join(data))
                    if not isinstance(row, dict):
                        raise Stop("workflow_event_invalid")
                    events.append(row)
                    if row.get("kind") in TERMINALS:
                        terminals += 1
                        if terminals == terminal_index:
                            return events
                data, kind = [], None
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Stop("workflow_event_invalid") from exc
    finally:
        response.close()
    raise Stop("workflow_terminal_not_observed")


def _filter_gateway_ack_lines(stdout: bytes, stderr: bytes) -> tuple[list[dict], list[dict], bool]:
    found, found_lines, parse_error = [], [], False
    for line in (stdout + b"\n" + stderr).decode("utf-8", "replace").splitlines():
        marker = "terminal_ack_observed "
        pos = line.find(marker)
        if pos < 0:
            continue
        try:
            row = json.loads(line[pos + len(marker):])
        except json.JSONDecodeError:
            parse_error = True
            continue
        if isinstance(row, dict) and row.get("schema_version") == "byq-gateway-terminal-ack-observed.v1":
            ack_keys = {"schema_version", "event", "root_run_id", "session_id", "boot_id",
                        "trace_id", "sequence", "event_sha256", "outcome"}
            if set(row) != ack_keys:
                parse_error = True
                continue
            found.append(row)
            matched_line = line[pos:]
            encoded = matched_line.encode("utf-8")
            found_lines.append({"line_bytes": len(encoded), "line_sha256": hashlib.sha256(encoded).hexdigest(),
                                "matched_line": matched_line})
    return found, found_lines, parse_error


def _gateway_ack_events(out: Path, gateway_id: str, since: str, expected: list[dict],
                        *, deadline: float) -> list[dict]:
    log_type = _command(out, "gateway-log-type", ["docker", "inspect", "--format",
        "{{.HostConfig.LogConfig.Type}}", gateway_id], deadline=deadline).decode().strip()
    if log_type != "json-file":
        raise Stop("gateway_log_driver_unexpected")
    argv = ["docker", "logs", "--since", since, "--timestamps", gateway_id]
    start = time.monotonic()
    timeout = _remaining(deadline, 20)
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        if isinstance(stdout, str): stdout = stdout.encode()
        if isinstance(stderr, str): stderr = stderr.encode()
        partial_rows, partial_lines, parse_error = _filter_gateway_ack_lines(stdout, stderr)
        _json_write(out / "commands/gateway-terminal-ack-log.json", {
            "argv": argv, "returncode": None, "elapsed_ms": int((time.monotonic()-start)*1000),
            "stdout_bytes": len(stdout), "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_bytes": len(stderr), "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "error": "TimeoutExpired", "timeout_seconds": timeout, "parse_error": parse_error,
            "filtered_tuple_count": len(partial_rows)})
        _json_write(out / "gateway-ack-filtered.json", {"status": "STOP", "events": partial_rows})
        _json_write(out / "gateway-ack-original-matches.json", {
            "schema_version": "byq-gateway-terminal-ack-lines.v1", "lines": partial_lines})
        raise Stop("gateway_ack_log_read_failed") from None
    except OSError as exc:
        _json_write(out / "commands/gateway-terminal-ack-log.json", {
            "argv": argv, "returncode": None, "elapsed_ms": int((time.monotonic()-start)*1000),
            "stdout_bytes": 0, "stderr_bytes": 0, "error": type(exc).__name__, "timeout_seconds": timeout})
        _json_write(out / "gateway-ack-filtered.json", {"status": "STOP", "events": []})
        raise Stop("gateway_ack_log_read_failed") from None
    meta = {"argv": argv, "returncode": proc.returncode,
            "elapsed_ms": int((time.monotonic()-start)*1000),
            "stdout_bytes": len(proc.stdout), "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(),
            "stderr_bytes": len(proc.stderr), "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest(),
            "timeout_seconds": timeout}
    if proc.returncode != 0:
        _json_write(out / "commands/gateway-terminal-ack-log.json", meta)
        _json_write(out / "gateway-ack-filtered.json", {"status": "STOP", "events": []})
        raise Stop("gateway_ack_log_read_failed")
    # uvicorn INFO logging writes to stderr in some valid deployments. Parse
    # both channels in memory, save only allowlisted exact ACK tuples.
    raw = proc.stdout + b"\n" + proc.stderr
    found, found_lines, parse_error = _filter_gateway_ack_lines(proc.stdout, proc.stderr)
    meta["filtered_tuple_count"] = len(found)
    meta["filtered_tuple_count"] = len(found)
    meta["parse_error"] = parse_error
    _json_write(out / "commands/gateway-terminal-ack-log.json", meta)
    _json_write(out / "gateway-ack-filtered.json", {"status": "PARSED", "events": found})
    _json_write(out / "gateway-ack-original-matches.json", {
        "schema_version": "byq-gateway-terminal-ack-lines.v1", "lines": found_lines})
    _remaining(deadline, timeout)
    if parse_error:
        raise Stop("gateway_ack_log_invalid")
    for want in expected:
        matches = [item for item in found if item.get("root_run_id") == want["root_run_id"]]
        if not matches or any(item != want for item in matches):
            raise Stop("gateway_ack_missing_or_conflicting")
    return found


def _binding_and_journal(out: Path, adapter_id: str, session_root: str, workspace: str,
                         runtime_session: str, root_id: str, *, deadline: float) -> tuple[dict, bytes]:
    if not all(ID_RE.fullmatch(x) for x in (workspace, runtime_session)) or not ROOT_RE.fullmatch(root_id):
        raise Stop("adapter_artifact_scope_invalid")
    base = Path(session_root) / workspace
    binding = base / "byq-acp-bindings" / f"{runtime_session}.json"
    py = r'''import json, pathlib, sys
b=pathlib.Path(sys.argv[1]); r=pathlib.Path(sys.argv[2]);
v=json.loads(b.read_text()); p=pathlib.Path(v["cwd"])/("product-turn-provider-request-"+sys.argv[3]+".jsonl")
print(json.dumps({"binding":v,"journal":p.read_text()},separators=(",",":")))'''
    raw = _command(out, f"adapter-binding-{root_id}",
                   ["docker", "exec", "--workdir", "/app", "-i", adapter_id, "python3", "-I", "-c", py,
                   str(binding), str(base), root_id], deadline=deadline)
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("binding"), dict) or not isinstance(value.get("journal"), str):
        raise Stop("adapter_artifact_invalid")
    return value["binding"], value["journal"].encode()


def _capture_turn(args, opener, identity, *, deadline: float) -> None:
    out = args.out_dir.resolve()
    if not out.is_dir() or (out.stat().st_mode & 0o077):
        raise Stop("capture_directory_permissions_invalid")
    if args.turn not in (1, 2) or not ID_RE.fullmatch(args.conversation_id):
        raise Stop("turn_scope_invalid")
    session_path = f"/v1/agent/sessions/{args.conversation_id}"
    status, conversation = _request(opener, "GET", session_path, deadline=deadline)
    if status != 200 or not isinstance(conversation, dict):
        raise Stop("conversation_read_failed")
    public = conversation.get("conversation")
    if not isinstance(public, dict) or public.get("session_id") != args.conversation_id:
        raise Stop("conversation_identity_mismatch")
    trace_id = public.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id:
        raise Stop("conversation_trace_scope_missing")
    clock = _json_read(out / "batch-clock.json")
    runtime_scope = _pg(out, args.postgres_id, f"conversation-scope-turn-{args.turn}",
        _runtime_scope_sql(args.conversation_id, identity["subject"], identity["workspace_id"],
                           clock["started_utc"], args.turn), deadline=deadline)
    if (not isinstance(runtime_scope, dict)
            or runtime_scope.get("conversation_id") != args.conversation_id
            or runtime_scope.get("owner_principal") != identity["subject"]
            or runtime_scope.get("workspace_id") != identity["workspace_id"]
            or runtime_scope.get("trace_id") != trace_id
            or runtime_scope.get("status") != "active"
            or runtime_scope.get("user_message_count") != args.turn
            or not isinstance(runtime_scope.get("runtime_session_id"), str)):
        raise Stop("conversation_backend_scope_mismatch")
    runtime_session = runtime_scope["runtime_session_id"]
    scope_path = out / "scope.json"
    if args.turn == 1:
        if scope_path.exists():
            raise Stop("scope_already_captured")
        scope = {"conversation_id": args.conversation_id, "runtime_session_id": runtime_session,
                 "trace_id": trace_id, "workspace_id": identity["workspace_id"],
                 "owner_principal": identity["subject"], "actor_principal": identity["subject"]}
        _json_write(scope_path, scope)
        after = 0
    else:
        scope = _json_read(scope_path)
        if (not isinstance(scope, dict) or scope.get("conversation_id") != args.conversation_id
                or scope.get("runtime_session_id") != runtime_session or scope.get("trace_id") != trace_id
                or scope.get("owner_principal") != identity["subject"]
                or scope.get("actor_principal") != identity["subject"]
                or scope.get("workspace_id") != identity["workspace_id"]):
            raise Stop("scope_identity_changed")
        old_trace = _json_read(out / "turn-1" / "trace.json")
        if not isinstance(old_trace, list):
            raise Stop("prior_trace_missing")
        after = max((row.get("sequence", 0) for row in old_trace if isinstance(row, dict)), default=0)
    since = clock["started_utc"]
    events = _sse_events(opener, args.conversation_id, after, 1, deadline=deadline)
    if not events or any(e.get("session_id") != args.conversation_id or e.get("trace_id") != trace_id for e in events):
        raise Stop("workflow_event_scope_mismatch")
    starts = [e for e in events if e.get("kind") == "session.started"]
    terms = [e for e in events if e.get("kind") in TERMINALS]
    if len(starts) != 1 or len(terms) != 1:
        raise Stop("workflow_root_count_mismatch")
    root_id = starts[0].get("payload", {}).get("run_id")
    if not isinstance(root_id, str) or not ROOT_RE.fullmatch(root_id) or terms[0].get("payload", {}).get("run_id") != root_id:
        raise Stop("workflow_root_identity_mismatch")
    delivery_status, delivery = _request(opener, "GET", f"/v1/agent/sessions/{args.conversation_id}/answer-delivery", deadline=deadline)
    if (delivery_status != 200 or not isinstance(delivery, dict)
            or delivery.get("schema_version") != "public-answer-delivery-status.v1"
            or delivery.get("state") != "up_to_date"
            or any(type(delivery.get(k)) is not int or delivery[k] != 0
                   for k in ("pending_events", "exhausted_events", "rejected_events"))):
        raise Stop("answer_delivery_read_failed")
    # Re-read the durable Product projection after delivery reaches up_to_date.
    final_status, final_conversation = _request(opener, "GET", session_path, deadline=deadline)
    final_public = final_conversation.get("conversation") if isinstance(final_conversation, dict) else None
    messages = final_conversation.get("messages") if isinstance(final_conversation, dict) else None
    if (final_status != 200 or not isinstance(final_public, dict)
            or final_public.get("session_id") != args.conversation_id
            or final_public.get("trace_id") != trace_id or not isinstance(messages, list)
            or sum(1 for row in messages if isinstance(row, dict) and row.get("role") == "user") != args.turn):
        raise Stop("durable_conversation_projection_mismatch")
    turn_dir = out / f"turn-{args.turn}"
    turn_dir.mkdir(mode=0o700)
    binding, journal = _binding_and_journal(out, args.adapter_id, args.session_root,
                                            identity["workspace_id"], runtime_session, root_id,
                                            deadline=deadline)
    if (binding.get("schema_version") != "byq-acp-root-binding.v1"
            or binding.get("session_id") != runtime_session
            or binding.get("trace_id") != trace_id
            or binding.get("owner_principal") != identity["subject"]
            or binding.get("workspace_id") != identity["workspace_id"]
            or binding.get("root_run_id") != root_id
            or not isinstance(binding.get("native_session_id"), str)
            or not isinstance(binding.get("runtime_generation"), str)
            or not isinstance(binding.get("previous_boot_id"), str)):
        raise Stop("binding_scope_or_generation_mismatch")
    all_events = events
    if args.turn == 2:
        first_events = _json_read(out / "turn-1" / "trace.json")
        if not isinstance(first_events, list):
            raise Stop("prior_trace_missing")
        all_events = first_events + events
        seqs = [e.get("sequence") for e in all_events if isinstance(e, dict)]
        if len(seqs) != len(set(seqs)):
            raise Stop("workflow_event_duplicate_sequence")
        roots = [e.get("payload", {}).get("run_id") for e in all_events if e.get("kind") == "session.started"]
        if len(roots) != 2 or len(set(roots)) != 2:
            raise Stop("two_root_trace_required")
        terminal = _pg(out, args.postgres_id, "backend-roots", _roots_sql(scope, clock["started_utc"]), deadline=deadline)
        terminal_rows = terminal.get("roots") if isinstance(terminal, dict) else None
        if (not isinstance(terminal_rows, list) or len(terminal_rows) != 2
                or {r.get("root_run_id") for r in terminal_rows if isinstance(r, dict)} != set(roots)
                or any(not isinstance(r, dict) or r.get("status") != "completed"
                       or r.get("authority_status") != "closed"
                       or r.get("terminal_unknown_claim_count") != 0 for r in terminal_rows)):
            raise Stop("backend_roots_not_exact_two_closed")
        ack_expected = []
        for root in roots:
            snap = _json_read(out / "turn-1" / "binding.json") if root == _root_for_turn(out, 1) else binding
            receipt = snap.get("settlement_receipt") if isinstance(snap, dict) else None
            if not isinstance(receipt, dict):
                raise Stop("persisted_settlement_missing")
            ack_expected.append({"schema_version": "byq-gateway-terminal-ack-observed.v1",
                "event": "terminal_ack_observed", "root_run_id": root, "session_id": runtime_session,
                "boot_id": snap.get("previous_boot_id"), "trace_id": trace_id,
                "sequence": receipt.get("sequence"), "event_sha256": receipt.get("event_sha256"),
                "outcome": "completed"})
        observed = _gateway_ack_events(out, args.gateway_id, since, ack_expected, deadline=deadline)
        _json_write(out / "gateway-ack-observed.json", {
            "schema_version": "byq-gateway-terminal-ack-observed-set.v1", "events": observed,
        })
        _native_projection(args, out, binding, identity["workspace_id"], runtime_session, deadline=deadline)
        _json_write(out / "terminal.json", terminal)
        _json_write(out / "trace.json", all_events)
        _json_write(out / "conversation.json", final_conversation)
    _json_write(turn_dir / "trace.json", events)
    _json_write(out / f"conversation-turn-{args.turn}.json", final_conversation)
    _json_write(out / f"delivery-turn-{args.turn}.json", delivery)
    _json_write(turn_dir / "binding.json", binding)
    _write(turn_dir / f"product-turn-provider-request-{root_id}.jsonl", journal)
    snapshots = out / "binding-snapshots"
    snapshots.mkdir(mode=0o700, exist_ok=True)
    _json_write(snapshots / f"{root_id}.json", binding)
    journals = out / "journals"
    journals.mkdir(mode=0o700, exist_ok=True)
    _write(journals / f"product-turn-provider-request-{root_id}.jsonl", journal)


def _root_for_turn(out: Path, turn: int) -> str:
    binding = _json_read(out / f"turn-{turn}" / "binding.json")
    root = binding.get("root_run_id") if isinstance(binding, dict) else None
    if not isinstance(root, str) or not ROOT_RE.fullmatch(root):
        raise Stop("binding_root_invalid")
    return root


def _native_projection(args, out: Path, binding: dict, workspace: str, runtime_session: str,
                       *, deadline: float) -> None:
    native_id = binding.get("native_session_id")
    cwd = binding.get("cwd")
    if not isinstance(native_id, str) or not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise Stop("native_projection_scope_missing")
    # The runner emits only header identity, compressed digest/size and hashes of
    # exactly the two human input messages. The source is pinned by SHA below.
    projector = r'''import ctypes,hashlib,json,os,pathlib,stat,sys
root=pathlib.Path(sys.argv[1]); expected=sys.argv[2]; workspace=sys.argv[3]; producer=sys.argv[4]
if not root.is_absolute() or root.resolve()!=root: raise SystemExit("native_cwd_not_canonical")
def project_key(cwd):
 readable=[]; separator=False
 for ch in cwd:
  if ch in "/\\:":
   if not separator: readable.append("-")
   separator=True
  elif ch != "~" and (ch.isascii() and (ch.isalnum() or ch in "._-")):
   readable.append(ch); separator=False
  else:
   code=ord(ch)
   if code>0xffff: raise SystemExit("native_cwd_non_bmp")
   readable.append("~"+format(code,"04X")); separator=False
 return "--"+("".join(readable).lstrip("-") or "root")[:251]+"--"
class IB(ctypes.Structure): _fields_=[("src",ctypes.c_void_p),("size",ctypes.c_size_t),("pos",ctypes.c_size_t)]
class OB(ctypes.Structure): _fields_=[("dst",ctypes.c_void_p),("size",ctypes.c_size_t),("pos",ctypes.c_size_t)]
lib=ctypes.CDLL("libzstd.so.1")
lib.ZSTD_createDStream.restype=ctypes.c_void_p; lib.ZSTD_initDStream.argtypes=[ctypes.c_void_p]; lib.ZSTD_initDStream.restype=ctypes.c_size_t
lib.ZSTD_decompressStream.argtypes=[ctypes.c_void_p,ctypes.POINTER(OB),ctypes.POINTER(IB)]; lib.ZSTD_decompressStream.restype=ctypes.c_size_t
lib.ZSTD_isError.argtypes=[ctypes.c_size_t]; lib.ZSTD_isError.restype=ctypes.c_uint
lib.ZSTD_freeDStream.argtypes=[ctypes.c_void_p];
def stamp(st): return (st.st_dev,st.st_ino,st.st_mode,st.st_nlink,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
def decode(path, full):
 parent=root
 for part in ("sessions",project_key(str(root)),expected):
  parent=parent/part
  st=os.lstat(parent)
  if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode): raise SystemExit("native_parent_invalid")
 before=os.lstat(path)
 if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_nlink!=1 or before.st_size<=0 or before.st_size>67108864: raise SystemExit("native_file_invalid")
 fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); st=os.fstat(fd)
 if stamp(st)!=stamp(before): os.close(fd); raise SystemExit("native_file_changed")
 stream=lib.ZSTD_createDStream(); digest=hashlib.sha256(); size=0; pending=bytearray(); header=None; users=[]; records=0; decompressed=0; need_init=True; opened_after=None
 try:
  while True:
   chunk=os.read(fd,65536)
   if not chunk: break
   digest.update(chunk); size+=len(chunk); src=ctypes.create_string_buffer(chunk); ib=IB(ctypes.cast(src,ctypes.c_void_p),len(chunk),0)
   while ib.pos<ib.size:
    if need_init:
     r=lib.ZSTD_initDStream(stream)
     if lib.ZSTD_isError(r): raise SystemExit("native_zstd_init")
     need_init=False
    output=ctypes.create_string_buffer(65536); ob=OB(ctypes.cast(output,ctypes.c_void_p),65536,0)
    r=lib.ZSTD_decompressStream(stream,ctypes.byref(ob),ctypes.byref(ib))
    if lib.ZSTD_isError(r): raise SystemExit("native_decompress")
    if ob.pos:
     decompressed+=ob.pos
     if decompressed>67108864: raise SystemExit("native_decompressed_oversize")
     pending.extend(output.raw[:ob.pos])
     if len(pending)>8388608 and b"\n" not in pending: raise SystemExit("native_record_oversize")
     while b"\n" in pending:
      line,_,rest=pending.partition(b"\n"); pending=bytearray(rest)
      if line:
       records+=1
       if records>100000: raise SystemExit("native_record_count_oversize")
       row=json.loads(line)
       if records==1:
        header=row
        if not full: return header,None,None
       elif full and isinstance(row,dict) and row.get("type")=="user/message":
        d=row.get("data")
        if isinstance(d,dict) and isinstance(d.get("source"),dict) and d["source"].get("kind")=="user":
         if not isinstance(d.get("content"),list): raise SystemExit("native_content_invalid")
         text="".join(x.get("text","") for x in d["content"] if isinstance(x,dict) and x.get("type")=="text" and isinstance(x.get("text"),str))
         users.append(hashlib.sha256(text.encode()).hexdigest())
    if r==0: need_init=True
  if pending or not need_init: raise SystemExit("native_truncated")
  opened_after=os.fstat(fd)
 finally:
  lib.ZSTD_freeDStream(stream); os.close(fd)
 after=os.lstat(path)
 if opened_after is None or stamp(opened_after)!=stamp(before) or stamp(after)!=stamp(before) or size!=before.st_size: raise SystemExit("native_file_changed")
 return (header,users),digest.hexdigest(),size
p=root/"sessions"/project_key(str(root))/expected/"session.v4.jsonl.zstd"
(h,users),digest,size=decode(p,True); h=h or {}
required={"type","version","id","createdAt","isSeeded","delegationDepth"}; allowed=required|{"cwd","parentSession","origin","agentPreset"}
if not isinstance(h,dict) or not required<=set(h) or not set(h)<=allowed or h.get("type")!="session" or type(h.get("version")) is not int or h.get("version")!=4 or type(h.get("createdAt")) is not int or type(h.get("isSeeded")) is not bool or type(h.get("delegationDepth")) is not int: raise SystemExit("native_header_invalid")
if h.get("id")!=expected or len(users)!=2: raise SystemExit("native_scope_invalid")
print(json.dumps({"schema_version":"byq-native-session-input-projection.v1","producer_source_sha256":producer,"native_session_id":h["id"],"binding_cwd":str(root),"workspace_id":workspace,"relative_path":str(p.relative_to(root)),"compressed_sha256":digest,"compressed_bytes":size,"header_id":h["id"],"header_version":h["version"],"human_input_sha256_order":users},separators=(",",":")))'''
    producer_hash = hashlib.sha256(projector.encode()).hexdigest()
    if producer_hash != PROJECTOR_SHA256:
        raise Stop("native_projector_source_changed")
    group_root = str(Path(args.session_root) / workspace)
    if ".." in Path(cwd).parts or not Path(cwd).is_relative_to(Path(group_root)):
        raise Stop("native_cwd_outside_workspace_volume")
    raw = _command(out, "native-projection", ["docker", "exec", "--user", "10002:10002", "--workdir", "/app", "-i", args.runner_id,
        "python3", "-I", "-c", projector, cwd, native_id, workspace, producer_hash], timeout=30, deadline=deadline)
    value = json.loads(raw)
    required = {"schema_version", "producer_source_sha256", "native_session_id", "binding_cwd", "workspace_id",
                "relative_path", "compressed_sha256", "compressed_bytes", "header_id", "header_version",
                "human_input_sha256_order"}
    if (not isinstance(value, dict) or set(value) != required
            or value.get("schema_version") != "byq-native-session-input-projection.v1"
            or value.get("producer_source_sha256") != PROJECTOR_SHA256
            or value.get("native_session_id") != native_id or value.get("header_id") != native_id
            or value.get("binding_cwd") != cwd or value.get("workspace_id") != workspace
            or value.get("relative_path") != f"sessions/{_session_project_key(cwd)}/{native_id}/session.v4.jsonl.zstd"
            or value.get("header_version") != 4
            or not isinstance(value.get("compressed_sha256"), str)
            or not HASH_RE.fullmatch(value["compressed_sha256"])
            or type(value.get("compressed_bytes")) is not int or value["compressed_bytes"] <= 0
            or not isinstance(value.get("human_input_sha256_order"), list)
            or len(value["human_input_sha256_order"]) != 2
            or any(not isinstance(item, str) or not HASH_RE.fullmatch(item)
                   for item in value["human_input_sha256_order"])):
        raise Stop("native_projection_schema_invalid")
    _json_write(out / "native-projection.json", value)


def _finish(args, out: Path, *, deadline: float) -> dict:
    jobs_before = _json_read(out / "jobs-before.json")
    jobs_after = _pg(out, args.postgres_id, "jobs-after", _job_counts_sql(), deadline=deadline)
    _json_write(out / "jobs-after.json", jobs_after)
    if jobs_before != jobs_after:
        raise Stop("job_inventory_changed")
    _verify_container_snapshot(args, out, "finish-final", deadline=deadline)
    # Include the legacy observer only after all input files have been captured.
    sys.path.insert(0, str(Path(__file__).parent))
    import importlib.util
    path = Path(__file__).with_name("acp-ordinary-continuous-observer.py")
    spec = importlib.util.spec_from_file_location("ordinary_observer", path)
    if spec is None or spec.loader is None:
        raise Stop("observer_unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result = module.inspect(out)
    _json_write(out / "observer-result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "capture-turn", "finish"))
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--conversation-id")
    parser.add_argument("--turn", type=int, choices=(1, 2))
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--adapter-id", required=True)
    parser.add_argument("--runner-id", required=True)
    parser.add_argument("--postgres-id", required=True)
    parser.add_argument("--session-root", required=True)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    if args.action == "preflight" and out.exists():
        print("STOP:capture_output_exists", file=sys.stderr)
        return 2
    try:
        if args.action == "preflight":
            out.mkdir(mode=0o700, parents=True)
            started_ns = time.monotonic_ns()
            started_utc = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            _json_write(out / "batch-clock.json", {
                "schema_version": "byq-ordinary-capture-clock.v1", "boot_id": _boot_id(),
                "started_monotonic_ns": started_ns,
                "deadline_monotonic_ns": started_ns + BATCH_SECONDS * 1_000_000_000,
                "started_utc": started_utc, "budget_seconds": BATCH_SECONDS})
            deadline = _action_start(out, "preflight")
            if args.session_root != SESSION_ROOT:
                raise Stop("session_root_not_authoritative")
            facts = _container_snapshot(args, out, "preflight", deadline=deadline)
            _json_write(out / "container-facts-preflight.json", facts)
            _native_runtime_preflight(args, out, deadline=deadline)
            _json_write(out / "authorized-login-writes.json", {
                "schema_version": "byq-ordinary-capture-authorized-login-writes.v1",
                "durable_login_may_write_auth_sessions": True,
                "business_jobs_created_by_capture": False})
            opener, identity = _login(deadline=deadline)
            if identity.get("role") != "admin" or identity.get("workspace_id") != WORKSPACE:
                raise Stop("admin_workspace_required")
            _json_write(out / "identity.json", identity)
            _json_write(out / "jobs-before.json", _pg(out, args.postgres_id, "jobs-before", _job_counts_sql(), deadline=deadline))
            _checkpoint_pass(out, "preflight", deadline=deadline)
            return 0
        if not out.is_dir() or (out.stat().st_mode & 0o077):
            raise Stop("capture_directory_permissions_invalid")
        if args.session_root != SESSION_ROOT:
            raise Stop("session_root_not_authoritative")
        stage = (f"turn-{args.turn}" if args.action == "capture-turn" else "finish")
        deadline = _action_start(out, stage)
        _verify_container_snapshot(args, out, stage, deadline=deadline)
        identity = _json_read(out / "identity.json")
        opener, current = _login(deadline=deadline)
        if identity != current:
            raise Stop("durable_identity_changed")
        if args.action == "capture-turn":
            if args.conversation_id is None or args.turn is None:
                raise Stop("turn_arguments_required")
            _capture_turn(args, opener, identity, deadline=deadline)
            _checkpoint_pass(out, stage, deadline=deadline)
            return 0
        result = _finish(args, out, deadline=deadline)
        if not isinstance(result, dict) or result.get("status") != "PASS":
            raise Stop("observer_contract_failed")
        _remaining(deadline, IO_TIMEOUT)
        _checkpoint_pass(out, "finish", deadline=deadline)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") == "PASS" else 1
    except Stop as exc:
        if (out.is_dir() and (out / "batch-clock.json").is_file()
                and not (out / "capture-stop.json").exists()):
            try:
                _json_write(out / "capture-stop.json", {
                    "status": "STOP", "reason": str(exc), "monotonic_ns": time.monotonic_ns()})
            except OSError:
                pass
        print(f"STOP:{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        reason = f"internal_{type(exc).__name__}"
        if (out.is_dir() and (out / "batch-clock.json").is_file()
                and not (out / "capture-stop.json").exists()):
            try:
                _json_write(out / "capture-stop.json", {
                    "status": "STOP", "reason": reason, "monotonic_ns": time.monotonic_ns()})
            except OSError:
                pass
        print(f"STOP:{reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
