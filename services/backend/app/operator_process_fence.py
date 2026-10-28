"""Private Engineering CLI and reset guard for ADR-0104 operator fences.

This module is not mounted as an HTTP or MCP route. Native evidence is supplied
only by a restricted local Engineering invocation and is stored in the
reserved global operations-audit namespace.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import pwd
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from packages.contracts.acp_operator_process_fence import (
    ACK_ACTION,
    ACK_IDEMPOTENCY_PREFIX,
    HANDOFF_ACTION,
    HANDOFF_IDEMPOTENCY_PREFIX,
    HANDOFF_ACK_ACTION,
    HANDOFF_ACK_IDEMPOTENCY_PREFIX,
    PROCESS_FENCE_HANDOFF_REQUEST_SCHEMA,
    PROCESS_FENCE_ACTION,
    PROCESS_FENCE_IDEMPOTENCY_PREFIX,
    canonical_json,
    digest,
    validate_ack_receipt,
    validate_fence_close_receipt,
    validate_operator_observation,
    validate_process_fence_proof,
    validate_process_fence_request,
    validate_local_validation_close_request,
    validate_local_validation_pre_ack_request,
    LOCAL_VALIDATION_PRE_ACK_SCHEMA,
    validate_local_validation_projection,
    LOCAL_VALIDATION_ACK_REQUEST_SCHEMA,
    LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA,
    LOCAL_VALIDATION_HANDOFF_INPUT_SCHEMA,
    validate_local_validation_handoff_request,
    validate_local_validation_handoff_input,
    validate_local_validation_handoff_observation,
    validate_local_validation_stop_evidence,
    validate_local_validation_ack_request,
    validate_local_validation_final_receipt,
    validate_local_validation_release_observation,
    validate_local_validation_backend_confirmation,
    COMPLETED_CLEANUP_REQUEST_SCHEMA,
    validate_completed_cleanup_request,
    validate_process_fence_handoff,
    validate_process_fence_handoff_observation,
    validate_process_fence_handoff_confirmation,
    validate_process_fence_handoff_request,
)
from .db import execute


MAX_RESERVED_ROWS = 10_000
MAX_PRIVATE_INPUT_BYTES = 2 * 1024 * 1024


class OperatorProcessFenceHold(RuntimeError):
    """An R2 proof or ACK row is missing, malformed, or still required."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OperatorProcessFenceHold("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise OperatorProcessFenceHold("non-finite JSON value")


def _read_private_json(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    try:
        before = os.lstat(path)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o077
                or before.st_size > MAX_PRIVATE_INPUT_BYTES):
            raise OperatorProcessFenceHold("input is not a private bounded regular file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            opened = os.fstat(descriptor)
            if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_uid != os.getuid() or opened.st_mode & 0o077
                    or opened.st_size > MAX_PRIVATE_INPUT_BYTES):
                raise OperatorProcessFenceHold("input changed while opening")
            raw = bytearray()
            while len(raw) <= MAX_PRIVATE_INPUT_BYTES:
                block = os.read(descriptor, min(65_536, MAX_PRIVATE_INPUT_BYTES + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            after = os.fstat(descriptor)
            if (len(raw) > MAX_PRIVATE_INPUT_BYTES or len(raw) != after.st_size
                    or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns,
                        opened.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
                                                after.st_mtime_ns, after.st_ctime_ns)):
                raise OperatorProcessFenceHold("input changed while reading")
        finally:
            os.close(descriptor)
    except OperatorProcessFenceHold:
        raise
    except (OSError, ValueError) as exc:
        raise OperatorProcessFenceHold("private input is unavailable") from exc
    try:
        value = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_strict_object,
                           parse_constant=_reject_constant)
    except OperatorProcessFenceHold:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise OperatorProcessFenceHold("private input JSON is invalid") from exc
    if not isinstance(value, dict):
        raise OperatorProcessFenceHold("private input must be a JSON object")
    return value


def _engineering_operator() -> dict[str, object]:
    uid = os.getuid()
    try:
        name = pwd.getpwuid(uid).pw_name
    except (KeyError, OSError) as exc:
        raise OperatorProcessFenceHold("Engineering operator identity is unavailable") from exc
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 256:
        raise OperatorProcessFenceHold("Engineering operator identity is invalid")
    return {"uid": uid, "name": name}


def _expected_audit_id(prefix: str, idempotency_key: str) -> str:
    import hashlib

    return prefix + hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()


