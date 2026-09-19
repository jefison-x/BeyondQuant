"""Stable, boot-independent runtime executor identity and monotonic epoch fencing.

ADR-0079 (Runtime Continuity & Session Recovery, R1). The lifecycle-journal
lease MUST NOT depend on host boot identity, process id, hostname or container
id. It is bound to a stable deployment identity plus a monotonic
``executor_epoch`` that only an explicit, audited ownership takeover increments.

Layout (all inside the durable evidence volume):

* ``<evidence-root>/executor-state/executor-epoch.v1.json`` is the authoritative
  volume-owned epoch record. It is written atomically and fsynced.
* ``<evidence-root>/executor-state/executor-epoch.lock`` serializes epoch
  initialization, takeover and fenced writes.

``deployment_id``/``volume_identity``/``runtime_release``/initial
``executor_epoch`` come from the ``runtime-executor.v1`` record of the
deployment-controlled identity file (``BYQ_DSH_RELEASE_IDENTITY``, default
``/opt/byq/releases/deployment.identity.json``). The image file is read-only at
runtime, so the authoritative live epoch is the volume-owned record; the image
record is the initialization floor.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from dataclasses import dataclass


DEPLOYMENT_IDENTITY_SCHEMA = "dsh-deployment-identity.v1"
EXECUTOR_RECORD_KEY = "runtime_executor"
EXECUTOR_RECORD_SCHEMA = "runtime-executor.v1"
EPOCH_STATE_SCHEMA = "byq-executor-epoch.v1"
TAKEOVER_AUDIT_SCHEMA = "byq-executor-takeover.v1"
EXECUTOR_STATE_DIR = "executor-state"
EPOCH_STATE_NAME = "executor-epoch.v1.json"
EPOCH_LOCK_NAME = "executor-epoch.lock"
TAKEOVER_AUDIT_DIR = "takeover-audit"
DEFAULT_RELEASE_IDENTITY = "/opt/byq/releases/deployment.identity.json"
RELEASE_FIELD = "runtime_release"
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_LOCAL_FILESYSTEMS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "overlay", "tmpfs"}
_EPOCH_STATE_KEYS = {
    "schema_version", "deployment_id", "volume_identity", "runtime_release",
    "executor_epoch", "updated_at", "reason",
}
_RECORD_KEYS = {"schema_version", "deployment_id", RELEASE_FIELD, "volume_identity", "executor_epoch"}


class ExecutorIdentityError(ValueError):
    """The stable executor identity or its epoch cannot be resolved; fail closed."""


class ExecutorTakeoverBusy(ExecutorIdentityError):
    """Another explicit takeover currently owns the epoch lock."""


class ExecutorFenced(ExecutorIdentityError):
    """A writer's deployment identity or executor epoch is no longer current."""


@dataclass(frozen=True, slots=True)
class DeploymentExecutor:
    deployment_id: str
    runtime_release: str
    volume_identity: str
    executor_epoch: int


@dataclass(frozen=True, slots=True)
class ExecutorIdentity:
    deployment_id: str
    runtime_release: str
    volume_identity: str
    executor_epoch: int
    state_path: Path
    reason: str


def deployment_identity_path() -> Path:
    return Path(os.environ.get("BYQ_DSH_RELEASE_IDENTITY", DEFAULT_RELEASE_IDENTITY))


def read_boot_id(path: Path | None = None) -> str:
    """Diagnostic-only boot identity; never part of the stable lease."""

    source = Path(path) if path is not None else Path("/proc/sys/kernel/random/boot_id")
    value = source.read_text(encoding="ascii").strip()
    if not value:
        raise ExecutorIdentityError("boot identity is empty")
    return value


