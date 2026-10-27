"""Closed Backend/Runtime contract for an ADR-0104 operator fence.

The contract records an Engineering process-fence claim separately from an
Adapter lifecycle event. It never manufactures an Adapter sequence, EXIT, or
cleanup receipt.
"""

from __future__ import annotations

import hashlib
import base64
import binascii
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .acp_product_slot import (PRODUCT_SCOPE_KEYS, ProductSlotContractError,
                               product_scope_digest, validate_product_scope)
from .acp_product_prebind import DEPLOYMENT_FIELDS, START_BINDING_FIELDS, START_BINDING_SCHEMA, VOLUME_FIELDS


PROCESS_FENCE_REQUEST_SCHEMA = "byq-acp-operator-process-fence-request.v1"
PROCESS_FENCE_SCHEMA = "byq-acp-operator-process-fence.v1"
INTERRUPTION_SCHEMA = "byq-agent-root-operator-interruption.v1"
FAILED_TERMINAL_SCHEMA = "byq-agent-root-operator-failed-terminal-fence.v1"
COMPLETED_CLEANUP_REQUEST_SCHEMA = "byq-acp-completed-cleanup-request.v1"
COMPLETED_CLEANUP_PROOF_SCHEMA = "byq-agent-root-operator-completed-cleanup-proof.v1"
COMPLETED_CLEANUP_ACK_SCHEMA = "byq-runtime-operator-completed-cleanup-ack.v1"
COMPLETED_CLEANUP_OBSERVATION_SCHEMA = "byq-runtime-operator-completed-cleanup-observation.v1"
ACK_REQUEST_SCHEMA = "byq-acp-operator-process-fence-ack-request.v1"
ACK_SCHEMA = "byq-acp-operator-process-fence-ack-confirm.v1"
FENCE_CLOSE_RECEIPT_SCHEMA = "byq-acp-operator-process-fence-close-receipt.v1"
PREIMAGE_SCHEMA = "byq-acp-r2-preimage.v1"
LOCAL_VALIDATION_CLOSE_SCHEMA = "byq-local-validation-close-request.v1"
LOCAL_VALIDATION_CLOSE_FIELDS = frozenset({"schema_version", "root_run_id", "session_id", "boot_id",
                                           "cleanup_receipt_raw_b64"})
LOCAL_VALIDATION_PRE_ACK_SCHEMA = "byq-local-validation-pre-ack-stop-request.v1"
LOCAL_VALIDATION_PRE_ACK_FIELDS = frozenset({"schema_version", "root_run_id", "session_id", "boot_id"})
LOCAL_VALIDATION_PRE_ACK_STOP_SCHEMA = "byq-local-validation-pre-ack-stop.v1"
LOCAL_VALIDATION_RESERVATION_SCHEMA = "byq-local-validation-reconciliation-reservation.v1"
LOCAL_VALIDATION_CALLBACK_EXIT_SCHEMA = "byq-local-strategy-validation-callback-exit.v1"
LOCAL_VALIDATION_PROJECTION_SCHEMA = "byq-runtime-local-validation-terminal-evidence.v1"
LOCAL_VALIDATION_FINAL_SCHEMA = "byq-local-validation-final-terminal.v1"
LOCAL_VALIDATION_ACK_REQUEST_SCHEMA = "byq-local-validation-ack-request.v1"
LOCAL_VALIDATION_ACK_INTENT_SCHEMA = "byq-local-validation-ack-intent.v1"
LOCAL_VALIDATION_RELEASE_OBSERVATION_SCHEMA = "byq-local-validation-release-observation.v1"
LOCAL_VALIDATION_BACKEND_CONFIRMATION_SCHEMA = "byq-local-validation-backend-confirmation.v1"
LOCAL_VALIDATION_HANDOFF_SCHEMA = "byq-local-validation-confirmation-handoff.v1"
LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA = "byq-local-validation-confirmation-handoff-request.v1"
LOCAL_VALIDATION_HANDOFF_INPUT_SCHEMA = "byq-local-validation-confirmation-handoff-input.v1"
LOCAL_VALIDATION_HANDOFF_INTENT_SCHEMA = "byq-local-validation-confirmation-handoff-intent.v1"
LOCAL_VALIDATION_HANDOFF_OBSERVATION_SCHEMA = "byq-local-validation-confirmation-handoff-observation.v1"
LOCAL_VALIDATION_HANDOFF_CONFIRMATION_SCHEMA = "byq-local-validation-handoff-backend-confirmation.v1"
PROCESS_FENCE_HANDOFF_SCHEMA = "byq-acp-operator-process-fence-handoff.v1"
PROCESS_FENCE_HANDOFF_REQUEST_SCHEMA = "byq-acp-operator-process-fence-handoff-request.v1"
PROCESS_FENCE_HANDOFF_OBSERVATION_SCHEMA = "byq-runtime-operator-process-fence-handoff-observation.v1"
PROCESS_FENCE_HANDOFF_CONFIRMATION_SCHEMA = "byq-acp-operator-process-fence-handoff-confirmation.v1"

LOCAL_VALIDATION_FINAL_FIELDS = frozenset({
    "schema_version", "root_run_id", "scope", "claim_id", "task_id", "claim_status",
    "idempotency_key_sha256", "reservation_sha256", "disposition", "disposition_sha256",
    "source_rows_sha256", "terminal_event_receipt", "runtime_binding_sha256",
    "runtime_projection_sha256", "cleanup_receipt_sha256", "unknown_ingress_count",
    "unknown_ingress_sha256", "terminal_acp_ingress_sequence",
    "terminal_acp_ingress_sha256", "terminal_unknown_claim_count",
    "terminal_unknown_claims_sha256", "operator_uid", "operator_name", "receipt_sha256",
})
LOCAL_VALIDATION_ACK_REQUEST_FIELDS = frozenset({"schema_version", "final_receipt"})
LOCAL_VALIDATION_ACK_INTENT_FIELDS = frozenset({
    "schema_version", "final_receipt", "runtime_boot_id", "runtime_authority_epoch",
    "final_live_sequence", "domain_call_sequence", "domain_call_drained_sequence", "intent_sha256",
})
LOCAL_VALIDATION_RELEASE_OBSERVATION_FIELDS = frozenset({
    "schema_version", "ack_intent", "slot_scope_sha256", "cleanup_receipt_sha256",
    "state", "observation_sha256",
})
LOCAL_VALIDATION_BACKEND_CONFIRMATION_FIELDS = frozenset({
    "schema_version", "root_run_id", "final_receipt_sha256", "runtime_observation",
    "operator_uid", "operator_name", "receipt_sha256",
})
LOCAL_VALIDATION_HANDOFF_STOP_FIELDS = frozenset({
    "daemon_id", "container_id", "image_id", "started_at", "stopped_at",
    "before_pid", "after_pid", "running", "paused", "restarting",
    "restart_policy", "pid_mode", "mounts_before_sha256", "mounts_after_sha256",
})
LOCAL_VALIDATION_HANDOFF_AUTHORITY_FIELDS = frozenset({"boot_id", "epoch", "boot_receipt_sha256"})
LOCAL_VALIDATION_HANDOFF_FIELDS = frozenset({
    "schema_version", "operation_id", "root_run_id", "final_receipt_sha256",
    "reservation_sha256", "scope", "original_binding_sha256", "cleanup_receipt_sha256",
    "old_authority", "new_authority", "stopped_runtime_evidence", "operator_uid",
    "operator_name", "confirmation_baseline_basis", "confirmation_baseline_sha256", "handoff_sha256",
})
LOCAL_VALIDATION_HANDOFF_SUCCESSOR_FIELDS = LOCAL_VALIDATION_HANDOFF_FIELDS | frozenset({
    "predecessor_handoff_sha256", "predecessor_runtime_stopped_evidence",
})
LOCAL_VALIDATION_HANDOFF_REQUEST_FIELDS = frozenset({"schema_version", "handoff", "final_receipt"})
LOCAL_VALIDATION_HANDOFF_INPUT_FIELDS = frozenset({
    "schema_version", "final_receipt", "stopped_runtime_evidence", "confirmation_baseline",
})
LOCAL_VALIDATION_HANDOFF_SUCCESSOR_INPUT_FIELDS = LOCAL_VALIDATION_HANDOFF_INPUT_FIELDS | frozenset({
    "predecessor_runtime_stopped_evidence",
})
LOCAL_VALIDATION_HANDOFF_INTENT_FIELDS = frozenset({
    "schema_version", "handoff", "final_receipt", "runtime_boot_id",
    "runtime_authority_epoch", "domain_call_sequence", "domain_call_drained_sequence",
    "intent_sha256",
})
LOCAL_VALIDATION_HANDOFF_OBSERVATION_FIELDS = frozenset({
    "schema_version", "ack_intent", "slot_scope_sha256", "cleanup_receipt_sha256",
    "state", "observation_sha256",
})
LOCAL_VALIDATION_HANDOFF_CONFIRMATION_FIELDS = frozenset({
    "schema_version", "root_run_id", "final_receipt_sha256", "handoff",
    "runtime_observation", "operator_uid", "operator_name", "receipt_sha256",
})