def _validate_reserved_proof_row(row: dict[str, Any]) -> dict[str, Any]:
    detail = row.get("detail_json")
    if (row.get("action") != PROCESS_FENCE_ACTION
            or not isinstance(row.get("idempotency_key"), str)
            or not row["idempotency_key"].startswith(PROCESS_FENCE_IDEMPOTENCY_PREFIX)
            or not isinstance(detail, dict) or set(detail) != {"proof"}):
        raise OperatorProcessFenceHold("reserved process-fence row is malformed")
    proof = validate_process_fence_proof(detail["proof"])
    key = PROCESS_FENCE_IDEMPOTENCY_PREFIX + proof["operation_id"]
    operator = proof["operator"]
    if (row.get("audit_id") != _expected_audit_id("ops_acp_process_fence_", key)
            or row.get("idempotency_key") != key
            or row.get("resource_type") != "workspace"
            or row.get("resource_id") != proof["scope"]["workspace_id"]
            or row.get("outcome") != "closed"
            or row.get("request_sha256") != proof["request_sha256"]
            or row.get("actor_principal") != f"engineering:{operator['name']}:{operator['uid']}"):
        raise OperatorProcessFenceHold("reserved process-fence row identity is inconsistent")
    response = validate_fence_close_receipt(row.get("response_json"))
    fact_key = ("operator_failed_terminal" if "operator_failed_terminal" in proof else
                "operator_completed_cleanup" if "operator_completed_cleanup" in proof
                else "operator_interruption")
    if (response.get("operation_id") != proof["operation_id"]
            or response.get("workspace_id") != proof["scope"]["workspace_id"]
            or response.get("root_run_id") != proof["scope"]["root_run_id"]
            or response.get("process_fence_receipt_sha256") != proof["process_fence_receipt_sha256"]
            or response.get(fact_key) != proof[fact_key]
            or response.get("scope") != proof["scope"]
            or response.get("authority") != proof["authority"]
            or response.get("runner") != {
                "old_runner_instance_id": proof["old_runner"]["runner_instance_id"],
                "successor_runner_instance_id": proof["successor"]["runner_instance_id"],
                "tombstone_sha256": proof["successor"]["tombstone_sha256"],
            }
            or response.get("engineering_evidence_sha256") != proof["engineering_evidence_sha256"]
            or response.get("runtime_binding_sha256") != proof["runtime_binding_sha256"]):
        raise OperatorProcessFenceHold("reserved process-fence response differs from its proof")
    return proof


def _validate_reserved_ack_row(row: dict[str, Any]) -> dict[str, Any]:
    detail = row.get("detail_json")
    if (row.get("action") != ACK_ACTION
            or not isinstance(row.get("idempotency_key"), str)
            or not row["idempotency_key"].startswith(ACK_IDEMPOTENCY_PREFIX)
            or not isinstance(detail, dict) or set(detail) != {"ack_request"}):
        raise OperatorProcessFenceHold("reserved process-fence ACK row is malformed")
    from packages.contracts.acp_operator_process_fence import validate_ack_request

    request = validate_ack_request(detail["ack_request"])
    ack = validate_ack_receipt(row.get("response_json"))
    key = ACK_IDEMPOTENCY_PREFIX + request["operation_id"]
    runtime_ack = request["runtime_ack"]
    fact_digest_key = ("operator_failed_terminal_receipt_sha256"
                       if "operator_failed_terminal_receipt_sha256" in runtime_ack
                       else "operator_completed_cleanup_receipt_sha256"
                       if "operator_completed_cleanup_receipt_sha256" in runtime_ack
                       else "operator_interruption_receipt_sha256")
    drain = request["domain_call_drain"]
    release = request["slot_release"]
    operator = ack["operator"]
    if (row.get("audit_id") != _expected_audit_id("ops_acp_process_fence_ack_", key)
            or row.get("idempotency_key") != key
            or row.get("resource_type") != "workspace"
            or row.get("resource_id") != request["scope"]["workspace_id"]
            or row.get("outcome") != "confirmed"
            or row.get("request_sha256") != digest(request)
            or row.get("actor_principal") != f"engineering:{operator['name']}:{operator['uid']}"
            or ack.get("operation_id") != request["operation_id"]
            or ack.get("scope") != request["scope"]
            or ack.get("authority") != request["authority"]
            or ack.get("runner") != request["runner"]
            or ack.get("proof_receipt_sha256") != request["proof_receipt_sha256"]
            or ack.get(fact_digest_key) != runtime_ack[fact_digest_key]
            or ack.get("runtime_ack_sha256") != digest(runtime_ack)
            or ack.get("root_binding_sha256") != runtime_ack["root_binding_sha256"]
            or ack.get("terminal_ack_sha256") != runtime_ack["terminal_ack_sha256"]
            or ack.get("last_domain_sequence") != drain["last_domain_sequence"]
            or ack.get("drained_sequence") != drain["drained_sequence"]
            or ack.get("drain_receipt_sha256") != drain["drain_receipt_sha256"]
            or ack.get("slot_release_sha256") != release["release_receipt_sha256"]
            or ack.get("confirmed_at") != request["confirmed_at"]
            or ack.get("engineering_evidence_sha256") != request["engineering_evidence_sha256"]
            or ack.get("superseded_terminal") != request["superseded_terminal"]):
        raise OperatorProcessFenceHold("reserved process-fence ACK identity is inconsistent")
    return ack


def _validate_reserved_handoff_row(row: dict[str, Any]) -> dict[str, Any]:
    detail = row.get("detail_json")
    if (row.get("action") != HANDOFF_ACTION or not isinstance(row.get("idempotency_key"), str)
            or not row["idempotency_key"].startswith(HANDOFF_IDEMPOTENCY_PREFIX)
            or not isinstance(detail, dict) or set(detail) != {"handoff", "close_receipt"}):
        raise OperatorProcessFenceHold("reserved handoff row is malformed")
    handoff = validate_process_fence_handoff(detail["handoff"], close_receipt=detail["close_receipt"])
    key = HANDOFF_IDEMPOTENCY_PREFIX + handoff["operation_id"]
    operator = handoff["operator"]
    if (row.get("audit_id") != _expected_audit_id("ops_acp_process_fence_handoff_", key)
            or row.get("idempotency_key") != key or row.get("resource_type") != "workspace"
            or row.get("resource_id") != handoff["scope"]["workspace_id"]
            or row.get("outcome") != "pending" or row.get("request_sha256") != digest(detail)
            or row.get("actor_principal") != f"engineering:{operator['name']}:{operator['uid']}"
            or row.get("response_json") != handoff):
        raise OperatorProcessFenceHold("reserved handoff row identity is inconsistent")
    return handoff


