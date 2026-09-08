"""BYQ-owned private domain-call evidence; no model or domain execution queue."""
import json
import uuid

from packages.contracts.domain_call_admission import call_evidence_receipt, request_evidence, validate_call_evidence
from .db import execute, fetch_one


class DomainValidationRejected(ValueError):
    """Only a trusted domain/schema validator may classify a repairable failure."""


DOMAIN_CALL_DDL = [
    """CREATE TABLE IF NOT EXISTS agent_domain_call_evidence (
        owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL, session_id TEXT NOT NULL,
        trace_id TEXT NOT NULL, sequence BIGINT NOT NULL CHECK (sequence > 0),
        root_run_id TEXT NOT NULL REFERENCES agent_runtime_turns(root_run_id),
        generation TEXT NOT NULL, agent_run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
        task_id TEXT NOT NULL, action TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, request_sha256 TEXT NOT NULL, input_sha256 TEXT NOT NULL,
        evidence_json JSONB NOT NULL, receipt_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (owner_principal, workspace_id, session_id, sequence)
    )""",
    """CREATE INDEX IF NOT EXISTS agent_domain_call_request
        ON agent_domain_call_evidence(root_run_id, task_id, action, idempotency_key, request_sha256)""",
    """CREATE TABLE IF NOT EXISTS agent_domain_correction_buckets (
        root_run_id TEXT NOT NULL REFERENCES agent_runtime_turns(root_run_id),
        task_id TEXT NOT NULL, action TEXT NOT NULL,
        owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL,
        failed_input_sha256 TEXT, repair_used BOOLEAN NOT NULL DEFAULT FALSE,
        PRIMARY KEY(root_run_id,task_id,action)
    )""",
    """CREATE TABLE IF NOT EXISTS agent_domain_call_claims (
        claim_id TEXT PRIMARY KEY, root_run_id TEXT NOT NULL, task_id TEXT NOT NULL, action TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, request_sha256 TEXT NOT NULL, input_sha256 TEXT NOT NULL,
        evidence_sequence BIGINT NOT NULL, agent_run_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('claimed','executing','succeeded','correctable_failure')),
        result_json JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(root_run_id,task_id,action,idempotency_key),
        FOREIGN KEY(root_run_id,task_id,action)
            REFERENCES agent_domain_correction_buckets(root_run_id,task_id,action)
    )""",
]


