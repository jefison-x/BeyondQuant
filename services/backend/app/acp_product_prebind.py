"""Private one-shot Engineering preparation/activation of ACP runner prebind.

Prepared is non-authorizing. Activation records an Engineering-collected
actual-facts anchor; it does not by itself authorize Product START. This
module is not imported by the Backend HTTP application.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pwd
import re
import stat
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

from packages.contracts.acp_product_instance import (
    ProductInstanceContractError, canonical_json as product_canonical_json,
    validate_instance,
)
from packages.contracts.acp_product_prebind import (
    ACTIVATE_ACTION, ACTIVATE_IDEMPOTENCY_PREFIX,
    PREPARE_ACTION, PREPARE_IDEMPOTENCY_PREFIX, PREPARE_SCHEMA,
    BACKEND_ACTIVE_SCHEMA, canonical_json, digest, validate_activation_request,
    validate_backend_active_receipt, validate_prepare_request, validate_prepared_receipt,
)
from sqlalchemy.exc import SQLAlchemyError

from .db import execute, fetch_one
from .operations import OperationsPersistenceError, OperationsStore

_MAX_INPUT_BYTES = 1_048_576
_MAX_CONTROL_KEY_BYTES = 512
_MIN_CONTROL_KEY_BYTES = 32


class PrebindHold(RuntimeError):
    """The private prebind operation cannot proceed safely."""


class _ExistingSchemaOperationsStore(OperationsStore):
    """Use existing operations tables without running any DDL/bootstrap."""

    def bootstrap_schema(self) -> None:
        return None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PrebindHold("duplicate JSON field")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise PrebindHold("non-finite JSON number")


def _read_regular_json(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    try:
        before = os.lstat(path)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > _MAX_INPUT_BYTES):
            raise PrebindHold("input is not a bounded regular file")
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_size > _MAX_INPUT_BYTES):
                raise PrebindHold("input changed while opening")
            raw = bytearray()
            while len(raw) <= _MAX_INPUT_BYTES:
                block = os.read(descriptor, min(65_536, _MAX_INPUT_BYTES + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            after = os.fstat(descriptor)
            if (len(raw) > _MAX_INPUT_BYTES or len(raw) != after.st_size
                    or (opened.st_dev, opened.st_ino, opened.st_size,
                        opened.st_mtime_ns, opened.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns)):
                raise PrebindHold("input changed while reading")
        finally:
            os.close(descriptor)
    except PrebindHold:
        raise
    except (OSError, ValueError) as exc:
        raise PrebindHold("input file is unavailable") from exc
    try:
        value = json.loads(bytes(raw).decode("utf-8"),
                           object_pairs_hook=_strict_object,
                           parse_constant=_reject_constant)
    except PrebindHold:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise PrebindHold("input JSON is invalid") from exc
    if not isinstance(value, dict):
        raise PrebindHold("input JSON must be an object")
    return value


def _read_product_key(descriptor: int) -> bytes:
    if descriptor < 3:
        raise PrebindHold("private Product verification descriptor is required")
    try:
        data = bytearray()
        while len(data) <= _MAX_CONTROL_KEY_BYTES:
            block = os.read(descriptor, min(128, _MAX_CONTROL_KEY_BYTES + 1 - len(data)))
            if not block:
                break
            data.extend(block)
    except OSError as exc:
        raise PrebindHold("private Product verification descriptor is unavailable") from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if not _MIN_CONTROL_KEY_BYTES <= len(data) <= _MAX_CONTROL_KEY_BYTES:
        raise PrebindHold("private Product verification key size is invalid")
    return bytes(data)


def _engineering_operator() -> tuple[int, str]:
    try:
        uid = os.getuid()
        name = pwd.getpwuid(uid).pw_name
    except (AttributeError, KeyError, OSError) as exc:
        raise PrebindHold("Engineering operator identity is unavailable") from exc
    if not name:
        raise PrebindHold("Engineering operator identity is unavailable")
    return uid, name


def _run_prepare(arguments_file: str, product_key_fd: int) -> None:
    product_key = _read_product_key(product_key_fd)
    request = validate_prepare_request(_read_regular_json(arguments_file))
    try:
        verified_instance = validate_instance(request["instance"], key=product_key)
    except ProductInstanceContractError as exc:
        raise PrebindHold("signed runner instance is invalid") from exc
    if product_canonical_json(verified_instance) != product_canonical_json(request["instance"]):
        raise PrebindHold("signed runner instance changed during validation")
    operator_uid, operator_name = _engineering_operator()
    store = _PrebindOperationsStore()
    try:
        receipt = store.prepare_prebind(
            request=request, operator_uid=operator_uid, operator_name=operator_name,
        )
    finally:
        store.close()
    sys.stdout.buffer.write(canonical_json(receipt))
    sys.stdout.buffer.flush()


def _run_activate(arguments_file: str, product_key_fd: int) -> None:
    product_key = _read_product_key(product_key_fd)
    raw = _read_regular_json(arguments_file)
    try:
        if not isinstance(raw.get("install_record"), dict):
            raise PrebindHold("installed runner readback is missing")
        prepared_raw = raw["install_record"].get("prepared_receipt")
        if not isinstance(raw.get("instance"), dict):
            raise PrebindHold("signed current runner instance is missing")
        prepared = validate_prepared_receipt(prepared_raw, instance=raw.get("instance"))
        if raw.get("prepared_receipt_sha256") != prepared.get("receipt_sha256"):
            raise PrebindHold("prepared receipt digest differs")
        request = validate_activation_request(
            raw, product_key=product_key, prepared_receipt=prepared,
        )
    except (ProductInstanceContractError, PrebindHold):
        raise
    except Exception as exc:
        raise PrebindHold("activation facts or runner readback are invalid") from exc
    operator_uid, operator_name = _engineering_operator()
    store = _PrebindOperationsStore()
    try:
        receipt = store.activate_prebind(
            request=request, prepared_receipt=prepared,
            operator_uid=operator_uid, operator_name=operator_name,
        )
    finally:
        store.close()
    sys.stdout.buffer.write(canonical_json(receipt))
    sys.stdout.buffer.flush()


class _PrebindOperationsStore(_ExistingSchemaOperationsStore):
    """Append-only writer for the reserved prebind and activation actions."""

    def prepare_prebind(
        self, *, request: dict[str, Any], operator_uid: int, operator_name: str,
    ) -> dict[str, Any]:
        key = PREPARE_IDEMPOTENCY_PREFIX + request["operation_id"]
        operator = {"uid": operator_uid, "name": operator_name}
        request_hash = hashlib.sha256(canonical_json({
            "request": request, "operator": operator,
        })).hexdigest()
        workspace_instance = (
            f"acp-prebind:v1:{request['workspace_id']}:{request['instance']['runner_instance_id']}"
        )
        try:
            with self._transaction() as connection:
                execute(connection,
                        "SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))",
                        {"scope": workspace_instance})
                prior = fetch_one(
                    connection,
                    """SELECT audit_id, action, request_sha256, response_json
                       FROM operations_audit WHERE idempotency_key = :key""",
                    {"key": key},
                )
                if prior is not None:
                    if (prior.get("action") != PREPARE_ACTION
                            or prior.get("request_sha256") != request_hash
                            or not isinstance(prior.get("response_json"), dict)):
                        raise PrebindHold("prebind idempotency conflict")
                    return prior["response_json"]

                backend_nonce = uuid.uuid4().hex + uuid.uuid4().hex
                prepared = {
                    "schema_version": PREPARE_SCHEMA,
                    "status": "prepared",
                    "authorizes_start": False,
                    "native_facts_verified": False,
                    "runner_install_verified": False,
                    "operation_id": request["operation_id"],
                    "workspace_id": request["workspace_id"],
                    "operator": operator,
                    "runner_instance_id": request["instance"]["runner_instance_id"],
                    "runner_boot_id": request["instance"]["runner_boot_id"],
                    "state_generation": request["instance"]["state_generation"],
                    "signed_instance_sha256": digest(request["instance"]),
                    "deployment": request["deployment"],
                    "state_volume": request["state_volume"],
                    "backend_binding_nonce": backend_nonce,
                    "request_sha256": request_hash,
                }
                receipt_sha256 = digest(prepared)
                prepared["receipt_sha256"] = receipt_sha256
                audit_id = "ops_acp_prebind_" + hashlib.sha256(key.encode()).hexdigest()
                execute(
                    connection,
                    """INSERT INTO operations_audit
                       (audit_id, actor_principal, action, resource_type, resource_id,
                        outcome, idempotency_key, request_sha256, detail_json,
                        response_json, created_at)
                       VALUES (:audit_id, :actor, :action, 'acp_runner_instance',
                               :resource_id, 'prepared', :key, :request_hash,
                               :detail, :response, now())""",
                    {
                        "audit_id": audit_id,
                        "actor": f"engineering:{operator_name}:{operator_uid}",
                        "action": PREPARE_ACTION,
                        "resource_id": request["instance"]["runner_instance_id"],
                        "key": key,
                        "request_hash": request_hash,
                        "detail": {"prepared": prepared},
                        "response": prepared,
                    },
                )
                return prepared
        except PrebindHold:
            raise
        except OperationsPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise OperationsPersistenceError("prebind storage is unavailable") from exc

    def activate_prebind(
        self, *, request: dict[str, Any], prepared_receipt: dict[str, Any],
        operator_uid: int, operator_name: str,
    ) -> dict[str, Any]:
        activation_id = request["activation_id"]
        key = ACTIVATE_IDEMPOTENCY_PREFIX + activation_id
        instance = request["instance"]
        scope = f"acp-prebind:v1:{prepared_receipt['workspace_id']}:{instance['runner_instance_id']}"
        request_hash = hashlib.sha256(canonical_json({
            "request": request,
            "operator": {"uid": operator_uid, "name": operator_name},
        })).hexdigest()
        prepare_key = PREPARE_IDEMPOTENCY_PREFIX + prepared_receipt["operation_id"]
        try:
            with self._transaction() as connection:
                execute(connection,
                        "SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))",
                        {"scope": scope})
                prepared_row = fetch_one(
                    connection,
                    """SELECT action, request_sha256, detail_json, response_json FROM operations_audit
                       WHERE idempotency_key = :key""",
                    {"key": prepare_key},
                )
                if (prepared_row is None or prepared_row.get("action") != PREPARE_ACTION
                        or not isinstance(prepared_row.get("response_json"), dict)
                        or prepared_row["response_json"] != prepared_receipt
                        or prepared_row.get("request_sha256") != prepared_receipt.get("request_sha256")
                        or not isinstance(prepared_row.get("detail_json"), dict)
                        or prepared_row["detail_json"].get("prepared") != prepared_receipt
                        or prepared_row["response_json"].get("receipt_sha256")
                        != request["prepared_receipt_sha256"]):
                    raise PrebindHold("exact prepared Backend receipt is unavailable")

                prior = fetch_one(
                    connection,
                    """SELECT action, request_sha256, response_json FROM operations_audit
                       WHERE idempotency_key = :key""",
                    {"key": key},
                )
                if prior is not None:
                    if (prior.get("action") != ACTIVATE_ACTION
                            or prior.get("request_sha256") != request_hash
                            or not isinstance(prior.get("response_json"), dict)):
                        raise PrebindHold("activation idempotency conflict")
                    response = prior["response_json"]
                    validate_backend_active_receipt(
                        response, prepared_receipt=prepared_receipt,
                        install_record=request["install_record"],
                    )
                    return response

                existing = fetch_one(
                    connection,
                    """SELECT audit_id FROM operations_audit
                       WHERE action = :action AND resource_type = 'acp_runner_instance'
                         AND resource_id = :instance LIMIT 1""",
                    {"action": ACTIVATE_ACTION, "instance": instance["runner_instance_id"]},
                )
                if existing is not None:
                    raise PrebindHold("runner instance already has an activation receipt")

                receipt = {
                    "schema_version": BACKEND_ACTIVE_SCHEMA,
                    "status": "active",
                    "activation_id": activation_id,
                    "workspace_id": prepared_receipt["workspace_id"],
                    "runner_instance_id": instance["runner_instance_id"],
                    "runner_boot_id": instance["runner_boot_id"],
                    "state_generation": instance["state_generation"],
                    "signed_instance_sha256": digest(instance),
                    "prepared_receipt_sha256": prepared_receipt["receipt_sha256"],
                    "backend_binding_nonce": prepared_receipt["backend_binding_nonce"],
                    "install_receipt_sha256": digest(request["install_record"]),
                    "native_binding_sha256": digest({
                        "native_facts": request["native_facts"],
                        "engineering_observation": request["engineering_observation"],
                    }),
                    "activated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
                receipt["receipt_sha256"] = digest(receipt)
                validate_backend_active_receipt(
                    receipt, prepared_receipt=prepared_receipt,
                    install_record=request["install_record"],
                )
                audit_id = "ops_acp_activate_" + hashlib.sha256(key.encode()).hexdigest()
                execute(
                    connection,
                    """INSERT INTO operations_audit
                       (audit_id, actor_principal, action, resource_type, resource_id,
                        outcome, idempotency_key, request_sha256, detail_json,
                        response_json, created_at)
                       VALUES (:audit_id, :actor, :action, 'acp_runner_instance',
                               :instance, 'active', :key, :request_hash,
                               :detail, :response, now())""",
                    {
                        "audit_id": audit_id,
                        "actor": f"engineering:{operator_name}:{operator_uid}",
                        "action": ACTIVATE_ACTION,
                        "instance": instance["runner_instance_id"],
                        "key": key,
                        "request_hash": request_hash,
                        "detail": {
                            "active": receipt,
                            "native_facts": request["native_facts"],
                            "engineering_observation": request["engineering_observation"],
                            "install_record": request["install_record"],
                        },
                        "response": receipt,
                    },
                )
                return receipt
        except PrebindHold:
            raise
        except OperationsPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise OperationsPersistenceError("prebind activation storage is unavailable") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--arguments-file", required=True)
    prepare.add_argument("--product-key-fd", required=True, type=int)
    activate = commands.add_parser("activate")
    activate.add_argument("--arguments-file", required=True)
    activate.add_argument("--product-key-fd", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            _run_prepare(args.arguments_file, args.product_key_fd)
        else:
            _run_activate(args.arguments_file, args.product_key_fd)
    except Exception as exc:
        frames = [frame for frame in traceback.extract_tb(exc.__traceback__)
                  if Path(frame.filename).resolve().parent == Path(__file__).resolve().parent]
        location = f" {Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else ""
        exception_name = type(exc).__name__
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", exception_name) is None:
            exception_name = "Exception"
        sys.stderr.write(f"HOLD {exception_name}{location}\n")
        sys.stderr.flush()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