PROCESS_FENCE_ACTION = "acp_operator_process_fence_proof"
PROCESS_FENCE_IDEMPOTENCY_PREFIX = "acp-operator-process-fence:"
ACK_ACTION = "acp_operator_process_fence_ack_confirm"
ACK_IDEMPOTENCY_PREFIX = "acp-operator-process-fence-ack:"
HANDOFF_ACTION = "acp_operator_process_fence_handoff"
HANDOFF_IDEMPOTENCY_PREFIX = PROCESS_FENCE_IDEMPOTENCY_PREFIX + "handoff:"
HANDOFF_ACK_ACTION = "acp_operator_process_fence_handoff_ack"
HANDOFF_ACK_IDEMPOTENCY_PREFIX = ACK_IDEMPOTENCY_PREFIX + "handoff:"
PROCESS_FENCE_RESERVED_PREFIXES = (
    PROCESS_FENCE_IDEMPOTENCY_PREFIX,
    ACK_IDEMPOTENCY_PREFIX,
    HANDOFF_IDEMPOTENCY_PREFIX,
    HANDOFF_ACK_IDEMPOTENCY_PREFIX,
)

HANDOFF_FIELDS = frozenset({"schema_version", "operation_id", "root_run_id", "scope",
    "proof_receipt_sha256", "process_fence_receipt_sha256", "tombstone_sha256",
    "original_request_sha256", "close_receipt_sha256",
    "runtime_binding_sha256", "terminal_receipt_sha256", "old_authority", "new_authority",
    "preflight", "runtime_stop_proof", "operator", "created_at", "handoff_sha256"})
HANDOFF_PREFLIGHT_FIELDS = frozenset({"binding_sha256", "reservation_request_sha256",
    "new_authority_receipt_sha256",
    "runtime_observation_absent", "slot_release_absent", "backend_ack_count"})
HANDOFF_REQUEST_FIELDS = frozenset({"schema_version", "handoff", "close_receipt"})
HANDOFF_AUTHORITY_FIELDS = frozenset({"boot_id", "epoch"})
HANDOFF_STOP_PROOF_FIELDS = frozenset({"daemon_id", "container_id", "started_at",
    "image_id", "stopped_at", "before_pid", "after_pid", "running", "paused", "restarting",
    "restart_policy", "pid_mode", "mounts_before_sha256", "mounts_after_sha256"})
HANDOFF_OBSERVATION_FIELDS = frozenset({"schema_version", "operation_id", "handoff_sha256",
    "root_run_id", "scope", "runtime_boot_id", "runtime_authority_epoch",
    "original_binding_sha256", "domain_call_drain", "slot_release", "observed_at", "receipt_sha256"})
HANDOFF_CONFIRMATION_FIELDS = frozenset({"schema_version", "operation_id", "handoff_sha256",
    "proof_receipt_sha256", "close_receipt_sha256", "runtime_observation",
    "operator", "confirmed_at", "receipt_sha256"})

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
FAILED_TERMINAL_FIELDS = INTERRUPTION_FIELDS | {"sequence", "event_sha256"}
COMPLETED_CLEANUP_REQUEST_FIELDS = frozenset({
    "schema_version", "process_fence_request", "original_terminal_receipt",
})
COMPLETED_CLEANUP_FACT_FIELDS = frozenset({
    "schema_version", "operation_id", "root_run_id", "outcome",
    "original_terminal_receipt_sha256", "process_fence_receipt_sha256",
    "terminal_acp_ingress_sequence", "terminal_acp_ingress_sha256",
    "terminal_unknown_claim_count", "terminal_unknown_claims_sha256", "receipt_sha256",
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
FAILED_FACT_DIGEST_FIELD = "operator_failed_terminal_receipt_sha256"
COMPLETED_CLEANUP_DIGEST_FIELD = "operator_completed_cleanup_receipt_sha256"
INTERRUPTION_DIGEST_FIELD = "operator_interruption_receipt_sha256"
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


def validate_local_validation_close_request(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, dict) or set(raw) != LOCAL_VALIDATION_CLOSE_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_CLOSE_SCHEMA
            or not isinstance(raw.get("root_run_id"), str) or _HEX32.fullmatch(raw["root_run_id"]) is None
            or not _text(raw.get("session_id"))
            or not isinstance(raw.get("boot_id"), str) or _HEX32.fullmatch(raw["boot_id"]) is None
            or not isinstance(raw.get("cleanup_receipt_raw_b64"), str)
            or len(raw["cleanup_receipt_raw_b64"]) > 16384):
        _fail()
    try:
        raw_bytes = raw["cleanup_receipt_raw_b64"].encode("ascii")
        cleanup = base64.b64decode(raw_bytes, validate=True)
    except (UnicodeError, ValueError, binascii.Error):
        _fail()
    if not cleanup or base64.b64encode(cleanup).decode("ascii") != raw["cleanup_receipt_raw_b64"]:
        _fail()
    return dict(raw)


def validate_local_validation_pre_ack_request(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_PRE_ACK_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_PRE_ACK_SCHEMA
            or not isinstance(raw.get("root_run_id"), str) or _HEX32.fullmatch(raw["root_run_id"]) is None
            or not _text(raw.get("session_id"))
            or not isinstance(raw.get("boot_id"), str) or _HEX32.fullmatch(raw["boot_id"]) is None):
        _fail()
    return dict(raw)


def validate_local_validation_pre_ack_evidence(raw: object, *, request: Mapping[str, Any]) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != {"schema_version", "reservation", "callback_exit"}
            or raw.get("schema_version") != "byq-local-validation-pre-ack-evidence.v1"):
        _fail()
    reservation, callback = raw.get("reservation"), raw.get("callback_exit")
    reservation_fields = {"schema_version", "root_run_id", "scope", "authority_boot_id", "claim_id",
        "task_id", "idempotency_key", "original_key_submission_sha256", "mcp_request_id", "request_sha256",
        "input_sha256", "event_sha256", "settlement_sha256", "claim_sha256", "registration_sha256",
        "evidence_sha256", "observation_sha256", "callback_exit_sha256", "snapshot_sha256", "reservation_sha256"}
    if (not isinstance(reservation, Mapping) or set(reservation) != reservation_fields
            or reservation.get("schema_version") != LOCAL_VALIDATION_RESERVATION_SCHEMA
            or reservation.get("root_run_id") != request.get("root_run_id")
            or reservation.get("authority_boot_id") != request.get("boot_id")
            or not isinstance(reservation.get("scope"), Mapping)
            or reservation["scope"].get("session_id") != request.get("session_id")
            or not isinstance(reservation.get("authority_boot_id"), str)
            or _HEX32.fullmatch(reservation["authority_boot_id"]) is None):
        _fail()
    if (set(reservation["scope"]) != {"owner_principal", "workspace_id", "actor_principal",
                                       "session_id", "trace_id", "generation"}
            or any(not isinstance(reservation["scope"].get(k), str) or not reservation["scope"][k]
                   for k in reservation["scope"])
            or reservation["scope"]["actor_principal"] !=
               "byq-product-agent-" + reservation["scope"]["session_id"]
            or not isinstance(reservation.get("claim_id"), str)
            or _HEX32.fullmatch(reservation["claim_id"]) is None
            or not isinstance(reservation.get("mcp_request_id"), str)
            or _HEX32.fullmatch(reservation["mcp_request_id"]) is None
            or not isinstance(reservation.get("task_id"), str) or not reservation["task_id"]
            or not isinstance(reservation.get("idempotency_key"), str) or not reservation["idempotency_key"]
            or any(not _hex(reservation.get(k)) for k in (
                "original_key_submission_sha256", "request_sha256", "input_sha256", "event_sha256",
                "settlement_sha256", "claim_sha256", "registration_sha256", "evidence_sha256",
                "observation_sha256", "callback_exit_sha256", "snapshot_sha256"))):
        _fail()
    if not _local_digest_matches(reservation, "reservation_sha256"):
        _fail()
    cb_fields = {"schema_version", "claim_id", "root_run_id", "mcp_request_id", "scope", "authority_boot_id",
        "evidence_sequence", "agent_run_id", "task_id", "action", "idempotency_key", "request_sha256",
        "input_sha256", "evidence_sha256", "observation_sha256", "callback_disposition", "receipt_sha256"}
    if (not isinstance(callback, Mapping) or set(callback) != cb_fields
            or callback.get("schema_version") != LOCAL_VALIDATION_CALLBACK_EXIT_SCHEMA
            or callback.get("callback_disposition") != "callback_exited"
            or callback.get("root_run_id") != request.get("root_run_id")
            or callback.get("claim_id") != reservation.get("claim_id")
            or callback.get("mcp_request_id") != reservation.get("mcp_request_id")
            or callback.get("scope") != reservation.get("scope")
            or callback.get("authority_boot_id") != request.get("boot_id")
            or callback.get("task_id") != reservation.get("task_id")
            or callback.get("idempotency_key") != reservation.get("idempotency_key")
            or callback.get("request_sha256") != reservation.get("request_sha256")
            or callback.get("input_sha256") != reservation.get("input_sha256")
            or callback.get("evidence_sha256") != reservation.get("evidence_sha256")
            or callback.get("observation_sha256") != reservation.get("observation_sha256")
            or callback.get("action") != "byq_strategy_validate"
            or type(callback.get("evidence_sequence")) is not int or callback["evidence_sequence"] < 1
            or callback.get("receipt_sha256") != reservation.get("callback_exit_sha256")
            or not _local_digest_matches(callback, "receipt_sha256")):
        _fail()
    if (reservation["scope"].get("actor_principal") !=
            "byq-product-agent-" + str(reservation["scope"].get("session_id"))
            or any(not isinstance(reservation["scope"].get(k), str) or not reservation["scope"][k]
                   for k in ("owner_principal", "workspace_id", "actor_principal", "session_id",
                             "trace_id", "generation"))):
        _fail()
    return {"schema_version": raw["schema_version"], "reservation": dict(reservation),
            "callback_exit": dict(callback)}


