#!/usr/bin/env python3
"""Trusted in-container consumer for the ADR-0085 P4-B normal-journey driver.

Runs INSIDE the isolated Backend container and drives the committed production
plan-continuation/ledger seams by their exact persisted identities. It is the
trusted consumer the P2/P4 contracts always assumed; it is NOT a second generic
agent harness, never starts a model turn, and never accepts caller routing.

    docker exec -i <backend> python /tmp/p4b-step-runner.py <command> < payload.json
"""

from __future__ import annotations

import hashlib
import json
import sys

from app.agent_research import AgentResearchStore
from app.research import ResearchStore


def _context(store: ResearchStore, task_id: str) -> dict:
    row = store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task",
                           {"task": task_id})
    if row is None:
        raise SystemExit(json.dumps({"error": "task_not_found", "task_id": task_id}))
    return {"owner_principal": row["owner_principal"], "workspace_id": row["workspace_id"],
            "conversation_id": row["conversation_id"]}


def _plan(store: ResearchStore, task_id: str) -> dict:
    row = store._fetch_one("SELECT plan FROM research_execution_plans WHERE task_id = :task",
                           {"task": task_id})
    if row is None:
        raise SystemExit(json.dumps({"error": "plan_not_found", "task_id": task_id}))
    return row["plan"]


def _artifact(store: ResearchStore, task: dict, *, kind: str, suffix: str,
              content: dict, trace: str) -> str:
    artifact_id = "artifact_" + hashlib.sha256(
        f"p4b-{kind}-{task['task_id']}-{suffix}".encode()).hexdigest()[:32]
    existing = store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id = :a",
                                {"a": artifact_id})
    if existing is not None:
        return artifact_id
    canonical = json.dumps(content, sort_keys=True)
    store._execute(
        """INSERT INTO artifacts
        (artifact_id, task_id, experiment_id, owner_principal, workspace_id, kind, status,
         content, content_sha256, lineage, trace_id, idempotency_key, request_hash,
         created_at, updated_at, version)
        VALUES (:id, :task, NULL, :owner, :workspace, :kind, 'validated',
                CAST(:content AS jsonb), :sha, '[]'::jsonb, :trace, :key, :hash, now(), now(), 1)""",
        {"id": artifact_id, "task": task["task_id"], "owner": task["owner_principal"],
         "workspace": task["workspace_id"], "kind": kind, "content": canonical,
         "sha": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
         "trace": trace, "key": f"p4b-{kind}-{suffix}",
         "hash": "sha256:" + hashlib.sha256(f"p4b-{kind}-{suffix}".encode()).hexdigest()})
    return artifact_id


def _pool_snapshot(store: ResearchStore, task: dict, iteration: int) -> str:
    pool_id = "stock_pool_" + hashlib.sha256(
        f"p4b-pool-{task['task_id']}".encode()).hexdigest()[:32]
    snapshot_id = "stocksnapshot_" + hashlib.sha256(
        f"p4b-snapshot-{task['task_id']}-{iteration}".encode()).hexdigest()[:32]
    store._execute(
        """INSERT INTO stock_pools
        (pool_id, owner_principal, name, pool_type, weights_json, symbols_json, version,
         provenance_json, created_at, status, metadata_version)
        VALUES (:pool, :owner, 'p4b signal pool', 'index', '{}'::jsonb, '[]'::jsonb,
                'pending', '{}'::jsonb, now(), 'active', 1)
        ON CONFLICT (pool_id) DO NOTHING""",
        {"pool": pool_id, "owner": task["owner_principal"]})
    store._execute(
        """INSERT INTO stock_pool_snapshots
        (snapshot_id, pool_id, version_number, schema_version, pool_type,
         membership_fingerprint, snapshot_fingerprint, definition_json, provenance_json,
         weight_mode, member_count, created_at)
        VALUES (:snap, :pool, :version, 'p4b', 'index', 'p4b', :fingerprint,
                '{}'::jsonb, '{}'::jsonb, 'equal', 0, now())
        ON CONFLICT (snapshot_id) DO NOTHING""",
        {"snap": snapshot_id, "pool": pool_id, "version": iteration,
         "fingerprint": f"p4b-{iteration}"})
    return snapshot_id


