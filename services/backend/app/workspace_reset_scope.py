"""Closed personal Product reset scope, not a generic archive registry (ADR-0091)."""
from __future__ import annotations

OWNED = "r.workspace_id=:workspace AND r.owner_principal=:owner"
WORKSPACE = "r.workspace_id=:workspace"
ACCOUNT = "r.owner_principal=:owner"

def child(parent: str, key: str, foreign: str | None = None) -> str:
    return f"EXISTS (SELECT 1 FROM {parent} p WHERE p.{key}=r.{foreign or key} AND p.workspace_id=:workspace)"

# Child-first, explicit ownership; every selected row is archived before deletion.
# Personal configuration is distinct from Workspace-bearing domain records.
RESET_SCOPE = (
    # Retained local-publication rows are historical: archive them only through
    # the normal verified reset after external side effects are classified.
    ("product_feedback_hub_outbox", child("product_feedback", "feedback_id")),
    ("product_feedback_outbox", child("product_feedback", "feedback_id")),
    ("product_feedback_publications", child("product_feedback", "feedback_id")),
    ("product_feedback_revisions", WORKSPACE),
    ("product_feedback_audit", WORKSPACE),
    ("product_feedback_commands", "r.scope_key=:workspace"),
    ("product_feedback", OWNED),
    ("agent_domain_call_claims", child("agent_runtime_turns", "root_run_id")),
    ("agent_domain_call_evidence", OWNED),
    ("agent_domain_correction_buckets", OWNED),
    ("agent_runtime_registrations", child("agent_runtime_turns", "root_run_id")),
    ("agent_runtime_receipts", OWNED),
    ("agent_approvals", OWNED),
    ("agent_audit", OWNED),
    ("agent_runs", OWNED),
    ("agent_runtime_turns", OWNED),
    ("product_conversation_messages", OWNED),
    ("research_receipt_watches", OWNED),
    ("ml_training_submission_keys", OWNED),
    ("ml_training_receipt_watches", OWNED),
    ("data_demands", OWNED),
    ("factor_jobs", OWNED),
    ("signal_producer_jobs", OWNED),
    ("backtest_jobs", OWNED),
    ("optimization_jobs", OWNED),
    ("ml_prediction_runs", OWNED),
    ("ml_training_runs", OWNED),
    ("learning_history", WORKSPACE),
    ("learning_iterations", child("learning_runs", "learning_run_id")),
    ("evaluation_signals", WORKSPACE),
    ("lessons", OWNED),
    ("learning_runs", OWNED),
    ("research_task_actions", OWNED),
    ("research_judgment_stage_calls", child("research_tasks", "task_id")),
    ("research_execution_plan_receipts", child("research_tasks", "task_id")),
    ("research_execution_plans", OWNED),
    ("artifact_submission_receipts", child("research_tasks", "task_id")),
    ("research_transitions", WORKSPACE),
    ("artifacts", OWNED),
    ("experiments", OWNED),
    ("research_tasks", OWNED),
    ("product_conversations", OWNED),
    ("paper_fills", child("paper_accounts", "account_id")),
    ("paper_orders", child("paper_accounts", "account_id")),
    ("paper_positions", child("paper_accounts", "account_id")),
    ("paper_account_controls", child("paper_accounts", "account_id")),
    ("paper_ledger_entries", child("paper_accounts", "account_id")),
    ("paper_account_snapshots", child("paper_accounts", "account_id")),
    ("paper_account_audit", OWNED),
    ("paper_transfer_audit", OWNED),
    ("paper_accounts", OWNED),
    ("stock_pool_materialization_runs", OWNED),
    ("stock_pool_producer_idempotency", OWNED),
    ("stock_pool_producer_definitions", OWNED),
    ("stock_pool_snapshot_members", WORKSPACE),
    ("stock_pool_lifecycle_audit", OWNED),
    ("stock_pool_write_idempotency", OWNED),
    ("stock_pool_domain_references", OWNED),
    ("stock_pool_snapshots", WORKSPACE),
    ("stock_pools", OWNED),
    ("agent_model_bindings", ACCOUNT),
    ("model_command_receipts", ACCOUNT),
    ("model_profile_status_receipts", ACCOUNT),
    ("model_profiles", ACCOUNT),
    ("credential_discovered_models", "EXISTS (SELECT 1 FROM credentials p WHERE p.credential_id=r.credential_id AND p.scope='user' AND p.owner_principal=:owner)"),
    ("credential_audit", "r.scope='user' AND r.owner_principal=:owner"),
    ("credentials", "r.scope='user' AND r.owner_principal=:owner"),
    ("user_policy_command_receipts", ACCOUNT),
    ("user_agent_policy_audit", ACCOUNT),
    ("user_agent_policy_rules", ACCOUNT),
    ("user_agent_policy", ACCOUNT),
    ("user_ui_preferences", "r.user_id=:user_id"),
)
SCOPE_BY_TABLE = dict(RESET_SCOPE)