def _validate_reserved_handoff_ack_row(row: dict[str, Any]) -> dict[str, Any]:
    detail = row.get("detail_json")
    if (row.get("action") != HANDOFF_ACK_ACTION or not isinstance(row.get("idempotency_key"), str)
            or not row["idempotency_key"].startswith(HANDOFF_ACK_IDEMPOTENCY_PREFIX)
            or not isinstance(detail, dict) or set(detail) != {"handoff", "runtime_observation"}):
        raise OperatorProcessFenceHold("reserved handoff ACK row is malformed")
    handoff = validate_process_fence_handoff(detail["handoff"])
    observation = validate_process_fence_handoff_observation(detail["runtime_observation"], handoff=handoff)
    confirmation = validate_process_fence_handoff_confirmation(row.get("response_json"), handoff=handoff)
    key = HANDOFF_ACK_IDEMPOTENCY_PREFIX + handoff["operation_id"]
    operator = confirmation["operator"]
    if (row.get("audit_id") != _expected_audit_id("ops_acp_process_fence_handoff_ack_", key)
            or row.get("idempotency_key") != key or row.get("resource_type") != "workspace"
            or row.get("resource_id") != handoff["scope"]["workspace_id"]
            or row.get("outcome") != "confirmed" or row.get("request_sha256") != digest(detail)
            or row.get("actor_principal") != f"engineering:{operator['name']}:{operator['uid']}"
            or confirmation.get("runtime_observation") != observation):
        raise OperatorProcessFenceHold("reserved handoff ACK row identity is inconsistent")
    return confirmation


def require_workspace_process_fence_ack(connection: Any, workspace_id: str) -> None:
    """Hold reset until every exact R2 proof for this Workspace has an ACK pair.

    The reserved namespace is scanned as a whole so a malformed row cannot
    evade a workspace-scoped filter by changing its resource binding. Any
    malformed global row is fail-closed until Engineering repairs the exact
    control record; valid records for other Workspaces do not block this one.
    """
    rows = execute(connection, """SELECT audit_id,actor_principal,action,resource_type,
            resource_id,outcome,idempotency_key,request_sha256,detail_json,response_json
        FROM operations_audit
        WHERE action IN (:proof_action,:ack_action,:handoff_action,:handoff_ack_action)
           OR idempotency_key LIKE :proof_prefix
           OR idempotency_key LIKE :ack_prefix
           OR idempotency_key LIKE :handoff_prefix
           OR idempotency_key LIKE :handoff_ack_prefix
        ORDER BY created_at,audit_id LIMIT :row_limit FOR SHARE""",
        {"proof_action": PROCESS_FENCE_ACTION, "ack_action": ACK_ACTION,
         "handoff_action": HANDOFF_ACTION, "handoff_ack_action": HANDOFF_ACK_ACTION,
         "proof_prefix": PROCESS_FENCE_IDEMPOTENCY_PREFIX + "%",
         "ack_prefix": ACK_IDEMPOTENCY_PREFIX + "%",
         "handoff_prefix": HANDOFF_IDEMPOTENCY_PREFIX + "%",
         "handoff_ack_prefix": HANDOFF_ACK_IDEMPOTENCY_PREFIX + "%",
         "row_limit": MAX_RESERVED_ROWS + 1})
    if len(rows) > MAX_RESERVED_ROWS:
        raise OperatorProcessFenceHold("reserved process-fence namespace exceeds its bound")
    proofs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    acknowledgements: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    handoffs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    handoff_acks: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row in rows:
        key = row.get("idempotency_key")
        action = row.get("action")
        if action == HANDOFF_ACTION or (isinstance(key, str) and key.startswith(HANDOFF_IDEMPOTENCY_PREFIX)):
            handoff = _validate_reserved_handoff_row(row)
            operation_id = handoff["operation_id"]
            if operation_id in handoffs:
                raise OperatorProcessFenceHold("duplicate handoff identity")
            handoffs[operation_id] = (handoff, row)
        elif action == HANDOFF_ACK_ACTION or (isinstance(key, str) and key.startswith(HANDOFF_ACK_IDEMPOTENCY_PREFIX)):
            ack = _validate_reserved_handoff_ack_row(row)
            operation_id = ack["operation_id"]
            if operation_id in handoff_acks:
                raise OperatorProcessFenceHold("duplicate handoff ACK identity")
            handoff_acks[operation_id] = (ack, row)
        elif action == PROCESS_FENCE_ACTION or (isinstance(key, str) and key.startswith(PROCESS_FENCE_IDEMPOTENCY_PREFIX)):
            proof = _validate_reserved_proof_row(row)
            operation_id = proof["operation_id"]
            if operation_id in proofs:
                raise OperatorProcessFenceHold("duplicate process-fence proof identity")
            proofs[operation_id] = (proof, row)
        elif action == ACK_ACTION or (isinstance(key, str) and key.startswith(ACK_IDEMPOTENCY_PREFIX)):
            ack = _validate_reserved_ack_row(row)
            operation_id = ack["operation_id"]
            if operation_id in acknowledgements:
                raise OperatorProcessFenceHold("duplicate process-fence ACK identity")
            acknowledgements[operation_id] = (ack, row)
        else:
            raise OperatorProcessFenceHold("reserved process-fence namespace has a conflicting row")
    for operation_id, (ack, _row) in acknowledgements.items():
        proof_record = proofs.get(operation_id)
        if proof_record is None:
            raise OperatorProcessFenceHold("process-fence ACK has no exact proof")
        proof, proof_row = proof_record
        fact_digest_key = ("operator_failed_terminal_receipt_sha256"
                           if "operator_failed_terminal" in proof
                           else "operator_completed_cleanup_receipt_sha256"
                           if "operator_completed_cleanup" in proof
                           else "operator_interruption_receipt_sha256")
        if (ack.get("proof_audit_id") != proof_row["audit_id"]
                or ack.get("proof_receipt_sha256") != proof["receipt_sha256"]
                or ack.get(fact_digest_key)
                != proof["operator_failed_terminal" if "operator_failed_terminal" in proof else
                         "operator_completed_cleanup" if "operator_completed_cleanup" in proof
                         else "operator_interruption"]["receipt_sha256"]
                or ack.get("root_binding_sha256") != proof["runtime_binding_sha256"]
                or ack.get("terminal_ack_sha256") != digest(proof_row["response_json"])
                or ack.get("scope") != proof["scope"]
                or ack.get("authority") != proof["authority"]
                or ack.get("runner") != {
                    "old_runner_instance_id": proof["old_runner"]["runner_instance_id"],
                    "successor_runner_instance_id": proof["successor"]["runner_instance_id"],
                    "tombstone_sha256": proof["successor"]["tombstone_sha256"],
                }
                or ("operator_failed_terminal" in proof
                    and ack.get("superseded_terminal") is not None)
                or (ack.get("superseded_terminal") is not None
                    and ack["superseded_terminal"].get("root_run_id") != proof["scope"]["root_run_id"])):
            raise OperatorProcessFenceHold("process-fence ACK does not bind the exact proof")
    for operation_id, (handoff, handoff_row) in handoffs.items():
        proof_record = proofs.get(operation_id)
        if proof_record is None:
            raise OperatorProcessFenceHold("handoff has no exact proof")
        proof, proof_row = proof_record
        if (handoff.get("proof_receipt_sha256") != proof.get("receipt_sha256")
                or handoff.get("original_request_sha256") != proof.get("request_sha256")
                or handoff_row.get("resource_id") != proof_row.get("resource_id")
                or handoff.get("close_receipt_sha256") != digest(proof_row.get("response_json"))):
            raise OperatorProcessFenceHold("handoff differs from its exact proof")
        ack_record = handoff_acks.get(operation_id)
        if proof["scope"]["workspace_id"] == workspace_id and ack_record is None:
            raise OperatorProcessFenceHold("Workspace has a pending cleanup handoff")
        if ack_record is not None:
            ack, _row = ack_record
            if (ack.get("handoff_sha256") != handoff.get("handoff_sha256")
                    or ack.get("proof_receipt_sha256") != handoff.get("proof_receipt_sha256")
                    or ack.get("close_receipt_sha256") != handoff.get("close_receipt_sha256")):
                raise OperatorProcessFenceHold("handoff ACK differs from its exact handoff")
    if set(handoff_acks) - set(handoffs):
        raise OperatorProcessFenceHold("handoff ACK has no protected handoff")
    for proof, _row in proofs.values():
        if (proof["scope"]["workspace_id"] == workspace_id
                and proof["operation_id"] not in acknowledgements
                and proof["operation_id"] not in handoff_acks):
            raise OperatorProcessFenceHold("operator process-fence proof lacks exact durable ACK and slot release")


