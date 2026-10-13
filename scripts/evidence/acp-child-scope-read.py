#!/usr/bin/env python3
"""Build and validate one bounded, read-only ACP child-scope projection.

Input to the CLI is strict JSON on stdin: {"mode": "preflight"|"root_child",
"scope": {the exact Product scope fields plus actor_principal}}. It emits only
the parameter-quoted SELECT statement; callers execute it through the existing
read-only PostgreSQL command boundary and pass its JSON result to
validate_projection().
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "byq-acp-child-scope-read.v1"
SCOPE_KEYS = frozenset({
    "workspace_id", "owner_principal", "session_id", "trace_id", "root_run_id",
    "runtime_boot_id", "generation_id", "cwd_leaf", "actor_principal",
})
MODES = frozenset({"preflight", "root_child"})
MAX_REGISTRATIONS = 2
MAX_INGRESS = 256
MAX_AUDITS = 512
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class ScopeReadError(ValueError):
    """A scope or bounded projection failed its closed contract."""


def _reject_constant(value: str) -> None:
    raise ScopeReadError("json_constant_invalid")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScopeReadError("json_duplicate_key")
        result[key] = value
    return result


def _strict_json(raw: str | bytes) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except ScopeReadError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ScopeReadError("json_invalid") from exc


def _validated_scope(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != SCOPE_KEYS:
        raise ScopeReadError("scope_fields_invalid")
    product_scope = {key: raw[key] for key in SCOPE_KEYS if key != "actor_principal"}
    try:
        from packages.contracts.acp_product_slot import validate_product_scope

        product_scope = validate_product_scope(product_scope)
    except Exception as exc:
        raise ScopeReadError("scope_invalid") from exc
    actor = raw["actor_principal"]
    if actor != f"byq-product-agent-{product_scope['session_id']}":
        raise ScopeReadError("actor_scope_invalid")
    return {**product_scope, "actor_principal": actor}


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_sql(raw_scope: object, mode: str) -> str:
    """Return one bounded read-only SQL statement for this exact scope."""
    scope = _validated_scope(raw_scope)
    if not isinstance(mode, str) or mode not in MODES:
        raise ScopeReadError("mode_invalid")
    q = {key: _quote(value) for key, value in scope.items()}
    return f"""BEGIN READ ONLY;
