"""Private Engineering CLI and reset guard for ADR-0104 operator fences.

This module is not mounted as an HTTP or MCP route. Native evidence is supplied
only by a restricted local Engineering invocation and is stored in the
reserved global operations-audit namespace.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from packages.contracts.acp_operator_process_fence import (
    ACK_ACTION,
    ACK_IDEMPOTENCY_PREFIX,
    PROCESS_FENCE_ACTION,
    PROCESS_FENCE_IDEMPOTENCY_PREFIX,
    canonical_json,
    digest,
    validate_ack_receipt,
    validate_fence_close_receipt,
    validate_operator_observation,
    validate_process_fence_proof,
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
    if (response.get("operation_id") != proof["operation_id"]
            or response.get("workspace_id") != proof["scope"]["workspace_id"]
            or response.get("root_run_id") != proof["scope"]["root_run_id"]
            or response.get("process_fence_receipt_sha256") != proof["process_fence_receipt_sha256"]
            or response.get("operator_interruption") != proof["operator_interruption"]
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
            or ack.get("operator_interruption_receipt_sha256")
                != runtime_ack["operator_interruption_receipt_sha256"]
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
        WHERE action IN (:proof_action,:ack_action)
           OR idempotency_key LIKE :proof_prefix
           OR idempotency_key LIKE :ack_prefix
        ORDER BY created_at,audit_id LIMIT :row_limit FOR SHARE""",
        {"proof_action": PROCESS_FENCE_ACTION, "ack_action": ACK_ACTION,
         "proof_prefix": PROCESS_FENCE_IDEMPOTENCY_PREFIX + "%",
         "ack_prefix": ACK_IDEMPOTENCY_PREFIX + "%", "row_limit": MAX_RESERVED_ROWS + 1})
    if len(rows) > MAX_RESERVED_ROWS:
        raise OperatorProcessFenceHold("reserved process-fence namespace exceeds its bound")
    proofs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    acknowledgements: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row in rows:
        key = row.get("idempotency_key")
        action = row.get("action")
        if action == PROCESS_FENCE_ACTION or (isinstance(key, str) and key.startswith(PROCESS_FENCE_IDEMPOTENCY_PREFIX)):
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
        if (ack.get("proof_audit_id") != proof_row["audit_id"]
                or ack.get("proof_receipt_sha256") != proof["receipt_sha256"]
                or ack.get("operator_interruption_receipt_sha256")
                != proof["operator_interruption"]["receipt_sha256"]
                or ack.get("root_binding_sha256") != proof["runtime_binding_sha256"]
                or ack.get("terminal_ack_sha256") != digest(proof_row["response_json"])
                or ack.get("scope") != proof["scope"]
                or ack.get("authority") != proof["authority"]
                or ack.get("runner") != {
                    "old_runner_instance_id": proof["old_runner"]["runner_instance_id"],
                    "successor_runner_instance_id": proof["successor"]["runner_instance_id"],
                    "tombstone_sha256": proof["successor"]["tombstone_sha256"],
                }
                or (ack.get("superseded_terminal") is not None
                    and ack["superseded_terminal"].get("root_run_id") != proof["scope"]["root_run_id"])):
            raise OperatorProcessFenceHold("process-fence ACK does not bind the exact proof")
    for proof, _row in proofs.values():
        if proof["scope"]["workspace_id"] == workspace_id and proof["operation_id"] not in acknowledgements:
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


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(canonical_json(value))
    sys.stdout.buffer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    close = commands.add_parser("close")
    close.add_argument("--request-file", required=True)
    ack = commands.add_parser("confirm-ack")
    ack.add_argument("--close-receipt-file", required=True)
    args = parser.parse_args(argv)
    store = None
    try:
        operator = _engineering_operator()
        store = _ExistingSchemaAgentResearchStore()
        if args.command == "close":
            request = _read_private_json(args.request_file)
            result = store.close_runtime_root_by_operator_process_fence(
                request=request, operator_uid=operator["uid"], operator_name=operator["name"],
            )
        else:
            close_receipt = _read_private_json(args.close_receipt_file)
            close_receipt = validate_fence_close_receipt(close_receipt)
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
