#!/usr/bin/env python3
"""D15 real isolated runtime-continuity qualification driver.

Brings up the isolated stack (or reuses a running one), drives the normal BYQ
Product entry path plus the runtime-adapter service boundary with a keyless
scripted provider, records before/after evidence per fault row, and writes an
observations artifact for the independent fail-able observer.

This is service-boundary runtime-continuity evidence with a scripted provider.
It is NOT real-LLM-quality semantic evidence and does not claim D15-4/D15-5/D15-G.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMPOSE = HERE / "compose.runtime-qual.yml"
PROJECT = "byq-d15-runtime"
GATEWAY = "http://127.0.0.1:18100"
BACKEND = "http://127.0.0.1:18000"
ADAPTER = "http://127.0.0.1:18400"
MCP = "http://127.0.0.1:18300"
SESSION_ROOT = "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1"
ADAPTER_CONTAINER = "byq-d15-runtime-runtime-adapter-1"
GATEWAY_CONTAINER = "byq-d15-runtime-gateway-1"
PROVIDER_CONTAINER = "byq-d15-runtime-scripted-provider-1"
ALL_CONTAINERS = [
    "byq-d15-runtime-postgres-1", "byq-d15-runtime-scripted-provider-1",
    "byq-d15-runtime-backend-1", "byq-d15-runtime-mcp-1",
    ADAPTER_CONTAINER, GATEWAY_CONTAINER,
]


class QualError(RuntimeError):
    pass


def run(argv: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=check, timeout=timeout,
                          env={**os.environ, "PATH": os.environ.get("PATH", "/usr/bin:/bin")})


def docker(*args: str, check: bool = True, timeout: int = 120) -> str:
    return run(["docker", *args], check=check, timeout=timeout).stdout


def compose(*args: str, check: bool = True, timeout: int = 600) -> str:
    return run(["docker", "compose", "--env-file", "/dev/null", "-p", PROJECT, "-f", str(COMPOSE), *args],
               check=check, timeout=timeout).stdout


def http_json(method: str, url: str, payload: dict | None = None, *, headers: dict | None = None,
              opener: urllib.request.OpenerDirector | None = None, timeout: int = 30) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"content-type": "application/json", **(headers or {})})
    client = opener.open if opener else urllib.request.urlopen
    try:
        with client(request, timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        body = error.read().decode()
        raise QualError(f"{method} {url} -> {error.code}: {body[:300]}") from error


def try_http(method: str, url: str, payload: dict | None = None, *, opener=None, timeout: int = 30):
    try:
        return http_json(method, url, payload, opener=opener, timeout=timeout)
    except QualError as exc:
        return {"_error": str(exc)}


class ProductClient:
    def __init__(self, username: str, password: str) -> None:
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        body = self.call("POST", "/api/product/auth/login", {"username": username, "password": password})
        if body.get("user", {}).get("username") != username:
            raise QualError("product login returned the wrong user")

    def call(self, method: str, path: str, payload: dict | None = None, *, timeout: int = 30) -> dict:
        return http_json(method, GATEWAY + path, payload, opener=self.opener, timeout=timeout)


_LIFECYCLE = None


def lifecycle_module():
    global _LIFECYCLE
    if _LIFECYCLE is None:
        import importlib.util
        path = ROOT / "packages/contracts/agent_run_lifecycle.py"
        spec = importlib.util.spec_from_file_location("d15_agent_run_lifecycle", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _LIFECYCLE = module
    return _LIFECYCLE


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def container_pid(name: str) -> int:
    try:
        return int(docker("inspect", "-f", "{{.State.Pid}}", name).strip())
    except Exception:  # noqa: BLE001
        return 0


def adapter_dsh_pids() -> list[int]:
    # python:*-slim has no procps; scan /proc directly inside the container.
    script = (
        "for p in /proc/[0-9]*; do "
        "if tr '\\0' ' ' < \"$p/cmdline\" 2>/dev/null | grep -q deepseek-harness-sdk-runtime-linux-x64; then "
        "echo \"${p#/proc/}\"; fi; done"
    )
    result = run(["docker", "exec", ADAPTER_CONTAINER, "sh", "-c", script], check=False)
    return sorted(int(line) for line in result.stdout.split() if line.strip().isdigit())


def adapter_exec_python(code: str) -> str:
    return docker("exec", "-w", "/app", ADAPTER_CONTAINER, "python3", "-c", code, timeout=60)


def evidence_root() -> str:
    return f"{SESSION_ROOT}/byq-lifecycle-evidence"


def list_journals() -> list[str]:
    out = docker("exec", ADAPTER_CONTAINER, "sh", "-c",
                 f"ls -1 {evidence_root()}/*.json 2>/dev/null || true", check=False)
    return [Path(line).name[:-5] for line in out.splitlines() if line.strip()]


def read_journal(session_id: str) -> dict:
    raw = docker("exec", ADAPTER_CONTAINER, "sh", "-c",
                 f"cat {evidence_root()}/{session_id}.json", check=True)
    return json.loads(raw)["state"]


def read_generations(session_id: str) -> list[dict]:
    raw = docker("exec", ADAPTER_CONTAINER, "sh", "-c",
                 f"cat {evidence_root()}/generation-ledger/{session_id}.json 2>/dev/null || true", check=False)
    if not raw.strip():
        return []
    try:
        return json.loads(raw).get("generations", [])
    except json.JSONDecodeError:
        return []


def wait_trace_result(session_id: str, run_id: str, timeout: int = 45) -> list[dict]:
    deadline = time.time() + timeout
    events: list[dict] = []
    while time.time() < deadline:
        events = read_gateway_trace(session_id)
        if any(e.get("kind") == "session.result" and (e.get("payload") or {}).get("run_id") == run_id
               for e in events):
            return events
        time.sleep(1)
    return events


def read_gateway_trace(session_id: str) -> list[dict]:
    raw = docker("exec", GATEWAY_CONTAINER, "sh", "-c",
                 f"cat /var/lib/byq/workflow-traces/{session_id}.ndjson 2>/dev/null || true", check=False)
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def executor_epoch() -> int:
    out = adapter_exec_python(
        "import json,sys;sys.path.insert(0,'/app');from app import executor_identity as e;"
        "from pathlib import Path;print(json.dumps(e.read_epoch_state(Path('" + evidence_root() + "')) or {}))")
    return int(json.loads(out).get("executor_epoch") or 0)


def _safe_epoch() -> int:
    try:
        return executor_epoch()
    except Exception:  # noqa: BLE001
        return 0


def continuity_of(session_id: str) -> str:
    body = try_http("POST", f"{ADAPTER}/internal/runtime/sessions/{session_id}/resume", {})
    return str(body.get("continuity"))


def provider_calls() -> int:
    out = docker("exec", PROVIDER_CONTAINER, "python3", "-c",
                 "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8900/_calls').read().decode())",
                 check=False)
    return int(json.loads(out).get("calls", 0))


def set_provider_delay(seconds: float) -> None:
    docker("exec", PROVIDER_CONTAINER, "python3", "-c",
           f"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8900/_delay?seconds={seconds}').read().decode())",
           check=False)


def arm_provider_tool_call(name: str, arguments: dict) -> dict:
    payload = json.dumps({"name": name, "arguments": arguments})
    code = (
        "import urllib.request;"
        "data=" + repr(payload) + ".encode();"
        "req=urllib.request.Request('http://127.0.0.1:8900/_tool_call',data=data,"
        "headers={'content-type':'application/json'},method='POST');"
        "print(urllib.request.urlopen(req,timeout=5).read().decode())"
    )
    out = docker("exec", PROVIDER_CONTAINER, "python3", "-c", code, check=False)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def provider_state() -> dict:
    out = docker("exec", PROVIDER_CONTAINER, "python3", "-c",
                 "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8900/_calls',timeout=5).read().decode())",
                 check=False)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def tool_call_and_result(history: object, start: int = 0) -> tuple[dict | None, dict | None]:
    """Return the first real tool call at/after ``start`` and its matching result."""
    if not isinstance(history, list):
        return None, None
    call = None
    call_pos = None
    for index in range(max(0, start), len(history)):
        item = history[index]
        if isinstance(item, dict) and item.get("stage") == "call":
            call = item
            call_pos = index
            break
    if call is None:
        return None, None
    for index in range(call_pos + 1, len(history)):
        item = history[index]
        if isinstance(item, dict) and item.get("stage") == "result" \
                and item.get("call_id") == call.get("call_id"):
            return call, item
    return call, None


def tool_result_payload(result: object) -> dict:
    if isinstance(result, dict) and isinstance(result.get("content"), dict):
        return result["content"]
    return {}


def tool_result_task_id(result: object) -> str | None:
    value = tool_result_payload(result).get("task_id")
    return value if isinstance(value, str) and value else None


def tool_result_status(result: object) -> str | None:
    """Normalize an MCP tool result to ok/error.

    The MCP envelope is ``{"service":"beyondquant-mcp","status":...}`` but a
    successful domain payload can override ``status`` with its own value (e.g. a
    research task status of ``planned``), so success is keyed on the service
    envelope and an explicit ``error`` status.
    """
    content = tool_result_payload(result)
    if content.get("service") != "beyondquant-mcp":
        return None
    if content.get("status") == "error":
        return "error"
    return "ok"


def wait_healthy(name: str, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = docker("inspect", "-f", "{{.State.Health.Status}}", name, check=False).strip()
        if out == "healthy":
            return
        time.sleep(2)
    raise QualError(f"container did not become healthy: {name} ({out!r})")


def wait_not_running(timeout: int = 45) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = try_http("GET", f"{ADAPTER}/internal/runtime/operations")
        active = (body.get("sessions") or {}).get("status_counts", {}).get("running", 0) if isinstance(body, dict) else 0
        if not active:
            return
        time.sleep(1)


TERMINAL_KINDS = frozenset({
    "session.result", "session.failed", "session.cancelled",
    "session.result.discarded", "session.closed",
})
ORIGIN_MANUAL = "product-api-manual"
ORIGIN_AGENT = "agent-mcp"


def derive_goal_receipt(journal: object, message_id: object) -> tuple[dict | None, str | None]:
    """Return the durable prompt receipt or an explicit error; never fabricate."""
    if not isinstance(journal, dict):
        return None, "journal unavailable"
    prompts = journal.get("prompts")
    if not isinstance(prompts, dict):
        return None, "journal has no prompt receipts"
    receipt = prompts.get(message_id)
    if not isinstance(receipt, dict):
        return None, f"durable journal prompt receipt missing for {message_id!r}"
    root = receipt.get("root_run_id")
    digest = receipt.get("content_sha256")
    if not isinstance(root, str) or not root or not isinstance(digest, str) or not digest:
        return None, "durable journal prompt receipt is incomplete"
    return {"root_run_id": root, "content_sha256": digest}, None


def derive_replay_run(replay: object) -> tuple[str | None, str | None]:
    """Return the idempotent replay run id or an explicit error; never fall back."""
    if not isinstance(replay, dict):
        return None, "prompt replay returned no response"
    if "_error" in replay:
        return None, f"prompt replay request error: {str(replay['_error'])[:160]}"
    run_id = replay.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return None, "prompt replay returned no run_id"
    return run_id, None


def derive_trace_evidence(trace_events: object, messages: object,
                          target_run_id: object) -> dict:
    """Full-sequence continuity + target-run completion/attribution.

    ``trace_contiguous`` is computed over the whole persisted sequence (which
    must start at 1 and have no gaps). ``completed``/``attributed_message_sequence``
    are attributed to the TARGET run only, never to an arbitrary historical
    assistant message.
    """
    errors: list[str] = []
    events = [e for e in trace_events if isinstance(e, dict) and type(e.get("sequence")) is int] \
        if isinstance(trace_events, list) else []
    sequences = [e["sequence"] for e in events]
    contiguous = bool(sequences) and sequences == list(range(1, len(sequences) + 1))
    if not sequences:
        errors.append("no persisted trace events")
    elif not contiguous:
        errors.append("persisted trace sequence is not contiguous from 1")

    started = [e for e in events if e.get("kind") == "session.started"
               and (e.get("payload") or {}).get("run_id") == target_run_id]
    terminals = [e for e in events if e.get("kind") in TERMINAL_KINDS
                 and (e.get("payload") or {}).get("run_id") == target_run_id]
    terminal = terminals[-1] if terminals else None
    completed = terminal is not None and terminal.get("kind") == "session.result"
    start_sequence = started[0]["sequence"] if started else None
    terminal_sequence = terminal["sequence"] if terminal else None

    attributed: int | None = None
    if start_sequence is not None and terminal_sequence is not None and isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            workflow_sequence = message.get("workflow_sequence")
            if type(workflow_sequence) is int and start_sequence < workflow_sequence <= terminal_sequence:
                attributed = workflow_sequence

    if not isinstance(target_run_id, str) or not target_run_id:
        errors.append("no target run id for attribution")
    else:
        if not started:
            errors.append(f"target run {target_run_id} has no session.started event")
        if terminal is None:
            errors.append(f"target run {target_run_id} has no terminal event")
        elif not completed:
            errors.append(f"target run {target_run_id} terminal is {terminal.get('kind')!r}, not session.result")
        if completed and attributed is None:
            errors.append("no assistant message is attributed to the target run")

    return {
        "trace_contiguous": contiguous,
        "completed": completed,
        "terminal_kind": terminal.get("kind") if terminal else None,
        "start_sequence": start_sequence,
        "terminal_sequence": terminal_sequence,
        "attributed_message_sequence": attributed,
        "errors": errors,
    }


def artifact_of(response: object) -> dict:
    if isinstance(response, dict) and isinstance(response.get("artifact"), dict):
        return response["artifact"]
    return response if isinstance(response, dict) else {}


def _maybe_json(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"raw": raw[:300]}
    return value if isinstance(value, dict) else {"raw": str(value)[:300]}


def http_attempt(method: str, url: str, payload: dict | None = None, *,
                 opener: urllib.request.OpenerDirector | None = None, timeout: int = 30) -> dict:
    """Return the HTTP status and parsed body; never infer denial from an error alone."""
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"content-type": "application/json"})
    client = opener.open if opener else urllib.request.urlopen
    try:
        with client(request, timeout=timeout) as response:
            return {"ok": True, "status": response.status,
                    "body": _maybe_json(response.read().decode()), "error": None}
    except urllib.error.HTTPError as error:
        return {"ok": False, "status": error.code,
                "body": _maybe_json(error.read().decode()), "error": f"http {error.code}"}
    except Exception as exc:  # noqa: BLE001 - timeouts/connection errors are not denials
        return {"ok": False, "status": 0, "body": None, "error": f"{type(exc).__name__}: {exc}"}


def domain_code(attempt: object) -> str | None:
    """Extract a closed domain error code/message from a backend error body."""
    if not isinstance(attempt, dict):
        return None
    body = attempt.get("body")
    if not isinstance(body, dict):
        return None
    for key in ("code", "detail"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    error = body.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict):
        for key in ("code", "message"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def definitive_denial(attempt: object) -> bool:
    """A denial requires an explicit 4xx client rejection with a domain code."""
    if not isinstance(attempt, dict):
        return False
    status = attempt.get("status")
    return isinstance(status, int) and 400 <= status < 500 and bool(domain_code(attempt))


def derive_approval(approved_response: object, rejected_response: object,
                    verification: object, fetched_approval: object) -> dict:
    """Approval fields come only from persisted responses + real protected-operation trials.

    Denial is never inferred from an arbitrary error: the invalid-reuse and the
    protected-operation attempts must record a definitive 4xx domain rejection,
    and the protected operation must leave the authoritative side-effect count
    unchanged. ``verification`` carries an explicit ``phase`` (pre-fault or
    post-fault) so a pre-fault proof is never reported as a post-fault attempt.
    """
    approved = artifact_of(approved_response)
    approved_content = approved.get("content") if isinstance(approved.get("content"), dict) else {}
    rejected = artifact_of(rejected_response)
    rejected_content = rejected.get("content") if isinstance(rejected.get("content"), dict) else {}

    approved_state = approved_content.get("decision")
    approved_authorized = approved_content.get("execution_authorized")
    rejected_state = rejected_content.get("decision")
    rejected_authorized = rejected_content.get("execution_authorized")

    verification = verification if isinstance(verification, dict) else {}
    phase = verification.get("phase")
    invalid_reuse_attempt = verification.get("invalid_reuse")
    protected_attempt = verification.get("protected_operation")

    invalid_denied = definitive_denial(invalid_reuse_attempt)
    invalid_status = _as_int(invalid_reuse_attempt.get("status")) if isinstance(invalid_reuse_attempt, dict) else None

    before_count = _as_int(verification.get("backtests_before"))
    after_count = _as_int(verification.get("backtests_after"))
    count_unchanged = before_count is not None and after_count is not None and after_count == before_count
    protected_definitive = definitive_denial(protected_attempt)
    protected_denied = protected_definitive and count_unchanged
    protected_status = _as_int(protected_attempt.get("status")) if isinstance(protected_attempt, dict) else None
    protected_side = (not count_unchanged) or (not protected_definitive and count_unchanged)

    rejected_denied = rejected_state == "rejected" and rejected_authorized is False
    trials = [
        {"kind": "rejected", "state": rejected_state, "denied": bool(rejected_denied),
         "side_effect_created": not bool(rejected_denied),
         "artifact_id": rejected.get("artifact_id"), "http_status": 201, "phase": "durable"},
        {"kind": "invalid_reuse", "state": rejected_state, "denied": bool(invalid_denied),
         "side_effect_created": not bool(invalid_denied), "phase": phase,
         "http_status": invalid_status, "domain_code": domain_code(invalid_reuse_attempt)},
        {"kind": "protected_operation_blocked", "state": rejected_state, "denied": bool(protected_denied),
         "side_effect_created": bool(protected_side), "phase": phase,
         "http_status": protected_status, "domain_code": domain_code(protected_attempt),
         "before_count": before_count, "after_count": after_count},
    ]
    bypassed = any(trial["side_effect_created"] for trial in trials)
    fetched = artifact_of(fetched_approval)
    fetched_content = fetched.get("content") if isinstance(fetched.get("content"), dict) else {}
    return {
        "approval_id": approved.get("artifact_id"),
        "state": approved_state,
        "decided_by": approved_content.get("reviewer_principal"),
        "execution_authorized": approved_authorized,
        "bypassed": bypassed,
        "reuse_denied": all(trial["denied"] for trial in trials),
        "trials": trials,
        "fetched_approval": {
            "artifact_id": fetched.get("artifact_id"),
            "state": fetched_content.get("decision"),
        },
    }


def make_receipt(tool: str, key: str, receipt: dict, side_effect_count: int, origin: str,
                 replay_receipt: dict | None = None, replay_side_effect_count: int | None = None) -> dict:
    """Build a receipt; the count and origin are mandatory and measured."""
    if not isinstance(side_effect_count, int) or isinstance(side_effect_count, bool):
        raise QualError("side_effect_count must be measured before building a receipt")
    if origin not in {ORIGIN_MANUAL, ORIGIN_AGENT}:
        raise QualError("action origin must be labeled")
    replay_count = side_effect_count if replay_side_effect_count is None else replay_side_effect_count
    return {"tool": tool, "origin": origin, "idempotency_key": key, "receipt": receipt,
            "side_effect_count": side_effect_count,
            "replay": {"receipt": receipt if replay_receipt is None else replay_receipt,
                       "side_effect_count": replay_count}}


class Qualification:
    def __init__(self, client: ProductClient) -> None:
        self.client = client
        self.runtime_session_id: str | None = None
        self.conversation_id: str | None = None
        self.trace_id: str | None = None
        self.message_id: str | None = None
        self.agent_runtime_session_id: str | None = None
        self.agent_conversation_id: str | None = None
        self.agent_trace_id: str | None = None
        self.goal = ("D15 runtime continuity original goal: preserve this research objective "
                     "across adapter, DSH and Gateway faults without duplicate side effects.")
        self.artifacts: dict[str, object] = {}

    # ---- domain entry path (research task, persistent approval, side effect) ----
    def _strategy_version(self, task_id: str, prefix: str, lookback: int) -> str:
        source = (
            "import pandas as pd\n"
            "class CustomStrategy:\n"
            "    def generate_signals(self, data, parameters=None):\n"
            "        result = {}\n"
            "        for symbol in data.index.get_level_values('symbol').unique():\n"
            "            closes = data.xs(symbol, level='symbol')['close']\n"
            "            result[str(symbol)] = (closes > closes.shift(1)).fillna(False).astype(int)\n"
            "        return result\n"
        )
        strategy = {
            "strategy_id": f"D15RuntimeContinuity{prefix}", "name": f"D15 Runtime Continuity {prefix}",
            "category": "momentum", "description": "D15 isolated approval fixture.",
            "parameters": {"lookback": lookback},
            "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
            "source_type": "python_script", "script": source,
        }
        common = {"task_id": task_id, "strategy": strategy}
        self.client.call("POST", "/api/product/strategies/drafts",
                         {**common, "trace_id": f"d15-draft-{uuid.uuid4().hex}",
                          "idempotency_key": f"d15-draft-{uuid.uuid4().hex}"})
        validated = self.client.call("POST", "/api/product/strategies/validate",
                                     {**common, "trace_id": f"d15-valid-{uuid.uuid4().hex}",
                                      "idempotency_key": f"d15-valid-{uuid.uuid4().hex}"})
        draft_id = str(validated["artifact"]["artifact_id"])
        version = self.client.call("POST", "/api/product/strategies/versions",
                                   {"task_id": task_id, "draft_artifact_id": draft_id,
                                    "trace_id": f"d15-version-{uuid.uuid4().hex}",
                                    "idempotency_key": f"d15-version-{uuid.uuid4().hex}"})
        return str(version["artifact"]["artifact_id"])

    def _approval(self, task_id: str, version_id: str, decision: str, key: str) -> dict:
        body = {"task_id": task_id, "strategy_version_artifact_id": version_id,
                "decision": decision, "rationale": f"D15 isolated human {decision} decision.",
                "trace_id": f"d15-approval-trace-{uuid.uuid4().hex}", "idempotency_key": key}
        response = self.client.call("POST", "/api/product/strategies/approvals", body)
        return {"body": body, "response": response}

    def create_domain_state(self) -> None:
        task = self.client.call("POST", "/api/product/research/tasks",
                                {"title": "D15 runtime continuity isolated task",
                                 "objective": self.goal})
        task_id = str(task["task_id"])
        version_id = self._strategy_version(task_id, "Main", 1)
        approved = self._approval(task_id, version_id, "approved", f"d15-approval-{uuid.uuid4().hex}")
        approved_id = str(artifact_of(approved["response"]).get("artifact_id"))

        # Real deny trials: a persisted REJECT decision on a distinct version, and
        # an invalid reuse of the approved idempotency key with a different decision.
        rejected_version_id = self._strategy_version(task_id, "Reject", 2)
        rejected = self._approval(task_id, rejected_version_id, "rejected",
                                  f"d15-approval-reject-{uuid.uuid4().hex}")
        rejected_id = str(artifact_of(rejected["response"]).get("artifact_id"))
        invalid_body = {**approved["body"], "decision": "rejected",
                        "rationale": "D15 invalid reuse attempt.",
                        "idempotency_key": approved["body"]["idempotency_key"]}

        pool_key = f"d15-pool-{uuid.uuid4().hex}"
        pool_name = f"D15 isolated pool {uuid.uuid4().hex}"
        pool_body = {"idempotency_key": pool_key, "name": pool_name,
                     "pool_type": "custom", "symbols": ["000001.SZ"]}
        pool = self.client.call("POST", "/api/product/paper/pools", pool_body)
        pool_id = str(pool["pool"]["pool_id"])
        self.artifacts = {
            "task_id": task_id,
            "strategy_version_artifact_id": version_id,
            "approval_id": approved_id,
            "approval_key": approved["body"]["idempotency_key"],
            "approval_body": approved["body"],
            "approved_response": approved["response"],
            "rejected_version_artifact_id": rejected_version_id,
            "rejected_approval_id": rejected_id,
            "rejected_response": rejected["response"],
            "invalid_reuse_body": invalid_body,
            "pool_id": pool_id, "pool_key": pool_key, "pool_body": pool_body,
            "pool_name": pool_name,
        }
        self.artifacts["approval_verification_pre"] = self.verify_approval("pre-fault")

    def _backtest_count(self) -> int:
        body = self.client.call("GET", "/api/product/backtests")
        rows = body.get("backtests") if isinstance(body, dict) else None
        return len(rows) if isinstance(rows, list) else 0

    def verify_approval(self, phase: str) -> dict:
        """Re-attempt the invalid reuse and the protected operation for one phase.

        The authoritative backtest-job count is measured immediately before and
        after the protected-operation attempt. ``phase`` labels whether this is
        the pre-fault proof or an actual post-fault re-attempt.
        """
        invalid = http_attempt("POST", f"{GATEWAY}/api/product/strategies/approvals",
                               self.artifacts["invalid_reuse_body"], opener=self.client.opener)
        before = self._backtest_count()
        protected = http_attempt("POST", f"{GATEWAY}/api/product/backtests",
                                 {"task_id": self.artifacts["task_id"],
                                  "strategy_version_artifact_id": self.artifacts["rejected_version_artifact_id"],
                                  "approval_artifact_id": self.artifacts["rejected_approval_id"],
                                  "trace_id": f"d15-protected-{uuid.uuid4().hex}",
                                  "idempotency_key": f"d15-protected-{uuid.uuid4().hex}"},
                                 opener=self.client.opener)
        after = self._backtest_count()
        return {"phase": phase, "invalid_reuse": invalid, "protected_operation": protected,
                "backtests_before": before, "backtests_after": after}

    def domain_replay(self) -> dict:
        pool = self.client.call("POST", "/api/product/paper/pools", self.artifacts["pool_body"])
        replay_pool_id = str(pool["pool"]["pool_id"])
        pools = self.client.call("GET", "/api/product/paper/pools")
        pool_rows = [item for item in pools.get("pools", [])
                     if item.get("name") == self.artifacts["pool_name"]]
        fetched_approved = self.client.call(
            "GET", f"/api/product/research/artifacts/{self.artifacts['approval_id']}")
        approval_replay = try_http("POST", f"{GATEWAY}/api/product/strategies/approvals",
                                   self.artifacts["approval_body"], opener=self.client.opener)
        replay_approval_id = None
        if isinstance(approval_replay, dict) and isinstance(approval_replay.get("artifact"), dict):
            replay_approval_id = approval_replay["artifact"].get("artifact_id")
        artifacts = self.client.call("GET", "/api/product/research/artifacts")
        rows = artifacts.get("artifacts") if isinstance(artifacts, dict) else []
        approval_rows = [item for item in (rows or []) if isinstance(item, dict)
                         and item.get("kind") == "strategy_approval"
                         and (item.get("content") or {}).get("strategy_version_artifact_id")
                         == self.artifacts["strategy_version_artifact_id"]]
        return {
            "replay_pool_id": replay_pool_id,
            "pool_side_effect_count": len(pool_rows),
            "approval_side_effect_count": len(approval_rows),
            "fetched_approved": fetched_approved,
            "replay_approval_id": replay_approval_id,
            "approval_replay_matches": replay_approval_id == self.artifacts["approval_id"],
        }

    # ---- agent session path ----
    def create_session(self) -> None:
        body = self.client.call("POST", "/v1/agent/sessions", {})
        self.conversation_id = str(body["session_id"])
        self.trace_id = str(body["trace_id"])
        deadline = time.time() + 30
        while time.time() < deadline:
            journals = list_journals()
            if journals:
                self.runtime_session_id = journals[0]
                break
            time.sleep(1)
        if not self.runtime_session_id:
            raise QualError("runtime session journal was not created")

    def submit_goal(self) -> dict:
        body = self.client.call("POST", f"/v1/agent/sessions/{self.conversation_id}/turns",
                                {"content": self.goal}, timeout=30)
        self.message_id = self.message_id or self._last_user_message_id()
        self.artifacts["run_id"] = body.get("run_id")
        return body

    def _last_user_message_id(self) -> str | None:
        detail = self.client.call("GET", f"/v1/agent/sessions/{self.conversation_id}")
        for message in reversed(detail.get("messages", [])):
            if message.get("role") == "user":
                return str(message["message_id"])
        return None

    def wait_result(self, timeout: int = 90) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            detail = self.client.call("GET", f"/v1/agent/sessions/{self.conversation_id}")
            assistant = [m for m in detail.get("messages", []) if m.get("role") == "assistant"]
            if assistant:
                return detail
            time.sleep(1)
        raise QualError("assistant result did not persist")

    def capture(self, continuity: str | None = None, *, message_id: str | None = None,
                phase: str = "pre-fault") -> dict:
        errors: list[str] = []
        journal = None
        try:
            journal = read_journal(self.runtime_session_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"journal read failed: {exc}")
        generations = read_generations(self.runtime_session_id)

        detail = try_http("GET", f"{GATEWAY}/v1/agent/sessions/{self.conversation_id}",
                          opener=self.client.opener)
        if not isinstance(detail, dict) or "_error" in detail:
            errors.append(f"product session read failed: {detail.get('_error') if isinstance(detail, dict) else detail}")
            detail = {}
        messages = detail.get("messages") if isinstance(detail.get("messages"), list) else []

        receipt, receipt_error = derive_goal_receipt(journal, message_id or self.message_id)
        if receipt_error:
            errors.append(receipt_error)
        target_run = receipt.get("root_run_id") if receipt else None
        if target_run is None:
            errors.append("no durable target run id; refusing to attribute a result")

        replay = try_http("POST", f"{ADAPTER}/internal/runtime/sessions/{self.runtime_session_id}/prompt",
                          {"content": self.goal, "idempotency_key": message_id or self.message_id,
                           "require_model_key": False})
        replay_run, replay_error = derive_replay_run(replay)
        if replay_error:
            errors.append(replay_error)
        elif target_run is not None and replay_run != target_run:
            errors.append(f"prompt replay returned {replay_run!r}, not the durable target run {target_run!r}")

        try:
            domain = self.domain_replay()
        except QualError as exc:
            domain = {}
            errors.append(f"domain replay failed: {exc}")

        if phase == "pre-fault":
            verification = self.artifacts.get("approval_verification_pre")
        else:
            try:
                verification = self.verify_approval(phase)
            except QualError as exc:
                verification = {"phase": phase}
                errors.append(f"post-fault approval re-verification failed: {exc}")
        approval = derive_approval(
            self.artifacts["approved_response"], self.artifacts["rejected_response"],
            verification, domain.get("fetched_approved"))
        if approval.get("state") != "approved":
            errors.append(f"persisted approval state is {approval.get('state')!r}, not approved")
        if approval.get("execution_authorized") is not True:
            errors.append("persisted approval is not execution_authorized")
        if approval.get("bypassed"):
            errors.append("an approval deny trial created a side effect")
        pool_count = domain.get("pool_side_effect_count")
        approval_count = domain.get("approval_side_effect_count")
        if pool_count != 1:
            errors.append(f"measured pool side-effect count is {pool_count!r}, not 1")
        if approval_count != 1:
            errors.append(f"measured approval side-effect count is {approval_count!r}, not 1")
        if not domain.get("approval_replay_matches"):
            errors.append("approval replay did not return the original approval id")

        trace_events = read_gateway_trace(self.runtime_session_id)
        trace = derive_trace_evidence(trace_events, messages, target_run)
        errors.extend(trace["errors"])

        epoch = journal.get("executor_epoch") if isinstance(journal, dict) else None
        if not isinstance(epoch, int) or epoch < 1:
            epoch = _safe_epoch()
        prompt_count = 1 if (receipt is not None and replay_run == target_run) else 0
        sequence = journal.get("sequence") if isinstance(journal, dict) and type(journal.get("sequence")) is int else 0
        capture_ok = not errors
        return {
            "session_id": self.conversation_id,
            "trace_id": self.trace_id,
            "adapter_pid": container_pid(ADAPTER_CONTAINER),
            "adapter_generation": generations[-1]["generation_id"] if generations else "generation-none",
            "generation_index": len(generations),
            "executor_epoch": epoch,
            "continuity": continuity,
            "capture_ok": capture_ok,
            "capture_errors": errors,
            "goal": {"content_sha256": receipt.get("content_sha256") if receipt else None,
                     "prompt_receipt": receipt},
            "approval": approval,
            "action_receipts": [
                make_receipt("runtime.prompt.idempotent", message_id or self.message_id,
                             {"state": "accepted", "run_id": replay_run}, prompt_count, ORIGIN_MANUAL,
                             replay_receipt={"state": "accepted", "run_id": replay_run},
                             replay_side_effect_count=prompt_count),
                make_receipt("byq_paper_pool_create", self.artifacts["pool_key"],
                             {"state": "accepted", "pool_id": self.artifacts["pool_id"]},
                             pool_count if isinstance(pool_count, int) else 0, ORIGIN_MANUAL,
                             replay_receipt={"state": "accepted", "pool_id": domain.get("replay_pool_id")},
                             replay_side_effect_count=pool_count if isinstance(pool_count, int) else 0),
                make_receipt("byq_strategy_approval", self.artifacts["approval_key"],
                             {"state": "approved", "approval_id": self.artifacts["approval_id"]},
                             approval_count if isinstance(approval_count, int) else 0, ORIGIN_MANUAL,
                             replay_receipt={"state": "approved", "approval_id": domain.get("replay_approval_id")},
                             replay_side_effect_count=approval_count if isinstance(approval_count, int) else 0),
            ],
            "result": {
                "run_id": target_run,
                "status": "completed" if trace["completed"] else ("missing" if not trace_events else "incomplete"),
                "sequence": sequence,
                "trace_contiguous": trace["trace_contiguous"],
                "target_run_id": target_run,
                "terminal_kind": trace["terminal_kind"],
                "attributed_message_sequence": trace["attributed_message_sequence"],
            },
            "_trace_event_count": len(trace_events),
            "_journal_generations": generations,
            "_domain": {k: v for k, v in domain.items() if k != "fetched_approved"},
            "_detail_message_count": len(messages),
            "_provider_calls": provider_calls(),
            "_dsh_pids": adapter_dsh_pids(),
        }

    # ---- real Agent -> MCP -> Backend path (scripted provider emits a tool call) ----
    def _new_journal(self, exclude: str | None) -> str:
        deadline = time.time() + 30
        while time.time() < deadline:
            journals = [item for item in list_journals() if item != exclude]
            if journals:
                return journals[0]
            time.sleep(1)
        raise QualError("agent-mcp session journal was not created")

    def create_agent_mcp_session(self) -> None:
        body = self.client.call("POST", "/v1/agent/sessions", {})
        self.agent_conversation_id = str(body["session_id"])
        self.agent_trace_id = str(body["trace_id"])
        self.agent_runtime_session_id = self._new_journal(self.runtime_session_id)

    def _agent_user_message_id(self) -> str | None:
        detail = self.client.call("GET", f"/v1/agent/sessions/{self.agent_conversation_id}")
        for message in reversed(detail.get("messages", [])):
            if message.get("role") == "user":
                return str(message["message_id"])
        return None

    def submit_agent_mcp_turn(self, key: str, title: str, objective: str) -> dict:
        arm_provider_tool_call("mcp__byq__byq_research_task_create",
                               {"owner_principal": "placeholder", "title": title,
                                "objective": objective, "trace_id": "placeholder",
                                "idempotency_key": key})
        return self.client.call("POST", f"/v1/agent/sessions/{self.agent_conversation_id}/turns",
                                {"content": f"Create the research task titled {title}."}, timeout=30)

    def research_tasks_by_title(self, title: str) -> list[dict]:
        body = self.client.call("GET", "/api/product/research/tasks")
        rows = body.get("tasks") if isinstance(body, dict) else None
        return [row for row in (rows or []) if isinstance(row, dict) and row.get("title") == title]

    def _agent_user_message_ids(self) -> list[str]:
        detail = self.client.call("GET", f"/v1/agent/sessions/{self.agent_conversation_id}")
        return [str(m["message_id"]) for m in detail.get("messages", [])
                if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("message_id"), str)]

    def wait_agent_run_complete(self, run_id: str, timeout: int = 60) -> dict:
        """Wait for THIS run's terminal and its own attributed assistant message."""
        deadline = time.time() + timeout
        trace: dict = {}
        while time.time() < deadline:
            detail = self.client.call("GET", f"/v1/agent/sessions/{self.agent_conversation_id}")
            messages = detail.get("messages") if isinstance(detail.get("messages"), list) else []
            trace_events = read_gateway_trace(self.agent_runtime_session_id)
            trace = derive_trace_evidence(trace_events, messages, run_id)
            if trace.get("completed") and isinstance(trace.get("attributed_message_sequence"), int):
                return trace
            time.sleep(1)
        return trace

    def wait_agent_tool_result(self, history_start: int, timeout: int = 60) -> tuple[dict | None, dict | None]:
        """Wait for a real tool call at/after the marker and its matching tool result."""
        deadline = time.time() + timeout
        call = result = None
        while time.time() < deadline:
            history = provider_state().get("tool_history") or []
            call, result = tool_call_and_result(history, history_start)
            if call is not None and result is not None:
                return call, result
            time.sleep(1)
        return call, result

    def _agent_run_view(self, run: dict) -> dict:
        run_id = run.get("run_id")
        try:
            journal = read_journal(self.agent_runtime_session_id)
        except Exception as exc:  # noqa: BLE001
            journal = None
            return {"receipt": None, "receipt_error": f"agent-mcp journal read failed: {exc}", "trace": {}}
        receipt, receipt_error = derive_goal_receipt(journal, run.get("message_id"))
        detail = try_http("GET", f"{GATEWAY}/v1/agent/sessions/{self.agent_conversation_id}",
                          opener=self.client.opener)
        messages = detail.get("messages") if isinstance(detail, dict) and isinstance(
            detail.get("messages"), list) else []
        trace_events = read_gateway_trace(self.agent_runtime_session_id)
        trace = derive_trace_evidence(trace_events, messages, run_id)
        return {"receipt": receipt, "receipt_error": receipt_error, "trace": trace}

    def capture_agent_mcp(self, *, key: str, title: str, continuity: str, first_run: dict,
                          second_run: dict | None = None, phase: str = "pre-fault") -> dict:
        errors: list[str] = []
        if continuity not in {"fresh", "reattached", "rehydrated", "interrupted"}:
            errors.append(f"agent-mcp continuity is invalid: {continuity!r}")

        first_view = self._agent_run_view(first_run)
        if first_view.get("receipt_error"):
            errors.append(first_view["receipt_error"])
        first_receipt = first_view.get("receipt")
        if first_receipt is not None and first_receipt.get("root_run_id") != first_run.get("run_id"):
            errors.append(f"first agent-mcp receipt run {first_receipt.get('root_run_id')!r} != {first_run.get('run_id')!r}")
        errors.extend((first_view.get("trace") or {}).get("errors", []))

        first_task = tool_result_task_id(first_run.get("tool_result"))
        first_status = tool_result_status(first_run.get("tool_result"))
        if first_status != "ok" or not first_task:
            errors.append("first agent-mcp tool result is not an ok MCP receipt")

        second_view = None
        second_task = second_status = None
        if second_run is not None:
            second_view = self._agent_run_view(second_run)
            if second_view.get("receipt_error"):
                errors.append(second_view["receipt_error"])
            errors.extend((second_view.get("trace") or {}).get("errors", []))
            second_task = tool_result_task_id(second_run.get("tool_result"))
            second_status = tool_result_status(second_run.get("tool_result"))
            if second_status != "ok" or not second_task:
                errors.append("second agent-mcp tool result is not an ok MCP receipt")
            if second_task != first_task:
                errors.append(f"second agent-mcp task {second_task!r} != first {first_task!r}")
            first_call_id = (first_run.get("tool_call") or {}).get("call_id")
            second_call_id = (second_run.get("tool_call") or {}).get("call_id")
            if not second_call_id or second_call_id == first_call_id:
                errors.append("second tool call id is not a distinct real call")
            first_index = (first_run.get("tool_call") or {}).get("call_index")
            second_index = (second_run.get("tool_call") or {}).get("call_index")
            if not (isinstance(first_index, int) and isinstance(second_index, int) and second_index > first_index):
                errors.append("scripted provider did not emit an incremented second tool call")

        tasks = self.research_tasks_by_title(title)
        count = len(tasks)
        if count != 1:
            errors.append(f"agent-mcp task side-effect count is {count}, not 1")

        if phase == "pre-fault":
            verification = self.artifacts.get("approval_verification_pre")
        else:
            try:
                verification = self.verify_approval(phase)
            except QualError as exc:
                verification = {"phase": phase}
                errors.append(f"agent-mcp post-fault approval re-verification failed: {exc}")
        approval = derive_approval(
            self.artifacts["approved_response"], self.artifacts["rejected_response"], verification, None)

        def run_dict(run: dict, view: dict) -> dict:
            return {
                "run_id": run.get("run_id"),
                "message_id": run.get("message_id"),
                "tool_call_id": (run.get("tool_call") or {}).get("call_id"),
                "call_index": (run.get("tool_call") or {}).get("call_index"),
                "task_id": tool_result_task_id(run.get("tool_result")),
                "mcp_status": tool_result_status(run.get("tool_result")),
                "terminal_kind": (view.get("trace") or {}).get("terminal_kind"),
                "terminal_sequence": (view.get("trace") or {}).get("terminal_sequence"),
                "assistant_sequence": (view.get("trace") or {}).get("attributed_message_sequence"),
                "side_effect_count": count,
            }

        runs = {"first": run_dict(first_run, first_view)}
        if second_run is not None:
            runs["second"] = run_dict(second_run, second_view)

        delivery = {"state": "accepted", "task_id": first_task,
                    "tool_call_id": (first_run.get("tool_call") or {}).get("call_id"),
                    "trace_id": self.agent_trace_id}
        if second_run is not None:
            replay = {"state": "accepted", "task_id": second_task,
                      "tool_call_id": (second_run.get("tool_call") or {}).get("call_id"),
                      "trace_id": self.agent_trace_id}
        else:
            replay = delivery

        try:
            journal = read_journal(self.agent_runtime_session_id)
        except Exception:  # noqa: BLE001
            journal = None
        epoch = journal.get("executor_epoch") if isinstance(journal, dict) else None
        if not isinstance(epoch, int) or epoch < 1:
            epoch = _safe_epoch()
        sequence = journal.get("sequence") if isinstance(journal, dict) and type(journal.get("sequence")) is int else 0
        generations = read_generations(self.agent_runtime_session_id)
        state = provider_state()
        return {
            "session_id": self.agent_conversation_id,
            "trace_id": self.agent_trace_id,
            "adapter_pid": container_pid(ADAPTER_CONTAINER),
            "adapter_generation": (generations or [{}])[-1].get("generation_id", "generation-none"),
            "generation_index": len(generations),
            "executor_epoch": epoch,
            "continuity": continuity,
            "capture_ok": not errors,
            "capture_errors": errors,
            "goal": {"content_sha256": first_receipt.get("content_sha256") if first_receipt else None,
                     "prompt_receipt": first_receipt},
            "approval": approval,
            "action_receipts": [
                make_receipt("mcp__byq__byq_research_task_create", key, delivery, count, ORIGIN_AGENT,
                             replay_receipt=replay, replay_side_effect_count=count),
            ],
            "agent_mcp_runs": runs,
            "result": {
                "run_id": first_run.get("run_id"),
                "status": "completed" if (first_view.get("trace") or {}).get("completed") else "incomplete",
                "sequence": sequence,
                "trace_contiguous": (first_view.get("trace") or {}).get("trace_contiguous", False),
                "target_run_id": first_run.get("run_id"),
                "terminal_kind": (first_view.get("trace") or {}).get("terminal_kind"),
                "attributed_message_sequence": (first_view.get("trace") or {}).get("attributed_message_sequence"),
            },
            "_provider_tool_name": state.get("last_tool_name"),
            "_provider_tool_calls_emitted": state.get("tool_calls_emitted"),
            "_task_count": count,
        }

    def agent_mcp_domain_at_most_once(self) -> dict:
        key = f"d15-mcp-{uuid.uuid4().hex}"
        title = f"D15 agent-mcp task {uuid.uuid4().hex}"
        objective = "D15 real Agent->MCP->Backend at-most-once across an adapter fault."
        self.create_agent_mcp_session()

        # First real run: real tool call -> real MCP result -> this run's terminal + assistant.
        history_start = len(provider_state().get("tool_history") or [])
        first = self.submit_agent_mcp_turn(key, title, objective)
        first_run_id = str(first.get("run_id"))
        first_message_id = self._agent_user_message_ids()[0]
        self.wait_agent_run_complete(first_run_id)
        call_one, result_one = self.wait_agent_tool_result(history_start)
        first_run = {"run_id": first_run_id, "message_id": first_message_id,
                     "tool_call": call_one, "tool_result": result_one}
        before = self.capture_agent_mcp(key=key, title=title, continuity="fresh",
                                        first_run=first_run, phase="pre-fault")

        # Fault: adapter process restart. The Gateway's trace collector for an
        # in-memory Product session ends with the adapter stream, so the Gateway
        # is reconnected to re-establish collection before the second delivery.
        docker("kill", ADAPTER_CONTAINER, check=False)
        docker("start", ADAPTER_CONTAINER)
        wait_healthy(ADAPTER_CONTAINER)
        docker("restart", GATEWAY_CONTAINER, timeout=120)
        wait_healthy(GATEWAY_CONTAINER)
        continuity_after = continuity_of(self.agent_runtime_session_id)
        self.ack_terminals(self.agent_runtime_session_id)
        history_start_2 = len(provider_state().get("tool_history") or [])
        second = self.submit_agent_mcp_turn(key, title, objective)
        second_run_id = str(second.get("run_id"))
        second_message_id = self._agent_user_message_ids()[-1]
        self.wait_agent_run_complete(second_run_id)
        call_two, result_two = self.wait_agent_tool_result(history_start_2)
        second_run = {"run_id": second_run_id, "message_id": second_message_id,
                      "tool_call": call_two, "tool_result": result_two}
        after = self.capture_agent_mcp(key=key, title=title, continuity=continuity_after,
                                       first_run=first_run, second_run=second_run, phase="post-fault")
        after["_second_delivery_run_id"] = second_run_id
        return self.finalize("agent-mcp-domain-at-most-once", before, after,
                             "docs/evidence/d15/d15-runtime/agent-mcp-domain-at-most-once.v5.json")

    def finalize(self, scenario_id: str, before: dict, after: dict, evidence: str) -> dict:
        capture_errors = list(before.get("capture_errors") or []) + list(after.get("capture_errors") or [])
        ok = before.get("capture_ok") is True and after.get("capture_ok") is True and not capture_errors
        return {"id": scenario_id, "result": "PASS" if ok else "FAIL", "fault_applied": True,
                "capture_errors": capture_errors, "before": before, "after": after,
                "evidence": [evidence]}

    # ---- scenarios ----
    def adapter_restart(self) -> dict:
        before = self.capture(self._current_continuity())
        docker("kill", ADAPTER_CONTAINER, check=False)
        docker("start", ADAPTER_CONTAINER)
        wait_healthy(ADAPTER_CONTAINER)
        after = self.capture(continuity_of(self.runtime_session_id), phase="post-fault")
        return self.finalize("adapter-process-restart", before, after,
                             "docs/evidence/d15/d15-runtime/adapter-process-restart.v3.json")

    def _start_product_run(self, content: str) -> dict:
        return self.client.call("POST", f"/v1/agent/sessions/{self.conversation_id}/turns",
                                {"content": content}, timeout=30)

    def generation_replacement(self) -> dict:
        before = self.capture(self._current_continuity())
        self.ack_terminals()
        set_provider_delay(30)
        submission = None
        try:
            submission = self._start_product_run("D15 generation replacement active run")
            time.sleep(3)
            active = self.adapter_session_status()
            self.client.call("POST", f"/v1/agent/sessions/{self.conversation_id}/cancel",
                             {"mode": "hard"}, timeout=20)
        finally:
            set_provider_delay(0)
        after = self.capture(continuity_of(self.runtime_session_id), phase="post-fault")
        after["_status_before_cancel"] = active
        after["_submission_run_id"] = (submission or {}).get("run_id")
        return self.finalize("generation-replacement", before, after,
                             "docs/evidence/d15/d15-runtime/generation-replacement.v3.json")

    def dsh_interruption(self) -> dict:
        before = self.capture(self._current_continuity())
        self.ack_terminals()
        set_provider_delay(30)
        submission = None
        try:
            submission = self._start_product_run("D15 DSH interruption active run")
            time.sleep(4)
            pids = adapter_dsh_pids()
            if not pids:
                return {"id": "dsh-process-interruption", "result": "BLOCKED", "fault_applied": False,
                        "not_run_reason": "no active DSH bundled-runtime child process was observable "
                                          "in /proc to interrupt (real DSH child not isolated)",
                        "before": before}
            active = self.adapter_session_status()
            for pid in pids:
                docker("exec", ADAPTER_CONTAINER, "sh", "-c", f"kill -9 {pid} || true", check=False)
            time.sleep(4)
        finally:
            set_provider_delay(0)
        wait_not_running()
        after = self.capture(continuity_of(self.runtime_session_id), phase="post-fault")
        after["_interrupted_pids"] = pids
        after["_status_before_interrupt"] = active
        after["_submission_run_id"] = (submission or {}).get("run_id")
        return self.finalize("dsh-process-interruption", before, after,
                             "docs/evidence/d15/d15-runtime/dsh-process-interruption.v3.json")

    def ack_terminals(self, session_id: str | None = None) -> None:
        """Acknowledge durable terminals so a new root is admitted (BYQ contract)."""
        session_id = session_id or self.runtime_session_id
        state = read_journal(session_id)
        context = state.get("context", {})
        module = lifecycle_module()
        for event in state.get("events", []):
            projected = module.project_lifecycle_event(
                event, context.get("session_id"), context.get("trace_id"))
            if not projected or projected.get("outcome") == "active":
                continue
            root = projected["root_run_id"]
            if root in state.get("terminal_acks", {}):
                continue
            try_http("POST", f"{ADAPTER}/internal/runtime/sessions/"
                     f"{session_id}/terminal-receipt",
                     {"receipt": module.lifecycle_receipt(projected)})

    def adapter_session_status(self) -> str:
        body = try_http("GET", f"{ADAPTER}/internal/runtime/sessions/"
                        f"{self.runtime_session_id}/continuation-qualification")
        return str(body.get("reason"))

    def gateway_reconnect(self) -> dict:
        before = self.capture(self._current_continuity())
        docker("restart", GATEWAY_CONTAINER, timeout=120)
        wait_healthy(GATEWAY_CONTAINER)
        detail = self.client.call("GET", f"/v1/agent/sessions/{self.conversation_id}")
        after = self.capture(continuity_of(self.runtime_session_id), phase="post-fault")
        after["_gateway_detail_messages"] = len(detail.get("messages", []))
        return self.finalize("gateway-disconnect-reconnect", before, after,
                             "docs/evidence/d15/d15-runtime/gateway-disconnect-reconnect.v3.json")

    def executor_takeover(self) -> dict:
        before = self.capture(self._current_continuity())
        result = json.loads(adapter_exec_python(
            "import json,sys;sys.path.insert(0,'/app');from app import executor_identity as e;"
            "from pathlib import Path;"
            "print(json.dumps(e.takeover(Path('" + evidence_root() +
            "'),reason='D15 runtime qualification executor takeover',operator='d15-runtime-qual')))"))
        after = self.capture(self._current_continuity(), phase="post-fault")
        after["_takeover"] = {k: result.get(k) for k in
                              ("previous_epoch", "executor_epoch", "reason", "database_rows_modified", "audit_path")}
        after["executor_epoch"] = result.get("executor_epoch", after.get("executor_epoch"))
        return self.finalize("executor-takeover", before, after,
                             "docs/evidence/d15/d15-runtime/executor-takeover.v3.json")

    def _current_continuity(self) -> str:
        body = try_http("GET", f"{ADAPTER}/internal/runtime/operations")
        # continuity is per-session; a live READY generation reports reattached.
        qualification = try_http("GET", f"{ADAPTER}/internal/runtime/sessions/"
                                  f"{self.runtime_session_id}/continuation-qualification")
        if qualification.get("reason") == "session_missing":
            return "rehydrated"
        return "reattached"