# Only command keys, never names, owner-only singleton PKs or personal content.
# Hashes survive payload expiry to reject accidental replay of deleted commands.
RETIRED_KEY_FIELDS = {
    "product_feedback_commands": ("scope_key", "actor_principal", "operation", "idempotency_key"),
    "research_tasks": ("owner_principal", "idempotency_key"),
    "experiments": ("task_id", "idempotency_key"),
    "artifact_submission_receipts": ("task_id", "idempotency_key"),
    "research_execution_plan_receipts": ("task_id", "idempotency_key"),
    "research_judgment_stage_calls": ("task_id", "call_identity"),
    "research_task_actions": ("task_id", "action_id"),
    "agent_runs": ("owner_principal", "idempotency_key"),
    "agent_approvals": ("run_id", "idempotency_key"),
    "data_demands": ("owner_principal", "idempotency_key"),
    "factor_jobs": ("workspace_id", "idempotency_key"),
    "signal_producer_jobs": ("owner_principal", "idempotency_key"),
    "backtest_jobs": ("owner_principal", "idempotency_key"),
    "optimization_jobs": ("workspace_id", "idempotency_key"),
    "ml_training_runs": ("workspace_id", "idempotency_key"),
    "ml_prediction_runs": ("workspace_id", "idempotency_key"),
    "ml_training_submission_keys": ("workspace_id", "owner_principal", "idempotency_key"),
    "ml_training_receipt_watches": ("workspace_id", "owner_principal", "idempotency_key"),
    "learning_runs": ("owner_principal", "idempotency_key"),
    "learning_iterations": ("learning_run_id", "idempotency_key"),
    "lessons": ("task_id", "idempotency_key"),
    "evaluation_signals": ("task_id", "idempotency_key"),
    "stock_pool_write_idempotency": ("owner_principal", "idempotency_key"),
    "stock_pool_producer_idempotency": ("workspace_id", "owner_principal", "idempotency_key"),
    "stock_pool_lifecycle_audit": ("owner_principal", "idempotency_key"),
    "paper_account_audit": ("owner_principal", "idempotency_key"),
    "paper_orders": ("account_id", "idempotency_key"),
    "paper_account_snapshots": ("account_id", "idempotency_key"),
    "credentials": ("scope", "owner_principal", "idempotency_key"),
    "user_policy_command_receipts": ("owner_principal", "request_id"),
}

ARCHIVE_DDL = [
    """CREATE TABLE IF NOT EXISTS workspace_reset_archives (
      reset_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, owner_principal TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
      payload_json JSONB NOT NULL, payload_sha256 TEXT NOT NULL,
      counts_json JSONB NOT NULL, object_references_json JSONB NOT NULL,
      CHECK(expires_at = created_at + interval '7 days'),
      CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'))""",
    "CREATE INDEX IF NOT EXISTS workspace_reset_archives_expiry ON workspace_reset_archives(expires_at)",
    """CREATE TABLE IF NOT EXISTS workspace_reset_retired_keys (
      source_table TEXT NOT NULL, identity_sha256 TEXT NOT NULL,
      reset_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
      PRIMARY KEY(source_table,identity_sha256))""",
    """CREATE TABLE IF NOT EXISTS workspace_reset_expired_objects (
      namespace TEXT NOT NULL, object_id TEXT NOT NULL, reference_json JSONB NOT NULL,
      PRIMARY KEY(namespace,object_id))""",
    """CREATE OR REPLACE FUNCTION byq_reset_archive_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' AND OLD.expires_at <= clock_timestamp() THEN RETURN OLD; END IF;
      RAISE EXCEPTION 'reset archive is immutable until its expiry';
    END $$""",
    "DROP TRIGGER IF EXISTS workspace_reset_archive_immutable ON workspace_reset_archives",
    """CREATE TRIGGER workspace_reset_archive_immutable BEFORE UPDATE OR DELETE ON workspace_reset_archives
       FOR EACH ROW EXECUTE FUNCTION byq_reset_archive_immutable()""",
]

