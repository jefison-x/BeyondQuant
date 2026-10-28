"""One-shot Engineering proof supplement for one historical ACP Root.

This module is not imported by the HTTP application and exposes no Product,
MCP, or browser operation. It only verifies the Backend-frozen scope and the
Product Runner's signed cleanup receipt before atomically updating the exact
persisted Adapter binding.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

from packages.contracts.acp_product_slot import (
    PRODUCT_SCOPE_KEYS,
    canonical_product_json,
    validate_product_scope,
)

from .acp_product_slot_client import (
    ProductSlotLeaseMismatch,
    read_product_cleanup_receipt_with_sha256,
)


EXPECTED_SCOPE_SCHEMA = "byq-acp-product-cleanup-scope.v1"
EXPECTED_MANIFEST_SCHEMA = "byq-acp-historical-audit-manifest.v1"
HISTORICAL_ROOT_RUN_ID = "753727634c8641a0add1597d6a304bae"
DEFAULT_PRODUCT_CONTROL_DIRECTORY = Path("/run/byq-acp-product-runner")
ENGINEERING_MANIFEST_PATH = Path(
    "/run/byq-engineering/historical-audit-manifest.json",
)
_BACKEND_SCOPE_KEYS = PRODUCT_SCOPE_KEYS - {"cwd_leaf"}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_NATIVE_SESSION = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_BINDING_KEYS = frozenset({
    "schema_version", "session_id", "trace_id", "owner_principal",
    "workspace_id", "root_run_id", "native_session_id", "runtime_generation",
    "model_provider", "model_id", "cwd", "previous_boot_id",
    "previous_authority_epoch", "sequence", "settlement_receipt",
    "domain_call_sequence", "domain_call_drained_sequence",
    "native_session_close_confirmed", "process_exit_confirmed",
    "cleanup_unconfirmed", "closed",
})
_SCOPE_FILE_KEYS = frozenset({
    "schema_version", "scope", "native_root_session_id",
    "backend_snapshot_sha256",
})
_MANIFEST_KEYS = frozenset({
    "schema_version", "expected_scope_file_sha256",
    "backend_snapshot_sha256", "native_root_session_id",
    "expected_binding_sha256", "control_key_sha256",
})
_MAX_SCOPE_FILE_BYTES = 16_384
_MAX_MANIFEST_BYTES = 4096
_MAX_BINDING_BYTES = 1_048_576
_PRODUCT_UID = 10002


class HistoricalCleanupHold(RuntimeError):
    """The exact signed cleanup supplement cannot proceed safely."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise HistoricalCleanupHold("duplicate JSON field")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise HistoricalCleanupHold("non-finite JSON number")


