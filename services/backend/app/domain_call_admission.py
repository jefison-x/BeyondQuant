"""BYQ-owned private domain-call evidence; no model or domain execution queue."""
import json
import hashlib
import math
import re
import uuid

from packages.contracts.domain_call_admission import call_evidence_receipt, request_evidence, validate_call_evidence
from .db import execute, fetch_one


_ACP_SESSION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ACP_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_ACP_ROOT_ID = re.compile(r"^[0-9a-f]{32}$")
_ACP_TOOL_NAME = re.compile(r"^byq_[a-z0-9_]{1,96}$")
_ACP_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def acp_binding_sha256(value: dict) -> str:
    """Hash only the bounded identity fields; never include tool arguments or secrets."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                     allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _acp_session_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _ACP_SESSION_ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase UUIDv4 session id")
    return value


def _acp_binding_fields(identity: dict, scope: dict, *, agent_run_id: str, parent_run_id: str | None) -> dict:
    return {
        "root_run_id": identity["root_run_id"],
        "runtime_boot_id": identity["runtime_boot_id"],
        "native_root_session_id": identity["native_root_session_id"],
        "native_agent_session_id": identity["native_agent_session_id"],
        "native_parent_session_id": identity["native_parent_session_id"],
        "origin": identity["origin"],
        "depth": identity["depth"],
        "agent_run_id": agent_run_id,
        "parent_run_id": parent_run_id,
        "owner_principal": scope["owner"],
        "workspace_id": scope["workspace"],
        "actor_principal": scope["actor"],
        "session_id": scope["session"],
        "trace_id": scope["trace"],
        "dsh_run_id": scope["generation"],
    }


def _canonical_acp_arguments(arguments: object) -> tuple[str, int]:
    """Return a bounded canonical JSON digest without retaining caller arguments."""
    if not isinstance(arguments, dict):
        raise ValueError("ACP tool arguments must be a JSON object")

    nodes = 0

    def validate(value: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 20_000 or depth > 32:
            raise ValueError("ACP tool arguments exceed the bounded JSON shape")
        if value is None or type(value) in {str, bool, int}:
            return
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("ACP tool arguments must contain finite JSON numbers")
            return
        if isinstance(value, list):
            for child in value:
                validate(child, depth + 1)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("ACP tool argument object keys must be strings")
                validate(child, depth + 1)
            return
        raise ValueError("ACP tool arguments must contain only JSON values")

    validate(arguments, 0)
    try:
        encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("ACP tool arguments are not canonical JSON") from error
    if len(encoded) > 32 * 1024 * 1024:
        raise ValueError("ACP tool arguments exceed the bounded JSON size")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


class DomainValidationRejected(ValueError):
    """Only a trusted domain/schema validator may classify a repairable failure."""

    def __init__(self, message, *, validation_error=None):
        from .factor_research import FactorValidationError
        from .ml_validation import MLValidationError
        from .strategy_artifact import StrategyValidationError
        super().__init__(message)
        # Never accept an arbitrary diagnostic dict or serialize exception text.
        self.validation = (MLValidationError("", field=validation_error.field,
            code=validation_error.code).public_problem()
            if isinstance(validation_error, MLValidationError) else None)
        if isinstance(validation_error, FactorValidationError):
            self.validation = FactorValidationError("", field=validation_error.field,
                code=validation_error.code).public_problem()
        if isinstance(validation_error, StrategyValidationError):
            self.validation = StrategyValidationError("", field=validation_error.field,
                code=validation_error.code).public_problem()


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
    """CREATE TABLE IF NOT EXISTS agent_acp_native_agent_registrations (
        root_run_id TEXT NOT NULL REFERENCES agent_runtime_turns(root_run_id),
        native_agent_session_id TEXT NOT NULL,
        native_root_session_id TEXT NOT NULL,
        native_parent_session_id TEXT,
        owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL,
        actor_principal TEXT NOT NULL, session_id TEXT NOT NULL, trace_id TEXT NOT NULL,
        dsh_run_id TEXT NOT NULL, runtime_boot_id TEXT NOT NULL,
        origin TEXT NOT NULL CHECK(origin IN ('root','subagent')),
        depth SMALLINT NOT NULL CHECK(depth IN (0,1)),
        agent_run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
        parent_run_id TEXT REFERENCES agent_runs(run_id),
        status TEXT NOT NULL CHECK(status IN ('pending','bound')),
        receipt_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(root_run_id,native_agent_session_id),
        UNIQUE(root_run_id,agent_run_id),
        CHECK ((origin='root' AND depth=0 AND native_parent_session_id IS NULL AND parent_run_id IS NULL)
            OR (origin='subagent' AND depth=1 AND native_parent_session_id IS NOT NULL AND parent_run_id IS NOT NULL))
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS agent_acp_one_native_root
        ON agent_acp_native_agent_registrations(root_run_id) WHERE origin='root'""",
    """CREATE INDEX IF NOT EXISTS agent_acp_registrations_run
        ON agent_acp_native_agent_registrations(agent_run_id,status)""",
    """CREATE TABLE IF NOT EXISTS agent_acp_domain_call_observations (
        mcp_request_id TEXT PRIMARY KEY CHECK(mcp_request_id ~ '^[0-9a-f]{32}$'),
        owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL,
        actor_principal TEXT NOT NULL, session_id TEXT NOT NULL, trace_id TEXT NOT NULL,
        dsh_run_id TEXT NOT NULL, runtime_boot_id TEXT NOT NULL,
        root_run_id TEXT NOT NULL REFERENCES agent_runtime_turns(root_run_id),
        native_agent_session_id TEXT NOT NULL,
        sequence BIGINT NOT NULL CHECK(sequence > 0), evidence_sequence BIGINT NOT NULL CHECK(evidence_sequence > 0),
        agent_run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
        task_id TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL,
        request_sha256 TEXT NOT NULL, input_sha256 TEXT NOT NULL,
        event_sha256 TEXT NOT NULL, receipt_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(root_run_id,sequence),
        UNIQUE(owner_principal,workspace_id,session_id,evidence_sequence),
        FOREIGN KEY(owner_principal,workspace_id,session_id,evidence_sequence)
            REFERENCES agent_domain_call_evidence(owner_principal,workspace_id,session_id,sequence)
    )""",
    """CREATE INDEX IF NOT EXISTS agent_acp_observations_root_cursor
        ON agent_acp_domain_call_observations(root_run_id,sequence)""",
    """CREATE TABLE IF NOT EXISTS agent_acp_tool_ingress_observations (
        mcp_request_id TEXT PRIMARY KEY CHECK(mcp_request_id ~ '^[0-9a-f]{32}$'),
        owner_principal TEXT NOT NULL, workspace_id TEXT NOT NULL,
        actor_principal TEXT NOT NULL, session_id TEXT NOT NULL, trace_id TEXT NOT NULL,
        dsh_run_id TEXT NOT NULL, runtime_boot_id TEXT NOT NULL,
        root_run_id TEXT NOT NULL REFERENCES agent_runtime_turns(root_run_id),
        native_root_session_id TEXT NOT NULL, native_agent_session_id TEXT NOT NULL,
        native_parent_session_id TEXT,
        origin TEXT NOT NULL CHECK(origin IN ('root','subagent')),
        depth SMALLINT NOT NULL CHECK(depth IN (0,1)),
        agent_run_id TEXT REFERENCES agent_runs(run_id),
        tool_name TEXT NOT NULL, arguments_sha256 TEXT NOT NULL,
        sequence BIGINT NOT NULL CHECK(sequence > 0), event_sha256 TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','settled','unknown')),
        settlement_json JSONB, settled_at TIMESTAMPTZ,
        receipt_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(root_run_id,sequence)
    )""",
    "ALTER TABLE agent_acp_tool_ingress_observations ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'",
    "ALTER TABLE agent_acp_tool_ingress_observations ADD COLUMN IF NOT EXISTS settlement_json JSONB",
    "ALTER TABLE agent_acp_tool_ingress_observations ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ",
    """CREATE INDEX IF NOT EXISTS agent_acp_tool_ingress_root_cursor
        ON agent_acp_tool_ingress_observations(root_run_id,sequence)""",
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
    def _require_acp_root_terminal_safe(self, connection, root_run_id: str) -> None:
        """Reject terminal ACK while ACP bind, tool dispatch, or domain claim is unresolved."""
        from .agent_research import AgentConflict

        pending_registration = fetch_one(connection, """SELECT count(*) AS count
            FROM agent_acp_native_agent_registrations
            WHERE root_run_id=:root AND status='pending'""", {"root": root_run_id})
        if pending_registration["count"]:
            raise AgentConflict("pending ACP native registration prevents root close")

        unsettled_ingress = fetch_one(connection, """SELECT count(*) AS count
            FROM agent_acp_tool_ingress_observations
            WHERE root_run_id=:root AND status IN ('pending','unknown')""", {"root": root_run_id})
        if unsettled_ingress["count"]:
            raise AgentConflict("pending or unknown ACP tool ingress prevents root close")

        acp_marker = fetch_one(connection, """SELECT
            (SELECT count(*) FROM agent_acp_native_agent_registrations WHERE root_run_id=:root)
            + (SELECT count(*) FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root)
            + (SELECT count(*) FROM agent_acp_domain_call_observations WHERE root_run_id=:root)
            AS count""", {"root": root_run_id})
        if acp_marker["count"]:
            unresolved_claims = fetch_one(connection, """SELECT count(*) AS count
                FROM agent_domain_call_claims
                WHERE root_run_id=:root AND status IN ('claimed','executing')""", {"root": root_run_id})
            if unresolved_claims["count"]:
                raise AgentConflict("unresolved ACP domain call claim prevents root close")

    def _require_current_acp_boot(self, connection, boot_id: str):
        from .agent_research import AgentConflict, AgentUnauthorized

        try:
            return self._require_current_runtime_boot(connection, boot_id, required=True)
        except AgentUnauthorized as error:
            raise AgentConflict("ACP runtime boot is no longer current Backend authority") from error

    def _acp_tool_ingress_agent_run(self, connection, identity: dict, scope: dict,
                                    tool_name: str, *, bootstrap: bool) -> str | None:
        """Resolve the exact bound AgentRun admission shared by observe and abort."""
        from .agent_research import AgentConflict, AgentForbidden, ROLE_BY_ID

        if identity["origin"] == "subagent":
            if identity["native_parent_session_id"] != identity["native_root_session_id"]:
                raise AgentConflict("Product ACP child must have its exact root native parent")
            parent = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
                WHERE root_run_id=:root AND native_agent_session_id=:parent FOR SHARE""",
                {"root": identity["root_run_id"], "parent": identity["native_parent_session_id"]})
            if (parent is None or parent["status"] != "bound" or parent["origin"] != "root"
                    or parent["depth"] != 0
                    or parent["native_agent_session_id"] != parent["native_root_session_id"]
                    or parent["runtime_boot_id"] != identity["runtime_boot_id"]
                    or parent["native_root_session_id"] != identity["native_root_session_id"]
                    or any(parent.get(key) != value for key, value in {
                        "owner_principal": scope["owner"], "workspace_id": scope["workspace"],
                        "actor_principal": scope["actor"], "session_id": scope["session"],
                        "trace_id": scope["trace"], "dsh_run_id": scope["generation"]}.items())):
                raise AgentConflict("ACP tool ingress child has no exact bound root native parent")
            parent_run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id=:run FOR SHARE",
                                   {"run": parent["agent_run_id"]})
            if (parent_run is None or parent_run["status"] != "active"
                    or parent_run.get("authority_status", "active") != "active"
                    or parent_run.get("authority_boot_id") != identity["runtime_boot_id"]):
                raise AgentConflict("ACP tool ingress child parent AgentRun is no longer active")

        binding = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
            WHERE root_run_id=:root AND native_agent_session_id=:native_agent FOR SHARE""",
            {"root": identity["root_run_id"], "native_agent": identity["native_agent_session_id"]})
        if binding is not None:
            expected_binding = {"native_root_session_id": identity["native_root_session_id"],
                "native_parent_session_id": identity["native_parent_session_id"],
                "origin": identity["origin"], "depth": identity["depth"],
                "runtime_boot_id": identity["runtime_boot_id"],
                "owner_principal": scope["owner"], "workspace_id": scope["workspace"],
                "actor_principal": scope["actor"], "session_id": scope["session"],
                "trace_id": scope["trace"], "dsh_run_id": scope["generation"]}
            if any(binding.get(key) != value for key, value in expected_binding.items()):
                raise AgentConflict("ACP tool ingress conflicts with the durable native Agent lineage")

        if binding is None or binding["status"] != "bound":
            if not bootstrap:
                raise AgentConflict("ACP business tool ingress requires a bound native AgentRun")
            return None

        run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id=:run FOR SHARE",
                        {"run": binding["agent_run_id"]})
        expected_run = {"root_run_id": identity["root_run_id"],
            "parent_run_id": binding["parent_run_id"], "owner_principal": scope["owner"],
            "workspace_id": scope["workspace"], "actor_principal": scope["actor"],
            "session_id": scope["session"], "trace_id": scope["trace"],
            "dsh_run_id": scope["generation"], "authority_boot_id": identity["runtime_boot_id"],
            "status": "active"}
        if (run is None or any(run.get(key) != value for key, value in expected_run.items())
                or run.get("authority_status", "active") != "active"):
            raise AgentConflict("ACP tool ingress AgentRun is no longer active under this authority")
        role = ROLE_BY_ID.get(run["role_id"])
        if role is None or (not bootstrap and tool_name not in role.allowed_tools):
            raise AgentForbidden("ACP Agent role is not authorized for this MCP tool")
        return run["run_id"]

    @staticmethod
    def _normalize_acp_agent_identity(identity: object) -> dict:
        from .agent_research import _entity_id, _runtime_boot_id

        keys = {"root_run_id", "runtime_boot_id", "native_root_session_id",
                "native_agent_session_id", "native_parent_session_id", "origin", "depth"}
        if not isinstance(identity, dict) or set(identity) != keys:
            raise ValueError("exact ACP native Agent registration identity required")
        if not isinstance(identity["root_run_id"], str) or _ACP_ROOT_ID.fullmatch(identity["root_run_id"]) is None:
            raise ValueError("root_run_id must be 32 lowercase hexadecimal characters")
        boot_id = _runtime_boot_id(identity["runtime_boot_id"])
        root_native = _acp_session_id(identity["native_root_session_id"], "native_root_session_id")
        agent_native = _acp_session_id(identity["native_agent_session_id"], "native_agent_session_id")
        parent_native = identity["native_parent_session_id"]
        if parent_native is not None:
            parent_native = _acp_session_id(parent_native, "native_parent_session_id")
        origin, depth = identity["origin"], identity["depth"]
        if (origin == "root" and (depth != 0 or parent_native is not None)
                or origin == "subagent" and (depth != 1 or parent_native is None)
                or origin not in {"root", "subagent"} or type(depth) is not int):
            raise ValueError("invalid bounded ACP Agent origin/depth lineage")
        if origin == "root" and agent_native != root_native:
            raise ValueError("root ACP Agent session must equal its native root session")
        return {"root_run_id": identity["root_run_id"], "runtime_boot_id": boot_id,
                "native_root_session_id": root_native, "native_agent_session_id": agent_native,
                "native_parent_session_id": parent_native, "origin": origin, "depth": depth}

    def _derive_acp_parent_run(self, connection, identity: dict, *, owner: str, workspace: str,
                               actor: str, session: str, trace: str, generation: str,
                               root_run_id: str) -> str | None:
        """Resolve only an already bound direct parent from this exact current root."""
        if identity["root_run_id"] != root_run_id:
            from .agent_research import AgentConflict
            raise AgentConflict("ACP registration root does not match the current Backend root")
        roots = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
            WHERE root_run_id=:root AND origin='root'""", {"root": root_run_id})
        if roots is not None and roots["native_root_session_id"] != identity["native_root_session_id"]:
            from .agent_research import AgentConflict
            raise AgentConflict("ACP native root session changed within one Backend root")
        if identity["origin"] == "root":
            if roots is not None and roots["native_agent_session_id"] != identity["native_agent_session_id"]:
                from .agent_research import AgentConflict
                raise AgentConflict("Backend root already has a different native root Agent")
            return None
        parent = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
            WHERE root_run_id=:root AND native_agent_session_id=:native_parent""",
            {"root": root_run_id, "native_parent": identity["native_parent_session_id"]})
        if parent is None:
            from .agent_research import AgentConflict
            raise AgentConflict("ACP native parent has no durable Backend Agent binding")
        exact_parent_scope = {
            "owner_principal": owner, "workspace_id": workspace, "actor_principal": actor,
            "session_id": session, "trace_id": trace, "dsh_run_id": generation,
            "runtime_boot_id": identity["runtime_boot_id"],
            "native_root_session_id": identity["native_root_session_id"],
            "origin": "root", "depth": 0, "status": "bound",
        }
        if any(parent.get(field) != expected for field, expected in exact_parent_scope.items()):
            from .agent_research import AgentConflict
            raise AgentConflict("ACP native parent binding is not exact and active")
        run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id=:run FOR SHARE",
                        {"run": parent["agent_run_id"]})
        if (run is None or run["status"] != "active" or run.get("authority_status", "active") != "active"
                or run.get("authority_boot_id") != identity["runtime_boot_id"]):
            from .agent_research import AgentConflict
            raise AgentConflict("ACP native parent AgentRun is not active")
        return parent["agent_run_id"]

    def _insert_acp_pending_registration(self, connection, identity: dict, *, scope: dict,
                                         agent_run_id: str, parent_run_id: str | None) -> None:
        execute(connection, """INSERT INTO agent_acp_native_agent_registrations
            (root_run_id,native_agent_session_id,native_root_session_id,native_parent_session_id,
             owner_principal,workspace_id,actor_principal,session_id,trace_id,dsh_run_id,runtime_boot_id,
             origin,depth,agent_run_id,parent_run_id,status)
            VALUES (:root,:native_agent,:native_root,:native_parent,:owner,:workspace,:actor,:session,:trace,
             :generation,:boot,:origin,:depth,:agent_run,:parent_run,'pending')""",
            {"root": identity["root_run_id"], "native_agent": identity["native_agent_session_id"],
             "native_root": identity["native_root_session_id"], "native_parent": identity["native_parent_session_id"],
             **scope, "boot": identity["runtime_boot_id"], "origin": identity["origin"],
             "depth": identity["depth"], "agent_run": agent_run_id, "parent_run": parent_run_id})

    @staticmethod
    def _acp_registration_matches(row: dict, identity: dict, *, scope: dict,
                                  agent_run_id: str, parent_run_id: str | None) -> bool:
        expected = {"root_run_id": identity["root_run_id"],
            "native_agent_session_id": identity["native_agent_session_id"],
            "native_root_session_id": identity["native_root_session_id"],
            "native_parent_session_id": identity["native_parent_session_id"],
            "runtime_boot_id": identity["runtime_boot_id"], "origin": identity["origin"],
            "depth": identity["depth"], "agent_run_id": agent_run_id, "parent_run_id": parent_run_id,
            "owner_principal": scope["owner"], "workspace_id": scope["workspace"],
            "actor_principal": scope["actor"], "session_id": scope["session"],
            "trace_id": scope["trace"], "dsh_run_id": scope["generation"]}
        return all(row.get(key) == value for key, value in expected.items())

    def bind_acp_agent(self, payload: object, *, trusted_scope: dict) -> dict:
        from .agent_research import (AgentConflict, AgentNotFound, AgentUnauthorized,
            _entity_id, _runtime_boot_id)

        fields = {"schema_version", "root_run_id", "runtime_boot_id", "native_root_session_id",
                  "native_agent_session_id", "native_parent_session_id", "origin", "depth",
                  "agent_run_id", "parent_run_id"}
        if not isinstance(payload, dict) or set(payload) != fields or payload.get("schema_version") != "byq-acp-agent-bind.v1":
            raise ValueError("exact ACP Agent bind request required")
        identity = self._normalize_acp_agent_identity({key: payload[key] for key in (
            "root_run_id", "runtime_boot_id", "native_root_session_id", "native_agent_session_id",
            "native_parent_session_id", "origin", "depth")})
        agent_run_id = _entity_id(payload["agent_run_id"], field="agent_run_id", prefix="agent_run")
        parent_run_id = payload["parent_run_id"]
        if parent_run_id is not None:
            parent_run_id = _entity_id(parent_run_id, field="parent_run_id", prefix="agent_run")
        if (identity["root_run_id"] != trusted_scope["root"]
                or identity["runtime_boot_id"] != trusted_scope["boot_id"]):
            raise AgentUnauthorized("ACP Agent bind body does not match trusted runtime scope")
        scope = {"owner": trusted_scope["owner"], "workspace": trusted_scope["workspace"],
                 "actor": trusted_scope["actor"], "session": trusted_scope["session"],
                 "trace": trusted_scope["trace"], "generation": trusted_scope["generation"]}
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._require_lifecycle_workspace(connection, scope["owner"], scope["workspace"])
            authority = self._require_current_acp_boot(connection, identity["runtime_boot_id"])
            self._lifecycle_lock(connection, "root:" + identity["root_run_id"])
            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root",
                              {"root": identity["root_run_id"]})
            if root is None:
                raise AgentNotFound("ACP Backend root not found")
            if (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"]) != (
                    scope["owner"], scope["workspace"], scope["session"], scope["trace"]):
                raise AgentUnauthorized("ACP Agent bind does not match the exact Backend root scope")
            if (root["status"] != "active" or root.get("authority_status", "active") != "active"
                    or root.get("authority_boot_id") != authority["boot_id"]):
                raise AgentConflict("ACP Agent bind root is no longer active under this boot")
            registration = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
                WHERE root_run_id=:root AND native_agent_session_id=:native_agent FOR UPDATE""",
                {"root": identity["root_run_id"], "native_agent": identity["native_agent_session_id"]})
            if registration is None:
                raise AgentNotFound("ACP native Agent registration not found")
            if not self._acp_registration_matches(registration, identity, scope=scope,
                    agent_run_id=agent_run_id, parent_run_id=parent_run_id):
                raise AgentConflict("ACP Agent bind conflicts with its exact pending native registration")
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id=:run FOR SHARE",
                             {"run": agent_run_id})
            if (run is None or run.get("root_run_id") != identity["root_run_id"]
                    or run.get("parent_run_id") != parent_run_id
                    or run.get("authority_boot_id") != identity["runtime_boot_id"]
                    or run.get("owner_principal") != scope["owner"]
                    or run.get("workspace_id") != scope["workspace"]
                    or run.get("actor_principal") != scope["actor"]
                    or run.get("session_id") != scope["session"]
                    or run.get("trace_id") != scope["trace"]
                    or run.get("dsh_run_id") != scope["generation"]):
                raise AgentConflict("ACP Agent bind AgentRun does not match its native registration")
            if registration["status"] == "bound":
                if run["status"] != "active" or registration["receipt_json"] is None:
                    raise AgentConflict("ACP Agent binding is no longer an active exact registration")
                return registration["receipt_json"]
            if run["status"] != "active":
                raise AgentConflict("ACP AgentRun is not active for native binding")
            if identity["origin"] == "subagent":
                parent = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
                    WHERE root_run_id=:root AND native_agent_session_id=:native_parent""",
                    {"root": identity["root_run_id"], "native_parent": identity["native_parent_session_id"]})
                if (parent is None or parent["status"] != "bound" or parent["agent_run_id"] != parent_run_id
                        or parent["runtime_boot_id"] != identity["runtime_boot_id"]):
                    raise AgentConflict("ACP Agent bind parent is not durably bound")
            binding_fields = _acp_binding_fields(identity, scope, agent_run_id=agent_run_id,
                                                 parent_run_id=parent_run_id)
            receipt = {"schema_version": "byq-acp-agent-bind-receipt.v1",
                "root_run_id": identity["root_run_id"], "runtime_boot_id": identity["runtime_boot_id"],
                "native_agent_session_id": identity["native_agent_session_id"],
                "native_parent_session_id": identity["native_parent_session_id"],
                "agent_run_id": agent_run_id, "parent_run_id": parent_run_id,
                "origin": identity["origin"], "depth": identity["depth"], "status": "bound",
                "binding_sha256": acp_binding_sha256(binding_fields)}
            execute(connection, """UPDATE agent_acp_native_agent_registrations
                SET status='bound',receipt_json=CAST(:receipt AS jsonb),updated_at=CURRENT_TIMESTAMP
                WHERE root_run_id=:root AND native_agent_session_id=:native_agent AND status='pending'""",
                {"receipt": json.dumps(receipt, allow_nan=False), "root": identity["root_run_id"],
                 "native_agent": identity["native_agent_session_id"]})
            return receipt

    def get_acp_agent_binding(self, *, root_run_id: object, native_agent_session_id: object,
                              trusted_scope: dict) -> dict:
        from .agent_research import AgentNotFound, _runtime_boot_id

        if not isinstance(root_run_id, str) or _ACP_ROOT_ID.fullmatch(root_run_id) is None:
            raise ValueError("root_run_id must be 32 lowercase hexadecimal characters")
        native_agent = _acp_session_id(native_agent_session_id, "native_agent_session_id")
        if root_run_id != trusted_scope["root"]:
            raise AgentNotFound("ACP native Agent binding not found")
        boot_id = _runtime_boot_id(trusted_scope["boot_id"])
        with self._transaction() as connection:
            row = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
                WHERE root_run_id=:root AND native_agent_session_id=:native_agent""",
                {"root": root_run_id, "native_agent": native_agent})
            if row is None or any(row.get(field) != value for field, value in {
                    "owner_principal": trusted_scope["owner"], "workspace_id": trusted_scope["workspace"],
                    "actor_principal": trusted_scope["actor"], "session_id": trusted_scope["session"],
                    "trace_id": trusted_scope["trace"], "dsh_run_id": trusted_scope["generation"],
                    "runtime_boot_id": boot_id}.items()):
                raise AgentNotFound("ACP native Agent binding not found")
            result = {"schema_version": "byq-acp-agent-binding-status.v1", "root_run_id": root_run_id,
                "runtime_boot_id": boot_id, "native_agent_session_id": native_agent,
                "status": row["status"]}
            if row["status"] == "bound":
                result["receipt"] = row["receipt_json"]
            return result

    def observe_acp_tool_ingress(self, payload: object, *, trusted_scope: dict) -> dict:
        """Persist proof that one verified ACP Agent reached a BYQ MCP tool callback."""
        from .agent_research import AgentConflict, AgentNotFound, AgentUnauthorized

        fields = {"schema_version", "mcp_request_id", "root_run_id", "runtime_boot_id",
                  "native_root_session_id", "native_agent_session_id", "native_parent_session_id",
                  "origin", "depth", "tool_name", "arguments"}
        if (not isinstance(payload, dict) or set(payload) != fields
                or payload.get("schema_version") != "byq-acp-tool-ingress-observe.v1"):
            raise ValueError("exact ACP tool ingress observation required")
        request_id = payload["mcp_request_id"]
        if not isinstance(request_id, str) or _ACP_REQUEST_ID.fullmatch(request_id) is None:
            raise ValueError("mcp_request_id must be 32 lowercase hexadecimal characters")
        tool_name = payload["tool_name"]
        if not isinstance(tool_name, str) or _ACP_TOOL_NAME.fullmatch(tool_name) is None:
            raise ValueError("tool_name must be a bounded BYQ MCP tool name")
        if tool_name == "byq_agent_run_start":
            raise ValueError("AgentRun registration uses its durable native bind flow")
        identity = self._normalize_acp_agent_identity({key: payload[key] for key in (
            "root_run_id", "runtime_boot_id", "native_root_session_id", "native_agent_session_id",
            "native_parent_session_id", "origin", "depth")})
        if (identity["root_run_id"] != trusted_scope["root"]
                or identity["runtime_boot_id"] != trusted_scope["boot_id"]):
            raise AgentUnauthorized("ACP tool ingress body does not match trusted runtime scope")
        arguments_sha256, _ = _canonical_acp_arguments(payload["arguments"])
        bootstrap = tool_name in {"byq_health", "byq_agent_roles", "byq_agent_context"}
        scope = {"owner": trusted_scope["owner"], "workspace": trusted_scope["workspace"],
                 "actor": trusted_scope["actor"], "session": trusted_scope["session"],
                 "trace": trusted_scope["trace"], "generation": trusted_scope["generation"]}
        identity_fields = {"root_run_id": identity["root_run_id"],
            "runtime_boot_id": identity["runtime_boot_id"],
            "native_root_session_id": identity["native_root_session_id"],
            "native_agent_session_id": identity["native_agent_session_id"],
            "native_parent_session_id": identity["native_parent_session_id"],
            "origin": identity["origin"], "depth": identity["depth"],
            "tool_name": tool_name, "arguments_sha256": arguments_sha256}
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._require_lifecycle_workspace(connection, scope["owner"], scope["workspace"])
            authority = self._require_current_acp_boot(connection, identity["runtime_boot_id"])
            self._lifecycle_lock(connection, "acp-mcp-request:" + request_id)
            self._lifecycle_lock(connection, "root:" + identity["root_run_id"])
            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root",
                              {"root": identity["root_run_id"]})
            if root is None:
                raise AgentNotFound("ACP Backend root not found")
            if (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"]) != (
                    scope["owner"], scope["workspace"], scope["session"], scope["trace"]):
                raise AgentUnauthorized("ACP tool ingress does not match the exact Backend root scope")
            if (root["status"] != "active" or root.get("authority_status", "active") != "active"
                    or root.get("authority_boot_id") != authority["boot_id"]):
                raise AgentConflict("ACP tool ingress root is not active under current Backend authority")

            prior = fetch_one(connection, "SELECT * FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
                              {"id": request_id})
            if prior is not None:
                expected_prior = {"owner_principal": scope["owner"], "workspace_id": scope["workspace"],
                    "actor_principal": scope["actor"], "session_id": scope["session"],
                    "trace_id": scope["trace"], "dsh_run_id": scope["generation"],
                    **identity_fields}
                if any(prior.get(key) != value for key, value in expected_prior.items()):
                    raise AgentConflict("ACP tool ingress request id was reused for changed input or identity")
                if (prior.get("settlement_json") or {}).get("outcome") == "aborted_before_dispatch":
                    raise AgentConflict("ACP tool ingress request was aborted before dispatch")
                return prior["receipt_json"]

            agent_run_id = self._acp_tool_ingress_agent_run(
                connection, identity, scope, tool_name, bootstrap=bootstrap)

            total = fetch_one(connection, """SELECT
                (SELECT count(*) FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root)
                + (SELECT count(*) FROM agent_acp_domain_call_observations WHERE root_run_id=:root)
                AS count""", {"root": identity["root_run_id"]})
            if total["count"] >= 4096:
                raise AgentConflict("ACP root ingress evidence retention bound reached")
            sequence_row = fetch_one(connection, """SELECT GREATEST(
                COALESCE((SELECT MAX(sequence) FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root),0),
                COALESCE((SELECT MAX(sequence) FROM agent_acp_domain_call_observations WHERE root_run_id=:root),0)
                )+1 AS sequence""", {"root": identity["root_run_id"]})
            sequence = sequence_row["sequence"]
            if type(sequence) is not int or not 1 <= sequence < 2**63:
                raise AgentConflict("ACP root ingress evidence sequence is exhausted")
            event = {"sequence": sequence, "owner_principal": scope["owner"],
                "workspace_id": scope["workspace"], "actor_principal": scope["actor"],
                "session_id": scope["session"], "trace_id": scope["trace"],
                "dsh_run_id": scope["generation"], "agent_run_id": agent_run_id, **identity_fields}
            event_sha256 = acp_binding_sha256(event)
            receipt = {"schema_version": "byq-acp-tool-ingress-receipt.v1",
                "mcp_request_id": request_id, "root_run_id": identity["root_run_id"],
                "runtime_boot_id": identity["runtime_boot_id"],
                "native_root_session_id": identity["native_root_session_id"],
                "native_agent_session_id": identity["native_agent_session_id"],
                "native_parent_session_id": identity["native_parent_session_id"],
                "origin": identity["origin"], "depth": identity["depth"],
                "tool_name": tool_name, "agent_run_id": agent_run_id,
                "sequence": sequence, "event_sha256": event_sha256}
            execute(connection, """INSERT INTO agent_acp_tool_ingress_observations
                (mcp_request_id,owner_principal,workspace_id,actor_principal,session_id,trace_id,dsh_run_id,
                 runtime_boot_id,root_run_id,native_root_session_id,native_agent_session_id,
                 native_parent_session_id,origin,depth,agent_run_id,tool_name,arguments_sha256,
                 sequence,event_sha256,receipt_json)
                VALUES (:mcp_request_id,:owner,:workspace,:actor,:session,:trace,:generation,
                 :boot,:root,:native_root,:native_agent,:native_parent,:origin,:depth,:agent_run,
                 :tool,:arguments_sha256,:sequence,:event_sha256,CAST(:receipt AS jsonb))""",
                {"mcp_request_id": request_id, "owner": scope["owner"], "workspace": scope["workspace"],
                 "actor": scope["actor"], "session": scope["session"], "trace": scope["trace"],
                 "generation": scope["generation"], "boot": identity["runtime_boot_id"],
                 "root": identity["root_run_id"], "native_root": identity["native_root_session_id"],
                 "native_agent": identity["native_agent_session_id"],
                 "native_parent": identity["native_parent_session_id"], "origin": identity["origin"],
                 "depth": identity["depth"], "agent_run": agent_run_id, "tool": tool_name,
                 "arguments_sha256": arguments_sha256, "sequence": sequence,
                 "event_sha256": event_sha256, "receipt": json.dumps(receipt, allow_nan=False)})
            return receipt

    def abort_acp_tool_ingress_before_dispatch(self, payload: object, *, trusted_scope: dict) -> dict:
        """Durably prove an observe request will not dispatch its handler."""
        from .agent_research import AgentConflict, AgentNotFound, AgentUnauthorized

        fields = {"schema_version", "mcp_request_id", "root_run_id", "runtime_boot_id",
                  "native_root_session_id", "native_agent_session_id", "native_parent_session_id",
                  "origin", "depth", "tool_name", "arguments"}
        if (not isinstance(payload, dict) or set(payload) != fields
                or payload.get("schema_version") != "byq-acp-tool-ingress-abort.v1"):
            raise ValueError("exact ACP tool ingress abort request required")
        request_id = payload["mcp_request_id"]
        if not isinstance(request_id, str) or _ACP_REQUEST_ID.fullmatch(request_id) is None:
            raise ValueError("mcp_request_id must be 32 lowercase hexadecimal characters")
        tool_name = payload["tool_name"]
        if (not isinstance(tool_name, str) or _ACP_TOOL_NAME.fullmatch(tool_name) is None
                or tool_name == "byq_agent_run_start"):
            raise ValueError("tool_name must be a non-registration BYQ MCP tool")
        identity = self._normalize_acp_agent_identity({key: payload[key] for key in (
            "root_run_id", "runtime_boot_id", "native_root_session_id", "native_agent_session_id",
            "native_parent_session_id", "origin", "depth")})
        if (identity["root_run_id"] != trusted_scope["root"]
                or identity["runtime_boot_id"] != trusted_scope["boot_id"]):
            raise AgentUnauthorized("ACP tool ingress abort does not match trusted runtime scope")
        arguments_sha256, _ = _canonical_acp_arguments(payload["arguments"])
        bootstrap = tool_name in {"byq_health", "byq_agent_roles", "byq_agent_context"}
        scope = {"owner": trusted_scope["owner"], "workspace": trusted_scope["workspace"],
                 "actor": trusted_scope["actor"], "session": trusted_scope["session"],
                 "trace": trusted_scope["trace"], "generation": trusted_scope["generation"]}
        identity_fields = {"root_run_id": identity["root_run_id"],
            "runtime_boot_id": identity["runtime_boot_id"],
            "native_root_session_id": identity["native_root_session_id"],
            "native_agent_session_id": identity["native_agent_session_id"],
            "native_parent_session_id": identity["native_parent_session_id"],
            "origin": identity["origin"], "depth": identity["depth"],
            "tool_name": tool_name, "arguments_sha256": arguments_sha256}

        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._require_lifecycle_workspace(connection, scope["owner"], scope["workspace"])
            authority = self._require_current_acp_boot(connection, identity["runtime_boot_id"])
            self._lifecycle_lock(connection, "acp-mcp-request:" + request_id)
            self._lifecycle_lock(connection, "root:" + identity["root_run_id"])
            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root",
                              {"root": identity["root_run_id"]})
            if root is None:
                raise AgentNotFound("ACP Backend root not found")
            if (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"]) != (
                    scope["owner"], scope["workspace"], scope["session"], scope["trace"]):
                raise AgentUnauthorized("ACP tool ingress abort does not match the exact Backend root scope")

            prior = fetch_one(connection, """SELECT * FROM agent_acp_tool_ingress_observations
                WHERE mcp_request_id=:id FOR UPDATE""", {"id": request_id})
            expected_prior = {"owner_principal": scope["owner"], "workspace_id": scope["workspace"],
                "actor_principal": scope["actor"], "session_id": scope["session"],
                "trace_id": scope["trace"], "dsh_run_id": scope["generation"], **identity_fields}
            if prior is not None:
                if any(prior.get(key) != value for key, value in expected_prior.items()):
                    raise AgentConflict("ACP tool ingress abort conflicts with the exact request identity")
                previous_abort = prior.get("settlement_json")
                if (prior["status"] == "settled" and isinstance(previous_abort, dict)
                        and previous_abort.get("outcome") == "aborted_before_dispatch"):
                    expected_receipt = self._acp_ingress_abort_receipt(prior)
                    if previous_abort != expected_receipt:
                        raise AgentConflict("ACP tool ingress abort receipt is not internally consistent")
                    return previous_abort
                if prior["status"] != "pending":
                    raise AgentConflict("ACP tool ingress is already settled or unknown and cannot be aborted")
                if (root["status"] != "active" or root.get("authority_status", "active") != "active"
                        or root.get("authority_boot_id") != authority["boot_id"]):
                    raise AgentConflict("ACP tool ingress abort root is not active under current authority")
                receipt = self._acp_ingress_abort_receipt(prior)
                execute(connection, """UPDATE agent_acp_tool_ingress_observations
                    SET status='settled',settlement_json=CAST(:settlement AS jsonb),settled_at=CURRENT_TIMESTAMP
                    WHERE mcp_request_id=:id AND status='pending'""",
                    {"settlement": json.dumps(receipt, allow_nan=False), "id": request_id})
                return receipt

            if (root["status"] != "active" or root.get("authority_status", "active") != "active"
                    or root.get("authority_boot_id") != authority["boot_id"]):
                raise AgentConflict("ACP tool ingress abort root is not active under current authority")
            agent_run_id = self._acp_tool_ingress_agent_run(
                connection, identity, scope, tool_name, bootstrap=bootstrap)
            total = fetch_one(connection, """SELECT
                (SELECT count(*) FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root)
                + (SELECT count(*) FROM agent_acp_domain_call_observations WHERE root_run_id=:root)
                AS count""", {"root": identity["root_run_id"]})
            if total["count"] >= 4096:
                raise AgentConflict("ACP root ingress evidence retention bound reached")
            sequence_row = fetch_one(connection, """SELECT GREATEST(
                COALESCE((SELECT MAX(sequence) FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root),0),
                COALESCE((SELECT MAX(sequence) FROM agent_acp_domain_call_observations WHERE root_run_id=:root),0)
                )+1 AS sequence""", {"root": identity["root_run_id"]})
            sequence = sequence_row["sequence"]
            if type(sequence) is not int or not 1 <= sequence < 2**63:
                raise AgentConflict("ACP root ingress evidence sequence is exhausted")
            event = {"sequence": sequence, "owner_principal": scope["owner"],
                "workspace_id": scope["workspace"], "actor_principal": scope["actor"],
                "session_id": scope["session"], "trace_id": scope["trace"],
                "dsh_run_id": scope["generation"], "agent_run_id": agent_run_id,
                **identity_fields}
            event_sha256 = acp_binding_sha256(event)
            observed_receipt = {"schema_version": "byq-acp-tool-ingress-receipt.v1",
                "mcp_request_id": request_id, "root_run_id": identity["root_run_id"],
                "runtime_boot_id": identity["runtime_boot_id"],
                "native_root_session_id": identity["native_root_session_id"],
                "native_agent_session_id": identity["native_agent_session_id"],
                "native_parent_session_id": identity["native_parent_session_id"],
                "origin": identity["origin"], "depth": identity["depth"],
                "tool_name": tool_name, "agent_run_id": agent_run_id,
                "sequence": sequence, "event_sha256": event_sha256}
            base = {"schema_version": "byq-acp-tool-ingress-abort-receipt.v1",
                "mcp_request_id": request_id, "root_run_id": identity["root_run_id"],
                "runtime_boot_id": identity["runtime_boot_id"],
                "native_root_session_id": identity["native_root_session_id"],
                "native_agent_session_id": identity["native_agent_session_id"],
                "native_parent_session_id": identity["native_parent_session_id"],
                "origin": identity["origin"], "depth": identity["depth"],
                "tool_name": tool_name, "arguments_sha256": arguments_sha256,
                "sequence": sequence, "event_sha256": event_sha256,
                "outcome": "aborted_before_dispatch"}
            receipt = {**base, "abort_sha256": acp_binding_sha256(base)}
            execute(connection, """INSERT INTO agent_acp_tool_ingress_observations
                (mcp_request_id,owner_principal,workspace_id,actor_principal,session_id,trace_id,dsh_run_id,
                 runtime_boot_id,root_run_id,native_root_session_id,native_agent_session_id,
                 native_parent_session_id,origin,depth,agent_run_id,tool_name,arguments_sha256,
                 sequence,event_sha256,status,settlement_json,settled_at,receipt_json)
                VALUES (:mcp_request_id,:owner,:workspace,:actor,:session,:trace,:generation,
                 :boot,:root,:native_root,:native_agent,:native_parent,:origin,:depth,:agent_run,
                 :tool,:arguments_sha256,:sequence,:event_sha256,'settled',CAST(:settlement AS jsonb),
                 CURRENT_TIMESTAMP,CAST(:receipt AS jsonb))""",
                {"mcp_request_id": request_id, "owner": scope["owner"], "workspace": scope["workspace"],
                 "actor": scope["actor"], "session": scope["session"], "trace": scope["trace"],
                 "generation": scope["generation"], "boot": identity["runtime_boot_id"],
                 "root": identity["root_run_id"], "native_root": identity["native_root_session_id"],
                 "native_agent": identity["native_agent_session_id"],
                 "native_parent": identity["native_parent_session_id"], "origin": identity["origin"],
                 "depth": identity["depth"], "agent_run": agent_run_id, "tool": tool_name,
                 "arguments_sha256": arguments_sha256, "sequence": sequence,
                 "event_sha256": event_sha256,
                 "settlement": json.dumps(receipt, allow_nan=False),
                 "receipt": json.dumps(observed_receipt, allow_nan=False)})
            return receipt

    @staticmethod
    def _acp_ingress_abort_receipt(row: dict) -> dict:
        base = {"schema_version": "byq-acp-tool-ingress-abort-receipt.v1",
            "mcp_request_id": row["mcp_request_id"], "root_run_id": row["root_run_id"],
            "runtime_boot_id": row["runtime_boot_id"],
            "native_root_session_id": row["native_root_session_id"],
            "native_agent_session_id": row["native_agent_session_id"],
            "native_parent_session_id": row["native_parent_session_id"],
            "origin": row["origin"], "depth": row["depth"], "tool_name": row["tool_name"],
            "arguments_sha256": row["arguments_sha256"], "sequence": row["sequence"],
            "event_sha256": row["event_sha256"], "outcome": "aborted_before_dispatch"}
        return {**base, "abort_sha256": acp_binding_sha256(base)}

    def settle_acp_tool_ingress(self, payload: object, *, trusted_scope: dict) -> dict:
        """Close one exact MCP dispatch receipt without classifying business success."""
        from .agent_research import AgentConflict, AgentNotFound, AgentUnauthorized, _runtime_boot_id

        fields = {"schema_version", "mcp_request_id", "root_run_id", "runtime_boot_id",
                  "native_root_session_id", "native_agent_session_id", "native_parent_session_id",
                  "origin", "depth", "tool_name", "sequence", "event_sha256", "outcome"}
        if (not isinstance(payload, dict) or set(payload) != fields
                or payload.get("schema_version") != "byq-acp-tool-ingress-settle.v1"):
            raise ValueError("exact ACP tool ingress settlement required")
        request_id = payload["mcp_request_id"]
        if not isinstance(request_id, str) or _ACP_REQUEST_ID.fullmatch(request_id) is None:
            raise ValueError("mcp_request_id must be 32 lowercase hexadecimal characters")
        identity = self._normalize_acp_agent_identity({key: payload[key] for key in (
            "root_run_id", "runtime_boot_id", "native_root_session_id", "native_agent_session_id",
            "native_parent_session_id", "origin", "depth")})
        tool_name = payload["tool_name"]
        if not isinstance(tool_name, str) or _ACP_TOOL_NAME.fullmatch(tool_name) is None:
            raise ValueError("tool_name must be a bounded BYQ MCP tool name")
        sequence = payload["sequence"]
        if type(sequence) is not int or not 1 <= sequence < 2**63:
            raise ValueError("sequence must be a positive signed 64-bit integer")
        event_sha256 = payload["event_sha256"]
        if not isinstance(event_sha256, str) or _ACP_SHA256.fullmatch(event_sha256) is None:
            raise ValueError("event_sha256 must be 64 lowercase hexadecimal characters")
        outcome = payload["outcome"]
        if outcome not in {"settled", "unknown"}:
            raise ValueError("ACP tool ingress outcome must be settled or unknown")
        if (identity["root_run_id"] != trusted_scope["root"]
                or identity["runtime_boot_id"] != trusted_scope["boot_id"]):
            raise AgentUnauthorized("ACP tool ingress settlement does not match trusted runtime scope")
        scope = {"owner": trusted_scope["owner"], "workspace": trusted_scope["workspace"],
                 "actor": trusted_scope["actor"], "session": trusted_scope["session"],
                 "trace": trusted_scope["trace"], "generation": trusted_scope["generation"]}
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._require_lifecycle_workspace(connection, scope["owner"], scope["workspace"])
            self._require_current_acp_boot(connection, identity["runtime_boot_id"])
            self._lifecycle_lock(connection, "acp-mcp-request:" + request_id)
            self._lifecycle_lock(connection, "root:" + identity["root_run_id"])
            row = fetch_one(connection, """SELECT * FROM agent_acp_tool_ingress_observations
                WHERE mcp_request_id=:id FOR UPDATE""", {"id": request_id})
            if row is None:
                raise AgentNotFound("ACP tool ingress receipt not found")
            expected = {"owner_principal": scope["owner"], "workspace_id": scope["workspace"],
                "actor_principal": scope["actor"], "session_id": scope["session"],
                "trace_id": scope["trace"], "dsh_run_id": scope["generation"],
                "runtime_boot_id": identity["runtime_boot_id"], "root_run_id": identity["root_run_id"],
                "native_root_session_id": identity["native_root_session_id"],
                "native_agent_session_id": identity["native_agent_session_id"],
                "native_parent_session_id": identity["native_parent_session_id"],
                "origin": identity["origin"], "depth": identity["depth"],
                "tool_name": tool_name, "sequence": sequence, "event_sha256": event_sha256}
            if any(row.get(key) != value for key, value in expected.items()):
                raise AgentConflict("ACP tool ingress settlement does not match the exact receipt")
            if row["status"] in {"settled", "unknown"}:
                if (row["status"] != outcome or row["settlement_json"] is None
                        or row["settlement_json"].get("outcome") != outcome):
                    raise AgentConflict("ACP tool ingress settlement outcome is already fixed")
                return row["settlement_json"]
            root = fetch_one(connection, """SELECT status,authority_status,authority_boot_id
                FROM agent_runtime_turns WHERE root_run_id=:root""", {"root": identity["root_run_id"]})
            if (root is None or root["status"] != "active" or root["authority_status"] != "active"
                    or root["authority_boot_id"] != identity["runtime_boot_id"]):
                raise AgentConflict("ACP tool ingress cannot settle after root authority closes")
            settlement_sha256 = acp_binding_sha256({"mcp_request_id": request_id,
                "root_run_id": identity["root_run_id"], "runtime_boot_id": identity["runtime_boot_id"],
                "native_agent_session_id": identity["native_agent_session_id"], "tool_name": tool_name,
                "sequence": sequence, "event_sha256": event_sha256, "outcome": outcome})
            receipt = {"schema_version": "byq-acp-tool-ingress-settle-receipt.v1",
                "mcp_request_id": request_id, "root_run_id": identity["root_run_id"],
                "runtime_boot_id": identity["runtime_boot_id"],
                "native_agent_session_id": identity["native_agent_session_id"],
                "tool_name": tool_name, "sequence": sequence, "event_sha256": event_sha256,
                "outcome": outcome, "settlement_sha256": settlement_sha256}
            execute(connection, """UPDATE agent_acp_tool_ingress_observations
                SET status=:outcome,settlement_json=CAST(:settlement AS jsonb),settled_at=CURRENT_TIMESTAMP
                WHERE mcp_request_id=:id AND status='pending'""",
                {"outcome": outcome, "settlement": json.dumps(receipt, allow_nan=False), "id": request_id})
            return receipt

    def _acp_terminal_evidence_snapshot(self, connection, root_run_id: str) -> dict[str, object]:
        """Freeze the shared ingress cursor and raw-free unknown claim summary under the root lock."""
        from .agent_research import AgentConflict

        events = execute(connection, """SELECT sequence,event_sha256,event_kind,status,outcome,settlement_sha256 FROM (
                SELECT sequence,event_sha256,'domain_call'::text AS event_kind,
                    'observed'::text AS status,NULL::text AS outcome,NULL::text AS settlement_sha256
                FROM agent_acp_domain_call_observations WHERE root_run_id=:root
                UNION ALL
                SELECT sequence,event_sha256,'tool_ingress'::text AS event_kind,status,
                    settlement_json->>'outcome' AS outcome,
                    COALESCE(settlement_json->>'settlement_sha256',settlement_json->>'abort_sha256')
                        AS settlement_sha256
                FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root
            ) evidence ORDER BY sequence LIMIT 4097""", {"root": root_run_id})
        if len(events) > 4096 or any(row["sequence"] != index for index, row in enumerate(events, 1)):
            raise AgentConflict("ACP root ingress evidence cursor is not contiguous and bounded")
        ingress_sequence = len(events)
        ingress_sha256 = acp_binding_sha256({"schema_version": "byq-acp-root-ingress-cursor.v1",
            "root_run_id": root_run_id, "sequence": ingress_sequence,
            "events": [{"sequence": row["sequence"], "event_sha256": row["event_sha256"],
                        "kind": row["event_kind"], "status": row["status"],
                        "outcome": row["outcome"], "settlement_sha256": row["settlement_sha256"]}
                       for row in events]})
        claims = execute(connection, """SELECT claim_id,task_id,action,idempotency_key,request_sha256,
                    input_sha256,agent_run_id,evidence_sequence,status
                FROM agent_domain_call_claims WHERE root_run_id=:root AND status IN ('claimed','executing')
                ORDER BY claim_id LIMIT 4097""", {"root": root_run_id})
        if len(claims) > 4096:
            raise AgentConflict("ACP unresolved claim projection exceeds its bounded result")
        bounded_claims = [{"claim_id": row["claim_id"], "task_id": row["task_id"],
            "action": row["action"], "idempotency_key_sha256": hashlib.sha256(
                row["idempotency_key"].encode("utf-8")).hexdigest(),
            "request_sha256": row["request_sha256"], "input_sha256": row["input_sha256"],
            "agent_run_id": row["agent_run_id"], "evidence_sequence": row["evidence_sequence"],
            "status": row["status"]} for row in claims]
        return {"terminal_acp_ingress_sequence": ingress_sequence,
            "terminal_acp_ingress_sha256": ingress_sha256,
            "terminal_unknown_claim_count": len(bounded_claims),
            "terminal_unknown_claims_sha256": acp_binding_sha256({
                "schema_version": "byq-acp-unknown-claims.v1", "root_run_id": root_run_id,
                "claims": bounded_claims})}

    def observe_acp_domain_call(self, payload: object, *, trusted_scope: dict) -> dict:
        from .agent_research import AgentConflict, AgentNotFound, AgentUnauthorized, _runtime_boot_id

        fields = {"schema_version", "mcp_request_id", "root_run_id", "runtime_boot_id",
                  "native_agent_session_id", "action", "arguments"}
        if (not isinstance(payload, dict) or set(payload) != fields
                or payload.get("schema_version") != "byq-acp-domain-call-observe.v1"):
            raise ValueError("exact ACP domain call observation required")
        request_id = payload["mcp_request_id"]
        if not isinstance(request_id, str) or _ACP_REQUEST_ID.fullmatch(request_id) is None:
            raise ValueError("mcp_request_id must be 32 lowercase hexadecimal characters")
        if (not isinstance(payload["root_run_id"], str)
                or _ACP_ROOT_ID.fullmatch(payload["root_run_id"]) is None):
            raise ValueError("root_run_id must be 32 lowercase hexadecimal characters")
        identity = {"root_run_id": payload["root_run_id"],
                    "runtime_boot_id": _runtime_boot_id(payload["runtime_boot_id"]),
                    "native_agent_session_id": _acp_session_id(payload["native_agent_session_id"],
                                                                "native_agent_session_id")}
        if (identity["root_run_id"] != trusted_scope["root"]
                or identity["runtime_boot_id"] != trusted_scope["boot_id"]):
            raise AgentUnauthorized("ACP observation body does not match trusted runtime scope")
        arguments = payload["arguments"]
        evidence = request_evidence(payload["action"], arguments, trace_id=trusted_scope["trace"])
        scope = {"owner": trusted_scope["owner"], "workspace": trusted_scope["workspace"],
                 "actor": trusted_scope["actor"], "session": trusted_scope["session"],
                 "trace": trusted_scope["trace"], "generation": trusted_scope["generation"]}
        context = {"owner": scope["owner"], "workspace": scope["workspace"],
                   "session": scope["session"], "trace": scope["trace"],
                   "root": identity["root_run_id"], "boot_id": identity["runtime_boot_id"]}
        replay_identity = {"mcp_request_id": request_id, "owner_principal": scope["owner"],
            "workspace_id": scope["workspace"], "actor_principal": scope["actor"],
            "session_id": scope["session"], "trace_id": scope["trace"],
            "dsh_run_id": scope["generation"], "runtime_boot_id": identity["runtime_boot_id"],
            "root_run_id": identity["root_run_id"],
            "native_agent_session_id": identity["native_agent_session_id"],
            "agent_run_id": evidence["agent_run_id"], "task_id": evidence["task_id"],
            "action": evidence["action"], "idempotency_key": evidence["idempotency_key"],
            "request_sha256": evidence["request_sha256"], "input_sha256": evidence["input_sha256"]}
        with self._transaction() as connection:
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._require_lifecycle_workspace(connection, scope["owner"], scope["workspace"])
            self._lifecycle_lock(connection, "root:" + identity["root_run_id"])
            authority = self._require_current_acp_boot(connection, identity["runtime_boot_id"])
            prior = fetch_one(connection, "SELECT * FROM agent_acp_domain_call_observations WHERE mcp_request_id=:id",
                              {"id": request_id})
            if prior is not None:
                if any(prior.get(key) != value for key, value in replay_identity.items()):
                    raise AgentConflict("ACP MCP request id was reused for changed input or identity")
                binding = fetch_one(connection, """SELECT status FROM agent_acp_native_agent_registrations
                    WHERE root_run_id=:root AND native_agent_session_id=:native_agent AND agent_run_id=:run""",
                    {"root": identity["root_run_id"], "native_agent": identity["native_agent_session_id"],
                     "run": evidence["agent_run_id"]})
                if binding is None or binding["status"] != "bound":
                    raise AgentConflict("exact ACP observation no longer has its durable Agent binding")
                return prior["receipt_json"]

            root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root",
                              {"root": identity["root_run_id"]})
            if root is None:
                raise AgentNotFound("ACP Backend root not found")
            if (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"]) != (
                    scope["owner"], scope["workspace"], scope["session"], scope["trace"]):
                raise AgentUnauthorized("ACP observation does not match the exact Backend root scope")
            if (root["status"] != "active" or root.get("authority_status", "active") != "active"
                    or root.get("authority_boot_id") != authority["boot_id"]):
                raise AgentConflict("ACP observation root is not active under current Backend authority")
            binding = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
                WHERE root_run_id=:root AND native_agent_session_id=:native_agent FOR SHARE""",
                {"root": identity["root_run_id"], "native_agent": identity["native_agent_session_id"]})
            root_binding = fetch_one(connection, """SELECT * FROM agent_acp_native_agent_registrations
                WHERE root_run_id=:root AND origin='root' FOR SHARE""",
                {"root": identity["root_run_id"]})
            if (binding is None or binding["status"] != "bound"
                    or binding["runtime_boot_id"] != identity["runtime_boot_id"]
                    or root_binding is None or root_binding["status"] != "bound"
                    or root_binding["native_agent_session_id"] != root_binding["native_root_session_id"]
                    or binding["native_root_session_id"] != root_binding["native_root_session_id"]
                    or binding["agent_run_id"] != evidence["agent_run_id"]):
                raise AgentConflict("ACP observation requires the exact bound native AgentRun")
            self._domain_identity(connection, {**evidence, "generation": scope["generation"]},
                                  context, active=True)

            root_count = fetch_one(connection, """SELECT
                (SELECT count(*) FROM agent_acp_domain_call_observations WHERE root_run_id=:root)
                + (SELECT count(*) FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root)
                AS count""",
                {"root": identity["root_run_id"]})
            if root_count["count"] >= 4096:
                raise AgentConflict("ACP root ingress evidence retention bound reached")
            self._lifecycle_lock(connection, "domain-call-session:" + scope["session"])
            session_count = fetch_one(connection, """SELECT count(*) AS count FROM agent_domain_call_evidence
                WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session""",
                {"owner": scope["owner"], "workspace": scope["workspace"], "session": scope["session"]})
            if session_count["count"] >= 1024:
                raise AgentConflict("private call evidence retention bound reached")
            sequence_row = fetch_one(connection, """SELECT GREATEST(
                COALESCE((SELECT MAX(sequence) FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root),0),
                COALESCE((SELECT MAX(sequence) FROM agent_acp_domain_call_observations WHERE root_run_id=:root),0)
                )+1 AS sequence""",
                {"root": identity["root_run_id"]})
            evidence_sequence_row = fetch_one(connection, """SELECT COALESCE(MAX(sequence),0)+1 AS sequence
                FROM agent_domain_call_evidence WHERE owner_principal=:owner
                  AND workspace_id=:workspace AND session_id=:session""",
                {"owner": scope["owner"], "workspace": scope["workspace"], "session": scope["session"]})
            sequence, evidence_sequence = sequence_row["sequence"], evidence_sequence_row["sequence"]
            if (type(sequence) is not int or not 1 <= sequence < 2**63
                    or type(evidence_sequence) is not int or not 1 <= evidence_sequence < 2**63):
                raise AgentConflict("ACP observation sequence is exhausted")
            stored_evidence = {"schema_version": "domain-call-observed.v1", "sequence": evidence_sequence,
                "root_run_id": identity["root_run_id"], "generation": scope["generation"],
                "call_id": "acp-" + request_id, **evidence}
            stored_receipt = call_evidence_receipt(stored_evidence)
            event = {**replay_identity, "sequence": sequence,
                     "evidence_sequence": evidence_sequence}
            event_sha256 = acp_binding_sha256(event)
            receipt = {"schema_version": "byq-acp-domain-call-observation-receipt.v1",
                "mcp_request_id": request_id, "root_run_id": identity["root_run_id"],
                "sequence": sequence, "event_sha256": event_sha256}
            execute(connection, """INSERT INTO agent_domain_call_evidence
                (owner_principal,workspace_id,session_id,trace_id,sequence,root_run_id,generation,agent_run_id,
                 task_id,action,idempotency_key,request_sha256,input_sha256,evidence_json,receipt_json)
                VALUES (:owner,:workspace,:session,:trace,:sequence,:root,:generation,:agent_run_id,
                 :task_id,:action,:idempotency_key,:request_sha256,:input_sha256,
                 CAST(:evidence AS jsonb),CAST(:stored_receipt AS jsonb))""",
                {**evidence, "owner": scope["owner"], "workspace": scope["workspace"],
                 "session": scope["session"], "trace": scope["trace"], "sequence": evidence_sequence,
                 "root": identity["root_run_id"], "generation": scope["generation"],
                 "evidence": json.dumps(stored_evidence, allow_nan=False),
                 "stored_receipt": json.dumps(stored_receipt, allow_nan=False)})
            execute(connection, """INSERT INTO agent_acp_domain_call_observations
                (mcp_request_id,owner_principal,workspace_id,actor_principal,session_id,trace_id,dsh_run_id,
                 runtime_boot_id,root_run_id,native_agent_session_id,sequence,evidence_sequence,agent_run_id,
                 task_id,action,idempotency_key,request_sha256,input_sha256,event_sha256,receipt_json)
                VALUES (:mcp_request_id,:owner_principal,:workspace_id,:actor_principal,:session_id,:trace_id,
                 :dsh_run_id,:runtime_boot_id,:root_run_id,:native_agent_session_id,:sequence,:evidence_sequence,
                 :agent_run_id,:task_id,:action,:idempotency_key,:request_sha256,:input_sha256,:event_sha256,
                 CAST(:receipt AS jsonb))""",
                {**replay_identity, "sequence": sequence, "evidence_sequence": evidence_sequence,
                 "event_sha256": event_sha256, "receipt": json.dumps(receipt, allow_nan=False)})
            return receipt

    def get_acp_domain_call_observation(self, *, mcp_request_id: object,
                                        trusted_scope: dict) -> dict:
        from .agent_research import AgentNotFound

        if not isinstance(mcp_request_id, str) or _ACP_REQUEST_ID.fullmatch(mcp_request_id) is None:
            raise ValueError("mcp_request_id must be 32 lowercase hexadecimal characters")
        row = self._fetch_one("SELECT * FROM agent_acp_domain_call_observations WHERE mcp_request_id=:id",
                              {"id": mcp_request_id})
        if row is None or any(row.get(field) != value for field, value in {
                "owner_principal": trusted_scope["owner"], "workspace_id": trusted_scope["workspace"],
                "actor_principal": trusted_scope["actor"], "session_id": trusted_scope["session"],
                "trace_id": trusted_scope["trace"], "dsh_run_id": trusted_scope["generation"],
                "runtime_boot_id": trusted_scope["boot_id"], "root_run_id": trusted_scope["root"]}.items()):
            raise AgentNotFound("ACP observation receipt not found")
        return row["receipt_json"]

    def _domain_identity(self, connection, evidence, context, *, active):
        from .agent_research import AgentConflict, AgentUnauthorized, ROLE_BY_ID

        self._lifecycle_lock(connection, "runtime-authority:current")
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
                       or root.get("authority_status", "active") != "active"
                       or run.get("authority_status", "active") != "active"
                       or task["status"] in {"cancelled", "failed", "completed"} or conversation["status"] != "active"):
            raise AgentConflict("domain call execution authority is no longer active")
        if active:
            authority = self._require_current_runtime_boot(connection, context.get("boot_id"))
            if authority is not None and (
                    root.get("authority_boot_id") != authority["boot_id"]
                    or run.get("authority_boot_id") != authority["boot_id"]):
                raise AgentConflict("domain call belongs to a superseded runtime boot")
        return conversation["conversation_id"]

    def claim_domain_call(self, action, payload, *, trusted_owner, trusted_workspace,
                          trusted_session_id, trusted_trace_id, trusted_generation, trusted_root,
                          trusted_boot_id=None, trusted_acp_observation_id=None):
        """Commit the debit before domain validation; proof arrival never executes."""
        from .agent_research import AgentConflict, _principal, _trace
        value = request_evidence(action, payload, trace_id=trusted_trace_id)
        # Reuse the closed proof identity validator, not a model-provided root.
        validate_call_evidence({**value, "schema_version": "domain-call-observed.v1", "sequence": 1,
            "root_run_id": trusted_root, "generation": trusted_generation, "call_id": "request"})
        if trusted_boot_id is not None:
            from .agent_research import _runtime_boot_id
            trusted_boot_id = _runtime_boot_id(trusted_boot_id)
        context = {"owner": _principal(trusted_owner, field="owner_principal"),
            "workspace": _trace(trusted_workspace, field="workspace_id"),
            "session": _trace(trusted_session_id, field="session_id"), "trace": trusted_trace_id,
            "root": trusted_root, "boot_id": trusted_boot_id}
        scope = {**value, **context}
        with self._transaction() as connection:
            # No proof means no claim and no execution, including when the
            # root/registration delivery itself is still pending. Do not turn
            # that ordering window into an ambiguous domain-write conflict.
            self._lifecycle_lock(connection, "runtime-authority:current")
            self._require_lifecycle_workspace(connection, context["owner"], context["workspace"])
            self._lifecycle_lock(connection, "root:" + context["root"])
            acp_marker = fetch_one(connection, """SELECT native_agent_session_id,status
                FROM agent_acp_native_agent_registrations WHERE root_run_id=:root
                ORDER BY native_agent_session_id LIMIT 1""", {"root": context["root"]})
            if acp_marker is not None:
                if not isinstance(trusted_acp_observation_id, str) or _ACP_REQUEST_ID.fullmatch(
                        trusted_acp_observation_id) is None:
                    raise AgentConflict("ACP domain call requires its exact Backend observation receipt")
                observation = fetch_one(connection, """SELECT * FROM agent_acp_domain_call_observations
                    WHERE mcp_request_id=:id""", {"id": trusted_acp_observation_id})
                expected_observation = {
                    "owner_principal": context["owner"], "workspace_id": context["workspace"],
                    "actor_principal": "byq-product-agent-" + context["session"],
                    "session_id": context["session"], "trace_id": context["trace"],
                    "dsh_run_id": trusted_generation, "runtime_boot_id": trusted_boot_id,
                    "root_run_id": context["root"], "agent_run_id": value["agent_run_id"],
                    "task_id": value["task_id"], "action": value["action"],
                    "idempotency_key": value["idempotency_key"],
                    "request_sha256": value["request_sha256"], "input_sha256": value["input_sha256"],
                }
                if observation is None or any(observation.get(key) != expected
                        for key, expected in expected_observation.items()):
                    raise AgentConflict("ACP observation receipt does not match this exact domain call")
                binding = fetch_one(connection, """SELECT status,runtime_boot_id,agent_run_id
                    FROM agent_acp_native_agent_registrations WHERE root_run_id=:root
                      AND native_agent_session_id=:native_agent""",
                    {"root": context["root"], "native_agent": observation["native_agent_session_id"]})
                if (binding is None or binding["status"] != "bound"
                        or binding["runtime_boot_id"] != trusted_boot_id
                        or binding["agent_run_id"] != value["agent_run_id"]):
                    raise AgentConflict("ACP observation does not have a bound native AgentRun")
                proof = fetch_one(connection, """SELECT * FROM agent_domain_call_evidence
                    WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session
                      AND trace_id=:trace AND sequence=:sequence AND root_run_id=:root
                      AND agent_run_id=:agent_run_id AND task_id=:task_id AND action=:action
                      AND idempotency_key=:idempotency_key AND request_sha256=:request_sha256
                      AND input_sha256=:input_sha256 AND generation=:generation""",
                    {**scope, "generation": trusted_generation, "sequence": observation["evidence_sequence"]})
                if proof is None:
                    raise AgentConflict("ACP observation evidence row is missing or changed")
            else:
                if trusted_acp_observation_id is not None:
                    raise AgentConflict("ACP observation receipt cannot authorize a non-ACP root")
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
        except DomainValidationRejected as error:
            # The failed artifact transaction has rolled back. Persist only a
            # closed error; raw Python/schema diagnostics never enter the ledger.
            with self._transaction() as connection:
                self._lifecycle_lock(connection, "runtime-authority:current")
                self._lifecycle_lock(connection, "root:" + context["root"])
                authority = self._current_authority_row(connection)
                root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root",
                                 {"root": context["root"]})
                if authority is not None and (
                        context.get("boot_id") != authority["boot_id"] or root is None
                        or root.get("authority_status") != "active"
                        or root.get("authority_boot_id") != authority["boot_id"]):
                    # If rotation won after the failed artifact transaction
                    # rolled back, retain the in-flight claim as unknown.
                    return {"state": "unknown"}
                row = fetch_one(connection, "SELECT * FROM agent_domain_call_claims WHERE claim_id=:id FOR UPDATE", {"id": claim["claim_id"]})
                if row is None or row["status"] != "executing":
                    raise AgentConflict("domain call claim cannot be completed twice")
                bucket = fetch_one(connection, """SELECT repair_used FROM agent_domain_correction_buckets
                    WHERE root_run_id=:root AND task_id=:task AND action=:action""",
                    {"root": row["root_run_id"], "task": row["task_id"], "action": row["action"]})
                result = {"state": "correctable_failure",
                    "reason": "correction_failed" if bucket["repair_used"] else "domain_validation_failed"}
                if error.validation is not None:
                    result["validation"] = error.validation
                execute(connection, """UPDATE agent_domain_correction_buckets SET failed_input_sha256=COALESCE(failed_input_sha256,:input)
                    WHERE root_run_id=:root AND task_id=:task AND action=:action""",
                    {"root": row["root_run_id"], "task": row["task_id"], "action": row["action"], "input": row["input_sha256"]})
                execute(connection, "UPDATE agent_domain_call_claims SET status='correctable_failure',result_json=CAST(:result AS jsonb) WHERE claim_id=:id",
                        {"id": claim["claim_id"], "result": json.dumps(result)})
            return result

    def consume_domain_call_evidence(self, value, *, trusted_owner, trusted_workspace,
                                    trusted_session_id, trusted_trace_id, conversation_id,
                                    trusted_boot_id=None):
        from .agent_research import AgentConflict, AgentUnauthorized, ROLE_BY_ID, _principal, _trace

        evidence = validate_call_evidence(value)
        receipt = call_evidence_receipt(evidence)
        if trusted_boot_id is not None:
            from .agent_research import _runtime_boot_id
            trusted_boot_id = _runtime_boot_id(trusted_boot_id)
        context = {"owner": _principal(trusted_owner, field="owner_principal"),
                   "workspace": _trace(trusted_workspace, field="workspace_id"),
                   "session": _trace(trusted_session_id, field="session_id"),
                   "trace": _trace(trusted_trace_id, field="trace_id"),
                   "sequence": evidence["sequence"], "root": evidence["root_run_id"],
                   "boot_id": trusted_boot_id}
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
            # Evidence is an inert observation. A late exact proof may establish
            # an existing claim's receipt after terminal/revocation; new claims
            # and execution still require active authority below.
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