def stack_up() -> None:
    compose("up", "-d", "--wait", "--wait-timeout", "600")
    for name in ALL_CONTAINERS:
        wait_healthy(name)


def stack_down() -> dict:
    before = docker("ps", "-aq", "--filter", f"name=byq-d15-runtime").split()
    compose("down", "--volumes", check=False)
    time.sleep(2)
    remaining = docker("ps", "-aq", "--filter", f"name=byq-d15-runtime").split()
    networks = docker("network", "ls", "--filter", "name=byq-d15-runtime", "-q").split()
    volumes = docker("volume", "ls", "--filter", "name=byq-d15-runtime", "-q").split()
    return {"containers_before": len(before), "containers_remaining": len(remaining),
            "networks_remaining": len(networks), "volumes_remaining": len(volumes)}


def preflight() -> dict:
    ids = docker("ps", "-aq", "--filter", "name=byq-d15-runtime").split()
    if len(ids) != len(ALL_CONTAINERS):
        raise QualError(f"expected {len(ALL_CONTAINERS)} isolated containers, saw {len(ids)}")
    inspect = json.loads(docker("inspect", *ids))
    names = {item["Name"].lstrip("/") for item in inspect}
    if names != set(ALL_CONTAINERS):
        raise QualError(f"unexpected isolated containers: {sorted(names)}")
    for item in inspect:
        if item["HostConfig"].get("Privileged"):
            raise QualError("privileged container detected")
        for port, bindings in (item["NetworkSettings"].get("Ports") or {}).items():
            for binding in bindings or []:
                if binding.get("HostIp") != "127.0.0.1":
                    raise QualError(f"non-loopback published port: {item['Name']} {port}")
    info = json.loads(docker("inspect", ADAPTER_CONTAINER))[0]
    env = dict(kv.split("=", 1) for kv in info["Config"]["Env"] if "=" in kv)
    candidate = env.get("BYQ_DSH_COMPATIBILITY_RELEASE")
    if candidate != "dsh-0.1.5rc1":
        raise QualError(f"runtime-adapter is not pinned to the candidate: {candidate!r}")
    images = {item["Name"].lstrip("/"): item["Image"] for item in inspect}
    return {"containers": len(ids), "candidate": candidate,
            "adapter_image": info["Image"], "network": "byq-d15-runtime_d15_internal",
            "images": images}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-up", action="store_true", help="reuse a running isolated stack")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--out", type=Path, default=HERE.parents[2] / "docs/evidence/d15/d15-runtime/observations.v5.json")
    args = parser.parse_args(argv)

    observations: dict = {
        "schema_version": "byq-d15-runtime-observations.v5",
        "evidence_class": "runtime-isolated-stack",
        "generated_at": now(),
        "candidate": {"release": "dsh-0.1.5rc1", "python_sdk": "0.1.5rc1",
                      "runtime_bin": "0.1.5rc1",
                      "selector_env": "BYQ_DSH_COMPATIBILITY_RELEASE"},
        "llm": {"class": "scripted-keyless", "real_llm_quality": False,
                "note": "Keyless deterministic loopback provider; service-boundary runtime-continuity "
                        "evidence, not real-LLM-quality semantic evidence."},
        "execution_model": {
            "provider": "scripted-keyless",
            "agent_mcp_tool_calls": 0,
            "action_origin": "product-api-manual + agent-mcp",
            "note": "The research goal, persistent approval and paper-pool side effect are manual "
                    "Product API actions. The agent-mcp-domain-at-most-once scenario additionally "
                    "drives a real scripted-provider tool call through the runtime-adapter -> MCP -> "
                    "Backend and verifies one domain side effect across an adapter restart.",
        },
        "stack": {"compose_project": PROJECT, "candidate_image": "byq-d15-runtime-candidate:local",
                  "isolated_session_root": SESSION_ROOT,
                  "ports": {"gateway": 18100, "backend": 18000, "mcp": 18300, "adapter": 18400}},
        "scenarios": [],
        "cleanup": None,
    }
    if not args.no_up:
        stack_up()
    observations["preflight"] = preflight()
    client = ProductClient("d15admin", "D15AdminPass123")
    qualification = Qualification(client)
    qualification.create_domain_state()
    qualification.create_session()
    qualification.submit_goal()
    qualification.wait_result()
    wait_trace_result(qualification.runtime_session_id, str(qualification.artifacts["run_id"]))
    observations["domain_artifacts"] = {k: v for k, v in qualification.artifacts.items()
                                       if k != "pool_body"}
    try:
        observations["scenarios"].append(qualification.adapter_restart())
        observations["scenarios"].append(qualification.gateway_reconnect())
        observations["scenarios"].append(qualification.generation_replacement())
        observations["scenarios"].append(qualification.dsh_interruption())
        observations["scenarios"].append(qualification.agent_mcp_domain_at_most_once())
        observations["scenarios"].append(qualification.executor_takeover())
        observations["execution_model"]["agent_mcp_tool_calls"] = int(
            provider_state().get("tool_calls_emitted") or 0)
    finally:
        if not args.no_cleanup:
            observations["cleanup"] = stack_down()
    observations["scenarios"].append({
        "id": "host-reboot", "result": "NOT_RUN",
        "not_run_reason": "not executed: rebooting the maintainer host is not authorized and a "
                          "container restart is not equivalent to a host reboot",
    })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(observations, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scenarios_dir = args.out.parent / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    for scenario in observations["scenarios"]:
        (scenarios_dir / f"{scenario['id']}.v5.json").write_text(
            json.dumps({"schema_version": "byq-d15-runtime-scenario.v5",
                        "evidence_class": observations["evidence_class"],
                        "candidate": observations["candidate"], "llm": observations["llm"],
                        "execution_model": observations["execution_model"],
                        "generated_at": observations["generated_at"], **scenario},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out.parent / "stack.v5.json").write_text(json.dumps(
        {"schema_version": "byq-d15-runtime-stack.v5", "generated_at": observations["generated_at"],
         "preflight": observations["preflight"], "domain_artifacts": observations["domain_artifacts"],
         "execution_model": observations["execution_model"],
         "cleanup": observations.get("cleanup")}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"observations": str(args.out),
                      "scenarios": [(s["id"], s["result"]) for s in observations["scenarios"]],
                      "cleanup": observations.get("cleanup")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
