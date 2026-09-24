#!/usr/bin/env python3
"""ADR-0085 P4 isolated four-boundary closed-loop driver (real, non-production).

Drives ONE real strategy_draft judgment turn through:
  Product API (Gateway) -> Runtime Adapter internal judgment route -> real DSH
  child persona -> Backend admit/result receipt.

It reuses the isolated D15 runtime-qualification stack plus the P4 override
(compose.p4-judgment.yml): dedicated read-only MCP service, keyless
judgment-aware scripted provider, current code mounted into the existing images.

Every recorded fact is read from a real HTTP response, a real container, a real
DB row or the provider's own call counter. It runs negative controls (no/forged
service token, forged attempt) and exits non-zero unless the positive case and
all controls behave as asserted.

    BYQ_P4_ROOT=<worktree> python3 scripts/v091/continuation_p4/run_p4_isolated.py
"""

from __future__ import annotations

import http.cookiejar
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PROJECT = "byq-p4-judgment"
COMPOSE = [
    "docker", "compose", "-p", PROJECT,
    "-f", str(ROOT / "scripts/d15/runtime_continuity/compose.runtime-qual.yml"),
    "-f", str(ROOT / "scripts/v091/continuation_p4/compose.p4-judgment.yml"),
]
GATEWAY = "http://127.0.0.1:18100"
BACKEND = "http://127.0.0.1:18000"
ADAPTER = "http://127.0.0.1:18400"
JUDGMENT_TOKEN = "d15-synthetic-judgment-only"
PG = "byq-p4-judgment-postgres-1"


class DriverError(RuntimeError):
    pass


def _env() -> dict:
    return {**os.environ, "BYQ_P4_ROOT": str(ROOT)}


def docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout, env=_env())