class _ExistingSchemaAgentResearchStore:
    """Construct the existing AgentResearchStore without running DDL."""

    def __new__(cls, *args, **kwargs):
        from .agent_research import AgentResearchStore

        class Store(AgentResearchStore):
            def bootstrap_schema(self) -> None:
                return None

        return Store(*args, **kwargs)


def _runtime_operator_observation(close_receipt: dict[str, Any]) -> dict[str, Any]:
    """Read one actual Runtime response; never retry an uncertain route call."""
    base_url = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400").rstrip("/")
    token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    parts = urlsplit(base_url)
    if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.path not in {"", "/"}
            or parts.query or parts.fragment or not token):
        raise OperatorProcessFenceHold("Runtime private route configuration is unavailable")
    path = "/internal/runtime/sessions/" + quote(close_receipt["scope"]["session_id"], safe="")
    target_url = base_url + path + "/terminal-receipt"
    raw = bytearray()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", target_url,
                    content=canonical_json({"receipt": close_receipt}),
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json", "Accept": "application/json"}) as response:
                if not 200 <= response.status_code < 300:
                    raise OperatorProcessFenceHold("Runtime process-fence acknowledgement was not confirmed")
                if response.url != httpx.URL(target_url):
                    raise OperatorProcessFenceHold("Runtime process-fence response changed its exact URL")
                for block in response.iter_bytes():
                    raw.extend(block)
                    if len(raw) > 128 * 1024:
                        raise OperatorProcessFenceHold("Runtime process-fence observation exceeds its bound")
    except OperatorProcessFenceHold:
        raise
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        # An uncertain response is never retried here; exact Runtime readback
        # and the same close receipt are required before another invocation.
        raise OperatorProcessFenceHold("Runtime process-fence acknowledgement is uncertain") from exc
    try:
        body = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_strict_object,
                          parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise OperatorProcessFenceHold("Runtime process-fence observation is invalid") from exc
    if not isinstance(body, dict) or set(body) != {"operator_observation"}:
        raise OperatorProcessFenceHold("Runtime response is not the closed operator observation")
    try:
        return validate_operator_observation(body["operator_observation"], close_receipt=close_receipt)
    except Exception as exc:
        raise OperatorProcessFenceHold("Runtime operator observation does not match the close receipt") from exc


