"""One-shot Engineering CLI for historical ACP audit reconciliation.

This module is intentionally separate from the Backend HTTP application. It
offers only the offline prepare/finalize operations required by ADR-0113.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import stat
import sys
import traceback
from pathlib import Path
from typing import Any

from packages.contracts.acp_product_slot import PRODUCT_SCOPE_KEYS, canonical_product_json

from .agent_research import AgentResearchStore


_SCOPE_SCHEMA = "byq-acp-product-cleanup-scope.v1"
_BACKEND_SCOPE_KEYS = PRODUCT_SCOPE_KEYS - {"cwd_leaf"}
_SCOPE_ENVELOPE_KEYS = frozenset({
    "schema_version", "scope", "native_root_session_id", "backend_snapshot_sha256",
})
_RUNTIME_RESULT_KEYS = frozenset({
    "status", "root_run_id", "backend_snapshot_sha256", "native_root_session_id",
    "scope", "binding_sha256_before", "binding_sha256_after",
    "product_cleanup_receipt_sha256", "product_cleanup_scope_digest",
    "product_cleanup_receipt_raw_b64",
})
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NATIVE_SESSION = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_MAX_ARGUMENTS_BYTES = 1_048_576
_MAX_RUNTIME_RESULT_BYTES = 32_768
_MAX_CONTROL_KEY_BYTES = 512
_MIN_CONTROL_KEY_BYTES = 32
_HISTORICAL_REQUEST_IDS = frozenset({
    "5e8e9f1701b9843fbce73ab218fa748a",
    "854f82571071842756c622ab4c532659",
})


class ReconciliationHold(RuntimeError):
    """The offline reconciliation input cannot be accepted safely."""


class _ExistingSchemaAgentResearchStore(AgentResearchStore):
    """Construct a store over the already-installed schema without running DDL."""

    def bootstrap_schema(self) -> None:
        return None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ReconciliationHold("duplicate JSON field")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ReconciliationHold("non-finite JSON number")


def _read_regular_json(path_value: str, *, limit: int) -> object:
    path = Path(path_value)
    try:
        before = os.lstat(path)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > limit):
            raise ReconciliationHold("input is not a bounded regular file")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_size > limit):
                raise ReconciliationHold("input changed while opening")
            raw = bytearray()
            while len(raw) <= limit:
                block = os.read(descriptor, min(65_536, limit + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            after = os.fstat(descriptor)
            if (len(raw) > limit or len(raw) != after.st_size
                    or (opened.st_dev, opened.st_ino, opened.st_size,
                        opened.st_mtime_ns, opened.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns)):
                raise ReconciliationHold("input changed while reading")
        finally:
            os.close(descriptor)
    except ReconciliationHold:
        raise
    except (OSError, ValueError) as exc:
        raise ReconciliationHold("input file is unavailable") from exc

    try:
        value = json.loads(
            bytes(raw).decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except ReconciliationHold:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ReconciliationHold("input JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ReconciliationHold("input JSON must be an object")
    return value


def _read_control_key(descriptor: int) -> bytes:
    if descriptor < 3:
        raise ReconciliationHold("private control descriptor is required")
    try:
        data = bytearray()
        while len(data) <= _MAX_CONTROL_KEY_BYTES:
            block = os.read(descriptor, min(128, _MAX_CONTROL_KEY_BYTES + 1 - len(data)))
            if not block:
                break
            data.extend(block)
    except OSError as exc:
        raise ReconciliationHold("private control descriptor is unavailable") from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if not _MIN_CONTROL_KEY_BYTES <= len(data) <= _MAX_CONTROL_KEY_BYTES:
        raise ReconciliationHold("private control key size is invalid")
    return bytes(data)


def _validate_arguments_by_request(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _HISTORICAL_REQUEST_IDS:
        raise ReconciliationHold("arguments-by-request input is invalid")
    for request_id, arguments in value.items():
        if (not isinstance(request_id, str) or not request_id
                or len(request_id.encode("utf-8")) > 256
                or not isinstance(arguments, dict)):
            raise ReconciliationHold("arguments-by-request input is invalid")
    return value


def _validate_scope_envelope(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _SCOPE_ENVELOPE_KEYS:
        raise ReconciliationHold("prepared scope result is invalid")
    scope = value.get("scope")
    if (value.get("schema_version") != _SCOPE_SCHEMA
            or not isinstance(scope, dict)
            or set(scope) != _BACKEND_SCOPE_KEYS
            or any(not isinstance(key, str) or not isinstance(item, str)
                   for key, item in scope.items())
            or not isinstance(value.get("native_root_session_id"), str)
            or _NATIVE_SESSION.fullmatch(value["native_root_session_id"]) is None
            or not isinstance(value.get("backend_snapshot_sha256"), str)
            or _HEX64.fullmatch(value["backend_snapshot_sha256"]) is None):
        raise ReconciliationHold("prepared scope result is invalid")
    return value


def _validate_runtime_result(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _RUNTIME_RESULT_KEYS:
        raise ReconciliationHold("runtime result is invalid")
    scope = value.get("scope")
    digest_fields = (
        "backend_snapshot_sha256", "binding_sha256_before", "binding_sha256_after",
        "product_cleanup_receipt_sha256", "product_cleanup_scope_digest",
    )
    if (value.get("status") != "supplemented"
            or not isinstance(scope, dict)
            or set(scope) != PRODUCT_SCOPE_KEYS
            or any(not isinstance(key, str) or not isinstance(item, str)
                   for key, item in scope.items())
            or any(not isinstance(value.get(field), str)
                   or _HEX64.fullmatch(value[field]) is None for field in digest_fields)
            or not isinstance(value.get("root_run_id"), str)
            or not isinstance(value.get("native_root_session_id"), str)
            or _NATIVE_SESSION.fullmatch(value["native_root_session_id"]) is None
            or not isinstance(value.get("product_cleanup_receipt_raw_b64"), str)
            or len(value["product_cleanup_receipt_raw_b64"]) > 8_192):
        raise ReconciliationHold("runtime result is invalid")
    return value


def _canonical_result(value: object) -> None:
    try:
        encoded = canonical_product_json(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReconciliationHold("reconciliation result is invalid") from exc
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _run_prepare(arguments_file: str) -> None:
    arguments_by_request = _validate_arguments_by_request(
        _read_regular_json(arguments_file, limit=_MAX_ARGUMENTS_BYTES),
    )
    store = _ExistingSchemaAgentResearchStore()
    try:
        result = store.prepare_historical_audit_reconciliation(
            arguments_by_request=arguments_by_request,
        )
    finally:
        store.close()
    _canonical_result(_validate_scope_envelope(result))


def _run_finalize(arguments_file: str, runtime_result_file: str, control_fd: int) -> None:
    arguments_by_request = _validate_arguments_by_request(
        _read_regular_json(arguments_file, limit=_MAX_ARGUMENTS_BYTES),
    )
    runtime_result = _validate_runtime_result(
        _read_regular_json(runtime_result_file, limit=_MAX_RUNTIME_RESULT_BYTES),
    )
    control_key = _read_control_key(control_fd)
    try:
        operator_uid = os.getuid()
        operator_name = pwd.getpwuid(operator_uid).pw_name
    except (AttributeError, KeyError, OSError) as exc:
        raise ReconciliationHold("Engineering operator identity is unavailable") from exc
    if not operator_name:
        raise ReconciliationHold("Engineering operator identity is unavailable")

    store = _ExistingSchemaAgentResearchStore()
    try:
        result = store.finalize_historical_audit_reconciliation(
            runtime_result=runtime_result,
            arguments_by_request=arguments_by_request,
            product_control_key=control_key,
            operator_uid=operator_uid,
            operator_name=operator_name,
        )
    finally:
        store.close()
    _canonical_result(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--arguments-file", required=True)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--arguments-file", required=True)
    finalize.add_argument("--runtime-result-file", required=True)
    finalize.add_argument("--control-fd", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            _run_prepare(args.arguments_file)
        else:
            _run_finalize(args.arguments_file, args.runtime_result_file, args.control_fd)
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