def validate_local_validation_pre_ack_stop(raw: object, *, allow_stopping: bool = False) -> dict[str, Any]:
    fields = {"schema_version", "root_run_id", "reservation_sha256", "callback_exit_sha256",
              "terminal_event_receipt", "state", "cleanup_receipt_sha256", "stop_sha256"}
    if (not isinstance(raw, Mapping) or set(raw) != fields
            or raw.get("schema_version") != LOCAL_VALIDATION_PRE_ACK_STOP_SCHEMA
            or not isinstance(raw.get("root_run_id"), str) or _HEX32.fullmatch(raw["root_run_id"]) is None
            or raw.get("state") not in ({"stopping", "stopped"} if allow_stopping else {"stopped"})
            or not _hex(raw.get("reservation_sha256")) or not _hex(raw.get("callback_exit_sha256"))):
        _fail()
    terminal = raw.get("terminal_event_receipt")
    if (not isinstance(terminal, Mapping)
            or set(terminal) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
            or terminal.get("schema_version") != "agent-run-lifecycle-receipt.v1"
            or terminal.get("root_run_id") != raw.get("root_run_id")
            or type(terminal.get("sequence")) is not int or terminal["sequence"] < 1
            or not _hex(terminal.get("event_sha256"))):
        _fail()
    cleanup = raw.get("cleanup_receipt_sha256")
    if ((raw["state"] == "stopping" and cleanup is not None)
            or (raw["state"] == "stopped" and not _hex(cleanup))
            or not _local_digest_matches(raw, "stop_sha256")):
        _fail()
    return dict(raw)


def validate_local_validation_projection(raw: object, *, request: Mapping[str, Any]) -> dict[str, Any]:
    from .agent_run_lifecycle import lifecycle_receipt

    if (not isinstance(raw, dict) or set(raw) != {"schema_version", "terminal", "scope", "binding_sha256"}
            or raw.get("schema_version") != LOCAL_VALIDATION_PROJECTION_SCHEMA
            or not isinstance(raw.get("binding_sha256"), str) or not _hex(raw["binding_sha256"])):
        _fail()
    terminal = raw.get("terminal")
    terminal_fields = {"schema_version", "session_id", "boot_id", "root_run_id", "sequence", "outcome", "receipt"}
    if (not isinstance(terminal, dict) or set(terminal) != terminal_fields
            or terminal.get("schema_version") != "byq-runtime-terminal-evidence.v1"
            or terminal.get("session_id") != request["session_id"]
            or terminal.get("boot_id") != request["boot_id"]
            or terminal.get("root_run_id") != request["root_run_id"]
            or type(terminal.get("sequence")) is not int or terminal["sequence"] < 1
            or terminal.get("outcome") not in {"completed", "failed", "cancelled", "interrupted"}):
        _fail()
    expected_receipt = lifecycle_receipt({"schema_version": "agent-run-lifecycle.v1",
        "root_run_id": terminal["root_run_id"], "sequence": terminal["sequence"],
        "outcome": terminal["outcome"]})
    if terminal.get("receipt") != expected_receipt:
        _fail()
    scope = raw.get("scope")
    try:
        scope = validate_product_scope(scope)
    except (TypeError, ValueError):
        _fail()
    if (scope["session_id"] != request["session_id"] or scope["root_run_id"] != request["root_run_id"]
            or scope["runtime_boot_id"] != request["boot_id"]):
        _fail()
    return dict(raw) | {"scope": dict(scope)}


def _local_digest_matches(value: Mapping[str, Any], field: str) -> bool:
    claimed = value.get(field)
    base = {key: item for key, item in value.items() if key != field}
    return isinstance(claimed, str) and _hex(claimed) and hmac_compare(digest(base), claimed)


def hmac_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left, right)


def validate_local_validation_final_receipt(raw: object) -> dict[str, Any]:
    """Validate the shared, closed Backend final receipt shape and all bindings."""
    from .agent_run_lifecycle import lifecycle_receipt

    if not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_FINAL_FIELDS:
        _fail()
    value = dict(raw)
    claim_facts = (value.get("disposition"), value.get("claim_status"),
                   value.get("terminal_unknown_claim_count"))
    if (value.get("schema_version") != LOCAL_VALIDATION_FINAL_SCHEMA
            or not _hex(value.get("root_run_id"), 32)
            or value.get("disposition") not in {"committed", "uncommitted"}
            or not isinstance(value.get("claim_status"), str) or not value["claim_status"]
            or not isinstance(value.get("task_id"), str) or not value["task_id"]
            or not _hex(value.get("claim_id"), 32)
            or type(value.get("operator_uid")) is not int
            or not 0 <= value["operator_uid"] <= 2**31 - 1
            or not _text(value.get("operator_name"))
            or type(value.get("unknown_ingress_count")) is not int
            or value["unknown_ingress_count"] != 1
            or type(value.get("terminal_acp_ingress_sequence")) is not int
            or not 0 <= value["terminal_acp_ingress_sequence"] < 2**63
            or type(value.get("terminal_unknown_claim_count")) is not int
            or value["terminal_unknown_claim_count"] not in {0, 1}
            or any(not _hex(value.get(field)) for field in (
                "idempotency_key_sha256", "reservation_sha256", "disposition_sha256",
                "source_rows_sha256", "runtime_binding_sha256", "runtime_projection_sha256",
                "cleanup_receipt_sha256", "unknown_ingress_sha256",
                "terminal_acp_ingress_sha256", "terminal_unknown_claims_sha256"))):
        _fail()
    if claim_facts not in {
            ("committed", "succeeded", 0),
            ("uncommitted", "executing", 1),
            ("uncommitted", "correctable_failure", 0),
    }:
        _fail()
    try:
        scope = validate_product_scope(value.get("scope"))
    except (TypeError, ValueError):
        _fail()
    if set(value["scope"]) != PRODUCT_SCOPE_KEYS or scope["root_run_id"] != value["root_run_id"]:
        _fail()
    terminal = value.get("terminal_event_receipt")
    if (not isinstance(terminal, Mapping)
            or set(terminal) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
            or terminal.get("schema_version") != "agent-run-lifecycle-receipt.v1"
            or terminal.get("root_run_id") != value["root_run_id"]
            or type(terminal.get("sequence")) is not int
            or not 1 <= terminal["sequence"] <= 2**63 - 1
            or not _hex(terminal.get("event_sha256"))):
        _fail()
    if not any(lifecycle_receipt({"schema_version": "agent-run-lifecycle.v1",
            "root_run_id": value["root_run_id"], "sequence": terminal["sequence"],
            "outcome": outcome}) == dict(terminal)
            for outcome in ("completed", "failed", "cancelled", "interrupted")):
        _fail()
    if not _local_digest_matches(value, "receipt_sha256"):
        _fail()
    return value | {"scope": dict(scope), "terminal_event_receipt": dict(terminal)}


def validate_local_validation_ack_request(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_ACK_REQUEST_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_ACK_REQUEST_SCHEMA):
        _fail()
    return {"schema_version": LOCAL_VALIDATION_ACK_REQUEST_SCHEMA,
            "final_receipt": validate_local_validation_final_receipt(raw.get("final_receipt"))}


def validate_local_validation_ack_intent(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_ACK_INTENT_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_ACK_INTENT_SCHEMA):
        _fail()
    value = dict(raw)
    final = validate_local_validation_final_receipt(value.get("final_receipt"))
    sequence_fields = ("final_live_sequence", "domain_call_sequence", "domain_call_drained_sequence")
    if (value.get("runtime_boot_id") != final["scope"]["runtime_boot_id"]
            or type(value.get("runtime_authority_epoch")) is not int
            or not 1 <= value["runtime_authority_epoch"] < 2**63
            or any(type(value.get(field)) is not int or not 0 <= value[field] < 2**63
                   for field in sequence_fields)
            or value["domain_call_drained_sequence"] != value["domain_call_sequence"]
            or value["final_live_sequence"] < final["terminal_event_receipt"]["sequence"]
            or not _local_digest_matches(value, "intent_sha256")):
        _fail()
    return value | {"final_receipt": final}


def validate_local_validation_release_observation(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_RELEASE_OBSERVATION_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_RELEASE_OBSERVATION_SCHEMA):
        _fail()
    value = dict(raw)
    intent = validate_local_validation_ack_intent(value.get("ack_intent"))
    final = intent["final_receipt"]
    scope_sha = product_scope_digest(final["scope"])
    if (value.get("state") != "released"
            or value.get("slot_scope_sha256") != scope_sha
            or value.get("cleanup_receipt_sha256") != final["cleanup_receipt_sha256"]
            or not _local_digest_matches(value, "observation_sha256")):
        _fail()
    return value | {"ack_intent": intent}