def _runtime_local_validation_ack(final_receipt: dict[str, Any]) -> dict[str, Any]:
    request = validate_local_validation_ack_request({
        "schema_version": LOCAL_VALIDATION_ACK_REQUEST_SCHEMA,
        "final_receipt": final_receipt,
    })
    base_url = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400").rstrip("/")
    token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    parts = urlsplit(base_url)
    if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.path not in {"", "/"} or parts.query or parts.fragment or not token):
        raise OperatorProcessFenceHold("Runtime private route configuration is unavailable")
    target_url = (base_url + "/internal/runtime/sessions/"
                  + quote(request["final_receipt"]["scope"]["session_id"], safe="")
                  + "/terminal-receipt")
    raw = bytearray()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", target_url,
                    content=canonical_json({"receipt": request}),
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json", "Accept": "application/json"}) as response:
                if not 200 <= response.status_code < 300 or response.url != httpx.URL(target_url):
                    raise OperatorProcessFenceHold("Runtime local validation ACK was not confirmed")
                for block in response.iter_bytes():
                    raw.extend(block)
                    if len(raw) > 128 * 1024:
                        raise OperatorProcessFenceHold("Runtime local validation ACK exceeds its bound")
    except OperatorProcessFenceHold:
        raise
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise OperatorProcessFenceHold("Runtime local validation ACK is uncertain") from exc
    try:
        body = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_strict_object,
                          parse_constant=_reject_constant)
        if not isinstance(body, dict) or set(body) != {"runtime_observation"}:
            raise ValueError("Runtime response shape is invalid")
        observation = validate_local_validation_release_observation(body["runtime_observation"])
    except Exception as exc:
        raise OperatorProcessFenceHold("Runtime local validation observation is invalid") from exc
    if observation["ack_intent"]["final_receipt"] != request["final_receipt"]:
        raise OperatorProcessFenceHold("Runtime local validation observation changed its final receipt")
    return observation


def _runtime_local_validation_handoff_ack(
    final_receipt: dict[str, Any], handoff: dict[str, Any],
) -> dict[str, Any]:
    request = validate_local_validation_handoff_request({
        "schema_version": LOCAL_VALIDATION_HANDOFF_REQUEST_SCHEMA,
        "final_receipt": final_receipt, "handoff": handoff,
    })
    base_url = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400").rstrip("/")
    token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    parts = urlsplit(base_url)
    if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.path not in {"", "/"} or parts.query or parts.fragment or not token):
        raise OperatorProcessFenceHold("Runtime private route configuration is unavailable")
    target_url = (base_url + "/internal/runtime/sessions/"
                  + quote(final_receipt["scope"]["session_id"], safe="") + "/terminal-receipt")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            reserved = client.post(target_url, content=canonical_json({"reserve_request": request}), headers=headers)
            if (not 200 <= reserved.status_code < 300 or reserved.url != httpx.URL(target_url)):
                raise OperatorProcessFenceHold("Runtime confirmation lease was not reserved")
            reserved_body = reserved.json()
            if (not isinstance(reserved_body, dict) or set(reserved_body) != {"state", "operation_id"}
                    or reserved_body.get("state") not in {"reserved", "observed"}
                    or reserved_body.get("operation_id") != handoff["operation_id"]):
                raise OperatorProcessFenceHold("Runtime confirmation lease response changed")
            response = client.post(target_url, content=canonical_json({"receipt": request}), headers=headers)
            if not 200 <= response.status_code < 300 or response.url != httpx.URL(target_url):
                raise OperatorProcessFenceHold("Runtime confirmation release was not confirmed")
            raw = response.content
            if len(raw) > 128 * 1024:
                raise OperatorProcessFenceHold("Runtime handoff observation exceeds its bound")
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object,
                              parse_constant=_reject_constant)
            if not isinstance(body, dict) or set(body) != {"runtime_handoff_observation"}:
                raise ValueError("Runtime handoff response shape changed")
            observation = validate_local_validation_handoff_observation(body["runtime_handoff_observation"])
    except OperatorProcessFenceHold:
        raise
    except (httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError, UnicodeError) as exc:
        raise OperatorProcessFenceHold("Runtime confirmation result is uncertain") from exc
    if (observation["ack_intent"]["final_receipt"] != final_receipt
            or observation["ack_intent"]["handoff"] != handoff):
        raise OperatorProcessFenceHold("Runtime confirmation observation changed")
    return observation


def _runtime_local_validation_projection(request: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400").rstrip("/")
    token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    parts = urlsplit(base_url)
    if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.path not in {"", "/"} or parts.query or parts.fragment or not token):
        raise OperatorProcessFenceHold("Runtime private route configuration is unavailable")
    path = ("/internal/runtime/sessions/" + quote(request["session_id"], safe="")
            + "/terminal-evidence?root_run_id=" + quote(request["root_run_id"], safe="")
            + "&boot_id=" + quote(request["boot_id"], safe="")
            + "&projection=local-validation-v1")
    target_url = base_url + path
    raw = bytearray()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", target_url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}) as response:
                if not 200 <= response.status_code < 300 or response.url != httpx.URL(target_url):
                    raise OperatorProcessFenceHold("Runtime local terminal projection is unavailable")
                for block in response.iter_bytes():
                    raw.extend(block)
                    if len(raw) > 128 * 1024:
                        raise OperatorProcessFenceHold("Runtime local terminal projection exceeds its bound")
    except OperatorProcessFenceHold:
        raise
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise OperatorProcessFenceHold("Runtime local terminal projection is uncertain") from exc
    try:
        value = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_strict_object,
                           parse_constant=_reject_constant)
        return validate_local_validation_projection(value, request=request)
    except Exception as exc:
        raise OperatorProcessFenceHold("Runtime local terminal projection is malformed") from exc


