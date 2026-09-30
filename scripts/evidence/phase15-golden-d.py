#!/usr/bin/env python3
"""Fail-closed, staged Product/Gateway evidence for Phase 15 Golden D.

The script never manages services. Before its first Agent turn, the scoped
Backtest Worker and data-worker must be stopped. After Root verifies the single
20240102 repair request, an operator resumes data-worker. TuShare and model
calls require BYQ_PHASE15_EXTERNAL_CALLS_AUTHORIZED=1.
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
SYMBOL = "000001.SZ"
TRADE_DATE = "20240102"
MCP_DATE = "2024-01-02"
SEED_TASK_TITLE = "Development research fixture"
SEED_TASK_OBJECTIVE = "Explore a synthetic momentum example using fresh BYQ data."
MANIFEST_SCHEMA = "phase15-golden-d-manifest.v2"
BACKTEST_TIMEOUT_SECONDS = 900
AGENT_TIMEOUT_SECONDS = 900
TASK_ID_PATTERN = re.compile(r"\bbacktesttask_[0-9a-f]{32}\b")
JOB_ID_PATTERN = re.compile(r"\bbacktest_[0-9a-f]{32}\b")


class EvidenceError(RuntimeError):
    pass


def require(condition: object, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def configure() -> tuple[dict[str, str], str, Path, str]:
    if os.environ.get("BYQ_PHASE15_EXTERNAL_CALLS_AUTHORIZED") != "1":
        raise EvidenceError(
            "external calls are disabled; set BYQ_PHASE15_EXTERNAL_CALLS_AUTHORIZED=1 "
            "only after explicit operator authorization"
        )
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.dev.environment import local_env

        values = local_env()
    except Exception as error:
        raise EvidenceError("scripts.dev.environment.local_env rejected this worktree") from error
    scope = values.get("BYQ_DEV_SCOPE", "")
    require(re.fullmatch(r"byq-dev-[0-9a-f]{10}", scope) is not None,
            "the local environment has no valid worktree scope")
    require(values.get("BYQ_GATEWAY_BIND") == "127.0.0.1:0",
            "Gateway must be configured for dynamic loopback binding")
    origin = os.environ.get("BYQ_REAL_BASE_URL", "").rstrip("/")
    parsed = urlsplit(origin)
    require(
        parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
        and parsed.port is not None and parsed.port > 0
        and parsed.username is None and parsed.password is None
        and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment,
        "BYQ_REAL_BASE_URL must be the dynamic loopback Gateway URL",
    )
    expected_workspace = os.environ.get("BYQ_PHASE15_EXPECTED_WORKSPACE_ID", "")
    require(re.fullmatch(r"workspace_[0-9a-f]{32}", expected_workspace) is not None,
            "set BYQ_PHASE15_EXPECTED_WORKSPACE_ID to the disposable Workspace ID")
    return values, origin, manifest_path(), expected_workspace


def manifest_path() -> Path:
    raw = os.environ.get("BYQ_PHASE15_GOLDEN_D_MANIFEST", str(ROOT / ".phase15-golden-d.json"))
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve(strict=False)
    require(resolved.is_relative_to(ROOT.resolve()), "manifest must remain inside this worktree")
    require(not path.is_symlink(), "manifest path must not be a symlink")
    return resolved


class ProductClient:
    def __init__(self, origin: str, username: str, password: str) -> None:
        self.origin = origin
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login = self.request("POST", "/api/auth/login", {"username": username, "password": password}, 200)
        user, workspace = login.get("user"), login.get("workspace")
        require(isinstance(user, dict) and user.get("username") == username
                and user.get("role") == "admin", "Product login did not authenticate the bootstrap admin")
        require(isinstance(workspace, dict), "Product login returned no personal Workspace")
        self.user = user
        self.workspace = workspace
        self.username = username

    def request(
        self, method: str, path: str, payload: dict[str, object] | None = None,
        expected: int | None = None, *, headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, object]:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["content-type"] = "application/json"
        request = Request(self.origin + path, data=body, headers=request_headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                status = response.status
                raw = response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        except (URLError, TimeoutError) as error:
            raise EvidenceError(f"Product request outcome is unknown: {method} {path}") from error
        if expected is not None and status != expected:
            raise EvidenceError(f"Product request {method} {path} returned HTTP {status}")
        if expected is None and not 200 <= status < 300:
            raise EvidenceError(f"Product request {method} {path} returned HTTP {status}")
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EvidenceError(f"Product response was not JSON: {method} {path}") from error
        if not isinstance(value, dict):
            raise EvidenceError(f"Product response was not an object: {method} {path}")
        return value

    def product(
        self, method: str, path: str, payload: dict[str, object] | None = None,
        expected: int | None = None, *, headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return self.request(method, "/api/product" + path, payload, expected, headers=headers)

    def verify_identity(self, expected_workspace: str) -> None:
        me = self.request("GET", "/api/auth/me")
        workspace = me.get("workspace")
        require(me.get("subject") == self.username and me.get("role") == "admin",
                "authenticated Product identity is not the bootstrap admin")
        require(isinstance(workspace, dict) and isinstance(self.workspace, dict)
                and workspace.get("workspace_id") == expected_workspace
                and self.workspace.get("workspace_id") == expected_workspace
                and workspace.get("contract") == "personal-workspace.v1"
                and workspace.get("kind") == "personal"
                and workspace.get("role") == "owner",
                "authenticated Product identity does not match the required disposable Workspace")


def write_manifest(path: Path, data: dict[str, object]) -> None:
    require(not path.is_symlink(), "manifest path became a symlink")
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


def load_manifest(path: Path, scope: str, workspace_id: str, username: str) -> dict[str, object]:
    require(path.is_file() and not path.is_symlink(), "no safe Golden D manifest; run prepare first")
    require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0,
            "manifest must be private to the current user")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError("Golden D manifest is unreadable") from error
    require(isinstance(value, dict) and value.get("schema_version") == MANIFEST_SCHEMA,
            "Golden D manifest schema is invalid")
    require(value.get("scope") == scope and value.get("workspace_id") == workspace_id
            and value.get("owner_username") == username,
            "Golden D manifest belongs to another scope, Workspace, or user")
    return value


def save(path: Path, manifest: dict[str, object]) -> None:
    manifest["updated_at"] = utc_now()
    write_manifest(path, manifest)


def request_key(manifest: dict[str, object], suffix: str) -> str:
    key = f"{manifest['run_key']}-{suffix}"
    require(len(key) <= 96 and re.fullmatch(r"[A-Za-z0-9_-]+", key) is not None,
            "manifest idempotency key is invalid")
    return key


def list_items(body: dict[str, object], key: str, label: str) -> list[dict[str, object]]:
    values = body.get(key)
    require(isinstance(values, list) and all(isinstance(item, dict) for item in values),
            f"Product {label} projection is invalid")
    return values


def assert_fresh_workspace(client: ProductClient) -> None:
    tasks = list_items(client.product("GET", "/research/tasks"), "tasks", "ResearchTask")
    artifacts = list_items(client.product("GET", "/research/artifacts"), "artifacts", "Artifact")
    pools = list_items(client.product("GET", "/paper/pools?limit=100&offset=0"), "pools", "pool")
    backtests_response = client.product("GET", "/backtests?limit=100&offset=0")
    backtests = list_items(backtests_response, "backtests", "Backtest")
    require(backtests_response.get("total") == 0 and not backtests,
            "disposable Workspace already contains Backtest Jobs")
    require(not pools, "disposable Workspace already contains stock pools")
    require(len(tasks) == 1 and tasks[0].get("title") == SEED_TASK_TITLE
            and tasks[0].get("objective") == SEED_TASK_OBJECTIVE,
            "Workspace is not the fresh dev-seed baseline (expected only its seed ResearchTask)")
    seed_task_id = tasks[0].get("task_id")
    require(isinstance(seed_task_id, str), "fresh dev-seed ResearchTask has no ID")
    require(len(artifacts) == 2 and all(item.get("task_id") == seed_task_id for item in artifacts)
            and {item.get("kind") for item in artifacts} == {"strategy_draft", "dataset"},
            "Workspace is not the fresh dev-seed baseline (expected only its two seed Artifacts)")
    for status in ("active", "archived"):
        sessions = client.request("GET", f"/v1/agent/sessions?{urlencode({'status': status, 'limit': 100, 'offset': 0})}")
        require(sessions.get("total") == 0 and sessions.get("sessions") == [],
                "disposable Workspace already contains Agent conversations")


def current_session(client: ProductClient, session_id: str) -> dict[str, object] | None:
    try:
        return client.request("GET", f"/v1/agent/sessions/{session_id}")
    except EvidenceError as error:
        if "HTTP 404" in str(error):
            return None
        raise


def wait_for_job(
    client: ProductClient, path: str, job_id: str, *, timeout: int = BACKTEST_TIMEOUT_SECONDS,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.product("GET", path.format(job_id=job_id))
        job = body.get("job")
        require(isinstance(job, dict) and job.get("job_id") == job_id,
                "Product returned a different synchronization Job")
        status = job.get("status")
        if status == "completed":
            return job
        if status in {"failed", "partial", "cancelled"}:
            raise EvidenceError(f"synchronization Job {job_id} ended {status}")
        if status not in {"queued", "running"}:
            raise EvidenceError(f"synchronization Job {job_id} has unknown status")
        time.sleep(2)
    raise EvidenceError(f"synchronization Job {job_id} did not finish within {timeout}s")


def assert_exact_readiness(
    value: dict[str, object], *, allowed_verdicts: tuple[str, ...] = ("usable",),
) -> str:
    scope, summary = value.get("scope"), value.get("summary")
    require(isinstance(scope, dict) and isinstance(summary, dict),
            "Product readiness response is malformed")
    verdict = value.get("verdict")
    missing = summary.get("missing_items")
    require(value.get("schema_version") == "data-readiness-product.v1"
            and value.get("checked_against") == "persisted_byq"
            and verdict in allowed_verdicts
            and scope.get("selection_type") == "explicit"
            and scope.get("symbols") == [SYMBOL]
            and scope.get("symbol_count") == 1
            and scope.get("start_date") == TRADE_DATE
            and scope.get("end_date") == TRADE_DATE
            and scope.get("use_case") == "backtest"
            and (summary.get("required_sessions") == 1 if verdict == "usable"
                 else summary.get("required_sessions") in {0, 1})
            and isinstance(missing, int) and not isinstance(missing, bool)
            and (missing == 0 if verdict == "usable" else missing >= 0),
            "readiness scope expanded or is not usable; stop without requesting broader repairs")
    return str(verdict)


def wait_for_agent_id(
    client: ProductClient, session_id: str, pattern: re.Pattern[str], label: str,
    timeout: int = AGENT_TIMEOUT_SECONDS,
) -> tuple[dict[str, object], list[dict[str, object]], str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body, events = agent_events(client, session_id)
        if any(
            item.get("kind") == "agent.activity"
            and isinstance(item.get("payload"), dict)
            and item["payload"].get("state") in {"failed", "unknown"}
            for item in events
        ):
            raise EvidenceError("Agent MCP activity failed or has an unknown outcome")
        text = assistant_text(body)
        matches = set(pattern.findall(text))
        if len(matches) == 1:
            return body, events, matches.pop()
        if body.get("conversation", {}).get("status") in {"failed", "interrupted"}:
            raise EvidenceError(f"Agent conversation failed before reporting the exact {label}")
        time.sleep(1)
    raise EvidenceError(f"Agent answer did not report exactly one {label}")


def wait_for_exact_readiness(
    client: ProductClient, path: Path, manifest: dict[str, object],
) -> dict[str, object]:
    deadline = time.monotonic() + BACKTEST_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        value = client.product(
            "POST", "/data-center/readiness",
            {"symbols": [SYMBOL], "start_date": TRADE_DATE, "end_date": TRADE_DATE,
             "use_case": "backtest"},
        )
        verdict = assert_exact_readiness(value, allowed_verdicts=("unavailable", "usable"))
        snapshot = {
            "schema_version": value["schema_version"], "verdict": verdict,
            "scope": value["scope"], "summary": value["summary"],
        }
        if manifest.get("post_create_readiness") != snapshot:
            manifest["post_create_readiness"] = snapshot
            save(path, manifest)
        if verdict == "usable":
            return value
        time.sleep(5)
    raise EvidenceError("exact one-symbol, one-session Product readiness did not become usable")


def prepare(client: ProductClient, path: Path, scope: str, workspace_id: str) -> dict[str, object]:
    if path.exists():
        manifest = load_manifest(path, scope, workspace_id, client.username)
        require(manifest.get("stage") in {"prepare", "prepared"},
                "prepare cannot restart after Agent submission; continue with submit or finish")
    else:
        assert_fresh_workspace(client)
        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "run_key": "p15d-" + secrets.token_hex(8),
            "scope": scope,
            "workspace_id": workspace_id,
            "owner_username": client.username,
            "created_at": utc_now(),
            "stage": "prepare",
        }
        save(path, manifest)

    if not manifest.get("task_id"):
        task = client.product(
            "POST", "/research/tasks",
            {"title": f"Phase 15 Golden D {manifest['run_key']}",
             "objective": "Run one approved BYQ backtest from exact synchronized market data; verify the Job survives Agent conversation deletion."},
            expected=201,
            headers={"x-idempotency-key": request_key(manifest, "task")},
        )
        require(isinstance(task.get("task_id"), str), "Product did not return the exact ResearchTask")
        manifest["task_id"] = task["task_id"]
        save(path, manifest)

    if not manifest.get("security_master_job_id"):
        body = client.product(
            "POST", "/data-center/security-master/sync-jobs",
            {"idempotency_key": request_key(manifest, "security-master")}, expected=201,
        )
        job = body.get("job")
        require(isinstance(job, dict) and isinstance(job.get("job_id"), str),
                "Product did not return the security-master sync Job")
        manifest["security_master_job_id"] = job["job_id"]
        save(path, manifest)
    master = wait_for_job(
        client, "/data-center/security-master/sync-jobs/{job_id}",
        str(manifest["security_master_job_id"]),
    )
    require(master.get("provider") == "tushare" and master.get("statuses") == ["L", "P", "D"]
            and isinstance(master.get("snapshot_id"), str)
            and int(master.get("records_received") or 0) > 0,
            "security-master result lacks real TuShare provenance or a complete snapshot")
    manifest["security_master_snapshot_id"] = master["snapshot_id"]
    save(path, manifest)

    readiness = client.product(
        "POST", "/data-center/readiness",
        {"symbols": [SYMBOL], "start_date": TRADE_DATE, "end_date": TRADE_DATE,
         "use_case": "backtest"},
    )
    verdict = assert_exact_readiness(readiness, allowed_verdicts=("unavailable", "usable"))
    manifest["pre_create_readiness"] = {
        "schema_version": readiness["schema_version"], "verdict": verdict,
        "scope": readiness["scope"], "summary": readiness["summary"],
    }
    save(path, manifest)

    if not manifest.get("pool_id"):
        body = client.product(
            "POST", "/paper/pools",
            {"idempotency_key": request_key(manifest, "pool"),
             "name": f"Phase 15 Golden D {manifest['run_key']}",
             "pool_type": "custom", "symbols": [SYMBOL]}, expected=201,
        )
        pool = body.get("pool")
        require(isinstance(pool, dict) and isinstance(pool.get("pool_id"), str)
                and isinstance(pool.get("snapshot"), dict),
                "Product did not return the exact custom pool and snapshot")
        snapshot = pool["snapshot"]
        members = snapshot.get("members")
        require(pool.get("pool_type") == "custom" and pool.get("status") == "active"
                and pool.get("symbols") == [SYMBOL]
                and isinstance(snapshot.get("snapshot_id"), str)
                and isinstance(members, list)
                and [item.get("symbol") for item in members if isinstance(item, dict)] == [SYMBOL],
                "custom pool snapshot contains a different symbol")
        manifest["pool_id"] = pool["pool_id"]
        manifest["pool_snapshot_id"] = snapshot["snapshot_id"]
        save(path, manifest)

    strategy = {
        "strategy_id": "Phase15GoldenD" + str(manifest["run_key"])[-8:],
        "name": f"Phase 15 Golden D {manifest['run_key']}",
        "category": "momentum",
        "description": "Deterministic strategy source; market inputs come only from the validated BYQ readiness scope.",
        "parameters": {"lookback": 1},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": (
            "class CustomStrategy:\n"
            "    def generate_signals(self, data, parameters=None):\n"
            "        result = {}\n"
            "        for symbol in data.index.get_level_values('symbol').unique():\n"
            "            close = data.xs(symbol, level='symbol')['close']\n"
            "            result[str(symbol)] = (close > 0).fillna(False).astype(int)\n"
            "        return result\n"
        ),
    }
    common = {"task_id": manifest["task_id"], "strategy": strategy}
    if not manifest.get("draft_artifact_id"):
        validated = client.product(
            "POST", "/strategies/validate",
            {**common, "trace_id": request_key(manifest, "validate"),
             "idempotency_key": request_key(manifest, "validate")}, expected=201,
        )
        artifact = validated.get("artifact")
        require(isinstance(artifact, dict) and isinstance(artifact.get("artifact_id"), str)
                and artifact.get("task_id") == manifest["task_id"],
                "Product strategy validation did not return a Task-bound Artifact")
        manifest["draft_artifact_id"] = artifact["artifact_id"]
        save(path, manifest)
    if not manifest.get("strategy_version_artifact_id"):
        version_body = client.product(
            "POST", "/strategies/versions",
            {"task_id": manifest["task_id"], "draft_artifact_id": manifest["draft_artifact_id"],
             "trace_id": request_key(manifest, "version"),
             "idempotency_key": request_key(manifest, "version")}, expected=201,
        )
        version = version_body.get("artifact")
        require(isinstance(version, dict) and isinstance(version.get("artifact_id"), str)
                and version.get("task_id") == manifest["task_id"]
                and version.get("kind") == "strategy_version"
                and version.get("status") == "validated",
                "Product did not return the exact validated strategy version")
        manifest["strategy_version_artifact_id"] = version["artifact_id"]
        save(path, manifest)
    if not manifest.get("approval_artifact_id"):
        approval_body = client.product(
            "POST", "/strategies/approvals",
            {"task_id": manifest["task_id"],
             "strategy_version_artifact_id": manifest["strategy_version_artifact_id"],
             "decision": "approved", "rationale": "Explicit Phase 15 Golden D disposable-workspace approval.",
             "trace_id": request_key(manifest, "approval"),
             "idempotency_key": request_key(manifest, "approval")}, expected=201,
        )
        approval = approval_body.get("artifact")
        require(isinstance(approval, dict) and isinstance(approval.get("artifact_id"), str)
                and approval.get("task_id") == manifest["task_id"]
                and approval.get("kind") == "strategy_approval"
                and isinstance(approval.get("content"), dict)
                and approval["content"].get("decision") == "approved"
                and approval["content"].get("strategy_version_artifact_id") == manifest["strategy_version_artifact_id"],
                "Product did not return the exact approved strategy Artifact")
        manifest["approval_artifact_id"] = approval["artifact_id"]
        save(path, manifest)
    manifest["stage"] = "prepared"
    save(path, manifest)
    return manifest


def backtests_for_task(client: ProductClient, task_id: str) -> list[dict[str, object]]:
    body = client.product("GET", "/backtests?limit=100&offset=0")
    jobs = list_items(body, "backtests", "Backtest")
    require(body.get("total") == len(jobs), "Backtest catalog was truncated")
    return [job for job in jobs if job.get("task_id") == task_id]


def agent_events(client: ProductClient, session_id: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    body = client.request("GET", f"/v1/agent/sessions/{session_id}")
    events = body.get("events")
    require(isinstance(events, list) and all(isinstance(item, dict) for item in events),
            "Product Agent session has no normalized trace projection")
    return body, events


def activity_events(events: list[dict[str, object]], label: str) -> list[dict[str, object]]:
    return [item for item in events if item.get("kind") == "agent.activity"
            and isinstance(item.get("payload"), dict) and item["payload"].get("label") == label]


def require_only_activities(events: list[dict[str, object]], labels: set[str]) -> None:
    observed = {
        str(item["payload"].get("label"))
        for item in events if item.get("kind") == "agent.activity"
        and isinstance(item.get("payload"), dict)
        and item["payload"].get("label") != "理解请求"
    }
    require(observed == labels, "Agent called an unexpected capability; inspect the scoped effects and stop")


def wait_for_answer_ids(
    client: ProductClient, session_id: str, *identifiers: str,
    timeout: int = AGENT_TIMEOUT_SECONDS,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body, events = agent_events(client, session_id)
        if all(identifier in assistant_text(body) for identifier in identifiers):
            return body, events
        if body.get("conversation", {}).get("status") in {"failed", "interrupted"}:
            raise EvidenceError("Agent conversation failed before its answer was persisted")
        time.sleep(1)
    raise EvidenceError("Agent answer did not report the exact Product IDs")


def assistant_text(body: dict[str, object]) -> str:
    messages = body.get("messages")
    require(isinstance(messages, list), "Agent conversation has no Product messages")
    return "\n".join(str(message.get("content", "")) for message in messages
                     if isinstance(message, dict) and message.get("role") == "assistant")


def submit(client: ProductClient, path: Path, manifest: dict[str, object]) -> dict[str, object]:
    require(os.environ.get("BYQ_PHASE15_BACKTEST_WORKER_STEP") == "stopped",
            "operator step required: keep this scope's backtest-worker stopped")
    require(manifest.get("stage") in {"prepared", "initial_session_create_pending", "first_turn_pending",
                                       "repair_scope_review_pending", "execute_turn_pending", "queued",
                                       "interrupted"},
            "manifest is not ready for Agent submission")
    if manifest.get("stage") in {"prepared", "initial_session_create_pending", "first_turn_pending"}:
        require(os.environ.get("BYQ_PHASE15_DATA_WORKER_STEP") == "stopped",
                "operator step required: keep scoped data-worker stopped until Root reviews the repair request")
        if manifest.get("stage") == "prepared":
            readiness = manifest.get("pre_create_readiness")
            require(isinstance(readiness, dict) and readiness.get("verdict") == "unavailable",
                    "first Agent create requires exact one-session pre-create readiness=unavailable")
    research_task_id = str(manifest["task_id"])
    if manifest.get("stage") == "queued":
        prior = current_session(client, str(manifest["old_conversation_id"]))
        if prior is None:
            job_id = str(manifest.get("backtest_job_id", ""))
            job = client.product("GET", f"/backtests/{job_id}").get("job")
            require(isinstance(job, dict) and job.get("job_id") == job_id
                    and job.get("status") == "queued",
                    "cannot reconcile old conversation deletion against the same queued Job")
            manifest["old_conversation_deleted"] = True
            manifest["old_conversation_deleted_at"] = manifest.get("old_conversation_deleted_at") or utc_now()
            manifest["stage"] = "interrupted"
            save(path, manifest)
            return manifest
    if manifest.get("stage") == "prepared":
        manifest["stage"] = "initial_session_create_pending"
        save(path, manifest)
        session = client.request("POST", "/v1/agent/sessions", expected=201)
        require(isinstance(session.get("session_id"), str) and isinstance(session.get("trace_id"), str),
                "Product did not return the initial Agent conversation")
        manifest["old_conversation_id"] = session["session_id"]
        manifest["old_trace_id"] = session["trace_id"]
        manifest["stage"] = "first_turn_pending"
        manifest["create_message"] = (
            "Use only BeyondQuant MCP. Call byq_backtest_task_prepare once with these exact inputs, then "
            "byq_backtest_task_create exactly once with the same inputs and idempotency key. Creation may queue "
            "market-data repair; report the exact returned backtest_task_id and phase. Do not execute the task yet. "
            "Do not call any data-demand or data-sync tool, change symbols or dates, request broader repair, or "
            "transmit bars, market rows, or signals.\n"
            f"task_id={research_task_id}\n"
            f"strategy_version_artifact_id={manifest['strategy_version_artifact_id']}\n"
            f"stock_pool_snapshot_id={manifest['pool_snapshot_id']}\n"
            f"start_date={MCP_DATE}\nend_date={MCP_DATE}\nparameters={{\"lookback\":1}}\n"
            "execution={\"initial_capital\":100000,\"commission_rate\":0.0003,"
            "\"stamp_tax_rate\":0.001,\"slippage_rate\":0,\"lot_size\":100,"
            "\"max_positions\":10,\"a_share_rules\":true,\"max_runtime_seconds\":10,\"max_attempts\":2}\n"
            "order_quantity=100\n"
            f"idempotency_key={request_key(manifest, 'agent-backtest-task')}"
        )
        save(path, manifest)
    elif manifest.get("stage") == "initial_session_create_pending":
        raise EvidenceError("Agent session creation outcome is unknown; reconcile it manually instead of creating another conversation")

    session_id = str(manifest.get("old_conversation_id", ""))
    require(bool(session_id), "initial Agent conversation identity is missing")
    if manifest.get("stage") == "first_turn_pending":
        body = current_session(client, session_id)
        messages = body.get("messages") if isinstance(body, dict) else None
        already_posted = isinstance(messages, list) and any(
            isinstance(item, dict) and item.get("role") == "user"
            and item.get("content") == manifest["create_message"] for item in messages
        )
        if manifest.get("create_turn_post_attempted"):
            require(already_posted, "first Agent turn outcome is unknown; do not submit it again")
        else:
            manifest["create_turn_post_attempted"] = True
            save(path, manifest)
            accepted = client.request(
                "POST", f"/v1/agent/sessions/{session_id}/turns",
                {"content": manifest["create_message"]}, expected=202,
            )
            require(accepted.get("accepted") is True and accepted.get("session_id") == session_id,
                    "Product did not confirm the first Agent turn")
        _, events, backtest_task_id = wait_for_agent_id(
            client, session_id, TASK_ID_PATTERN, "backtest_task_id",
        )
        require_only_activities(events, {"准备回测任务", "创建回测任务"})
        prepare_events = activity_events(events, "准备回测任务")
        create_events = activity_events(events, "创建回测任务")
        execute_events = activity_events(events, "执行回测任务")
        require(len(prepare_events) == 2 and sum(item.get("payload", {}).get("state") == "started"
                for item in prepare_events) == 1
                and sum(item.get("payload", {}).get("state") == "completed" for item in prepare_events) == 1
                and len(create_events) == 2 and sum(item.get("payload", {}).get("state") == "started"
                for item in create_events) == 1
                and sum(item.get("payload", {}).get("state") in {"completed", "waiting"}
                        for item in create_events) == 1
                and not execute_events,
                "first normalized Agent trace must prove one prepare, one accepted create, and no execute")
        prepare_done = next(item for item in prepare_events if item.get("payload", {}).get("state") == "completed")
        create_start = next(item for item in create_events if item.get("payload", {}).get("state") == "started")
        require(int(prepare_done.get("sequence", 0)) < int(create_start.get("sequence", 0)),
                "Agent create did not follow the read-only prepare")
        manifest["backtest_task_id"] = backtest_task_id
        manifest["create_trace_state"] = next(
            item["payload"]["state"] for item in create_events
            if item.get("payload", {}).get("state") in {"completed", "waiting"}
        )
        manifest["agent_task_job_binding"] = (
            "not_proven_normalized_trace_omits_tool_arguments_and_results"
        )
        manifest["stage"] = "repair_scope_review_pending"
        save(path, manifest)
        return manifest

    if manifest.get("stage") == "repair_scope_review_pending":
        initial_readiness = manifest.get("pre_create_readiness")
        require(isinstance(initial_readiness, dict) and initial_readiness.get("verdict") == "unavailable",
                "Agent create is allowed only after exact pre-create readiness is unavailable")
        require(os.environ.get("BYQ_PHASE15_REPAIR_SCOPE_VERIFIED") == TRADE_DATE,
                "operator must read-only verify the unique market_data_repair_requests row is exactly 20240102 before resuming data-worker")
        require(os.environ.get("BYQ_PHASE15_DATA_WORKER_STEP") == "running",
                "after exact repair-scope review, resume the scoped data-worker and set BYQ_PHASE15_DATA_WORKER_STEP=running")
        require(isinstance(manifest.get("backtest_task_id"), str), "exact created backtest_task_id is missing")
        wait_for_exact_readiness(client, path, manifest)
        manifest["readiness_after_create"] = manifest.pop("post_create_readiness")
        manifest["stage"] = "execute_turn_pending"
        manifest["execute_message"] = (
            "Use only BeyondQuant MCP. For this exact backtest_task_id, call byq_backtest_task_get once. "
            "Only if its phase is ready_to_execute and its research_task_id, strategy_version_artifact_id, "
            "stock_pool_snapshot_id match below, call byq_backtest_task_execute exactly once. Otherwise do not "
            "execute and report the exact blocker. Do not create another task, use direct backtest submit, "
            "request repairs, broaden scope, or transmit raw market rows. Return the exact task and Job IDs.\n"
            f"backtest_task_id={manifest['backtest_task_id']}\n"
            f"task_id={research_task_id}\n"
            f"strategy_version_artifact_id={manifest['strategy_version_artifact_id']}\n"
            f"stock_pool_snapshot_id={manifest['pool_snapshot_id']}"
        )
        save(path, manifest)

    if manifest.get("stage") == "execute_turn_pending":
        body = current_session(client, session_id)
        messages = body.get("messages") if isinstance(body, dict) else None
        already_posted = isinstance(messages, list) and any(
            isinstance(item, dict) and item.get("role") == "user"
            and item.get("content") == manifest.get("execute_message") for item in messages
        )
        if manifest.get("execute_turn_post_attempted"):
            require(already_posted, "execute Agent turn outcome is unknown; do not submit it again")
        else:
            manifest["execute_turn_post_attempted"] = True
            save(path, manifest)
            accepted = client.request(
                "POST", f"/v1/agent/sessions/{session_id}/turns",
                {"content": manifest["execute_message"]}, expected=202,
            )
            require(accepted.get("accepted") is True and accepted.get("session_id") == session_id,
                    "Product did not confirm the execute Agent turn")
        _, events, reported_job_id = wait_for_agent_id(
            client, session_id, JOB_ID_PATTERN, "backtest_job_id",
        )
        require_only_activities(events, {"准备回测任务", "创建回测任务", "跟踪回测任务", "执行回测任务"})
        get_events = activity_events(events, "跟踪回测任务")
        execute_events = activity_events(events, "执行回测任务")
        require(len(get_events) == 2 and sum(item.get("payload", {}).get("state") == "started"
                for item in get_events) == 1
                and sum(item.get("payload", {}).get("state") == "completed" for item in get_events) == 1
                and len(execute_events) == 2 and sum(item.get("payload", {}).get("state") == "started"
                for item in execute_events) == 1
                and sum(item.get("payload", {}).get("state") in {"completed", "waiting"}
                        for item in execute_events) == 1,
                "second normalized Agent trace must prove one task read and one accepted execute")
        get_done = next(item for item in get_events if item.get("payload", {}).get("state") == "completed")
        execute_start = next(item for item in execute_events if item.get("payload", {}).get("state") == "started")
        require(int(get_done.get("sequence", 0)) < int(execute_start.get("sequence", 0)),
                "Agent execute did not follow the exact task readiness read")
        jobs = backtests_for_task(client, research_task_id)
        require(len(jobs) == 1, "the exact ResearchTask must have one Backtest Job")
        job = jobs[0]
        job_id = str(job.get("job_id", ""))
        require(job_id == reported_job_id
                and job.get("workspace_id") == manifest["workspace_id"]
                and job.get("owner_principal") == manifest["owner_username"]
                and job.get("strategy_version_artifact_id") == manifest["strategy_version_artifact_id"]
                and job.get("approval_artifact_id") == manifest["approval_artifact_id"]
                and job.get("stock_pool_snapshot_id") == manifest["pool_snapshot_id"]
                and job.get("status") == "queued"
                and JOB_ID_PATTERN.fullmatch(job_id) is not None,
                "queued Product Job does not match the Agent answer and exact owner, Task, Strategy, Approval, and Pool")
        manifest["backtest_job_id"] = job_id
        manifest["backtest_created_at"] = job.get("created_at")
        manifest["mcp_execute_activity_observed"] = True
        manifest["stage"] = "queued"
        save(path, manifest)

    if manifest.get("stage") == "queued":
        job_id = str(manifest["backtest_job_id"])
        deleted = client.request("DELETE", f"/v1/agent/sessions/{session_id}")
        require(deleted.get("session_id") == session_id and deleted.get("status") == "deleted",
                "Product did not delete the old Agent conversation")
        manifest["old_conversation_deleted"] = True
        manifest["old_conversation_deleted_at"] = utc_now()
        save(path, manifest)
        still_queued = client.product("GET", f"/backtests/{job_id}").get("job")
        require(isinstance(still_queued, dict) and still_queued.get("job_id") == job_id
                and still_queued.get("status") == "queued",
                "exact Backtest Job did not remain queued after old conversation deletion")
        manifest["stage"] = "interrupted"
        save(path, manifest)
    return manifest


def finish(client: ProductClient, path: Path, manifest: dict[str, object]) -> dict[str, object]:
    require(os.environ.get("BYQ_PHASE15_BACKTEST_WORKER_STEP") == "running",
            "operator step required: after old conversation deletion, restart the same scoped backtest-worker and set BYQ_PHASE15_BACKTEST_WORKER_STEP=running")
    require(manifest.get("stage") in {"interrupted", "finish_pending", "new_agent_create_pending",
                                       "new_agent_pending", "completed"}
            and manifest.get("old_conversation_deleted") is True,
            "old conversation must be deleted before Worker recovery")
    job_id = str(manifest["backtest_job_id"])
    if manifest.get("stage") != "completed":
        resume_stage = manifest.get("stage")
        if resume_stage not in {"new_agent_create_pending", "new_agent_pending"}:
            manifest["stage"] = "finish_pending"
            save(path, manifest)
        deadline = time.monotonic() + BACKTEST_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            job = client.product("GET", f"/backtests/{job_id}").get("job")
            require(isinstance(job, dict) and job.get("job_id") == job_id,
                    "Product returned a different Backtest Job")
            if job.get("status") == "completed":
                break
            if job.get("status") in {"failed", "cancelled"}:
                raise EvidenceError(f"Backtest Job ended {job.get('status')}")
            if job.get("status") not in {"queued", "running"}:
                raise EvidenceError("Backtest Job has an unknown status")
            time.sleep(2)
        else:
            raise EvidenceError("Backtest Worker did not complete the exact queued Job")
        result_artifact_id = job.get("result_artifact_id")
        require(job.get("attempts") == 1 and isinstance(result_artifact_id, str)
                and result_artifact_id.startswith("artifact_"),
                "Backtest Job did not complete in exactly one attempt with a result Artifact")
        result_body = client.product("GET", f"/backtests/{job_id}/result")
        require(result_body.get("job_id") == job_id and isinstance(result_body.get("result"), dict),
                "Product result endpoint returned a different Job")
        artifacts = list_items(client.product("GET", "/research/artifacts"), "artifacts", "Artifact")
        matching = [item for item in artifacts if item.get("artifact_id") == job.get("result_artifact_id")]
        require(len(matching) == 1, "exact completed Job has no unique Product result Artifact")
        artifact = matching[0]
        content = artifact.get("content")
        require(artifact.get("task_id") == manifest["task_id"]
                and artifact.get("workspace_id") == manifest["workspace_id"]
                and artifact.get("kind") == "backtest_result"
                and artifact.get("status") == "validated"
                and isinstance(content, dict)
                and content.get("job_id") == job_id
                and content.get("strategy_version_artifact_id") == manifest["strategy_version_artifact_id"]
                and content.get("approval_artifact_id") == manifest["approval_artifact_id"],
                "result Artifact provenance does not match the exact Job inputs")
        manifest["result_artifact_id"] = job["result_artifact_id"]
        manifest["worker_completed_at"] = job.get("finished_at")
        if manifest.get("stage") not in {"new_agent_create_pending", "new_agent_pending"}:
            manifest["stage"] = "finish_pending"
        save(path, manifest)

    if not manifest.get("new_conversation_id"):
        require(manifest.get("stage") == "finish_pending",
                "new Agent conversation creation outcome is unknown; reconcile it before continuing")
        manifest["stage"] = "new_agent_create_pending"
        save(path, manifest)
        session = client.request("POST", "/v1/agent/sessions", expected=201)
        require(isinstance(session.get("session_id"), str) and isinstance(session.get("trace_id"), str),
                "Product did not return the new Agent conversation")
        manifest["new_conversation_id"] = session["session_id"]
        manifest["new_trace_id"] = session["trace_id"]
        manifest["new_read_message"] = (
            "Use only the read-only BeyondQuant MCP tool byq_backtest_get once with this exact job_id. "
            "Report its status and result_artifact_id. Do not submit, execute, rerun, or read raw bars.\n"
            f"job_id={job_id}"
        )
        manifest["stage"] = "new_agent_pending"
        save(path, manifest)
        accepted = client.request(
            "POST", f"/v1/agent/sessions/{manifest['new_conversation_id']}/turns",
            {"content": manifest["new_read_message"]}, expected=202,
        )
        require(accepted.get("accepted") is True and accepted.get("session_id") == manifest["new_conversation_id"],
                "Product did not confirm the new Agent read turn")
        manifest["new_read_turn_accepted"] = True
        save(path, manifest)
    else:
        session_id = str(manifest["new_conversation_id"])
        body = current_session(client, session_id)
        if manifest.get("stage") == "new_agent_pending":
            require(body is not None, "new Agent read outcome is unknown; do not submit another turn")
            messages = body.get("messages")
            require(isinstance(messages, list) and any(
                isinstance(item, dict) and item.get("role") == "user"
                and item.get("content") == manifest.get("new_read_message") for item in messages
            ), "original new Agent read turn is not confirmed; do not retry")

    body, events = wait_for_answer_ids(
        client, str(manifest["new_conversation_id"]), job_id, str(manifest["result_artifact_id"]),
    )
    require_only_activities(events, {"读取回测状态"})
    read_calls = activity_events(events, "读取回测状态")
    reads = [item for item in read_calls if item.get("payload", {}).get("state") == "completed"]
    require(len(read_calls) == 2 and len(reads) == 1
            and sum(item.get("payload", {}).get("state") == "started" for item in read_calls) == 1,
            "new Agent trace does not prove one successful exact Job read")
    answer = assistant_text(body)
    require(job_id in answer and str(manifest["result_artifact_id"]) in answer
            and "completed" in answer.lower(),
            "new Agent answer did not identify the exact completed Job and Artifact")
    jobs = backtests_for_task(client, str(manifest["task_id"]))
    require(len(jobs) == 1 and jobs[0].get("job_id") == job_id
            and jobs[0].get("status") == "completed"
            and jobs[0].get("result_artifact_id") == manifest["result_artifact_id"],
            "new Agent read changed Job state or a duplicate Job exists")
    manifest["new_agent_read_activity_observed"] = True
    manifest["agent_read_job_binding"] = (
        "not_proven_normalized_trace_omits_tool_arguments_and_results"
    )
    manifest["stage"] = "completed"
    save(path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "submit", "finish"))
    args = parser.parse_args()
    values, origin, path, expected_workspace = configure()
    username = values.get("BYQ_BOOTSTRAP_ADMIN_USERNAME", "admin")
    password = values.get("BYQ_BOOTSTRAP_ADMIN_PASSWORD", "")
    require(bool(username and password), "local environment has no bootstrap admin identity")
    client = ProductClient(origin, username, password)
    client.verify_identity(expected_workspace)
    scope = values["BYQ_DEV_SCOPE"]
    if args.stage == "prepare":
        manifest = prepare(client, path, scope, expected_workspace)
    else:
        manifest = load_manifest(path, scope, expected_workspace, username)
        if args.stage == "submit":
            manifest = submit(client, path, manifest)
        else:
            manifest = finish(client, path, manifest)
    summary = {
        "schema_version": "phase15-golden-d-evidence.v2",
        "stage": manifest.get("stage"),
        "scope": scope,
        "workspace_id": manifest.get("workspace_id"),
        "task_id": manifest.get("task_id"),
        "pool_id": manifest.get("pool_id"),
        "pool_snapshot_id": manifest.get("pool_snapshot_id"),
        "backtest_task_id": manifest.get("backtest_task_id"),
        "strategy_version_artifact_id": manifest.get("strategy_version_artifact_id"),
        "approval_artifact_id": manifest.get("approval_artifact_id"),
        "security_master_job_id": manifest.get("security_master_job_id"),
        "pre_create_readiness": manifest.get("pre_create_readiness", {}).get("verdict")
        if isinstance(manifest.get("pre_create_readiness"), dict) else None,
        "agent_task_job_binding": manifest.get("agent_task_job_binding"),
        "old_conversation_id": manifest.get("old_conversation_id"),
        "backtest_job_id": manifest.get("backtest_job_id"),
        "old_conversation_deleted": manifest.get("old_conversation_deleted", False),
        "result_artifact_id": manifest.get("result_artifact_id"),
        "new_conversation_id": manifest.get("new_conversation_id"),
        "new_agent_read_activity_observed": manifest.get("new_agent_read_activity_observed", False),
        "agent_read_job_binding": manifest.get("agent_read_job_binding"),
        "next_operator_step": (
            "read-only verify exactly one 20240102 market repair row, then resume data-worker and rerun submit"
            if manifest.get("stage") == "repair_scope_review_pending" else None
        ),
        "manifest": str(path),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except EvidenceError as error:
        raise SystemExit(f"FAIL-CLOSED: {error}") from error