ARCHIVE_DDL.extend([
    """CREATE OR REPLACE FUNCTION byq_reset_reject_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
       BEGIN RAISE EXCEPTION 'reset archive truncation is forbidden'; END $$""",
    "DROP TRIGGER IF EXISTS workspace_reset_archive_no_truncate ON workspace_reset_archives",
    """CREATE TRIGGER workspace_reset_archive_no_truncate BEFORE TRUNCATE ON workspace_reset_archives
       FOR EACH STATEMENT EXECUTE FUNCTION byq_reset_reject_truncate()""",
])

ARCHIVE_DDL.extend([
    """CREATE OR REPLACE FUNCTION byq_reset_proof_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
       BEGIN RAISE EXCEPTION 'reset idempotency proof is immutable'; END $$""",
    *[statement for table in ('workspace_reset_retired_keys',) for statement in (
        f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}",
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION byq_reset_proof_immutable()")],
])

# Parent relationships not carrying direct owner/workspace columns.
FENCE_PARENTS = {
    "product_feedback_publications": ("product_feedback", "feedback_id", "feedback_id"),
    "product_feedback_outbox": ("product_feedback", "feedback_id", "feedback_id"),
    "product_feedback_hub_outbox": ("product_feedback", "feedback_id", "feedback_id"),
    "agent_runtime_registrations": ("agent_runtime_turns", "root_run_id", "root_run_id"),
    "agent_domain_call_claims": ("agent_runtime_turns", "root_run_id", "root_run_id"),
    "research_judgment_stage_calls": ("research_tasks", "task_id", "task_id"),
    "artifact_submission_receipts": ("research_tasks", "task_id", "task_id"),
    "research_execution_plan_receipts": ("research_tasks", "task_id", "task_id"),
    "learning_iterations": ("learning_runs", "learning_run_id", "learning_run_id"),
    "credential_discovered_models": ("credentials", "credential_id", "credential_id"),
}
FENCE_PARENTS.update({
    "product_conversation_messages": ("product_conversations","conversation_id","conversation_id"),
    "experiments": ("research_tasks","task_id","task_id"),
    "artifacts": ("research_tasks","task_id","task_id"),
    "research_execution_plans": ("research_tasks","task_id","task_id"),
    "agent_audit": ("agent_runs","run_id","run_id"),
    "agent_approvals": ("agent_runs","run_id","run_id"),
    "stock_pool_snapshots": ("stock_pools","pool_id","pool_id"),
    "stock_pool_snapshot_members": ("stock_pool_snapshots","snapshot_id","snapshot_id"),
    **{t:("paper_accounts","account_id","account_id") for t in (
        "paper_positions","paper_orders","paper_fills","paper_account_controls",
        "paper_ledger_entries","paper_account_snapshots","paper_account_audit","paper_transfer_audit")},
    "evaluation_signals": ("research_tasks","task_id","task_id"),
    "lessons": ("research_tasks","task_id","task_id"),
})



def install_reset_guards(connection) -> None:
    """Extend existing tenant triggers to account writers and reset-only key guards."""
    from sqlalchemy import text
    connection.execute(text("""CREATE OR REPLACE FUNCTION byq_personal_reset_fence()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE row_value JSONB; owner_name TEXT; workspace_key TEXT; workspace_row RECORD;
            parent_value JSONB; identity_value JSONB; field_name TEXT; default_clear BOOLEAN := FALSE;
    BEGIN
      row_value := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
      IF TG_TABLE_NAME='users' THEN
        IF TG_OP <> 'UPDATE' OR (NEW.preferences,NEW.default_prompt) IS NOT DISTINCT FROM
           (OLD.preferences,OLD.default_prompt) THEN RETURN NEW; END IF;
        owner_name := row_value->>'username';
      ELSIF TG_TABLE_NAME IN ('credentials','credential_audit') AND row_value->>'scope' <> 'user' THEN
        RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
      ELSIF TG_TABLE_NAME IN ('research_transitions','learning_history') THEN
        IF row_value->>'entity_type'='research_task' THEN
          SELECT workspace_id INTO workspace_key FROM research_tasks WHERE task_id=row_value->>'entity_id';
        ELSIF row_value->>'entity_type'='experiment' THEN
          SELECT workspace_id INTO workspace_key FROM experiments WHERE experiment_id=row_value->>'entity_id';
        ELSIF row_value->>'entity_type'='artifact' THEN
          SELECT workspace_id INTO workspace_key FROM artifacts WHERE artifact_id=row_value->>'entity_id';
        ELSIF row_value->>'entity_type'='learning_run' THEN
          SELECT workspace_id INTO workspace_key FROM learning_runs WHERE learning_run_id=row_value->>'entity_id';
        ELSIF row_value->>'entity_type'='lesson' THEN
          SELECT workspace_id INTO workspace_key FROM lessons WHERE lesson_id=row_value->>'entity_id';
        END IF;
        IF workspace_key IS NULL THEN RAISE EXCEPTION 'reset fence entity missing'; END IF;
      ELSIF TG_ARGV[0]='parent' THEN
        EXECUTE format('SELECT to_jsonb(p) FROM %I p WHERE %I=$1',TG_ARGV[1],TG_ARGV[2])
          INTO parent_value USING row_value->>TG_ARGV[3];
        IF parent_value IS NULL THEN RAISE EXCEPTION 'reset fence parent missing'; END IF;
        IF TG_TABLE_NAME='credential_discovered_models' AND parent_value->>'scope' <> 'user' THEN
          RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END IF;
        owner_name := parent_value->>'owner_principal'; workspace_key := parent_value->>'workspace_id';
      ELSIF TG_TABLE_NAME='user_ui_preferences' THEN
        SELECT username INTO owner_name FROM users WHERE user_id=row_value->>'user_id';
      ELSIF TG_TABLE_NAME='product_feedback_commands' THEN
        workspace_key := row_value->>'scope_key';
        IF workspace_key='platform-feedback' THEN RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END; END IF;
      ELSE
        owner_name := row_value->>'owner_principal'; workspace_key := row_value->>'workspace_id';
      END IF;
      SELECT w.*, u.status AS owner_status, m.status AS membership_status
        INTO workspace_row FROM workspaces w JOIN users u ON u.user_id=w.owner_user_id
        JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
        WHERE (owner_name IS NULL OR u.username=owner_name)
          AND (workspace_key IS NULL OR w.workspace_id=workspace_key)
          AND (owner_name IS NOT NULL OR workspace_key IS NOT NULL)
          AND w.kind='personal' AND m.role='owner'
        FOR SHARE OF w, u, m;
      IF workspace_row.workspace_id IS NULL THEN RAISE EXCEPTION 'reset fence owner mismatch'; END IF;
      IF workspace_row.owner_status <> 'active' OR workspace_row.membership_status <> 'active'
        OR workspace_row.status <> 'active' THEN
        -- A disabled identity has no business authority. Its trusted consumer
        -- may still persist exact terminal facts for an already-bound root.
        -- Pending Reset uses its separate recorded release-proof path below.
        IF workspace_row.reset_id IS NULL THEN
          IF TG_TABLE_NAME='agent_runtime_turns' AND TG_OP='UPDATE' THEN
            IF OLD.status='active' AND OLD.authority_status='active'
              AND NEW.status IN ('completed','failed','cancelled','interrupted')
              AND NEW.authority_status='closed' AND NEW.terminal_sequence > 0
              AND NEW.terminal_event_sha256 ~ '^[0-9a-f]{64}$'
              AND (to_jsonb(NEW)-ARRAY['status','authority_status','updated_at','terminal_sequence','terminal_event_sha256'])=
                  (to_jsonb(OLD)-ARRAY['status','authority_status','updated_at','terminal_sequence','terminal_event_sha256'])
              AND EXISTS (SELECT 1 FROM product_conversations c
                WHERE c.owner_principal=OLD.owner_principal AND c.workspace_id=OLD.workspace_id
                  AND c.runtime_session_id=OLD.session_id AND c.trace_id=OLD.trace_id) THEN RETURN NEW; END IF;
          END IF;
          -- The existing tenancy triggers additionally require immutable run
          -- fields, version+1, the matching closed root, and exact audit detail.
          IF TG_TABLE_NAME='agent_runs' AND TG_OP='UPDATE' THEN
            IF OLD.status IN ('active','pending_binding') AND OLD.authority_status='active'
              AND NEW.status IN ('completed','failed','cancelled','interrupted')
              AND NEW.authority_status='closed' AND NEW.version=OLD.version+1
              AND EXISTS (SELECT 1 FROM agent_runtime_turns r
                WHERE r.root_run_id=OLD.root_run_id AND r.owner_principal=OLD.owner_principal
                  AND r.workspace_id=OLD.workspace_id AND r.session_id=OLD.session_id
                  AND r.trace_id=OLD.trace_id AND r.status=NEW.status
                  AND r.authority_status='closed' AND r.terminal_sequence IS NOT NULL
                  AND r.terminal_event_sha256 ~ '^[0-9a-f]{64}$') THEN RETURN NEW; END IF;
          END IF;
          IF TG_TABLE_NAME='agent_audit' AND TG_OP='INSERT' THEN
            IF NEW.action='runtime_turn_binding' AND NEW.resource_type='runtime_turn'
              AND NEW.outcome IN ('completed','failed','cancelled','interrupted')
              AND EXISTS (SELECT 1 FROM agent_runs a JOIN agent_runtime_turns r ON r.root_run_id=a.root_run_id
                WHERE a.run_id=NEW.run_id AND a.owner_principal=NEW.owner_principal
                  AND a.actor_principal=NEW.actor_principal AND a.workspace_id=workspace_row.workspace_id
                  AND (NEW.workspace_id IS NULL OR NEW.workspace_id=a.workspace_id)
                  AND r.owner_principal=a.owner_principal AND r.workspace_id=a.workspace_id
                  AND r.session_id=a.session_id AND r.trace_id=a.trace_id
                  AND a.status=NEW.outcome AND r.status=a.status
                  AND a.authority_status='closed' AND r.authority_status='closed'
                  AND r.terminal_sequence IS NOT NULL AND r.terminal_event_sha256 ~ '^[0-9a-f]{64}$'
                  AND NEW.resource_id=r.root_run_id AND NEW.detail_json=jsonb_build_object(
                    'root_run_id',r.root_run_id,'terminal_sequence',r.terminal_sequence)) THEN RETURN NEW; END IF;
          END IF;
          IF TG_TABLE_NAME='agent_runtime_receipts' AND TG_OP='INSERT' THEN
            IF EXISTS (SELECT 1 FROM agent_runtime_turns r
              JOIN product_conversations c ON c.runtime_session_id=r.session_id
                AND c.owner_principal=r.owner_principal AND c.workspace_id=r.workspace_id AND c.trace_id=r.trace_id
              WHERE r.owner_principal=NEW.owner_principal AND r.workspace_id=NEW.workspace_id
                AND r.session_id=NEW.session_id AND r.trace_id=NEW.trace_id
                AND r.status IN ('completed','failed','cancelled','interrupted') AND r.authority_status='closed'
                AND r.terminal_sequence=NEW.sequence AND r.terminal_event_sha256 ~ '^[0-9a-f]{64}$'
                AND NEW.receipt_json=jsonb_build_object('schema_version','agent-run-lifecycle-receipt.v1',
                  'root_run_id',r.root_run_id,'sequence',r.terminal_sequence,'event_sha256',r.terminal_event_sha256)) THEN RETURN NEW; END IF;
          END IF;
        END IF;
        IF workspace_row.owner_status <> 'active' OR workspace_row.membership_status <> 'active' THEN
          RAISE EXCEPTION 'reset fence owner is inactive';
        END IF;
      END IF;
      IF TG_TABLE_NAME='users' AND TG_OP='UPDATE' THEN
        default_clear := NEW.preferences IS NULL AND NEW.default_prompt IS NULL;
      END IF;
      IF workspace_row.status <> 'active' THEN
        -- Exact reset transaction only, limited to deleting classified history
        -- and clearing the two profile defaults. No Agent/domain write bypass.
        IF workspace_row.reset_kind='workspace' AND workspace_row.reset_id IS NOT NULL
          AND current_setting('byq.personal_reset_id',true)=workspace_row.reset_id
          AND (TG_OP='DELETE' OR default_clear) THEN
          RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END IF;
        -- Existing authority/conversation triggers validate exact terminal proof.
        IF TG_TABLE_NAME IN ('agent_runs','product_conversations') AND TG_OP='UPDATE' THEN RETURN NEW; END IF;
        IF TG_TABLE_NAME='agent_runtime_turns' AND TG_OP='UPDATE' THEN
          IF OLD.status='active' AND OLD.authority_status='authority_revoked_unconfirmed'
            AND NEW.status='interrupted' AND NEW.authority_status='closed'
            AND NEW.terminal_sequence IS NULL AND NEW.terminal_event_sha256 IS NULL
            AND (to_jsonb(NEW)-ARRAY['status','authority_status','updated_at','terminal_sequence','terminal_event_sha256'])=
                (to_jsonb(OLD)-ARRAY['status','authority_status','updated_at','terminal_sequence','terminal_event_sha256'])
            AND EXISTS (SELECT 1 FROM jsonb_array_elements(workspace_row.reset_sessions_json) value
              WHERE value->>'session_id'=NEW.session_id AND value->>'trace_id'=NEW.trace_id) THEN RETURN NEW; END IF;
        END IF;
        IF TG_TABLE_NAME='agent_audit' AND TG_OP='INSERT' THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'personal workspace is disabled for reset';
      END IF;
      IF row_value ? 'workspace_id' AND row_value->>'workspace_id' IS NULL THEN
        row_value := row_value || jsonb_build_object('workspace_id',workspace_row.workspace_id);
      END IF;
      IF TG_OP='INSERT' AND TG_ARGV[4] <> '' THEN
        identity_value := '{}'::jsonb;
        FOREACH field_name IN ARRAY string_to_array(TG_ARGV[4],',') LOOP
          IF row_value->field_name IS NULL OR row_value->field_name='null'::jsonb THEN
            identity_value := NULL; EXIT;
          END IF;
          identity_value := identity_value || jsonb_build_object(field_name,row_value->field_name);
        END LOOP;
        IF identity_value IS NOT NULL AND EXISTS (SELECT 1 FROM workspace_reset_retired_keys
          WHERE source_table=TG_TABLE_NAME
            AND identity_sha256=encode(sha256(convert_to(identity_value::text,'UTF8')),'hex')) THEN
          RAISE EXCEPTION 'idempotency identity retired by personal reset; use a new request key';
        END IF;
      END IF;
      RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
    END $$"""))
    for table in (*SCOPE_BY_TABLE, 'users'):
        if connection.execute(text('SELECT to_regclass(:name)'), {'name':table}).scalar_one() is None:
            continue
        mode='direct'; parent=('', '', '')
        if table in FENCE_PARENTS:
            mode='parent'; parent=FENCE_PARENTS[table]
        args=(mode,*parent,','.join(RETIRED_KEY_FIELDS.get(table,())))
        quoted=','.join("'"+arg+"'" for arg in args)
        connection.execute(text(f'DROP TRIGGER IF EXISTS {table}_personal_reset_fence ON {table}'))
        operations='UPDATE' if table=='users' else 'INSERT OR UPDATE OR DELETE'
        connection.execute(text(f'''CREATE TRIGGER {table}_personal_reset_fence BEFORE {operations}
          ON {table} FOR EACH ROW EXECUTE FUNCTION byq_personal_reset_fence({quoted})'''))