def _reserve_runtime_operator_fence(raw_request: object) -> None:
    """Reserve the current Runtime slot before Backend's locked close."""
    cleanup = (validate_completed_cleanup_request(raw_request)
               if isinstance(raw_request, dict)
               and raw_request.get("schema_version") == COMPLETED_CLEANUP_REQUEST_SCHEMA else None)
    request = (cleanup["process_fence_request"] if cleanup is not None
               else validate_process_fence_request(raw_request))
    base_url = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400").rstrip("/")
    token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    parts = urlsplit(base_url)
    if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.path not in {"", "/"} or parts.query or parts.fragment or not token):
        raise OperatorProcessFenceHold("Runtime private route configuration is unavailable")
    path = "/internal/runtime/sessions/" + quote(request["scope"]["session_id"], safe="")
    target_url = base_url + path + "/terminal-receipt"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            response = client.post(target_url,
                content=canonical_json({"reserve_request": cleanup if cleanup is not None else request}),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                         "Accept": "application/json"})
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise OperatorProcessFenceHold("Runtime slot reservation is uncertain") from exc
    if not 200 <= response.status_code < 300 or response.url != httpx.URL(target_url):
        raise OperatorProcessFenceHold("Runtime slot reservation was not confirmed")
    try:
        body = response.json()
    except (ValueError, TypeError) as exc:
        raise OperatorProcessFenceHold("Runtime slot reservation response is invalid") from exc
    if (not isinstance(body, dict) or set(body) != {"state", "operation_id"}
            or body["state"] not in {"reserved", "observed"}
            or body["operation_id"] != request["operation_id"]):
        raise OperatorProcessFenceHold("Runtime slot reservation response changed")