def _read_regular_file(path: Path, limit: int) -> tuple[bytes, os.stat_result]:
    try:
        before = os.lstat(path)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > limit):
            raise HistoricalCleanupHold("input file is not a bounded regular file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_size > limit):
                raise HistoricalCleanupHold("input file changed while opening")
            chunks = bytearray()
            while len(chunks) <= limit:
                block = os.read(descriptor, min(65_536, limit + 1 - len(chunks)))
                if not block:
                    break
                chunks.extend(block)
            if len(chunks) > limit:
                raise HistoricalCleanupHold("input file exceeds its bound")
            return bytes(chunks), opened
        finally:
            os.close(descriptor)
    except HistoricalCleanupHold:
        raise
    except OSError as exc:
        raise HistoricalCleanupHold("input file is unavailable") from exc


def _parse_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise HistoricalCleanupHold("input JSON is invalid") from exc
    if not isinstance(value, dict):
        raise HistoricalCleanupHold("input JSON must be an object")
    return value


def _read_expected_scope(
    path: Path, expected_sha256: str,
) -> tuple[dict[str, str], str, str]:
    if _HEX64.fullmatch(expected_sha256) is None:
        raise HistoricalCleanupHold("expected scope file digest is invalid")
    if not path.is_absolute():
        raise HistoricalCleanupHold("expected scope file path must be absolute")
    raw, _info = _read_regular_file(path, _MAX_SCOPE_FILE_BYTES)
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise HistoricalCleanupHold("expected scope file digest changed")
    envelope = _parse_object(raw)
    try:
        canonical = canonical_product_json(envelope)
    except ValueError as exc:
        raise HistoricalCleanupHold("expected Backend scope envelope is invalid") from exc
    if raw != canonical:
        raise HistoricalCleanupHold("expected Backend scope envelope is not canonical")
    if (set(envelope) != _SCOPE_FILE_KEYS
            or envelope.get("schema_version") != EXPECTED_SCOPE_SCHEMA
            or not isinstance(envelope.get("native_root_session_id"), str)
            or _NATIVE_SESSION.fullmatch(envelope["native_root_session_id"]) is None
            or not isinstance(envelope.get("backend_snapshot_sha256"), str)
            or _HEX64.fullmatch(envelope["backend_snapshot_sha256"]) is None):
        raise HistoricalCleanupHold("expected Backend scope envelope is invalid")
    backend_scope = envelope.get("scope")
    if (not isinstance(backend_scope, dict)
            or set(backend_scope) != _BACKEND_SCOPE_KEYS
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in backend_scope.items())):
        raise HistoricalCleanupHold("expected Backend scope fields are invalid")
    if backend_scope.get("root_run_id") != HISTORICAL_ROOT_RUN_ID:
        raise HistoricalCleanupHold("scope is outside this historical Root")
    # Reuse the Product scope validator for every shared field, with a valid
    # placeholder cwd leaf that is discarded. The actual leaf comes only from
    # the locked, persisted Adapter binding below.
    try:
        validate_product_scope({
            **backend_scope,
            "cwd_leaf": f"root-{backend_scope['root_run_id']}",
        })
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalCleanupHold("expected Backend scope values are invalid") from exc
    return (
        dict(backend_scope),
        envelope["native_root_session_id"],
        envelope["backend_snapshot_sha256"],
    )


def _read_trusted_manifest() -> dict[str, str]:
    directory = ENGINEERING_MANIFEST_PATH.parent
    try:
        directory_info = os.lstat(directory)
        resolved_directory = directory.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HistoricalCleanupHold("Engineering manifest directory is unavailable") from exc
    if (not stat.S_ISDIR(directory_info.st_mode)
            or resolved_directory != directory
            or directory_info.st_uid != 0
            or stat.S_IMODE(directory_info.st_mode) & 0o022):
        raise HistoricalCleanupHold("Engineering manifest directory is unsafe")
    raw, info = _read_regular_file(ENGINEERING_MANIFEST_PATH, _MAX_MANIFEST_BYTES)
    if (info.st_uid == _PRODUCT_UID
            or stat.S_IMODE(info.st_mode) != 0o444):
        raise HistoricalCleanupHold("Engineering manifest file is unsafe")
    try:
        mount_flags = os.statvfs(ENGINEERING_MANIFEST_PATH).f_flag
    except OSError as exc:
        raise HistoricalCleanupHold("Engineering manifest mount state is unavailable") from exc
    if not mount_flags & getattr(os, "ST_RDONLY", 1):
        raise HistoricalCleanupHold("Engineering manifest mount is not read-only")
    envelope = _parse_object(raw)
    try:
        canonical = canonical_product_json(envelope)
    except ValueError as exc:
        raise HistoricalCleanupHold("Engineering manifest is invalid") from exc
    if raw != canonical or set(envelope) != _MANIFEST_KEYS:
        raise HistoricalCleanupHold("Engineering manifest schema is invalid")
    if envelope.get("schema_version") != EXPECTED_MANIFEST_SCHEMA:
        raise HistoricalCleanupHold("Engineering manifest schema is invalid")
    for key in (
        "expected_scope_file_sha256", "backend_snapshot_sha256",
        "expected_binding_sha256", "control_key_sha256",
    ):
        if (not isinstance(envelope.get(key), str)
                or _HEX64.fullmatch(envelope[key]) is None):
            raise HistoricalCleanupHold("Engineering manifest digest is invalid")
    if (not isinstance(envelope.get("native_root_session_id"), str)
            or _NATIVE_SESSION.fullmatch(envelope["native_root_session_id"]) is None):
        raise HistoricalCleanupHold("Engineering manifest native identity is invalid")
    return {key: envelope[key] for key in _MANIFEST_KEYS}


