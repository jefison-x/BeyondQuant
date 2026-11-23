"""One-shot Engineering reconciliation for one retained read-only market error.

This module is deliberately not wired into the Backend HTTP application. It
accepts only the exact f6dc Root and its one daily-read MCP request from ADR-0117.
The original ingress remains unknown and byte-for-byte unchanged.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from packages.contracts.acp_product_slot import (
    PRODUCT_SCOPE_KEYS,
    validate_product_scope,
    verify_product_cleanup_receipt,
)
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event
from .agent_research import AgentResearchStore


ROOT_ID = "f6dc48f8c4e446c6912eed772a47493f"
REQUEST_ID = "d654db9604d2a0631a6db5ba5e77412c"
WORKSPACE_ID = "workspace_4c5b803209d549019b7804976f6930c6"
SESSION_ID = "byq-session-e84ae897741647b7b27881de996cc06c"
TRACE_ID = "byq-trace-06a38817a2bc4a34839fd1111795f387"
BOOT_ID = "33e339aa0f16c1d4f0604f9f75bdb33d"
NATIVE_ROOT_ID = "a1d158ec-b89b-45c6-8846-92ee9e8b6567"
GENERATION_ID = "generation-cca499003b9948c998f0a977dbee34be"
CONVERSATION_ID = "conversation_5ecc68a5555c4de2a6fc975a6682c6bd"
AUTHORITY_EPOCH = 51
SCHEMA = "byq-acp-readonly-market-reconciliation.v1"
ACTION = "readonly_market_unknown_reconciliation"
OUTCOME = "readonly_query_outcome_unknown_acknowledged"
SCOPE_SCHEMA = "byq-acp-product-cleanup-scope.v1"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILE = 1_048_576
READONLY_SOURCE_SHA256 = {
    "main.py": "84e3923d2b24bb9b50cafe91923a178f7077b0ffa1537c2ee7e4ec151791e830",
    "market_data.py": "72e511f206e3ddd8edf6d40a26ef1462ccdbcd99fd2cef4beaf5708dbc32cc54",
    "data_provider.py": "0fdf9de31724ed53ccb53c35ed1a069a696cc0fa6e3843048cfc047a967b7662",
}


class ReadonlyReconciliationHold(RuntimeError):
    """Evidence is incomplete, changed or outside the one accepted scope."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _readonly_source_evidence() -> dict[str, str]:
    """Pin the exact Backend sources reviewed as a pure persisted-data read."""
    source_dir = Path(__file__).resolve().parent
    actual: dict[str, str] = {}
    for name, expected in READONLY_SOURCE_SHA256.items():
        path = source_dir / name
        try:
            metadata = path.lstat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE
                    or metadata.st_nlink != 1):
                raise ReadonlyReconciliationHold("reviewed market-read source is not a bounded regular file")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ReadonlyReconciliationHold("reviewed market-read source is unavailable") from exc
        if digest != expected:
            raise ReadonlyReconciliationHold("market-read source differs from the reviewed read-only version")
        actual[name] = digest
    return actual


def _validate_arguments(value: object) -> dict[str, dict[str, Any]]:
    if (not isinstance(value, dict) or set(value) != {REQUEST_ID}
            or not isinstance(value[REQUEST_ID], dict)
            or set(value[REQUEST_ID]) != {"ts_code"}
            or value[REQUEST_ID]["ts_code"] != "600036.SH"):
        raise ReadonlyReconciliationHold("market-read arguments do not match the exact retained request")
    return value


