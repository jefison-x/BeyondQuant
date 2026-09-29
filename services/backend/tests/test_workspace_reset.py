"""Isolated PostgreSQL coverage for the narrow workspace reset contract."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.agent_research import AgentResearchStore
from app.conversation_catalog import ConversationCatalogStore
from app.ml_strategy import normalize_ml_strategy
from app.research import ResearchStore
from app.strategy_artifact import prepare_strategy, strategy_version_content
from app.workspace_reset import WorkspaceResetBlocked, WorkspaceResetStore
from app.workspace_runtime_reset import WorkspaceRuntimeResetConflict, WorkspaceRuntimeResetStore
from tests.workspace_helpers import trusted_agent_context
from tests.test_research import snapshot
from tests.test_strategy_artifact import strategy_payload
from tests.test_web_research import evidence_fixture
from tests.test_ml_strategy import valid_strategy

pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required",
)


def _context(owner: str, session: str, trace: str) -> dict[str, str]:
    headers = trusted_agent_context(owner, session_id=session, trace_id=trace)
    return {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}


def _research_graph(owner: str, *, suffix: str) -> tuple[dict[str, str], str, str, str, str]:
    context = _context(owner, f"reset-session-{suffix}", f"reset-trace-{suffix}")
    catalog = ConversationCatalogStore()
    try:
        conversation = catalog.create(owner, context["session_id"], context["trace_id"])
    finally:
        catalog.close()
    research = ResearchStore()
    try:
        task = research.create_task({
            "owner_principal": owner,
            "title": "Disposable reset task",
            "objective": "Prove workspace deletion remains owner-scoped.",
            "trace_id": context["trace_id"],
            "idempotency_key": f"reset-task-{suffix}",
        }, trusted_context=context)
        experiment = research.create_experiment({
            "task_id": task["task_id"],
            "name": "Disposable reset experiment",
            "input_snapshot": snapshot(),
            "trace_id": context["trace_id"],
            "idempotency_key": f"reset-experiment-{suffix}",
        })
        artifact = research.create_artifact({
            "task_id": task["task_id"],
            "experiment_id": experiment["experiment_id"],
            "kind": "research_evidence",
            "content": {"disposable": True},
            "lineage": [],
            "trace_id": context["trace_id"],
            "idempotency_key": f"reset-artifact-{suffix}",
        }, trusted_owner=owner, trusted_workspace=context["workspace_id"])
    finally:
        research.close()
    return context, conversation["conversation_id"], task["task_id"], experiment["experiment_id"], artifact["artifact_id"]


def _approved_strategy(research: ResearchStore, owner: str, context: dict[str, str],
                       task_id: str, *, suffix: str) -> tuple[dict[str, object], dict[str, object]]:
    content = strategy_version_content(prepare_strategy(strategy_payload()))
    version = research.create_content_addressed_artifact({
        "task_id": task_id, "kind": "strategy_version", "content": content, "lineage": [],
        "trace_id": context["trace_id"], "idempotency_key": f"reset-version-{suffix}",
    }, trusted_owner=owner, trusted_workspace=context["workspace_id"])
    if version["status"] == "draft":
        version = research.transition("artifact", version["artifact_id"], "validated",
                                      f"reset-version-validate-{suffix}")
    approval_content = {
        "schema_version": "strategy-approval-v1",
        "strategy_version_id": content["version_id"],
        "strategy_version_artifact_id": version["artifact_id"],
        "decision": "approved", "reviewer_principal": owner, "rationale": "Reviewed",
        "execution_authorized": True, "execution_outcome": "not_started",
    }
    approval = research.create_artifact({
        "task_id": task_id, "kind": "strategy_approval", "content": approval_content,
        "lineage": [{"kind": "artifact", "id": version["artifact_id"]}],
        "trace_id": context["trace_id"], "idempotency_key": f"reset-approval-{suffix}",
    }, trusted_owner=owner, trusted_workspace=context["workspace_id"])
    if approval["status"] == "draft":
        approval = research.transition("artifact", approval["artifact_id"], "validated",
                                       f"reset-approval-validate-{suffix}")
    return version, approval


def _approved_ml_strategy(research: ResearchStore, owner: str, context: dict[str, str],
                          task_id: str, *, suffix: str, decision: str = "approved") -> tuple[dict[str, object], dict[str, object]]:
    content = normalize_ml_strategy(valid_strategy())
    version = research.create_content_addressed_artifact({
        "task_id": task_id, "kind": "ml_strategy_version", "content": content, "lineage": [],
        "trace_id": context["trace_id"], "idempotency_key": f"reset-ml-version-{suffix}",
    }, trusted_owner=owner, trusted_workspace=context["workspace_id"])
    if version["status"] == "draft":
        version = research.transition("artifact", version["artifact_id"], "validated",
                                      f"reset-ml-version-validate-{suffix}")
    approval = research.create_artifact({
        "task_id": task_id, "kind": "ml_strategy_approval", "content": {
            "schema_version": "ml-strategy-approval.v1",
            "ml_strategy_version_id": content["version_id"],
            "ml_strategy_artifact_id": version["artifact_id"],
            "decision": decision, "reviewer_principal": owner, "rationale": "Reviewed",
            "execution_authorized": decision == "approved", "execution_outcome": "not_started",
        }, "lineage": [{"kind": "artifact", "id": version["artifact_id"]}],
        "trace_id": context["trace_id"], "idempotency_key": f"reset-ml-approval-{suffix}",
    }, trusted_owner=owner, trusted_workspace=context["workspace_id"])
    if approval["status"] == "draft":
        approval = research.transition("artifact", approval["artifact_id"], "validated",
                                       f"reset-ml-approval-validate-{suffix}")
    return version, approval


def test_ml_strategy_approval_archive_precedes_workspace_deletion() -> None:
    suffix = uuid4().hex[:12]
    owner_a, owner_b = f"ml-reset-a-{suffix}", f"ml-reset-b-{suffix}"
    context_a, _, task_a, _, _ = _research_graph(owner_a, suffix=suffix + "a")
    context_b, _, task_b, _, _ = _research_graph(owner_b, suffix=suffix + "b")
    research, store = ResearchStore(), WorkspaceResetStore()
    try:
        version_a, approval_a = _approved_ml_strategy(research, owner_a, context_a, task_a,
                                                      suffix=suffix + "a", decision="rejected")
        version_b, approval_b = _approved_ml_strategy(research, owner_b, context_b, task_b, suffix=suffix + "b")
        approval_snapshot = store._fetch_one(
            "SELECT to_jsonb(a) AS snapshot FROM artifacts a WHERE artifact_id=:id",
            {"id": approval_a["artifact_id"]})["snapshot"]
        version_snapshot = store._fetch_one(
            "SELECT to_jsonb(a) AS snapshot FROM artifacts a WHERE artifact_id=:id",
            {"id": version_a["artifact_id"]})["snapshot"]

        store._execute("UPDATE artifacts SET status='draft' WHERE artifact_id=:id",
                       {"id": version_a["artifact_id"]})
        with pytest.raises(WorkspaceResetBlocked, match="incomplete"):
            store.reset_workspace(owner_principal=owner_a, workspace_id=context_a["workspace_id"])
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 0
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a})
        store._execute("UPDATE artifacts SET status='validated' WHERE artifact_id=:id",
                       {"id": version_a["artifact_id"]})

        result = store.reset_workspace(owner_principal=owner_a, workspace_id=context_a["workspace_id"])
        assert result["deleted"]["research_tasks"] == 1
        assert result["deleted"]["artifacts"] == 3
        assert "strategy_approval_fact_archive" not in result["deleted"]
        archived = store._fetch_one("SELECT * FROM strategy_approval_fact_archive WHERE source_artifact_id=:id",
                                    {"id": approval_a["artifact_id"]})
        assert archived["approval_kind"] == "ml_strategy_approval"
        assert archived["owner_principal"] == owner_a
        assert archived["workspace_id"] == context_a["workspace_id"]
        assert archived["research_task_id"] == task_a
        assert archived["strategy_version_artifact_id"] == version_a["artifact_id"]
        assert archived["approval_snapshot"] == approval_snapshot
        assert archived["strategy_version_snapshot"] == version_snapshot
        assert archived["approval_snapshot"]["content"]["decision"] == "rejected"
        assert archived["approval_snapshot"]["content"]["execution_authorized"] is False
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": approval_a["artifact_id"]}) is None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": version_a["artifact_id"]}) is None
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a}) is None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": approval_b["artifact_id"]}) is not None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": version_b["artifact_id"]}) is not None
        assert store.reset_workspace(owner_principal=owner_a, workspace_id=context_a["workspace_id"])["already_empty"]
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 1
    finally:
        store.close()
        research.close()


def test_reset_deletes_only_the_selected_workspace_and_is_idempotent() -> None:
    owner_a = "workspace-reset-a"
    owner_b = "workspace-reset-b"
    context_a, conversation_a, task_a, experiment_a, artifact_a = _research_graph(owner_a, suffix="a")
    context_b, conversation_b, task_b, experiment_b, artifact_b = _research_graph(owner_b, suffix="b")
    store = WorkspaceResetStore()
    try:
        preview = store.reset_workspace(owner_principal=owner_a,
                                        workspace_id=context_a["workspace_id"], preview=True)
        assert preview["ready"] is True
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a}) is not None
        first = store.reset_workspace(owner_principal=owner_a, workspace_id=context_a["workspace_id"])
        assert first["schema_version"] == "workspace-reset.v1"
        assert first["already_empty"] is False
        assert first["deleted"]["research_tasks"] == 1
        assert first["deleted"]["experiments"] == 1
        assert first["deleted"]["artifacts"] == 1
        assert first["deleted"]["product_conversations"] == 1

        second = store.reset_workspace(owner_principal=owner_a, workspace_id=context_a["workspace_id"])
        assert second["already_empty"] is True
        assert not any(second["deleted"].values())

        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a}) is None
        assert store._fetch_one("SELECT experiment_id FROM experiments WHERE experiment_id=:id", {"id": experiment_a}) is None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id", {"id": artifact_a}) is None
        assert store._fetch_one("SELECT conversation_id FROM product_conversations WHERE conversation_id=:id", {"id": conversation_a}) is None

        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_b}) is not None
        assert store._fetch_one("SELECT experiment_id FROM experiments WHERE experiment_id=:id", {"id": experiment_b}) is not None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id", {"id": artifact_b}) is not None
        assert store._fetch_one("SELECT conversation_id FROM product_conversations WHERE conversation_id=:id", {"id": conversation_b}) is not None
        assert store._fetch_one("SELECT workspace_id FROM workspaces WHERE workspace_id=:id", {"id": context_a["workspace_id"]}) is not None
        assert store._fetch_one("SELECT username FROM users WHERE username=:owner", {"owner": owner_a}) is not None
    finally:
        store.close()


def test_active_job_blocks_reset_without_partial_deletion() -> None:
    owner = "workspace-reset-active-job"
    context, _conversation, task_id, _experiment, _artifact = _research_graph(owner, suffix="active-job")
    store = WorkspaceResetStore()
    try:
        now = datetime.now(timezone.utc).isoformat()
        store._execute("""
            INSERT INTO factor_jobs
                (job_id,task_id,workspace_id,owner_principal,experiment_id,trace_id,idempotency_key,
                 request_hash,input_manifest_id,request_json,status,attempts,max_attempts,created_at,updated_at)
            VALUES
                ('factor_reset_active',:task,:workspace,:owner,NULL,'reset-trace-active-job','reset-active',
                 'hash','manifest','{}'::jsonb,'queued',0,3,:now,:now)
        """, {"task": task_id, "workspace": context["workspace_id"], "owner": owner, "now": now})

        with pytest.raises(WorkspaceResetBlocked, match="factor_jobs"):
            store.reset_workspace(owner_principal=owner, workspace_id=context["workspace_id"])
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_id}) is not None
        assert store._fetch_one("SELECT job_id FROM factor_jobs WHERE job_id='factor_reset_active'") is not None
    finally:
        store.close()


def test_active_agent_root_blocks_reset_without_partial_deletion() -> None:
    owner = "workspace-reset-active-root"
    context, _conversation, task_id, _experiment, _artifact = _research_graph(owner, suffix="active-root")
    agents = AgentResearchStore()
    reset = WorkspaceResetStore()
    try:
        now = datetime.now(timezone.utc).isoformat()
        agents._execute("""
            INSERT INTO agent_runtime_turns
                (root_run_id,owner_principal,workspace_id,session_id,trace_id,status,authority_status,
                 created_at,updated_at)
            VALUES ('root_reset_active',:owner,:workspace,'reset-session-active-root',
                    'reset-trace-active-root','active','active',:now,:now)
        """, {"owner": owner, "workspace": context["workspace_id"], "now": now})

        with pytest.raises(WorkspaceResetBlocked, match="Agent root"):
            reset.reset_workspace(owner_principal=owner, workspace_id=context["workspace_id"])
        assert reset._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_id}) is not None
    finally:
        agents.close()
        reset.close()


def test_unknown_approval_outcome_blocks_reset_without_deleting_research() -> None:
    owner = "workspace-reset-unknown-approval"
    context, _conversation, task_id, _experiment, _artifact = _research_graph(owner, suffix="unknown")
    store = WorkspaceResetStore()
    try:
        now = datetime.now(timezone.utc).isoformat()
        store._execute("""INSERT INTO agent_runs
            (run_id,owner_principal,actor_principal,role_id,role_version,trace_id,session_id,
             dsh_run_id,status,authority_status,idempotency_key,request_hash,created_at,updated_at,version,workspace_id)
            VALUES ('run_reset_unknown',:owner,:owner,'quant_research','1',:trace,:session,
                    'dsh-reset','completed','closed','reset-unknown','hash',:now,:now,1,:workspace)""",
            {"owner": owner, "trace": context["trace_id"], "session": context["session_id"],
             "workspace": context["workspace_id"], "now": now})
        store._execute("""INSERT INTO agent_approvals
            (approval_id,run_id,owner_principal,actor_principal,action,reason,status,
             execution_outcome,continuation_status,idempotency_key,request_hash,
             created_at,updated_at,workspace_id)
            VALUES ('approval_reset_unknown','run_reset_unknown',:owner,:owner,'test_action',
                    'test','approved','outcome_unknown','outcome_unknown','reset-unknown',
                    'hash',:now,:now,:workspace)""",
            {"owner": owner, "workspace": context["workspace_id"], "now": now})
        with pytest.raises(WorkspaceResetBlocked, match="unknown approval"):
            store.reset_workspace(owner_principal=owner, workspace_id=context["workspace_id"])
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_id}) is not None
    finally:
        store.close()


def test_web_evidence_audit_survives_reset_without_pinning_disposable_artifact() -> None:
    suffix = uuid4().hex[:12]
    owner = f"web-audit-reset-{suffix}"
    context, _conversation, task_id, _experiment, generic_artifact_id = _research_graph(
        owner, suffix=suffix)
    research, store = ResearchStore(), WorkspaceResetStore()
    try:
        web_artifact = research.create_artifact({
            "task_id": task_id, "kind": "web_research_evidence",
            "content": evidence_fixture(),
            "lineage": [], "trace_id": context["trace_id"],
            "idempotency_key": f"web-audit-artifact-{suffix}",
        }, trusted_owner=owner, trusted_workspace=context["workspace_id"])
        now = datetime.now(timezone.utc).isoformat()
        run_id = f"run_web_audit_{suffix}"
        store._execute("""INSERT INTO agent_runs
            (run_id,owner_principal,actor_principal,role_id,role_version,trace_id,session_id,
             dsh_run_id,status,authority_status,idempotency_key,request_hash,created_at,updated_at,version,workspace_id)
            VALUES (:run,:owner,:owner,'quant_research','1',:trace,:session,
                    'dsh-web-audit','completed','closed',:key,'hash',:now,:now,1,:workspace)""",
            {"run": run_id, "owner": owner, "trace": context["trace_id"],
             "session": context["session_id"], "key": f"web-audit-run-{suffix}",
             "now": now, "workspace": context["workspace_id"]})
        audit_id = f"agent_audit_web_reset_{suffix}"
        store._execute("""INSERT INTO agent_audit
            (audit_id,run_id,owner_principal,actor_principal,action,outcome,resource_type,
             resource_id,detail_json,created_at)
            VALUES (:audit,:run,:owner,:owner,'byq_web_evidence_create','saved','artifact',
                    :artifact,'{}'::jsonb,:now)""",
            {"audit": audit_id, "run": run_id, "owner": owner,
             "artifact": web_artifact["artifact_id"], "now": now})

        blocked_id = f"agent_audit_other_reset_{suffix}"
        store._execute("""INSERT INTO agent_audit
            (audit_id,run_id,owner_principal,actor_principal,action,outcome,resource_type,
             resource_id,detail_json,created_at)
            VALUES (:audit,:run,:owner,:owner,'other_artifact_action','success','artifact',
                    :artifact,'{}'::jsonb,:now)""",
            {"audit": blocked_id, "run": run_id, "owner": owner,
             "artifact": generic_artifact_id, "now": now})
        with pytest.raises(WorkspaceResetBlocked, match="Agent audit"):
            store.reset_workspace(owner_principal=owner, workspace_id=context["workspace_id"])
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": web_artifact["artifact_id"]}) is not None
        store._execute("DELETE FROM agent_audit WHERE audit_id=:audit", {"audit": blocked_id})

        missing_type_id = f"agent_audit_missing_type_{suffix}"
        store._execute("""INSERT INTO agent_audit
            (audit_id,run_id,owner_principal,actor_principal,action,outcome,resource_type,
             resource_id,detail_json,created_at)
            VALUES (:audit,:run,:owner,:owner,'byq_web_evidence_create','saved',NULL,
                    :artifact,'{}'::jsonb,:now)""",
            {"audit": missing_type_id, "run": run_id, "owner": owner,
             "artifact": web_artifact["artifact_id"], "now": now})
        with pytest.raises(WorkspaceResetBlocked, match="Agent audit"):
            store.reset_workspace(owner_principal=owner, workspace_id=context["workspace_id"])
        store._execute("DELETE FROM agent_audit WHERE audit_id=:audit", {"audit": missing_type_id})

        result = store.reset_workspace(owner_principal=owner, workspace_id=context["workspace_id"])
        assert result["deleted"]["research_tasks"] == 1
        assert result["deleted"]["artifacts"] == 2
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": web_artifact["artifact_id"]}) is None
        retained = store._fetch_one("SELECT action,outcome,resource_type,resource_id FROM agent_audit WHERE audit_id=:audit",
                                        {"audit": audit_id})
        assert retained == {"action": "byq_web_evidence_create", "outcome": "saved",
                            "resource_type": "artifact", "resource_id": web_artifact["artifact_id"]}
        assert store.reset_workspace(owner_principal=owner,
                                     workspace_id=context["workspace_id"])["already_empty"] is True
    finally:
        store.close()
        research.close()


def test_product_workspace_reset_requires_release_proof_is_scoped_and_idempotent() -> None:
    suffix = uuid4().hex[:12]
    owner_a = f"product-reset-a-{suffix}"
    owner_b = f"product-reset-b-{suffix}"
    context_a, conversation_a, task_a, _experiment_a, artifact_a = _research_graph(owner_a, suffix=suffix + "a")
    context_b, conversation_b, task_b, _experiment_b, _artifact_b = _research_graph(owner_b, suffix=suffix + "b")
    research = ResearchStore()
    agents = AgentResearchStore()
    reset = WorkspaceRuntimeResetStore()
    store = WorkspaceResetStore()
    conversations = ConversationCatalogStore()
    try:
        version_a, approval_a = _approved_strategy(research, owner_a, context_a, task_a, suffix=suffix + "a")
        version_b, approval_b = _approved_strategy(research, owner_b, context_b, task_b, suffix=suffix + "b")
        approval_snapshot = store._fetch_one(
            "SELECT to_jsonb(a) AS snapshot FROM artifacts a WHERE artifact_id=:id",
            {"id": approval_a["artifact_id"]},
        )["snapshot"]
        version_snapshot = store._fetch_one(
            "SELECT to_jsonb(a) AS snapshot FROM artifacts a WHERE artifact_id=:id",
            {"id": version_a["artifact_id"]},
        )["snapshot"]
        completed_job_id = f"factor_reset_completed_{suffix}"
        now = datetime.now(timezone.utc).isoformat()
        store._execute("""INSERT INTO factor_jobs
            (job_id,task_id,workspace_id,owner_principal,experiment_id,trace_id,idempotency_key,
             request_hash,input_manifest_id,request_json,status,attempts,max_attempts,result_artifact_id,
             created_at,updated_at,finished_at)
            VALUES (:job,:task,:workspace,:owner,NULL,:trace,:key,'hash','manifest','{}'::jsonb,
                    'completed',1,3,:artifact,:now,:now,:now)""",
            {"job": completed_job_id, "task": task_a, "workspace": context_a["workspace_id"],
             "owner": owner_a, "trace": context_a["trace_id"], "key": f"reset-completed-{suffix}",
             "artifact": artifact_a, "now": now})
        bad_content = dict(approval_a["content"])
        bad_content["strategy_version_id"] = version_b["content"]["version_id"]
        bad_content["strategy_version_artifact_id"] = version_b["artifact_id"]
        bad_lineage = [*approval_snapshot["lineage"][:-1],
                       {"kind": "artifact", "id": version_b["artifact_id"]}]
        bad_payload = ResearchStore._artifact_payload({
            "task_id": task_a, "kind": "strategy_approval", "content": bad_content,
            "lineage": bad_lineage, "trace_id": context_a["trace_id"],
            "idempotency_key": f"reset-approval-{suffix}a",
        })
        store._execute("""UPDATE artifacts SET content=:content,content_sha256=:digest,lineage=:lineage
            WHERE artifact_id=:id""", {"content": bad_payload["content"],
            "digest": bad_payload["content_sha256"], "lineage": bad_lineage,
            "id": approval_a["artifact_id"]})
        with store.engine.begin() as connection:
            with pytest.raises(WorkspaceResetBlocked, match="cross-Workspace"):
                WorkspaceResetStore.preflight_in_connection(
                    connection, owner_principal=owner_a, workspace_id=context_a["workspace_id"])
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 0
        restored = ResearchStore._artifact_payload({
            "task_id": task_a, "kind": "strategy_approval", "content": approval_a["content"],
            "lineage": approval_a["lineage"], "trace_id": context_a["trace_id"],
            "idempotency_key": f"reset-approval-{suffix}a",
        })
        store._execute("""UPDATE artifacts SET content=:content,content_sha256=:digest,lineage=:lineage
            WHERE artifact_id=:id""", {"content": restored["content"],
            "digest": restored["content_sha256"], "lineage": approval_snapshot["lineage"],
            "id": approval_a["artifact_id"]})

        authority = agents.current_runtime_authority()
        if authority is None:
            authority = agents.rotate_runtime_authority(uuid4().hex)
        root_id = uuid4().hex
        agents.apply_runtime_lifecycle_event(
            {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root_id,
             "sequence": 1, "outcome": "active"},
            trusted_owner=owner_a, trusted_workspace=context_a["workspace_id"],
            trusted_session_id=context_a["session_id"], trusted_trace_id=context_a["trace_id"],
            trusted_boot_id=str(authority["boot_id"]),
        )
        request_key = str(uuid4())
        begin = reset.begin_workspace_reset(
            owner_principal=owner_a, workspace_id=context_a["workspace_id"],
            idempotency_key=request_key,
        )
        assert begin == {
            "schema_version": "workspace-reset-begin.v1",
            "workspace_id": context_a["workspace_id"],
            "reset_id": begin["reset_id"], "status": "pending",
            "sessions": [{"conversation_id": conversation_a,
                          "session_id": context_a["session_id"], "trace_id": context_a["trace_id"]}],
        }
        assert store._fetch_one("SELECT status FROM workspaces WHERE workspace_id=:id",
                                {"id": context_a["workspace_id"]})["status"] == "disabled"
        assert agents._fetch_one(
            "SELECT authority_status FROM agent_runtime_turns WHERE root_run_id=:id",
            {"id": root_id})["authority_status"] == "authority_revoked_unconfirmed"
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 0

        with pytest.raises(WorkspaceRuntimeResetConflict, match="release proof"):
            reset.finalize_workspace_reset(
                owner_principal=owner_a, workspace_id=context_a["workspace_id"],
                reset_id=begin["reset_id"], idempotency_key=request_key, released_sessions=[],
            )
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a})
        assert store._fetch_one("SELECT status FROM workspaces WHERE workspace_id=:id",
                                {"id": context_a["workspace_id"]})["status"] == "disabled"
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 0

        finalized = reset.finalize_workspace_reset(
            owner_principal=owner_a, workspace_id=context_a["workspace_id"],
            reset_id=begin["reset_id"], idempotency_key=request_key,
            released_sessions=[context_a["session_id"]],
        )
        assert finalized["schema_version"] == "workspace-reset-finalize.v1"
        assert finalized["reset_id"] == begin["reset_id"]
        assert finalized["status"] == "reset"
        assert finalized["workspace_id"] == context_a["workspace_id"]
        assert finalized["already_empty"] is False
        assert finalized["deleted"]["research_tasks"] == 1
        assert finalized["deleted"]["factor_jobs"] == 1
        assert finalized["deleted"]["artifacts"] == 3
        assert "strategy_approval_fact_archive" not in finalized["deleted"]
        archived = store._fetch_one("SELECT * FROM strategy_approval_fact_archive WHERE source_artifact_id=:id",
                                    {"id": approval_a["artifact_id"]})
        assert archived["approval_kind"] == "strategy_approval"
        assert archived["owner_principal"] == owner_a
        assert archived["workspace_id"] == context_a["workspace_id"]
        assert archived["research_task_id"] == task_a
        assert archived["strategy_version_artifact_id"] == version_a["artifact_id"]
        assert archived["approval_content_sha256"] == approval_snapshot["content_sha256"]
        assert archived["strategy_version_content_sha256"] == version_snapshot["content_sha256"]
        assert archived["approval_created_at"] == approval_snapshot["created_at"]
        assert archived["strategy_version_created_at"] == version_snapshot["created_at"]
        assert archived["approval_snapshot"] == approval_snapshot
        assert archived["strategy_version_snapshot"] == version_snapshot
        assert datetime.fromisoformat(archived["reset_at"]) >= datetime.fromisoformat(archived["approval_created_at"])
        assert datetime.fromisoformat(archived["reset_at"]) >= datetime.fromisoformat(archived["strategy_version_created_at"])
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 1
        with pytest.raises(DBAPIError, match="immutable"):
            store._execute("UPDATE strategy_approval_fact_archive SET reset_at=now() WHERE source_artifact_id=:id",
                           {"id": approval_a["artifact_id"]})
        assert store._fetch_one("SELECT status FROM workspaces WHERE workspace_id=:id",
                                {"id": context_a["workspace_id"]})["status"] == "active"
        assert agents._fetch_one(
            "SELECT status,authority_status FROM agent_runtime_turns WHERE root_run_id=:id",
            {"id": root_id}) == {"status": "interrupted", "authority_status": "closed"}
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a}) is None
        assert store._fetch_one("SELECT job_id FROM factor_jobs WHERE job_id=:id",
                                {"id": completed_job_id}) is None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": artifact_a}) is None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": approval_a["artifact_id"]}) is None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": version_a["artifact_id"]}) is None
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_b}) is not None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": approval_b["artifact_id"]}) is not None
        assert store._fetch_one("SELECT artifact_id FROM artifacts WHERE artifact_id=:id",
                                {"id": version_b["artifact_id"]}) is not None
        assert conversations._fetch_one(
            "SELECT conversation_id FROM product_conversations WHERE conversation_id=:id",
            {"id": conversation_b}) is not None
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 1

        replay = reset.begin_workspace_reset(
            owner_principal=owner_a, workspace_id=context_a["workspace_id"],
            idempotency_key=request_key,
        )
        assert replay == {
            "schema_version": "workspace-reset-begin.v1",
            "workspace_id": context_a["workspace_id"],
            "status": "completed",
            "receipt": {key: finalized[key] for key in
                         ("status", "workspace_id", "deleted", "already_empty")},
        }
        new_conversation = conversations.create(owner_a, f"new-session-{suffix}", f"new-trace-{suffix}")
        replay_after_new_data = reset.begin_workspace_reset(
            owner_principal=owner_a, workspace_id=context_a["workspace_id"],
            idempotency_key=request_key,
        )
        assert replay_after_new_data == replay
        assert conversations._fetch_one(
            "SELECT conversation_id FROM product_conversations WHERE conversation_id=:id",
            {"id": new_conversation["conversation_id"]}) is not None
        assert store._fetch_one("SELECT COUNT(*) AS count FROM strategy_approval_fact_archive")["count"] == 1
    finally:
        conversations.close()
        store.close()
        reset.close()
        agents.close()
        research.close()


def test_product_workspace_reset_active_job_blocks_before_fencing() -> None:
    suffix = uuid4().hex[:12]
    owner = f"product-reset-job-{suffix}"
    context, _conversation, task_id, _experiment, _artifact = _research_graph(owner, suffix=suffix)
    agents = AgentResearchStore()
    reset = WorkspaceRuntimeResetStore()
    store = WorkspaceResetStore()
    try:
        now = datetime.now(timezone.utc).isoformat()
        store._execute("""INSERT INTO factor_jobs
            (job_id,task_id,workspace_id,owner_principal,experiment_id,trace_id,idempotency_key,
             request_hash,input_manifest_id,request_json,status,attempts,max_attempts,created_at,updated_at)
            VALUES (:job,:task,:workspace,:owner,NULL,:trace,:key,'hash','manifest','{}'::jsonb,
                    'queued',0,3,:now,:now)""",
            {"job": f"active-reset-{suffix}", "task": task_id,
             "workspace": context["workspace_id"], "owner": owner,
             "trace": context["trace_id"], "key": f"active-reset-{suffix}", "now": now})
        with pytest.raises(WorkspaceRuntimeResetConflict, match="factor_jobs"):
            reset.begin_workspace_reset(owner_principal=owner,
                                        workspace_id=context["workspace_id"],
                                        idempotency_key=str(uuid4()))
        assert store._fetch_one("SELECT status FROM workspaces WHERE workspace_id=:id",
                                {"id": context["workspace_id"]})["status"] == "active"
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_id})
    finally:
        store.close()
        reset.close()
        agents.close()


def test_product_workspace_reset_unknown_approval_blocks_before_fencing() -> None:
    suffix = uuid4().hex[:12]
    owner = f"product-reset-unknown-{suffix}"
    context, _conversation, task_id, _experiment, _artifact = _research_graph(owner, suffix=suffix)
    agents = AgentResearchStore()
    reset = WorkspaceRuntimeResetStore()
    try:
        now = datetime.now(timezone.utc).isoformat()
        run_id = f"unknown-reset-{suffix}"
        agents._execute("""INSERT INTO agent_runs
            (run_id,owner_principal,actor_principal,role_id,role_version,trace_id,session_id,
             dsh_run_id,status,authority_status,idempotency_key,request_hash,created_at,updated_at,version,workspace_id)
            VALUES (:run,:owner,:owner,'quant_research','1',:trace,:session,'dsh-reset',
                    'completed','closed',:key,'hash',:now,:now,1,:workspace)""",
            {"run": run_id, "owner": owner, "trace": context["trace_id"],
             "session": context["session_id"], "key": run_id, "now": now,
             "workspace": context["workspace_id"]})
        agents._execute("""INSERT INTO agent_approvals
            (approval_id,run_id,owner_principal,actor_principal,action,reason,status,
             execution_outcome,continuation_status,idempotency_key,request_hash,created_at,updated_at,workspace_id)
            VALUES (:approval,:run,:owner,:owner,'external_action','test','approved',
                    'outcome_unknown','outcome_unknown',:key,'hash',:now,:now,:workspace)""",
            {"approval": f"approval-{suffix}", "run": run_id, "owner": owner,
             "key": run_id, "now": now, "workspace": context["workspace_id"]})
        with pytest.raises(WorkspaceRuntimeResetConflict, match="unknown approval"):
            reset.begin_workspace_reset(owner_principal=owner,
                                        workspace_id=context["workspace_id"],
                                        idempotency_key=str(uuid4()))
        row = agents._fetch_one("SELECT status,reset_id FROM workspaces WHERE workspace_id=:id",
                                {"id": context["workspace_id"]})
        assert row == {"status": "active", "reset_id": None}
        assert agents._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_id})
    finally:
        reset.close()
        agents.close()