class DomainCallEvidenceMixin:
    def _domain_identity(self, connection, evidence, context, *, active):
        from .agent_research import AgentConflict, AgentUnauthorized, ROLE_BY_ID

        self._require_lifecycle_workspace(connection, context["owner"], context["workspace"])
        self._lifecycle_lock(connection, "root:" + context["root"])
        root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root", context)
        if root is None:
            raise AgentConflict("runtime root binding is not yet confirmed")
        if (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"]) != (
                context["owner"], context["workspace"], context["session"], context["trace"]):
            raise AgentUnauthorized("private call does not match its runtime root")
        run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id=:run FOR SHARE", {"run": evidence["agent_run_id"]})
        if run is None or any(run[field] != expected for field, expected in {
                "owner_principal": context["owner"], "workspace_id": context["workspace"],
                "actor_principal": "byq-product-agent-" + context["session"], "session_id": context["session"],
                "trace_id": context["trace"], "root_run_id": context["root"], "dsh_run_id": evidence["generation"],
        }.items()):
            raise AgentUnauthorized("private call does not match its registered agent")
        role = ROLE_BY_ID.get(run["role_id"])
        if role is None or evidence["action"] not in role.allowed_tools:
            raise AgentUnauthorized("private call action is outside the registered role")
        task = fetch_one(connection, "SELECT * FROM research_tasks WHERE task_id=:task FOR SHARE", {"task": evidence["task_id"]})
        conversation = fetch_one(connection, "SELECT * FROM product_conversations WHERE runtime_session_id=:session FOR SHARE", context)
        if (conversation is None or task is None
                or (task["owner_principal"], task.get("workspace_id"), task.get("conversation_id")) != (
                    context["owner"], context["workspace"], conversation["conversation_id"])
                or (conversation["owner_principal"], conversation["workspace_id"], conversation["trace_id"]) != (
                    context["owner"], context["workspace"], context["trace"])):
            raise AgentUnauthorized("private call does not match the original conversation task")
        if active and (root["status"] != "active" or run["status"] != "active"
                       or task["status"] in {"cancelled", "failed", "completed"} or conversation["status"] != "active"):
            raise AgentConflict("domain call execution authority is no longer active")
        return conversation["conversation_id"]

    def claim_domain_call(self, action, payload, *, trusted_owner, trusted_workspace,
                          trusted_session_id, trusted_trace_id, trusted_generation, trusted_root):
        """Commit the debit before domain validation; proof arrival never executes."""
        from .agent_research import AgentConflict, _principal, _trace
        value = request_evidence(action, payload, trace_id=trusted_trace_id)
        # Reuse the closed proof identity validator, not a model-provided root.
        validate_call_evidence({**value, "schema_version": "domain-call-observed.v1", "sequence": 1,
            "root_run_id": trusted_root, "generation": trusted_generation, "call_id": "request"})
        context = {"owner": _principal(trusted_owner, field="owner_principal"),
            "workspace": _trace(trusted_workspace, field="workspace_id"),
            "session": _trace(trusted_session_id, field="session_id"), "trace": trusted_trace_id, "root": trusted_root}
        scope = {**value, **context}
        with self._transaction() as connection:
            # No proof means no claim and no execution, including when the
            # root/registration delivery itself is still pending. Do not turn
            # that ordering window into an ambiguous domain-write conflict.
            self._require_lifecycle_workspace(connection, context["owner"], context["workspace"])
            self._lifecycle_lock(connection, "root:" + context["root"])
            proof = fetch_one(connection, """SELECT * FROM agent_domain_call_evidence
                WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session AND trace_id=:trace
                AND root_run_id=:root AND task_id=:task_id AND action=:action AND idempotency_key=:idempotency_key
                AND request_sha256=:request_sha256 AND input_sha256=:input_sha256
                AND generation=:generation AND agent_run_id=:agent_run_id ORDER BY sequence LIMIT 1""",
                {**scope, "generation": trusted_generation})
            if proof is None:
                return {"state": "blocked", "reason": "call_evidence_pending"}
            self._domain_identity(connection, {**value, "generation": trusted_generation}, context, active=False)
            # Root lock serializes both correction claims and terminal revocation.
            existing = fetch_one(connection, """SELECT * FROM agent_domain_call_claims
                WHERE root_run_id=:root AND task_id=:task_id AND action=:action AND idempotency_key=:idempotency_key""", scope)
            if existing:
                if existing["request_sha256"] != value["request_sha256"]:
                    raise AgentConflict("domain call idempotency key was reused")
                return {"state": "unknown"} if existing["status"] in {"claimed", "executing"} else existing["result_json"]
            self._domain_identity(connection, {**value, "generation": trusted_generation}, context, active=True)
            execute(connection, """INSERT INTO agent_domain_correction_buckets
                (root_run_id,task_id,action,owner_principal,workspace_id) VALUES (:root,:task_id,:action,:owner,:workspace)
                ON CONFLICT DO NOTHING""", scope)
            bucket = fetch_one(connection, """SELECT * FROM agent_domain_correction_buckets
                WHERE root_run_id=:root AND task_id=:task_id AND action=:action FOR UPDATE""", scope)
            unresolved = fetch_one(connection, """SELECT claim_id FROM agent_domain_call_claims
                WHERE root_run_id=:root AND task_id=:task_id AND action=:action AND status IN ('claimed','executing') LIMIT 1""", scope)
            if unresolved:
                return {"state": "blocked", "reason": "prior_call_outcome_unknown"}
            if bucket["failed_input_sha256"] == value["input_sha256"]:
                return {"state": "blocked", "reason": "unchanged_failed_input"}
            if bucket["repair_used"]:
                return {"state": "blocked", "reason": "correction_budget_exhausted"}
            count = fetch_one(connection, "SELECT count(*) AS n FROM agent_domain_call_claims WHERE root_run_id=:root", scope)
            if count["n"] >= 1024:
                return {"state": "blocked", "reason": "call_retention_bound"}
            if bucket["failed_input_sha256"] is not None:
                execute(connection, """UPDATE agent_domain_correction_buckets SET repair_used=TRUE
                    WHERE root_run_id=:root AND task_id=:task_id AND action=:action""", scope)
            claim_id = uuid.uuid4().hex
            execute(connection, """INSERT INTO agent_domain_call_claims
                (claim_id,root_run_id,task_id,action,idempotency_key,request_sha256,input_sha256,evidence_sequence,agent_run_id,status)
                VALUES (:claim,:root,:task_id,:action,:idempotency_key,:request_sha256,:input_sha256,:sequence,:agent_run_id,'claimed')""",
                {**scope, "claim": claim_id, "sequence": proof["sequence"]})
        # Internal capability, never an HTTP/model-facing result. No raw request
        # is persisted. Caller alone may execute this newly claimed operation.
        return {"state": "claimed", "claim_id": claim_id, "context": context,
                "evidence": proof["evidence_json"]}

    def execute_domain_call(self, claim, operation):
        """Artifact and success receipt share one transaction; crashes stay charged."""
        from .agent_research import AgentConflict
        if claim.get("state") != "claimed":
            return claim
        context, evidence = claim["context"], claim["evidence"]
        with self._transaction() as connection:
            self._domain_identity(connection, evidence, context, active=True)
            row = fetch_one(connection, "SELECT * FROM agent_domain_call_claims WHERE claim_id=:id FOR UPDATE", {"id": claim["claim_id"]})
            if row is None:
                raise AgentConflict("domain call claim is missing")
            if row["status"] != "claimed":
                return {"state": "unknown"} if row["status"] == "executing" else row["result_json"]
            execute(connection, "UPDATE agent_domain_call_claims SET status='executing' WHERE claim_id=:id", {"id": claim["claim_id"]})
        try:
            with self._transaction() as connection:
                self._domain_identity(connection, evidence, context, active=True)
                row = fetch_one(connection, "SELECT * FROM agent_domain_call_claims WHERE claim_id=:id FOR UPDATE", {"id": claim["claim_id"]})
                if row is None or row["status"] != "executing":
                    raise AgentConflict("domain call claim is no longer executable")
                # This is a BYQ validation/artifact transaction, never a model,
                # provider, training job, or general-purpose task callback.
                result = {"state": "succeeded", "result": operation(connection)}
                execute(connection, "UPDATE agent_domain_call_claims SET status='succeeded',result_json=CAST(:result AS jsonb) WHERE claim_id=:id",
                        {"id": claim["claim_id"], "result": json.dumps(result, allow_nan=False)})
            return result
        except DomainValidationRejected:
            # The failed artifact transaction has rolled back. Persist only a
            # closed error; raw Python/schema diagnostics never enter the ledger.
            with self._transaction() as connection:
                self._lifecycle_lock(connection, "root:" + context["root"])
                row = fetch_one(connection, "SELECT * FROM agent_domain_call_claims WHERE claim_id=:id FOR UPDATE", {"id": claim["claim_id"]})
                if row is None or row["status"] != "executing":
                    raise AgentConflict("domain call claim cannot be completed twice")
                bucket = fetch_one(connection, """SELECT repair_used FROM agent_domain_correction_buckets
                    WHERE root_run_id=:root AND task_id=:task AND action=:action""",
                    {"root": row["root_run_id"], "task": row["task_id"], "action": row["action"]})
                result = {"state": "correctable_failure",
                    "reason": "correction_failed" if bucket["repair_used"] else "domain_validation_failed"}
                execute(connection, """UPDATE agent_domain_correction_buckets SET failed_input_sha256=COALESCE(failed_input_sha256,:input)
                    WHERE root_run_id=:root AND task_id=:task AND action=:action""",
                    {"root": row["root_run_id"], "task": row["task_id"], "action": row["action"], "input": row["input_sha256"]})
                execute(connection, "UPDATE agent_domain_call_claims SET status='correctable_failure',result_json=CAST(:result AS jsonb) WHERE claim_id=:id",
                        {"id": claim["claim_id"], "result": json.dumps(result)})
            return result

    def consume_domain_call_evidence(self, value, *, trusted_owner, trusted_workspace,
                                    trusted_session_id, trusted_trace_id, conversation_id):
        from .agent_research import AgentConflict, AgentUnauthorized, ROLE_BY_ID, _principal, _trace

        evidence = validate_call_evidence(value)
        receipt = call_evidence_receipt(evidence)
        context = {"owner": _principal(trusted_owner, field="owner_principal"),
                   "workspace": _trace(trusted_workspace, field="workspace_id"),
                   "session": _trace(trusted_session_id, field="session_id"),
                   "trace": _trace(trusted_trace_id, field="trace_id"),
                   "sequence": evidence["sequence"], "root": evidence["root_run_id"]}
        with self._transaction() as connection:
            # Preserve all original ingestion checks below. Replays also
            # require the same catalog binding; an existing sequence is not
            # authority to accept a different conversation argument.
            if self._domain_identity(connection, evidence, context, active=False) != conversation_id:
                raise AgentUnauthorized("private call does not match the original conversation")
            self._require_lifecycle_workspace(connection, context["owner"], context["workspace"])
            self._lifecycle_lock(connection, "root:" + context["root"])
            self._lifecycle_lock(connection, "domain-call-session:" + context["session"])
            existing = fetch_one(connection, """SELECT * FROM agent_domain_call_evidence
                WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session AND sequence=:sequence""", context)
            if existing:
                if existing["trace_id"] != context["trace"] or existing["evidence_json"] != evidence:
                    raise AgentConflict("private call sequence conflicts with its durable evidence")
                return existing["receipt_json"]
            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root", context)
            if root is None:
                raise AgentConflict("runtime root binding is not yet confirmed")
            if (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"]) != (
                    context["owner"], context["workspace"], context["session"], context["trace"]):
                raise AgentUnauthorized("private call does not match its runtime root")
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id=:run", {"run": evidence["agent_run_id"]})
            if run is None or any(run[field] != expected for field, expected in {
                    "owner_principal": context["owner"], "workspace_id": context["workspace"],
                    "actor_principal": "byq-product-agent-" + context["session"], "session_id": context["session"],
                    "trace_id": context["trace"], "root_run_id": context["root"], "dsh_run_id": evidence["generation"],
            }.items()):
                raise AgentUnauthorized("private call does not match its registered agent")
            role = ROLE_BY_ID.get(run["role_id"])
            if role is None or evidence["action"] not in role.allowed_tools:
                raise AgentUnauthorized("private call action is outside the registered role")
            task = fetch_one(connection, "SELECT * FROM research_tasks WHERE task_id=:task", {"task": evidence["task_id"]})
            if task is None or (task["owner_principal"], task.get("workspace_id"), task.get("conversation_id")) != (
                    context["owner"], context["workspace"], conversation_id):
                raise AgentUnauthorized("private call does not match the original conversation task")
            count = fetch_one(connection, """SELECT count(*) AS count FROM agent_domain_call_evidence
                WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session""", context)
            if count["count"] >= 1024:
                raise AgentConflict("private call evidence retention bound reached")
            execute(connection, """INSERT INTO agent_domain_call_evidence
                (owner_principal,workspace_id,session_id,trace_id,sequence,root_run_id,generation,agent_run_id,
                 task_id,action,idempotency_key,request_sha256,input_sha256,evidence_json,receipt_json)
                VALUES (:owner,:workspace,:session,:trace,:sequence,:root,:generation,:agent_run_id,
                    :task_id,:action,:idempotency_key,:request_sha256,:input_sha256,CAST(:evidence AS jsonb),CAST(:receipt AS jsonb))""",
                {**evidence, **context, "evidence": json.dumps(evidence), "receipt": json.dumps(receipt)})
        return receipt
