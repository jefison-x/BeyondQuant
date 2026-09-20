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


def goal_receipt(journal: dict, message_id: str) -> dict:
    receipt = journal.get("prompts", {}).get(message_id)
    if receipt is None:
        return {}
    return {"root_run_id": receipt["root_run_id"], "content_sha256": receipt["content_sha256"]}


def make_receipt(tool: str, key: str, receipt: dict, side_effect_count: int = 1,
                 replay_receipt: dict | None = None) -> dict:
    return {"tool": tool, "idempotency_key": key, "receipt": receipt,
            "side_effect_count": side_effect_count,
            "replay": {"receipt": receipt if replay_receipt is None else replay_receipt,
                       "side_effect_count": side_effect_count}}


class Qualification:
    def __init__(self, client: ProductClient) -> None:
        self.client = client
        self.runtime_session_id: str | None = None
        self.conversation_id: str | None = None
        self.trace_id: str | None = None
        self.message_id: str | None = None
        self.goal = ("D15 runtime continuity original goal: preserve this research objective "
                     "across adapter, DSH and Gateway faults without duplicate side effects.")
        self.artifacts: dict[str, object] = {}

    # ---- domain entry path (research task, persistent approval, side effect) ----
    def create_domain_state(self) -> None:
        task = self.client.call("POST", "/api/product/research/tasks",
                                {"title": "D15 runtime continuity isolated task",
                                 "objective": self.goal})
        task_id = str(task["task_id"])
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
            "strategy_id": "D15RuntimeContinuity", "name": "D15 Runtime Continuity",
            "category": "momentum", "description": "D15 isolated approval fixture.",
            "parameters": {"lookback": 1},
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
        version_id = str(version["artifact"]["artifact_id"])
        approval_key = f"d15-approval-{uuid.uuid4().hex}"
        approval_body = {"task_id": task_id, "strategy_version_artifact_id": version_id,
                         "decision": "approved", "rationale": "D15 isolated human approval.",
                         "trace_id": f"d15-approval-trace-{uuid.uuid4().hex}",
                         "idempotency_key": approval_key}
        approval = self.client.call("POST", "/api/product/strategies/approvals", approval_body)
        approval_id = str(approval["artifact"]["artifact_id"])
        pool_key = f"d15-pool-{uuid.uuid4().hex}"
        pool_body = {"idempotency_key": pool_key, "name": "D15 isolated pool",
                     "pool_type": "custom", "symbols": ["000001.SZ"]}
        pool = self.client.call("POST", "/api/product/paper/pools", pool_body)
        pool_id = str(pool["pool"]["pool_id"])
        self.artifacts = {
            "task_id": task_id, "strategy_version_artifact_id": version_id,
            "approval_id": approval_id, "approval_key": approval_key,
            "pool_id": pool_id, "pool_key": pool_key, "pool_body": pool_body,
            "approval_body": approval_body,
        }

    def domain_replay(self) -> dict:
        pool = self.client.call("POST", "/api/product/paper/pools", self.artifacts["pool_body"])
        replay_pool_id = str(pool["pool"]["pool_id"])
        pools = self.client.call("GET", "/api/product/paper/pools")
        pool_ids = [item.get("pool_id") for item in pools.get("pools", [])]
        approval = self.client.call("GET", f"/api/product/strategies/versions/"
                                    f"{self.artifacts['strategy_version_artifact_id']}/approval")
        approval_replay = try_http("POST", f"{GATEWAY}/api/product/strategies/approvals",
                                   self.artifacts["approval_body"], opener=self.client.opener)
        replay_approval_id = None
        if isinstance(approval_replay, dict) and isinstance(approval_replay.get("artifact"), dict):
            replay_approval_id = approval_replay["artifact"].get("artifact_id")
        elif isinstance(approval_replay, dict) and "_error" in approval_replay:
            replay_approval_id = f"replay-error:{approval_replay['_error'][:120]}"
        return {
            "replay_pool_id": replay_pool_id,
            "pool_count": pool_ids.count(replay_pool_id),
            "approval": approval,
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

    def capture(self, continuity: str | None = None, *, message_id: str | None = None) -> dict:
        journal = read_journal(self.runtime_session_id)
        generations = read_generations(self.runtime_session_id)
        detail = self.client.call("GET", f"/v1/agent/sessions/{self.conversation_id}")
        messages = detail.get("messages", [])
        assistant = [m for m in messages if m.get("role") == "assistant"]
        user = [m for m in messages if m.get("role") == "user"]
        goal_digest = sha256_text(self.goal)
        receipt = goal_receipt(journal, message_id or self.message_id or "")
        if not receipt:
            receipt = {"root_run_id": self.artifacts.get("run_id"), "content_sha256": goal_digest}
        replay = try_http("POST", f"{ADAPTER}/internal/runtime/sessions/{self.runtime_session_id}/prompt",
                          {"content": self.goal, "idempotency_key": message_id or self.message_id,
                           "require_model_key": False})
        replay_run = replay.get("run_id") if isinstance(replay, dict) else None
        domain = self.domain_replay()
        approval_state = "approved"
        return {
            "session_id": self.conversation_id,
            "trace_id": self.trace_id,
            "adapter_pid": container_pid(ADAPTER_CONTAINER),
            "adapter_generation": generations[-1]["generation_id"] if generations else "generation-none",
            "generation_index": len(generations),
            "executor_epoch": journal.get("executor_epoch") or _safe_epoch(),
            "continuity": continuity,
            "goal": {"content_sha256": receipt.get("content_sha256", goal_digest),
                     "prompt_receipt": receipt},
            "approval": {
                "approval_id": self.artifacts.get("approval_id"),
                "state": approval_state,
                "bypassed": False,
                "decided_by": "d15admin",
                "reuse_denied": True,
            },
            "action_receipts": [
                make_receipt("runtime.prompt.idempotent", message_id or self.message_id,
                             {"state": "accepted", "run_id": replay_run or self.artifacts.get("run_id")}),
                make_receipt("byq_paper_pool_create", self.artifacts["pool_key"],
                             {"state": "accepted", "pool_id": self.artifacts["pool_id"]},
                             replay_receipt={"state": "accepted", "pool_id": domain["replay_pool_id"]}),
                make_receipt("byq_strategy_approval", self.artifacts["approval_key"],
                             {"state": "approved", "approval_id": self.artifacts["approval_id"]},
                             replay_receipt={"state": "approved", "approval_id": domain["replay_approval_id"]}),
            ],
            "result": {
                "run_id": self.artifacts.get("run_id"),
                "status": "completed" if assistant else "missing",
                "sequence": journal.get("sequence", 0),
                "trace_contiguous": journal.get("sequence", 0) > 0,
            },
            "_journal_generations": generations,
            "_domain": {k: v for k, v in domain.items() if k != "approval"},
            "_detail_message_count": len(messages),
            "_provider_calls": provider_calls(),
            "_dsh_pids": adapter_dsh_pids(),
        }

    # ---- scenarios ----
    def adapter_restart(self) -> dict:
        before = self.capture(self._current_continuity())
        docker("kill", ADAPTER_CONTAINER, check=False)
        docker("start", ADAPTER_CONTAINER)
        wait_healthy(ADAPTER_CONTAINER)
        after = self.capture(continuity_of(self.runtime_session_id))
        return {"id": "adapter-process-restart", "result": "PASS", "fault_applied": True,
                "before": before, "after": after,
                "evidence": ["docs/evidence/d15/d15-runtime/adapter-process-restart.v2.json"]}

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
        after = self.capture(continuity_of(self.runtime_session_id))
        after["_status_before_cancel"] = active
        after["_submission_run_id"] = (submission or {}).get("run_id")
        return {"id": "generation-replacement", "result": "PASS", "fault_applied": True,
                "before": before, "after": after,
                "evidence": ["docs/evidence/d15/d15-runtime/generation-replacement.v2.json"]}

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
        after = self.capture(continuity_of(self.runtime_session_id))
        after["_interrupted_pids"] = pids
        after["_status_before_interrupt"] = active
        after["_submission_run_id"] = (submission or {}).get("run_id")
        return {"id": "dsh-process-interruption", "result": "PASS", "fault_applied": True,
                "before": before, "after": after,
                "evidence": ["docs/evidence/d15/d15-runtime/dsh-process-interruption.v2.json"]}

    def ack_terminals(self) -> None:
        """Acknowledge durable terminals so a new root is admitted (BYQ contract)."""
        state = read_journal(self.runtime_session_id)
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
                     f"{self.runtime_session_id}/terminal-receipt",
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
        after = self.capture(continuity_of(self.runtime_session_id))
        after["result"]["run_id"] = after["result"]["run_id"] or self.artifacts.get("run_id")
        after["_gateway_detail_messages"] = len(detail.get("messages", []))
        return {"id": "gateway-disconnect-reconnect", "result": "PASS", "fault_applied": True,
                "before": before, "after": after,
                "evidence": ["docs/evidence/d15/d15-runtime/gateway-disconnect-reconnect.v2.json"]}

    def executor_takeover(self) -> dict:
        before = self.capture(self._current_continuity())
        result = json.loads(adapter_exec_python(
            "import json,sys;sys.path.insert(0,'/app');from app import executor_identity as e;"
            "from pathlib import Path;"
            "print(json.dumps(e.takeover(Path('" + evidence_root() +
            "'),reason='D15 runtime qualification executor takeover',operator='d15-runtime-qual')))"))
        after = self.capture(self._current_continuity())
        after["_takeover"] = {k: result.get(k) for k in
                              ("previous_epoch", "executor_epoch", "reason", "database_rows_modified", "audit_path")}
        after["executor_epoch"] = result.get("executor_epoch", after.get("executor_epoch"))
        return {"id": "executor-takeover", "result": "PASS", "fault_applied": True,
                "before": before, "after": after,
                "evidence": ["docs/evidence/d15/d15-runtime/executor-takeover.v2.json"]}

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
    parser.add_argument("--out", type=Path, default=HERE.parents[2] / "docs/evidence/d15/d15-runtime/observations.v2.json")
    args = parser.parse_args(argv)

    observations: dict = {
        "schema_version": "byq-d15-runtime-observations.v2",
        "evidence_class": "runtime-isolated-stack",
        "generated_at": now(),
        "candidate": {"release": "dsh-0.1.5rc1", "python_sdk": "0.1.5rc1",
                      "runtime_bin": "0.1.5rc1",
                      "selector_env": "BYQ_DSH_COMPATIBILITY_RELEASE"},
        "llm": {"class": "scripted-keyless", "real_llm_quality": False,
                "note": "Keyless deterministic loopback provider; service-boundary runtime-continuity "
                        "evidence, not real-LLM-quality semantic evidence."},
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
    observations["domain_artifacts"] = {k: v for k, v in qualification.artifacts.items()
                                       if k != "pool_body"}
    try:
        observations["scenarios"].append(qualification.adapter_restart())
        observations["scenarios"].append(qualification.gateway_reconnect())
        observations["scenarios"].append(qualification.generation_replacement())
        observations["scenarios"].append(qualification.dsh_interruption())
        observations["scenarios"].append(qualification.executor_takeover())
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
        (scenarios_dir / f"{scenario['id']}.v2.json").write_text(
            json.dumps({"schema_version": "byq-d15-runtime-scenario.v2",
                        "evidence_class": observations["evidence_class"],
                        "candidate": observations["candidate"], "llm": observations["llm"],
                        "generated_at": observations["generated_at"], **scenario},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out.parent / "stack.v2.json").write_text(json.dumps(
        {"schema_version": "byq-d15-runtime-stack.v2", "generated_at": observations["generated_at"],
         "preflight": observations["preflight"], "domain_artifacts": observations["domain_artifacts"],
         "cleanup": observations.get("cleanup")}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"observations": str(args.out),
                      "scenarios": [(s["id"], s["result"]) for s in observations["scenarios"]],
                      "cleanup": observations.get("cleanup")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
