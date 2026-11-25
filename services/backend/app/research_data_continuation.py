"""Durable, one-shot continuation after conversation-scoped market preparation.

The store binds a verified data-demand event to the exact ACP root and user
message that requested it. It never dispatches work; Gateway and Runtime own
the continuation transport and lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from sqlalchemy.exc import SQLAlchemyError

from .data_demand import DataDemandConflict, DataDemandNotFound, DataDemandPersistenceError
from .db import PgStoreMixin, execute, fetch_one


_ROOT = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTINUATION = re.compile(r"^rdcontinuation_[0-9a-f]{32}$")


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _message_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ResearchDataContinuationStore(PgStoreMixin):
    """Persist a verified data-ready event and its single dispatch binding."""

    SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS research_data_continuations (
            continuation_id TEXT PRIMARY KEY CHECK (continuation_id ~ '^rdcontinuation_[0-9a-f]{32}$'),
            demand_id TEXT NOT NULL REFERENCES data_demands(demand_id),
            owner_principal TEXT NOT NULL,
            workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
            conversation_id TEXT NOT NULL REFERENCES product_conversations(conversation_id),
            session_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            source_root_id TEXT NOT NULL REFERENCES agent_runtime_turns(root_run_id),
            source_boot_id TEXT NOT NULL,
            source_observation_id TEXT NOT NULL REFERENCES agent_acp_tool_ingress_observations(mcp_request_id),
            source_arguments_sha256 TEXT NOT NULL,
            source_message_id TEXT NOT NULL REFERENCES product_conversation_messages(message_id),
            source_message_sequence BIGINT NOT NULL,
            source_message_sha256 TEXT NOT NULL,
            scope_json JSONB NOT NULL,
            requirements_json JSONB NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('waiting','dispatching','bound','succeeded','failed','cancelled')),
            reason TEXT NOT NULL DEFAULT 'awaiting_verified_data',
            ready_input_sha256 TEXT,
            dispatch_boot_id TEXT,
            dispatch_content_sha256 TEXT,
            dispatch_root_id TEXT UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            claimed_at TIMESTAMPTZ,
            bound_at TIMESTAMPTZ,
            UNIQUE(demand_id,source_message_id)
        )
        """,
        """CREATE INDEX IF NOT EXISTS research_data_continuations_waiting
            ON research_data_continuations(conversation_id,owner_principal,workspace_id,created_at)
            WHERE status='waiting'""",
        """CREATE INDEX IF NOT EXISTS research_data_continuations_demand
            ON research_data_continuations(demand_id,owner_principal,workspace_id)""",
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise DataDemandPersistenceError("research data continuation storage is unavailable") from error

    @staticmethod
    def _context_values(context: dict[str, str]) -> tuple[str, str, str, str]:
        values = tuple(context.get(field) for field in (
            "owner_principal", "workspace_id", "session_id", "trace_id",
        ))
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("exact research continuation context required")
        return values  # type: ignore[return-value]

    @staticmethod
    def _require_active_conversation(connection, conversation_id: str, context: dict[str, str], *, lock=True):
        owner, workspace, session, trace = ResearchDataContinuationStore._context_values(context)
        lock_clause = "FOR UPDATE OF c FOR SHARE OF u,w,m" if lock else "FOR SHARE OF c,u,w,m"
        row = fetch_one(connection, f"""SELECT c.conversation_id,c.runtime_session_id,c.trace_id,
                c.message_count,c.status,u.status AS user_status,w.status AS workspace_status,
                m.status AS membership_status
            FROM product_conversations c
            JOIN users u ON u.username=c.owner_principal
            JOIN workspaces w ON w.workspace_id=c.workspace_id AND w.owner_user_id=u.user_id
            JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
            WHERE c.conversation_id=:conversation AND c.owner_principal=:owner AND c.workspace_id=:workspace
              AND c.runtime_session_id=:session AND c.trace_id=:trace
              AND c.status='active' AND u.status='active' AND w.status='active'
              AND m.status='active' AND m.role='owner' {lock_clause}""", {
            "conversation": conversation_id, "owner": owner, "workspace": workspace,
            "session": session, "trace": trace,
        })
        if row is None:
            raise DataDemandNotFound("research conversation is unavailable")
        return row

    @staticmethod
    def _auto_continue_enabled(connection, owner: str) -> bool:
        row = fetch_one(connection, """SELECT o.user_id,o.options_json FROM users u
            LEFT JOIN user_agent_execution_options o ON o.user_id=u.user_id
            WHERE u.username=:owner AND u.status='active'""", {"owner": owner})
        if row is None or row.get("user_id") is None:
            return row is not None
        options = row.get("options_json")
        if not isinstance(options, dict):
            return False
        value = options.get("auto_continue", True)
        return type(value) is bool and value

    @staticmethod
    def _newer_user_message(connection, row) -> bool:
        newer = fetch_one(connection, """SELECT message_id FROM product_conversation_messages
            WHERE conversation_id=:conversation AND owner_principal=:owner AND role='user'
              AND sequence>:sequence ORDER BY sequence DESC LIMIT 1""", {
            "conversation": row["conversation_id"], "owner": row["owner_principal"],
            "sequence": row["source_message_sequence"],
        })
        return newer is not None

    @staticmethod
    def _instruction(scope: dict[str, object]) -> str:
        public_scope = {key: scope[key] for key in (
            "symbols", "start_date", "end_date", "data_requirements",
        ) if key in scope}
        serialized = json.dumps(public_scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content = (
            "继续回答本会话中原用户问题。原问题与此前对话已在上下文中，不要替换或扩展问题。"
            f"数据中心已持久化核验以下范围：{serialized}。请在给出研究结论前，通过只读工具重新读取该范围内需要的日线、估值和财务数据，"
            "通过本轮 AgentRun 授权精确工具名；如需填写资源类型和标识，使用 market_data 和单个证券代码。"
            "读单日涨跌幅时，优先读取该日行情记录中的昨收字段。"
            "核对数据日期、指标口径、来源和缺项，再完成研究。不得发起补数、扩大范围、修改业务资产或交易。"
            "如复读后仍缺字段，明确说明缺口及其对结论的影响，不要补造数据。"
        )
        if len(content.encode("utf-8")) > 4096:
            raise DataDemandConflict("verified research scope exceeds continuation prompt bounds")
        return content

    @staticmethod
    def _assess_ready(row, readiness_store) -> str | None:
        scope = row.get("scope_json")
        requirements = row.get("requirements_json")
        if (not isinstance(scope, dict) or scope.get("kind") != "conversation_research"
                or not isinstance(requirements, list) or not 1 <= len(requirements) <= 16):
            return None
        if (not isinstance(scope.get("symbols"), list) or not scope["symbols"]
                or not isinstance(scope.get("start_date"), str)
                or not isinstance(scope.get("end_date"), str)
                or not isinstance(scope.get("data_requirements", {}), dict)):
            return None
        identities: list[dict[str, str]] = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                return None
            if (requirement.get("symbols") != scope["symbols"]
                    or requirement.get("start_date") != scope["start_date"].replace("-", "")
                    or requirement.get("end_date") != scope["end_date"].replace("-", "")
                    or requirement.get("declared", {}) != scope.get("data_requirements", {})):
                return None
            assessment = readiness_store.assess(dict(requirement))
            digest = assessment.get("ready_input_sha256")
            if (assessment.get("state") != "ready" or not assessment.get("required_session_count")
                    or not assessment.get("required_cell_count") or not isinstance(digest, str)
                    or _SHA256.fullmatch(digest) is None):
                return None
            identities.append({
                "requirement_sha256": str(requirement.get("requirement_sha256", "")),
                "ready_input_sha256": digest,
            })
        return identities[0]["ready_input_sha256"] if len(identities) == 1 else _canonical_sha256(identities)

    @classmethod
    def _source_root_is_settled(cls, connection, row) -> bool:
        if not cls._source_ingress_is_settled(row):
            return False
        root = fetch_one(connection, """SELECT 1 AS settled FROM agent_runtime_turns
            WHERE root_run_id=:root AND status='completed' AND authority_status='closed'
              AND authority_boot_id=:boot AND terminal_sequence IS NOT NULL
              AND terminal_event_sha256 IS NOT NULL AND terminal_unknown_claim_count=0
              AND terminal_acp_ingress_sha256 IS NOT NULL AND terminal_acp_ingress_sequence>=:sequence""", {
            "root": row["source_root_id"], "boot": row["source_boot_id"], "sequence": row["observation_sequence"],
        })
        return root is not None

    @staticmethod
    def _source_ingress_is_settled(row) -> bool:
        settlement = row.get("observation_settlement")
        return (row.get("observation_status") == "settled" and isinstance(settlement, dict)
                and settlement.get("outcome") == "settled"
                and settlement.get("mcp_request_id") == row.get("source_observation_id")
                and settlement.get("root_run_id") == row.get("source_root_id")
                and settlement.get("runtime_boot_id") == row.get("source_boot_id")
                and settlement.get("tool_name") == "byq_data_demand_create"
                and settlement.get("sequence") == row.get("observation_sequence"))

    @staticmethod
    def _public(row, *, instruction=False) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": "research-data-continuation.v1",
            "continuation_id": row["continuation_id"], "status": row["status"],
            "reason": row["reason"], "demand_id": row["demand_id"],
            "conversation_id": row["conversation_id"], "owner_principal": row["owner_principal"],
            "workspace_id": row["workspace_id"], "session_id": row["session_id"],
            "trace_id": row["trace_id"], "source_root_id": row["source_root_id"],
            "source_message_id": row["source_message_id"],
            "source_message_sha256": row["source_message_sha256"],
            "ready_input_sha256": row.get("ready_input_sha256"),
            "scope": dict(row.get("scope_json") or {}),
            "scope_json": dict(row.get("scope_json") or {}),
            "requirements": list(row.get("requirements_json") or []),
            "content_sha256": row.get("dispatch_content_sha256"),
        }
        if instruction:
            result["instruction"] = ResearchDataContinuationStore._instruction(
                dict(row.get("scope_json") or {}),
            )
        return result

    def watch(self, connection, demand_id: str, acp_scope: dict[str, str],
              observation_id: str, arguments_sha256: str) -> dict[str, object]:
        """Atomically attach the exact root observation to a conversation demand."""
        if (not isinstance(demand_id, str) or not demand_id
                or not isinstance(observation_id, str) or _ROOT.fullmatch(observation_id) is None
                or not isinstance(arguments_sha256, str) or _SHA256.fullmatch(arguments_sha256) is None
                or not isinstance(acp_scope, dict)):
            raise ValueError("exact data preparation observation required")
        owner, workspace, actor = (acp_scope.get("owner"), acp_scope.get("workspace"), acp_scope.get("actor"))
        session, trace = acp_scope.get("session"), acp_scope.get("trace")
        root_id, boot_id = acp_scope.get("root"), acp_scope.get("boot_id")
        if (any(not isinstance(value, str) or not value for value in (owner, workspace, actor, session, trace))
                or actor != "byq-product-agent-" + session
                or not isinstance(root_id, str) or _ROOT.fullmatch(root_id) is None
                or not isinstance(boot_id, str) or _ROOT.fullmatch(boot_id) is None):
            raise ValueError("exact trusted ACP data preparation scope required")
        params = {"id": demand_id, "owner": owner, "workspace": workspace, "session": session, "trace": trace}
        demand = fetch_one(connection, """SELECT * FROM data_demands WHERE demand_id=:id FOR SHARE""", params)
        if (demand is None or demand["owner_principal"] != owner or demand["workspace_id"] != workspace
                or demand["session_id"] != session or demand["trace_id"] != trace
                or not isinstance(demand.get("scope_json"), dict)
                or demand["scope_json"].get("kind") != "conversation_research"):
            raise DataDemandConflict("data demand does not match the exact research conversation")
        conversation = fetch_one(connection, """SELECT conversation_id FROM product_conversations
            WHERE owner_principal=:owner AND workspace_id=:workspace AND runtime_session_id=:session
              AND trace_id=:trace AND status='active' FOR SHARE""", params)
        if conversation is None:
            raise DataDemandNotFound("research conversation is unavailable")
        self._require_active_conversation(connection, conversation["conversation_id"], {
            "owner_principal": owner, "workspace_id": workspace, "session_id": session, "trace_id": trace,
        }, lock=False)
        authority = fetch_one(connection, "SELECT boot_id FROM agent_runtime_authority_current WHERE authority_key='current'")
        root = fetch_one(connection, """SELECT * FROM agent_runtime_turns WHERE root_run_id=:root FOR SHARE""",
                         {"root": root_id})
        if (authority is None or authority["boot_id"] != boot_id or root is None
                or (root["owner_principal"], root["workspace_id"], root["session_id"], root["trace_id"],
                    root["status"], root["authority_status"], root["authority_boot_id"])
                   != (owner, workspace, session, trace, "active", "active", boot_id)):
            raise DataDemandConflict("source Agent root is not active under current runtime authority")
        ingress = fetch_one(connection, """SELECT * FROM agent_acp_tool_ingress_observations
            WHERE mcp_request_id=:observation FOR SHARE""", {"observation": observation_id})
        if (ingress is None or (ingress["owner_principal"], ingress["workspace_id"], ingress["actor_principal"],
                ingress["session_id"], ingress["trace_id"], ingress["root_run_id"], ingress["runtime_boot_id"],
                ingress["origin"], ingress["depth"], ingress["tool_name"], ingress["arguments_sha256"])
                != (owner, workspace, actor, session, trace, root_id, boot_id, "root", 0,
                    "byq_data_demand_create", arguments_sha256)
                or ingress["status"] not in {"pending", "settled"}):
            raise DataDemandConflict("data preparation does not match its exact root ingress")
        if not self._auto_continue_enabled(connection, owner):
            return None
        message = fetch_one(connection, """SELECT m.message_id,m.sequence,m.content FROM product_conversation_messages m
            JOIN product_conversations c ON c.conversation_id=m.conversation_id
            JOIN agent_runtime_turns t ON t.root_run_id=:root
            WHERE m.conversation_id=:conversation AND m.owner_principal=:owner AND m.role='user'
              AND m.created_at<=t.created_at ORDER BY m.created_at DESC,m.sequence DESC LIMIT 1""", {
            "root": root_id, "conversation": conversation["conversation_id"], "owner": owner,
        })
        if message is None or not isinstance(message.get("content"), str) or not message["content"].strip():
            return None
        existing = fetch_one(connection, """SELECT continuation_id,status,source_root_id FROM research_data_continuations
            WHERE demand_id=:demand AND source_message_id=:message FOR UPDATE""",
            {"demand": demand_id, "message": message["message_id"]})
        if existing is not None:
            if existing["source_root_id"] != root_id:
                return None
            return {"continuation_id": existing["continuation_id"], "status": existing["status"]}
        continuation_id = "rdcontinuation_" + uuid.uuid4().hex
        execute(connection, """INSERT INTO research_data_continuations
            (continuation_id,demand_id,owner_principal,workspace_id,conversation_id,session_id,trace_id,
             source_root_id,source_boot_id,source_observation_id,source_arguments_sha256,
             source_message_id,source_message_sequence,source_message_sha256,scope_json,requirements_json,status,reason)
            VALUES (:continuation,:demand,:owner,:workspace,:conversation,:session,:trace,:root,:boot,:observation,
             :arguments,:message,:sequence,:message_sha,:scope,:requirements,'waiting','awaiting_verified_data')""", {
            "continuation": continuation_id, "demand": demand_id, "owner": owner, "workspace": workspace,
            "conversation": conversation["conversation_id"], "session": session, "trace": trace,
            "root": root_id, "boot": boot_id, "observation": observation_id, "arguments": arguments_sha256,
            "message": message["message_id"], "sequence": message["sequence"],
            "message_sha": _message_sha256(message["content"]), "scope": demand["scope_json"],
            "requirements": demand["requirements_json"],
        })
        return {"continuation_id": continuation_id, "status": "waiting"}

    def has_waiting(self, conversation_id: str, *, owner: str, workspace: str) -> bool:
        row = self._fetch_one("""SELECT 1 AS present FROM research_data_continuations r
            JOIN product_conversations c ON c.conversation_id=r.conversation_id
            JOIN users u ON u.username=r.owner_principal
            JOIN workspaces w ON w.workspace_id=r.workspace_id AND w.owner_user_id=u.user_id
            JOIN workspace_memberships m ON m.workspace_id=w.workspace_id AND m.user_id=u.user_id
            WHERE r.conversation_id=:conversation AND r.owner_principal=:owner AND r.workspace_id=:workspace
              AND r.status='waiting' AND c.status='active' AND u.status='active' AND w.status='active'
              AND m.status='active' AND m.role='owner' LIMIT 1""", {
            "conversation": conversation_id, "owner": owner, "workspace": workspace,
        })
        return row is not None

    def _candidate(self, connection, conversation_id: str, continuation_id: str | None,
                   context: dict[str, str]):
        params = {"conversation": conversation_id, "owner": context["owner_principal"],
                  "workspace": context["workspace_id"], "session": context["session_id"],
                  "trace": context["trace_id"], "id": continuation_id}
        suffix = " AND r.continuation_id=:id" if continuation_id is not None else " AND r.status='waiting'"
        return fetch_one(connection, """SELECT r.*,i.sequence AS observation_sequence,
                i.status AS observation_status,i.settlement_json AS observation_settlement
            FROM research_data_continuations r
            JOIN agent_acp_tool_ingress_observations i ON i.mcp_request_id=r.source_observation_id
            WHERE r.conversation_id=:conversation AND r.owner_principal=:owner AND r.workspace_id=:workspace
              AND r.session_id=:session AND r.trace_id=:trace""" + suffix + " ORDER BY r.created_at,r.continuation_id LIMIT 1 FOR UPDATE OF r", params)

    def _cancel_row(self, connection, row, reason: str) -> None:
        execute(connection, """UPDATE research_data_continuations SET status='cancelled',reason=:reason,updated_at=now()
            WHERE continuation_id=:id AND status IN ('waiting','dispatching') AND dispatch_root_id IS NULL""", {
            "reason": reason, "id": row["continuation_id"],
        })

    def peek(self, conversation_id: str, context: dict[str, str], readiness_store) -> dict[str, object] | None:
        with self._transaction() as connection:
            self._require_active_conversation(connection, conversation_id, context)
            row = self._candidate(connection, conversation_id, None, context)
            if row is None:
                return None
            if not self._auto_continue_enabled(connection, context["owner_principal"]):
                self._cancel_row(connection, row, "auto_continue_disabled")
                return None
            if self._newer_user_message(connection, row):
                self._cancel_row(connection, row, "superseded_by_new_user_message")
                return None
            if not self._source_root_is_settled(connection, row):
                source = fetch_one(connection, "SELECT status,authority_status FROM agent_runtime_turns WHERE root_run_id=:root",
                                   {"root": row["source_root_id"]})
                if source is not None and (source["status"] != "active" or source["authority_status"] != "active"):
                    self._cancel_row(connection, row, "source_root_not_settled")
                return None
            demand = fetch_one(connection, """SELECT scope_json,requirements_json,status FROM data_demands
                WHERE demand_id=:demand AND owner_principal=:owner AND workspace_id=:workspace
                  AND session_id=:session""", {"demand": row["demand_id"], "owner": context["owner_principal"],
                "workspace": context["workspace_id"], "session": context["session_id"]})
            if demand is None or demand["status"] == "cancelled":
                self._cancel_row(connection, row, "data_preparation_cancelled")
                return None
            if demand["status"] in {"failed", "partial"}:
                execute(connection, """UPDATE research_data_continuations SET status='failed',reason=:reason,
                    updated_at=now() WHERE continuation_id=:id AND status='waiting'""", {
                    "reason": "data_preparation_" + str(demand["status"]), "id": row["continuation_id"],
                })
                return None
            if demand["scope_json"] != row["scope_json"] or demand["requirements_json"] != row["requirements_json"]:
                self._cancel_row(connection, row, "frozen_data_scope_changed")
                return None
            if demand["status"] != "ready":
                return None
            ready_input_sha256 = self._assess_ready(row, readiness_store)
            if ready_input_sha256 is None:
                return None
            if row.get("ready_input_sha256") != ready_input_sha256:
                execute(connection, """UPDATE research_data_continuations SET ready_input_sha256=:hash,
                    reason='verified_data_ready',updated_at=now() WHERE continuation_id=:id AND status='waiting'""", {
                    "hash": ready_input_sha256, "id": row["continuation_id"],
                })
                row["ready_input_sha256"] = ready_input_sha256
                row["reason"] = "verified_data_ready"
            return self._public(row)

    def claim(self, conversation_id: str, continuation_id: str, context: dict[str, str], readiness_store,
              *, boot_id: str | None = None) -> dict[str, object] | None:
        if not isinstance(continuation_id, str) or _CONTINUATION.fullmatch(continuation_id) is None:
            raise ValueError("continuation_id is invalid")
        if not isinstance(boot_id, str) or _ROOT.fullmatch(boot_id) is None:
            raise ValueError("current runtime boot is required")
        with self._transaction() as connection:
            self._require_active_conversation(connection, conversation_id, context)
            authority = fetch_one(connection, "SELECT boot_id FROM agent_runtime_authority_current WHERE authority_key='current'")
            if authority is None or authority["boot_id"] != boot_id:
                return None
            row = self._candidate(connection, conversation_id, continuation_id, context)
            if (row is None or row["status"] != "waiting" or row["dispatch_root_id"] is not None):
                return None
            if not self._auto_continue_enabled(connection, context["owner_principal"]):
                self._cancel_row(connection, row, "auto_continue_disabled")
                return None
            if self._newer_user_message(connection, row):
                self._cancel_row(connection, row, "superseded_by_new_user_message")
                return None
            if not self._source_root_is_settled(connection, row):
                return None
            demand = fetch_one(connection, """SELECT scope_json,requirements_json,status FROM data_demands
                WHERE demand_id=:demand AND owner_principal=:owner AND workspace_id=:workspace
                  AND session_id=:session FOR SHARE""", {"demand": row["demand_id"], "owner": context["owner_principal"],
                "workspace": context["workspace_id"], "session": context["session_id"]})
            if (demand is None or demand["status"] == "cancelled"
                    or demand["scope_json"] != row["scope_json"]
                    or demand["requirements_json"] != row["requirements_json"]):
                self._cancel_row(connection, row, "data_preparation_cancelled")
                return None
            if demand["status"] in {"failed", "partial"}:
                execute(connection, """UPDATE research_data_continuations SET status='failed',reason=:reason,
                    updated_at=now() WHERE continuation_id=:id AND status='waiting'""", {
                    "reason": "data_preparation_" + str(demand["status"]), "id": continuation_id,
                })
                return None
            if demand["status"] != "ready":
                return None
            ready_input_sha256 = self._assess_ready(row, readiness_store)
            if ready_input_sha256 is None:
                return None
            instruction = self._instruction(dict(row["scope_json"]))
            content_sha256 = _message_sha256(instruction)
            updated = fetch_one(connection, """UPDATE research_data_continuations SET status='dispatching',
                reason='dispatch_claimed',ready_input_sha256=:ready,dispatch_boot_id=:boot,
                dispatch_content_sha256=:content,claimed_at=now(),updated_at=now()
                WHERE continuation_id=:id AND status='waiting' AND dispatch_root_id IS NULL RETURNING *""", {
                "ready": ready_input_sha256, "boot": boot_id, "content": content_sha256,
                "id": continuation_id,
            })
            if updated is None:
                return None
            return {**self._public(updated, instruction=True), "dispatch_boot_id": boot_id}

    def bind(self, continuation_id: str, payload: dict[str, str]) -> dict[str, str]:
        if not isinstance(continuation_id, str) or _CONTINUATION.fullmatch(continuation_id) is None:
            raise ValueError("continuation_id is invalid")
        if not isinstance(payload, dict) or set(payload) != {
                "owner_principal", "workspace_id", "session_id", "trace_id", "root_run_id", "boot_id", "content_sha256"}:
            raise ValueError("exact runtime binding is required")
        if (not isinstance(payload.get("root_run_id"), str) or _ROOT.fullmatch(payload["root_run_id"]) is None
                or not isinstance(payload.get("boot_id"), str) or _ROOT.fullmatch(payload["boot_id"]) is None
                or not isinstance(payload.get("content_sha256"), str) or _SHA256.fullmatch(payload["content_sha256"]) is None):
            raise ValueError("runtime binding identity is invalid")
        context = {key: payload[key] for key in ("owner_principal", "workspace_id", "session_id", "trace_id")}
        with self._transaction() as connection:
            source = fetch_one(connection, """SELECT conversation_id FROM research_data_continuations
                WHERE continuation_id=:id AND owner_principal=:owner AND workspace_id=:workspace
                  AND session_id=:session AND trace_id=:trace""", {
                "id": continuation_id, "owner": context["owner_principal"], "workspace": context["workspace_id"],
                "session": context["session_id"], "trace": context["trace_id"],
            })
            if source is None:
                raise DataDemandNotFound("research continuation is unavailable")
            conversation_id = source["conversation_id"]
            self._require_active_conversation(connection, conversation_id, context)
            row = self._candidate(connection, conversation_id, continuation_id, context)
            if row is None:
                raise DataDemandNotFound("research continuation is unavailable")
            if self._newer_user_message(connection, row):
                raise DataDemandConflict("research continuation was superseded")
            if not self._auto_continue_enabled(connection, context["owner_principal"]):
                raise DataDemandConflict("automatic continuation is disabled")
            existing = row.get("dispatch_root_id")
            if existing is not None:
                if (existing, row.get("dispatch_boot_id"), row.get("dispatch_content_sha256")) == (
                        payload["root_run_id"], payload["boot_id"], payload["content_sha256"]):
                    return {"continuation_id": continuation_id, "root_run_id": existing}
                raise DataDemandConflict("research continuation is already bound to another runtime root")
            if (row["status"] != "dispatching" or row.get("dispatch_boot_id") != payload["boot_id"]
                    or row.get("dispatch_content_sha256") != payload["content_sha256"]):
                raise DataDemandConflict("runtime binding differs from the claimed continuation")
            authority = fetch_one(connection, "SELECT boot_id FROM agent_runtime_authority_current WHERE authority_key='current'")
            root = fetch_one(connection, "SELECT 1 FROM agent_runtime_turns WHERE root_run_id=:root",
                             {"root": payload["root_run_id"]})
            if (authority is None or authority["boot_id"] != payload["boot_id"] or root is not None
                    or not self._source_root_is_settled(connection, row)):
                raise DataDemandConflict("dispatch requires a fresh root under current runtime authority")
            updated = fetch_one(connection, """UPDATE research_data_continuations SET status='bound',reason='bound',
                dispatch_root_id=:root,bound_at=now(),updated_at=now()
                WHERE continuation_id=:id AND status='dispatching' AND dispatch_root_id IS NULL RETURNING *""", {
                "root": payload["root_run_id"], "id": continuation_id,
            })
            if updated is None:
                raise DataDemandConflict("research continuation binding lost its one-shot claim")
            return {"continuation_id": continuation_id, "root_run_id": payload["root_run_id"]}

    def reject_unbound(self, conversation_id: str, continuation_id: str, context: dict[str, str],
                       *, boot_id: str) -> bool:
        if _CONTINUATION.fullmatch(continuation_id) is None or _ROOT.fullmatch(boot_id) is None:
            raise ValueError("exact dispatch identity required")
        with self._transaction() as connection:
            self._require_active_conversation(connection, conversation_id, context)
            row = self._candidate(connection, conversation_id, continuation_id, context)
            if (row is None or row["status"] != "dispatching" or row["dispatch_root_id"] is not None
                    or row["dispatch_boot_id"] != boot_id):
                return False
            self._finish(connection, row, "failed", "runtime_rejected_before_acceptance")
            return True

    def cancel(self, conversation_id: str, context: dict[str, str], *, demand_id: str | None = None) -> bool:
        with self._transaction() as connection:
            self._require_active_conversation(connection, conversation_id, context)
            params: dict[str, object] = {"conversation": conversation_id,
                "owner": context["owner_principal"], "workspace": context["workspace_id"]}
            demand_clause = ""
            if demand_id is not None:
                demand_clause = " AND demand_id=:demand"
                params["demand"] = demand_id
            rows = execute(connection, """UPDATE research_data_continuations SET status='cancelled',
                reason='cancelled_by_user',updated_at=now() WHERE conversation_id=:conversation
                AND owner_principal=:owner AND workspace_id=:workspace""" + demand_clause + """
                AND status IN ('waiting','dispatching') AND dispatch_root_id IS NULL
                RETURNING continuation_id""", params)
            return bool(rows)

    @staticmethod
    def _finish(connection, row, status: str, reason: str):
        return fetch_one(connection, """UPDATE research_data_continuations SET status=:status,
            reason=:reason,updated_at=now() WHERE continuation_id=:id AND status=:previous RETURNING *""", {
            "status": status, "reason": reason, "id": row["continuation_id"], "previous": row["status"],
        }) or row

    def _bound_outcome(self, connection, row):
        terminal = fetch_one(connection, """SELECT status,terminal_sequence FROM agent_runtime_turns
            WHERE root_run_id=:root AND owner_principal=:owner AND workspace_id=:workspace
              AND session_id=:session AND trace_id=:trace AND authority_status='closed'
              AND terminal_sequence IS NOT NULL AND terminal_event_sha256 IS NOT NULL
              AND terminal_unknown_claim_count=0""", {
            "root": row["dispatch_root_id"], "owner": row["owner_principal"], "workspace": row["workspace_id"],
            "session": row["session_id"], "trace": row["trace_id"],
        })
        if terminal is None:
            return row
        outcome = terminal["status"]
        if outcome in {"failed", "interrupted", "cancelled"}:
            return self._finish(connection, row, "cancelled" if outcome == "cancelled" else "failed",
                                "runtime_" + outcome)
        if outcome != "completed":
            return row
        read = fetch_one(connection, """SELECT 1 AS present FROM agent_acp_tool_ingress_observations
            WHERE root_run_id=:root AND origin='root' AND status='settled'
              AND settlement_json->>'outcome'='settled'
              AND tool_name IN ('byq_market_daily','byq_market_valuation','byq_market_fundamentals') LIMIT 1""",
            {"root": row["dispatch_root_id"]})
        if read is None:
            return self._finish(connection, row, "failed", "no_verified_market_read")
        answer = fetch_one(connection, """SELECT 1 AS present FROM product_conversation_messages m
            WHERE m.conversation_id=:conversation AND m.owner_principal=:owner AND m.workspace_id=:workspace
              AND m.role='assistant' AND m.workflow_sequence<:terminal
              AND m.workflow_sequence>(SELECT min(a.sequence) FROM agent_runtime_receipts a
                WHERE a.owner_principal=:owner AND a.workspace_id=:workspace AND a.session_id=:session
                  AND a.trace_id=:trace AND a.receipt_json->>'root_run_id'=:root)
            LIMIT 1""", {
            "conversation": row["conversation_id"], "owner": row["owner_principal"], "workspace": row["workspace_id"],
            "session": row["session_id"], "trace": row["trace_id"], "root": row["dispatch_root_id"],
            "terminal": terminal["terminal_sequence"],
        })
        return self._finish(connection, row, "succeeded", "verified_answer_persisted") if answer else row

    def status_for_demand(self, demand_id: str, context: dict[str, str]) -> dict[str, object] | None:
        owner, workspace, session, trace = self._context_values(context)
        params = {"demand": demand_id, "owner": owner, "workspace": workspace, "session": session, "trace": trace}
        with self._transaction() as connection:
            identity = fetch_one(connection, """SELECT conversation_id FROM research_data_continuations
                WHERE demand_id=:demand AND owner_principal=:owner AND workspace_id=:workspace
                  AND session_id=:session AND trace_id=:trace LIMIT 1""", params)
            if identity is None:
                return None
            self._require_active_conversation(connection, identity["conversation_id"], context)
            row = fetch_one(connection, """SELECT r.*,d.status AS demand_status FROM research_data_continuations r
                JOIN data_demands d ON d.demand_id=r.demand_id
                WHERE r.demand_id=:demand AND r.owner_principal=:owner AND r.workspace_id=:workspace
                  AND r.session_id=:session AND r.trace_id=:trace
                ORDER BY r.source_message_sequence DESC LIMIT 1 FOR UPDATE OF r""", params)
            if row is None:
                return None
            if row["status"] in {"waiting", "dispatching"}:
                if self._newer_user_message(connection, row):
                    row = self._finish(connection, row, "cancelled", "superseded_by_new_user_message")
                elif not self._auto_continue_enabled(connection, owner):
                    row = self._finish(connection, row, "cancelled", "auto_continue_disabled")
                elif row["status"] == "waiting" and row["demand_status"] in {"failed", "partial", "cancelled"}:
                    row = self._finish(connection, row, "failed", "data_preparation_not_ready")
            if row["status"] == "bound":
                row = self._bound_outcome(connection, row)
            return {"status": row["status"]}