def compose(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run([*COMPOSE, *args], capture_output=True, text=True,
                          timeout=timeout, env=_env())


def psql(sql: str) -> list[list[str]]:
    out = docker("exec", PG, "psql", "-U", "byq_app", "-d", "byq_domain", "-Atc", sql)
    if out.returncode != 0:
        raise DriverError(f"psql failed: {out.stderr[:300]}")
    return [line.split("|") for line in out.stdout.splitlines() if line.strip()]


def start_agent_run(owner: str, trace: str, runtime_session_id: str) -> dict:
    """Register the task's bound owner AgentRun through the trusted Backend store."""

    payload = {"owner_principal": owner, "actor_principal": f"byq-product-agent-{runtime_session_id}",
               "role_id": "quant_orchestrator", "trace_id": trace,
               "session_id": runtime_session_id, "dsh_run_id": runtime_session_id + "-p4",
               "idempotency_key": f"p4-run-{runtime_session_id}"}
    script = (
        "import json;from app.agent_research import AgentResearchStore;"
        "s=AgentResearchStore();r=s.start_run({payload!r});s.close();print(json.dumps(r, default=str))"
    ).format(payload=payload)
    out = docker("exec", "byq-p4-judgment-backend-1", "python", "-c", script)
    if out.returncode != 0:
        raise DriverError(f"agent run start failed: {out.stderr[-400:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def backend_exec(script: str) -> str:
    out = docker("exec", "byq-p4-judgment-backend-1", "python", "-c", script)
    if out.returncode != 0:
        raise DriverError(f"backend exec failed: {out.stderr[-500:]}")
    return out.stdout.strip().splitlines()[-1]


def seed_signal_job(task_id: str, owner: str, workspace: str,
                    strategy_version_id: str) -> dict:
    """Seed one completed signal producer job for the exact task (trusted seam).

    The job row has a real FK to ``stock_pool_snapshots``, so the referenced
    snapshot fixture is seeded first (same transaction, ON CONFLICT DO NOTHING).
    Both rows are honest test fixtures for the deterministic create action; the
    action itself is the real Backend seam.
    """

    job_id = "signaljob_" + hashlib.sha256(f"p4-{task_id}".encode()).hexdigest()[:32]
    snapshot_id = "stocksnapshot_" + hashlib.sha256(
        f"p4-snapshot-{task_id}".encode()).hexdigest()[:32]
    pool_id = "stock_pool_" + hashlib.sha256(
        f"p4-pool-{task_id}".encode()).hexdigest()[:32]
    payload = {"job": job_id, "snapshot": snapshot_id, "pool": pool_id,
               "owner": owner, "task": task_id, "strategy": strategy_version_id}
    script = (
        "import json;from app.research import ResearchStore;"
        "p=json.loads(" + repr(json.dumps(payload)) + ");"
        "s=ResearchStore();"
        "s._execute(\"INSERT INTO stock_pools (pool_id, owner_principal, name, "
        "pool_type, weights_json, symbols_json, version, provenance_json, created_at, "
        "status, metadata_version) VALUES (:pool, :owner, 'p4 signal pool', 'index', "
        "'{}'::jsonb, '[]'::jsonb, 'pending', '{}'::jsonb, now(), 'active', 1) "
        "ON CONFLICT (pool_id) DO NOTHING\", "
        "{'pool': p['pool'], 'owner': p['owner']});"
        "s._execute(\"INSERT INTO stock_pool_snapshots "
        "(snapshot_id, pool_id, version_number, schema_version, pool_type, "
        "membership_fingerprint, snapshot_fingerprint, definition_json, provenance_json, "
        "weight_mode, member_count, created_at) VALUES (:snap, :pool, 1, 'p4', 'index', "
        "'p4', 'p4', '{}'::jsonb, '{}'::jsonb, 'equal', 0, now()) "
        "ON CONFLICT (snapshot_id) DO NOTHING\", "
        "{'snap': p['snapshot'], 'pool': p['pool']});"
        "created=s._fetch_one('SELECT job_id FROM signal_producer_jobs "
        "WHERE job_id = :j', {'j': p['job']}) is None;"
        "s._execute(\"INSERT INTO signal_producer_jobs "
        "(job_id, owner_principal, task_id, strategy_version_artifact_id, "
        "stock_pool_snapshot_id, status, input_json, input_sha256, trace_id, "
        "idempotency_key, request_hash, created_at, updated_at) VALUES "
        "(:job, :owner, :task, :strategy, :snap, 'completed', '{}'::jsonb, 'p4', "
        "'p4-trace', :job, 'p4', now(), now()) ON CONFLICT (job_id) DO NOTHING\", "
        "{'job': p['job'], 'owner': p['owner'], 'task': p['task'], "
        "'strategy': p['strategy'], 'snap': p['snapshot']});"
        "s.close();print(json.dumps({'job_id': p['job'], 'snapshot_id': p['snapshot'], "
        "'pool_id': p['pool'], 'created': created}))"
    )
    return json.loads(backend_exec(script))


def apply_deterministic_action(task_id: str, owner: str, workspace: str,
                               signal_job_id: str) -> dict:
    """Apply the trusted deterministic create_backtest_task result."""

    script = (
        "import json;from app.research import ResearchStore;s=ResearchStore();"
        "r=s.apply_deterministic_action_result({task!r}, {{'signal_job_id':{job!r}}}, "
        "trusted_context={{'owner_principal':{owner!r},'workspace_id':{workspace!r}}});"
        "s.close();print(json.dumps(r, default=str))"
    ).format(task=task_id, job=signal_job_id, owner=owner, workspace=workspace)
    return json.loads(backend_exec(script))


def request_plan_approval(task_id: str, owner: str, workspace: str) -> dict:
    """Request the plan-command-bound approval through the trusted Backend seam."""

    script = (
        "import json;from app.research import ResearchStore;"
        "s=ResearchStore();"
        "r=s.request_plan_approval({task!r}, trusted_context={{'owner_principal':{owner!r},"
        "'workspace_id':{workspace!r}}});s.close();print(json.dumps(r, default=str))"
    ).format(task=task_id, owner=owner, workspace=workspace)
    out = docker("exec", "byq-p4-judgment-backend-1", "python", "-c", script)
    if out.returncode != 0:
        raise DriverError(f"approval request failed: {out.stderr[-400:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


class ProductClient:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.calls = 0
        body = self.call("POST", "/api/product/auth/login",
                         {"username": "d15admin", "password": "D15AdminPass123"})
        if body.get("user", {}).get("username") != "d15admin":
            raise DriverError("product login failed")

    def call(self, method: str, path: str, payload: dict | None = None, *,
             headers: dict | None = None, timeout: int = 60) -> dict:
        self.calls += 1
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            GATEWAY + path, data=data, method=method,
            headers={"content-type": "application/json", **(headers or {})})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            raise DriverError(f"{method} {path} -> {error.code}: {error.read().decode()[:200]}")


def adapter_run(task_id: str, headers: dict, *, timeout: int = 300) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{ADAPTER}/internal/runtime/research-judgment/{task_id}/run",
        data=b"{}", method="POST",
        headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode() or "{}")
        except json.JSONDecodeError:
            return error.code, {"raw": error.read().decode()[:200]}


def provider_calls() -> dict:
    script = ("import json,urllib.request;"
              "print(urllib.request.urlopen('http://judgment-provider:8901/_calls',timeout=5).read().decode())")
    out = docker("exec", "byq-p4-judgment-gateway-1", "python3", "-c", script)
    if out.returncode != 0:
        raise DriverError(f"provider counter unavailable: {out.stderr[:200]}")
    return json.loads(out.stdout)


def main() -> int:
    evidence: dict = {"schema_version": "byq-adr0085-p4-isolated-four-boundary.v1",
                      "project": PROJECT}
    violations: list[str] = []
    client = ProductClient()
    conversation = client.call("POST", "/v1/agent/sessions", {})
    session_id = conversation["session_id"]
    # Boundary 1a: the Product API creates the real conversation. The task is then
    # bound to that exact conversation through the trusted Backend route (the real
    # product flow does this through the agent conversation); the Product-API
    # continuation grant and the judgment turn then operate on the bound task.
    conv = psql(f"SELECT runtime_session_id, trace_id, owner_principal, workspace_id "
                f"FROM product_conversations ORDER BY created_at DESC LIMIT 1")[0]
    runtime_session_id, trace_id, owner, workspace = conv
    bind_headers = {
        "content-type": "application/json",
        "x-byq-owner-principal": owner, "x-byq-workspace-id": workspace,
        "x-byq-actor-principal": owner, "x-byq-trace-id": trace_id,
        "x-byq-session-id": runtime_session_id, "x-byq-dsh-run-id": runtime_session_id,
    }
    bind_body = {"owner_principal": owner, "title": "P4 isolated four-boundary",
                 "objective": "One bounded strategy_draft judgment turn through the real stack.",
                 "trace_id": trace_id, "idempotency_key": f"p4-bind-{uuid.uuid4().hex[:12]}"}
    bind = urllib.request.Request(f"{BACKEND}/v1/research/tasks",
                                  data=json.dumps(bind_body).encode(), method="POST",
                                  headers=bind_headers)
    with urllib.request.urlopen(bind, timeout=30) as response:
        bound = json.loads(response.read().decode())
    task = (bound.get("task") or bound)["task_id"]
    source = (
        "import pandas as pd\n"
        "class CustomStrategy:\n"
        "    def generate_signals(self, data, parameters=None):\n"
        "        return {str(s): int(c) for s, c in data['close'].items()}\n"
    )
    strategy = {"strategy_id": "P4Isolated", "name": "P4 isolated draft",
                "category": "momentum", "description": "P4 isolated grant fixture.",
                "parameters": {"lookback": 2},
                "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
                "source_type": "python_script", "script": source}
    nonce = uuid.uuid4().hex
    client.call("POST", "/api/product/strategies/drafts", {
        "task_id": task, "strategy": strategy, "trace_id": f"p4-draft-{nonce}",
        "idempotency_key": f"p4-draft-{nonce}"})
    validated = client.call("POST", "/api/product/strategies/validate", {
        "task_id": task, "strategy": strategy, "trace_id": f"p4-valid-{nonce}",
        "idempotency_key": f"p4-valid-{nonce}"})
    draft_artifact = str(validated["artifact"]["artifact_id"])
    version = client.call("POST", "/api/product/strategies/versions", {
        "task_id": task, "draft_artifact_id": draft_artifact,
        "trace_id": f"p4-version-{nonce}", "idempotency_key": f"p4-version-{nonce}"})
    version_artifact = str(version["artifact"]["artifact_id"])
    client.call("POST", f"/api/product/research/tasks/{task}/continuation-permission", {
        "idempotency_key": f"p4-grant-{task}", "token_limit": 64_000_000,
        "confirmed_artifact_ids": [version_artifact]},
        headers={"x-byq-continuation-confirmation": "v1"})
    # Trusted bounded stage input (Backend) captured for a task/version/stage/digest
    # cross-check against what the DSH provider actually received.
    stage_request = urllib.request.Request(
        f"{BACKEND}/v1/research/tasks/{task}/stage-input", headers=bind_headers)
    with urllib.request.urlopen(stage_request, timeout=30) as response:
        trusted_input = json.loads(response.read().decode())
    canonical = json.dumps(trusted_input, sort_keys=True)
    forbidden = ("bars_frame", "date_index", "signals", "signal_rows", "frame",
                 "benchmark_series", "equity_curve", "positions", "trades_frame")
    evidence["trusted_stage_input"] = {
        "serialized_bytes": len(canonical.encode()),
        "digest": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        "fields": sorted(trusted_input.keys()),
        "allowed_tools": trusted_input.get("allowed_tools"),
        "forbidden_raw_hits": [k for k in forbidden if k in canonical],
    }
    plan_body = client.call("GET", f"/api/product/research/tasks/{task}/execution-plan")
    plan = plan_body.get("plan") or plan_body
    evidence["boundary1_product_api"] = {
        "gateway": GATEWAY, "http_calls": client.calls, "session_id": session_id,
        "task_id": task, "initial_plan": plan, "confirmed_strategy_version": version_artifact,
    }
    if plan["stage"] != "strategy_draft":
        raise DriverError(f"grant did not create a strategy_draft plan: {plan['stage']}")

    rows = psql(f"SELECT owner_principal, workspace_id, conversation_id FROM research_tasks "
                f"WHERE task_id = '{task}'")
    owner, workspace, conversation_id = rows[0]
    rt = psql(f"SELECT runtime_session_id, trace_id FROM product_conversations "
              f"WHERE conversation_id = '{conversation_id}'")[0]
    runtime_session_id, trace_id = rt
    plan_version, stage, iteration = psql(
        f"SELECT plan_version, stage, iteration FROM research_execution_plans "
        f"WHERE task_id = '{task}'")[0]
    attempt = f"{plan_version}:{stage}:{iteration}"
    headers = {
        "x-byq-runtime-judgment-token": JUDGMENT_TOKEN,
        "x-byq-judgment-attempt": attempt,
        "x-byq-owner-principal": owner, "x-byq-workspace-id": workspace,
        "x-byq-actor-principal": owner, "x-byq-trace-id": trace_id,
        "x-byq-session-id": runtime_session_id, "x-byq-dsh-run-id": runtime_session_id,
    }
    evidence["boundary_request"] = {"attempt": attempt, "identity": {
        k: v for k, v in headers.items() if k not in {
            "x-byq-runtime-judgment-token", "x-byq-owner-principal",
            "x-byq-actor-principal"}}}

    # Negative controls (must not create any stage call or reach the provider).
    before_rows = int(psql(f"SELECT count(*) FROM research_judgment_stage_calls "
                           f"WHERE task_id = '{task}'")[0][0])
    provider_before_controls = provider_calls()["calls"]
    no_token = {k: v for k, v in headers.items() if k != "x-byq-runtime-judgment-token"}
    code, _ = adapter_run(task, no_token)
    forged = {**headers, "x-byq-runtime-judgment-token": "forged"}
    code_forged, _ = adapter_run(task, forged)
    forged_attempt = {**headers, "x-byq-judgment-attempt": "999:strategy_draft:1"}
    code_attempt, _ = adapter_run(task, forged_attempt)
    provider_after_controls = provider_calls()["calls"]
    after_rows = int(psql(f"SELECT count(*) FROM research_judgment_stage_calls "
                          f"WHERE task_id = '{task}'")[0][0])
    evidence["negative_controls"] = {
        "no_token_status": code, "forged_token_status": code_forged,
        "forged_attempt_status": code_attempt,
        "stage_calls_before": before_rows, "stage_calls_after": after_rows,
        "provider_calls_before": provider_before_controls,
        "provider_calls_after": provider_after_controls,
    }
    if code != 401:
        violations.append(f"no-token control returned {code}, expected 401")
    if code_forged != 401:
        violations.append(f"forged-token control returned {code_forged}, expected 401")
    if after_rows != before_rows:
        violations.append("a negative control created a stage call")
    if provider_after_controls != provider_before_controls:
        violations.append("a negative control reached the provider")

    # Positive boundary. The provider total call count is authoritative for the
    # model-call accounting (root + child + final root = 3 for one real turn).
    provider_pre = provider_calls()["calls"]
    pcode, body = adapter_run(task, headers)
    provider_post = provider_calls()
    provider_delta = provider_post["calls"] - provider_pre
    evidence["boundary2_adapter"] = {"status": pcode, "response": body}
    if pcode != 200:
        violations.append(f"adapter judgment turn returned {pcode}: {body}")
    else:
        invocation = body.get("adapter_invocation") or {}
        receipt = body.get("receipt") or {}
        evidence["boundary3_dsh"] = {
            "provider": provider_post, "positive_provider_delta": provider_delta,
            "task_provider_calls": provider_post["calls_by_task"].get(task, 0)}
        if provider_delta != 3:
            violations.append(f"one real turn made {provider_delta} provider calls, expected 3")
        if provider_post["calls_by_task"].get(task, 0) != 3:
            violations.append(
                f"task provider call total is {provider_post['calls_by_task'].get(task, 0)}, expected 3")
        call_rows = psql(
            f"SELECT call_identity, status, call_index, outcome FROM research_judgment_stage_calls "
            f"WHERE task_id = '{task}' ORDER BY admitted_at")
        final_plan = psql(
            f"SELECT plan_version, stage, iteration FROM research_execution_plans "
            f"WHERE task_id = '{task}'")[0]
        evidence["boundary4_backend"] = {
            "call_identity": invocation.get("call_identity"),
            "receipt_call_identity": receipt.get("call_identity"),
            "receipt_progress": receipt.get("progress"),
            "stage_call_rows": call_rows, "final_plan": final_plan,
        }
        if receipt.get("replayed") is not False:
            violations.append("positive result was not a fresh commit")
        if not call_rows or call_rows[0][1] != "completed":
            violations.append("no completed stage call row")
        if call_rows and call_rows[0][2] != "1":
            violations.append(f"unexpected call_index: {call_rows[0]}")
        if invocation.get("call_identity") != receipt.get("call_identity"):
            violations.append("adapter call identity does not match the receipt")
        plan_json = json.loads(psql(
            f"SELECT plan::text FROM research_execution_plans "
            f"WHERE task_id = '{task}'")[0][0])
        approval = plan_json.get("approval") or {}
        evidence["boundary4_backend"]["plan_references"] = plan_json.get("references")
        evidence["boundary4_backend"]["plan_approval"] = approval
        if final_plan[1] != "waiting_for_strategy_approval":
            violations.append(
                f"normal strategy_draft proposal did not reach waiting_for_strategy_approval: {final_plan}")
        if approval.get("resource_id") != version_artifact:
            violations.append(
                f"approval is not bound to the validated strategy_version: {approval}")
        if approval.get("action") != "strategy_approve":
            violations.append(f"unexpected approval action: {approval}")
        dsh = evidence["boundary3_dsh"]["provider"]
        if dsh.get("root_calls", 0) < 1 or dsh.get("child_calls", 0) < 1:
            violations.append("the real DSH child persona was not invoked")

        # The ACTUAL model-visible bounded input: what the provider received on the
        # child request, cross-checked against the trusted Backend stage input.
        child = next((c for c in dsh.get("per_call", [])
                      if c.get("role") == "child" and (c.get("call") or 0) > provider_pre), {})
        trusted = evidence["trusted_stage_input"]
        observed = {k: child.get(k) for k in (
            "bounded_input_bytes", "bounded_input_fields", "bounded_input_digest",
            "forbidden_raw_hits", "input_task_id", "input_plan_version",
            "input_task_version", "input_stage")}
        observed["child_tools"] = child.get("tools")
        evidence["boundary_stage_projection"] = {
            "observed_by_provider": observed,
            "trusted_backend": {
                "serialized_bytes": trusted.get("serialized_bytes"),
                "digest": trusted.get("digest"),
                "fields": trusted.get("fields"),
                "allowed_tools": trusted.get("allowed_tools")},
        }
        if observed.get("forbidden_raw_hits"):
            violations.append(
                f"provider input exposed forbidden raw keys: {observed['forbidden_raw_hits']}")
        if (observed.get("bounded_input_bytes") or 0) > 65536:
            violations.append("provider input exceeded the 64 KiB bound")
        if observed.get("bounded_input_digest") != trusted.get("digest"):
            violations.append("provider input digest does not match the trusted stage input")
        for observed_key, trusted_key in (("input_task_id", "task_id"),
                                          ("input_plan_version", "plan_version"),
                                          ("input_task_version", "task_version"),
                                          ("input_stage", "stage")):
            if observed.get(observed_key) != trusted_input.get(trusted_key):
                violations.append(f"provider input {observed_key} mismatch")
        read_only = {"mcp__byq__byq_agent_context", "mcp__byq__byq_research_get",
                     "mcp__byq__byq_research_stage_input_get",
                     "mcp__byq__byq_backtest_task_get", "mcp__byq__byq_backtest_analysis_get"}
        if not set(observed.get("child_tools") or []).issubset(read_only):
            violations.append(f"child exposed a non-read-only tool: {observed.get('child_tools')}")

        # A duplicate completed request must only replay the stored receipt with
        # ZERO extra TOTAL provider calls and no new stage call.
        provider_before = dsh.get("calls")
        dcode, dbody = adapter_run(task, headers)
        provider_after = provider_calls()
        evidence["replay"] = {
            "status": dcode,
            "model_turn_skipped": (dbody.get("receipt") or {}).get("model_turn_skipped"),
            "replayed": (dbody.get("receipt") or {}).get("replayed"),
            "provider_calls_before": provider_before,
            "provider_calls_after": provider_after.get("calls"),
            "stage_calls": psql(
                f"SELECT count(*) FROM research_judgment_stage_calls WHERE task_id = '{task}'")[0][0],
        }
        if dcode != 200 or evidence["replay"]["replayed"] is not True \
                or evidence["replay"]["model_turn_skipped"] is not True:
            violations.append(f"duplicate completed request did not replay: {dcode} {dbody}")
        if evidence["replay"]["provider_calls_after"] != provider_before:
            violations.append("duplicate completed request ran an extra provider call")
        if evidence["replay"]["stage_calls"] != "1":
            violations.append("duplicate completed request created a second stage call")

        # Real approval handoff: the trusted seam requests the plan-command-bound
        # approval, the user decides it through the Product API, and the Backend
        # deterministically advances the plan with ZERO model calls. A duplicate
        # decision must not duplicate anything.
        start_agent_run(owner, trace_id, runtime_session_id)
        task_calls_before_handoff = provider_calls()["calls_by_task"].get(task, 0)
        requested = request_plan_approval(task, owner, workspace)
        approval_id = str(requested.get("approval_id") or "")
        if not approval_id:
            violations.append(f"trusted approval request returned no approval id: {requested}")
            approval_id = psql(
                f"SELECT approval_id FROM agent_approvals WHERE owner_principal = '{owner}' "
                f"ORDER BY created_at DESC LIMIT 1")[0][0]
        provider_before_decision = provider_calls()["calls"]
        decision = client.call(
            "POST", f"/api/product/approvals/{approval_id}/decision",
            {"decision": "approved", "rationale": "P4 isolated user decision"})
        provider_after_decision = provider_calls()["calls"]
        plan_after = psql(
            f"SELECT plan_version, stage, iteration FROM research_execution_plans "
            f"WHERE task_id = '{task}'")[0]
        events = psql(f"SELECT event_id FROM research_continuation_events "
                      f"WHERE task_id = '{task}'")
        client.call("POST", f"/api/product/approvals/{approval_id}/decision",
                    {"decision": "approved", "rationale": "P4 isolated user decision"})
        plan_replay = psql(
            f"SELECT plan_version, stage, iteration FROM research_execution_plans "
            f"WHERE task_id = '{task}'")[0]
        events_replay = psql(f"SELECT event_id FROM research_continuation_events "
                             f"WHERE task_id = '{task}'")
        evidence["approval_handoff"] = {
            "approval_id": approval_id, "decision_action": decision.get("approval", {}).get("action"),
            "decision_status": decision.get("approval", {}).get("status"),
            "plan_after_decision": plan_after, "event_count": len(events),
            "provider_calls_before": provider_before_decision,
            "provider_calls_after": provider_after_decision,
            "task_provider_calls_before_handoff": task_calls_before_handoff,
            "task_provider_calls_after_handoff": provider_calls()["calls_by_task"].get(task, 0),
            "plan_after_replay": plan_replay, "event_count_after_replay": len(events_replay),
        }
        if task_calls_before_handoff != 3 or \
                evidence["approval_handoff"]["task_provider_calls_after_handoff"] != 3:
            violations.append(
                "the deterministic approval handoff changed the task provider call count")
        if plan_after[1] == "waiting_for_strategy_approval":
            violations.append("approval decision did not advance the plan")
        if provider_after_decision != provider_before_decision:
            violations.append("approval decision ran a model call")
        if plan_replay != plan_after or len(events_replay) != len(events):
            violations.append("duplicate approval decision changed the plan or duplicated events")

        # Next deterministic handoff (zero model calls): request + decide the
        # backtest-task-create approval, then apply the trusted deterministic
        # create_backtest_task result (seeded signal job) to reach waiting_for_data.
        task_calls_before_second = provider_calls()["calls_by_task"].get(task, 0)
        strategy_version_id = (plan_json.get("references") or {}).get(
            "strategy_version", {}).get("strategy_version")
        second = request_plan_approval(task, owner, workspace)
        second_id = str(second.get("approval_id") or "")
        client.call("POST", f"/api/product/approvals/{second_id}/decision",
                    {"decision": "approved", "rationale": "P4 isolated task-create decision"})
        plan_after_second = psql(
            f"SELECT plan_version, stage, iteration FROM research_execution_plans "
            f"WHERE task_id = '{task}'")[0]
        job = seed_signal_job(task, owner, workspace, str(strategy_version_id))
        apply_deterministic_action(task, owner, workspace, job["job_id"])
        plan_after_action = psql(
            f"SELECT plan_version, stage, iteration FROM research_execution_plans "
            f"WHERE task_id = '{task}'")[0]
        # Replay the deterministic action: idempotent, no plan/object change.
        apply_deterministic_action(task, owner, workspace, job["job_id"])
        plan_action_replay = psql(
            f"SELECT plan_version, stage, iteration FROM research_execution_plans "
            f"WHERE task_id = '{task}'")[0]
        task_calls_after_second = provider_calls()["calls_by_task"].get(task, 0)
        evidence["next_handoff"] = {
            "task_create_approval_id": second_id,
            "plan_after_task_create_approval": plan_after_second,
            "signal_job_created": job["created"], "plan_after_action": plan_after_action,
            "plan_after_action_replay": plan_action_replay,
            "task_provider_calls": task_calls_after_second,
        }
        if plan_after_second[1] != "ready_to_create_backtest_task":
            violations.append(f"task-create approval did not advance the plan: {plan_after_second}")
        if plan_after_action[1] != "waiting_for_data":
            violations.append(f"deterministic create_backtest_task did not reach waiting_for_data: {plan_after_action}")
        if plan_action_replay != plan_after_action:
            violations.append("deterministic action replay changed the plan")
        if task_calls_after_second != task_calls_before_second:
            violations.append("the deterministic handoffs ran an extra model call")

    # Cross-check the trusted Backend stage input itself (independent of the provider).
    trusted = evidence["trusted_stage_input"]
    if trusted.get("forbidden_raw_hits"):
        violations.append(f"trusted stage input exposed forbidden raw keys: {trusted['forbidden_raw_hits']}")
    if (trusted.get("serialized_bytes") or 0) > 65536:
        violations.append("trusted stage input exceeded the 64 KiB bound")
    read_only_bare = {"byq_agent_context", "byq_research_get",
                      "byq_research_stage_input_get", "byq_backtest_task_get",
                      "byq_backtest_analysis_get"}
    if not set(trusted.get("allowed_tools") or []).issubset(read_only_bare):
        violations.append(f"trusted stage input allowed a non-read-only tool: {trusted.get('allowed_tools')}")

    evidence["http_business_calls"] = client.calls
    evidence["violations"] = violations
    evidence["all_observed"] = not violations
    out = HERE / "isolated-four-boundary.v1.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: evidence[k] for k in ("all_observed", "violations")}, indent=2))
    print(f"wrote {out}")
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