def _validate_terminal(raw_event: object, evidence: object) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    if not isinstance(raw_event, dict) or not isinstance(evidence, dict):
        raise ReadonlyReconciliationHold("original Runtime terminal event/evidence is unavailable")
    binding, terminal = evidence.get("binding"), evidence.get("terminal")
    if not isinstance(binding, dict) or not isinstance(terminal, dict):
        raise ReadonlyReconciliationHold("original Runtime binding and terminal readback are required")
    expected_binding = {
        "schema_version": "byq-acp-root-binding.v1", "root_run_id": ROOT_ID,
        "owner_principal": "admin", "workspace_id": WORKSPACE_ID,
        "session_id": SESSION_ID, "trace_id": TRACE_ID,
        "native_session_id": NATIVE_ROOT_ID, "runtime_generation": GENERATION_ID,
        "previous_boot_id": BOOT_ID, "previous_authority_epoch": AUTHORITY_EPOCH,
        "sequence": 1, "domain_call_sequence": 0, "domain_call_drained_sequence": 0,
        "closed": False, "process_exit_confirmed": False,
        "native_session_close_confirmed": False, "settlement_receipt": None,
    }
    if any(binding.get(key) != expected for key, expected in expected_binding.items()):
        raise ReadonlyReconciliationHold("original Runtime binding differs from the fixed historical Root")
    cwd = binding.get("cwd")
    if (not isinstance(cwd, str) or not Path(cwd).is_absolute()
            or Path(cwd).parent.name != WORKSPACE_ID
            or re.fullmatch(r"(?:session|root)-[0-9a-f]{32}", Path(cwd).name) is None):
        raise ReadonlyReconciliationHold("original Runtime binding working directory is outside the fixed workspace")
    if (terminal.get("schema_version") != "byq-runtime-terminal-evidence.v1"
            or terminal.get("session_id") != SESSION_ID or terminal.get("boot_id") != BOOT_ID
            or terminal.get("root_run_id") != ROOT_ID or terminal.get("sequence") != 38
            or terminal.get("outcome") != "completed"):
        raise ReadonlyReconciliationHold("Runtime terminal evidence is outside the fixed original Root")
    event = project_lifecycle_event(raw_event, SESSION_ID, TRACE_ID)
    if event is None or event != {"schema_version": "agent-run-lifecycle.v1",
                                  "root_run_id": ROOT_ID, "sequence": 38,
                                  "outcome": "completed"}:
        raise ReadonlyReconciliationHold("original raw Runtime event is not the exact terminal result")
    receipt = lifecycle_receipt(event)
    if terminal.get("receipt") != receipt:
        raise ReadonlyReconciliationHold("raw Runtime terminal event differs from its readback receipt")
    if (raw_event.get("sequence") != 38 or raw_event.get("session_id") != SESSION_ID
            or raw_event.get("trace_id") != TRACE_ID or raw_event.get("source") != "runtime-adapter"):
        raise ReadonlyReconciliationHold("saved raw Runtime event identity is invalid")
    return event, receipt, Path(cwd).name, _digest({"event": raw_event, "evidence": evidence})


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def normalize(value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value
    return [normalize(row) for row in rows]


def _load_snapshot(connection: Any, store: AgentResearchStore, *,
                   arguments: dict[str, dict[str, Any]],
                   native_root_session_id: str, terminal_receipt: dict[str, Any],
                   cwd_leaf: str, terminal_evidence_sha256: str,
                   allow_closed: bool = False, lock_rows: bool = False) -> dict[str, Any]:
    from .agent_research import AgentConflict, AgentNotFound
    from .db import execute, fetch_one

    suffix = " FOR UPDATE" if lock_rows else " FOR SHARE"
    root = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root" + suffix,
                     {"root": ROOT_ID})
    if root is None:
        raise AgentNotFound("fixed read-only reconciliation Root is absent")
    if any(root.get(key) != expected for key, expected in {
            "root_run_id": ROOT_ID, "owner_principal": "admin", "workspace_id": WORKSPACE_ID,
            "session_id": SESSION_ID, "trace_id": TRACE_ID, "authority_boot_id": BOOT_ID}.items()):
        raise AgentConflict("fixed Root identity changed")
    if allow_closed:
        if (root.get("status") != "completed" or root.get("authority_status") != "closed"
                or root.get("terminal_sequence") != 38
                or root.get("terminal_event_sha256") != terminal_receipt["event_sha256"]):
            raise AgentConflict("closed Root does not match its original Runtime terminal")
    elif (root.get("status") != "active" or root.get("authority_status") != "active"
          or root.get("terminal_sequence") is not None or root.get("terminal_event_sha256") is not None):
        raise AgentConflict("fixed Root is not active and unclosed")

    authority = store._require_current_runtime_boot(connection, BOOT_ID, required=True)
    store._require_lifecycle_workspace(connection, "admin", WORKSPACE_ID,
                                       terminal_cleanup=allow_closed)
    conversations = execute(connection, """SELECT * FROM product_conversations
        WHERE conversation_id=:conversation""" + suffix,
        {"conversation": CONVERSATION_ID})
    if (len(conversations) != 1 or conversations[0].get("status") != "active"
            or conversations[0].get("owner_principal") != "admin"
            or conversations[0].get("runtime_session_id") != SESSION_ID
            or conversations[0].get("trace_id") != TRACE_ID):
        raise AgentConflict("public conversation identity or status changed")

    run_rows = execute(connection, "SELECT * FROM agent_runs WHERE root_run_id=:root ORDER BY run_id" + suffix,
                       {"root": ROOT_ID})
    if not run_rows or len(run_rows) > 32:
        raise AgentConflict("Root AgentRun set is absent or exceeds its bound")
    root_runs = [row for row in run_rows if row.get("parent_run_id") is None]
    if len(root_runs) != 1:
        raise AgentConflict("Root does not have one exact root AgentRun")
    if allow_closed:
        if any(row.get("status") != "completed" or row.get("authority_status") != "closed"
               for row in run_rows):
            raise AgentConflict("AgentRun authority was not closed with the Root")
    elif any(row.get("authority_status") != "active" for row in run_rows):
        raise AgentConflict("an AgentRun does not have current authority")
    generation = root_runs[0].get("dsh_run_id")
    if generation != GENERATION_ID:
        raise AgentConflict("Root DSH generation differs from the original Runtime binding")

    from packages.contracts.acp_product_slot import validate_product_scope
    scope = validate_product_scope({"workspace_id": WORKSPACE_ID, "owner_principal": "admin",
        "session_id": SESSION_ID, "trace_id": TRACE_ID, "root_run_id": ROOT_ID,
        "runtime_boot_id": BOOT_ID, "generation_id": generation,
        "cwd_leaf": cwd_leaf})

    tables = (
        ("agent_runtime_registrations", "registration_fingerprint"),
        ("agent_acp_native_agent_registrations", "origin,native_agent_session_id"),
        ("agent_acp_tool_ingress_observations", "sequence"),
        ("agent_acp_domain_call_observations", "sequence"),
        ("agent_domain_call_evidence", "sequence"),
        ("agent_domain_call_claims", "claim_id"),
        ("agent_domain_correction_buckets", "task_id,action"),
    )
    facts: dict[str, Any] = {"schema_version": "byq-acp-readonly-market-snapshot.v1",
        "root_run_id": ROOT_ID, "scope": {key: scope[key] for key in PRODUCT_SCOPE_KEYS - {"cwd_leaf"}},
        "native_root_session_id": native_root_session_id,
        "root": _normalize_rows([root])[0],
        "conversation": _normalize_rows(conversations),
        "agent_runs": _normalize_rows(run_rows),
        "arguments_sha256": {},
        "terminal_event_receipt": terminal_receipt,
        "terminal_runtime_evidence_sha256": terminal_evidence_sha256,
        "readonly_implementation_sources": _readonly_source_evidence(),
    }
    if authority.get("epoch") != AUTHORITY_EPOCH:
        raise AgentConflict("Runtime authority epoch differs from the retained binding")
    facts["runtime_authority"] = _normalize_rows([authority])[0]
    for request_id, args in arguments.items():
        from .domain_call_admission import _canonical_acp_arguments
        argument_sha, _ = _canonical_acp_arguments(args)
        facts["arguments_sha256"][request_id] = argument_sha

    selected_unknown: list[dict[str, Any]] = []
    for table, order in tables:
        rows = execute(connection, f"SELECT * FROM {table} WHERE root_run_id=:root ORDER BY {order}" + suffix,
                       {"root": ROOT_ID})
        facts[table] = _normalize_rows(rows)
        if len(rows) > 10_000:
            raise AgentConflict("read-only reconciliation evidence exceeds its bounded row count")
        if table in {"agent_acp_domain_call_observations", "agent_domain_call_evidence", "agent_domain_call_claims", "agent_domain_correction_buckets"} and rows:
            raise AgentConflict("unexpected business domain evidence blocks exact read-only recovery")
        if table == "agent_runtime_registrations":
            expected = {row.get("runtime_registration_fingerprint") for row in run_rows}
            actual = {row.get("registration_fingerprint") for row in rows}
            if None in expected or actual != expected or any(row.get("root_run_id") != ROOT_ID for row in rows):
                raise AgentConflict("Runtime registration set differs from the exact AgentRuns")
        elif table == "agent_acp_native_agent_registrations":
            if (any(row.get("status") != "bound" for row in rows)
                    or len([row for row in rows if row.get("origin") == "root"]) != 1
                    or not rows):
                raise AgentConflict("pending or incomplete native registration blocks read-only reconciliation")
            run_ids = {row["run_id"] for row in run_rows}
            for row in rows:
                if (row.get("root_run_id") != ROOT_ID
                        or row.get("native_root_session_id") != NATIVE_ROOT_ID
                        or row.get("owner_principal") != "admin"
                        or row.get("workspace_id") != WORKSPACE_ID
                        or row.get("session_id") != SESSION_ID
                        or row.get("trace_id") != TRACE_ID
                        or row.get("dsh_run_id") != GENERATION_ID
                        or row.get("runtime_boot_id") != BOOT_ID
                        or row.get("agent_run_id") not in run_ids):
                    raise AgentConflict("native registration identity changed")
            native_root = next(row for row in rows if row.get("origin") == "root")
            if (native_root.get("native_agent_session_id") != NATIVE_ROOT_ID
                    or native_root.get("depth") != 0
                    or native_root.get("native_parent_session_id") is not None
                    or native_root.get("parent_run_id") is not None):
                raise AgentConflict("native Root registration is not exact")
        elif table == "agent_acp_tool_ingress_observations":
            if [row.get("sequence") for row in rows] != list(range(1, len(rows) + 1)):
                raise AgentConflict("ingress sequence is incomplete")
            for row in rows:
                from .domain_call_admission import DomainCallEvidenceMixin, acp_binding_sha256
                event, receipt = DomainCallEvidenceMixin._acp_audit_ingress_event_and_receipt(row)
                if (acp_binding_sha256(event) != row.get("event_sha256")
                        or row.get("receipt_json") != receipt
                        or row.get("root_run_id") != ROOT_ID
                        or row.get("owner_principal") != "admin"
                        or row.get("workspace_id") != WORKSPACE_ID
                        or row.get("session_id") != SESSION_ID
                        or row.get("trace_id") != TRACE_ID
                        or row.get("runtime_boot_id") != BOOT_ID):
                    raise AgentConflict("ingress identity or receipt changed")
                if row.get("mcp_request_id") == REQUEST_ID:
                    if (row.get("sequence") != 8 or row.get("tool_name") != "byq_market_daily"
                            or row.get("status") != "unknown"
                            or row.get("arguments_sha256") != facts["arguments_sha256"][REQUEST_ID]
                            or not isinstance(row.get("settlement_json"), dict)):
                        raise AgentConflict("selected daily-read unknown differs from its exact request")
                    selected_unknown.append(row)
                elif row.get("status") != "settled" or not isinstance(row.get("settlement_json"), dict):
                    raise AgentConflict("another unresolved tool ingress blocks reconciliation")
        elif table == "agent_domain_call_claims":
            if any(row.get("status") in {"claimed", "executing"} for row in rows):
                raise AgentConflict("unresolved domain claim blocks read-only reconciliation")

    if len(selected_unknown) != 1:
        raise AgentConflict("exactly one selected daily-read unknown is required")
    approvals = execute(connection, "SELECT a.* FROM agent_approvals a JOIN agent_runs r ON r.run_id=a.run_id WHERE r.root_run_id=:root ORDER BY a.approval_id" + suffix, {"root": ROOT_ID})
    if approvals:
        raise AgentConflict("unexpected approval state blocks exact read-only recovery")
    facts["agent_approvals"] = []
    messages = execute(connection, """SELECT * FROM product_conversation_messages
        WHERE conversation_id=:conversation ORDER BY sequence""" + suffix,
        {"conversation": CONVERSATION_ID})
    if len(messages) > 10_000:
        raise AgentConflict("conversation message set exceeds its bound")
    facts["conversation_messages"] = _normalize_rows(messages)
    audit_rows = execute(connection, """SELECT a.* FROM agent_audit a JOIN agent_runs r ON r.run_id=a.run_id
        WHERE r.root_run_id=:root AND a.audit_id<>:reserved ORDER BY a.audit_id""" + suffix,
        {"root": ROOT_ID, "reserved": readonly_market_reconciliation_id()})
    facts["agent_audit"] = _normalize_rows(audit_rows)
    runtime_receipts = execute(connection, """SELECT * FROM agent_runtime_receipts
        WHERE owner_principal=:owner AND workspace_id=:workspace AND session_id=:session
        ORDER BY sequence""" + suffix,
        {"owner": "admin", "workspace": WORKSPACE_ID, "session": SESSION_ID})
    expected_terminal = terminal_receipt
    stable_receipts = []
    for row in runtime_receipts:
        if row.get("trace_id") != TRACE_ID:
            raise AgentConflict("Runtime receipt trace differs from the exact session")
        if row.get("sequence") == 38:
            if allow_closed and row.get("receipt_json") == expected_terminal:
                continue
            raise AgentConflict("terminal sequence is already occupied")
        stable_receipts.append(row)
    facts["runtime_lifecycle_receipts"] = _normalize_rows(stable_receipts)

    from .domain_call_admission import acp_binding_sha256
    ingress_digest = acp_binding_sha256({"schema_version": "byq-acp-readonly-original-ingress-rows.v1",
        "root_run_id": ROOT_ID, "rows": facts["agent_acp_tool_ingress_observations"]})
    claims = facts["agent_domain_call_claims"]
    unknown_claims = [row for row in claims if row.get("status") in {"unknown", "claimed", "executing"}]
    if unknown_claims:
        raise AgentConflict("unknown or unfinished domain claim blocks reconciliation")
    empty_unknown_claims_sha = acp_binding_sha256({"schema_version": "byq-acp-unknown-claims.v1",
                                                    "root_run_id": ROOT_ID, "claims": []})
    digest = acp_binding_sha256(facts)
    return {"scope": scope, "native_root_session_id": native_root_session_id,
        "snapshot_sha256": digest, "facts": facts, "root": root,
        "run": root_runs[0], "rows": facts["agent_acp_tool_ingress_observations"],
        "unknown_row": selected_unknown[0], "original_ingress_rows_sha256": ingress_digest,
        "terminal_unknown_claims_sha256": empty_unknown_claims_sha,
        "terminal_event_receipt": expected_terminal}


