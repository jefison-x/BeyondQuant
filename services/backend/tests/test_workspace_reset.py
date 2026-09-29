"""Isolated PostgreSQL coverage for the narrow workspace reset contract."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.agent_research import AgentResearchStore
from app.conversation_catalog import ConversationCatalogStore
from app.research import ResearchStore
from app.workspace_reset import WorkspaceResetBlocked, WorkspaceResetStore
from app.workspace_runtime_reset import WorkspaceRuntimeResetConflict, WorkspaceRuntimeResetStore
from tests.workspace_helpers import trusted_agent_context
from tests.test_research import snapshot

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


def test_product_workspace_reset_requires_release_proof_is_scoped_and_idempotent() -> None:
    suffix = uuid4().hex[:12]
    owner_a = f"product-reset-a-{suffix}"
    owner_b = f"product-reset-b-{suffix}"
    context_a, conversation_a, task_a, _experiment_a, artifact_a = _research_graph(owner_a, suffix=suffix + "a")
    context_b, conversation_b, task_b, _experiment_b, _artifact_b = _research_graph(owner_b, suffix=suffix + "b")
    agents = AgentResearchStore()
    reset = WorkspaceRuntimeResetStore()
    store = WorkspaceResetStore()
    conversations = ConversationCatalogStore()
    try:
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

        with pytest.raises(WorkspaceRuntimeResetConflict, match="release proof"):
            reset.finalize_workspace_reset(
                owner_principal=owner_a, workspace_id=context_a["workspace_id"],
                reset_id=begin["reset_id"], idempotency_key=request_key, released_sessions=[],
            )
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a})
        assert store._fetch_one("SELECT status FROM workspaces WHERE workspace_id=:id",
                                {"id": context_a["workspace_id"]})["status"] == "disabled"

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
        assert store._fetch_one("SELECT status FROM workspaces WHERE workspace_id=:id",
                                {"id": context_a["workspace_id"]})["status"] == "active"
        assert agents._fetch_one(
            "SELECT status,authority_status FROM agent_runtime_turns WHERE root_run_id=:id",
            {"id": root_id}) == {"status": "interrupted", "authority_status": "closed"}
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_a}) is None
        assert store._fetch_one("SELECT job_id FROM factor_jobs WHERE job_id=:id",
                                {"id": completed_job_id}) is None
        assert store._fetch_one("SELECT task_id FROM research_tasks WHERE task_id=:id", {"id": task_b}) is not None
        assert conversations._fetch_one(
            "SELECT conversation_id FROM product_conversations WHERE conversation_id=:id",
            {"id": conversation_b}) is not None

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
    finally:
        conversations.close()
        store.close()
        reset.close()
        agents.close()


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