def load_deployment_executor(path: Path | None = None) -> DeploymentExecutor:
    """Load the deployment-controlled ``runtime-executor.v1`` record, fail closed."""

    source = Path(path) if path is not None else deployment_identity_path()
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExecutorIdentityError(f"executor deployment identity is unavailable: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExecutorIdentityError("executor deployment identity is not valid JSON") from exc
    if not isinstance(value, dict) or value.get("schema_version") != DEPLOYMENT_IDENTITY_SCHEMA:
        raise ExecutorIdentityError("unexpected deployment identity schema")
    record = value.get(EXECUTOR_RECORD_KEY)
    if (not isinstance(record, dict) or set(record) != _RECORD_KEYS
            or record.get("schema_version") != EXECUTOR_RECORD_SCHEMA):
        raise ExecutorIdentityError("missing or invalid runtime-executor.v1 record")
    deployment_id = record["deployment_id"]
    volume_identity = record["volume_identity"]
    runtime_release = record[RELEASE_FIELD]
    executor_epoch = record["executor_epoch"]
    if not isinstance(deployment_id, str) or _IDENTITY.fullmatch(deployment_id) is None:
        raise ExecutorIdentityError("invalid executor deployment identity")
    if not isinstance(volume_identity, str) or _IDENTITY.fullmatch(volume_identity) is None:
        raise ExecutorIdentityError("invalid executor volume identity")
    if not isinstance(runtime_release, str) or _IDENTITY.fullmatch(runtime_release) is None:
        raise ExecutorIdentityError("invalid executor runtime release")
    if type(executor_epoch) is not int or not 1 <= executor_epoch < 2 ** 63:
        raise ExecutorIdentityError("invalid executor epoch floor")
    return DeploymentExecutor(deployment_id, runtime_release, volume_identity, executor_epoch)


def state_directory(root: Path) -> Path:
    return Path(root) / EXECUTOR_STATE_DIR


def state_path(root: Path) -> Path:
    return state_directory(root) / EPOCH_STATE_NAME


def _lock_path(root: Path) -> Path:
    return state_directory(root) / EPOCH_LOCK_NAME


def _require_local_coherent_filesystem(root: Path) -> None:
    mounts: list[tuple[int, str]] = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        mount = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), before.split()[4])
        resolved = str(Path(root).resolve())
        if resolved == mount or resolved.startswith(mount.rstrip("/") + "/"):
            mounts.append((len(mount), after.split()[0]))
    if not mounts or max(mounts)[1] not in _LOCAL_FILESYSTEMS:
        raise ExecutorIdentityError("executor state requires a local coherent filesystem")


