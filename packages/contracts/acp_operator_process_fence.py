"""Closed Backend/Runtime contract for an ADR-0104 operator fence.

The contract records an Engineering process-fence claim separately from an
Adapter lifecycle event. It never manufactures an Adapter sequence, EXIT, or
cleanup receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .acp_product_slot import PRODUCT_SCOPE_KEYS, ProductSlotContractError, validate_product_scope
from .acp_product_prebind import DEPLOYMENT_FIELDS, START_BINDING_FIELDS, START_BINDING_SCHEMA, VOLUME_FIELDS


PROCESS_FENCE_REQUEST_SCHEMA = "byq-acp-operator-process-fence-request.v1"
PROCESS_FENCE_SCHEMA = "byq-acp-operator-process-fence.v1"
INTERRUPTION_SCHEMA = "byq-agent-root-operator-interruption.v1"
ACK_REQUEST_SCHEMA = "byq-acp-operator-process-fence-ack-request.v1"
ACK_SCHEMA = "byq-acp-operator-process-fence-ack-confirm.v1"
FENCE_CLOSE_RECEIPT_SCHEMA = "byq-acp-operator-process-fence-close-receipt.v1"
PREIMAGE_SCHEMA = "byq-acp-r2-preimage.v1"

PROCESS_FENCE_ACTION = "acp_operator_process_fence_proof"
PROCESS_FENCE_IDEMPOTENCY_PREFIX = "acp-operator-process-fence:"
ACK_ACTION = "acp_operator_process_fence_ack_confirm"
ACK_IDEMPOTENCY_PREFIX = "acp-operator-process-fence-ack:"
PROCESS_FENCE_RESERVED_PREFIXES = (
    PROCESS_FENCE_IDEMPOTENCY_PREFIX,
    ACK_IDEMPOTENCY_PREFIX,
)

PROCESS_FENCE_REQUEST_FIELDS = frozenset({
    "schema_version", "operation_id", "scope", "authority", "old_runner",
    "native_fence", "successor", "prestart_binding", "runtime_binding_observation",
})
ROOT_BINDING_OBSERVATION_FIELDS = frozenset({
    "schema_version", "raw_binding_utf8", "raw_sha256", "evidence_sha256", "observed_at",
})
ROOT_BINDING_V2_FIELDS = frozenset({
    "schema_version", "session_id", "trace_id", "owner_principal", "workspace_id",
    "root_run_id", "native_session_id", "runtime_generation", "model_provider", "model_id",
    "cwd", "previous_boot_id", "previous_authority_epoch", "sequence", "settlement_receipt",
    "domain_call_sequence", "domain_call_drained_sequence", "native_session_close_confirmed",
    "process_exit_confirmed", "cleanup_unconfirmed", "closed", "operator_scope",
    "operator_binding",
})
AUTHORITY_FIELDS = frozenset({"previous_boot_id", "previous_epoch", "current_boot_id", "current_epoch"})
RUNNER_FIELDS = frozenset({
    "runner_instance_id", "runner_boot_id", "state_generation",
    "signed_instance_sha256", "prestart_binding_sha256",
    "deployment", "state_volume",
})
SUCCESSOR_FIELDS = frozenset({
    "runner_instance_id", "runner_boot_id", "state_generation",
    "signed_instance_sha256", "active_binding_receipt_sha256", "tombstone_sha256",
})
NATIVE_FENCE_FIELDS = frozenset({
    "old_container_stopped", "pid_count", "paused", "restarting",
    "restart_disabled", "pre_finalize_evidence_sha256", "pre_finalize_observed_at",
})
PROOF_FIELDS = frozenset({
    "schema_version", "operation_id", "request_sha256", "scope", "authority",
    "old_runner", "native_fence", "successor", "backend_preimage",
    "prestart_binding", "runtime_binding_observation",
    "allowed_poststate_delta", "expected_poststate_sha256", "backend_snapshot_sha256",
    "runtime_binding_sha256", "engineering_evidence_sha256",
    "terminal_acp_ingress_sequence", "terminal_acp_ingress_sha256",
    "terminal_unknown_claim_count", "terminal_unknown_claims_sha256",
    "operator_interruption", "process_fence_receipt_sha256", "operator", "disposition",
    "receipt_sha256",
})
INTERRUPTION_FIELDS = frozenset({
    "schema_version", "operation_id", "root_run_id", "outcome",
    "process_fence_receipt_sha256", "terminal_acp_ingress_sequence",
    "terminal_acp_ingress_sha256", "terminal_unknown_claim_count",
    "terminal_unknown_claims_sha256", "receipt_sha256",
})
OPERATOR_FIELDS = frozenset({"uid", "name"})
PREIMAGE_FIELDS = frozenset({"schema_version", "rows", "sha256"})
PREIMAGE_ROW_FIELDS = frozenset({"table", "key", "row"})
DELTA_FIELDS = frozenset({"close_at", "root", "agent_runs", "inserted_proof_operations_audit_id", "sha256"})
DELTA_ROOT_FIELDS = frozenset({"id", "before", "after"})
DELTA_RUN_FIELDS = frozenset({"id", "before", "after"})
DELTA_ROOT_MUTABLE = frozenset({
    "status", "authority_status", "updated_at", "terminal_acp_ingress_sequence",
    "terminal_acp_ingress_sha256", "terminal_unknown_claim_count",
    "terminal_unknown_claims_sha256",
})
DELTA_RUN_MUTABLE = frozenset({"status", "authority_status", "updated_at", "version"})

ACK_REQUEST_FIELDS = frozenset({
    "schema_version", "operation_id", "proof_receipt_sha256", "runtime_ack",
    "domain_call_drain", "slot_release", "engineering_evidence_sha256",
    "confirmed_at", "scope", "authority", "runner", "superseded_terminal",
})
RUNTIME_ACK_FIELDS = frozenset({
    "schema_version", "root_run_id", "runtime_boot_id", "scope_sha256",
    "process_fence_receipt_sha256", "operator_interruption_receipt_sha256",
    "root_binding_sha256", "terminal_ack_sha256", "acknowledged_at",
})
DOMAIN_DRAIN_FIELDS = frozenset({
    "schema_version", "root_run_id", "last_domain_sequence", "drained_sequence",
    "drain_receipt_sha256",
})
SLOT_RELEASE_FIELDS = frozenset({
    "schema_version", "workspace_id", "root_run_id", "scope_sha256",
    "process_fence_receipt_sha256", "tombstone_sha256", "drained_sequence",
    "status", "release_receipt_sha256", "released_at",
})
ACK_RECEIPT_FIELDS = frozenset({
    "schema_version", "operation_id", "proof_audit_id", "proof_receipt_sha256",
    "operator_interruption_receipt_sha256", "scope", "authority", "runner",
    "runtime_ack_sha256", "root_binding_sha256", "terminal_ack_sha256",
    "last_domain_sequence", "drained_sequence", "drain_receipt_sha256",
    "slot_release_sha256", "confirmed_at", "operator", "engineering_evidence_sha256",
    "receipt_sha256", "superseded_terminal",
})
FENCE_CLOSE_RECEIPT_FIELDS = frozenset({
    "schema_version", "operation_id", "workspace_id", "root_run_id",
    "process_fence_receipt_sha256", "operator_interruption", "scope", "authority",
    "runner", "engineering_evidence_sha256", "runtime_binding_sha256",
})
ACK_RUNNER_FIELDS = frozenset({"old_runner_instance_id", "successor_runner_instance_id", "tombstone_sha256"})
OPERATOR_OBSERVATION_SCHEMA = "byq-runtime-operator-observation.v1"
OPERATOR_OBSERVATION_FIELDS = frozenset({
    "schema_version", "operation_id", "close_receipt_sha256", "process_fence_receipt_sha256",
    "operator_interruption_receipt_sha256", "scope", "authority", "runner",
    "engineering_evidence_sha256", "runtime_binding_sha256", "runtime_ack",
    "domain_call_drain", "slot_release", "observed_at", "superseded_terminal",
})
SUPERSEDED_TERMINAL_FIELDS = frozenset({
    "schema_version", "root_run_id", "sequence", "event_sha256", "receipt_sha256",
})

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class OperatorProcessFenceContractError(ValueError):
    """The closed operator process-fence contract is malformed."""


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise OperatorProcessFenceContractError("operator process-fence value is not canonical JSON") from exc


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _fail() -> None:
    raise OperatorProcessFenceContractError("operator process-fence fields are invalid")


def _text(value: object, *, maximum: int = 512) -> bool:
    return isinstance(value, str) and len(value.encode("utf-8")) <= maximum and _TEXT.fullmatch(value) is not None


def _hex(value: object, length: int = 64) -> bool:
    return isinstance(value, str) and (_HEX64 if length == 64 else _HEX32).fullmatch(value) is not None


def _utc(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_process_fence_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != PROCESS_FENCE_REQUEST_FIELDS:
        _fail()
    value = dict(raw)
    if (value.get("schema_version") != PROCESS_FENCE_REQUEST_SCHEMA
            or not _hex(value.get("operation_id"), 32)):
        _fail()
    try:
        scope = validate_product_scope(value.get("scope"))
    except ProductSlotContractError as exc:
        raise OperatorProcessFenceContractError("operator process-fence scope is invalid") from exc
    authority = value.get("authority")
    if not isinstance(authority, Mapping) or set(authority) != AUTHORITY_FIELDS:
        _fail()
    if (not _hex(authority.get("previous_boot_id"), 32)
            or not _hex(authority.get("current_boot_id"), 32)
            or type(authority.get("previous_epoch")) is not int or authority["previous_epoch"] < 1
            or type(authority.get("current_epoch")) is not int or authority["current_epoch"] < 1
            or authority.get("previous_boot_id") != scope["runtime_boot_id"]
            or (authority["current_boot_id"] == authority["previous_boot_id"]
                and authority["current_epoch"] != authority["previous_epoch"])
            or (authority["current_boot_id"] != authority["previous_boot_id"]
                and authority["current_epoch"] <= authority["previous_epoch"])):
        _fail()
    old = value.get("old_runner")
    if not isinstance(old, Mapping) or set(old) != RUNNER_FIELDS:
        _fail()
    if (not _hex(old.get("runner_instance_id")) or not _hex(old.get("runner_boot_id"), 32)
            or not _hex(old.get("state_generation"))
            or not _hex(old.get("signed_instance_sha256"))
            or not _hex(old.get("prestart_binding_sha256"))):
        _fail()
    deployment = old.get("deployment")
    volume = old.get("state_volume")
    if not isinstance(deployment, Mapping) or set(deployment) != DEPLOYMENT_FIELDS:
        _fail()
    if (not all(_text(deployment.get(key)) for key in DEPLOYMENT_FIELDS - {"image_digest"})
            or not isinstance(deployment.get("image_digest"), str)
            or _DIGEST.fullmatch(deployment["image_digest"]) is None):
        _fail()
    if not isinstance(volume, Mapping) or set(volume) != VOLUME_FIELDS or not all(_text(volume.get(key)) for key in VOLUME_FIELDS):
        _fail()
    native = value.get("native_fence")
    if not isinstance(native, Mapping) or set(native) != NATIVE_FENCE_FIELDS:
        _fail()
    if (native.get("old_container_stopped") is not True or type(native.get("pid_count")) is not int
            or native["pid_count"] != 0 or native.get("paused") is not False
            or native.get("restarting") is not False or native.get("restart_disabled") is not True
            or not _hex(native.get("pre_finalize_evidence_sha256"))
            or not _utc(native.get("pre_finalize_observed_at"))):
        _fail()
    successor = value.get("successor")
    if not isinstance(successor, Mapping) or set(successor) != SUCCESSOR_FIELDS:
        _fail()
    if (not _hex(successor.get("runner_instance_id"))
            or successor["runner_instance_id"] == old["runner_instance_id"]
            or not _hex(successor.get("runner_boot_id"), 32)
            or not _hex(successor.get("state_generation"))
            or successor.get("state_generation") != old.get("state_generation")
            or not _hex(successor.get("signed_instance_sha256"))
            or not _hex(successor.get("active_binding_receipt_sha256"))
            or not _hex(successor.get("tombstone_sha256"))):
        _fail()
    binding = value.get("prestart_binding")
    if (not isinstance(binding, Mapping) or set(binding) != START_BINDING_FIELDS
            or binding.get("schema_version") != START_BINDING_SCHEMA
            or not _hex(digest(dict(binding)))
            or digest(dict(binding)) != old["prestart_binding_sha256"]):
        _fail()
    if any(binding.get(field) != old.get(field) for field in (
            "runner_instance_id", "runner_boot_id", "state_generation", "signed_instance_sha256")):
        _fail()
    observation = value.get("runtime_binding_observation")
    if not isinstance(observation, Mapping) or set(observation) != ROOT_BINDING_OBSERVATION_FIELDS:
        _fail()
    if (observation.get("schema_version") != "byq-engineering-runtime-root-binding-observation.v1"
            or not isinstance(observation.get("raw_binding_utf8"), str)
            or len(observation["raw_binding_utf8"].encode("utf-8")) > 256 * 1024
            or not _hex(observation.get("raw_sha256"))
            or not _hex(observation.get("evidence_sha256"))
            or not _utc(observation.get("observed_at"))):
        _fail()
    raw_binding = observation["raw_binding_utf8"].encode("utf-8")
    if hashlib.sha256(raw_binding).hexdigest() != observation["raw_sha256"]:
        _fail()
    try:
        parsed_binding = json.loads(raw_binding.decode("utf-8"), object_pairs_hook=_strict_object,
                                    parse_constant=_reject_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise OperatorProcessFenceContractError("runtime binding observation is invalid") from exc
    if not isinstance(parsed_binding, dict) or set(parsed_binding) != ROOT_BINDING_V2_FIELDS:
        _fail()
    try:
        binding_scope = validate_product_scope(parsed_binding.get("operator_scope"))
    except (ProductSlotContractError, TypeError) as exc:
        raise OperatorProcessFenceContractError("runtime binding scope is invalid") from exc
    runtime_binding = parsed_binding.get("operator_binding")
    if (parsed_binding.get("schema_version") != "byq-acp-root-binding.v2"
            or not isinstance(runtime_binding, Mapping) or set(runtime_binding) != START_BINDING_FIELDS
            or runtime_binding.get("schema_version") != START_BINDING_SCHEMA
            or parsed_binding.get("closed") is not False
            or parsed_binding.get("native_session_close_confirmed") is not False
            or parsed_binding.get("process_exit_confirmed") is not False
            or parsed_binding.get("cleanup_unconfirmed") is not False
            or type(parsed_binding.get("sequence")) is not int
            or type(parsed_binding.get("domain_call_sequence")) is not int
            or type(parsed_binding.get("domain_call_drained_sequence")) is not int
            or parsed_binding.get("domain_call_drained_sequence") != parsed_binding.get("domain_call_sequence")
            or not isinstance(parsed_binding.get("cwd"), str)
            or not parsed_binding["cwd"].startswith("/")
            or not isinstance(parsed_binding.get("native_session_id"), str)
            or not parsed_binding["native_session_id"]
            or binding_scope != scope
            or parsed_binding.get("session_id") != scope["session_id"]
            or parsed_binding.get("trace_id") != scope["trace_id"]
            or parsed_binding.get("owner_principal") != scope["owner_principal"]
            or parsed_binding.get("workspace_id") != scope["workspace_id"]
            or parsed_binding.get("root_run_id") != scope["root_run_id"]
            or parsed_binding.get("runtime_generation") != scope["generation_id"]
            or parsed_binding.get("previous_boot_id") != scope["runtime_boot_id"]
            or runtime_binding != dict(binding)
            or parsed_binding["cwd"].rsplit("/", 1)[-1] != scope["cwd_leaf"]):
        _fail()
    return value


def parsed_runtime_binding_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return the V2 binding whose exact UTF-8 bytes were independently hashed."""
    return json.loads(raw["raw_binding_utf8"], object_pairs_hook=_strict_object,
                      parse_constant=_reject_constant)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            _fail()
        result[key] = item
    return result