def validate_local_validation_stop_evidence(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_HANDOFF_STOP_FIELDS:
        _fail()
    value = dict(raw)
    try:
        started = datetime.fromisoformat(value["started_at"].replace("Z", "+00:00"))
        stopped = datetime.fromisoformat(value["stopped_at"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        _fail()
    if (value.get("daemon_id") != "ab9a85ff-1f4a-47a8-a57f-c99b0d7abff7"
            or value.get("container_id") != "0ecd41e55fc3846f3c5845d1c4635c0568acdc0ef3dc244f1bd185a6d6645bf4"
            or value.get("image_id") != "8db07938a7f5fa63ed059fd0ca896a0a35c24017b973787a6b05d41144ad78f2"
            or value.get("started_at") != "2026-10-26T15:02:29.398117328Z"
            or not _utc(value.get("started_at")) or not _utc(value.get("stopped_at"))
            or type(value.get("before_pid")) is not int or value["before_pid"] <= 0
            or value.get("after_pid") != 0 or value.get("running") is not False
            or value.get("paused") is not False or value.get("restarting") is not False
            or value.get("restart_policy") != "no" or value.get("pid_mode") not in {"private", ""}
            or not _hex(value.get("mounts_before_sha256"))
            or value.get("mounts_after_sha256") != value.get("mounts_before_sha256")
            or stopped <= started):
        _fail()
    return value


def validate_local_validation_handoff(raw: object, *, final_receipt: object | None = None) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or frozenset(raw) not in {
            LOCAL_VALIDATION_HANDOFF_FIELDS, LOCAL_VALIDATION_HANDOFF_SUCCESSOR_FIELDS}:
        _fail()
    value = dict(raw)
    successor = set(value) == LOCAL_VALIDATION_HANDOFF_SUCCESSOR_FIELDS
    try:
        scope = validate_product_scope(value.get("scope"))
    except (ProductSlotContractError, TypeError):
        _fail()
    old, new = value.get("old_authority"), value.get("new_authority")
    stop_raw = value.get("stopped_runtime_evidence")
    try:
        stop = validate_local_validation_stop_evidence(stop_raw)
    except (TypeError, ValueError):
        _fail()
    if successor:
        proof = value["predecessor_runtime_stopped_evidence"]
        if not isinstance(proof, Mapping) or set(proof) != LOCAL_VALIDATION_HANDOFF_STOP_FIELDS:
            _fail()
        try:
            started = datetime.fromisoformat(proof["started_at"].replace("Z", "+00:00"))
            stopped = datetime.fromisoformat(proof["stopped_at"].replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            _fail()
        if (value["predecessor_handoff_sha256"] != "ff4b4c2b703fc96ea1aa0b07b1f9e7dfb2c3a815eb7b96688e08f0ff406f788a"
                or proof.get("daemon_id") != "ab9a85ff-1f4a-47a8-a57f-c99b0d7abff7"
                or proof.get("container_id") != "942683136ec38f06e1ad1006a3bf7bec96e2174029a05d4524969a50b2468d5d"
                or proof.get("image_id") != "1e1dd23a9b5920b507b7daa12c68a0aae0561cb151c35b090e2ce252bc86d934"
                or proof.get("started_at") != "2026-10-27T10:06:15.706203884Z"
                or not _utc(proof.get("started_at")) or not _utc(proof.get("stopped_at"))
                or type(proof.get("before_pid")) is not int or proof["before_pid"] <= 0
                or proof.get("after_pid") != 0 or proof.get("running") is not False
                or proof.get("paused") is not False or proof.get("restarting") is not False
                or proof.get("restart_policy") != "no" or proof.get("pid_mode") not in {"private", ""}
                or not _hex(proof.get("mounts_before_sha256"))
                or proof.get("mounts_after_sha256") != proof.get("mounts_before_sha256")
                or stopped <= started or not isinstance(new, Mapping)
                or new.get("boot_id") == "a06bfa20edec5f49110a39705bd629b7"
                or type(new.get("epoch")) is not int or new["epoch"] <= 33):
            _fail()
    elif value.get("handoff_sha256") != "ff4b4c2b703fc96ea1aa0b07b1f9e7dfb2c3a815eb7b96688e08f0ff406f788a":
        _fail()
    if (value.get("schema_version") != LOCAL_VALIDATION_HANDOFF_SCHEMA
            or not _hex(value.get("operation_id"), 32)
            or not _hex(value.get("root_run_id"), 32)
            or scope["root_run_id"] != value.get("root_run_id")
            or not all(_hex(value.get(k)) for k in ("final_receipt_sha256", "reservation_sha256",
                "original_binding_sha256", "cleanup_receipt_sha256"))
            or not isinstance(old, Mapping) or set(old) != {"boot_id", "epoch"}
            or not _hex(old.get("boot_id"), 32) or type(old.get("epoch")) is not int or old["epoch"] < 1
            or old != {"boot_id": "a0942b63e3a4c3f7fa260ce58a1d93b1", "epoch": 32}
            or old.get("boot_id") != scope["runtime_boot_id"]
            or not isinstance(new, Mapping) or set(new) != LOCAL_VALIDATION_HANDOFF_AUTHORITY_FIELDS
            or not _hex(new.get("boot_id"), 32) or type(new.get("epoch")) is not int
            or new["epoch"] < 1 or new["boot_id"] == old["boot_id"] or new["epoch"] <= old["epoch"]
            or not _hex(new.get("boot_receipt_sha256"))
            or value.get("confirmation_baseline_basis") != "accepted-independent-postfinal-2026-10-27"
            or value.get("confirmation_baseline_sha256") != "923e0702c1495e0c8ddeab6ff4fcb4367492ad0241a716b5fa1c9d4579f86e6a"
            or type(value.get("operator_uid")) is not int or not 0 <= value["operator_uid"] <= 2**31 - 1
            or not _text(value.get("operator_name"))
            or not _local_digest_matches(value, "handoff_sha256")):
        _fail()
    if (value["root_run_id"] != "c530d89d59d84c91906954dfe994b540"
            or value["final_receipt_sha256"] != "19baa898f90ffdb187cebcc3d380132be617f1adcf733eb5423810abf19354e0"
            or value["reservation_sha256"] != "3aef6f36ffd632d5b1e3c8efa7b52d17dce4d7c0e28a3a7950999992b4dc97b5"
            or value["original_binding_sha256"] != "6d9c7e5672fa86b644e262b7916968d73172d92343352afa514ad80a875c30cb"
            or value["cleanup_receipt_sha256"] != "062ece3143a3e1b4c6baba75e0e71ca53cf558b5d2890d0afe96443dbb085547"):
        _fail()
    if final_receipt is not None:
        final = validate_local_validation_final_receipt(final_receipt)
        if (final["root_run_id"] != value["root_run_id"]
                or final["root_run_id"] != "c530d89d59d84c91906954dfe994b540"
                or final["receipt_sha256"] != value["final_receipt_sha256"]
                or final["receipt_sha256"] != "19baa898f90ffdb187cebcc3d380132be617f1adcf733eb5423810abf19354e0"
                or final["reservation_sha256"] != value["reservation_sha256"]
                or final["reservation_sha256"] != "3aef6f36ffd632d5b1e3c8efa7b52d17dce4d7c0e28a3a7950999992b4dc97b5"
                or final["runtime_binding_sha256"] != value["original_binding_sha256"]
                or final["runtime_binding_sha256"] != "6d9c7e5672fa86b644e262b7916968d73172d92343352afa514ad80a875c30cb"
                or final["cleanup_receipt_sha256"] != value["cleanup_receipt_sha256"]
                or final["cleanup_receipt_sha256"] != "062ece3143a3e1b4c6baba75e0e71ca53cf558b5d2890d0afe96443dbb085547"
                or final["scope"] != scope):
            _fail()
    value["scope"] = dict(scope)
    return value


def validate_local_validation_handoff_request(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_HANDOFF_REQUEST_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA):
        _fail()
    final = validate_local_validation_final_receipt(raw.get("final_receipt"))
    handoff = validate_local_validation_handoff(raw.get("handoff"), final_receipt=final)
    return {"schema_version": LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA,
            "handoff": handoff, "final_receipt": final}


def validate_local_validation_handoff_input(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or frozenset(raw) not in {
            LOCAL_VALIDATION_HANDOFF_INPUT_FIELDS, LOCAL_VALIDATION_HANDOFF_SUCCESSOR_INPUT_FIELDS}
            or raw.get("schema_version") != LOCAL_VALIDATION_HANDOFF_INPUT_SCHEMA):
        _fail()
    successor = set(raw) == LOCAL_VALIDATION_HANDOFF_SUCCESSOR_INPUT_FIELDS
    final = validate_local_validation_final_receipt(raw.get("final_receipt"))
    stop = validate_local_validation_stop_evidence(raw.get("stopped_runtime_evidence"))
    predecessor_stop = raw.get("predecessor_runtime_stopped_evidence")
    if successor:
        if not isinstance(predecessor_stop, Mapping) or set(predecessor_stop) != LOCAL_VALIDATION_HANDOFF_STOP_FIELDS:
            _fail()
        try:
            started = datetime.fromisoformat(predecessor_stop["started_at"].replace("Z", "+00:00"))
            stopped = datetime.fromisoformat(predecessor_stop["stopped_at"].replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            _fail()
        if (predecessor_stop.get("daemon_id") != "ab9a85ff-1f4a-47a8-a57f-c99b0d7abff7"
                or predecessor_stop.get("container_id") != "942683136ec38f06e1ad1006a3bf7bec96e2174029a05d4524969a50b2468d5d"
                or predecessor_stop.get("image_id") != "1e1dd23a9b5920b507b7daa12c68a0aae0561cb151c35b090e2ce252bc86d934"
                or predecessor_stop.get("started_at") != "2026-10-27T10:06:15.706203884Z"
                or not _utc(predecessor_stop.get("started_at"))
                or not _utc(predecessor_stop.get("stopped_at"))
                or type(predecessor_stop.get("before_pid")) is not int
                or predecessor_stop["before_pid"] <= 0 or predecessor_stop.get("after_pid") != 0
                or predecessor_stop.get("running") is not False
                or predecessor_stop.get("paused") is not False
                or predecessor_stop.get("restarting") is not False
                or predecessor_stop.get("restart_policy") != "no"
                or predecessor_stop.get("pid_mode") not in {"private", ""}
                or not _hex(predecessor_stop.get("mounts_before_sha256"))
                or predecessor_stop.get("mounts_after_sha256") != predecessor_stop.get("mounts_before_sha256")
                or stopped <= started):
            _fail()
    baseline = raw.get("confirmation_baseline")
    baseline_fields = {"schema_version", "root_run_id", "agent_runtime_turns", "agent_runs",
        "agent_runtime_registrations", "agent_acp_native_agent_registrations",
        "agent_acp_tool_ingress_observations", "agent_acp_domain_call_observations",
        "agent_domain_call_evidence", "agent_domain_call_claims", "agent_audit",
        "local_validation_business_facts"}
    if (final["root_run_id"] != "c530d89d59d84c91906954dfe994b540"
            or final["scope"]["runtime_boot_id"] != "a0942b63e3a4c3f7fa260ce58a1d93b1"
            or not isinstance(baseline, Mapping) or set(baseline) != baseline_fields
            or baseline.get("schema_version") != "byq-local-validation-backend-snapshot.v1"
            or baseline.get("root_run_id") != final["root_run_id"]
            or any(not isinstance(baseline[field], list) for field in baseline_fields - {
                "schema_version", "root_run_id", "local_validation_business_facts"})
            or not isinstance(baseline.get("local_validation_business_facts"), Mapping)
            or digest(baseline) != "923e0702c1495e0c8ddeab6ff4fcb4367492ad0241a716b5fa1c9d4579f86e6a"):
        _fail()
    return {"schema_version": LOCAL_VALIDATION_HANDOFF_INPUT_SCHEMA,
            "final_receipt": final, "stopped_runtime_evidence": stop,
            "confirmation_baseline": dict(baseline),
            **({"predecessor_runtime_stopped_evidence": dict(predecessor_stop)} if successor else {})}


def validate_local_validation_handoff_intent(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_HANDOFF_INTENT_FIELDS:
        _fail()
    value = dict(raw)
    final = validate_local_validation_final_receipt(value.get("final_receipt"))
    handoff = validate_local_validation_handoff(value.get("handoff"), final_receipt=final)
    if (value.get("schema_version") != LOCAL_VALIDATION_HANDOFF_INTENT_SCHEMA
            or value.get("runtime_boot_id") != handoff["new_authority"]["boot_id"]
            or value.get("runtime_authority_epoch") != handoff["new_authority"]["epoch"]
            or type(value.get("domain_call_sequence")) is not int
            or value["domain_call_sequence"] < 0
            or value.get("domain_call_drained_sequence") != value.get("domain_call_sequence")
            or not _local_digest_matches(value, "intent_sha256")):
        _fail()
    return value | {"final_receipt": final, "handoff": handoff}


def validate_local_validation_handoff_observation(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_HANDOFF_OBSERVATION_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_HANDOFF_OBSERVATION_SCHEMA):
        _fail()
    value = dict(raw)
    intent = validate_local_validation_handoff_intent(value.get("ack_intent"))
    if (value.get("state") != "released"
            or value.get("slot_scope_sha256") != product_scope_digest(intent["final_receipt"]["scope"])
            or value.get("cleanup_receipt_sha256") != intent["handoff"]["cleanup_receipt_sha256"]
            or not _local_digest_matches(value, "observation_sha256")):
        _fail()
    return value | {"ack_intent": intent}


def validate_local_validation_backend_confirmation(raw: object) -> dict[str, Any]:
    if (isinstance(raw, Mapping)
            and raw.get("schema_version") == LOCAL_VALIDATION_HANDOFF_SCHEMA):
        _fail()
    if (isinstance(raw, Mapping)
            and raw.get("schema_version") == "byq-local-validation-handoff-backend-confirmation.v1"):
        if set(raw) != LOCAL_VALIDATION_HANDOFF_CONFIRMATION_FIELDS:
            _fail()
        value = dict(raw)
        observation = validate_local_validation_handoff_observation(value.get("runtime_observation"))
        final = observation["ack_intent"]["final_receipt"]
        handoff = validate_local_validation_handoff(value.get("handoff"), final_receipt=final)
        if (value.get("root_run_id") != final["root_run_id"]
                or value.get("final_receipt_sha256") != final["receipt_sha256"]
                or value.get("handoff") != handoff
                or type(value.get("operator_uid")) is not int or not 0 <= value["operator_uid"] <= 2**31 - 1
                or not _text(value.get("operator_name"))
                or not _local_digest_matches(value, "receipt_sha256")):
            _fail()
        return value | {"runtime_observation": observation, "handoff": handoff}
    if (not isinstance(raw, Mapping) or set(raw) != LOCAL_VALIDATION_BACKEND_CONFIRMATION_FIELDS
            or raw.get("schema_version") != LOCAL_VALIDATION_BACKEND_CONFIRMATION_SCHEMA):
        _fail()
    value = dict(raw)
    observation = validate_local_validation_release_observation(value.get("runtime_observation"))
    final = observation["ack_intent"]["final_receipt"]
    if (value.get("root_run_id") != final["root_run_id"]
            or value.get("final_receipt_sha256") != final["receipt_sha256"]
            or type(value.get("operator_uid")) is not int
            or not 0 <= value["operator_uid"] <= 2**31 - 1
            or not _text(value.get("operator_name"))
            or not _local_digest_matches(value, "receipt_sha256")):
        _fail()
    return value | {"runtime_observation": observation}


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


def validate_process_fence_handoff(raw: object, *, close_receipt: object | None = None) -> dict[str, Any]:
    """Validate a closed, operator-authorized completed-cleanup boot handoff."""
    if not isinstance(raw, Mapping) or set(raw) != HANDOFF_FIELDS:
        _fail()
    value = dict(raw)
    try:
        scope = validate_product_scope(value.get("scope"))
    except (ProductSlotContractError, TypeError) as exc:
        raise OperatorProcessFenceContractError("handoff scope is invalid") from exc
    old, new, stop, operator = (value.get("old_authority"), value.get("new_authority"),
                                value.get("runtime_stop_proof"), value.get("operator"))
    preflight = value.get("preflight")
    if (value.get("schema_version") != PROCESS_FENCE_HANDOFF_SCHEMA
            or not _hex(value.get("operation_id"), 32) or value.get("root_run_id") != scope["root_run_id"]
            or not all(_hex(value.get(k)) for k in ("proof_receipt_sha256", "process_fence_receipt_sha256",
                "tombstone_sha256", "original_request_sha256",
                "close_receipt_sha256", "runtime_binding_sha256", "terminal_receipt_sha256"))
            or not isinstance(old, Mapping) or set(old) != HANDOFF_AUTHORITY_FIELDS
            or not _hex(old.get("boot_id"), 32) or type(old.get("epoch")) is not int or old["epoch"] < 1
            or not isinstance(new, Mapping) or set(new) != HANDOFF_AUTHORITY_FIELDS
            or not _hex(new.get("boot_id"), 32) or type(new.get("epoch")) is not int or new["epoch"] < 1
            or new["boot_id"] == old["boot_id"] or new["epoch"] <= old["epoch"]
            or not isinstance(preflight, Mapping) or set(preflight) != HANDOFF_PREFLIGHT_FIELDS
            or preflight.get("binding_sha256") != value.get("runtime_binding_sha256")
            or not _hex(preflight.get("reservation_request_sha256"))
            or not _hex(preflight.get("new_authority_receipt_sha256"))
            or preflight.get("runtime_observation_absent") is not True
            or preflight.get("slot_release_absent") is not True
            or type(preflight.get("backend_ack_count")) is not int
            or preflight.get("backend_ack_count") != 0
            or not isinstance(stop, Mapping) or set(stop) != HANDOFF_STOP_PROOF_FIELDS
            or type(stop.get("before_pid")) is not int or stop["before_pid"] < 1
            or type(stop.get("after_pid")) is not int or stop["after_pid"] != 0
            or stop.get("running") is not False or stop.get("paused") is not False
            or stop.get("restarting") is not False
            or not _text(stop.get("daemon_id"), maximum=256)
            or not _hex(stop.get("container_id")) or not _hex(stop.get("image_id"))
            or not _utc(stop.get("started_at"))
            or not _utc(stop.get("stopped_at")) or stop.get("restart_policy") != "no"
            or stop.get("pid_mode") not in {"private", ""}
            or not _hex(stop.get("mounts_before_sha256"))
            or stop.get("mounts_before_sha256") != stop.get("mounts_after_sha256")
            or not isinstance(operator, Mapping) or set(operator) != OPERATOR_FIELDS
            or type(operator.get("uid")) is not int or not 0 <= operator["uid"] <= 2**32 - 1
            or not _text(operator.get("name"), maximum=256) or not _utc(value.get("created_at"))
            or not _hex(value.get("handoff_sha256"))
            or digest({k: v for k, v in value.items() if k != "handoff_sha256"}) != value["handoff_sha256"]):
        _fail()
    if (value["operation_id"] != "a510a3c04f2abd4aa22d7ac72347e315"
            or value["root_run_id"] != "7ff777b689024eb49076cdf6d65a3624"
            or scope["workspace_id"] != "workspace_4c5b803209d549019b7804976f6930c6"
            or value["proof_receipt_sha256"] != "82cff128ed5f46694b27a917b4eb349614fa8d1fbcaf64d2c75238f5a4baa217"):
        _fail()
    if (value["original_request_sha256"] != "4d2ae64dbb97d224105120b50c28f0065c9f6bc63da134583eae3e6c9e04f39a"
            or preflight["reservation_request_sha256"] != value["original_request_sha256"]
            or stop["daemon_id"] != "ab9a85ff-1f4a-47a8-a57f-c99b0d7abff7"
            or stop["container_id"] != "cf6db383b15a5aa4b77ad6af2855962511a9132d9ae972d426c08f8cf75d0a35"
            or stop["image_id"] != "804c19e92eecefcf7be47f44c081f5a219c620701f7ffe95128d2f4aacf1e3f9"
            or stop["started_at"] != "2026-10-25T09:45:46.375099034Z"
            or value["old_authority"] != {"boot_id": "7415380060d6c1e71aa91bcc3c02ad30", "epoch": 27}):
        _fail()
    if close_receipt is not None:
        close = validate_fence_close_receipt(close_receipt)
        completed = close.get("operator_completed_cleanup")
        if (close.get("operation_id") != value["operation_id"] or close.get("scope") != scope
                or close.get("runtime_binding_sha256") != value["runtime_binding_sha256"]
                or not isinstance(completed, Mapping)
                or completed.get("original_terminal_receipt_sha256") != value["terminal_receipt_sha256"]
                or close.get("process_fence_receipt_sha256") != value["process_fence_receipt_sha256"]
                or close.get("runner", {}).get("tombstone_sha256") != value["tombstone_sha256"]
                or close.get("authority", {}).get("current_boot_id") != old["boot_id"]
                or close.get("authority", {}).get("current_epoch") != old["epoch"]
                or close.get("authority", {}).get("previous_boot_id") == old["boot_id"]
                or close.get("authority", {}).get("previous_epoch") >= old["epoch"]
                or digest(close) != value["close_receipt_sha256"]):
            _fail()
    return value


def validate_process_fence_handoff_request(raw: object) -> dict[str, Any]:
    if (not isinstance(raw, Mapping) or set(raw) != HANDOFF_REQUEST_FIELDS
            or raw.get("schema_version") != PROCESS_FENCE_HANDOFF_REQUEST_SCHEMA):
        _fail()
    close = validate_fence_close_receipt(raw.get("close_receipt"))
    handoff = validate_process_fence_handoff(raw.get("handoff"), close_receipt=close)
    return {"schema_version": raw["schema_version"], "handoff": handoff, "close_receipt": close}


def validate_process_fence_handoff_observation(raw: object, *, handoff: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != HANDOFF_OBSERVATION_FIELDS:
        _fail()
    value = dict(raw)
    if (value.get("schema_version") != PROCESS_FENCE_HANDOFF_OBSERVATION_SCHEMA
            or value.get("operation_id") != handoff.get("operation_id")
            or value.get("handoff_sha256") != handoff.get("handoff_sha256")
            or value.get("root_run_id") != handoff.get("root_run_id")
            or value.get("scope") != handoff.get("scope")
            or value.get("runtime_boot_id") != handoff.get("new_authority", {}).get("boot_id")
            or value.get("runtime_authority_epoch") != handoff.get("new_authority", {}).get("epoch")
            or not _hex(value.get("original_binding_sha256"))
            or value.get("original_binding_sha256") != handoff.get("runtime_binding_sha256")
            or not _utc(value.get("observed_at")) or not _hex(value.get("receipt_sha256"))
            or digest({k: v for k, v in value.items() if k != "receipt_sha256"}) != value["receipt_sha256"]):
        _fail()
    drain, release = value.get("domain_call_drain"), value.get("slot_release")
    if (not isinstance(drain, Mapping) or set(drain) != DOMAIN_DRAIN_FIELDS
            or drain.get("schema_version") != "byq-runtime-domain-call-drain.v1"
            or drain.get("root_run_id") != handoff["root_run_id"]
            or type(drain.get("last_domain_sequence")) is not int
            or drain.get("last_domain_sequence") < 0
            or type(drain.get("drained_sequence")) is not int
            or drain.get("drained_sequence") != drain.get("last_domain_sequence")
            or not _hex(drain.get("drain_receipt_sha256"))
            or digest({k: v for k, v in drain.items() if k != "drain_receipt_sha256"})
               != drain["drain_receipt_sha256"]
            or not isinstance(release, Mapping) or set(release) != SLOT_RELEASE_FIELDS
            or release.get("schema_version") != "byq-acp-operator-process-fence-slot-release.v1"
            or release.get("workspace_id") != handoff["scope"].get("workspace_id")
            or release.get("root_run_id") != handoff["root_run_id"]
            or release.get("scope_sha256") != digest(handoff["scope"])
            or release.get("process_fence_receipt_sha256") != handoff["process_fence_receipt_sha256"]
            or release.get("tombstone_sha256") != handoff["tombstone_sha256"]
            or type(release.get("drained_sequence")) is not int or release["drained_sequence"] < 0
            or release.get("drained_sequence") != drain.get("drained_sequence")
            or release.get("status") != "released" or not _utc(release.get("released_at"))
            or not _hex(release.get("release_receipt_sha256"))
            or digest({k: v for k, v in release.items() if k != "release_receipt_sha256"})
               != release["release_receipt_sha256"]):
        _fail()
    return value


def validate_process_fence_handoff_confirmation(raw: object, *, handoff: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != HANDOFF_CONFIRMATION_FIELDS:
        _fail()
    value = dict(raw)
    observation = validate_process_fence_handoff_observation(value.get("runtime_observation"), handoff=handoff)
    operator = value.get("operator")
    if (value.get("schema_version") != PROCESS_FENCE_HANDOFF_CONFIRMATION_SCHEMA
            or value.get("operation_id") != handoff.get("operation_id")
            or value.get("handoff_sha256") != handoff.get("handoff_sha256")
            or value.get("proof_receipt_sha256") != handoff.get("proof_receipt_sha256")
            or value.get("close_receipt_sha256") != handoff.get("close_receipt_sha256")
            or not isinstance(operator, Mapping) or set(operator) != OPERATOR_FIELDS
            or type(operator.get("uid")) is not int or not _text(operator.get("name"), maximum=256)
            or not _utc(value.get("confirmed_at")) or not _hex(value.get("receipt_sha256"))
            or digest({k: v for k, v in value.items() if k != "receipt_sha256"}) != value["receipt_sha256"]):
        _fail()
    return value | {"runtime_observation": observation}


def validate_process_fence_request(raw: object, *, completed_cleanup: bool = False) -> dict[str, Any]:
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
    settlement = parsed_binding.get("settlement_receipt")
    if (parsed_binding.get("schema_version") != "byq-acp-root-binding.v2"
            or not isinstance(runtime_binding, Mapping) or set(runtime_binding) != START_BINDING_FIELDS
            or runtime_binding.get("schema_version") != START_BINDING_SCHEMA
            or parsed_binding.get("closed") is not False
            or parsed_binding.get("native_session_close_confirmed") is not completed_cleanup
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
            or parsed_binding["cwd"].rsplit("/", 1)[-1] != scope["cwd_leaf"]
            or (settlement is not None and (
                not isinstance(settlement, Mapping)
                or set(settlement) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
                or settlement.get("schema_version") != "agent-run-lifecycle-receipt.v1"
                or settlement.get("root_run_id") != scope["root_run_id"]
                or type(settlement.get("sequence")) is not int
                or not 1 <= settlement["sequence"] <= parsed_binding["sequence"]
                or not _hex(settlement.get("event_sha256"))))):
        _fail()
    return value


def validate_completed_cleanup_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != COMPLETED_CLEANUP_REQUEST_FIELDS:
        _fail()
    value = dict(raw)
    request = value.get("process_fence_request")
    try:
        request = validate_process_fence_request(request, completed_cleanup=True)
    except (OperatorProcessFenceContractError, TypeError, ValueError):
        _fail()
    terminal = value.get("original_terminal_receipt")
    if (value.get("schema_version") != COMPLETED_CLEANUP_REQUEST_SCHEMA
            or not isinstance(terminal, Mapping)
            or set(terminal) != {"schema_version", "root_run_id", "sequence", "event_sha256"}
            or terminal.get("schema_version") != "agent-run-lifecycle-receipt.v1"
            or terminal.get("root_run_id") != request["scope"]["root_run_id"]
            or type(terminal.get("sequence")) is not int or terminal["sequence"] < 1
            or not _hex(terminal.get("event_sha256"))):
        _fail()
    from .agent_run_lifecycle import lifecycle_receipt
    expected = lifecycle_receipt({"schema_version": "agent-run-lifecycle.v1",
        "root_run_id": terminal["root_run_id"], "sequence": terminal["sequence"],
        "outcome": "completed"})
    observed_settlement = parsed_runtime_binding_observation(
        request["runtime_binding_observation"]).get("settlement_receipt")
    if terminal != expected or observed_settlement != dict(terminal):
        _fail()
    return {**value, "process_fence_request": request, "original_terminal_receipt": dict(terminal)}


def validate_completed_cleanup_fact(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != COMPLETED_CLEANUP_FACT_FIELDS:
        _fail()
    value = dict(raw)
    if (value.get("schema_version") != COMPLETED_CLEANUP_PROOF_SCHEMA
            or value.get("outcome") != "completed"
            or not _hex(value.get("operation_id"), 32)
            or not _hex(value.get("root_run_id"), 32)
            or not _hex(value.get("original_terminal_receipt_sha256"))
            or not _hex(value.get("process_fence_receipt_sha256"))
            or type(value.get("terminal_acp_ingress_sequence")) is not int
            or value["terminal_acp_ingress_sequence"] < 0
            or not _hex(value.get("terminal_acp_ingress_sha256"))
            or type(value.get("terminal_unknown_claim_count")) is not int
            or value["terminal_unknown_claim_count"] != 0
            or not _hex(value.get("terminal_unknown_claims_sha256"))
            or not _hex(value.get("receipt_sha256"))
            or digest({key: item for key, item in value.items()
                       if key != "receipt_sha256"}) != value["receipt_sha256"]):
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


def validate_operator_failed_terminal(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != FAILED_TERMINAL_FIELDS:
        _fail()
    value = dict(raw)
    if (value.get("schema_version") != FAILED_TERMINAL_SCHEMA
            or value.get("outcome") != "failed"
            or not _hex(value.get("operation_id"), 32)
            or not _hex(value.get("root_run_id"), 32)
            or not _hex(value.get("process_fence_receipt_sha256"))
            or type(value.get("sequence")) is not int or value["sequence"] < 1
            or not _hex(value.get("event_sha256"))
            or type(value.get("terminal_acp_ingress_sequence")) is not int
            or value["terminal_acp_ingress_sequence"] < 0
            or not _hex(value.get("terminal_acp_ingress_sha256"))
            or value.get("terminal_unknown_claim_count") != 0
            or not _hex(value.get("terminal_unknown_claims_sha256"))
            or not _hex(value.get("receipt_sha256"))
            or digest({key: item for key, item in value.items()
                       if key != "receipt_sha256"}) != value["receipt_sha256"]):
        _fail()
    return value


def validate_process_fence_proof(raw: object) -> dict[str, Any]:
    failed_terminal = isinstance(raw, Mapping) and "operator_failed_terminal" in raw
    completed_cleanup = isinstance(raw, Mapping) and "operator_completed_cleanup" in raw
    if failed_terminal and completed_cleanup:
        _fail()
    terminal_cleanup = failed_terminal or completed_cleanup
    fact_key = ("operator_failed_terminal" if failed_terminal else
                "operator_completed_cleanup" if completed_cleanup else "operator_interruption")
    expected_fields = ((PROOF_FIELDS - {"operator_interruption"}) | {fact_key}
                       if terminal_cleanup else PROOF_FIELDS)
    if not isinstance(raw, Mapping) or set(raw) != expected_fields:
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
    validated_request = validate_process_fence_request(request, completed_cleanup=completed_cleanup)
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
    if len(root_rows) != 1 or (not agent_runs and not terminal_cleanup):
        _fail()
    if not agent_runs and any(item["table"] in {
        "agent_acp_native_agent_registrations", "agent_runtime_registrations",
        "agent_acp_tool_ingress_observations", "agent_acp_domain_call_observations",
        "agent_domain_call_evidence", "agent_domain_correction_buckets",
        "agent_domain_call_claims", "agent_approvals", "agent_audit",
    } for item in rows):
        # A plain failed Root is valid only with a completely empty child graph.
        _fail()
    root_row = root_rows[0]
    frozen_settlement = parsed_runtime_binding_observation(
        value["runtime_binding_observation"]).get("settlement_receipt")
    if terminal_cleanup:
        expected_terminal = {
            "schema_version": "agent-run-lifecycle-receipt.v1",
            "root_run_id": root_id,
            "sequence": root_row.get("terminal_sequence"),
            "event_sha256": root_row.get("terminal_event_sha256"),
        }
        if ((completed_cleanup and frozen_settlement != expected_terminal)
                or (failed_terminal and frozen_settlement not in (None, expected_terminal))):
            _fail()
        terminal_receipts = [item["row"] for item in rows
                             if item["table"] == "agent_runtime_receipts"
                             and item["row"].get("sequence") == root_row.get("terminal_sequence")]
        if (len(terminal_receipts) > 1
                or not terminal_receipts and frozen_settlement != expected_terminal
                or terminal_receipts and (
                    terminal_receipts[0].get("trace_id") != scope["trace_id"]
                    or terminal_receipts[0].get("receipt_json") != expected_terminal)):
            _fail()
    elif frozen_settlement is not None and not completed_cleanup:
        _fail()
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
            or len(root_agent_runs) != (1 if agent_runs else 0)
            or (agent_runs and root_agent_runs[0].get("status")
                != ("failed" if failed_terminal else "completed" if completed_cleanup else "active"))
            or (agent_runs and root_agent_runs[0].get("authority_status") not in
                ({"closed"} if terminal_cleanup else {"active", "authority_revoked_unconfirmed"}))
            or value.get("terminal_unknown_claim_count") != 0):
        _fail()
    root_delta = delta["root"]
    if (root_delta.get("id") != root_id
            or root_row.get("owner_principal") != scope["owner_principal"]
            or root_row.get("workspace_id") != scope["workspace_id"]
            or root_row.get("session_id") != scope["session_id"]
            or root_row.get("trace_id") != scope["trace_id"]
            or root_row.get("status") != ("failed" if failed_terminal else "completed" if completed_cleanup else "active")
            or root_row.get("authority_status") not in
                ({"closed"} if terminal_cleanup else {"active", "authority_revoked_unconfirmed"})
            or (terminal_cleanup and (type(root_row.get("terminal_sequence")) is not int
                 or root_row["terminal_sequence"] < 1 or not _hex(root_row.get("terminal_event_sha256"))))
            or (not terminal_cleanup and (root_row.get("terminal_sequence") is not None
                 or root_row.get("terminal_event_sha256") is not None))
            or set(root_delta["before"]) != DELTA_ROOT_MUTABLE
            or set(root_delta["after"]) != DELTA_ROOT_MUTABLE
            or any(root_delta["before"].get(key) != root_row.get(key) for key in DELTA_ROOT_MUTABLE)
            or root_delta["after"].get("status") != ("failed" if failed_terminal else "completed" if completed_cleanup else "interrupted")
            or root_delta["after"].get("authority_status") != "closed"
            or (terminal_cleanup and root_delta["after"] != root_delta["before"])
            or (not terminal_cleanup and root_delta["after"].get("updated_at") != delta["close_at"])
            or any(root_delta["after"].get(key) != value.get(key)
                   for key in ("terminal_acp_ingress_sequence", "terminal_acp_ingress_sha256",
                               "terminal_unknown_claim_count", "terminal_unknown_claims_sha256"))):
        _fail()
    run_delta = delta["agent_runs"]
    active_runs = [row for row in agent_runs if row.get("status") == "active"
                   and row.get("authority_status") in {"active", "authority_revoked_unconfirmed"}]
    terminal_runs = [row for row in agent_runs if row not in active_runs]
    if (len(run_delta) != len(active_runs)
            or (terminal_cleanup and active_runs)
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
    fact = (validate_operator_failed_terminal(value.get(fact_key)) if failed_terminal
            else validate_completed_cleanup_fact(value.get(fact_key)) if completed_cleanup
            else validate_operator_interruption(value.get(fact_key)))
    if (fact["operation_id"] != value["operation_id"]
            or fact["root_run_id"] != value["scope"].get("root_run_id")
            or fact["process_fence_receipt_sha256"] != value["process_fence_receipt_sha256"]
            or fact["terminal_acp_ingress_sequence"] != value["terminal_acp_ingress_sequence"]
            or fact["terminal_acp_ingress_sha256"] != value["terminal_acp_ingress_sha256"]
            or fact["terminal_unknown_claim_count"] != value["terminal_unknown_claim_count"]
            or fact["terminal_unknown_claims_sha256"] != value["terminal_unknown_claims_sha256"]
            or (failed_terminal and (fact["sequence"] != root_row["terminal_sequence"]
                or fact["event_sha256"] != root_row["terminal_event_sha256"]))
            or (completed_cleanup and (
                fact["original_terminal_receipt_sha256"] != digest(frozen_settlement)
                or fact["terminal_acp_ingress_sequence"] != root_row.get("terminal_acp_ingress_sequence")
                or fact["terminal_acp_ingress_sha256"] != root_row.get("terminal_acp_ingress_sha256")
                or fact["terminal_unknown_claim_count"] != root_row.get("terminal_unknown_claim_count")
                or fact["terminal_unknown_claims_sha256"] != root_row.get("terminal_unknown_claims_sha256")))):
        _fail()
    operator = value.get("operator")
    if (not isinstance(operator, Mapping) or set(operator) != OPERATOR_FIELDS
            or type(operator.get("uid")) is not int or not 0 <= operator["uid"] <= 2**32 - 1
            or not _text(operator.get("name"), maximum=256)
            or value.get("disposition") != ("operator_failed_terminal_fence_confirmed"
                if failed_terminal else "operator_completed_cleanup_confirmed" if completed_cleanup
                else "operator_process_fence_confirmed")
            or not _hex(value.get("process_fence_receipt_sha256"))
            or not _hex(value.get("receipt_sha256"))):
        _fail()
    process_payload = {key: item for key, item in value.items()
                       if key not in {"operator_interruption", "operator_failed_terminal", "operator_completed_cleanup",
                                      "process_fence_receipt_sha256", "receipt_sha256"}}
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
    failed_terminal = isinstance(runtime_ack, Mapping) and FAILED_FACT_DIGEST_FIELD in runtime_ack
    completed_cleanup = isinstance(runtime_ack, Mapping) and COMPLETED_CLEANUP_DIGEST_FIELD in runtime_ack
    if failed_terminal and completed_cleanup:
        _fail()
    fact_digest_field = (FAILED_FACT_DIGEST_FIELD if failed_terminal else
                         COMPLETED_CLEANUP_DIGEST_FIELD if completed_cleanup else INTERRUPTION_DIGEST_FIELD)
    ack_fields = ((RUNTIME_ACK_FIELDS - {INTERRUPTION_DIGEST_FIELD}) | {FAILED_FACT_DIGEST_FIELD}
                  if failed_terminal else (RUNTIME_ACK_FIELDS - {INTERRUPTION_DIGEST_FIELD})
                  | {COMPLETED_CLEANUP_DIGEST_FIELD} if completed_cleanup else RUNTIME_ACK_FIELDS)
    if not isinstance(runtime_ack, Mapping) or set(runtime_ack) != ack_fields:
        _fail()
    if not isinstance(drain, Mapping) or set(drain) != DOMAIN_DRAIN_FIELDS:
        _fail()
    if not isinstance(release, Mapping) or set(release) != SLOT_RELEASE_FIELDS:
        _fail()
    expected_ack_schema = (COMPLETED_CLEANUP_ACK_SCHEMA if completed_cleanup
                           else "byq-runtime-operator-terminal-ack.v1")
    if (runtime_ack.get("schema_version") != expected_ack_schema
            or not _hex(runtime_ack.get("root_run_id"), 32)
            or not _hex(runtime_ack.get("runtime_boot_id"), 32)
            or any(not _hex(runtime_ack.get(field)) for field in (
                "scope_sha256", "process_fence_receipt_sha256", fact_digest_field,
                "root_binding_sha256", "terminal_ack_sha256"))
            or not _utc(runtime_ack.get("acknowledged_at"))
            or runtime_ack.get("scope_sha256") != digest(value["scope"])
            or runtime_ack.get("root_run_id") != value["scope"].get("root_run_id")
            or runtime_ack.get("runtime_boot_id") != (
                value["authority"].get("current_boot_id") if completed_cleanup
                else value["scope"].get("runtime_boot_id"))):
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
    failed_terminal = isinstance(raw, Mapping) and FAILED_FACT_DIGEST_FIELD in raw
    completed_cleanup = isinstance(raw, Mapping) and COMPLETED_CLEANUP_DIGEST_FIELD in raw
    if failed_terminal and completed_cleanup:
        _fail()
    fact_digest_field = (FAILED_FACT_DIGEST_FIELD if failed_terminal else
                         COMPLETED_CLEANUP_DIGEST_FIELD if completed_cleanup else INTERRUPTION_DIGEST_FIELD)
    expected_fields = ((ACK_RECEIPT_FIELDS - {INTERRUPTION_DIGEST_FIELD}) | {FAILED_FACT_DIGEST_FIELD}
                       if failed_terminal else (ACK_RECEIPT_FIELDS - {INTERRUPTION_DIGEST_FIELD})
                       | {COMPLETED_CLEANUP_DIGEST_FIELD} if completed_cleanup else ACK_RECEIPT_FIELDS)
    if not isinstance(raw, Mapping) or set(raw) != expected_fields:
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
            or not _hex(value.get(fact_digest_field))
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
    failed_terminal = isinstance(raw, Mapping) and "operator_failed_terminal" in raw
    completed_cleanup = isinstance(raw, Mapping) and "operator_completed_cleanup" in raw
    if failed_terminal and completed_cleanup:
        _fail()
    fact_key = ("operator_failed_terminal" if failed_terminal else
                "operator_completed_cleanup" if completed_cleanup else "operator_interruption")
    expected_fields = ((FENCE_CLOSE_RECEIPT_FIELDS - {"operator_interruption"})
                       | {fact_key} if failed_terminal or completed_cleanup
                       else FENCE_CLOSE_RECEIPT_FIELDS)
    if not isinstance(raw, Mapping) or set(raw) != expected_fields:
        _fail()
    value = dict(raw)
    fact = (validate_operator_failed_terminal(value.get("operator_failed_terminal"))
            if failed_terminal else validate_completed_cleanup_fact(value.get("operator_completed_cleanup"))
            if completed_cleanup else validate_operator_interruption(value.get("operator_interruption")))
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
            or fact.get("operation_id") != value.get("operation_id")
            or fact.get("root_run_id") != value.get("root_run_id")
            or scope.get("workspace_id") != value.get("workspace_id")
            or scope.get("root_run_id") != value.get("root_run_id")
            or authority.get("previous_boot_id") != scope.get("runtime_boot_id")
            or (authority.get("current_boot_id") == authority.get("previous_boot_id")
                and authority.get("current_epoch") != authority.get("previous_epoch"))
            or (authority.get("current_boot_id") != authority.get("previous_boot_id")
                and authority.get("current_epoch") <= authority.get("previous_epoch"))
            or fact.get("process_fence_receipt_sha256")
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
    failed_terminal = isinstance(raw, Mapping) and "operator_failed_terminal" in raw
    completed_cleanup = isinstance(raw, Mapping) and "operator_completed_cleanup" in raw
    if failed_terminal and completed_cleanup:
        _fail()
    fact_digest_field = (FAILED_FACT_DIGEST_FIELD if failed_terminal else
                         COMPLETED_CLEANUP_DIGEST_FIELD if completed_cleanup else INTERRUPTION_DIGEST_FIELD)
    expected_fields = ((OPERATOR_OBSERVATION_FIELDS - {INTERRUPTION_DIGEST_FIELD})
                       | {"operator_failed_terminal", FAILED_FACT_DIGEST_FIELD} if failed_terminal
                       else (OPERATOR_OBSERVATION_FIELDS - {INTERRUPTION_DIGEST_FIELD})
                       | {"operator_completed_cleanup", COMPLETED_CLEANUP_DIGEST_FIELD} if completed_cleanup
                       else OPERATOR_OBSERVATION_FIELDS)
    if not isinstance(raw, Mapping) or set(raw) != expected_fields:
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
            or not _hex(value.get(fact_digest_field))
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
    if failed_terminal:
        fact = validate_operator_failed_terminal(value["operator_failed_terminal"])
        if (fact["operation_id"] != value["operation_id"]
                or fact["root_run_id"] != scope["root_run_id"]
                or fact["process_fence_receipt_sha256"] != value["process_fence_receipt_sha256"]
                or fact["receipt_sha256"] != value[fact_digest_field]
                or value["superseded_terminal"] is not None):
            _fail()
    elif completed_cleanup:
        fact = validate_completed_cleanup_fact(value["operator_completed_cleanup"])
        if (fact["operation_id"] != value["operation_id"]
                or fact["root_run_id"] != scope["root_run_id"]
                or fact["process_fence_receipt_sha256"] != value["process_fence_receipt_sha256"]
                or fact["receipt_sha256"] != value[fact_digest_field]
                or value["superseded_terminal"] is not None):
            _fail()
    if (ack.get("terminal_ack_sha256") != value["close_receipt_sha256"]
            or ack.get("process_fence_receipt_sha256") != value["process_fence_receipt_sha256"]
            or ack.get(fact_digest_field) != value[fact_digest_field]
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
    fact = close.get("operator_failed_terminal", close.get("operator_completed_cleanup",
                      close.get("operator_interruption")))
    fact_digest_field = (FAILED_FACT_DIGEST_FIELD if "operator_failed_terminal" in close else
                         COMPLETED_CLEANUP_DIGEST_FIELD if "operator_completed_cleanup" in close
                         else INTERRUPTION_DIGEST_FIELD)
    if (value.get("operation_id") != close["operation_id"]
            or value.get("close_receipt_sha256") != digest(close)
            or value.get("process_fence_receipt_sha256") != close["process_fence_receipt_sha256"]
            or value.get(fact_digest_field) != fact["receipt_sha256"]
            or value.get("scope") != close["scope"]
            or value.get("authority") != close["authority"]
            or value.get("runner") != close["runner"]
            or value.get("engineering_evidence_sha256") != close["engineering_evidence_sha256"]
            or value.get("runtime_binding_sha256") != close["runtime_binding_sha256"]):
        _fail()
    if ("operator_failed_terminal" in close) != ("operator_failed_terminal" in value):
        _fail()
    if "operator_failed_terminal" in close and value["operator_failed_terminal"] != fact:
        _fail()
    if ("operator_completed_cleanup" in close) != ("operator_completed_cleanup" in value):
        _fail()
    if "operator_completed_cleanup" in close and value["operator_completed_cleanup"] != fact:
        _fail()
    return value