def _atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd, name = tempfile.mkstemp(prefix=".executor-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            os.fsync(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    finally:
        os.close(directory)


def read_epoch_state(root: Path) -> dict | None:
    """Read the volume-owned epoch record; corrupt/malformed fails closed."""

    path = state_path(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ExecutorIdentityError(f"executor epoch state is unreadable: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExecutorIdentityError("executor epoch state is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _EPOCH_STATE_KEYS:
        raise ExecutorIdentityError("executor epoch state has an invalid schema")
    if value["schema_version"] != EPOCH_STATE_SCHEMA:
        raise ExecutorIdentityError("unexpected executor epoch state schema")
    if (not isinstance(value["deployment_id"], str)
            or not isinstance(value["volume_identity"], str)
            or not isinstance(value["runtime_release"], str)
            or not isinstance(value["updated_at"], str)
            or not isinstance(value["reason"], str)):
        raise ExecutorIdentityError("executor epoch state has invalid fields")
    if type(value["executor_epoch"]) is not int or not 1 <= value["executor_epoch"] < 2 ** 63:
        raise ExecutorIdentityError("invalid executor epoch value")
    return value


def _write_epoch_state(root: Path, deployment: DeploymentExecutor, epoch: int, reason: str) -> None:
    _atomic_write(state_path(root), {
        "schema_version": EPOCH_STATE_SCHEMA,
        "deployment_id": deployment.deployment_id,
        "volume_identity": deployment.volume_identity,
        "runtime_release": deployment.runtime_release,
        "executor_epoch": epoch,
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "reason": reason,
    })


@contextlib.contextmanager
def epoch_lock(root: Path, *, exclusive: bool = True, nonblocking: bool = False):
    """Serialize epoch initialization, takeover and fenced journal writes."""

    directory = state_directory(root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = _lock_path(root)
    if lock_path.is_symlink():
        raise ExecutorIdentityError("executor epoch lock cannot be a symlink")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    flags = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (fcntl.LOCK_NB if nonblocking else 0)
    try:
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError as exc:
            raise ExecutorTakeoverBusy("another executor takeover currently owns the epoch lock") from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _journal_envelopes(root: Path) -> list[tuple[Path, str]]:
    envelopes: list[tuple[Path, str]] = []
    for path in sorted(Path(root).glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ExecutorIdentityError(f"lifecycle journal is unreadable: {path}") from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExecutorIdentityError(f"lifecycle journal is not valid JSON: {path}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("schema_version"), str):
            raise ExecutorIdentityError(f"lifecycle journal envelope is invalid: {path}")
        envelopes.append((path, value["schema_version"]))
    return envelopes


def _bootstrap_reason(root: Path) -> str:
    """Return the bootstrap reason, or fail closed when stable journals exist."""

    envelopes = _journal_envelopes(root)
    stable = [path for path, schema in envelopes if schema == "byq-lifecycle-journal.v4"]
    if stable:
        raise ExecutorIdentityError(
            "stable journal identity cannot be proven: executor epoch state is missing; "
            "explicit takeover required")
    return "legacy-journal-migration" if envelopes else "bootstrap"


def _maximum_journal_epoch(root: Path) -> int:
    maximum = 0
    for path, schema in _journal_envelopes(root):
        if schema != "byq-lifecycle-journal.v4":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            epoch = value["state"]["executor_epoch"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ExecutorIdentityError(f"stable journal epoch is unreadable: {path}") from exc
        if type(epoch) is not int or not 1 <= epoch < 2 ** 63:
            raise ExecutorIdentityError(f"stable journal epoch is invalid: {path}")
        maximum = max(maximum, epoch)
    return maximum


def resolve(root: Path, *, deployment: DeploymentExecutor | None = None) -> ExecutorIdentity:
    """Resolve (or first-bootstrap) the authoritative stable executor identity."""

    root = Path(root)
    if root.is_symlink():
        raise ExecutorIdentityError("executor state cannot live behind a symlink")
    _require_local_coherent_filesystem(root)
    deployment = deployment or load_deployment_executor()
    with epoch_lock(root, exclusive=True):
        state = read_epoch_state(root)
        if state is None:
            reason = _bootstrap_reason(root)
            epoch = deployment.executor_epoch
            _write_epoch_state(root, deployment, epoch, reason)
            return ExecutorIdentity(deployment.deployment_id, deployment.runtime_release,
                                    deployment.volume_identity, epoch, state_path(root), reason)
        if (state["deployment_id"] != deployment.deployment_id
                or state["volume_identity"] != deployment.volume_identity):
            raise ExecutorIdentityError("executor epoch state belongs to a different deployment")
        if state["executor_epoch"] < deployment.executor_epoch:
            raise ExecutorIdentityError("executor epoch is below the deployment identity floor")
        return ExecutorIdentity(deployment.deployment_id, deployment.runtime_release,
                                state["volume_identity"], state["executor_epoch"],
                                state_path(root), "existing")


def assert_write_allowed(root: Path, deployment_id: str, executor_epoch: int) -> None:
    """Fail closed unless the authoritative epoch still matches this writer."""

    with epoch_lock(root, exclusive=False):
        state = read_epoch_state(root)
        if state is None:
            raise ExecutorFenced("executor epoch state is missing; writer is fenced")
        if state["deployment_id"] != deployment_id or state["executor_epoch"] != executor_epoch:
            raise ExecutorFenced("executor epoch changed; writer is fenced")


def takeover(
    root: Path, *, reason: str, operator: str | None = None,
    deployment: DeploymentExecutor | None = None,
) -> dict:
    """Explicitly increment the monotonic epoch and write an audit record.

    Normal startup never calls this. Exactly one concurrent takeover wins; the
    loser observes ``ExecutorTakeoverBusy``. The new epoch is always strictly
    greater than the current volume epoch and any epoch recorded in a stable
    journal, so an old-epoch writer can never re-establish ownership.
    """

    if not isinstance(reason, str) or len(reason.strip()) < 8 or len(reason) > 512:
        raise ExecutorIdentityError("executor takeover requires a specific reason")
    if operator is not None and (not isinstance(operator, str) or not 1 <= len(operator) <= 128):
        raise ExecutorIdentityError("invalid executor takeover operator")
    root = Path(root)
    if root.is_symlink():
        raise ExecutorIdentityError("executor state cannot live behind a symlink")
    _require_local_coherent_filesystem(root)
    deployment = deployment or load_deployment_executor()
    with epoch_lock(root, exclusive=True, nonblocking=True):
        state = read_epoch_state(root)
        if state is not None and (state["deployment_id"] != deployment.deployment_id
                                  or state["volume_identity"] != deployment.volume_identity):
            raise ExecutorIdentityError("executor epoch state belongs to a different deployment")
        previous = state["executor_epoch"] if state is not None else 0
        base = max(previous, _maximum_journal_epoch(root), deployment.executor_epoch - 1)
        new_epoch = base + 1
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _write_epoch_state(root, deployment, new_epoch, "explicit-takeover")
        audit = {
            "schema_version": TAKEOVER_AUDIT_SCHEMA,
            "timestamp": timestamp,
            "deployment_id": deployment.deployment_id,
            "volume_identity": deployment.volume_identity,
            "runtime_release": deployment.runtime_release,
            "previous_epoch": previous,
            "executor_epoch": new_epoch,
            "reason": reason.strip(),
            "operator": operator,
            "database_rows_modified": False,
            "production_data_deleted": False,
            "reversible": False,
        }
        directory = state_directory(root) / TAKEOVER_AUDIT_DIR
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        final = directory / f"{timestamp}.{new_epoch}.json"
        _atomic_write(final, audit)
        return {**audit, "audit_path": str(final)}


def lock_token(st_dev: int, st_ino: int, token: str) -> str:
    """Bind the lease to the never-unlinked owner lock object on this volume."""

    return hashlib.sha256(f"{st_dev}:{st_ino}:{token}".encode()).hexdigest()


def lease_identity(identity: ExecutorIdentity, st_dev: int, st_ino: int, token: str) -> str:
    """Boot-independent lease: ``sha256(deployment_id:epoch:lock_token)``."""

    return hashlib.sha256(
        f"{identity.deployment_id}:{identity.executor_epoch}:{lock_token(st_dev, st_ino, token)}".encode()
    ).hexdigest()
