"""Private, root-only installer for Product runner prebind records.

This is an Engineering container-exec entry point, never a Product API.
Installation records prepared intent; activation requires a validated Backend
active receipt and does not by itself authorize START without server checks.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.acp_product_instance import validate_instance
from packages.contracts.acp_product_prebind import (
    ACTIVATION_SCHEMA, PrebindContractError, canonical_json, digest, make_install_record,
    sign_activation_record, validate_activation_record,
    validate_backend_active_receipt, validate_birth_mode,
    validate_install_record, validate_prepared_receipt,
)

STATE = Path("/var/lib/byq/acp-product-runner-state")
CONTROL = Path("/run/byq-acp-product-runner")
WORKSPACE_ENV = "BYQ_ACP_PRODUCT_WORKSPACE_ID"
SECRET_ENV = "BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET"
MODE_ENV = "BYQ_ACP_PRODUCT_REQUIRE_PREBIND"


def _json(data: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("invalid number")))


def _read(path: Path, *, uid: int, gid: int, mode: int, limit: int = 65536) -> bytes:
    before = os.lstat(path)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != uid or before.st_gid != gid
            or stat.S_IMODE(before.st_mode) != mode or before.st_size > limit):
        raise ValueError("private prebind input permissions are invalid")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("private prebind input changed")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(8192, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > limit:
            raise ValueError("private prebind input exceeds bound")
        return bytes(data)
    finally:
        os.close(fd)


def _pid1_environment() -> dict[str, str]:
    raw = Path("/proc/1/environ").read_bytes()
    values = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        if key.decode("ascii", "ignore") in {WORKSPACE_ENV, SECRET_ENV, MODE_ENV}:
            values[key.decode("ascii")] = value.decode("utf-8")
    return values


def _verify_pid1_entrypoint() -> None:
    raw = Path("/proc/1/cmdline").read_bytes().split(b"\0")
    argv = tuple(item.decode("utf-8") for item in raw if item)
    allowed = {
        ("python3", "/opt/byq/acp_product_runner/server.py"),
        ("/usr/bin/python3", "/opt/byq/acp_product_runner/server.py"),
    }
    if argv not in allowed:
        raise ValueError("Product runner PID 1 entrypoint is not the pinned daemon")


def _sync_exact_record(path: Path, expected: bytes, *, uid: int, gid: int,
                       mode: int, limit: int = 65536,
                       identity: tuple[int, int] | None = None) -> tuple[int, int]:
    before = os.lstat(path)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != uid or before.st_gid != gid
            or stat.S_IMODE(before.st_mode) != mode or before.st_size > limit
            or (identity is not None and (before.st_dev, before.st_ino) != identity)):
        raise ValueError("installed prebind record identity is invalid")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or opened.st_nlink != 1 or opened.st_size > limit):
            raise ValueError("installed prebind record changed while opening")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(8192, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if bytes(data) != expected:
            raise ValueError("installed prebind exact readback differs")
        os.fsync(fd)
        after = os.fstat(fd)
        if ((after.st_dev, after.st_ino, after.st_nlink, after.st_size)
                != (opened.st_dev, opened.st_ino, 1, len(expected))):
            raise ValueError("installed prebind record changed during fsync")
        identity = (after.st_dev, after.st_ino)
    finally:
        os.close(fd)
    directory = path.parent
    directory_info = os.lstat(directory)
    if (not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != uid
            or directory_info.st_gid != gid or stat.S_IMODE(directory_info.st_mode) != 0o700):
        raise ValueError("installed prebind directory is invalid")
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                           | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened_directory = os.fstat(directory_fd)
        if ((opened_directory.st_dev, opened_directory.st_ino)
                != (directory_info.st_dev, directory_info.st_ino)):
            raise ValueError("installed prebind directory changed")
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return identity


def _persist_immutable(path: Path, value: dict, *, gid: int) -> tuple[bytes, tuple[int, int]]:
    payload = canonical_json(value)
    temp = path.parent / ("." + path.name + "." + os.urandom(8).hex() + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchown(fd, 0, gid)
        os.fchmod(fd, 0o600)
        view = memoryview(payload)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("short prebind write")
            view = view[count:]
        os.fsync(fd)
        temp_info = os.fstat(fd)
        if (not stat.S_ISREG(temp_info.st_mode) or temp_info.st_nlink != 1
                or temp_info.st_uid != 0 or temp_info.st_gid != gid
                or stat.S_IMODE(temp_info.st_mode) != 0o600):
            raise ValueError("prebind staging file permissions are invalid")
        identity = (temp_info.st_dev, temp_info.st_ino)
    finally:
        os.close(fd)
    try:
        os.link(temp, path, follow_symlinks=False)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                               | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    _sync_exact_record(path, payload, uid=0, gid=gid, mode=0o600, identity=identity)
    return payload, identity


def install(candidate_path: Path) -> None:
    if os.geteuid() != 0 or os.getpid() == 1:
        raise ValueError("private container-exec root context is required")
    _verify_pid1_entrypoint()
    environ = _pid1_environment()
    if (environ.get(MODE_ENV) != "1" or not environ.get(WORKSPACE_ENV)
            or not environ.get(SECRET_ENV)):
        raise ValueError("PID 1 was not born with prebind qualification enabled")
    key = base64.urlsafe_b64decode(environ[SECRET_ENV] + "=" * (-len(environ[SECRET_ENV]) % 4))
    if len(key) < 32:
        raise ValueError("Product runner signing key is invalid")
    state_info = os.lstat(STATE)
    if (not stat.S_ISDIR(state_info.st_mode) or state_info.st_uid != 0
            or stat.S_IMODE(state_info.st_mode) != 0o700):
        raise ValueError("private state volume is invalid")
    lifetime = os.open(STATE / ".runner-lifetime.lock", os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            fcntl.flock(lifetime, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass  # PID 1 owns the state-volume lifetime lock.
        else:
            fcntl.flock(lifetime, fcntl.LOCK_UN)
            raise ValueError("Product runner lifetime lock is not held")
    finally:
        os.close(lifetime)
    admission = os.open(STATE / ".runner-admission.lock", os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(admission, fcntl.LOCK_EX)
        descriptor_path = CONTROL / "instance.json"
        descriptor = _json(_read(descriptor_path, uid=0, gid=10006, mode=0o640, limit=4096))
        instance_path = STATE / "instances" / f"{descriptor.get('runner_instance_id')}.json"
        instance_bytes = _read(instance_path, uid=0, gid=0, mode=0o600, limit=4096)
        instance = _json(instance_bytes)
        if canonical_json(descriptor) != canonical_json(instance):
            raise ValueError("control descriptor differs from current state instance")
        validate_instance(instance, key=key)
        if instance.get("workspace_id") != environ[WORKSPACE_ENV]:
            raise ValueError("current runner workspace differs from PID 1")
        instance_id = instance["runner_instance_id"]
        instances = STATE / "instances"
        marker = instances / f"{instance_id}.started.json"
        if os.path.lexists(marker):
            raise ValueError("runner has already crossed START admission")
        birth_path = instances / f"{instance_id}.birth-mode.json"
        birth = _json(_read(birth_path, uid=0, gid=0, mode=0o600))
        validate_birth_mode(birth, key=key, instance=instance)
        if birth["require_prebind"] is not True:
            raise ValueError("runner birth mode is not qualified")
        prepared = _json(_read(candidate_path, uid=0, gid=0, mode=0o600))
        receipt = validate_prepared_receipt(prepared, instance=instance)
        install_path = instances / f"{instance_id}.prebind-install.json"
        if os.path.lexists(install_path):
            existing_bytes = _read(install_path, uid=0, gid=0, mode=0o600)
            existing = _json(existing_bytes)
            validate_install_record(existing, key=key, instance=instance, birth_mode=birth)
            if existing["prepared_receipt_sha256"] != receipt["receipt_sha256"]:
                raise ValueError("a different prepared candidate is already installed")
            if canonical_json(existing) != existing_bytes:
                raise ValueError("existing installed prebind encoding is not canonical")
            _sync_exact_record(install_path, existing_bytes, uid=0, gid=0, mode=0o600)
            return
        record = make_install_record(
            instance=instance, birth_mode=birth, prepared_receipt=receipt,
            installed_at=datetime.now(timezone.utc).isoformat(), key=key,
        )
        expected_bytes, identity = _persist_immutable(install_path, record, gid=0)
        readback_bytes = _read(install_path, uid=0, gid=0, mode=0o600)
        readback = _json(readback_bytes)
        validate_install_record(readback, key=key, instance=instance, birth_mode=birth)
        if canonical_json(readback) != canonical_json(record) or readback_bytes != expected_bytes:
            raise ValueError("installed prebind readback differs")
        _sync_exact_record(install_path, expected_bytes, uid=0, gid=0, mode=0o600,
                           identity=identity)
    finally:
        fcntl.flock(admission, fcntl.LOCK_UN)
        os.close(admission)


def activate(receipt_path: Path) -> None:
    """Install a Product-MACed activation bound to a Backend active receipt."""
    if os.geteuid() != 0 or os.getpid() == 1:
        raise ValueError("private container-exec root context is required")
    _verify_pid1_entrypoint()
    environ = _pid1_environment()
    if (environ.get(MODE_ENV) != "1" or not environ.get(WORKSPACE_ENV)
            or not environ.get(SECRET_ENV)):
        raise ValueError("PID 1 was not born with prebind qualification enabled")
    key = base64.urlsafe_b64decode(environ[SECRET_ENV] + "=" * (-len(environ[SECRET_ENV]) % 4))
    if len(key) < 32:
        raise ValueError("Product runner signing key is invalid")
    state_info = os.lstat(STATE)
    if (not stat.S_ISDIR(state_info.st_mode) or state_info.st_uid != 0
            or stat.S_IMODE(state_info.st_mode) != 0o700):
        raise ValueError("private state volume is invalid")
    lifetime = os.open(STATE / ".runner-lifetime.lock", os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            fcntl.flock(lifetime, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(lifetime, fcntl.LOCK_UN)
            raise ValueError("Product runner lifetime lock is not held")
    finally:
        os.close(lifetime)
    admission = os.open(STATE / ".runner-admission.lock", os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(admission, fcntl.LOCK_EX)
        descriptor_path = CONTROL / "instance.json"
        descriptor = _json(_read(descriptor_path, uid=0, gid=10006, mode=0o640, limit=4096))
        instance_id = descriptor.get("runner_instance_id")
        instances = STATE / "instances"
        instance_path = instances / f"{instance_id}.json"
        instance_bytes = _read(instance_path, uid=0, gid=0, mode=0o600, limit=4096)
        instance = _json(instance_bytes)
        if canonical_json(descriptor) != canonical_json(instance):
            raise ValueError("control descriptor differs from current state instance")
        validate_instance(instance, key=key)
        if instance.get("workspace_id") != environ[WORKSPACE_ENV]:
            raise ValueError("current runner workspace differs from PID 1")
        if os.path.lexists(instances / f"{instance_id}.started.json"):
            raise ValueError("runner has already crossed START admission")
        birth = _json(_read(instances / f"{instance_id}.birth-mode.json",
                            uid=0, gid=0, mode=0o600, limit=4096))
        validate_birth_mode(birth, key=key, instance=instance)
        if birth["require_prebind"] is not True:
            raise ValueError("runner birth mode is not qualified")
        install_path = instances / f"{instance_id}.prebind-install.json"
        install_bytes = _read(install_path, uid=0, gid=0, mode=0o600)
        install_record = _json(install_bytes)
        if canonical_json(install_record) != install_bytes:
            raise ValueError("installed prebind encoding is not canonical")
        validate_install_record(install_record, key=key, instance=instance,
                                birth_mode=birth)
        prepared = validate_prepared_receipt(install_record["prepared_receipt"],
                                             instance=instance)
        backend_receipt_bytes = _read(receipt_path, uid=0, gid=0, mode=0o600)
        backend_receipt = _json(backend_receipt_bytes)
        if canonical_json(backend_receipt) != backend_receipt_bytes:
            raise ValueError("Backend activation receipt encoding is not canonical")
        backend_receipt = validate_backend_active_receipt(
            backend_receipt, prepared_receipt=prepared, install_record=install_record,
        )
        record = sign_activation_record({
            "schema_version": ACTIVATION_SCHEMA,
            "status": "active",
            "authorizes_start": True,
            "workspace_id": instance["workspace_id"],
            "runner_instance_id": instance_id,
            "runner_boot_id": instance["runner_boot_id"],
            "state_generation": instance["state_generation"],
            "signed_instance_sha256": digest(instance),
            "prepared_receipt_sha256": prepared["receipt_sha256"],
            "backend_binding_nonce": prepared["backend_binding_nonce"],
            "install_receipt_sha256": digest(install_record),
            "backend_receipt": backend_receipt,
        }, key=key)
        validate_activation_record(record, key=key, instance=instance,
                                   birth_mode=birth, prepared_receipt=prepared,
                                   install_record=install_record)
        activation_path = instances / f"{instance_id}.activation.json"
        if os.path.lexists(activation_path):
            existing_bytes = _read(activation_path, uid=0, gid=0, mode=0o600)
            existing = _json(existing_bytes)
            validate_activation_record(existing, key=key, instance=instance,
                                       birth_mode=birth, prepared_receipt=prepared,
                                       install_record=install_record)
            if (canonical_json(existing) != existing_bytes
                    or canonical_json(existing) != canonical_json(record)):
                raise ValueError("a different activation is already installed")
            _sync_exact_record(activation_path, existing_bytes, uid=0, gid=0,
                               mode=0o600)
            return
        expected_bytes, identity = _persist_immutable(activation_path, record, gid=0)
        readback_bytes = _read(activation_path, uid=0, gid=0, mode=0o600)
        readback = _json(readback_bytes)
        validate_activation_record(readback, key=key, instance=instance,
                                   birth_mode=birth, prepared_receipt=prepared,
                                   install_record=install_record)
        if canonical_json(readback) != canonical_json(record) or readback_bytes != expected_bytes:
            raise ValueError("installed activation readback differs")
        _sync_exact_record(activation_path, expected_bytes, uid=0, gid=0,
                           mode=0o600, identity=identity)
    finally:
        fcntl.flock(admission, fcntl.LOCK_UN)
        os.close(admission)


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 3 or argv[1] not in {"install", "activate"}:
            raise ValueError("private install or activate command required")
        if argv[1] == "install":
            install(Path(argv[2]))
        else:
            activate(Path(argv[2]))
        return 0
    except (OSError, ValueError, KeyError, TypeError, PrebindContractError):
        print("Product runner prebind installation refused", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