def _reject_constant(_value: str) -> None:
    _fail()


def validate_operator_interruption(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != INTERRUPTION_FIELDS:
        _fail()
    value = dict(raw)
    if (value.get("schema_version") != INTERRUPTION_SCHEMA
            or not _hex(value.get("operation_id"), 32)
            or not _hex(value.get("root_run_id"), 32)
            or value.get("outcome") != "interrupted"
            or not _hex(value.get("process_fence_receipt_sha256"))
            or type(value.get("terminal_acp_ingress_sequence")) is not int
            or value["terminal_acp_ingress_sequence"] < 0
            or not _hex(value.get("terminal_acp_ingress_sha256"))
            or type(value.get("terminal_unknown_claim_count")) is not int
            or value["terminal_unknown_claim_count"] != 0
            or not _hex(value.get("terminal_unknown_claims_sha256"))
            or not _hex(value.get("receipt_sha256"))):
        _fail()
    payload = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if digest(payload) != value["receipt_sha256"]:
        _fail()
    return value


def validate_process_fence_proof(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != PROOF_FIELDS:
        _fail()
    value = dict(raw)
    if (value.get("schema_version") != PROCESS_FENCE_SCHEMA
            or not _hex(value.get("operation_id"), 32)
            or not _hex(value.get("request_sha256"))):
        _fail()
    request = {
        "schema_version": PROCESS_FENCE_REQUEST_SCHEMA,
        "operation_id": value["operation_id"],
        "scope": value.get("scope"),
        "authority": value.get("authority"),
        "old_runner": value.get("old_runner"),
        "native_fence": value.get("native_fence"),
        "successor": value.get("successor"),
        "prestart_binding": value.get("prestart_binding"),
        "runtime_binding_observation": value.get("runtime_binding_observation"),
    }
    validated_request = validate_process_fence_request(request)
    if digest(validated_request) != value["request_sha256"]:
        _fail()
    if (not isinstance(value.get("scope"), Mapping) or set(value["scope"]) != PRODUCT_SCOPE_KEYS
            or not isinstance(value.get("authority"), Mapping) or set(value["authority"]) != AUTHORITY_FIELDS
            or not isinstance(value.get("old_runner"), Mapping) or set(value["old_runner"]) != RUNNER_FIELDS
            or not isinstance(value.get("native_fence"), Mapping)
            or set(value["native_fence"]) != NATIVE_FENCE_FIELDS
            or not isinstance(value.get("successor"), Mapping)
            or set(value["successor"]) != SUCCESSOR_FIELDS):
        _fail()
    preimage = value.get("backend_preimage")
    if not isinstance(preimage, Mapping) or set(preimage) != PREIMAGE_FIELDS:
        _fail()
    rows = preimage.get("rows")
    if (preimage.get("schema_version") != PREIMAGE_SCHEMA or not isinstance(rows, list)
            or len(rows) > 100_000 or not _hex(preimage.get("sha256"))
            or any(not isinstance(row, Mapping) or set(row) != PREIMAGE_ROW_FIELDS
                   or not _text(row.get("table"), maximum=128)
                   or not isinstance(row.get("key"), dict) or not isinstance(row.get("row"), dict)
                   for row in rows)
            or digest({"schema_version": PREIMAGE_SCHEMA, "rows": rows}) != preimage["sha256"]):
        _fail()
    delta = value.get("allowed_poststate_delta")
    if not isinstance(delta, Mapping) or set(delta) != DELTA_FIELDS:
        _fail()
    if (not _utc(delta.get("close_at")) or not isinstance(delta.get("root"), Mapping)
            or set(delta["root"]) != DELTA_ROOT_FIELDS
            or not isinstance(delta["root"].get("before"), dict)
            or not isinstance(delta["root"].get("after"), dict)
            or not isinstance(delta.get("agent_runs"), list)
            or not _text(delta.get("inserted_proof_operations_audit_id"), maximum=256)
            or not _hex(delta.get("sha256"))):
        _fail()
    if any(not isinstance(run, Mapping) or set(run) != DELTA_RUN_FIELDS
           or not _text(run.get("id"), maximum=256)
           or not isinstance(run.get("before"), dict) or not isinstance(run.get("after"), dict)
           for run in delta["agent_runs"]):
        _fail()
    delta_payload = {key: item for key, item in delta.items() if key != "sha256"}
    if digest(delta_payload) != delta["sha256"]:
        _fail()
    if (not _hex(value.get("expected_poststate_sha256"))
            or not _hex(value.get("backend_snapshot_sha256"))
            or not _hex(value.get("runtime_binding_sha256"))
            or not _hex(value.get("engineering_evidence_sha256"))
            or value["backend_snapshot_sha256"] != preimage["sha256"]
            or type(value.get("terminal_acp_ingress_sequence")) is not int
            or value["terminal_acp_ingress_sequence"] < 0
            or not _hex(value.get("terminal_acp_ingress_sha256"))
            or type(value.get("terminal_unknown_claim_count")) is not int
            or value["terminal_unknown_claim_count"] != 0
            or not _hex(value.get("terminal_unknown_claims_sha256"))):
        _fail()
    scope = validate_product_scope(value["scope"])
    root_id = scope["root_run_id"]
    if (not isinstance(value.get("prestart_binding"), Mapping)
            or set(value["prestart_binding"]) != START_BINDING_FIELDS
            or not isinstance(value.get("runtime_binding_observation"), Mapping)
            or set(value["runtime_binding_observation"]) != ROOT_BINDING_OBSERVATION_FIELDS):
        _fail()
    if (value["runtime_binding_observation"].get("raw_sha256") != value["runtime_binding_sha256"]):
        _fail()
    allowed_tables = {
        "agent_runtime_turns", "agent_runs", "workspaces", "users", "workspace_memberships",
        "product_conversations", "agent_runtime_authority_current", "agent_runtime_authority_boot_receipts",
        "agent_runtime_registrations", "agent_acp_native_agent_registrations",
        "agent_acp_tool_ingress_observations", "agent_acp_domain_call_observations",
        "agent_domain_call_evidence", "agent_domain_correction_buckets", "agent_domain_call_claims",
        "agent_approvals", "agent_audit", "agent_runtime_receipts", "operations_audit",
    }
    seen_rows: set[bytes] = set()
    previous_sort: tuple[str, bytes] | None = None
    for row in rows:
        if row["table"] not in allowed_tables:
            _fail()
        encoded_key = canonical_json(row["key"])
        unique = canonical_json([row["table"], row["key"]])
        sort_key = (row["table"], encoded_key)
        if unique in seen_rows or (previous_sort is not None and sort_key < previous_sort):
            _fail()
        seen_rows.add(unique)
        previous_sort = sort_key
        if any(row["row"].get(key) != item for key, item in row["key"].items()):
            _fail()
    root_rows = [row["row"] for row in rows if row["table"] == "agent_runtime_turns"
                 and row["row"].get("root_run_id") == root_id]
    agent_runs = [row["row"] for row in rows if row["table"] == "agent_runs"
                  and row["row"].get("root_run_id") == root_id]
    if len(root_rows) != 1 or not agent_runs:
        _fail()
    root_row = root_rows[0]
    conversations = [row["row"] for row in rows if row["table"] == "product_conversations"]
    workspaces = [row["row"] for row in rows if row["table"] == "workspaces"]
    users = [row["row"] for row in rows if row["table"] == "users"]
    memberships = [row["row"] for row in rows if row["table"] == "workspace_memberships"]
    root_agent_runs = [row for row in agent_runs if row.get("parent_run_id") is None]
    if (len(conversations) != 1 or conversations[0].get("owner_principal") != scope["owner_principal"]
            or conversations[0].get("runtime_session_id") != scope["session_id"]
            or conversations[0].get("trace_id") != scope["trace_id"]
            or conversations[0].get("status") != "active"
            or len(workspaces) != 1 or workspaces[0].get("workspace_id") != scope["workspace_id"]
            or workspaces[0].get("kind") != "personal" or workspaces[0].get("status") != "active"
            or workspaces[0].get("reset_id") is not None
            or len(users) != 1 or users[0].get("username") != scope["owner_principal"]
            or users[0].get("status") != "active"
            or users[0].get("user_id") != workspaces[0].get("owner_user_id")
            or len(memberships) != 1 or memberships[0].get("user_id") != users[0].get("user_id")
            or memberships[0].get("workspace_id") != scope["workspace_id"]
            or memberships[0].get("role") != "owner" or memberships[0].get("status") != "active"
            or len(root_agent_runs) != 1 or root_agent_runs[0].get("status") != "active"
            or root_agent_runs[0].get("authority_status") not in {"active", "authority_revoked_unconfirmed"}
            or value.get("terminal_unknown_claim_count") != 0):
        _fail()
    root_delta = delta["root"]
    if (root_delta.get("id") != root_id
            or root_row.get("owner_principal") != scope["owner_principal"]
            or root_row.get("workspace_id") != scope["workspace_id"]
            or root_row.get("session_id") != scope["session_id"]
            or root_row.get("trace_id") != scope["trace_id"]
            or root_row.get("status") != "active"
            or root_row.get("authority_status") not in {"active", "authority_revoked_unconfirmed"}
            or root_row.get("terminal_sequence") is not None
            or root_row.get("terminal_event_sha256") is not None
            or set(root_delta["before"]) != DELTA_ROOT_MUTABLE
            or set(root_delta["after"]) != DELTA_ROOT_MUTABLE
            or any(root_delta["before"].get(key) != root_row.get(key) for key in DELTA_ROOT_MUTABLE)
            or root_delta["after"].get("status") != "interrupted"
            or root_delta["after"].get("authority_status") != "closed"
            or root_delta["after"].get("updated_at") != delta["close_at"]
            or any(root_delta["after"].get(key) != value.get(key)
                   for key in ("terminal_acp_ingress_sequence", "terminal_acp_ingress_sha256",
                               "terminal_unknown_claim_count", "terminal_unknown_claims_sha256"))):
        _fail()
    run_delta = delta["agent_runs"]
    active_runs = [row for row in agent_runs if row.get("status") == "active"
                   and row.get("authority_status") in {"active", "authority_revoked_unconfirmed"}]
    terminal_runs = [row for row in agent_runs if row not in active_runs]
    if (len(run_delta) != len(active_runs)
            or {item["id"] for item in run_delta} != {row.get("run_id") for row in active_runs}
            or any(row.get("status") not in {"completed", "failed", "cancelled", "interrupted"}
                   or row.get("authority_status") != "closed" for row in terminal_runs)):
        _fail()
    run_by_id = {item["id"]: item for item in run_delta}
    for row in active_runs:
        item = run_by_id[row["run_id"]]
        if (row.get("owner_principal") != scope["owner_principal"]
                or row.get("workspace_id") != scope["workspace_id"]
                or row.get("session_id") != scope["session_id"]
                or row.get("trace_id") != scope["trace_id"]
                or set(item["before"]) != DELTA_RUN_MUTABLE or set(item["after"]) != DELTA_RUN_MUTABLE
                or any(item["before"].get(key) != row.get(key) for key in DELTA_RUN_MUTABLE)
                or item["after"].get("status") != "interrupted"
                or item["after"].get("authority_status") != "closed"
                or item["after"].get("updated_at") != delta["close_at"]
                or type(item["before"].get("version")) is not int
                or item["after"].get("version") != item["before"]["version"] + 1):
            _fail()
    if any(row.get("owner_principal") != scope["owner_principal"]
           or row.get("workspace_id") != scope["workspace_id"]
           or row.get("session_id") != scope["session_id"]
           or row.get("trace_id") != scope["trace_id"]
           for row in terminal_runs):
        _fail()
    expected_audit_id = "ops_acp_process_fence_" + hashlib.sha256(
        (PROCESS_FENCE_IDEMPOTENCY_PREFIX + value["operation_id"]).encode("ascii")
    ).hexdigest()
    if delta["inserted_proof_operations_audit_id"] != expected_audit_id:
        _fail()
    expected_rows = []
    run_after = {item["id"]: item["after"] for item in run_delta}
    for item in rows:
        copied = {**item, "row": dict(item["row"])}
        if copied["table"] == "agent_runtime_turns" and copied["row"].get("root_run_id") == root_id:
            copied["row"].update(root_delta["after"])
        elif copied["table"] == "agent_runs" and copied["row"].get("run_id") in run_after:
            copied["row"].update(run_after[copied["row"]["run_id"]])
        expected_rows.append(copied)
    if digest({"schema_version": PREIMAGE_SCHEMA, "rows": expected_rows}) != value["expected_poststate_sha256"]:
        _fail()
    interruption = validate_operator_interruption(value.get("operator_interruption"))
    if (interruption["operation_id"] != value["operation_id"]
            or interruption["root_run_id"] != value["scope"].get("root_run_id")
            or interruption["process_fence_receipt_sha256"] != value["process_fence_receipt_sha256"]
            or interruption["terminal_acp_ingress_sequence"] != value["terminal_acp_ingress_sequence"]
            or interruption["terminal_acp_ingress_sha256"] != value["terminal_acp_ingress_sha256"]
            or interruption["terminal_unknown_claim_count"] != value["terminal_unknown_claim_count"]
            or interruption["terminal_unknown_claims_sha256"] != value["terminal_unknown_claims_sha256"]):
        _fail()
    operator = value.get("operator")
    if (not isinstance(operator, Mapping) or set(operator) != OPERATOR_FIELDS
            or type(operator.get("uid")) is not int or not 0 <= operator["uid"] <= 2**32 - 1
            or not _text(operator.get("name"), maximum=256)
            or value.get("disposition") != "operator_process_fence_confirmed"
            or not _hex(value.get("process_fence_receipt_sha256"))
            or not _hex(value.get("receipt_sha256"))):
        _fail()
    process_payload = {key: item for key, item in value.items()
                       if key not in {"operator_interruption", "process_fence_receipt_sha256", "receipt_sha256"}}
    if digest(process_payload) != value["process_fence_receipt_sha256"]:
        _fail()
    full_payload = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if digest(full_payload) != value["receipt_sha256"]:
        _fail()
    return value


def validate_ack_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != ACK_REQUEST_FIELDS:
        _fail()
    value = dict(raw)
    try:
        scope = validate_product_scope(value.get("scope"))
    except (ProductSlotContractError, TypeError) as exc:
        raise OperatorProcessFenceContractError("operator ACK scope is invalid") from exc
    if (value.get("schema_version") != ACK_REQUEST_SCHEMA
            or not _hex(value.get("operation_id"), 32)
            or not _hex(value.get("proof_receipt_sha256"))
            or not _hex(value.get("engineering_evidence_sha256"))
            or not _utc(value.get("confirmed_at"))
            or not isinstance(value.get("authority"), Mapping)
            or set(value["authority"]) != AUTHORITY_FIELDS
            or not isinstance(value.get("runner"), Mapping)
            or set(value["runner"]) != ACK_RUNNER_FIELDS
            or not all(_hex(value["runner"].get(key)) for key in ACK_RUNNER_FIELDS)
            or value["authority"].get("previous_boot_id") != scope["runtime_boot_id"]
            or value["runner"].get("tombstone_sha256") is None):
        _fail()
    superseded = validate_superseded_terminal(value.get("superseded_terminal"),
                                              root_run_id=value["scope"]["root_run_id"])
    runtime_ack = value.get("runtime_ack")
    drain = value.get("domain_call_drain")
    release = value.get("slot_release")
    if not isinstance(runtime_ack, Mapping) or set(runtime_ack) != RUNTIME_ACK_FIELDS:
        _fail()
    if not isinstance(drain, Mapping) or set(drain) != DOMAIN_DRAIN_FIELDS:
        _fail()
    if not isinstance(release, Mapping) or set(release) != SLOT_RELEASE_FIELDS:
        _fail()
    if (runtime_ack.get("schema_version") != "byq-runtime-operator-terminal-ack.v1"
            or not _hex(runtime_ack.get("root_run_id"), 32)
            or not _hex(runtime_ack.get("runtime_boot_id"), 32)
            or any(not _hex(runtime_ack.get(field)) for field in (
                "scope_sha256", "process_fence_receipt_sha256", "operator_interruption_receipt_sha256",
                "root_binding_sha256", "terminal_ack_sha256"))
            or not _utc(runtime_ack.get("acknowledged_at"))
            or runtime_ack.get("scope_sha256") != digest(value["scope"])
            or runtime_ack.get("root_run_id") != value["scope"].get("root_run_id")
            or runtime_ack.get("runtime_boot_id") != value["scope"].get("runtime_boot_id")):
        _fail()
    if (drain.get("schema_version") != "byq-runtime-domain-call-drain.v1"
            or drain.get("root_run_id") != runtime_ack.get("root_run_id")
            or type(drain.get("last_domain_sequence")) is not int or drain["last_domain_sequence"] < 0
            or type(drain.get("drained_sequence")) is not int
            or drain["drained_sequence"] != drain["last_domain_sequence"]
            or not _hex(drain.get("drain_receipt_sha256"))
            or digest({key: item for key, item in drain.items() if key != "drain_receipt_sha256"})
                != drain["drain_receipt_sha256"]):
        _fail()
    if (release.get("schema_version") != "byq-acp-operator-process-fence-slot-release.v1"
            or release.get("workspace_id") != value["scope"].get("workspace_id")
            or release.get("root_run_id") != runtime_ack.get("root_run_id")
            or release.get("scope_sha256") != runtime_ack.get("scope_sha256")
            or release.get("process_fence_receipt_sha256") != runtime_ack.get("process_fence_receipt_sha256")
            or release.get("tombstone_sha256") != value["runner"].get("tombstone_sha256")
            or release.get("drained_sequence") != drain.get("drained_sequence")
            or release.get("status") != "released"
            or not _hex(release.get("release_receipt_sha256"))
            or digest({key: item for key, item in release.items() if key != "release_receipt_sha256"})
                != release["release_receipt_sha256"]
            or not _utc(release.get("released_at"))):
        _fail()
    value["superseded_terminal"] = superseded
    return value


def validate_superseded_terminal(raw: object, *, root_run_id: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != SUPERSEDED_TERMINAL_FIELDS:
        _fail()
    value = dict(raw)
    if (value.get("schema_version") != "byq-runtime-superseded-terminal.v1"
            or value.get("root_run_id") != root_run_id
            or not _hex(value.get("root_run_id"), 32)
            or type(value.get("sequence")) is not int or value["sequence"] < 1
            or not _hex(value.get("event_sha256"))
            or not _hex(value.get("receipt_sha256"))):
        _fail()
    return value


def validate_ack_receipt(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != ACK_RECEIPT_FIELDS:
        _fail()
    value = dict(raw)
    try:
        scope = validate_product_scope(value.get("scope"))
    except (ProductSlotContractError, TypeError) as exc:
        raise OperatorProcessFenceContractError("operator ACK receipt scope is invalid") from exc
    if (value.get("schema_version") != ACK_SCHEMA
            or not _hex(value.get("operation_id"), 32)
            or not _text(value.get("proof_audit_id"), maximum=256)
            or not _hex(value.get("proof_receipt_sha256"))
            or not _hex(value.get("operator_interruption_receipt_sha256"))
            or not isinstance(value.get("authority"), Mapping)
            or set(value["authority"]) != AUTHORITY_FIELDS
            or not isinstance(value.get("runner"), Mapping)
            or set(value["runner"]) != ACK_RUNNER_FIELDS
            or not all(_hex(value["runner"].get(key)) for key in ACK_RUNNER_FIELDS)
            or not all(_hex(value.get(key)) for key in (
                "runtime_ack_sha256", "root_binding_sha256", "terminal_ack_sha256",
                "drain_receipt_sha256", "slot_release_sha256", "engineering_evidence_sha256"))
            or type(value.get("last_domain_sequence")) is not int
            or type(value.get("drained_sequence")) is not int
            or value["last_domain_sequence"] != value["drained_sequence"]
            or not _utc(value.get("confirmed_at"))
            or not isinstance(value.get("operator"), Mapping)
            or set(value["operator"]) != OPERATOR_FIELDS
            or type(value["operator"].get("uid")) is not int
            or not _text(value["operator"].get("name"), maximum=256)
            or not _hex(value.get("receipt_sha256"))
            or value["authority"].get("previous_boot_id") != scope["runtime_boot_id"]
            or (value["authority"].get("current_boot_id") == value["authority"].get("previous_boot_id")
                and value["authority"].get("current_epoch") != value["authority"].get("previous_epoch"))
            or (value["authority"].get("current_boot_id") != value["authority"].get("previous_boot_id")
                and value["authority"].get("current_epoch") <= value["authority"].get("previous_epoch"))
            or value["runner"].get("tombstone_sha256") is None):
        _fail()
    validate_superseded_terminal(value.get("superseded_terminal"),
                                 root_run_id=value["scope"]["root_run_id"])
    if digest({key: item for key, item in value.items() if key != "receipt_sha256"}) != value["receipt_sha256"]:
        _fail()
    return value


def validate_fence_close_receipt(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != FENCE_CLOSE_RECEIPT_FIELDS:
        _fail()
    value = dict(raw)
    interruption = validate_operator_interruption(value.get("operator_interruption"))
    try:
        scope = validate_product_scope(value.get("scope"))
    except (ProductSlotContractError, TypeError) as exc:
        raise OperatorProcessFenceContractError("close receipt scope is invalid") from exc
    authority = value.get("authority")
    runner = value.get("runner")
    if (value.get("schema_version") != FENCE_CLOSE_RECEIPT_SCHEMA
            or not _hex(value.get("operation_id"), 32)
            or not _text(value.get("workspace_id"), maximum=256)
            or not _hex(value.get("root_run_id"), 32)
            or not _hex(value.get("process_fence_receipt_sha256"))
            or not isinstance(authority, Mapping) or set(authority) != AUTHORITY_FIELDS
            or not _hex(authority.get("previous_boot_id"), 32)
            or not _hex(authority.get("current_boot_id"), 32)
            or type(authority.get("previous_epoch")) is not int or authority["previous_epoch"] < 1
            or type(authority.get("current_epoch")) is not int or authority["current_epoch"] < 1
            or not isinstance(runner, Mapping) or set(runner) != ACK_RUNNER_FIELDS
            or not all(_hex(runner.get(key)) for key in ACK_RUNNER_FIELDS)
            or not _hex(value.get("engineering_evidence_sha256"))
            or not _hex(value.get("runtime_binding_sha256"))
            or interruption.get("operation_id") != value.get("operation_id")
            or interruption.get("root_run_id") != value.get("root_run_id")
            or scope.get("workspace_id") != value.get("workspace_id")
            or scope.get("root_run_id") != value.get("root_run_id")
            or authority.get("previous_boot_id") != scope.get("runtime_boot_id")
            or (authority.get("current_boot_id") == authority.get("previous_boot_id")
                and authority.get("current_epoch") != authority.get("previous_epoch"))
            or (authority.get("current_boot_id") != authority.get("previous_boot_id")
                and authority.get("current_epoch") <= authority.get("previous_epoch"))
            or interruption.get("process_fence_receipt_sha256")
            != value.get("process_fence_receipt_sha256")
            or not _hex(runner.get("tombstone_sha256"))):
        _fail()
    return value


def validate_operator_observation_record(raw: object) -> dict[str, Any]:
    """Validate a persisted Runtime observation without needing its close row.

    V3 stores the exact observation and only the close-receipt digest. Callers
    must separately compare ``close_receipt_sha256`` with the exact protected
    Backend receipt before accepting the observation as an ACK confirmation.
    """
    if not isinstance(raw, Mapping) or set(raw) != OPERATOR_OBSERVATION_FIELDS:
        _fail()
    value = dict(raw)
    try:
        scope = validate_product_scope(value.get("scope"))
    except (ProductSlotContractError, TypeError) as exc:
        raise OperatorProcessFenceContractError("operator observation scope is invalid") from exc
    authority = value.get("authority")
    runner = value.get("runner")
    if (value.get("schema_version") != OPERATOR_OBSERVATION_SCHEMA
            or not _hex(value.get("operation_id"), 32)
            or not _hex(value.get("close_receipt_sha256"))
            or not _hex(value.get("process_fence_receipt_sha256"))
            or not _hex(value.get("operator_interruption_receipt_sha256"))
            or not isinstance(authority, Mapping) or set(authority) != AUTHORITY_FIELDS
            or not _hex(authority.get("previous_boot_id"), 32)
            or not _hex(authority.get("current_boot_id"), 32)
            or type(authority.get("previous_epoch")) is not int or authority["previous_epoch"] < 1
            or type(authority.get("current_epoch")) is not int or authority["current_epoch"] < 1
            or authority.get("previous_boot_id") != scope.get("runtime_boot_id")
            or not isinstance(runner, Mapping) or set(runner) != ACK_RUNNER_FIELDS
            or not all(_hex(runner.get(key)) for key in ACK_RUNNER_FIELDS)
            or not _hex(value.get("engineering_evidence_sha256"))
            or not _hex(value.get("runtime_binding_sha256"))
            or not _utc(value.get("observed_at"))):
        _fail()
    request = {
        "schema_version": ACK_REQUEST_SCHEMA,
        "operation_id": value["operation_id"],
        "proof_receipt_sha256": value["close_receipt_sha256"],
        "runtime_ack": value.get("runtime_ack"),
        "domain_call_drain": value.get("domain_call_drain"),
        "slot_release": value.get("slot_release"),
        "engineering_evidence_sha256": value["engineering_evidence_sha256"],
        "confirmed_at": value["observed_at"],
        "scope": value["scope"],
        "authority": value["authority"],
        "runner": value["runner"],
        "superseded_terminal": value["superseded_terminal"],
    }
    validated = validate_ack_request(request)
    ack = validated["runtime_ack"]
    if (ack.get("terminal_ack_sha256") != value["close_receipt_sha256"]
            or ack.get("process_fence_receipt_sha256") != value["process_fence_receipt_sha256"]
            or ack.get("operator_interruption_receipt_sha256")
                != value["operator_interruption_receipt_sha256"]
            or ack.get("root_binding_sha256") != value["runtime_binding_sha256"]):
        _fail()
    if ((authority.get("current_boot_id") == authority.get("previous_boot_id")
         and authority.get("current_epoch") != authority.get("previous_epoch"))
            or (authority.get("current_boot_id") != authority.get("previous_boot_id")
                and authority.get("current_epoch") <= authority.get("previous_epoch"))):
        _fail()
    return value


def validate_operator_observation(raw: object, *, close_receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = validate_operator_observation_record(raw)
    close = validate_fence_close_receipt(close_receipt)
    if (value.get("operation_id") != close["operation_id"]
            or value.get("close_receipt_sha256") != digest(close)
            or value.get("process_fence_receipt_sha256") != close["process_fence_receipt_sha256"]
            or value.get("operator_interruption_receipt_sha256")
                != close["operator_interruption"]["receipt_sha256"]
            or value.get("scope") != close["scope"]
            or value.get("authority") != close["authority"]
            or value.get("runner") != close["runner"]
            or value.get("engineering_evidence_sha256") != close["engineering_evidence_sha256"]
            or value.get("runtime_binding_sha256") != close["runtime_binding_sha256"]):
        _fail()
    return value
