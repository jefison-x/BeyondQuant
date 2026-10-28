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

    signal_job_id = payload.get("signal_job_id")
    if stage == "background":
        signal_job_id = _required(payload, "signal_job_id", SIGNAL_JOB_PATTERN)
    elif signal_job_id is not None:
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
                    SELECT root_run_id, owner_principal, workspace_id, session_id, trace_id, authority_boot_id,
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

                fg1_callback_exit_verified = False
                if stage == "fg1":
                    from app.agent_research import (
                        _local_validation_callback_exit_from_audit_row,
                        local_validation_callback_exit_audit_id,
                    )
                    claim_rows = connection.execute(text("""
                        SELECT * FROM agent_domain_call_claims
                        WHERE root_run_id=:root_run_id AND task_id=:task_id
                          AND agent_run_id=:agent_run_id AND action='byq_strategy_validate'
                          AND idempotency_key=:idempotency_key LIMIT 2
                    """), {**root_parameters, "agent_run_id": run["run_id"],
                            "idempotency_key": "f6-ci-draft-" + os.environ["COMPOSE_PROJECT_NAME"]}).mappings().all()
                    if len(claim_rows) != 1:
                        raise SystemExit("exact F6 strategy validation claim is not unique")
                    claim = dict(claim_rows[0])
                    result = claim.get("result_json")
                    outcome = result.get("result") if isinstance(result, dict) else None
                    artifact = outcome.get("artifact") if isinstance(outcome, dict) else None
                    if (claim.get("status") != "succeeded" or not isinstance(result, dict)
                            or result.get("state") != "succeeded"
                            or not isinstance(artifact, dict)
                            or artifact.get("artifact_id") != draft_id
                            or artifact.get("task_id") != task_id or artifact.get("status") != "validated"):
                        raise SystemExit("exact F6 strategy validation result is not the expected Draft")
                    callback_rows = connection.execute(text("""
                        SELECT a.*,r.root_run_id AS audit_root_run_id,
                               r.owner_principal AS audit_owner_principal,
                               r.actor_principal AS audit_actor_principal,
                               t.workspace_id AS audit_workspace_id
                        FROM agent_audit a JOIN agent_runs r ON r.run_id=a.run_id
                        JOIN agent_runtime_turns t ON t.root_run_id=r.root_run_id
                        WHERE a.audit_id=:audit_id AND a.run_id=:agent_run_id LIMIT 2
                    """), {"audit_id": local_validation_callback_exit_audit_id(claim["claim_id"]),
                            "agent_run_id": run["run_id"]}).mappings().all()
                    if len(callback_rows) != 1:
                        raise SystemExit("exact F6 strategy validation callback audit is missing")
                    receipt = _local_validation_callback_exit_from_audit_row(
                        dict(callback_rows[0]), claim["claim_id"])
                    expected_scope = {"owner_principal": OWNER, "workspace_id": task["workspace_id"],
                        "actor_principal": run["actor_principal"], "session_id": runtime_session_id,
                        "trace_id": trace_id, "generation": run["dsh_run_id"]}
                    if (receipt is None or receipt.get("scope") != expected_scope
                            or receipt.get("root_run_id") != root_run_id
                            or receipt.get("authority_boot_id") != root["authority_boot_id"]
                            or any(receipt.get(field) != claim[field] for field in (
                                "claim_id", "agent_run_id", "task_id", "action", "idempotency_key",
                                "request_sha256", "input_sha256", "evidence_sequence"))):
                        raise SystemExit("exact F6 strategy validation callback receipt differs from its claim")
                    matching = [event for event in events if event["audit_id"] == callback_rows[0]["audit_id"]]
                    if len(matching) != 1:
                        raise SystemExit("exact F6 strategy validation callback is absent from the audit set")
                    fg1_callback_exit_verified = True

                settlement = None
                if stage == "background":
                    from packages.contracts.continuation_request import (
                        validate_reservation_v3, validate_request_usage_v2,
                    )
                    receipt_rows = connection.execute(text("""
                        SELECT budget.item AS receipt
                        FROM research_tasks AS t
                        CROSS JOIN LATERAL jsonb_array_elements(
                            COALESCE(t.continuation_budget, '[]'::jsonb)
                        ) AS budget(item)
                        WHERE t.task_id = :task_id AND t.owner_principal = :owner
                          AND t.workspace_id = :workspace_id AND t.conversation_id = :conversation_id
                          AND budget.item->>'signal_job_id' = :signal_job_id
                        LIMIT 2
                    """), {**root_parameters, "signal_job_id": signal_job_id}).mappings().all()
                    if not receipt_rows:
                        transaction.rollback()
                        return _not_ready(stage, "settlement_not_visible")
                    if len(receipt_rows) != 1:
                        raise SystemExit("exact F6 settled request receipt is ambiguous")
                    settlement = receipt_rows[0]["receipt"]
                    if settlement.get("status") in {"reserved", "accepted", "outcome_unknown"}:
                        transaction.rollback()
                        return _not_ready(stage, "settlement_not_visible")
                    carrier = validate_reservation_v3(settlement.get("reservation"))
                    usage = validate_request_usage_v2(settlement.get("request_usage"))
                    digest = carrier["idempotency_key"].removeprefix("task-ready-event:")
                    runtime_receipt = {"reservation_id": settlement.get("reservation_id"),
                                       "idempotency_key": carrier["idempotency_key"],
                                       "status": "settled", "run_id": root_run_id,
                                       "outcome": "completed", "request_usage": usage}
                    if (settlement.get("run_id") != root_run_id
                            or settlement.get("schema_version") != "task-continuation-ledger-entry.v1"
                            or settlement.get("reservation_id") != "continuation_" + digest[:32]
                            or settlement.get("event_key") != "ready-v1:" + digest
                            or settlement.get("signal_job_id") != signal_job_id
                            or settlement.get("status") != "settled"
                            or settlement.get("outcome") != "completed"
                            or settlement.get("dispatch_attempts") != 1
                            or usage["execution_profile"] != carrier["execution_profile"]
                            or usage["request_limits"] != carrier["request_limits"]
                            or settlement.get("settlement_sha256") != hashlib.sha256(json.dumps(
                                runtime_receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()):
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
        "runtime_root": {key: value for key, value in root.items() if key != "authority_boot_id"},
        "runtime_session_id": runtime_session_id,
        "agent_run": run, "events": events, "settlement": settlement,
        **({"fg1_callback_exit_verified": fg1_callback_exit_verified} if stage == "fg1" else {}),
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