def readonly_market_reconciliation_id(root_run_id: str = ROOT_ID) -> str:
    if root_run_id != ROOT_ID:
        raise ReadonlyReconciliationHold("reconciliation is limited to the exact accepted Root")
    value = hashlib.sha256((SCHEMA + "\0" + ROOT_ID).encode("ascii")).hexdigest()[:32]
    return "agent_audit_" + value


def readonly_market_reconciliation_row(connection: Any, root_run_id: str) -> dict[str, Any] | None:
    if root_run_id != ROOT_ID:
        return None
    from .db import fetch_one
    row = fetch_one(connection, """SELECT a.*,r.root_run_id AS audit_root_run_id,
            r.owner_principal AS audit_owner_principal,r.actor_principal AS audit_actor_principal,
            t.workspace_id AS audit_workspace_id
        FROM agent_audit a JOIN agent_runs r ON r.run_id=a.run_id
        JOIN agent_runtime_turns t ON t.root_run_id=r.root_run_id WHERE a.audit_id=:id""",
        {"id": readonly_market_reconciliation_id()})
    if row is None:
        return None
    detail = row.get("detail_json")
    receipt = detail.get("acp_control") if isinstance(detail, dict) else None
    if (row.get("audit_id") != readonly_market_reconciliation_id()
            or row.get("audit_root_run_id") != ROOT_ID or row.get("resource_id") != ROOT_ID
            or row.get("audit_owner_principal") != "admin"
            or row.get("audit_workspace_id") != WORKSPACE_ID
            or row.get("owner_principal") != "admin"
            or not isinstance(receipt, dict) or row.get("run_id") != receipt.get("agent_run_id")
            or row.get("action") != ACTION or row.get("outcome") != OUTCOME
            or row.get("resource_type") != "runtime_root"
            or row.get("detail_json") != {"acp_control": receipt} or not isinstance(receipt, dict)):
        raise ValueError("reserved read-only reconciliation row identity changed")
    base = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if (set(receipt) != {"schema_version", "root_run_id", "scope", "native_root_session_id",
            "authority_epoch", "agent_run_id", "backend_snapshot_sha256",
            "original_ingress_rows_sha256", "unknown_count", "unknown_disposition",
            "unknown_ingress", "domain_claim_count", "terminal_unknown_claims_sha256",
            "product_cleanup_receipt_sha256", "product_cleanup_scope_digest",
            "binding_sha256_before", "binding_sha256_after", "terminal_event_receipt",
            "operator_uid", "operator_name", "terminal_runtime_evidence_sha256",
            "readonly_implementation_sources", "receipt_sha256"}
            or receipt.get("schema_version") != SCHEMA or receipt.get("root_run_id") != ROOT_ID
            or receipt.get("unknown_count") != 1 or receipt.get("unknown_disposition") != OUTCOME
            or receipt.get("domain_claim_count") != 0 or receipt.get("scope", {}).get("root_run_id") != ROOT_ID
            or _digest(base) != receipt.get("receipt_sha256")):
        raise ValueError("reserved read-only reconciliation receipt is invalid")
    return {**row, "detail_json": detail, "receipt": receipt}