def _seed_signal_job(store: ResearchStore, task_id: str, iteration: int) -> dict:
    task = store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task",
                            {"task": task_id})
    plan = _plan(store, task_id)
    strategy_version = (plan.get("references") or {}).get("strategy_version", {}).get(
        "strategy_version")
    snapshot_artifact = _artifact(
        store, task, kind="signal_snapshot", suffix=f"iter{iteration}",
        content={"iteration": iteration, "bars": "bounded-fixture",
                 "validated": True}, trace="p4b-signal")
    pool_snapshot = _pool_snapshot(store, task, iteration)
    job_id = "signaljob_" + hashlib.sha256(
        f"p4b-signal-{task_id}-{iteration}".encode()).hexdigest()[:32]
    existing = store._fetch_one("SELECT job_id FROM signal_producer_jobs WHERE job_id = :j",
                                {"j": job_id})
    if existing is not None:
        return {"job_id": job_id, "snapshot_artifact_id": snapshot_artifact,
                "created": False}
    store._execute(
        """INSERT INTO signal_producer_jobs
        (job_id, owner_principal, task_id, experiment_id, strategy_version_artifact_id,
         stock_pool_snapshot_id, status, input_json, input_sha256, trace_id, idempotency_key,
         request_hash, attempt_count, result_artifact_id, created_at, finished_at, updated_at)
        VALUES (:job, :owner, :task, NULL, :strategy, :pool, 'completed', '{}'::jsonb, 'p4b',
                'p4b-signal', :key, 'p4b', 1, :snapshot, now(), now(), now())""",
        {"job": job_id, "owner": task["owner_principal"], "task": task_id,
         "strategy": strategy_version, "pool": pool_snapshot,
         "snapshot": snapshot_artifact, "key": job_id})
    return {"job_id": job_id, "snapshot_artifact_id": snapshot_artifact, "created": True}


def _seed_backtest_job(store: ResearchStore, task_id: str, iteration: int,
                       signal_job_id: str) -> dict:
    task = store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task",
                            {"task": task_id})
    signal = store._fetch_one("SELECT * FROM signal_producer_jobs WHERE job_id = :j",
                              {"j": signal_job_id})
    plan = _plan(store, task_id)
    strategy_version = (plan.get("references") or {}).get("strategy_version", {}).get(
        "strategy_version")
    result_artifact = _artifact(
        store, task, kind="backtest_result", suffix=f"iter{iteration}",
        content={"iteration": iteration, "total_return": 0.1 * iteration,
                 "max_drawdown": 0.2}, trace="p4b-backtest")
    job_id = "backtest_" + hashlib.sha256(
        f"p4b-bt-{task_id}-{iteration}".encode()).hexdigest()[:32]
    existing = store._fetch_one("SELECT job_id FROM backtest_jobs WHERE job_id = :j",
                                {"j": job_id})
    if existing is not None:
        return {"job_id": job_id, "result_artifact_id": result_artifact, "created": False}
    request_json = json.dumps({
        "signal_snapshot_artifact_id": signal["result_artifact_id"],
        "signal_producer_job_id": signal_job_id, "iteration": iteration})
    store._execute(
        """INSERT INTO backtest_jobs
        (job_id, name, task_id, experiment_id, owner_principal, status, request_json,
         request_hash, input_manifest_id, input_manifest_json, strategy_version_artifact_id,
         approval_artifact_id, idempotency_key, attempts, max_attempts, result_artifact_id,
         summary_json, created_at, updated_at, finished_at)
        VALUES (:job, :name, :task, NULL, :owner, 'completed', CAST(:request AS jsonb), 'p4b',
                'p4b-manifest', '{}'::jsonb, :strategy, :strategy, :key, 1, 3, :result,
                CAST(:summary AS jsonb), now(), now(), now())""",
        {"job": job_id, "name": f"P4B round {iteration}", "task": task_id,
         "owner": task["owner_principal"], "request": request_json,
         "strategy": strategy_version, "result": result_artifact, "key": job_id,
         "summary": json.dumps({"iteration": iteration, "total_return": 0.1 * iteration})})
    return {"job_id": job_id, "result_artifact_id": result_artifact, "created": True}