def _runtime_handoff_observation(request: dict[str, Any]) -> dict[str, Any]:
    request = validate_process_fence_handoff_request(request)
    handoff = request["handoff"]
    base_url = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400").rstrip("/")
    token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    parts = urlsplit(base_url)
    if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.path not in {"", "/"} or parts.query or parts.fragment or not token):
        raise OperatorProcessFenceHold("Runtime private route configuration is unavailable")
    target_url = (base_url + "/internal/runtime/sessions/"
                  + quote(handoff["scope"]["session_id"], safe="") + "/terminal-receipt")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            reserve = client.post(target_url, content=canonical_json({"reserve_request": request}), headers=headers)
            if not 200 <= reserve.status_code < 300 or reserve.url != httpx.URL(target_url):
                raise OperatorProcessFenceHold("Runtime handoff reservation was not confirmed")
            reserved = reserve.json()
            if (not isinstance(reserved, dict) or set(reserved) != {"state", "operation_id"}
                    or reserved.get("state") not in {"reserved", "observed"}
                    or reserved.get("operation_id") != handoff["operation_id"]):
                raise OperatorProcessFenceHold("Runtime handoff reservation response changed")
            ack = client.post(target_url, content=canonical_json({"receipt": request}), headers=headers)
            if not 200 <= ack.status_code < 300 or ack.url != httpx.URL(target_url):
                raise OperatorProcessFenceHold("Runtime handoff observation was not confirmed")
            body = ack.json()
    except OperatorProcessFenceHold:
        raise
    except (httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError) as exc:
        raise OperatorProcessFenceHold("Runtime handoff result is uncertain") from exc
    if not isinstance(body, dict) or set(body) != {"operator_handoff_observation"}:
        raise OperatorProcessFenceHold("Runtime response is not the closed handoff observation")
    try:
        return validate_process_fence_handoff_observation(body["operator_handoff_observation"], handoff=handoff)
    except Exception as exc:
        raise OperatorProcessFenceHold("Runtime observation differs from the exact handoff") from exc


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(canonical_json(value))
    sys.stdout.buffer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    close = commands.add_parser("close")
    close.add_argument("--request-file", required=True)
    close.add_argument("--control-fd", type=int)
    ack = commands.add_parser("confirm-ack")
    ack.add_argument("--close-receipt-file", required=True)
    ack.add_argument("--control-fd", type=int)
    args = parser.parse_args(argv)
    store = None
    try:
        operator = _engineering_operator()
        store = _ExistingSchemaAgentResearchStore()
        if args.command == "close":
            request = _read_private_json(args.request_file)
            if request.get("schema_version") == COMPLETED_CLEANUP_REQUEST_SCHEMA:
                cleanup = validate_completed_cleanup_request(request)
                _reserve_runtime_operator_fence(cleanup)
                result = store.close_runtime_root_by_operator_process_fence(
                    request=cleanup["process_fence_request"], operator_uid=operator["uid"],
                    operator_name=operator["name"], completed_cleanup=cleanup,
                )
                _emit(result)
                return 0
            if request.get("schema_version") == LOCAL_VALIDATION_PRE_ACK_SCHEMA:
                if args.control_fd is None:
                    raise OperatorProcessFenceHold("local validation pre-ACK stop requires a private control FD")
                pre_ack = validate_local_validation_pre_ack_request(request)
                from .historical_audit_reconciliation import _read_control_key
                control_key = _read_control_key(args.control_fd)
                pinned = os.environ.get("BYQ_ACP_PRODUCT_CONTROL_KEY_SHA256", "")
                if (not pinned or not hmac.compare_digest(hashlib.sha256(control_key).hexdigest(), pinned)):
                    raise OperatorProcessFenceHold("Product control key does not match the Backend trust anchor")
                reservation = store.prepare_local_validation_reconciliation(pre_ack["root_run_id"])
                scope = reservation.get("scope")
                if (not isinstance(scope, dict)
                        or reservation.get("root_run_id") != pre_ack["root_run_id"]
                        or reservation.get("authority_boot_id") != pre_ack["boot_id"]
                        or scope.get("session_id") != pre_ack["session_id"]
                        or scope.get("actor_principal") != "byq-product-agent-" + pre_ack["session_id"]):
                    raise OperatorProcessFenceHold("local validation reservation differs from exact pre-ACK request")
                roots = store.runtime_roots_for_scope(
                    owner_principal=scope["owner_principal"], workspace_id=scope["workspace_id"],
                    session_id=scope["session_id"], trace_id=scope["trace_id"])
                matches = [row for row in roots.get("roots", []) if isinstance(row, dict)
                           and row.get("root_run_id") == pre_ack["root_run_id"]]
                if len(matches) != 1:
                    raise OperatorProcessFenceHold("local validation Root readback is not unique")
                existing = matches[0].get("local_validation")
                if existing is not None:
                    if (not isinstance(existing, dict)
                            or set(existing) != {"final_receipt", "runtime_observation", "confirmation_receipt"}
                            or existing.get("final_receipt") is None):
                        raise OperatorProcessFenceHold("local validation finalized Root projection is malformed")
                    try:
                        prior_final = validate_local_validation_final_receipt(existing["final_receipt"])
                    except (TypeError, ValueError) as exc:
                        raise OperatorProcessFenceHold("local validation finalized receipt is malformed") from exc
                    final_scope = prior_final["scope"]
                    if (matches[0].get("authority_status") != "closed"
                            or matches[0].get("status") not in {"completed", "failed", "cancelled", "interrupted"}
                            or prior_final["root_run_id"] != pre_ack["root_run_id"]
                            or prior_final["reservation_sha256"] != reservation["reservation_sha256"]
                            or prior_final["claim_id"] != reservation["claim_id"]
                            or prior_final["task_id"] != reservation["task_id"]
                            or prior_final["operator_uid"] != operator["uid"]
                            or prior_final["operator_name"] != operator["name"]
                            or final_scope["session_id"] != pre_ack["session_id"]
                            or final_scope["runtime_boot_id"] != pre_ack["boot_id"]
                            or final_scope["owner_principal"] != scope["owner_principal"]
                            or final_scope["workspace_id"] != scope["workspace_id"]
                            or final_scope["trace_id"] != scope["trace_id"]
                            or final_scope["generation_id"] != scope["generation"]):
                        raise OperatorProcessFenceHold("local validation finalized receipt differs from exact retry")
                    _emit(prior_final)
                    return 0
                base_url = os.environ.get("BYQ_RUNTIME_ADAPTER_URL", "http://runtime-adapter:8400").rstrip("/")
                token = os.environ.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
                parts = urlsplit(base_url)
                if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
                        or parts.path not in {"", "/"} or parts.query or parts.fragment or not token):
                    raise OperatorProcessFenceHold("Runtime private route configuration is unavailable")
                target_url = (base_url + "/internal/runtime/sessions/"
                              + quote(pre_ack["session_id"], safe="") + "/terminal-receipt")
                raw = bytearray()
                try:
                    with httpx.Client(timeout=75.0, follow_redirects=False, trust_env=False) as client:
                        with client.stream("POST", target_url,
                                content=canonical_json({"receipt": pre_ack}),
                                headers={"Authorization": f"Bearer {token}",
                                         "Content-Type": "application/json", "Accept": "application/json"}) as response:
                            if not 200 <= response.status_code < 300 or response.url != httpx.URL(target_url):
                                raise OperatorProcessFenceHold("Runtime pre-ACK cleanup was not confirmed")
                            for block in response.iter_bytes():
                                raw.extend(block)
                                if len(raw) > 64 * 1024:
                                    raise OperatorProcessFenceHold("Runtime pre-ACK cleanup response exceeds its bound")
                except OperatorProcessFenceHold:
                    raise
                except (httpx.HTTPError, TimeoutError, OSError) as exc:
                    raise OperatorProcessFenceHold("Runtime pre-ACK cleanup result is uncertain") from exc
                try:
                    stop_result = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_strict_object,
                                             parse_constant=_reject_constant)
                    fields = {"schema_version", "root_run_id", "cleanup_receipt_raw_b64",
                              "cleanup_receipt_sha256", "runtime_binding_sha256"}
                    raw_cleanup = base64.b64decode(stop_result["cleanup_receipt_raw_b64"].encode("ascii"),
                                                   validate=True)
                    if (not isinstance(stop_result, dict) or set(stop_result) != fields
                            or stop_result.get("schema_version") != "byq-local-validation-pre-ack-stop-result.v1"
                            or stop_result.get("root_run_id") != pre_ack["root_run_id"]
                            or not raw_cleanup or base64.b64encode(raw_cleanup).decode("ascii")
                               != stop_result["cleanup_receipt_raw_b64"]
                            or hashlib.sha256(raw_cleanup).hexdigest() != stop_result["cleanup_receipt_sha256"]
                            or len(raw_cleanup) > 12_288
                            or not isinstance(stop_result.get("runtime_binding_sha256"), str)
                            or re.fullmatch(r"[0-9a-f]{64}", stop_result["runtime_binding_sha256"]) is None):
                        raise ValueError("Runtime stop result changed")
                except Exception as exc:
                    raise OperatorProcessFenceHold("Runtime pre-ACK cleanup result is malformed") from exc
                close_request = validate_local_validation_close_request({
                    "schema_version": "byq-local-validation-close-request.v1",
                    "root_run_id": pre_ack["root_run_id"], "session_id": pre_ack["session_id"],
                    "boot_id": pre_ack["boot_id"],
                    "cleanup_receipt_raw_b64": stop_result["cleanup_receipt_raw_b64"],
                })
                projection = _runtime_local_validation_projection(close_request)
                if projection["binding_sha256"] != stop_result["runtime_binding_sha256"]:
                    raise OperatorProcessFenceHold("Runtime stopped binding changed before finalization")
                result = store.finalize_local_validation_reconciliation(
                    request=close_request, runtime_projection=projection, product_control_key=control_key,
                    operator_uid=operator["uid"], operator_name=operator["name"],
                )
                _emit(result)
                return 0
            if request.get("schema_version") == "byq-local-validation-close-request.v1":
                if args.control_fd is None:
                    raise OperatorProcessFenceHold("local validation close requires a private control FD")
                request = validate_local_validation_close_request(request)
                projection = _runtime_local_validation_projection(request)
                from .historical_audit_reconciliation import _read_control_key
                result = store.finalize_local_validation_reconciliation(
                    request=request, runtime_projection=projection,
                    product_control_key=_read_control_key(args.control_fd),
                    operator_uid=operator["uid"], operator_name=operator["name"],
                )
                _emit(result)
                return 0
            if args.control_fd is not None:
                raise OperatorProcessFenceHold("control FD is only valid for local validation close")
            _reserve_runtime_operator_fence(request)
            result = store.close_runtime_root_by_operator_process_fence(
                request=request, operator_uid=operator["uid"], operator_name=operator["name"],
            )
        else:
            ack_receipt = _read_private_json(args.close_receipt_file)
            if ack_receipt.get("schema_version") == LOCAL_VALIDATION_HANDOFF_INPUT_SCHEMA:
                if args.control_fd is None:
                    raise OperatorProcessFenceHold("local validation handoff requires a private control FD")
                handoff_input = validate_local_validation_handoff_input(ack_receipt)
                from .historical_audit_reconciliation import _read_control_key
                control_key = _read_control_key(args.control_fd)
                pinned = os.environ.get("BYQ_ACP_PRODUCT_CONTROL_KEY_SHA256", "")
                if not pinned or not hmac.compare_digest(hashlib.sha256(control_key).hexdigest(), pinned):
                    raise OperatorProcessFenceHold("Product control key does not match the Backend trust anchor")
                handoff = store.prepare_local_validation_confirmation_handoff(
                    final_receipt=handoff_input["final_receipt"],
                    stopped_runtime_evidence=handoff_input["stopped_runtime_evidence"],
                    confirmation_baseline=handoff_input["confirmation_baseline"],
                    predecessor_runtime_stopped_evidence=handoff_input.get(
                        "predecessor_runtime_stopped_evidence"),
                    operator_uid=operator["uid"], operator_name=operator["name"],
                )
                observation = _runtime_local_validation_handoff_ack(handoff_input["final_receipt"], handoff)
                result = store.confirm_local_validation_handoff(
                    final_receipt=handoff_input["final_receipt"], handoff=handoff,
                    runtime_observation=observation, operator_uid=operator["uid"],
                    operator_name=operator["name"],
                )
            elif ack_receipt.get("schema_version") == PROCESS_FENCE_HANDOFF_REQUEST_SCHEMA:
                if args.control_fd is not None:
                    raise OperatorProcessFenceHold("control FD is only valid for local validation handoff")
                request = validate_process_fence_handoff_request(ack_receipt)
                handoff = store.persist_operator_process_fence_handoff(
                    close_receipt=request["close_receipt"], handoff=request["handoff"],
                    operator_uid=operator["uid"], operator_name=operator["name"],
                )
                observation = _runtime_handoff_observation(request)
                result = store.confirm_operator_process_fence_handoff(
                    close_receipt=request["close_receipt"], handoff=handoff,
                    runtime_observation=observation,
                    operator_uid=operator["uid"], operator_name=operator["name"],
                )
            elif ack_receipt.get("schema_version") == "byq-local-validation-final-terminal.v1":
                if args.control_fd is not None:
                    raise OperatorProcessFenceHold("control FD is only valid for local validation handoff")
                final = validate_local_validation_final_receipt(ack_receipt)
                observation = _runtime_local_validation_ack(final)
                result = store.confirm_local_validation_ack(
                    final_receipt=final, runtime_observation=observation,
                    operator_uid=operator["uid"], operator_name=operator["name"],
                )
            else:
                if args.control_fd is not None:
                    raise OperatorProcessFenceHold("control FD is only valid for local validation handoff")
                close_receipt = validate_fence_close_receipt(ack_receipt)
                observation = _runtime_operator_observation(close_receipt)
                result = store.confirm_operator_process_fence_ack(
                    close_receipt=close_receipt, runtime_observation=observation,
                    operator_uid=operator["uid"], operator_name=operator["name"],
                )
        _emit(result)
        return 0
    except Exception as exc:
        # Do not leak filesystem paths, native output, SQL, or input values.
        name = type(exc).__name__
        if not name.isascii() or not name.isidentifier():
            name = "Exception"
        sys.stderr.write(f"HOLD {name}\n")
        sys.stderr.flush()
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
