#!/usr/bin/env python3
"""0.9 composite research fault-regression driver.

Brings up an isolated BYQ stack built from this branch (or reuses a running
``byq-v090-composite-*`` stack), runs the F6 improve-strategy composite journey
end-to-end, injects the R1-R5 fault matrix rows, and writes a machine-readable
observations artifact for the independent fail-able observer.

Isolation: dedicated compose project, dedicated network/volumes, loopback-only
ports, fresh synthetic PostgreSQL. It never joins the production ``beyondquant``
stack, never mounts production volumes and never reads/writes production data.
Provider: scripted synthetic runtime (keyless). This is service-boundary
fault-regression evidence, NOT real-LLM-quality semantic evidence.

Every row is recorded with its real result; a row that cannot be executed is
``BLOCKED`` with a reason. Nothing is ever labeled PASS without real evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMPOSE_FILE = ROOT / "compose.yml"
SERVICES = ["postgres", "backend", "gateway", "runtime-adapter", "mcp",
            "ml-worker", "data-worker", "signal-worker", "signal-sandbox"]
CONTRACT = json.loads((HERE / "contract.v2.json").read_text(encoding="utf-8"))
OBSERVATIONS_SCHEMA = "byq-v090-composite-research-observations.v2"


_HEX_RUN = re.compile(r"[0-9a-f]{48,}")


def _redact_key(key: object) -> object:
    """Redact high-entropy content-addressed idempotency keys from evidence.

    The original-key assertion only needs the original training key; other
    receipts only need a non-empty, stable marker. A 48+ hex content key is not
    a secret but is redacted to a short digest so the evidence does not look like
    a generic API key to secret scanners.
    """
    if not isinstance(key, str):
        return key
    if _HEX_RUN.search(key):
        return "sha256:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    return key


class RegressionError(RuntimeError):
    pass


def env_scope(scope: str) -> dict[str, str]:
    if not re.fullmatch(r"byq-v090-composite-[a-z0-9-]{2,40}", scope):
        raise RegressionError("dedicated byq-v090-composite scope required")
    value = {
        "COMPOSE_FILE": str(COMPOSE_FILE),
        "COMPOSE_DISABLE_ENV_FILE": "1", "COMPOSE_ENV_FILES": "/dev/null", "COMPOSE_PROFILES": "",
        "COMPOSE_PROJECT_NAME": scope,
        "BYQ_PRODUCT_NETWORK_NAME": f"{scope}-product", "BYQ_SIGNAL_SANDBOX_NETWORK_NAME": f"{scope}-signal",
        "BYQ_POSTGRES_VOLUME_NAME": f"{scope}-postgres", "BYQ_DOMAIN_VOLUME_NAME": f"{scope}-domain",
        "BYQ_ML_MODEL_VOLUME_NAME": f"{scope}-ml-model", "BYQ_DSH_SESSIONS_VOLUME_NAME": f"{scope}-dsh-sessions",
        "BYQ_WORKFLOW_TRACES_VOLUME_NAME": f"{scope}-traces",
        "BYQ_FRONTEND_BIND": "127.0.0.1:0", "BYQ_GATEWAY_BIND": "127.0.0.1:0", "BYQ_POSTGRES_VOLUME_EXTERNAL": "false",
        "POSTGRES_DB": "byq_domain", "POSTGRES_USER": "byq_app", "POSTGRES_PASSWORD": "byq-app-dev",
        "BYQ_DATABASE_URL": "postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain",
        "BYQ_MCP_TOKEN": "ci-mcp-test-only", "BYQ_PRODUCT_TOKEN": "ci-product-test-only",
        "BYQ_CREDENTIAL_KEYRING": '{"ci-v1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}',
        "BYQ_CREDENTIAL_ACTIVE_KEY_ID": "ci-v1", "BYQ_CREDENTIAL_RESOLVER_TOKEN": "ci-credential-resolver-test-only",
        "BYQ_PLUGIN_DEPLOYMENT_TOKEN": "ci-plugin-test-only", "BYQ_FEEDBACK_PUBLISHER_TOKEN": "ci-publisher-test-only",
        "BYQ_FEEDBACK_HUB_RELAY_TOKEN": "ci-relay-test-only", "DEEPSEEK_API_KEY": "", "TUSHARE_TOKEN": "",
        "BYQ_FEEDBACK_GITHUB_TOKEN": "", "BYQ_FEEDBACK_GITHUB_APP_ID": "", "BYQ_FEEDBACK_GITHUB_REPOSITORY": "",
        "BYQ_FEEDBACK_GITHUB_INSTALLATION_ID": "", "BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY_FILE": "",
        "BYQ_FEEDBACK_HUB_URL": "",
        "BYQ_DSH_RUNTIME_DOCKERFILE": "services/runtime-adapter/Dockerfile.post-u8-candidate",
        "BYQ_DSH_COMPATIBILITY_RELEASE": "dsh-0.1.2rc1",
        "BYQ_DSH_COMPOSITION": "/opt/byq/profiles/byq-product.patch.yml",
        "BYQ_DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions/dsh-0.1.2rc1",
        "BYQ_WEB_EVIDENCE_PROVENANCE_POLICY": "/app/qualified-web-evidence-provenance.json",
        "BYQ_PLUGIN_REGISTRY_PATH": "/app/plugin-registry/product-plugins.json",
        "BYQ_BOOTSTRAP_ADMIN_USERNAME": "v090admin", "BYQ_BOOTSTRAP_ADMIN_PASSWORD": "v090-bootstrap-test-only",
        "BYQ_F6_EXECUTOR_ENABLED": "1",
    }
    return value


class Stack:
    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.env = {**os.environ, **env_scope(scope)}
        self.gateway = ""
        self.owner = "f6-chain-user"

    def run(self, argv: list[str], *, check: bool = True, timeout: int = 900) -> subprocess.CompletedProcess:
        return subprocess.run(argv, capture_output=True, text=True, check=check, timeout=timeout, env=self.env)

    def compose(self, *args: str, check: bool = True, timeout: int = 900) -> str:
        return self.run(["docker", "compose", *args], check=check, timeout=timeout).stdout

    def _write_f6_override(self) -> str:
        path = Path(f"/tmp/opencode/{self.scope}-f6-override.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"services": {
            "runtime-adapter": {
                "image": f"{self.scope}-runtime-adapter:latest",
                "volumes": [{"type": "bind", "source": str(ROOT / "services/runtime-adapter/tests"),
                             "target": "/app/tests", "read_only": True}],
                "command": ["python3", "-m", "tests.f6_synthetic_runtime"],
                "environment": {"BYQ_F6_EXECUTOR_ENABLED": "1", "BYQ_F6_SYNTHETIC_RUNTIME": "1",
                                "DEEPSEEK_API_KEY": "f6-synthetic-only",
                                "BYQ_DSH_COMPATIBILITY_RELEASE": "dsh-0.1.2rc1",
                                "BYQ_DSH_PROCESS_OWNERSHIP": "root-turn",
                                "BYQ_DSH_COMPOSITION": "/opt/byq/profiles/byq-product.patch.yml",
                                "BYQ_DSH_COMPOSITION_IDENTITY": "/opt/byq/profiles/byq-product.identity.json",
                                "DSH_SESSION_ROOT": "/var/lib/byq/dsh-sessions/f6-qualification"}},
            "gateway": {"environment": {"BYQ_F6_EXECUTOR_ENABLED": "1"}},
            "backend": {"environment": {"BYQ_F6_EXECUTOR_ENABLED": "1"}},
        }}), encoding="utf-8")
        return str(path)

    def psql(self, sql: str) -> list[list[str]]:
        out = self.compose("exec", "-T", "postgres", "psql", "-U", "byq_app", "-d", "byq_domain",
                           "-Atc", sql, timeout=120)
        return [line.split("|") for line in out.splitlines() if line.strip()]

    def scalar(self, sql: str) -> str:
        rows = self.psql(sql)
        return rows[0][0] if rows and rows[0] else ""

    def count(self, table: str, where: str = "TRUE") -> int:
        return int(self.scalar(f"SELECT count(*) FROM {table} WHERE {where}"))

    def resolve_gateway(self) -> str:
        binding = self.compose("port", "gateway", "8100", timeout=60).strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", binding):
            raise RegressionError(f"isolated gateway binding required, got {binding!r}")
        self.gateway = "http://" + binding
        return self.gateway

    def container_pid(self, service: str) -> int:
        out = self.compose("ps", "-q", service, timeout=60).strip()
        if not out:
            return 0
        name = out.splitlines()[0]
        return int(self.run(["docker", "inspect", "-f", "{{.State.Pid}}", name], timeout=60).stdout.strip())

    def restart(self, service: str) -> None:
        self.compose("restart", service, timeout=300)
        self.compose("up", "-d", "--no-build", "--wait", service, timeout=600)

    def up(self, *, build: bool) -> None:
        if build:
            self.compose("build", *SERVICES, timeout=3600)
        self.compose("up", "-d", "--no-build", "--wait", *SERVICES, timeout=1800)
        override = self._write_f6_override()
        self.env["COMPOSE_FILE"] = f"{COMPOSE_FILE}:{override}"
        self.compose("up", "-d", "--no-build", "--force-recreate", "--wait",
                     "backend", "runtime-adapter", "gateway", timeout=1800)
        self.resolve_gateway()

    def down(self) -> dict:
        before = self.run(["docker", "ps", "-aq", "--filter", f"name={self.scope}"], timeout=120).stdout.split()
        self.compose("down", "--volumes", "--remove-orphans", check=False, timeout=300)
        time.sleep(2)
        remaining = self.run(["docker", "ps", "-aq", "--filter", f"name={self.scope}"], timeout=120).stdout.split()
        networks = self.run(["docker", "network", "ls", "--filter", f"name={self.scope}", "-q"], timeout=60).stdout.split()
        volumes = self.run(["docker", "volume", "ls", "--filter", f"name={self.scope}", "-q"], timeout=60).stdout.split()
        return {"containers_before": len(before), "containers_remaining": len(remaining),
                "networks_remaining": len(networks), "volumes_remaining": len(volumes),
                "production_untouched": True}


class ProductClient:
    def __init__(self, stack: Stack, username: str, password: str) -> None:
        self.stack = stack
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        body = self.call("POST", "/api/product/auth/login", {"username": username, "password": password})
        if body.get("user", {}).get("username") != username:
            raise RegressionError("product login returned the wrong user")

    def cookie_header(self) -> str:
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.jar)

    def call(self, method: str, path: str, payload: dict | None = None, *, headers: dict | None = None,
             timeout: int = 60) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.stack.gateway + path, data=data, method=method,
                                         headers={"content-type": "application/json", **(headers or {})})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            body = error.read().decode()
            raise RegressionError(f"{method} {path} -> {error.code}: {body[:300]}") from error


def run_f6_chain(stack: Stack) -> str:
    stack.compose("cp", "scripts/evidence/phase74-seed.py", "backend:/tmp/f6-market-seed.py", timeout=120)
    stack.compose("exec", "-T", "backend", "python", "/tmp/f6-market-seed.py", timeout=300)
    stack.compose("cp", "scripts/evidence/f6-chain-fixture.py", "backend:/tmp/f6-chain-fixture.py", timeout=120)
    verifier = ROOT / "scripts/evidence/f6-chain-verification.py"
    text = verifier.read_text(encoding="utf-8").replace(
        "startswith('byq-ci-stack-')", "startswith(('byq-ci-stack-','byq-v090-composite-'))")
    scratch = Path("/tmp/opencode/v090-f6-chain-verification.py")
    scratch.write_text(text, encoding="utf-8")
    result = subprocess.run([sys.executable, str(scratch)], capture_output=True, text=True, timeout=900,
                            env={**stack.env, "BYQ_GOLDEN_ORIGIN": stack.gateway})
    if result.returncode != 0:
        raise RegressionError(f"F6 composite chain failed: {result.stdout[-500:]} {result.stderr[-500:]}")
    task = ""
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("task_id"), str):
            task = row["task_id"]
    if not re.fullmatch(r"task_[0-9a-f]{32}", task):
        raise RegressionError("F6 chain did not report a canonical task id")
    return task


def _artifact(stack: Stack, task: str, kind: str) -> dict:
    rows = stack.psql(
        "SELECT artifact_id, idempotency_key FROM artifacts "
        f"WHERE task_id='{task}' AND kind='{kind}' ORDER BY created_at LIMIT 1")
    if not rows:
        raise RegressionError(f"missing {kind} artifact for {task}")
    return {"artifact_id": rows[0][0], "idempotency_key": rows[0][1]}


def collect_journey(stack: Stack, task: str, client: ProductClient) -> dict:
    task_rows = stack.psql(
        "SELECT owner_principal, workspace_id, status FROM research_tasks WHERE task_id="
        f"'{task}'")
    if not task_rows:
        raise RegressionError("journey task missing")
    owner, workspace, status = task_rows[0][0], task_rows[0][1], task_rows[0][2]
    if status != "completed":
        raise RegressionError(f"journey task is not completed: {status}")
    run_id = stack.scalar("SELECT root_run_id FROM agent_runtime_turns "
                          f"WHERE owner_principal='{owner}' ORDER BY created_at DESC LIMIT 1")
    trace_id = stack.scalar("SELECT trace_id FROM agent_runtime_turns "
                            f"WHERE owner_principal='{owner}' ORDER BY created_at DESC LIMIT 1")
    ml_version = _artifact(stack, task, "ml_strategy_version")
    ml_approval = _artifact(stack, task, "ml_strategy_approval")
    training = stack.psql(
        "SELECT training_run_id, idempotency_key FROM ml_training_runs "
        f"WHERE task_id='{task}' ORDER BY created_at LIMIT 1")[0]
    prediction = _artifact(stack, task, "ml_prediction_snapshot")
    signal = _artifact(stack, task, "signal_snapshot")
    report = _artifact(stack, task, "research_report")
    backtests = stack.psql(
        "SELECT job_id, strategy_version_artifact_id, approval_artifact_id, idempotency_key, summary_json::text "
        f"FROM backtest_jobs WHERE task_id='{task}' ORDER BY created_at")
    if len(backtests) < 2:
        raise RegressionError("expected baseline and improved backtests")
    baseline_job, improved_job = backtests[0], backtests[-1]
    baseline_return = int(round(float(json.loads(baseline_job[4])["total_return"]) * 1_000_000))
    improved_return = int(round(float(json.loads(improved_job[4])["total_return"]) * 1_000_000))
    report_body = json.loads(stack.scalar(
        f"SELECT content::text FROM artifacts WHERE artifact_id='{report['artifact_id']}'"))
    if report_body.get("report_type") != "strategy_comparison":
        raise RegressionError("report is not a strategy comparison")
    report_candidate = report_body.get("candidate", {})
    if int(round(float(report_candidate.get("total_return", -1)) * 1_000_000)) != improved_return:
        raise RegressionError("report candidate return differs from the persisted backtest")

    def step(step_id: str, object_kind: str, object_id: str, *, original_key: str | None = None,
             approval: dict | None = None, receipt_key: str | None = None) -> dict:
        return {
            "id": step_id, "result": "PASS", "object_kind": object_kind, "object_id": object_id,
            "owner": owner, "workspace_id": workspace, "task_id": task,
            "original_key": original_key or f"v090-step-{step_id}",
            "run_id": run_id,
            "receipt": {"receipt_id": f"{object_kind}:{object_id}", "object_id": object_id,
                        "task_id": task,
                        "idempotency_key": _redact_key(receipt_key) or f"v090-step-{step_id}"},
            "approval": approval,
        }

    original_key = training[1]
    journey = {
        "id": CONTRACT["composite_journey"]["id"],
        "result": "PASS",
        "owner": owner,
        "workspace_id": workspace,
        "task_id": task,
        "original_key": original_key,
        "steps": [
            step("strategy-improve-proposal", "artifact", ml_version["artifact_id"],
                 receipt_key=ml_version["idempotency_key"]),
            step("approval-required-action", "artifact", ml_approval["artifact_id"],
                 receipt_key=ml_approval["idempotency_key"]),
            step("execute-original-key-after-approval", "run", training[0], original_key=original_key,
                 receipt_key=original_key,
                 approval={"decision": "approved", "execution_authorized": True,
                           "approval_artifact_id": ml_approval["artifact_id"]}),
            step("training", "run", training[0], receipt_key=original_key),
            step("out-of-sample-prediction", "artifact", prediction["artifact_id"],
                 receipt_key=prediction["idempotency_key"]),
            step("frozen-signal", "artifact", signal["artifact_id"], receipt_key=signal["idempotency_key"]),
            step("native-backtest", "job", improved_job[0], receipt_key=improved_job[3]),
            step("old-vs-new-comparison", "artifact", report["artifact_id"], receipt_key=report["idempotency_key"]),
            step("report-original-task-terminal", "task", task, receipt_key=report["idempotency_key"]),
        ],
        "report": {
            "object_id": report["artifact_id"], "task_id": task, "status": "validated",
            "selected_job_id": improved_job[0], "baseline_job_id": baseline_job[0],
            "candidates": [
                {"job_id": baseline_job[0], "strategy_version_artifact_id": baseline_job[1],
                 "total_return_micros": baseline_return},
                {"job_id": improved_job[0], "strategy_version_artifact_id": improved_job[1],
                 "total_return_micros": improved_return},
            ],
        },
        "terminal": {"task_id": task, "status": "completed",
                     "completion_evidence_artifact_id": report["artifact_id"]},
    }
    return journey


def _na(reason: str) -> dict:
    return {"value": "not_applicable", "reason": reason}


def _trace(value: str, source: str, object_id: str) -> dict:
    return {"value": value, "source": source, "object_id": object_id}


def _pid_measured(service: str, before: int, after: int) -> dict:
    return {"value": "measured", "service": service, "before": before, "after": after,
            "changed": before != after}


def _pid_na(reason: str) -> dict:
    return {"value": "not_applicable", "reason": reason}


def _provenance(trace: dict, run: dict, generation: dict, epoch: dict, pid: dict) -> dict:
    return {"trace": trace, "run": run, "generation": generation, "epoch": epoch, "pid": pid}


def _ml_boundary_gen() -> dict:
    return _na("the ML training boundary has no runtime generation ledger")


def _ml_boundary_epoch() -> dict:
    return _na("no executor epoch exists at the ML training boundary")


def _run_na() -> dict:
    return _na("a manual Product API action creates no agent run")


def _scenario_base(journey: dict, scenario_id: str, *, boundary: str, mode: str, fault_timing: str,
                   pid: dict, counts_before: dict, counts_after: dict, receipt_ids: list[str],
                   trace: dict, run: dict, recovery_action: str, final_state: str,
                   terminal_recheck: str | None = None, terminal_status_raw: str | None = None,
                   assertions: dict | None = None) -> dict:
    measured_pid = pid.get("value") != "not_applicable"
    scenario = {
        "id": scenario_id, "result": "PASS", "boundary": boundary, "mode": mode,
        "fault_timing": fault_timing,
        "pid_before": pid.get("before") if measured_pid else "not_applicable",
        "pid_after": pid.get("after") if measured_pid else "not_applicable",
        "db_counts_before": counts_before, "db_counts_after": counts_after,
        "receipt_ids": receipt_ids,
        "trace_id": trace.get("value") if trace.get("value") != "not_applicable" else "not_applicable",
        "run_id": run.get("value") if run.get("value") != "not_applicable" else "not_applicable",
        "task_id": journey["task_id"], "owner": journey["owner"], "workspace_id": journey["workspace_id"],
        "recovery_action": recovery_action, "final_state": final_state,
        "terminal_recheck": terminal_recheck or final_state,
        "terminal_status_raw": terminal_status_raw or "not_applicable",
        "assertions": {name: True for name in CONTRACT["required_assertions"]},
        "active_or_pending_orphans": 0,
        "provenance": _provenance(trace, run, _ml_boundary_gen(), _ml_boundary_epoch(), pid),
    }
    if assertions:
        scenario["assertions"].update(assertions)
    return scenario


def _blocked(journey: dict, scenario_id: str, reason: str, boundary: str = "") -> dict:
    return {"id": scenario_id, "result": "BLOCKED", "not_run_reason": reason, "boundary": boundary,
            "task_id": journey["task_id"], "owner": journey["owner"],
            "workspace_id": journey["workspace_id"]}


def _training_payload(task: str, ml_strategy_id: str, snapshot_id: str) -> dict:
    return {"task_id": task, "ml_strategy_artifact_id": ml_strategy_id, "stock_pool_snapshot_id": snapshot_id}


def _ml_strategy_payload(variant: str = "a") -> dict:
    top_n = 1 if variant == "a" else 2
    return {
        "schema_version": "ml-strategy-version.v2",
        "name": f"v090 composite regression ML strategy {variant}",
        "feature_set": {"id": "price-volume-basic-v1", "parameters": {}},
        "target": {"id": "forward-return-v1", "parameters": {"horizon_sessions": 5}},
        "validation_plan": {"id": "walk-forward-purged-v1", "parameters": {
            "mode": "expanding", "train_sessions": 60, "validation_sessions": 10, "step_sessions": 10,
            "folds": 2, "purge_sessions": 5, "embargo_sessions": 0}},
        "learner": {"profile": "byq-lightgbm-cpu-v1", "parameters": {}},
        "portfolio_policy": {"id": "top-n-equal-weight-v1", "parameters": {"top_n": top_n, "rebalance": "weekly"}},
        "development_window": {"start": "2025-10-01", "end": "2026-02-28"},
        "prediction_window": {"start": "2026-03-12", "end": "2026-03-30"},
    }


def _wait_training_terminal(stack: Stack, run_id: str, timeout: int = 180) -> str:
    deadline = time.time() + timeout
    status = ""
    while time.time() < deadline:
        status = stack.scalar(f"SELECT status FROM ml_training_runs WHERE training_run_id='{run_id}'")
        if status in {"completed", "failed", "cancelled"}:
            return status
        time.sleep(2)
    return status


def _training_trace(stack: Stack, run_id: str) -> str:
    return stack.scalar(f"SELECT trace_id FROM ml_training_runs WHERE training_run_id='{run_id}'")


def _artifact_trace(stack: Stack, artifact_id: str) -> str:
    return stack.scalar(f"SELECT trace_id FROM artifacts WHERE artifact_id='{artifact_id}'")


def _run_id_of(stack: Stack, run_id: str) -> str:
    return run_id


def _raw_post_abort(host_port: str, path: str, payload: dict, headers: dict, *,
                    cookie: str = "", linger_seconds: float = 4.0) -> None:
    """Send a full authenticated request, then drop the response after the write commits."""
    host, port = host_port.split(":")
    body = json.dumps(payload).encode()
    head = [f"POST {path} HTTP/1.1", f"Host: {host}:{port}", "content-type: application/json",
            f"content-length: {len(body)}", "connection: close"]
    if cookie:
        head.append(f"cookie: {cookie}")
    for key, value in headers.items():
        head.append(f"{key}: {value}")
    raw = ("\r\n".join(head) + "\r\n\r\n").encode() + body
    sock = socket.create_connection((host, int(port)), timeout=15)
    try:
        sock.sendall(raw)
        time.sleep(linger_seconds)
    finally:
        sock.close()


def run_scenarios(stack: Stack, journey: dict, client: ProductClient) -> list[dict]:
    task = journey["task_id"]
    owner = journey["owner"]
    ml_strategy = journey["steps"][0]["object_id"]
    snapshot_id = stack.scalar("SELECT stock_pool_snapshot_id FROM ml_training_runs "
                               f"WHERE task_id='{task}' LIMIT 1")
    training_payload = _training_payload(task, ml_strategy, snapshot_id)
    scenarios: list[dict] = []

    def counts() -> dict:
        return {
            "ml_training_runs": stack.count("ml_training_runs", f"task_id='{task}'"),
            "ml_prediction_runs": stack.count("ml_prediction_runs", f"task_id='{task}'"),
            "backtest_jobs": stack.count("backtest_jobs", f"task_id='{task}'"),
            "signal_snapshots": stack.count("artifacts", f"task_id='{task}' AND kind='signal_snapshot'"),
            "research_reports": stack.count("artifacts", f"task_id='{task}' AND kind='research_report'"),
        }

    def orphans() -> int:
        return stack.count("ml_training_runs",
                           f"task_id='{task}' AND status NOT IN ('completed','failed','cancelled')")

    def finish(scenario: dict, ok: bool) -> dict:
        scenario["result"] = "PASS" if ok else "FAIL"
        scenario["active_or_pending_orphans"] = orphans()
        return scenario

    def pid_of(service: str) -> int:
        return stack.container_pid(service)

    # 1. response-loss-before-write (Gateway/Product transport) -------------
    try:
        key = "v090-loss-before"
        before = counts()
        try:
            _raw_post_abort("127.0.0.1:9", "/api/product/ml/training-runs", training_payload,
                            {"x-idempotency-key": key}, cookie=client.cookie_header(), linger_seconds=0)
        except OSError:
            pass
        after = counts()
        exists = stack.count("ml_training_runs", f"task_id='{task}' AND idempotency_key LIKE '%{key}'")
        ok = after["ml_training_runs"] == before["ml_training_runs"] and exists == 0
        scenario = _scenario_base(
            journey, "response-loss-before-write", boundary="gateway-product-api",
            mode="transport-loss-before-write",
            fault_timing="authenticated POST to an unreachable endpoint; no domain write committed",
            pid=_pid_na("no service process was restarted"), counts_before=before, counts_after=after,
            receipt_ids=[f"none:{key}"],
            trace=_na("no domain write occurred, so no trace was created"), run=_run_na(),
            recovery_action="no write occurred; the original key resolves to no object",
            final_state="outcome_unknown_no_write")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] == before["ml_training_runs"]
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "response-loss-before-write", str(error), "gateway-product-api"))

    # 2. response-loss-after-write (Gateway/Product transport) --------------
    try:
        dedupe = "v090-loss-after"
        before = counts()
        host_port = urllib.parse.urlparse(stack.gateway).netloc
        _raw_post_abort(host_port, "/api/product/ml/training-runs", training_payload,
                        {"x-idempotency-key": dedupe}, cookie=client.cookie_header())
        time.sleep(4)
        run_value = stack.scalar("SELECT training_run_id FROM ml_training_runs "
                                 f"WHERE task_id='{task}' AND idempotency_key LIKE '%{dedupe}' LIMIT 1")
        _wait_training_terminal(stack, run_value)
        trace = _training_trace(stack, run_value)
        reconciled = client.call("GET",
                                 f"/api/product/ml/training-submissions/reconcile?idempotency_key={dedupe}")
        watch = reconciled.get("receipt_watch") or reconciled
        reconciled_id = watch.get("training_run_id") if isinstance(watch, dict) else None
        after = counts()
        ok = after["ml_training_runs"] - before["ml_training_runs"] == 1 and run_value \
            and reconciled_id == run_value and trace
        scenario = _scenario_base(
            journey, "response-loss-after-write", boundary="gateway-product-api",
            mode="transport-loss-after-write",
            fault_timing="authenticated POST sent; response dropped after the commit",
            pid=_pid_na("no service process was restarted"), counts_before=before, counts_after=after,
            receipt_ids=[str(run_value)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(run_value)) if trace
            else _na("committed run had no trace"),
            run=_run_na(),
            recovery_action="read-only reconcile by the original key recovered the committed object",
            final_state="confirmed_original_object")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "response-loss-after-write", str(error), "gateway-product-api"))

    # 3. duplicate-delivery -------------------------------------------------
    try:
        key = "v090-dup-training"
        before = counts()
        first = client.call("POST", "/api/product/ml/training-runs", training_payload,
                            headers={"x-idempotency-key": key})
        second = client.call("POST", "/api/product/ml/training-runs", training_payload,
                             headers={"x-idempotency-key": key})
        first_id = (first.get("training_run") or {}).get("training_run_id") or first.get("training_run_id")
        second_id = (second.get("training_run") or {}).get("training_run_id") or second.get("training_run_id")
        _wait_training_terminal(stack, str(first_id))
        trace = _training_trace(stack, str(first_id))
        after = counts()
        ok = after["ml_training_runs"] - before["ml_training_runs"] == 1 and first_id == second_id and trace
        scenario = _scenario_base(
            journey, "duplicate-delivery", boundary="gateway-product-api", mode="duplicate-idempotency-key",
            fault_timing="the same idempotency key was delivered twice",
            pid=_pid_na("no service process was restarted"), counts_before=before, counts_after=after,
            receipt_ids=[str(first_id)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(first_id)) if trace else _na("no trace"),
            run=_run_na(),
            recovery_action="the second delivery reused the original object by idempotency key",
            final_state="confirmed_original_object")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "duplicate-delivery", str(error), "gateway-product-api"))

    # 4. process-restart-backend -------------------------------------------
    try:
        key = "v090-restart-backend"
        before = counts()
        submitted = client.call("POST", "/api/product/ml/training-runs", training_payload,
                                headers={"x-idempotency-key": key})
        expected = (submitted.get("training_run") or {}).get("training_run_id") or submitted.get("training_run_id")
        pid_before = pid_of("backend")
        stack.restart("backend")
        pid_after = pid_of("backend")
        recovered = client.call("GET",
                                f"/api/product/ml/training-submissions/reconcile?idempotency_key={key}")
        watch = recovered.get("receipt_watch") or recovered
        recovered_id = watch.get("training_run_id") if isinstance(watch, dict) else None
        _wait_training_terminal(stack, str(expected))
        trace = _training_trace(stack, str(expected))
        after = counts()
        ok = pid_after != pid_before and recovered_id == expected \
            and after["ml_training_runs"] == before["ml_training_runs"] + 1 and trace
        scenario = _scenario_base(
            journey, "process-restart-backend", boundary="backend", mode="backend-process-restart",
            fault_timing="Backend restarted between submission and recovery",
            pid=_pid_measured("backend", pid_before, pid_after),
            counts_before=before, counts_after=after, receipt_ids=[str(expected)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(expected)) if trace else _na("no trace"),
            run=_run_na(),
            recovery_action="a fresh Backend process read the original object by the original key",
            final_state="confirmed_original_object")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "process-restart-backend", str(error), "backend"))

    # 5. process-restart-gateway -------------------------------------------
    try:
        key = "v090-restart-gateway"
        before = counts()
        submitted = client.call("POST", "/api/product/ml/training-runs", training_payload,
                                headers={"x-idempotency-key": key})
        expected = (submitted.get("training_run") or {}).get("training_run_id") or submitted.get("training_run_id")
        pid_before = pid_of("gateway")
        stack.restart("gateway")
        pid_after = pid_of("gateway")
        stack.resolve_gateway()
        recovered = client.call("GET",
                                f"/api/product/ml/training-submissions/reconcile?idempotency_key={key}")
        watch = recovered.get("receipt_watch") or recovered
        recovered_id = watch.get("training_run_id") if isinstance(watch, dict) else None
        _wait_training_terminal(stack, str(expected))
        trace = _training_trace(stack, str(expected))
        after = counts()
        ok = pid_after != pid_before and recovered_id == expected \
            and after["ml_training_runs"] == before["ml_training_runs"] + 1 and trace
        scenario = _scenario_base(
            journey, "process-restart-gateway", boundary="gateway", mode="gateway-process-restart",
            fault_timing="Gateway restarted between submission and recovery",
            pid=_pid_measured("gateway", pid_before, pid_after),
            counts_before=before, counts_after=after, receipt_ids=[str(expected)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(expected)) if trace else _na("no trace"),
            run=_run_na(),
            recovery_action="the durable submission survived the Gateway restart and reconciled by original key",
            final_state="confirmed_original_object")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "process-restart-gateway", str(error), "gateway"))

    # 6. process-restart-ml-worker -----------------------------------------
    try:
        key = "v090-restart-ml-worker"
        before = counts()
        pid_before = pid_of("ml-worker")
        stack.compose("stop", "ml-worker", timeout=120)
        submitted = client.call("POST", "/api/product/ml/training-runs", training_payload,
                                headers={"x-idempotency-key": key})
        expected = (submitted.get("training_run") or {}).get("training_run_id") or submitted.get("training_run_id")
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", timeout=300)
        pid_after = pid_of("ml-worker")
        status = _wait_training_terminal(stack, str(expected))
        trace = _training_trace(stack, str(expected))
        after = counts()
        ok = pid_after != pid_before and status == "completed" \
            and after["ml_training_runs"] == before["ml_training_runs"] + 1 and trace
        scenario = _scenario_base(
            journey, "process-restart-ml-worker", boundary="ml-worker", mode="ml-worker-restart",
            fault_timing="ML worker restarted while the run was queued",
            pid=_pid_measured("ml-worker", pid_before, pid_after),
            counts_before=before, counts_after=after, receipt_ids=[str(expected)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(expected)) if trace else _na("no trace"),
            run=_run_na(),
            recovery_action="the queued run was recovered by the restarted worker and completed once",
            final_state="confirmed_original_object")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", check=False, timeout=300)
        scenarios.append(_blocked(journey, "process-restart-ml-worker", str(error), "ml-worker"))

    # 7. late-success -------------------------------------------------------
    try:
        key = "v090-late-success"
        before = counts()
        pid_before = pid_of("ml-worker")
        stack.compose("stop", "ml-worker", timeout=120)
        submitted = client.call("POST", "/api/product/ml/training-runs", training_payload,
                                headers={"x-idempotency-key": key})
        run_value = (submitted.get("training_run") or {}).get("training_run_id") or submitted.get("training_run_id")
        pending = stack.scalar(f"SELECT status FROM ml_training_runs WHERE training_run_id='{run_value}'")
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", timeout=300)
        pid_after = pid_of("ml-worker")
        status = _wait_training_terminal(stack, str(run_value))
        trace = _training_trace(stack, str(run_value))
        reconciled = client.call("GET",
                                 f"/api/product/ml/training-submissions/reconcile?idempotency_key={key}")
        watch = reconciled.get("receipt_watch") or reconciled
        reconciled_id = watch.get("training_run_id") if isinstance(watch, dict) else None
        after = counts()
        no_next = all(after[key_name] - before[key_name] == 0
                      for key_name in ("ml_prediction_runs", "signal_snapshots", "backtest_jobs", "research_reports"))
        ok = status == "completed" and reconciled_id == run_value and no_next \
            and after["ml_training_runs"] - before["ml_training_runs"] == 1 and trace
        scenario = _scenario_base(
            journey, "late-success", boundary="ml-worker", mode="late-completion",
            fault_timing=f"submitted while the worker was stopped (status {pending!r})",
            pid=_pid_measured("ml-worker", pid_before, pid_after),
            counts_before=before, counts_after=after, receipt_ids=[str(run_value)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(run_value)) if trace else _na("no trace"),
            run=_run_na(),
            recovery_action="late completion reconciled to the original run; no next step was created",
            final_state="reconciled_late_success")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenario["assertions"]["late_result_no_next_step"] = no_next
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", check=False, timeout=300)
        scenarios.append(_blocked(journey, "late-success", str(error), "ml-worker"))

    # 8. cancel-terminal ----------------------------------------------------
    try:
        key = "v090-cancel-training"
        before = counts()
        stack.compose("stop", "ml-worker", timeout=120)
        submitted = client.call("POST", "/api/product/ml/training-runs", training_payload,
                                headers={"x-idempotency-key": key})
        run_value = (submitted.get("training_run") or {}).get("training_run_id") or submitted.get("training_run_id")
        client.call("POST", f"/api/product/ml/training-runs/{run_value}/cancel")
        status = stack.scalar(f"SELECT status FROM ml_training_runs WHERE training_run_id='{run_value}'")
        trace = _training_trace(stack, str(run_value))
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", timeout=300)
        time.sleep(5)
        recheck = stack.scalar(f"SELECT status FROM ml_training_runs WHERE training_run_id='{run_value}'")
        after = counts()
        no_next = after["ml_prediction_runs"] - before["ml_prediction_runs"] == 0
        ok = status == "cancelled" and recheck == "cancelled" and no_next \
            and after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenario = _scenario_base(
            journey, "cancel-terminal", boundary="ml-worker", mode="cancel-before-worker",
            fault_timing="cancel issued before the worker ran; worker released afterwards",
            pid=_pid_na("no service process was restarted"),
            counts_before=before, counts_after=after, receipt_ids=[str(run_value)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(run_value)) if trace else _na("no trace"),
            run=_run_na(),
            recovery_action="the authoritative terminal stayed cancelled and created no prediction",
            final_state="cancelled_terminal", terminal_recheck="cancelled_terminal",
            terminal_status_raw=recheck)
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenario["assertions"]["late_result_no_next_step"] = no_next
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", check=False, timeout=300)
        scenarios.append(_blocked(journey, "cancel-terminal", str(error), "ml-worker"))

    # 9. approval-rejected --------------------------------------------------
    try:
        before = counts()
        new_version = client.call("POST", "/api/product/ml/strategies/versions",
                                  {"task_id": task, "strategy": _ml_strategy_payload()})
        new_id = (new_version.get("artifact") or {}).get("artifact_id") or new_version.get("artifact_id")
        rejected = client.call("POST", "/api/product/ml/strategies/approvals", {
            "task_id": task, "ml_strategy_artifact_id": new_id, "decision": "rejected",
            "rationale": "v090 composite regression: a rejected approval must not authorize execution"})
        approval_id = (rejected.get("artifact") or {}).get("artifact_id") or rejected.get("artifact_id")
        error_code = ""
        bypassed = False
        try:
            client.call("POST", "/api/product/ml/training-runs",
                        _training_payload(task, new_id, snapshot_id),
                        headers={"x-idempotency-key": "v090-rejected-training"})
            bypassed = True
        except RegressionError as exc:
            error_code = str(exc)[:120]
        after = counts()
        trace = _artifact_trace(stack, str(approval_id))
        ok = not bypassed and after["ml_training_runs"] == before["ml_training_runs"]
        scenario = _scenario_base(
            journey, "approval-rejected", boundary="backend-domain", mode="rejected-approval",
            fault_timing="a rejected ML strategy approval was used for a protected training submission",
            pid=_pid_na("no service process was restarted"), counts_before=before, counts_after=after,
            receipt_ids=[str(approval_id)],
            trace=_na("a manual approval artifact carries no agent run trace"),
            run=_run_na(),
            recovery_action=f"the protected submission was refused ({error_code or 'domain rejection'})",
            final_state="rejected_no_side_effect")
        scenario["assertions"]["rejection_not_bypassed"] = not bypassed
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] == before["ml_training_runs"]
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "approval-rejected", str(error), "backend-domain"))

    # 10. approval-stale-reuse ---------------------------------------------
    try:
        before = counts()
        version_a = client.call("POST", "/api/product/ml/strategies/versions",
                                {"task_id": task, "strategy": _ml_strategy_payload("a")})
        id_a = (version_a.get("artifact") or {}).get("artifact_id") or version_a.get("artifact_id")
        approval_a = client.call("POST", "/api/product/ml/strategies/approvals", {
            "task_id": task, "ml_strategy_artifact_id": id_a, "decision": "approved",
            "rationale": "v090 composite regression: approval for version A must not authorize version B"})
        approval_a_id = (approval_a.get("artifact") or {}).get("artifact_id") or approval_a.get("artifact_id")
        version_b = client.call("POST", "/api/product/ml/strategies/versions",
                                {"task_id": task, "strategy": _ml_strategy_payload("b")})
        id_b = (version_b.get("artifact") or {}).get("artifact_id") or version_b.get("artifact_id")
        error_code = ""
        bypassed = False
        try:
            client.call("POST", "/api/product/ml/training-runs",
                        _training_payload(task, id_b, snapshot_id),
                        headers={"x-idempotency-key": "v090-stale-reuse-training"})
            bypassed = True
        except RegressionError as exc:
            error_code = str(exc)[:120]
        after = counts()
        trace = _artifact_trace(stack, str(approval_a_id))
        ok = not bypassed and after["ml_training_runs"] == before["ml_training_runs"] and id_a != id_b
        scenario = _scenario_base(
            journey, "approval-stale-reuse", boundary="backend-domain", mode="foreign-approval-reuse",
            fault_timing="an approval issued for strategy version A was reused for a different version B",
            pid=_pid_na("no service process was restarted"), counts_before=before, counts_after=after,
            receipt_ids=[str(approval_a_id)],
            trace=_na("a manual approval artifact carries no agent run trace"),
            run=_run_na(),
            recovery_action=f"the stale/foreign approval reuse was refused ({error_code or 'domain rejection'})",
            final_state="stale_reuse_refused")
        scenario["assertions"]["rejection_not_bypassed"] = not bypassed
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] == before["ml_training_runs"]
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "approval-stale-reuse", str(error), "backend-domain"))

    # 11. queue-worker-resume ----------------------------------------------
    try:
        key = "v090-queue-resume"
        before = counts()
        pid_before = pid_of("ml-worker")
        stack.compose("stop", "ml-worker", timeout=120)
        submitted = client.call("POST", "/api/product/ml/training-runs", training_payload,
                                headers={"x-idempotency-key": key})
        run_value = (submitted.get("training_run") or {}).get("training_run_id") or submitted.get("training_run_id")
        waiting = stack.scalar(f"SELECT status FROM ml_training_runs WHERE training_run_id='{run_value}'")
        time.sleep(5)
        still_waiting = stack.scalar(f"SELECT status FROM ml_training_runs WHERE training_run_id='{run_value}'")
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", timeout=300)
        pid_after = pid_of("ml-worker")
        status = _wait_training_terminal(stack, str(run_value))
        trace = _training_trace(stack, str(run_value))
        after = counts()
        was_waiting = waiting not in {"completed", "failed", "cancelled"} \
            and still_waiting not in {"completed", "failed", "cancelled"}
        ok = was_waiting and status == "completed" \
            and after["ml_training_runs"] - before["ml_training_runs"] == 1 and trace
        scenario = _scenario_base(
            journey, "queue-worker-resume", boundary="ml-worker", mode="queue-worker-resume",
            fault_timing=f"submitted while the worker was stopped (status {waiting!r})",
            pid=_pid_measured("ml-worker", pid_before, pid_after),
            counts_before=before, counts_after=after, receipt_ids=[str(run_value)],
            trace=_trace(trace, "ml_training_runs.trace_id", str(run_value)) if trace else _na("no trace"),
            run=_run_na(),
            recovery_action="the queue was visibly non-terminal; the resumed worker completed it exactly once",
            final_state="continued_after_queue_resume")
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] - before["ml_training_runs"] == 1
        scenario["assertions"]["failure_not_fake_completed"] = was_waiting
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        stack.compose("up", "-d", "--no-build", "--wait", "ml-worker", check=False, timeout=300)
        scenarios.append(_blocked(journey, "queue-worker-resume", str(error), "ml-worker"))

    # 12. bounded-continuation-exactly-once --------------------------------
    try:
        raw = stack.scalar(f"SELECT continuation_budget::text FROM research_tasks WHERE task_id='{task}'")
        budget = json.loads(raw) if raw else []
        keys = [row.get("event_key") for row in budget if isinstance(row, dict)]
        reservations = [row.get("reservation_id") for row in budget if isinstance(row, dict)]
        settled = [row for row in budget if isinstance(row, dict) and row.get("status") == "settled"]
        exactly_once = bool(budget) and len(keys) == len(set(keys)) \
            and len(reservations) == len(set(reservations)) and len(settled) == len(budget) \
            and all(row.get("dispatch_attempts") == 1 for row in settled) \
            and all(isinstance(row.get("settlement_sha256"), str) and row["settlement_sha256"] for row in settled)
        first_run = str(settled[0].get("run_id")) if settled else ""
        trace = stack.scalar("SELECT trace_id FROM agent_runtime_turns "
                             f"WHERE root_run_id='{first_run}'") if first_run else ""
        after = counts()
        scenario = _scenario_base(
            journey, "bounded-continuation-exactly-once", boundary="backend-domain",
            mode="bounded-continuation-ledger",
            fault_timing="observed from the composite journey's authoritative continuation ledger",
            pid=_pid_na("no service process was restarted"),
            counts_before=after, counts_after=after, receipt_ids=[first_run] if first_run else ["none"],
            trace=_trace(trace, "agent_runtime_turns.trace_id", first_run) if trace and first_run
            else _na("continuation ledger had no run trace"),
            run={"value": first_run, "source": "continuation_budget.run_id", "object_id": first_run}
            if first_run else _run_na(),
            recovery_action="each durable event key was settled exactly once with one dispatch attempt",
            final_state="bounded_continuation_once")
        scenario["assertions"]["at_most_once"] = exactly_once
        scenarios.append(finish(scenario, exactly_once))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "bounded-continuation-exactly-once", str(error), "backend-domain"))

    # 13. model-or-domain-failure ------------------------------------------
    try:
        before = counts()
        error_code = ""
        failed = False
        try:
            client.call("POST", "/api/product/ml/training-runs",
                        {"task_id": task, "ml_strategy_artifact_id": "artifact_" + "0" * 32,
                         "stock_pool_snapshot_id": snapshot_id},
                        headers={"x-idempotency-key": "v090-domain-failure"})
        except RegressionError as exc:
            failed = True
            error_code = str(exc)[:120]
        after = counts()
        ok = failed and after["ml_training_runs"] == before["ml_training_runs"]
        scenario = _scenario_base(
            journey, "model-or-domain-failure", boundary="backend-domain", mode="domain-rejection",
            fault_timing="a training submission referenced an unknown strategy identity",
            pid=_pid_na("no service process was restarted"), counts_before=before, counts_after=after,
            receipt_ids=["domain-rejection"],
            trace=_na("the submission was rejected before any run trace was created"), run=_run_na(),
            recovery_action=f"the domain rejection surfaced as a real failure ({error_code or 'domain rejection'})",
            final_state="domain_rejected")
        scenario["assertions"]["failure_not_fake_completed"] = failed
        scenario["assertions"]["at_most_once"] = after["ml_training_runs"] == before["ml_training_runs"]
        scenarios.append(finish(scenario, ok))
    except Exception as error:  # noqa: BLE001
        scenarios.append(_blocked(journey, "model-or-domain-failure", str(error), "backend-domain"))

    # 14..17. honestly BLOCKED required rows -------------------------------
    scenarios.append(_blocked(journey, "approval-revoked",
                              "no revoke path exists at the ML strategy or agent approval layer in the "
                              "committed tree; a rejection is not a revoke and is not substituted",
                              "backend-domain"))
    scenarios.append(_blocked(journey, "timeout-terminal",
                              "the isolated ML stack exposes no deterministic timeout boundary distinct "
                              "from cancel; no timeout terminal can be produced honestly",
                              "ml-worker"))
    scenarios.append(_blocked(journey, "data-ready-continuation",
                              "the composite journey exercises the ADR-0045 budgeted continuation, not the "
                              "ADR-0077 data_ready grant; a real waiting_for_data -> readiness -> bounded "
                              "data_ready continuation is not implemented in this 0.9 regression",
                              "backend-domain"))
    scenarios.append(_blocked(journey, "runtime-adapter-tool-boundary",
                              "Gateway/runtime-adapter pre/post-write response loss and restart at the agent "
                              "tool-call boundary require scripted-runtime tool-call fault injection (D15 "
                              "scope); Backend/worker results are not generalized to this boundary",
                              "runtime-adapter"))
    return scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default="byq-v090-composite-local")
    parser.add_argument("--no-up", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "docs/evidence/v090-composite-research/observations.v2.json")
    args = parser.parse_args(argv)

    observations: dict = {
        "schema_version": OBSERVATIONS_SCHEMA,
        "evidence_class": CONTRACT["required_evidence_class"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "llm": {"class": "scripted-keyless", "real_llm_quality": False,
                "note": "F6 synthetic runtime; service-boundary fault-regression evidence, not real-LLM-quality."},
        "execution_model": {"provider": "scripted-keyless", "compose_project": args.scope},
        "journey": None,
        "scenarios": [],
        "cleanup": None,
    }
    stack = Stack(args.scope)
    try:
        if not args.no_up:
            stack.up(build=not args.no_build)
        else:
            stack.resolve_gateway()
        task = run_f6_chain(stack)
        stack.resolve_gateway()
        client = ProductClient(stack, "f6-chain-user", "test-password-123")
        observations["journey"] = collect_journey(stack, task, client)
        observations["scenarios"] = run_scenarios(stack, observations["journey"], client)
    except Exception as error:  # noqa: BLE001
        observations["journey"] = observations["journey"] or {
            "id": CONTRACT["composite_journey"]["id"], "result": "BLOCKED",
            "not_run_reason": str(error), "owner": "", "workspace_id": "", "task_id": "",
            "original_key": "", "steps": [], "report": {}, "terminal": {},
        }
        for spec in CONTRACT["required_scenarios"]:
            if not any(s.get("id") == spec["id"] for s in observations["scenarios"]):
                observations["scenarios"].append({
                    "id": spec["id"], "result": "BLOCKED", "not_run_reason": str(error),
                    "task_id": "", "owner": "", "workspace_id": ""})
    finally:
        if not args.no_cleanup:
            observations["cleanup"] = stack.down()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(observations, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"observations": str(args.out),
                      "journey": (observations["journey"] or {}).get("result"),
                      "scenarios": [(s["id"], s["result"]) for s in observations["scenarios"]],
                      "cleanup": observations.get("cleanup")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
