#!/usr/bin/env python3
"""Staged Product/Gateway evidence for an Agent-bound real-data Golden B.

Stages: prepare, agent-a-version, agent-a-run, agent-b-version, agent-b-run.
One Product Agent session creates its own conversation-bound ResearchTask and
versions A/B through BYQ MCP. Root approves each exact version between turns.
This script never starts services, syncs data, calls TuShare, or reads a DB.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
SCOPE = "byq-dev-ea551690f4"
WORKSPACE = "workspace_9f180f427ac14bb7b5ccb35c4c59d1c8"
POOL_SNAPSHOT = "stock_pool_snapshot_844b57d3fccacf0004738c9dfa428fd7cf854460cb5b11f42c4ff54cb6725222"
SYMBOL = "000001.SZ"
DATE = "2024-01-02"
DATE_COMPACT = "20240102"
THRESHOLD_A = 9.20
THRESHOLD_B = 9.22
SCHEMA = "phase15-golden-b-bound-manifest.v1"
JOB_RE = re.compile(r"\bbacktest_[0-9a-f]{32}\b")
TASK_RE = re.compile(r"\bbacktesttask_[0-9a-f]{32}\b")
RESEARCH_TASK_RE = re.compile(r"\btask_[0-9a-f]{32}\b")
ARTIFACT_RE = re.compile(r"\bartifact_[0-9a-f]{32}\b")
AGENT_TIMEOUT = 900
JOB_TIMEOUT = 900


class EvidenceError(RuntimeError):
    pass


def need(ok: object, message: str) -> None:
    if not ok:
        raise EvidenceError(message)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def manifest_path() -> Path:
    value = Path(os.environ.get("BYQ_PHASE15_GOLDEN_B_BOUND_MANIFEST", str(ROOT / ".phase15-golden-b-bound.json"))).expanduser()
    if not value.is_absolute():
        value = ROOT / value
    resolved = value.resolve(strict=False)
    need(resolved.is_relative_to(ROOT.resolve()), "manifest must remain inside this worktree")
    need(not value.is_symlink(), "manifest path must not be a symlink")
    return resolved


def write_manifest(path: Path, data: dict[str, object]) -> None:
    need(not path.is_symlink(), "manifest path became a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(path: Path, data: dict[str, object]) -> None:
    data["updated_at"] = now()
    write_manifest(path, data)


def load(path: Path) -> dict[str, object]:
    need(path.is_file() and not path.is_symlink(), "run prepare first; no safe bound Golden B manifest")
    need(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, "manifest must be private to this user")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError("Golden B manifest is unreadable") from error
    need(isinstance(data, dict) and data.get("schema_version") == SCHEMA, "manifest schema is invalid")
    need(data.get("scope") == SCOPE and data.get("workspace_id") == WORKSPACE, "manifest scope/workspace mismatch")
    return data


class Product:
    def __init__(self, origin: str, username: str, password: str) -> None:
        self.origin = origin
        self.username = username
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login = self.request("POST", "/api/auth/login", {"username": username, "password": password}, 200)
        user = login.get("user")
        need(isinstance(user, dict) and user.get("username") == username and user.get("role") == "admin",
             "Product login is not the scoped bootstrap admin")

    def request(self, method: str, path: str, payload: dict[str, object] | None = None,
                expected: int = 200, headers: dict[str, str] | None = None,
                timeout: float = 30.0) -> dict[str, object]:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        outgoing_headers = dict(headers or {})
        if body is not None:
            outgoing_headers["content-type"] = "application/json"
        outgoing = Request(self.origin + path, data=body, headers=outgoing_headers, method=method)
        try:
            with self.opener.open(outgoing, timeout=timeout) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        except (URLError, TimeoutError) as error:
            raise EvidenceError(f"request outcome unknown: {method} {path}; do not replay") from error
        need(status == expected, f"Product {method} {path} returned HTTP {status}")
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EvidenceError(f"Product response is not JSON: {method} {path}") from error
        need(isinstance(value, dict), f"Product response is not an object: {method} {path}")
        return value

    def api(self, method: str, path: str, payload: dict[str, object] | None = None,
            expected: int = 200, headers: dict[str, str] | None = None,
            timeout: float = 30.0) -> dict[str, object]:
        return self.request(method, "/api/product" + path, payload, expected, headers, timeout)

    def verify(self, username: str) -> None:
        me = self.request("GET", "/api/auth/me")
        workspace = me.get("workspace")
        need(me.get("subject") == username and me.get("role") == "admin"
             and isinstance(workspace, dict) and workspace.get("workspace_id") == WORKSPACE
             and workspace.get("kind") == "personal" and workspace.get("role") == "owner",
             "authenticated Product identity is outside the exact disposable Workspace")


def configure(stage: str) -> tuple[dict[str, str], Product, Path]:
    need(os.environ.get("BYQ_PHASE15_EXTERNAL_CALLS_AUTHORIZED") == "1",
         "set BYQ_PHASE15_EXTERNAL_CALLS_AUTHORIZED=1 only for the explicitly authorized Agent turns")
    if stage == "agent-b-run":
        need(os.environ.get("BYQ_PHASE15_GOLDEN_B_FOUR_TURN_AUTHORIZED") == "1",
             "the fourth Golden B Agent turn requires explicit authorization")
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.dev.environment import local_env
        values = local_env()
    except Exception as error:
        raise EvidenceError("local_env rejected this worktree") from error
    need(values.get("BYQ_DEV_SCOPE") == SCOPE, "wrong BYQ_DEV_SCOPE")
    need(values.get("BYQ_GATEWAY_BIND") == "127.0.0.1:0", "Gateway must use dynamic loopback binding")
    need(os.environ.get("BYQ_PHASE15_EXPECTED_WORKSPACE_ID") == WORKSPACE,
         "set the exact BYQ_PHASE15_EXPECTED_WORKSPACE_ID")
    origin = os.environ.get("BYQ_REAL_BASE_URL", "").rstrip("/")
    parsed = urlsplit(origin)
    need(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port
         and parsed.username is None and parsed.password is None and parsed.path in {"", "/"}
         and not parsed.query and not parsed.fragment, "BYQ_REAL_BASE_URL must be dynamic loopback Gateway")
    need(os.environ.get("BYQ_PHASE15_DATA_WORKER_STEP") == "stopped",
         "Data Worker must remain stopped; this journey reuses persisted 20240102 data")
    username = values.get("BYQ_BOOTSTRAP_ADMIN_USERNAME", "admin")
    password = values.get("BYQ_BOOTSTRAP_ADMIN_PASSWORD", "")
    need(bool(username and password), "local environment has no bootstrap admin identity")
    client = Product(origin, username, password)
    client.verify(username)
    return values, client, manifest_path()


def once(client: Product, path: Path, data: dict[str, object], key: str, method: str,
         route: str, payload: dict[str, object], expected: int,
         headers: dict[str, str] | None = None) -> dict[str, object]:
    if data.get(key):
        raise EvidenceError(f"{key} was already attempted without a saved receipt; reconcile manually, do not replay")
    data[key] = True
    save(path, data)
    result = client.api(method, route, payload, expected, headers)
    data[key.removesuffix("_attempted")] = result
    save(path, data)
    return result


def strategy(strategy_id: str, threshold: float) -> dict[str, object]:
    return {
        "strategy_id": strategy_id, "name": "Phase 15 Golden B threshold strategy",
        "category": "momentum", "description": "One-session deterministic close threshold; no benchmark.",
        "parameters": {"threshold": threshold},
        "parameter_schema": {"threshold": {"type": "number", "minimum": 0, "maximum": 100000}},
        "source_type": "python_script",
        "script": (
            "class CustomStrategy:\n"
            "    def generate_signals(self, data, parameters=None):\n"
            "        threshold = 9.20 if parameters is None else parameters.get('threshold', 9.20)\n"
            "        result = {}\n"
            "        for symbol in data.index.get_level_values('symbol').unique():\n"
            "            close = data.xs(symbol, level='symbol')['close']\n"
            "            result[str(symbol)] = (close > threshold).fillna(False).astype(int)\n"
            "        return result\n"
        ),
    }


def same_strategy_snapshot(actual: object, expected: dict[str, object]) -> bool:
    if not isinstance(actual, dict) or not isinstance(actual.get("script"), str):
        return False
    normalized = dict(actual)
    normalized["script"] = normalized["script"].rstrip("\n")
    reference = dict(expected)
    reference["script"] = str(reference["script"]).rstrip("\n")
    return normalized == reference


def artifacts(client: Product) -> list[dict[str, object]]:
    values = client.api("GET", "/research/artifacts").get("artifacts")
    need(isinstance(values, list) and all(isinstance(item, dict) for item in values),
         "Product Artifact projection is invalid")
    return values


def exact_artifact(client: Product, artifact_id: str, kind: str) -> dict[str, object]:
    found = [item for item in artifacts(client) if item.get("artifact_id") == artifact_id]
    need(len(found) == 1 and found[0].get("kind") == kind and found[0].get("status") == "validated"
         and found[0].get("workspace_id") == WORKSPACE, f"exact {kind} Artifact is absent or invalid")
    return found[0]


def assert_approval(client: Product, data: dict[str, object], label: str) -> str:
    version_id = str(data.get(f"version_{label}_artifact_id", ""))
    matches = [item for item in artifacts(client) if item.get("kind") == "strategy_approval"
               and isinstance(item.get("content"), dict)
               and item["content"].get("strategy_version_artifact_id") == version_id
               and item["content"].get("decision") == "approved"
               and item.get("task_id") == data.get("task_id")]
    need(len(matches) == 1, f"Root must approve the exact StrategyVersion {version_id} through Product API")
    data[f"approval_{label}_artifact_id"] = matches[0]["artifact_id"]
    save(manifest_path(), data)
    return str(matches[0]["artifact_id"])


def assert_readiness(client: Product) -> None:
    value = client.api("POST", "/data-center/readiness", {
        "symbols": [SYMBOL], "start_date": DATE_COMPACT, "end_date": DATE_COMPACT, "use_case": "backtest",
    })
    scope, summary = value.get("scope"), value.get("summary")
    need(value.get("schema_version") == "data-readiness-product.v1" and value.get("verdict") == "usable"
         and value.get("checked_against") == "persisted_byq" and isinstance(scope, dict)
         and scope.get("selection_type") == "explicit" and scope.get("symbols") == [SYMBOL]
         and scope.get("start_date") == DATE_COMPACT and scope.get("end_date") == DATE_COMPACT
         and scope.get("use_case") == "backtest" and isinstance(summary, dict)
         and summary.get("missing_items") == 0, "persisted one-symbol/one-session readiness is not usable")


def prepare(client: Product, path: Path) -> dict[str, object]:
    """Read-only scope checks; the Agent creates the ResearchTask in turn 1."""
    need(not path.exists(), "Golden B manifest already exists; continue its recorded stage")
    run_key = "p15b-" + secrets.token_hex(8)
    data: dict[str, object] = {"schema_version": SCHEMA, "run_key": run_key, "scope": SCOPE,
                               "workspace_id": WORKSPACE, "owner_username": client.username,
                               "strategy_id": "Phase15GoldenB" + run_key[-8:],
                               "created_at": now(), "stage": "prepared"}
    write_manifest(path, data)
    assert_readiness(client)
    pools = client.api("GET", "/paper/pools?limit=100&offset=0").get("pools")
    need(isinstance(pools, list), "Product pool catalog is invalid")
    matches = [p for p in pools if isinstance(p, dict) and p.get("workspace_id") == WORKSPACE
               and p.get("status") == "active" and isinstance(p.get("snapshot"), dict)
               and p["snapshot"].get("snapshot_id") == POOL_SNAPSHOT]
    need(len(matches) == 1 and isinstance(matches[0].get("pool_id"), str),
         "exact frozen pool snapshot is unavailable or ambiguous")
    detail = client.api("GET", f"/paper/pools/{matches[0]['pool_id']}?include_members=true").get("pool")
    need(isinstance(detail, dict) and detail.get("workspace_id") == WORKSPACE
         and detail.get("status") == "active" and detail.get("symbols") == [SYMBOL]
         and isinstance(detail.get("snapshot"), dict)
         and detail["snapshot"].get("snapshot_id") == POOL_SNAPSHOT
         and [m.get("symbol") for m in detail["snapshot"].get("members", []) if isinstance(m, dict)] == [SYMBOL],
         "exact frozen pool detail does not contain only 000001.SZ")
    data["pool_id"] = matches[0]["pool_id"]
    data["stage"] = "prepared"
    save(path, data)
    return data


def session_body(client: Product, data: dict[str, object]) -> dict[str, object]:
    session_id = str(data.get("session_id", ""))
    need(bool(session_id), "Product Agent session ID is missing")
    return client.request("GET", f"/v1/agent/sessions/{session_id}")


def assistant_messages(body: dict[str, object]) -> list[str]:
    messages = body.get("messages")
    need(isinstance(messages, list), "Product Agent transcript is malformed")
    return [str(item.get("content", "")) for item in messages
            if isinstance(item, dict) and item.get("role") == "assistant"]


def turn_activity_events(body: dict[str, object], after_sequence: int) -> list[dict[str, object]]:
    events = body.get("events")
    need(isinstance(events, list), "Product Agent normalized trace is missing")
    return [item for item in events if isinstance(item, dict) and item.get("kind") == "agent.activity"
            and isinstance(item.get("payload"), dict)
            and isinstance(item.get("sequence"), int) and item["sequence"] > after_sequence
            and item["payload"].get("label") != "理解请求"]


def check_turn_activities(events: list[dict[str, object]], allowed: set[str], exact_once: set[str],
                          waiting_allowed: set[str] = frozenset()) -> None:
    counts: dict[str, dict[str, int]] = {}
    for event in events:
        payload = event.get("payload")
        need(isinstance(payload, dict), "normalized Agent activity payload is invalid")
        label, state = payload.get("label"), payload.get("state")
        need(isinstance(label, str) and label in allowed,
             "Agent called a capability outside this turn's approved label set")
        need(state not in {"failed", "unknown"}, "Agent MCP activity failed or has an unknown outcome")
        need(state in {"started", "completed", "waiting"}, "Agent MCP activity has an unknown state")
        need(state != "waiting" or label in waiting_allowed, "Agent MCP activity waited unexpectedly")
        state_counts = counts.setdefault(label, {"started": 0, "terminal": 0})
        if state == "started":
            state_counts["started"] += 1
        else:
            state_counts["terminal"] += 1
    need(bool(counts), "Agent turn has no normalized MCP activity")
    for label, value in counts.items():
        need(value["started"] == value["terminal"], f"Agent activity {label} lacks a matched terminal event")
    for label in exact_once:
        need(counts.get(label) == {"started": 1, "terminal": 1},
             f"Agent must call {label} exactly once and complete it once")


def registered_run(body: dict[str, object], after_sequence: int) -> bool:
    events = body.get("events")
    registrations = [item for item in events if isinstance(item, dict)
                     and item.get("kind") == "agent.run.registration"
                     and isinstance(item.get("sequence"), int)
                     and item["sequence"] > after_sequence] if isinstance(events, list) else []
    return len(registrations) == 1


def ensure_product_session(client: Product, path: Path, data: dict[str, object]) -> None:
    if data.get("session_id"):
        need(data.get("session_trace_id"), "Product Agent trace ID is missing")
        return
    need(not data.get("session_create_attempted"),
         "Product session creation outcome unknown; do not create another session")
    data["session_create_attempted"] = True
    save(path, data)
    created = client.request("POST", "/v1/agent/sessions", expected=201)
    session_id, trace_id = created.get("session_id"), created.get("trace_id")
    need(isinstance(session_id, str) and isinstance(trace_id, str) and trace_id,
         "Product did not return exact session and trace identities")
    data["session_id"] = session_id
    data["session_trace_id"] = trace_id
    save(path, data)


def turn(client: Product, path: Path, data: dict[str, object], number: int, prompt: str,
         answer_pattern: re.Pattern[str]) -> tuple[list[str], str, dict[str, object], list[dict[str, object]], bool]:
    key = f"turn_{number}"
    ensure_product_session(client, path, data)
    if not data.get(key + "_accepted"):
        if not data.get(key + "_attempted"):
            before = session_body(client, data)
            prior_events = before.get("events")
            need(isinstance(prior_events, list), "Product Agent trace is malformed before turn")
            data[key + "_assistant_count_before"] = len(assistant_messages(before))
            data[key + "_event_sequence_before"] = max(
                (item.get("sequence", 0) for item in prior_events if isinstance(item, dict)
                 and isinstance(item.get("sequence"), int)), default=0,
            )
            data[key + "_content"] = prompt
            data[key + "_attempted"] = True
            save(path, data)
            accepted = client.request("POST", f"/v1/agent/sessions/{data['session_id']}/turns",
                                      {"content": prompt}, 202)
            need(accepted.get("accepted") is True and accepted.get("session_id") == data["session_id"],
                 "Product did not accept this Agent turn")
            data[key + "_accepted"] = True
            save(path, data)
        else:
            body = session_body(client, data)
            messages = body.get("messages")
            seen = isinstance(messages, list) and any(isinstance(m, dict) and m.get("role") == "user"
                                                       and m.get("content") == data.get(key + "_content")
                                                       for m in messages)
            need(seen, "Agent turn outcome unknown; do not resubmit")
            data[key + "_accepted"] = True
            save(path, data)
    deadline = time.monotonic() + AGENT_TIMEOUT
    while time.monotonic() < deadline:
        body = session_body(client, data)
        messages = assistant_messages(body)
        before_count = int(data.get(key + "_assistant_count_before", 0))
        answer = "\n".join(messages[before_count:])
        matches = list(dict.fromkeys(answer_pattern.findall(answer)))
        if matches:
            sequence = int(data.get(key + "_event_sequence_before", 0))
            events = turn_activity_events(body, sequence)
            return matches, answer, body, events, registered_run(body, sequence)
        conversation = body.get("conversation")
        need(not isinstance(conversation, dict) or conversation.get("status") not in {"failed", "interrupted"},
             f"Agent turn {number} failed")
        time.sleep(1)
    raise EvidenceError(f"Agent turn {number} did not report the exact ID")


def expected_pool_and_job(client: Product, data: dict[str, object], job_id: str,
                          version_id: str, approval_id: str) -> dict[str, object]:
    body = client.api("GET", f"/backtests/{job_id}")
    job = body.get("job")
    need(isinstance(job, dict) and job.get("job_id") == job_id
         and job.get("workspace_id") == WORKSPACE and job.get("task_id") == data["task_id"]
         and job.get("strategy_version_artifact_id") == version_id
         and job.get("approval_artifact_id") == approval_id
         and job.get("stock_pool_snapshot_id") == POOL_SNAPSHOT,
         "BacktestJob owner, Task, Strategy, Approval, or Pool does not match this run")
    return job


def wait_backtest(client: Product, data: dict[str, object], job_id: str,
                  version_id: str, approval_id: str) -> dict[str, object]:
    deadline = time.monotonic() + JOB_TIMEOUT
    while time.monotonic() < deadline:
        job = expected_pool_and_job(client, data, job_id, version_id, approval_id)
        status = job.get("status")
        if status == "completed":
            artifact_id = job.get("result_artifact_id")
            need(isinstance(artifact_id, str), "completed BacktestJob has no result Artifact")
            artifact = exact_artifact(client, artifact_id, "backtest_result")
            content = artifact.get("content")
            need(artifact.get("task_id") == data["task_id"] and isinstance(content, dict)
                 and content.get("job_id") == job_id
                 and content.get("strategy_version_artifact_id") == version_id,
                 "Backtest result Artifact provenance mismatch")
            return job
        need(status in {"queued", "running"}, f"BacktestJob ended in unexpected state {status}")
        time.sleep(2)
    raise EvidenceError(f"BacktestJob {job_id} did not complete within {JOB_TIMEOUT}s")


def task_record(client: Product, task_id: str) -> dict[str, object]:
    body = client.api("GET", f"/research/tasks/{task_id}")
    task = body.get("task") if isinstance(body.get("task"), dict) else body
    need(isinstance(task, dict) and task.get("task_id") == task_id
         and task.get("workspace_id") == WORKSPACE, "Agent ResearchTask is absent or outside Workspace")
    return task


def agent_a_version(client: Product, path: Path, data: dict[str, object]) -> dict[str, object]:
    need(data.get("stage") in {"prepared", "agent_a_version_pending", "awaiting_approval_a"},
         "prepare must finish before Agent turn 1")
    expected = strategy(str(data["strategy_id"]), THRESHOLD_A)
    data["stage"] = "agent_a_version_pending"
    save(path, data)
    ensure_product_session(client, path, data)
    prompt = (
        "Use only BeyondQuant MCP; do not delegate, browse, call providers, or request data repair. "
        "This is turn 1 of one four-turn Product Agent conversation. Register a fresh byq_agent_run_start "
        "with role_id=quant_orchestrator and idempotency_key=" + str(data["run_key"]) + "-agent-a-version. "
        "In this original conversation, create exactly one ResearchTask with byq_research_task_create, "
        "then validate exactly the supplied strategy and create exactly one StrategyVersion with "
        "byq_strategy_validate and byq_strategy_version_create. Use the exact owner_principal, trace_id, "
        "task title/objective and idempotency keys below. Authorize and audit each strategy write using "
        "this turn's AgentRun. Do not request or record approval and do not start any backtest. "
        "Report exactly task_id and the StrategyVersion Artifact ID.\n"
        f"owner_principal={client.username}\nsession_trace_id={data['session_trace_id']}\n"
        f"task_title=Phase 15 Golden B {data['run_key']}\n"
        "task_objective=Compare two threshold-only StrategyVersions on persisted 000001.SZ data for 2024-01-02; no benchmark comparison.\n"
        f"task_create_idempotency_key={data['run_key']}-research-task\n"
        f"strategy_validate_trace_id={data['session_trace_id']}\n"
        f"strategy_validate_idempotency_key={data['run_key']}-a-validate\n"
        f"strategy_version_idempotency_key={data['run_key']}-a-version\n"
        "strategy_json=" + json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    matches, answer, _, events, registered = turn(client, path, data, 1, prompt, RESEARCH_TASK_RE)
    need(registered, "Agent A setup turn must register exactly one fresh AgentRun")
    need(len(matches) == 1, "Agent turn 1 must report exactly one ResearchTask ID")
    check_turn_activities(events, {"保存研究计划", "校验策略", "创建策略版本"},
                          {"保存研究计划", "校验策略", "创建策略版本"})
    task_id = matches[0]
    task = task_record(client, task_id)
    need(task.get("owner_principal") == client.username and task.get("conversation_id") == data.get("session_id")
         and task.get("trace_id") == data.get("session_trace_id"),
         "ResearchTask is not bound to this exact Product conversation and trace")
    reported_artifacts = set(ARTIFACT_RE.findall(answer))
    versions = [item for item in artifacts(client) if item.get("artifact_id") in reported_artifacts
                and item.get("kind") == "strategy_version" and item.get("status") == "validated"
                and item.get("task_id") == task_id and isinstance(item.get("content"), dict)
                and item["content"].get("strategy_id") == data["strategy_id"]
                and same_strategy_snapshot(item["content"].get("snapshot"), expected)]
    need(len(versions) == 1, "Agent turn 1 did not report exactly one matching threshold A StrategyVersion")
    version_id = str(versions[0]["artifact_id"])
    need(version_id in answer, "Agent turn 1 omitted its exact StrategyVersion Artifact ID")
    data.update({"task_id": task_id, "version_a_artifact_id": version_id,
                 "stage": "awaiting_approval_a"})
    save(path, data)
    return data


def agent_a_run(client: Product, path: Path, data: dict[str, object]) -> dict[str, object]:
    need(data.get("stage") in {"awaiting_approval_a", "agent_a_run_pending", "a_queued", "a_completed"},
         "Agent A StrategyVersion must exist before Backtest turn 2")
    need(os.environ.get("BYQ_PHASE15_BACKTEST_WORKER_STEP") == "running",
         "the exact scoped Backtest Worker must already be running")
    if not data.get("approval_a_artifact_id"):
        assert_approval(client, data, "a")
    assert_readiness(client)
    prompt = (
        "Use only BeyondQuant MCP; do not delegate. Register a fresh byq_agent_run_start for "
        "role_id=quant_orchestrator with idempotency_key=" + str(data["run_key"]) + "-agent-a. "
        "Use that run for authorization/audit. Start exactly one BacktestTask with the exact approved "
        "StrategyVersion A, ResearchTask, frozen pool, one date and execution below. Call prepare once, "
        "create once, then get/wait only on that exact task until ready_to_execute; execute it once. "
        "Do not create another strategy/task, request data repair or sync, call any provider, include a "
        "benchmark, broaden the universe/date, send bars/signals, or use raw Backtest APIs. Stop after "
        "reporting the exact backtest_task_id and backtest_job_id.\n"
        f"task_id={data['task_id']}\nstrategy_version_artifact_id={data['version_a_artifact_id']}\n"
        f"approval_artifact_id={data['approval_a_artifact_id']}\nstock_pool_snapshot_id={POOL_SNAPSHOT}\n"
        f"start_date={DATE}\nend_date={DATE}\nparameters={{\"threshold\":{THRESHOLD_A}}}\n"
        "execution={\"initial_capital\":100000,\"commission_rate\":0.0003,"
        "\"stamp_tax_rate\":0.001,\"slippage_rate\":0,\"lot_size\":100,"
        "\"max_positions\":10,\"a_share_rules\":true,\"max_runtime_seconds\":10,\"max_attempts\":2}\n"
        "order_quantity=100\nbenchmark=none"
    )
    data["stage"] = "agent_a_run_pending"
    save(path, data)
    task_ids, answer, _, events, registered = turn(client, path, data, 2, prompt, TASK_RE)
    need(registered, "Agent A backtest turn must register exactly one fresh AgentRun")
    need(len(task_ids) == 1, "Agent A answer contains ambiguous BacktestTask IDs")
    task_id = task_ids[0]
    check_turn_activities(events, {"准备回测任务", "创建回测任务", "跟踪回测任务", "执行回测任务"},
                          {"准备回测任务", "创建回测任务", "执行回测任务"},
                          {"创建回测任务", "执行回测任务"})
    jobs = client.api("GET", "/backtests?limit=100&offset=0").get("backtests")
    need(isinstance(jobs, list), "Backtest catalog projection is invalid")
    candidates = [item for item in jobs if isinstance(item, dict) and item.get("task_id") == data["task_id"]
                  and item.get("strategy_version_artifact_id") == data["version_a_artifact_id"]]
    need(len(candidates) == 1, "Agent A must create exactly one matching BacktestJob")
    job_id = str(candidates[0].get("job_id", ""))
    need(job_id in answer, "Agent answer does not identify the Product A Job")
    data.update({"backtest_task_a_id": task_id, "backtest_job_a_id": job_id, "stage": "a_queued"})
    save(path, data)
    job = wait_backtest(client, data, job_id, str(data["version_a_artifact_id"]),
                        str(data["approval_a_artifact_id"]))
    data["result_a_artifact_id"] = job["result_artifact_id"]
    data["stage"] = "a_completed"
    save(path, data)
    return data


def agent_b_version(client: Product, path: Path, data: dict[str, object]) -> dict[str, object]:
    need(data.get("stage") in {"a_completed", "agent_b_version_pending", "awaiting_approval_b"},
         "Backtest A must be completed before strategy revision")
    prompt = (
        "Use only BeyondQuant MCP; do not delegate. Register a fresh quant_orchestrator AgentRun with "
        "idempotency_key=" + str(data["run_key"]) + "-agent-b-version. Read the exact completed A Job "
        "with byq_backtest_analysis_get(section=summary,limit=20,offset=0) and export its StrategyVersion. Then create one revised StrategyDraft and "
        "StrategyVersion using byq_strategy_validate and byq_strategy_version_create, authorizing and "
        "auditing each write. Preserve the same strategy_id, script/source, schema, name, category and "
        "all snapshot fields; change only parameters.threshold from 9.20 to 9.22. Do not approve it, "
        "start a BacktestTask, delegate, request market data, call a provider, or add a benchmark. "
        "Report exactly the new strategy_version Artifact ID.\n"
        f"task_id={data['task_id']}\nbacktest_job_id={data['backtest_job_a_id']}\n"
        f"result_artifact_id={data['result_a_artifact_id']}\nstrategy_version_a={data['version_a_artifact_id']}\n"
        f"strategy_id={data['strategy_id']}\nthreshold_a={THRESHOLD_A}\nthreshold_b={THRESHOLD_B}\n"
        "The one-bar BYQ close is 9.21; no benchmark comparison is requested."
    )
    data["stage"] = "agent_b_version_pending"
    save(path, data)
    reported_artifact_ids, answer, _, events, registered = turn(client, path, data, 3, prompt, ARTIFACT_RE)
    need(registered, "Agent strategy revision turn must register exactly one fresh AgentRun")
    check_turn_activities(events, {"读取回测分析证据", "导出策略", "校验策略", "创建策略版本", "整理工作台建议"},
                          {"读取回测分析证据", "导出策略", "校验策略", "创建策略版本"})
    a = exact_artifact(client, str(data["version_a_artifact_id"]), "strategy_version")
    versions = [item for item in artifacts(client) if item.get("artifact_id") in reported_artifact_ids
                and item.get("kind") == "strategy_version" and item.get("task_id") == data["task_id"]
                and isinstance(item.get("content"), dict)
                and isinstance(item["content"].get("snapshot"), dict)
                and item["content"]["snapshot"].get("parameters") == {"threshold": THRESHOLD_B}]
    need(len(versions) == 1, "Agent answer does not identify exactly one new threshold B StrategyVersion")
    version_id = str(versions[0]["artifact_id"])
    b = exact_artifact(client, version_id, "strategy_version")
    ca, cb = a.get("content"), b.get("content")
    need(isinstance(ca, dict) and isinstance(cb, dict), "StrategyVersion content is malformed")
    sa, sb = ca.get("snapshot"), cb.get("snapshot")
    need(isinstance(sa, dict) and isinstance(sb, dict), "StrategyVersion snapshot is unavailable")
    left, right = dict(sa), dict(sb)
    pa, pb = left.pop("parameters", None), right.pop("parameters", None)
    need(ca.get("strategy_id") == data["strategy_id"] == cb.get("strategy_id")
         and ca.get("source_fingerprint") == cb.get("source_fingerprint")
         and left == right and pa == {"threshold": THRESHOLD_A} and pb == {"threshold": THRESHOLD_B},
         "revised StrategyVersion changed more than the threshold parameter")
    need(version_id in answer, "Agent answer omitted the exact revised Version Artifact")
    data.update({"version_b_artifact_id": version_id, "stage": "awaiting_approval_b"})
    save(path, data)
    return data


def check_signal_difference(client: Product, data: dict[str, object]) -> dict[str, int]:
    body = client.api("GET", "/signal-snapshots")
    snapshots = body.get("snapshots")
    need(isinstance(snapshots, list), "Product signal snapshot projection is invalid")
    counts: dict[str, int] = {}
    for label in ("a", "b"):
        version_id = str(data[f"version_{label}_artifact_id"])
        matches = [item for item in snapshots if isinstance(item, dict) and item.get("kind") == "signal_snapshot"
                   and isinstance(item.get("content"), dict)
                   and isinstance(item["content"].get("strategy"), dict)
                   and item["content"]["strategy"].get("strategy_version_artifact_id") == version_id]
        need(len(matches) == 1, f"expected one exact signal snapshot for version {label.upper()}")
        content = matches[0]["content"]
        need(matches[0].get("task_id") == data["task_id"] and matches[0].get("workspace_id") == WORKSPACE
             and content.get("universe", {}).get("symbols") == [SYMBOL]
             and content.get("benchmark") in (None, []), "signal snapshot scope or benchmark changed")
        signals = content.get("signals")
        need(isinstance(signals, list), "signal snapshot has no normalized signals list")
        counts[label] = len(signals)
    need(counts == {"a": 1, "b": 0}, "9.20/9.22 thresholds did not produce distinct one-bar snapshots")
    return counts


def agent_b_run(client: Product, path: Path, data: dict[str, object]) -> dict[str, object]:
    need(data.get("stage") in {"awaiting_approval_b", "agent_b_run_pending", "b_queued", "b_completed",
                                "optimization_pending", "complete"}, "Agent B Version is not ready")
    need(os.environ.get("BYQ_PHASE15_BACKTEST_WORKER_STEP") == "running"
         and os.environ.get("BYQ_PHASE15_OPTIMIZATION_WORKER_STEP") == "running",
         "the exact scoped Backtest and Optimization Workers must already be running")
    if not data.get("approval_b_artifact_id"):
        assert_approval(client, data, "b")
    assert_readiness(client)
    if not data.get("backtest_job_b_id"):
        prompt = (
            "Use only BeyondQuant MCP; do not delegate. Register a fresh quant_orchestrator AgentRun with "
            "idempotency_key=" + str(data["run_key"]) + "-agent-b-run. Read the exact approved StrategyVersion "
            "B and start exactly one BacktestTask using byq_backtest_task_prepare/create/get/execute. Authorize "
            "and audit domain writes. Wait only on that task until ready_to_execute; execute once. Do not "
            "create another strategy/task, change parameters, request data repair or sync, call a provider, "
            "include benchmark, broaden scope/date, delegate or send raw bars/signals. Report exact task and Job IDs.\n"
            f"task_id={data['task_id']}\nstrategy_version_artifact_id={data['version_b_artifact_id']}\n"
            f"approval_artifact_id={data['approval_b_artifact_id']}\nstock_pool_snapshot_id={POOL_SNAPSHOT}\n"
            f"start_date={DATE}\nend_date={DATE}\nparameters={{\"threshold\":{THRESHOLD_B}}}\n"
            "execution={\"initial_capital\":100000,\"commission_rate\":0.0003,"
            "\"stamp_tax_rate\":0.001,\"slippage_rate\":0,\"lot_size\":100,"
            "\"max_positions\":10,\"a_share_rules\":true,\"max_runtime_seconds\":10,\"max_attempts\":2}\n"
            "order_quantity=100\nbenchmark=none"
        )
        data["stage"] = "agent_b_run_pending"
        save(path, data)
        task_ids, answer, _, events, registered = turn(client, path, data, 4, prompt, TASK_RE)
        need(registered, "Agent B backtest turn must register exactly one fresh AgentRun")
        need(len(task_ids) == 1, "Agent B answer contains ambiguous BacktestTask IDs")
        task_id = task_ids[0]
        check_turn_activities(events, {"准备回测任务", "创建回测任务", "跟踪回测任务", "执行回测任务"},
                              {"准备回测任务", "创建回测任务", "执行回测任务"},
                              {"创建回测任务", "执行回测任务"})
        jobs = client.api("GET", "/backtests?limit=100&offset=0").get("backtests")
        need(isinstance(jobs, list), "Backtest catalog projection is invalid")
        candidates = [item for item in jobs if isinstance(item, dict) and item.get("task_id") == data["task_id"]
                      and item.get("strategy_version_artifact_id") == data["version_b_artifact_id"]]
        need(len(candidates) == 1, "Agent B must create exactly one matching BacktestJob")
        job_id = str(candidates[0].get("job_id", ""))
        need(job_id in answer, "Agent answer does not identify the Product B Job")
        data.update({"backtest_task_b_id": task_id, "backtest_job_b_id": job_id, "stage": "b_queued"})
        save(path, data)
    job = wait_backtest(client, data, str(data["backtest_job_b_id"]),
                        str(data["version_b_artifact_id"]), str(data["approval_b_artifact_id"]))
    data["result_b_artifact_id"] = job["result_artifact_id"]
    data["stage"] = "b_completed"
    save(path, data)
    signal_counts = check_signal_difference(client, data)
    if not data.get("optimization_job_id"):
        data["stage"] = "optimization_pending"
        save(path, data)
        reply = once(client, path, data, "optimization_attempted", "POST", "/optimization-jobs", {
            "task_id": data["task_id"], "idempotency_key": str(data["run_key"]) + "-compare",
            "objective": "total_return", "candidates": [
                {"backtest_job_id": data["backtest_job_a_id"], "parameters": {"threshold": THRESHOLD_A}},
                {"backtest_job_id": data["backtest_job_b_id"], "parameters": {"threshold": THRESHOLD_B}},
            ],
        }, 202)
        job_record = reply.get("job")
        need(isinstance(job_record, dict) and isinstance(job_record.get("job_id"), str),
             "Product did not return the exact OptimizationJob")
        data["optimization_job_id"] = job_record["job_id"]
        save(path, data)
    deadline = time.monotonic() + JOB_TIMEOUT
    while time.monotonic() < deadline:
        body = client.api("GET", f"/optimization-jobs/{data['optimization_job_id']}")
        optimization = body.get("job")
        need(isinstance(optimization, dict) and optimization.get("job_id") == data["optimization_job_id"],
             "Product returned a different OptimizationJob")
        status = optimization.get("status")
        if status in {"SUCCEEDED", "completed"}:
            artifact_id = optimization.get("result_artifact_id")
            need(isinstance(artifact_id, str), "OptimizationJob has no comparison Artifact")
            artifact = exact_artifact(client, artifact_id, "optimization_comparison")
            content = artifact.get("content")
            ranking = content.get("ranking") if isinstance(content, dict) else None
            ids = {row.get("backtest_job_id") for row in ranking if isinstance(row, dict)} if isinstance(ranking, list) else set()
            need(isinstance(content, dict) and content.get("optimization_job_id") == data["optimization_job_id"]
                 and content.get("candidate_count") == 2 and content.get("reran_backtests") is False
                 and ids == {data["backtest_job_a_id"], data["backtest_job_b_id"]}
                 and artifact.get("task_id") == data["task_id"],
                 "comparison Artifact does not bind exactly A and B")
            data.update({"comparison_artifact_id": artifact_id, "signal_counts": signal_counts, "stage": "complete"})
            save(path, data)
            return data
        need(status in {"QUEUED", "RUNNING", "queued", "running"},
             f"OptimizationJob ended in unexpected state {status}")
        time.sleep(2)
    raise EvidenceError(f"OptimizationJob did not complete within {JOB_TIMEOUT}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "agent-a-version", "agent-a-run",
                                           "agent-b-version", "agent-b-run"))
    args = parser.parse_args()
    _, client, path = configure(args.stage)
    if args.stage == "prepare":
        data = prepare(client, path)
    else:
        data = load(path)
        if args.stage == "agent-a-version":
            data = agent_a_version(client, path, data)
        elif args.stage == "agent-a-run":
            data = agent_a_run(client, path, data)
        elif args.stage == "agent-b-version":
            data = agent_b_version(client, path, data)
        else:
            data = agent_b_run(client, path, data)
    print(json.dumps({"result": data.get("stage"), "scope": SCOPE, "workspace_id": WORKSPACE,
                      "task_id": data.get("task_id"), "session_id": data.get("session_id"),
                      "session_trace_id": data.get("session_trace_id"), "strategy_id": data.get("strategy_id"),
                      "strategy_version_a": data.get("version_a_artifact_id"),
                      "approval_a": data.get("approval_a_artifact_id"),
                      "backtest_job_a": data.get("backtest_job_a_id"),
                      "strategy_version_b": data.get("version_b_artifact_id"),
                      "approval_b": data.get("approval_b_artifact_id"),
                      "backtest_job_b": data.get("backtest_job_b_id"),
                      "optimization_job": data.get("optimization_job_id"),
                      "comparison_artifact": data.get("comparison_artifact_id"),
                      "signal_counts": data.get("signal_counts"),
                      "next_operator_step": {
                          "prepared": "run agent-a-version under the approved three-turn limit",
                          "awaiting_approval_a": "approve exact A version through Product API, then run agent-a-run",
                          "a_completed": "run agent-b-version",
                          "awaiting_approval_b": "approve exact B version through Product API, then run agent-b-run",
                          "complete": None,
                      }.get(str(data.get("stage"))),
                      "manifest": str(path)}, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except EvidenceError as error:
        raise SystemExit(f"FAIL-CLOSED: {error}") from error