def readonly_unknown_coverage(connection: Any, root_run_id: str,
                              receipt: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from .db import execute
    from .domain_call_admission import DomainCallEvidenceMixin, acp_binding_sha256
    if root_run_id != ROOT_ID or receipt.get("root_run_id") != ROOT_ID:
        raise ValueError("read-only reconciliation covers another Root")
    rows = execute(connection, """SELECT * FROM agent_acp_tool_ingress_observations
        WHERE root_run_id=:root ORDER BY sequence""", {"root": ROOT_ID})
    normalized = _normalize_rows(rows)
    if acp_binding_sha256({"schema_version": "byq-acp-readonly-original-ingress-rows.v1",
            "root_run_id": ROOT_ID, "rows": normalized}) != receipt.get("original_ingress_rows_sha256"):
        raise ValueError("read-only reconciliation original ingress rows changed")
    selected = None
    for row in rows:
        event, expected = DomainCallEvidenceMixin._acp_audit_ingress_event_and_receipt(row)
        if acp_binding_sha256(event) != row.get("event_sha256") or row.get("receipt_json") != expected:
            raise ValueError("read-only reconciliation ingress identity changed")
        if row.get("mcp_request_id") == REQUEST_ID:
            if (row.get("sequence") != 8 or row.get("tool_name") != "byq_market_daily"
                    or row.get("status") != "unknown"
                    or acp_binding_sha256(row.get("settlement_json")) != receipt["unknown_ingress"].get("settlement_sha256")):
                raise ValueError("selected unknown ingress no longer matches reconciliation")
            selected = row
        elif row.get("status") != "settled":
            raise ValueError("another pending or unknown ingress prevents terminal closure")
    unknown = receipt.get("unknown_ingress")
    if (selected is None or not isinstance(unknown, dict)
            or {key: unknown.get(key) for key in ("mcp_request_id", "sequence", "event_sha256",
                "arguments_sha256", "status")} != {
                "mcp_request_id": REQUEST_ID, "sequence": 8,
                "event_sha256": selected["event_sha256"],
                "arguments_sha256": selected["arguments_sha256"], "status": "unknown"}):
        raise ValueError("read-only reconciliation does not cover the exact original unknown")
    return rows, selected


def prepare_readonly_market_error(store: AgentResearchStore, *, arguments_by_request: object,
                                  raw_terminal_event: object, terminal_evidence: object,
                                  native_root_session_id: str) -> dict[str, Any]:
    arguments = _validate_arguments(arguments_by_request)
    event, terminal_receipt, cwd_leaf, evidence_sha = _validate_terminal(raw_terminal_event, terminal_evidence)
    if native_root_session_id != NATIVE_ROOT_ID:
        raise ReadonlyReconciliationHold("native Root session differs from the exact retained Runtime Root")
    with store._transaction() as connection:
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        snapshot = _load_snapshot(connection, store, arguments=arguments,
            native_root_session_id=native_root_session_id, terminal_receipt=terminal_receipt,
            cwd_leaf=cwd_leaf, terminal_evidence_sha256=evidence_sha)
    return {"schema_version": SCOPE_SCHEMA,
        "scope": {key: snapshot["scope"][key] for key in PRODUCT_SCOPE_KEYS - {"cwd_leaf"}},
        "native_root_session_id": native_root_session_id,
        "backend_snapshot_sha256": snapshot["snapshot_sha256"]}


def _validate_runtime_result(value: object, *, envelope: dict[str, Any],
                             control_key: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    configured = os.environ.get("BYQ_ACP_PRODUCT_CONTROL_KEY_SHA256", "")
    if (not isinstance(control_key, bytes) or not 32 <= len(control_key) <= 512
            or not HEX64.fullmatch(configured)
            or not hmac.compare_digest(hashlib.sha256(control_key).hexdigest(), configured)):
        raise ReadonlyReconciliationHold("Product control key differs from Backend trust anchor")
    fields = {"status", "root_run_id", "backend_snapshot_sha256", "native_root_session_id",
        "scope", "binding_sha256_before", "binding_sha256_after", "product_cleanup_receipt_sha256",
        "product_cleanup_scope_digest", "product_cleanup_receipt_raw_b64"}
    if not isinstance(value, dict) or set(value) != fields or value.get("status") != "supplemented":
        raise ReadonlyReconciliationHold("runtime binding supplement result schema is invalid")
    scope = validate_product_scope(value.get("scope"))
    full_scope = validate_product_scope(envelope["scope"] | {"cwd_leaf": scope["cwd_leaf"]})
    if (value.get("root_run_id") != ROOT_ID or scope != full_scope
            or any(value.get(key) != envelope.get(other) for key, other in (
                ("backend_snapshot_sha256", "backend_snapshot_sha256"),
                ("native_root_session_id", "native_root_session_id")))
            or any(not isinstance(value.get(field), str) or not HEX64.fullmatch(value[field]) for field in (
                "backend_snapshot_sha256", "binding_sha256_before", "binding_sha256_after",
                "product_cleanup_receipt_sha256", "product_cleanup_scope_digest"))):
        raise ReadonlyReconciliationHold("runtime result does not match the prepared fixed scope")
    try:
        raw = base64.b64decode(value["product_cleanup_receipt_raw_b64"], validate=True)
        if (base64.b64encode(raw).decode("ascii") != value["product_cleanup_receipt_raw_b64"]
                or hashlib.sha256(raw).hexdigest() != value["product_cleanup_receipt_sha256"]):
            raise ValueError("cleanup digest changed")
        receipt = verify_product_cleanup_receipt(raw, control_key=control_key, expected_scope=full_scope)
    except (TypeError, ValueError) as exc:
        raise ReadonlyReconciliationHold("Product Runner signed cleanup proof is invalid") from exc
    if (receipt.get("cleanup") != "proven"
            or receipt.get("scope_digest") != value["product_cleanup_scope_digest"]):
        raise ReadonlyReconciliationHold("Product Runner did not prove exact process cleanup")
    return full_scope, receipt


def finalize_readonly_market_error(store: AgentResearchStore, *, scope_envelope: object,
                                   runtime_result: object, arguments_by_request: object,
                                   raw_terminal_event: object, terminal_evidence: object,
                                   product_control_key: bytes, operator_uid: int,
                                   operator_name: str) -> dict[str, Any]:
    from .db import execute, fetch_one, transaction
    from .domain_call_admission import acp_binding_sha256
    from .agent_research import AgentConflict, AgentNotFound

    arguments = _validate_arguments(arguments_by_request)
    event, terminal_receipt, cwd_leaf, evidence_sha = _validate_terminal(raw_terminal_event, terminal_evidence)
    if (not isinstance(scope_envelope, dict) or set(scope_envelope) != {
            "schema_version", "scope", "native_root_session_id", "backend_snapshot_sha256"}
            or scope_envelope.get("schema_version") != SCOPE_SCHEMA
            or scope_envelope.get("native_root_session_id") != NATIVE_ROOT_ID
            or not isinstance(scope_envelope.get("scope"), dict)
            or set(scope_envelope["scope"]) != PRODUCT_SCOPE_KEYS - {"cwd_leaf"}
            or scope_envelope["scope"].get("root_run_id") != ROOT_ID
            or not isinstance(scope_envelope.get("backend_snapshot_sha256"), str)
            or not HEX64.fullmatch(scope_envelope["backend_snapshot_sha256"])):
        raise ReadonlyReconciliationHold("prepared Backend scope is invalid")
    if (type(operator_uid) is not int or operator_uid < 0 or operator_uid > 2**32-1
            or not isinstance(operator_name, str) or not operator_name or len(operator_name.encode()) > 256):
        raise ReadonlyReconciliationHold("Engineering operator attribution is invalid")

    full_scope, cleanup = _validate_runtime_result(runtime_result,
        envelope=scope_envelope, control_key=product_control_key)
    if full_scope["cwd_leaf"] != cwd_leaf:
        raise ReadonlyReconciliationHold("cleanup working directory differs from original binding")
    reserved_id = readonly_market_reconciliation_id()
    gate_engine = getattr(store, "runtime_authority_guard_engine", None)
    if gate_engine is None:
        raise ReadonlyReconciliationHold("Backend writer gate is unavailable")
    with transaction(gate_engine) as gate_connection:
        gate_connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        store._lifecycle_lock(gate_connection, "runtime-authority:agent-writers")
        with store._transaction() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            store._lifecycle_lock(connection, "runtime-authority:current")
            store._lifecycle_lock(connection, "workspace-reset|" + WORKSPACE_ID)
            store._require_current_runtime_boot(connection, BOOT_ID, required=True)
            store._lifecycle_lock(connection, "acp-mcp-request:" + REQUEST_ID)
            store._lifecycle_lock(connection, "root:" + ROOT_ID)
            store._lifecycle_lock(connection, "domain-call-session:" + SESSION_ID)
            store._require_lifecycle_workspace(connection, "admin", WORKSPACE_ID, terminal_cleanup=True)
            existing = readonly_market_reconciliation_row(connection, ROOT_ID)
            if existing is not None:
                receipt = existing["receipt"]
                expected_runtime = receipt.get("product_cleanup_receipt_sha256")
                if (receipt.get("operator_uid") != operator_uid or receipt.get("operator_name") != operator_name
                        or receipt.get("terminal_runtime_evidence_sha256") != evidence_sha
                        or receipt.get("readonly_implementation_sources") != _readonly_source_evidence()
                        or receipt.get("scope") != full_scope
                        or receipt.get("backend_snapshot_sha256") != scope_envelope["backend_snapshot_sha256"]
                        or receipt.get("product_cleanup_receipt_sha256") != runtime_result.get("product_cleanup_receipt_sha256")
                        or receipt.get("binding_sha256_before") != runtime_result.get("binding_sha256_before")
                        or receipt.get("binding_sha256_after") != runtime_result.get("binding_sha256_after")
                        or expected_runtime != hashlib.sha256(base64.b64decode(
                            runtime_result.get("product_cleanup_receipt_raw_b64", ""), validate=True)).hexdigest()):
                    raise AgentConflict("read-only reconciliation retry differs from its immutable proof")
                if (event != {"schema_version": "agent-run-lifecycle.v1", "root_run_id": ROOT_ID,
                              "sequence": 38, "outcome": "completed"}
                        or receipt.get("terminal_event_receipt") != terminal_receipt):
                    raise AgentConflict("terminal event differs from the original reconciliation proof")
                readonly_unknown_coverage(connection, ROOT_ID, receipt)
                closed = fetch_one(connection, "SELECT * FROM agent_runtime_turns WHERE root_run_id=:root", {"root": ROOT_ID})
                durable = fetch_one(connection, "SELECT receipt_json FROM agent_runtime_receipts WHERE owner_principal='admin' AND workspace_id=:workspace AND session_id=:session AND sequence=38", {"workspace": WORKSPACE_ID, "session": SESSION_ID})
                if (closed is None or closed["status"] != "completed" or closed["authority_status"] != "closed"
                        or closed["terminal_sequence"] != 38 or closed["terminal_event_sha256"] != terminal_receipt["event_sha256"]
                        or durable is None or durable["receipt_json"] != terminal_receipt):
                    raise AgentConflict("reconciliation retry lacks its original durable closure")
                store._require_acp_root_terminal_safe(connection, ROOT_ID)
                return {"schema_version": SCHEMA, "status": "reconciled", "receipt": receipt,
                        "runtime_lifecycle_receipt": terminal_receipt}

            store._require_current_runtime_boot(connection, BOOT_ID, required=True)
            snapshot = _load_snapshot(connection, store, arguments=arguments,
                native_root_session_id=NATIVE_ROOT_ID, terminal_receipt=terminal_receipt,
                cwd_leaf=cwd_leaf, terminal_evidence_sha256=evidence_sha, lock_rows=True)
            if (snapshot["scope"] != full_scope
                    or snapshot["snapshot_sha256"] != scope_envelope["backend_snapshot_sha256"]):
                raise AgentConflict("Backend snapshot changed after process cleanup was prepared")
            root = snapshot["root"]
            if root.get("authority_status") != "active":
                raise AgentConflict("Root authority is no longer active")

            unknown = snapshot["unknown_row"]
            unknown_descriptor = {
                "mcp_request_id": REQUEST_ID, "sequence": 8,
                "event_sha256": unknown["event_sha256"],
                "arguments_sha256": unknown["arguments_sha256"],
                "settlement_sha256": acp_binding_sha256(unknown["settlement_json"]),
                "status": "unknown",
            }
            payload = {
                "schema_version": SCHEMA,
                "root_run_id": ROOT_ID,
                "scope": {key: full_scope[key] for key in PRODUCT_SCOPE_KEYS},
                "native_root_session_id": NATIVE_ROOT_ID,
                "authority_epoch": snapshot["facts"]["runtime_authority"]["epoch"],
                "agent_run_id": snapshot["run"]["run_id"],
                "backend_snapshot_sha256": snapshot["snapshot_sha256"],
                "original_ingress_rows_sha256": snapshot["original_ingress_rows_sha256"],
                "unknown_count": 1,
                "unknown_disposition": OUTCOME,
                "unknown_ingress": unknown_descriptor,
                "domain_claim_count": 0,
                "terminal_unknown_claims_sha256": snapshot["terminal_unknown_claims_sha256"],
                "product_cleanup_receipt_sha256": runtime_result["product_cleanup_receipt_sha256"],
                "product_cleanup_scope_digest": runtime_result["product_cleanup_scope_digest"],
                "binding_sha256_before": runtime_result["binding_sha256_before"],
                "binding_sha256_after": runtime_result["binding_sha256_after"],
                "terminal_event_receipt": terminal_receipt,
                "terminal_runtime_evidence_sha256": evidence_sha,
                "readonly_implementation_sources": snapshot["facts"]["readonly_implementation_sources"],
                "operator_uid": operator_uid,
                "operator_name": operator_name,
            }
            proof = {**payload, "receipt_sha256": _digest(payload)}
            # The reserved audit key and closed proof schema make the marker
            # tamper-evident; ordinary Product audit writes reject acp_control.
            run = fetch_one(connection, "SELECT * FROM agent_runs WHERE run_id=:run FOR UPDATE",
                            {"run": snapshot["run"]["run_id"]})
            if run is None:
                raise AgentNotFound("exact root AgentRun disappeared")
            store._record_audit_row(run, action=ACTION, outcome=OUTCOME,
                resource_type="runtime_root", resource_id=ROOT_ID,
                detail={"acp_control": proof}, connection=connection, audit_id=reserved_id)
            store.consume_runtime_lifecycle_event(event, _connection=connection,
                trusted_owner="admin", trusted_workspace=WORKSPACE_ID,
                trusted_session_id=SESSION_ID, trusted_trace_id=TRACE_ID,
                trusted_boot_id=BOOT_ID)
    return {"schema_version": SCHEMA, "status": "reconciled", "receipt": proof,
            "runtime_lifecycle_receipt": terminal_receipt}


def _cli(argv: list[str] | None = None) -> int:
    from .historical_audit_reconciliation import (
        _ExistingSchemaAgentResearchStore, _read_control_key,
        _read_regular_json, _canonical_result,
    )
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--arguments-file", required=True, type=Path)
    prepare.add_argument("--terminal-event-file", required=True, type=Path)
    prepare.add_argument("--terminal-evidence-file", required=True, type=Path)
    prepare.add_argument("--native-root-session-id", required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--arguments-file", required=True, type=Path)
    finalize.add_argument("--terminal-event-file", required=True, type=Path)
    finalize.add_argument("--terminal-evidence-file", required=True, type=Path)
    finalize.add_argument("--scope-file", required=True, type=Path)
    finalize.add_argument("--runtime-result-file", required=True, type=Path)
    finalize.add_argument("--control-fd", required=True, type=int)
    finalize.add_argument("--operator-uid", required=True, type=int)
    finalize.add_argument("--operator-name", required=True)
    args = parser.parse_args(argv)
    store = None
    try:
        argument_file = _read_regular_json(str(args.arguments_file), limit=MAX_FILE)
        terminal_event = _read_regular_json(str(args.terminal_event_file), limit=65_536)
        terminal_evidence = _read_regular_json(str(args.terminal_evidence_file), limit=65_536)
        arguments = _validate_arguments(argument_file)
        store = _ExistingSchemaAgentResearchStore()
        if args.operation == "prepare":
            result = prepare_readonly_market_error(store, arguments_by_request=arguments,
                raw_terminal_event=terminal_event, terminal_evidence=terminal_evidence,
                native_root_session_id=args.native_root_session_id)
        else:
            scope = _read_regular_json(str(args.scope_file), limit=32_768)
            runtime = _read_regular_json(str(args.runtime_result_file), limit=32_768)
            key = _read_control_key(args.control_fd)
            result = finalize_readonly_market_error(store, scope_envelope=scope,
                runtime_result=runtime, arguments_by_request=arguments,
                raw_terminal_event=terminal_event, terminal_evidence=terminal_evidence,
                product_control_key=key, operator_uid=args.operator_uid,
                operator_name=args.operator_name)
        _canonical_result(result)
    except Exception as exc:
        if type(exc).__name__.endswith(("Conflict", "NotFound", "Unauthorized")):
            print("HOLD: Backend evidence failed exact reconciliation checks", file=sys.stderr)
            return 2
        print(f"HOLD: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
