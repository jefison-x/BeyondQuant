#!/usr/bin/env python3
"""Dedicated F6 CI fixture and read-only AgentRun/audit observer.

The only write action creates the isolated CI user/workspace. The audit action
uses a transaction explicitly marked READ ONLY and is scoped to that owner,
Product conversation, ResearchTask, Runtime root, and (for BG) exact receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from typing import Any


PROJECT_PATTERN = re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z")
OWNER = "f6-chain-user"
SIGNAL_JOB_PATTERN = re.compile(r"signaljob_[0-9a-f]{32}\Z")
TASK_PATTERN = re.compile(r"task_[0-9a-f]{32}\Z")
ARTIFACT_PATTERN = re.compile(r"artifact_[0-9a-f]{32}\Z")
BACKTEST_TASK_PATTERN = re.compile(r"backtesttask_[0-9a-f]{32}\Z")
CONVERSATION_PATTERN = re.compile(r"conversation_[0-9a-f]{32}\Z")
SESSION_PATTERN = re.compile(r"byq-session-[0-9a-f]{32}\Z")
TRACE_PATTERN = re.compile(r"byq-trace-[0-9a-f]{32}\Z")
RUNTIME_ROOT_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
AGENT_RUN_PATTERN = re.compile(r"agent_run_[0-9a-f]{32}\Z")
RESERVATION_PATTERN = re.compile(r"continuation_[0-9a-f]{32}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _required(payload: dict[str, Any], field: str, pattern: re.Pattern[str]) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise SystemExit("invalid exact F6 observer scope")
    return value


def _not_ready(stage: str, category: str) -> dict[str, str]:
    return {"schema_version": "f6-agent-audit-readiness.v1", "stage": stage,
            "status": "not_ready", "category": category}


def _ready_signal_from_receipt(instruction: object, input_sha256: object, event_key: object) -> dict:
    """Closed projection from authoritative internal input, never publish raw text."""
    if (not isinstance(instruction, str) or len(instruction.encode()) > 262144
            or not isinstance(input_sha256, str) or SHA256_PATTERN.fullmatch(input_sha256) is None
            or hashlib.sha256(instruction.encode()).hexdigest() != input_sha256):
        raise SystemExit("F6 ready event input binding is invalid")
    signals = re.findall(r"Ready signal: (\{[^\n]+\})", instruction)
    if len(signals) != 1:
        raise SystemExit("F6 ready event input binding is invalid")
    try:
        signal = json.loads(signals[0])
    except (ValueError, TypeError):
        raise SystemExit("F6 ready event input binding is invalid") from None
    if (not isinstance(signal, dict) or set(signal) != {
            "kind", "data_ready", "identity", "status", "updated_at", "result_artifact_id"}
            or signal.get("kind") != "signal_producer_jobs" or signal.get("data_ready") is not True
            or signal.get("status") != "completed"
            or not isinstance(signal.get("identity"), str) or not SIGNAL_JOB_PATTERN.fullmatch(signal["identity"])
            or not isinstance(signal.get("result_artifact_id"), str)
            or not ARTIFACT_PATTERN.fullmatch(signal["result_artifact_id"])
            or not isinstance(signal.get("updated_at"), str) or len(signal["updated_at"]) > 64
            or event_key != "ready-v1:" + hashlib.sha256(json.dumps(signal, sort_keys=True).encode()).hexdigest()):
        raise SystemExit("F6 ready event input binding is invalid")
    return signal


def _check_environment() -> str:
    if os.environ.get("BYQ_F6_FIXTURE") != "1":
        raise SystemExit("explicit isolated fixture invocation required")
    project = os.environ.get("COMPOSE_PROJECT_NAME", "")
    if not PROJECT_PATTERN.fullmatch(project) or os.environ.get("BYQ_F6_CI_PROJECT") != project:
        raise SystemExit("dedicated CI project required")
    return project


def _audit_readback(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("action") != "audit":
        raise SystemExit("only a scoped audit read is supported")
    stage = payload.get("stage")
    if stage not in {"fg1", "fg2", "background"}:
        raise SystemExit("invalid F6 audit stage")
    task_id = _required(payload, "task_id", TASK_PATTERN)
    conversation_id = _required(payload, "conversation_id", CONVERSATION_PATTERN)
    trace_id = _required(payload, "trace_id", TRACE_PATTERN)
    root_run_id = _required(payload, "runtime_root_id", RUNTIME_ROOT_PATTERN)
    if payload.get("owner") != OWNER:
        raise SystemExit("invalid F6 audit owner")

    backtest_task_id = payload.get("backtest_task_id")
    if stage in {"fg2", "background"}:
        backtest_task_id = _required(payload, "backtest_task_id", BACKTEST_TASK_PATTERN)
    elif backtest_task_id is not None:
        raise SystemExit("unexpected F6 audit scope")

    draft_id = payload.get("strategy_draft_artifact_id")
    version_id = payload.get("strategy_version_artifact_id")
    if stage == "fg1":
        draft_id = _required(payload, "strategy_draft_artifact_id", ARTIFACT_PATTERN)
        version_id = _required(payload, "strategy_version_artifact_id", ARTIFACT_PATTERN)
    elif draft_id is not None or version_id is not None:
        raise SystemExit("unexpected F6 audit scope")

    reservation_id = payload.get("reservation_id")
    settlement_sha256 = payload.get("settlement_sha256")
    if stage == "background":
        reservation_id = _required(payload, "reservation_id", RESERVATION_PATTERN)
        settlement_sha256 = _required(payload, "settlement_sha256", SHA256_PATTERN)
    elif reservation_id is not None or settlement_sha256 is not None:
        raise SystemExit("unexpected F6 audit scope")

    # app.db imports no store and creates no connection/schema. Construct a
    # dedicated engine from the running Backend's configured URL; do not
    # instantiate PgStoreMixin/AgentResearchStore because those bootstrap DDL.
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("BYQ_DATABASE_URL")
    if not database_url:
        raise SystemExit("backend database URL unavailable")
    engine = create_engine(database_url, pool_size=1, max_overflow=0, pool_pre_ping=True, future=True)
    parameters = {"owner": OWNER, "conversation_id": conversation_id, "trace_id": trace_id,
                  "task_id": task_id, "root_run_id": root_run_id}
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                task_rows = connection.execute(text("""
                    SELECT t.task_id, t.owner_principal, t.workspace_id, t.conversation_id,
                           t.trace_id, t.status AS task_status,
                           c.runtime_session_id, c.owner_principal AS conversation_owner,
                           c.workspace_id AS conversation_workspace, c.trace_id AS conversation_trace
                    FROM research_tasks AS t
                    JOIN product_conversations AS c
                      ON c.conversation_id = t.conversation_id
                     AND c.owner_principal = t.owner_principal
                     AND c.workspace_id = t.workspace_id
                    WHERE t.task_id = :task_id AND t.owner_principal = :owner
                      AND t.conversation_id = :conversation_id AND t.trace_id = :trace_id
                    LIMIT 2
                """), parameters).mappings().all()
                if len(task_rows) != 1:
                    raise SystemExit("exact F6 task/conversation scope not found")
                task = dict(task_rows[0])
                runtime_session_id = task.get("runtime_session_id")
                if (not isinstance(runtime_session_id, str)
                        or SESSION_PATTERN.fullmatch(runtime_session_id) is None
                        or task.get("conversation_owner") != OWNER
                        or task.get("conversation_workspace") != task.get("workspace_id")
                        or task.get("conversation_trace") != trace_id):
                    raise SystemExit("exact F6 Product conversation scope changed")

                root_parameters = {**parameters, "workspace_id": task["workspace_id"],
                                   "session_id": runtime_session_id}
                root_rows = connection.execute(text("""
                    SELECT root_run_id, owner_principal, workspace_id, session_id, trace_id,
                           status, authority_status, terminal_sequence, terminal_event_sha256
                    FROM agent_runtime_turns
                    WHERE root_run_id = :root_run_id AND owner_principal = :owner
                      AND workspace_id = :workspace_id AND session_id = :session_id
                      AND trace_id = :trace_id
                    LIMIT 2
                """), root_parameters).mappings().all()
                if not root_rows:
                    root_identity_rows = connection.execute(text("""
                        SELECT root_run_id, owner_principal, workspace_id, session_id, trace_id
                        FROM agent_runtime_turns WHERE root_run_id = :root_run_id LIMIT 2
                    """), {"root_run_id": root_run_id}).mappings().all()
                    if not root_identity_rows:
                        transaction.rollback()
                        return _not_ready(stage, "runtime_root_not_visible")
                    raise SystemExit("F6 Runtime root exists outside the exact owner/session/workspace/trace scope")
                if len(root_rows) != 1:
                    raise SystemExit("F6 Runtime root identity is ambiguous")
                root = dict(root_rows[0])
                terminal_digest = root.get("terminal_event_sha256")
                if (root.get("status") == "active" and root.get("authority_status") == "active"
                        and root.get("terminal_sequence") is None and terminal_digest is None):
                    transaction.rollback()
                    return _not_ready(stage, "runtime_root_active")
                if (root.get("status") != "completed" or root.get("authority_status") != "closed"
                        or type(root.get("terminal_sequence")) is not int
                        or root.get("terminal_sequence") < 1
                        or not isinstance(terminal_digest, str)
                        or SHA256_PATTERN.fullmatch(terminal_digest) is None):
                    raise SystemExit("F6 Runtime root has no exact completed terminal proof")

                run_rows = connection.execute(text("""
                    SELECT run_id, owner_principal, actor_principal, role_id, role_version,
                           trace_id, session_id, dsh_run_id, root_run_id, status, authority_status
                    FROM agent_runs
                    WHERE root_run_id = :root_run_id AND owner_principal = :owner
                      AND workspace_id = :workspace_id AND session_id = :session_id
                      AND trace_id = :trace_id
                    ORDER BY run_id LIMIT 3
                """), root_parameters).mappings().all()
                if len(run_rows) != 1:
                    raise SystemExit("F6 Runtime root does not identify one AgentRun")
                run = dict(run_rows[0])
                if (not isinstance(run.get("run_id"), str)
                        or AGENT_RUN_PATTERN.fullmatch(run["run_id"]) is None
                        or run.get("actor_principal") != "byq-product-agent-" + runtime_session_id
                        or run.get("role_id") != "quant_orchestrator"
                        or run.get("status") != "completed"
                        or run.get("authority_status") != "closed"):
                    raise SystemExit("F6 AgentRun terminal or owner context is invalid")

                if root.get("root_run_id") != root_run_id:
                    raise SystemExit("F6 Runtime root identity changed during read")

                audit_rows = connection.execute(text("""
                    SELECT audit_id, run_id, owner_principal, actor_principal, action, outcome,
                           resource_type, resource_id
                    FROM agent_audit
                    WHERE run_id = :agent_run_id AND owner_principal = :owner
                    ORDER BY created_at ASC, audit_id ASC LIMIT 33
                """), {"agent_run_id": run["run_id"], "owner": OWNER}).mappings().all()
                if len(audit_rows) > 32:
                    raise SystemExit("F6 AgentRun audit event count exceeds the exact bounded contract")
                events = [dict(row) for row in audit_rows]

                settlement = None
                if stage == "background":
                    receipt_rows = connection.execute(text("""
                        SELECT budget.item->>'reservation_id' AS reservation_id,
                               (budget.item->>'grant_version')::integer AS grant_version,
                               budget.item->>'run_id' AS run_id,
                               budget.item->>'status' AS status,
                               budget.item->>'outcome' AS outcome,
                               budget.item->>'event_key' AS event_key,
                               budget.item->>'input_sha256' AS input_sha256,
                               budget.item->>'instruction' AS instruction,
                               budget.item->>'settlement_sha256' AS settlement_sha256,
                               (budget.item->>'dispatch_attempts')::integer AS dispatch_attempts
                        FROM research_tasks AS t
                        CROSS JOIN LATERAL jsonb_array_elements(
                            COALESCE(t.continuation_budget, '[]'::jsonb)
                        ) AS budget(item)
                        WHERE t.task_id = :task_id AND t.owner_principal = :owner
                          AND t.workspace_id = :workspace_id AND t.conversation_id = :conversation_id
                          AND budget.item->>'reservation_id' = :reservation_id
                        LIMIT 2
                    """), {**root_parameters, "reservation_id": reservation_id}).mappings().all()
                    if len(receipt_rows) != 1:
                        raise SystemExit("exact F6 settled request receipt not found")
                    settlement = dict(receipt_rows[0])
                    instruction = settlement.pop("instruction")
                    settlement["ready_signal"] = _ready_signal_from_receipt(
                        instruction, settlement["input_sha256"], settlement["event_key"])
                    if (settlement.get("run_id") != root_run_id
                            or settlement.get("grant_version") != 1
                            or settlement.get("status") != "settled"
                            or settlement.get("outcome") != "completed"
                            or settlement.get("dispatch_attempts") != 1
                            or settlement.get("settlement_sha256") != settlement_sha256):
                        raise SystemExit("F6 settlement is not bound to the exact Runtime root")

                transaction.rollback()
            except BaseException:
                transaction.rollback()
                raise
    finally:
        engine.dispose()

    return {
        "schema_version": "f6-agent-run-audit.v1", "stage": stage,
        "task": {key: task[key] for key in (
            "task_id", "owner_principal", "workspace_id", "conversation_id", "trace_id", "task_status")},
        "runtime_root": root, "runtime_session_id": runtime_session_id,
        "agent_run": run, "events": events, "settlement": settlement,
    }


def main() -> None:
    _check_environment()
    if len(sys.argv) != 2:
        raise SystemExit("one exact fixture action is required")
    action = sys.argv[1]
    if action == "user":
        from tests.workspace_helpers import trusted_agent_context

        context = trusted_agent_context(OWNER)
        workspace_id = context["x-byq-workspace-id"]
        print(json.dumps({"owner": OWNER, "workspace_id": workspace_id}, sort_keys=True))
        return
    if action == "audit":
        payload = json.load(sys.stdin)
        print(json.dumps(_audit_readback(payload), sort_keys=True, separators=(",", ":")))
        return
    raise SystemExit("unsupported F6 fixture action")


if __name__ == "__main__":
    main()