def _require_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise HistoricalCleanupHold("binding directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise HistoricalCleanupHold("binding directory is unsafe")


def _binding_path(session_root: Path, scope: dict[str, str]) -> Path:
    try:
        root = session_root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise HistoricalCleanupHold("configured session root is unavailable") from exc
    _require_directory(root)
    workspace_root = root / scope["workspace_id"]
    binding_directory = workspace_root / "byq-acp-bindings"
    _require_directory(workspace_root)
    _require_directory(binding_directory)
    return binding_directory / f"{scope['session_id']}.json"


def _validate_binding(
    raw: bytes, backend_scope: dict[str, str],
    native_root_session_id: str, session_root: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    binding = _parse_object(raw)
    if (set(binding) != _BINDING_KEYS
            or binding.get("schema_version") != "byq-acp-root-binding.v1"):
        raise HistoricalCleanupHold("persisted ACP binding schema is invalid")
    for key in ("session_id", "trace_id", "owner_principal", "workspace_id", "root_run_id"):
        if binding.get(key) != backend_scope[key]:
            raise HistoricalCleanupHold("persisted ACP binding identity differs")
    if (binding.get("previous_boot_id") != backend_scope["runtime_boot_id"]
            or binding.get("runtime_generation") != backend_scope["generation_id"]):
        raise HistoricalCleanupHold("persisted ACP binding generation differs")

    cwd = binding.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise HistoricalCleanupHold("persisted ACP binding working directory is invalid")
    session_root_resolved = session_root.expanduser().resolve()
    expected_workspace_root = session_root_resolved / backend_scope["workspace_id"]
    cwd_path = Path(cwd)
    try:
        resolved_cwd = cwd_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise HistoricalCleanupHold("persisted ACP binding working directory is invalid") from exc
    if (resolved_cwd != cwd_path or cwd_path.parent != expected_workspace_root):
        raise HistoricalCleanupHold("persisted ACP binding working directory differs")
    try:
        scope = validate_product_scope({
            **backend_scope,
            "cwd_leaf": cwd_path.name,
        })
    except (TypeError, ValueError) as exc:
        raise HistoricalCleanupHold("persisted ACP binding scope is invalid") from exc

    if (binding.get("native_session_id") != native_root_session_id
            or not isinstance(binding.get("native_session_id"), str)
            or _NATIVE_SESSION.fullmatch(binding["native_session_id"]) is None
            or not isinstance(binding.get("model_provider"), str)
            or not binding["model_provider"]
            or not isinstance(binding.get("model_id"), str)
            or not binding["model_id"]):
        raise HistoricalCleanupHold("persisted ACP binding fields are invalid")
    if (_HEX32.fullmatch(str(binding.get("previous_boot_id"))) is None
            or type(binding.get("previous_authority_epoch")) is not int
            or binding["previous_authority_epoch"] <= 0
            or type(binding.get("sequence")) is not int or binding["sequence"] < 0
            or type(binding.get("domain_call_sequence")) is not int
            or binding["domain_call_sequence"] < 0
            or type(binding.get("domain_call_drained_sequence")) is not int
            or not 0 <= binding["domain_call_drained_sequence"] <= binding["domain_call_sequence"]):
        raise HistoricalCleanupHold("persisted ACP binding counters are invalid")
    for key in (
        "native_session_close_confirmed", "process_exit_confirmed",
        "cleanup_unconfirmed", "closed",
    ):
        if type(binding.get(key)) is not bool:
            raise HistoricalCleanupHold("persisted ACP binding close state is invalid")
    if (binding["process_exit_confirmed"] is not False
            or binding["cleanup_unconfirmed"] is not False
            or binding["closed"] is not False
            or binding["domain_call_sequence"] != binding["domain_call_drained_sequence"]):
        raise HistoricalCleanupHold("persisted ACP binding is not eligible for proof supplement")
    if binding.get("settlement_receipt") is not None and not isinstance(
        binding["settlement_receipt"], dict,
    ):
        raise HistoricalCleanupHold("persisted ACP binding settlement is invalid")
    try:
        canonical_product_json(binding)
    except ValueError as exc:
        raise HistoricalCleanupHold("persisted ACP binding JSON is invalid") from exc
    return binding, scope


def _read_control_key(control_fd: int) -> bytes:
    if type(control_fd) is not int or control_fd < 0:
        raise HistoricalCleanupHold("private control descriptor is invalid")
    chunks = bytearray()
    while len(chunks) <= 512:
        try:
            block = os.read(control_fd, 513 - len(chunks))
        except OSError as exc:
            raise HistoricalCleanupHold("private control descriptor is unavailable") from exc
        if not block:
            break
        chunks.extend(block)
    if not 32 <= len(chunks) <= 512:
        raise HistoricalCleanupHold("private control key length is invalid")
    return bytes(chunks)


def _read_binding_file(path: Path) -> tuple[bytes, os.stat_result]:
    raw, info = _read_regular_file(path, _MAX_BINDING_BYTES)
    if (info.st_uid != os.getuid() or info.st_gid != os.getgid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise HistoricalCleanupHold("persisted ACP binding ownership is unsafe")
    return raw, info


def _atomic_replace_binding(
    path: Path, original_raw: bytes, original_info: os.stat_result,
    updated: dict[str, Any],
) -> str:
    updated_raw = canonical_product_json(updated)
    parent_fd = os.open(
        path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary_name: str | None = None
    try:
        current_raw, current_info = _read_binding_file(path)
        if (current_raw != original_raw
                or (current_info.st_dev, current_info.st_ino)
                != (original_info.st_dev, original_info.st_ino)):
            raise HistoricalCleanupHold("persisted ACP binding changed before write")
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".binding-", delete=False,
        ) as stream:
            temporary_name = Path(stream.name).name
            os.chmod(stream.name, 0o600)
            stream.write(updated_raw)
            stream.flush()
            os.fsync(stream.fileno())
        current = os.stat(path, follow_symlinks=False)
        if ((current.st_dev, current.st_ino)
                != (original_info.st_dev, original_info.st_ino)
                or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1):
            raise HistoricalCleanupHold("persisted ACP binding changed before replace")
        if temporary_name is None:
            raise HistoricalCleanupHold("temporary binding file was not created")
        os.replace(
            temporary_name, path.name,
            src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
        )
        temporary_name = None
        os.fsync(parent_fd)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)
    return hashlib.sha256(updated_raw).hexdigest()


def supplement_historical_binding(
    *, expected_scope_file: Path, expected_file_sha256: str,
    expected_binding_sha256: str,
    control_fd: int, session_root: Path,
) -> dict[str, object]:
    """Verify exact frozen scope and signed cleanup, then change one binding bit."""

    manifest = _read_trusted_manifest()
    if manifest["expected_scope_file_sha256"] != expected_file_sha256:
        raise HistoricalCleanupHold("scope file digest differs from Engineering manifest")
    if manifest["expected_binding_sha256"] != expected_binding_sha256:
        raise HistoricalCleanupHold("binding digest differs from Engineering manifest")
    backend_scope, native_root_session_id, backend_snapshot_sha256 = _read_expected_scope(
        expected_scope_file, expected_file_sha256,
    )
    if (backend_snapshot_sha256 != manifest["backend_snapshot_sha256"]
            or native_root_session_id != manifest["native_root_session_id"]):
        raise HistoricalCleanupHold("Backend scope differs from Engineering manifest")
    if _HEX64.fullmatch(expected_binding_sha256) is None:
        raise HistoricalCleanupHold("expected persisted binding digest is invalid")
    control_key = _read_control_key(control_fd)
    if hashlib.sha256(control_key).hexdigest() != manifest["control_key_sha256"]:
        raise HistoricalCleanupHold("private control key differs from Engineering manifest")
    binding_path = _binding_path(session_root, backend_scope)
    lock_path = binding_path.with_suffix(".lock")
    try:
        lock_before = os.lstat(lock_path)
    except FileNotFoundError:
        lock_before = None
    except OSError as exc:
        raise HistoricalCleanupHold("persisted ACP binding lock is unavailable") from exc
    if lock_before is not None and (
        not stat.S_ISREG(lock_before.st_mode) or lock_before.st_nlink != 1
    ):
        raise HistoricalCleanupHold("persisted ACP binding lock is unsafe")
    try:
        lock_fd = os.open(
            lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
    except OSError as exc:
        raise HistoricalCleanupHold("persisted ACP binding lock is unavailable") from exc
    try:
        lock_info = os.fstat(lock_fd)
        if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1
                or lock_info.st_uid != os.getuid() or lock_info.st_gid != os.getgid()
                or stat.S_IMODE(lock_info.st_mode) != 0o600):
            raise HistoricalCleanupHold("persisted ACP binding lock is unsafe")
        if lock_before is not None and (
            (lock_info.st_dev, lock_info.st_ino)
            != (lock_before.st_dev, lock_before.st_ino)
        ):
            raise HistoricalCleanupHold("persisted ACP binding lock changed")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        original_raw, original_info = _read_binding_file(binding_path)
        original_sha256 = hashlib.sha256(original_raw).hexdigest()
        already_supplemented = False
        if original_sha256 == expected_binding_sha256:
            before_raw = original_raw
            binding, scope = _validate_binding(
                before_raw, backend_scope, native_root_session_id, session_root,
            )
            if before_raw != canonical_product_json(binding):
                raise HistoricalCleanupHold("persisted ACP binding is not canonical")
        else:
            current_binding = _parse_object(original_raw)
            if (set(current_binding) != _BINDING_KEYS
                    or current_binding.get("schema_version") != "byq-acp-root-binding.v1"
                    or current_binding.get("process_exit_confirmed") is not True
                    or original_raw != canonical_product_json(current_binding)):
                raise HistoricalCleanupHold("persisted ACP binding digest changed")
            before_value = dict(current_binding)
            before_value["process_exit_confirmed"] = False
            before_raw = canonical_product_json(before_value)
            if hashlib.sha256(before_raw).hexdigest() != expected_binding_sha256:
                raise HistoricalCleanupHold("persisted ACP binding digest changed")
            binding, scope = _validate_binding(
                before_raw, backend_scope, native_root_session_id, session_root,
            )
            expected_after = dict(binding)
            expected_after["process_exit_confirmed"] = True
            if canonical_product_json(expected_after) != original_raw:
                raise HistoricalCleanupHold("persisted ACP binding differs from exact supplement")
            already_supplemented = True
        try:
            receipt, receipt_sha256 = read_product_cleanup_receipt_with_sha256(
                DEFAULT_PRODUCT_CONTROL_DIRECTORY, control_key, scope,
            )
        except ProductSlotLeaseMismatch as exc:
            raise HistoricalCleanupHold(
                "Product Runner cleanup receipt is unavailable or invalid",
            ) from exc
        if receipt["cleanup"] != "proven":
            raise HistoricalCleanupHold("Product Runner cleanup remains unproven")
        if already_supplemented:
            after_sha256 = original_sha256
        else:
            updated = dict(binding)
            updated["process_exit_confirmed"] = True
            after_sha256 = _atomic_replace_binding(
                binding_path, original_raw, original_info, updated,
            )
        return {
            "status": "supplemented",
            "root_run_id": scope["root_run_id"],
            "backend_snapshot_sha256": backend_snapshot_sha256,
            "native_root_session_id": native_root_session_id,
            "scope": scope,
            "binding_sha256_before": expected_binding_sha256,
            "binding_sha256_after": after_sha256,
            "product_cleanup_receipt_sha256": receipt_sha256,
            "product_cleanup_scope_digest": str(receipt["scope_digest"]),
            "product_cleanup_receipt_raw_b64": base64.b64encode(
                canonical_product_json(receipt),
            ).decode("ascii"),
        }
    except HistoricalCleanupHold:
        raise
    except (OSError, ValueError) as exc:
        raise HistoricalCleanupHold("historical binding proof supplement failed") from exc
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-scope-file", required=True, type=Path)
    parser.add_argument("--expected-file-sha256", required=True)
    parser.add_argument("--expected-binding-sha256", required=True)
    parser.add_argument("--session-root", required=True, type=Path)
    parser.add_argument("--control-fd", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        result = supplement_historical_binding(
            expected_scope_file=args.expected_scope_file,
            expected_file_sha256=args.expected_file_sha256,
            expected_binding_sha256=args.expected_binding_sha256,
            control_fd=args.control_fd,
            session_root=args.session_root,
        )
    except HistoricalCleanupHold as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