def _state(store: ResearchStore, task_id: str) -> dict:
    context = _context(store, task_id)
    task = store._fetch_one("SELECT * FROM research_tasks WHERE task_id = :task",
                            {"task": task_id})
    plan_row = store._fetch_one("SELECT * FROM research_execution_plans WHERE task_id = :task",
                                {"task": task_id})
    approvals = store._execute(
        "SELECT approval_id, action, status, resource_type, resource_id, plan_version,"
        " plan_task_version, plan_params_digest, plan_idempotency_key, plan_action,"
        " plan_resource_kind, plan_resource_id, decision_by"
        " FROM agent_approvals WHERE owner_principal = :owner ORDER BY created_at",
        {"owner": task["owner_principal"]})
    events = store._execute(
        "SELECT event_id, event_type, status, outcome, admitted, source_identity, plan_version"
        " FROM research_continuation_events WHERE task_id = :task ORDER BY created_at",
        {"task": task_id})
    stage_calls = store._execute(
        "SELECT call_identity, stage, call_index, status, outcome FROM research_judgment_stage_calls"
        " WHERE task_id = :task ORDER BY admitted_at", {"task": task_id})
    counts = {
        "research_tasks": store._fetch_one("SELECT COUNT(*) AS c FROM research_tasks")["c"],
        "research_execution_plans": store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_execution_plans")["c"],
        "research_continuation_events": store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_continuation_events WHERE task_id = :t",
            {"t": task_id})["c"],
        "research_judgment_stage_calls": store._fetch_one(
            "SELECT COUNT(*) AS c FROM research_judgment_stage_calls WHERE task_id = :t",
            {"t": task_id})["c"],
        "agent_approvals": store._fetch_one(
            "SELECT COUNT(*) AS c FROM agent_approvals WHERE owner_principal = :o",
            {"o": task["owner_principal"]})["c"],
        "artifacts": store._fetch_one(
            "SELECT COUNT(*) AS c FROM artifacts WHERE task_id = :t", {"t": task_id})["c"],
        "signal_producer_jobs": store._fetch_one(
            "SELECT COUNT(*) AS c FROM signal_producer_jobs WHERE task_id = :t",
            {"t": task_id})["c"],
        "backtest_jobs": store._fetch_one(
            "SELECT COUNT(*) AS c FROM backtest_jobs WHERE task_id = :t", {"t": task_id})["c"],
        "paper_accounts": store._fetch_one(
            "SELECT COUNT(*) AS c FROM paper_accounts WHERE owner_principal = :o AND"
            " status <> 'deleted'", {"o": task["owner_principal"]})["c"],
        "paper_orders": store._fetch_one(
            "SELECT COUNT(*) AS c FROM paper_orders o JOIN paper_accounts a USING(account_id)"
            " WHERE a.owner_principal = :o", {"o": task["owner_principal"]})["c"],
        "paper_positions": store._fetch_one(
            "SELECT COUNT(*) AS c FROM paper_positions p JOIN paper_accounts a USING(account_id)"
            " WHERE a.owner_principal = :o", {"o": task["owner_principal"]})["c"],
        "paper_fills": store._fetch_one(
            "SELECT COUNT(*) AS c FROM paper_fills f JOIN paper_accounts a USING(account_id)"
            " WHERE a.owner_principal = :o", {"o": task["owner_principal"]})["c"],
    }
    return {"task_status": task["status"], "task_version": task["version"],
            "task_progress": task.get("progress"),
            "plan": plan_row["plan"] if plan_row else None,
            "approvals": [dict(row) for row in (approvals or [])],
            "events": [dict(row) for row in (events or [])],
            "stage_calls": [dict(row) for row in (stage_calls or [])],
            "counts": counts, "context": context}


def _judgment_context(store: ResearchStore, task_id: str) -> dict:
    context = _context(store, task_id)
    catalog = store._fetch_one(
        "SELECT runtime_session_id, trace_id FROM product_conversations WHERE conversation_id = :c",
        {"c": context["conversation_id"]})
    plan = _plan(store, task_id)
    attempt = f"{plan['plan_version']}:{plan['stage']}:{plan['iteration']}"
    return {"context": context, "trace_id": catalog["trace_id"],
            "runtime_session_id": catalog["runtime_session_id"],
            "plan": plan, "attempt": attempt}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("command required")
    command = argv[1]
    payload = json.loads(sys.stdin.read() or "{}")
    store = ResearchStore()
    try:
        if command == "journey-state":
            result = _state(store, payload["task_id"])
        elif command == "judgment-context":
            result = _judgment_context(store, payload["task_id"])
        elif command == "plan":
            result = _plan(store, payload["task_id"])
        elif command == "start-run":
            context = _context(store, payload["task_id"])
            catalog = store._fetch_one(
                "SELECT runtime_session_id, trace_id FROM product_conversations"
                " WHERE conversation_id = :c", {"c": context["conversation_id"]})
            agent = AgentResearchStore()
            try:
                result = agent.start_run({
                    "owner_principal": context["owner_principal"],
                    "actor_principal": f"byq-product-agent-{catalog['runtime_session_id']}",
                    "role_id": "quant_orchestrator", "trace_id": catalog["trace_id"],
                    "session_id": catalog["runtime_session_id"],
                    "dsh_run_id": catalog["runtime_session_id"] + "-p4b",
                    "idempotency_key": payload["key"]})
            finally:
                agent.close()
        elif command == "request-approval":
            context = _context(store, payload["task_id"])
            result = store.request_plan_approval(payload["task_id"], trusted_context=context)
        elif command == "paper-account-params":
            context = _context(store, payload["task_id"])
            result = store.paper_account_create_parameters(
                payload["task_id"], trusted_context=context)
        elif command == "seed-signal-job":
            result = _seed_signal_job(store, payload["task_id"], int(payload["iteration"]))
        elif command == "seed-backtest-job":
            result = _seed_backtest_job(store, payload["task_id"], int(payload["iteration"]),
                                        payload["signal_job_id"])
        elif command == "record-data-ready":
            context = _context(store, payload["task_id"])
            result = store.record_data_ready_event(
                payload["task_id"], payload["signal_job_id"], trusted_context=context)
        elif command == "record-backtest-completed":
            context = _context(store, payload["task_id"])
            result = store.record_backtest_completed_event(
                payload["task_id"], payload["backtest_job_id"], trusted_context=context)
        elif command == "apply-action":
            context = _context(store, payload["task_id"])
            result = store.apply_deterministic_action_result(
                payload["task_id"], payload["source"], trusted_context=context)
        else:
            raise SystemExit(f"unknown command {command}")
        print(json.dumps(result, default=str))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