WITH root_candidates AS MATERIALIZED (
  SELECT root_run_id,owner_principal,workspace_id,session_id,trace_id,status,
         authority_status,authority_boot_id,terminal_sequence,terminal_event_sha256,
         terminal_acp_ingress_sequence,terminal_acp_ingress_sha256,
         terminal_unknown_claim_count,terminal_unknown_claims_sha256
  FROM agent_runtime_turns
  WHERE root_run_id={q['root_run_id']}
), root_scope AS MATERIALIZED (
  SELECT * FROM root_candidates
  WHERE owner_principal={q['owner_principal']} AND workspace_id={q['workspace_id']}
    AND session_id={q['session_id']} AND trace_id={q['trace_id']}
    AND authority_boot_id={q['runtime_boot_id']}
), reg_candidates AS MATERIALIZED (
  SELECT n.root_run_id,n.native_agent_session_id,n.native_root_session_id,
         n.native_parent_session_id,n.owner_principal,n.workspace_id,n.actor_principal,
         n.session_id,n.trace_id,n.dsh_run_id,n.runtime_boot_id,n.origin,n.depth,
         n.agent_run_id,n.parent_run_id,n.status AS registration_status
  FROM root_scope rs
  JOIN agent_acp_native_agent_registrations n ON n.root_run_id=rs.root_run_id
), reg_scope_candidates AS MATERIALIZED (
  SELECT * FROM reg_candidates
  WHERE owner_principal={q['owner_principal']} AND workspace_id={q['workspace_id']}
    AND actor_principal={q['actor_principal']} AND session_id={q['session_id']}
    AND trace_id={q['trace_id']} AND dsh_run_id={q['generation_id']}
    AND runtime_boot_id={q['runtime_boot_id']}
), reg_run_candidates AS MATERIALIZED (
  SELECT n.*,
         ar.run_id AS joined_run_id,ar.owner_principal AS run_owner,
         ar.actor_principal AS run_actor,ar.trace_id AS run_trace,
         ar.session_id AS run_session,ar.dsh_run_id AS run_generation,
         ar.root_run_id AS run_root,ar.parent_run_id AS run_parent,
         ar.authority_boot_id AS run_boot,ar.status AS run_status,
         ar.authority_status AS run_authority_status
  FROM reg_scope_candidates n
  LEFT JOIN agent_runs ar ON ar.run_id=n.agent_run_id
), reg_rows AS MATERIALIZED (
  SELECT * FROM reg_run_candidates
  WHERE joined_run_id=agent_run_id AND run_root=root_run_id
    AND run_owner={q['owner_principal']} AND run_actor={q['actor_principal']}
    AND run_session={q['session_id']} AND run_trace={q['trace_id']}
    AND run_generation={q['generation_id']} AND run_boot={q['runtime_boot_id']}
), ingress_candidates AS MATERIALIZED (
  SELECT i.mcp_request_id,i.root_run_id,i.owner_principal,i.workspace_id,
         i.actor_principal,i.session_id,i.trace_id,i.dsh_run_id,i.runtime_boot_id,
         i.native_root_session_id,i.native_agent_session_id,i.native_parent_session_id,
         i.origin,i.depth,i.agent_run_id,i.tool_name,i.arguments_sha256,i.sequence,
         i.event_sha256,i.status,
         i.settlement_json->>'outcome' AS settlement_outcome,
         COALESCE(i.settlement_json->>'settlement_sha256',
                  i.settlement_json->>'abort_sha256') AS settlement_sha256
  FROM root_scope rs
  JOIN agent_acp_tool_ingress_observations i ON i.root_run_id=rs.root_run_id
), ingress_rows AS MATERIALIZED (
  SELECT * FROM ingress_candidates
  WHERE owner_principal={q['owner_principal']} AND workspace_id={q['workspace_id']}
    AND actor_principal={q['actor_principal']} AND session_id={q['session_id']}
    AND trace_id={q['trace_id']} AND dsh_run_id={q['generation_id']}
    AND runtime_boot_id={q['runtime_boot_id']}
), audit_candidates AS MATERIALIZED (
  SELECT n.root_run_id,n.native_agent_session_id,a.audit_id,a.run_id,
         a.owner_principal,a.actor_principal,a.action,a.outcome,a.created_at
  FROM root_scope rs
  JOIN reg_candidates n ON n.root_run_id=rs.root_run_id
  JOIN agent_audit a ON a.run_id=n.agent_run_id
), audit_rows AS MATERIALIZED (
  SELECT c.* FROM audit_candidates c
  JOIN reg_rows n ON n.root_run_id=c.root_run_id AND n.agent_run_id=c.run_id
    AND n.native_agent_session_id=c.native_agent_session_id
  WHERE c.owner_principal={q['owner_principal']} AND c.actor_principal={q['actor_principal']}
), root_limited AS (
  SELECT * FROM root_scope LIMIT 2
), reg_limited AS (
  SELECT * FROM reg_rows ORDER BY origin,depth,native_agent_session_id LIMIT {MAX_REGISTRATIONS + 1}
), ingress_limited AS (
  SELECT * FROM ingress_rows ORDER BY sequence,mcp_request_id LIMIT {MAX_INGRESS + 1}
), audit_limited AS (
  SELECT * FROM audit_rows ORDER BY created_at,audit_id LIMIT {MAX_AUDITS + 1}
)
SELECT json_build_object(
  'schema_version',{_quote(SCHEMA)},'mode',{_quote(mode)},
  'foreign_mismatch_count',
    (SELECT count(*) FROM root_candidates) - (SELECT count(*) FROM root_scope)
    + (SELECT count(*) FROM reg_candidates) - (SELECT count(*) FROM reg_rows)
    + (SELECT count(*) FROM ingress_candidates) - (SELECT count(*) FROM ingress_rows)
    + (SELECT count(*) FROM audit_candidates) - (SELECT count(*) FROM audit_rows)
    + (SELECT count(*)-count(DISTINCT audit_id) FROM audit_candidates),
  'root_count',(SELECT count(*) FROM root_scope),
  'roots',COALESCE((SELECT json_agg(json_build_object(
    'root_run_id',root_run_id,'owner_principal',owner_principal,'workspace_id',workspace_id,
    'session_id',session_id,'trace_id',trace_id,'status',status,
    'authority_status',authority_status,'authority_boot_id',authority_boot_id,
    'terminal_sequence',terminal_sequence,'terminal_event_sha256',terminal_event_sha256,
    'terminal_acp_ingress_sequence',terminal_acp_ingress_sequence,
    'terminal_acp_ingress_sha256',terminal_acp_ingress_sha256,
    'terminal_unknown_claim_count',terminal_unknown_claim_count,
    'terminal_unknown_claims_sha256',terminal_unknown_claims_sha256) ORDER BY root_run_id)
    FROM root_limited),'[]'::json),
  'registration_count',(SELECT count(*) FROM reg_rows),
  'registrations',COALESCE((SELECT json_agg(to_jsonb(reg_limited)
    ORDER BY origin,depth,native_agent_session_id) FROM reg_limited),'[]'::json),
  'ingress_count',(SELECT count(*) FROM ingress_rows),
  'ingress',COALESCE((SELECT json_agg(to_jsonb(ingress_limited)
    ORDER BY sequence,mcp_request_id) FROM ingress_limited),'[]'::json),
  'audit_count',(SELECT count(*) FROM audit_rows),
  'audits',COALESCE((SELECT json_agg(to_jsonb(audit_limited)
    ORDER BY created_at,audit_id) FROM audit_limited),'[]'::json)
)::text;
COMMIT;"""


def _object_rows(value: object, name: str, count: object, maximum: int) -> list[dict[str, Any]]:
    if (type(count) is not int or count < 0 or count > maximum
            or not isinstance(value, list) or len(value) != count
            or any(not isinstance(row, dict) for row in value)):
        raise ScopeReadError(f"{name}_projection_invalid")
    return value


def validate_projection(raw_scope: object, mode: str, raw_projection: object) -> dict[str, Any]:
    """Validate the SQL projection and return only bounded identity/audit fields."""
    scope = _validated_scope(raw_scope)
    if not isinstance(mode, str) or mode not in MODES:
        raise ScopeReadError("mode_invalid")
    if isinstance(raw_projection, (str, bytes)):
        raw_projection = _strict_json(raw_projection)
    if not isinstance(raw_projection, dict):
        raise ScopeReadError("projection_invalid")
    expected = {"schema_version", "mode", "foreign_mismatch_count", "root_count", "roots",
                "registration_count", "registrations", "ingress_count", "ingress",
                "audit_count", "audits"}
    if set(raw_projection) != expected or raw_projection["schema_version"] != SCHEMA or raw_projection["mode"] != mode:
        raise ScopeReadError("projection_schema_invalid")
    if type(raw_projection["foreign_mismatch_count"]) is not int or raw_projection["foreign_mismatch_count"] != 0:
        raise ScopeReadError("foreign_scope_or_run_rows")
    if (type(raw_projection["root_count"]) is not int or raw_projection["root_count"] != 1
            or not isinstance(raw_projection["roots"], list) or len(raw_projection["roots"]) != 1):
        raise ScopeReadError("root_scope_not_unique")
    root = raw_projection["roots"][0]
    root_fields = {"root_run_id", "owner_principal", "workspace_id", "session_id", "trace_id",
        "status", "authority_status", "authority_boot_id", "terminal_sequence",
        "terminal_event_sha256", "terminal_acp_ingress_sequence", "terminal_acp_ingress_sha256",
        "terminal_unknown_claim_count", "terminal_unknown_claims_sha256"}
    if (not isinstance(root, dict) or set(root) != root_fields
            or any(root.get(key) != scope[key] for key in (
                "root_run_id", "owner_principal", "workspace_id", "session_id", "trace_id"))
            or root.get("authority_boot_id") != scope["runtime_boot_id"]):
        raise ScopeReadError("root_scope_mismatch")
    terminal = (root["terminal_sequence"], root["terminal_event_sha256"],
        root["terminal_acp_ingress_sequence"], root["terminal_acp_ingress_sha256"],
        root["terminal_unknown_claim_count"], root["terminal_unknown_claims_sha256"])
    if not isinstance(root["status"], str) or not isinstance(root["authority_status"], str):
        raise ScopeReadError("root_fields_invalid")
    if root["status"] == "active":
        if root["authority_status"] != "active" or any(value is not None for value in terminal):
            raise ScopeReadError("active_root_terminal_fields_invalid")
    elif root["status"] in {"completed", "failed", "cancelled", "interrupted"}:
        if (root["authority_status"] != "closed"
                or type(root["terminal_sequence"]) is not int or root["terminal_sequence"] < 1
                or not isinstance(root["terminal_event_sha256"], str)
                or not _HEX64.fullmatch(root["terminal_event_sha256"])
                or type(root["terminal_acp_ingress_sequence"]) is not int
                or root["terminal_acp_ingress_sequence"] < 0
                or not isinstance(root["terminal_acp_ingress_sha256"], str)
                or not _HEX64.fullmatch(root["terminal_acp_ingress_sha256"])
                or type(root["terminal_unknown_claim_count"]) is not int
                or root["terminal_unknown_claim_count"] < 0
                or not isinstance(root["terminal_unknown_claims_sha256"], str)
                or not _HEX64.fullmatch(root["terminal_unknown_claims_sha256"])):
            raise ScopeReadError("terminal_root_fields_invalid")
    else:
        raise ScopeReadError("root_status_invalid")
    regs = _object_rows(raw_projection["registrations"], "registrations",
                        raw_projection["registration_count"], MAX_REGISTRATIONS)
    ingress = _object_rows(raw_projection["ingress"], "ingress",
                           raw_projection["ingress_count"], MAX_INGRESS)
    audits = _object_rows(raw_projection["audits"], "audits", raw_projection["audit_count"], MAX_AUDITS)
    if mode == "preflight":
        if len(regs) > 1 or any(row.get("origin") != "root" or row.get("depth") != 0
                or row.get("native_agent_session_id") != row.get("native_root_session_id")
                or row.get("native_parent_session_id") is not None or row.get("parent_run_id") is not None
                for row in regs):
            raise ScopeReadError("preflight_registration_shape_invalid")
    elif len(regs) != 2:
        raise ScopeReadError("root_child_registration_count_invalid")
    by_native: dict[str, dict[str, Any]] = {}
    reg_fields = {"root_run_id", "native_agent_session_id", "native_root_session_id",
        "native_parent_session_id", "owner_principal", "workspace_id", "actor_principal",
        "session_id", "trace_id", "dsh_run_id", "runtime_boot_id", "origin", "depth",
        "agent_run_id", "parent_run_id", "registration_status", "joined_run_id", "run_owner",
        "run_actor", "run_trace", "run_session", "run_generation", "run_root", "run_parent",
        "run_boot", "run_status", "run_authority_status"}
    for row in regs:
        if set(row) != reg_fields:
            raise ScopeReadError("registration_fields_invalid")
        if any(row.get(key) != scope[value] for key, value in (
            ("root_run_id", "root_run_id"), ("owner_principal", "owner_principal"),
            ("workspace_id", "workspace_id"), ("actor_principal", "actor_principal"),
            ("session_id", "session_id"), ("trace_id", "trace_id"),
            ("dsh_run_id", "generation_id"), ("runtime_boot_id", "runtime_boot_id"))):
            raise ScopeReadError("registration_scope_mismatch")
        run_id = row.get("agent_run_id")
        if (not isinstance(run_id, str) or not run_id or row.get("joined_run_id") != run_id
                or row.get("run_root") != scope["root_run_id"]
                or row.get("run_owner") != scope["owner_principal"]
                or row.get("run_actor") != scope["actor_principal"]
                or row.get("run_session") != scope["session_id"]
                or row.get("run_trace") != scope["trace_id"]
                or row.get("run_generation") != scope["generation_id"]
                or row.get("run_boot") != scope["runtime_boot_id"]
                or not isinstance(row.get("run_status"), str)
                or not isinstance(row.get("run_authority_status"), str)
                or row.get("run_parent") != row.get("parent_run_id")):
            raise ScopeReadError("registration_run_mismatch")
        if row.get("registration_status") not in {"pending", "bound"}:
            raise ScopeReadError("registration_status_invalid")
        if mode == "root_child" and row.get("registration_status") != "bound":
            raise ScopeReadError("root_child_registration_unbound")
        native = row.get("native_agent_session_id")
        if not isinstance(native, str) or native in by_native:
            raise ScopeReadError("registration_identity_invalid")
        by_native[native] = row
    if mode == "root_child":
        roots = [row for row in regs if row.get("origin") == "root" and row.get("depth") == 0]
        children = [row for row in regs if row.get("origin") == "subagent" and row.get("depth") == 1]
        if len(roots) != 1 or len(children) != 1:
            raise ScopeReadError("root_child_lineage_invalid")
        root_reg, child_reg = roots[0], children[0]
        if (root_reg.get("native_agent_session_id") != root_reg.get("native_root_session_id")
                or child_reg.get("native_agent_session_id") == root_reg.get("native_agent_session_id")
                or child_reg.get("agent_run_id") == root_reg.get("agent_run_id")
                or root_reg.get("native_parent_session_id") is not None
                or root_reg.get("parent_run_id") is not None
                or child_reg.get("native_root_session_id") != root_reg.get("native_root_session_id")
                or child_reg.get("native_parent_session_id") != root_reg.get("native_agent_session_id")
                or child_reg.get("parent_run_id") != root_reg.get("agent_run_id")):
            raise ScopeReadError("root_child_parent_mismatch")
    for row in ingress:
        required = {"mcp_request_id", "root_run_id", "owner_principal", "workspace_id", "actor_principal",
            "session_id", "trace_id", "dsh_run_id", "runtime_boot_id", "native_root_session_id",
            "native_agent_session_id", "native_parent_session_id", "origin", "depth", "agent_run_id",
            "tool_name", "arguments_sha256", "sequence", "event_sha256", "status",
            "settlement_outcome", "settlement_sha256"}
        if set(row) != required or any(row.get(key) != scope[value] for key, value in (
            ("root_run_id", "root_run_id"), ("owner_principal", "owner_principal"),
            ("workspace_id", "workspace_id"), ("actor_principal", "actor_principal"),
            ("session_id", "session_id"), ("trace_id", "trace_id"),
            ("dsh_run_id", "generation_id"), ("runtime_boot_id", "runtime_boot_id"))):
            raise ScopeReadError("ingress_scope_mismatch")
        if (not isinstance(row.get("mcp_request_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", row["mcp_request_id"])
                or not isinstance(row.get("tool_name"), str)
                or not isinstance(row.get("arguments_sha256"), str) or not _HEX64.fullmatch(row["arguments_sha256"])
                or not isinstance(row.get("event_sha256"), str) or not _HEX64.fullmatch(row["event_sha256"])
                or type(row.get("sequence")) is not int or row["sequence"] < 1
                or row.get("status") not in {"pending", "settled", "unknown"}):
            raise ScopeReadError("ingress_fields_invalid")
        reg = by_native.get(row.get("native_agent_session_id"))
        if (reg is None or row.get("agent_run_id") != reg.get("agent_run_id")
              or row.get("native_root_session_id") != reg.get("native_root_session_id")
              or row.get("native_parent_session_id") != reg.get("native_parent_session_id")
              or row.get("origin") != reg.get("origin") or row.get("depth") != reg.get("depth")):
            raise ScopeReadError("ingress_registration_mismatch")
        settlement_hash = row.get("settlement_sha256")
        settlement_outcome = row.get("settlement_outcome")
        if row["status"] == "pending":
            if settlement_outcome is not None or settlement_hash is not None:
                raise ScopeReadError("pending_ingress_settlement_invalid")
        elif row["status"] == "settled":
            if (settlement_outcome not in {"settled", "denied", "aborted_before_dispatch"}
                    or not isinstance(settlement_hash, str) or not _HEX64.fullmatch(settlement_hash)):
                raise ScopeReadError("settled_ingress_settlement_invalid")
        elif row["status"] == "unknown":
            if (settlement_outcome != "unknown" or not isinstance(settlement_hash, str)
                    or not _HEX64.fullmatch(settlement_hash)):
                raise ScopeReadError("unknown_ingress_settlement_invalid")
    audit_ids: set[str] = set()
    for row in audits:
        if (set(row) != {"root_run_id", "native_agent_session_id", "audit_id", "run_id",
                         "owner_principal", "actor_principal", "action", "outcome", "created_at"}
                or row.get("root_run_id") != scope["root_run_id"]
                or row.get("owner_principal") != scope["owner_principal"]
                or row.get("native_agent_session_id") not in by_native
                or row.get("run_id") != by_native[row.get("native_agent_session_id")].get("agent_run_id")
                or row.get("actor_principal") != scope["actor_principal"]
                or not isinstance(row.get("audit_id"), str) or not isinstance(row.get("action"), str)
                or not isinstance(row.get("outcome"), str) or not isinstance(row.get("created_at"), str)):
            raise ScopeReadError("audit_scope_mismatch")
        if row["audit_id"] in audit_ids:
            raise ScopeReadError("audit_duplicate_id")
        audit_ids.add(row["audit_id"])
    return {
        "schema_version": SCHEMA, "mode": mode,
        "root": {key: root[key] for key in ("root_run_id", "owner_principal", "workspace_id",
            "session_id", "trace_id", "status", "authority_status", "authority_boot_id",
            "terminal_sequence", "terminal_event_sha256", "terminal_acp_ingress_sequence",
            "terminal_acp_ingress_sha256", "terminal_unknown_claim_count",
            "terminal_unknown_claims_sha256")},
        "registration_count": len(regs),
        "registrations": [{key: row[key] for key in (
            "native_agent_session_id", "native_root_session_id", "native_parent_session_id",
            "origin", "depth", "agent_run_id", "parent_run_id", "registration_status", "run_status",
            "run_authority_status")} for row in regs],
        "ingress_count": len(ingress),
        "ingress": [{key: row[key] for key in (
            "native_agent_session_id", "origin", "depth", "agent_run_id", "tool_name",
            "arguments_sha256", "sequence", "event_sha256", "status", "settlement_outcome",
            "settlement_sha256")} for row in ingress],
        "audit_count": len(audits),
        "audits": [{key: row[key] for key in ("native_agent_session_id", "audit_id", "run_id",
            "action", "outcome", "created_at")} for row in audits],
    }


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(16_385)
        if len(raw) > 16_384:
            raise ScopeReadError("request_too_large")
        request = _strict_json(raw)
        if not isinstance(request, dict) or set(request) != {"mode", "scope"}:
            raise ScopeReadError("request_fields_invalid")
        sql = build_sql(request["scope"], request["mode"])
        sys.stdout.write(sql)
        return 0
    except ScopeReadError as exc:
        sys.stderr.write(f"SCOPE_READ_STOP:{exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
