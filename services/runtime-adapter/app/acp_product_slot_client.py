"""Authenticated transport client for Product ACP execution slots.

The process that owns an ACP child lives behind a dedicated Unix socket. This
module only relays ACP bytes and keeps a process-local workspace lease until
both the runner proves cleanup and Backend acknowledges the exact root.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from packages.contracts.acp_product_slot import (
    PRODUCT_CLEANUP_RECEIPT_DIRECTORY,
    PRODUCT_CLEANUP_RECEIPT_MAX_BYTES,
    PRODUCT_SCOPE_KEYS,
    product_scope_digest,
    validate_product_environment,
    validate_product_scope,
    verify_product_cleanup_receipt,
)
from packages.contracts.acp_product_instance import (
    canonical_json as canonical_instance_json,
    validate_instance,
)

from . import research_judgment_acp_runner_client as wire


PRODUCT_BINDINGS_ENV = "BYQ_ACP_PRODUCT_SLOT_BINDINGS"
PRODUCT_SECRET_ENV_PREFIX = "BYQ_ACP_PRODUCT_SLOT_"
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")
_TEXT = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_CWD_LEAF = re.compile(r"(?:session|root)-[0-9a-f]{32}\Z")
_PROTOCOL_VERSION = wire.PROTOCOL_VERSION
MAX_GUARD_BYTES = 16_384
_PRODUCT_REJECT_CODES = frozenset({
    "workspace_mismatch", "environment_rejected", "scope_consumed",
    "state_unavailable", "deadline_expired", "runner_process_fence_unverified",
    "launch_failed", "child_isolation_unverified",
    "operator_binding_invalid", "prebind_activation_unavailable", "prebind_not_enabled",
})
_PRE_LAUNCH_REJECT_CODES = frozenset({
    "workspace_mismatch", "environment_rejected", "deadline_expired",
    "operator_binding_invalid", "prebind_activation_unavailable", "prebind_not_enabled",
})
_INSTANCE_MAX_BYTES = 16 * 1024
_RUNNER_CONTROL_UID = 0
_RUNNER_CONTROL_GID = 10006
_RUNNER_CONTROL_DIRECTORY_MODE = 0o710
_RUNNER_INSTANCE_MODE = 0o640
_CONTROL_ENV_DENY = frozenset({
    PRODUCT_BINDINGS_ENV,
    wire.RUNNER_SOCKET_ENV,
    wire.RUNNER_SECRET_ENV,
})


class ProductSlotError(RuntimeError):
    """A sanitized Product slot error safe to return through the adapter."""


class ProductSlotBusy(ProductSlotError):
    """The workspace already has an unreconciled root lease."""


class ProductSlotUnavailable(ProductSlotError):
    """The configured workspace slot cannot accept a request."""


class ProductSlotUnknown(ProductSlotError):
    """A dispatched request has no authenticated cleanup proof."""


class ProductSlotRejected(ProductSlotError):
    """The authenticated runner rejected START before launching a process."""

    def __init__(self, code: str, retirement_receipt: "ProductSlotPrebindRetirement | None" = None):
        super().__init__("Product ACP runner rejected the request")
        self.code = code
        self.retirement_receipt = retirement_receipt


class ProductSlotLeaseMismatch(ProductSlotError):
    """An ACK or cleanup receipt did not identify the held root exactly."""


class ProductSlotPrebindNoStart(ProductSlotError):
    """Qualified pre-START work failed before any durable v2 write or START."""

    def __init__(self, message: str, retirement_receipt: "ProductSlotPrebindRetirement"):
        super().__init__(message)
        self.retirement_receipt = retirement_receipt


class ProductSlotPrebindUncertain(ProductSlotError):
    """Qualified pre-START persistence or retirement has an uncertain outcome."""


@dataclass(frozen=True)
class ProductSlotPrebindRetirement:
    """Exact in-process proof that Runtime retired the pre-START fence."""

    scope_digest: str
    root_run_id: str
    base_binding_sha256: str
    prepared_guard_sha256: str
    retired_binding_sha256: str | None
    disposition: str


def read_product_cleanup_receipt_with_sha256(
    control_directory: str | os.PathLike[str], control_key: bytes,
    expected_scope: Mapping[str, str],
) -> tuple[dict[str, object], str]:
    """Read one exact signed receipt and return its source-file digest."""

    scope = validate_product_scope(expected_scope)
    directory = Path(control_directory)
    receipt_dir = directory / PRODUCT_CLEANUP_RECEIPT_DIRECTORY
    for candidate in (directory, receipt_dir):
        try:
            info = os.lstat(candidate)
        except OSError as exc:
            raise ProductSlotLeaseMismatch("Product cleanup receipt is unavailable") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise ProductSlotLeaseMismatch("Product cleanup receipt directory is unsafe")

    path = receipt_dir / f"{product_scope_digest(scope)}.json"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = os.lstat(path)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > PRODUCT_CLEANUP_RECEIPT_MAX_BYTES):
            raise ProductSlotLeaseMismatch("Product cleanup receipt file is unsafe")
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_size > PRODUCT_CLEANUP_RECEIPT_MAX_BYTES):
                raise ProductSlotLeaseMismatch("Product cleanup receipt changed while opening")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                raw = source.read(PRODUCT_CLEANUP_RECEIPT_MAX_BYTES + 1)
        finally:
            os.close(descriptor)
    except ProductSlotLeaseMismatch:
        raise
    except OSError as exc:
        raise ProductSlotLeaseMismatch("Product cleanup receipt is unavailable") from exc
    try:
        receipt = verify_product_cleanup_receipt(
            raw, control_key=control_key, expected_scope=scope,
        )
    except ValueError as exc:
        raise ProductSlotLeaseMismatch("Product cleanup receipt did not verify") from exc
    return receipt, hashlib.sha256(raw).hexdigest()


def read_product_cleanup_receipt(
    control_directory: str | os.PathLike[str], control_key: bytes,
    expected_scope: Mapping[str, str],
) -> dict[str, object]:
    """Read one exact signed cleanup receipt from the private runner volume."""

    receipt, _digest = read_product_cleanup_receipt_with_sha256(
        control_directory, control_key, expected_scope,
    )
    return receipt


@dataclass(frozen=True)
class ProductSlotBinding:
    workspace_id: str
    socket_path: str
    control_secret_env: str
    require_prebind: bool = False


@dataclass(frozen=True)
class _ResolvedBinding:
    public: ProductSlotBinding
    secret: bytes = field(repr=False)


@dataclass
class _Lease:
    digest: str
    scope: dict[str, str]
    cleanup_proven: bool = False
    backend_acknowledged: bool = False
    fence_operation_id: str | None = None
    fence_request_sha256: str | None = None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Product ACP slot bindings contain duplicate fields")
        value[key] = item
    return value


def _parse_bindings(raw: str) -> dict[str, dict[str, str | bool]]:
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Product ACP slot bindings are invalid") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError("Product ACP slot bindings are invalid")
    bindings: dict[str, dict[str, str | bool]] = {}
    socket_paths: set[str] = set()
    secret_names: set[str] = set()
    for workspace_id, item in value.items():
        if not isinstance(workspace_id, str) or _TEXT.fullmatch(workspace_id) is None:
            raise ValueError("Product ACP workspace binding is invalid")
        if (not isinstance(item, dict)
                or set(item) not in (
                    {"socket_path", "control_secret_env"},
                    {"socket_path", "control_secret_env", "require_prebind"},
                )):
            raise ValueError("Product ACP workspace binding is invalid")
        socket_path = item.get("socket_path")
        secret_env = item.get("control_secret_env")
        require_prebind = item.get("require_prebind", False)
        if (
            not isinstance(socket_path, str) or not socket_path.startswith("/")
            or "\0" in socket_path or len(socket_path.encode("utf-8")) >= 104
            or not isinstance(secret_env, str) or _ENV_NAME.fullmatch(secret_env) is None
            or secret_env in _CONTROL_ENV_DENY
            or not secret_env.startswith(PRODUCT_SECRET_ENV_PREFIX)
            or type(require_prebind) is not bool
        ):
            raise ValueError("Product ACP workspace binding is invalid")
        if socket_path in socket_paths or secret_env in secret_names:
            raise ValueError("Product ACP slot bindings must be distinct per workspace")
        socket_paths.add(socket_path)
        secret_names.add(secret_env)
        bindings[workspace_id] = {
            "socket_path": socket_path,
            "control_secret_env": secret_env,
            "require_prebind": require_prebind,
        }
    return bindings


class ProductSlotRegistry:
    """Process-local, single-slot-per-workspace lease registry.

    This registry is intended to be a singleton inside the Runtime Adapter.
    It is not a durable scheduler: a lease can be released only by the exact
    root's cleanup proof and Backend terminal acknowledgement.
    """

    def __init__(
        self,
        bindings_json: str | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        judgment_socket_path: str | None = None,
        judgment_control_secret: str | bytes | None = None,
    ) -> None:
        env = os.environ if environ is None else environ
        raw = env.get(PRODUCT_BINDINGS_ENV) if bindings_json is None else bindings_json
        if not isinstance(raw, str) or not raw:
            raise ValueError("Product ACP slot bindings are unavailable")
        parsed = _parse_bindings(raw)
        if judgment_socket_path is None:
            judgment_socket_path = env.get(
                wire.RUNNER_SOCKET_ENV, wire.DEFAULT_RUNNER_SOCKET_PATH,
            )
        if not isinstance(judgment_socket_path, str) or not judgment_socket_path.startswith("/"):
            raise ValueError("ACP judgment runner binding is invalid")
        if judgment_control_secret is None:
            judgment_control_secret = env.get(wire.RUNNER_SECRET_ENV)
        if isinstance(judgment_control_secret, str) and judgment_control_secret:
            judgment_secret = wire.decode_control_secret(judgment_control_secret)
        elif isinstance(judgment_control_secret, bytes) and len(judgment_control_secret) >= 32:
            judgment_secret = judgment_control_secret
        else:
            judgment_secret = None

        resolved: dict[str, _ResolvedBinding] = {}
        seen_secrets: list[bytes] = []
        for workspace_id, item in parsed.items():
            if item["socket_path"] == judgment_socket_path:
                raise ValueError("Product and judgment ACP sockets must be distinct")
            encoded = env.get(item["control_secret_env"])
            try:
                secret = wire.decode_control_secret(encoded or "")
            except ValueError as exc:
                raise ValueError("Product ACP slot control secret is unavailable") from exc
            if judgment_secret is not None and hmac.compare_digest(secret, judgment_secret):
                raise ValueError("Product and judgment ACP control secrets must be distinct")
            if any(hmac.compare_digest(secret, old) for old in seen_secrets):
                raise ValueError("Product ACP control secrets must be distinct per workspace")
            seen_secrets.append(secret)
            public = ProductSlotBinding(
                workspace_id=workspace_id,
                socket_path=str(item["socket_path"]),
                control_secret_env=str(item["control_secret_env"]),
                require_prebind=bool(item["require_prebind"]),
            )
            resolved[workspace_id] = _ResolvedBinding(public, secret)
        self._bindings = resolved
        self._leases: dict[str, _Lease] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls, *, environ: Mapping[str, str] | None = None) -> "ProductSlotRegistry":
        """Build the static slot registry from the Adapter environment."""
        env = os.environ if environ is None else environ
        return cls(environ=env)

    def configured_workspaces(self) -> tuple[str, ...]:
        """Return the statically configured resource-group identities."""
        with self._lock:
            return tuple(sorted(self._bindings))

    def requires_prebind(self, workspace_id: str) -> bool:
        """Return the trusted static qualified-start mode for one workspace."""
        return self.assert_workspace(workspace_id).require_prebind

    def operations_counts(self) -> dict[str, int | str]:
        """Return anonymous process-local lease counts for operations views."""
        with self._lock:
            leases = tuple(self._leases.values())
            return {
                "configured": len(self._bindings),
                "held": len(leases),
                "awaiting_backend_ack": sum(
                    not lease.backend_acknowledged for lease in leases
                ),
                "awaiting_cleanup": sum(
                    not lease.cleanup_proven for lease in leases
                ),
                "scope": "adapter_process_lifetime",
                "source": "live_product_slot_registry",
            }

    def assert_workspace(self, workspace_id: str) -> ProductSlotBinding:
        """Return the configured public binding or a sanitized error."""
        with self._lock:
            binding = self._bindings.get(workspace_id)
            if binding is None:
                raise ProductSlotUnavailable("No Product ACP slot is configured for this workspace")
            return binding.public

    def get_available_binding(self, workspace_id: str) -> ProductSlotBinding:
        """Return a binding only when its workspace has no unresolved root."""
        with self._lock:
            binding = self._bindings.get(workspace_id)
            if binding is None:
                raise ProductSlotUnavailable("No Product ACP slot is configured for this workspace")
            if workspace_id in self._leases:
                raise ProductSlotBusy("Product ACP workspace slot is busy")
            return binding.public

    def owns(self, scope: Mapping[str, object]) -> bool:
        """Return whether this exact scope currently owns its workspace fence."""
        checked_scope, digest = _checked_scope(scope)
        with self._lock:
            lease = self._leases.get(checked_scope["workspace_id"])
            return lease is not None and hmac.compare_digest(lease.digest, digest)

    def reserve(self, scope: Mapping[str, object]) -> None:
        checked_scope, digest = _checked_scope(scope)
        workspace_id = checked_scope["workspace_id"]
        with self._lock:
            if workspace_id not in self._bindings:
                raise ProductSlotUnavailable("No Product ACP slot is configured for this workspace")
            if workspace_id in self._leases:
                raise ProductSlotBusy("Product ACP workspace slot is busy")
            self._leases[workspace_id] = _Lease(digest, checked_scope)

    def reserve_operator_fence(
        self, scope: Mapping[str, object], *, operation_id: str, request_sha256: str,
        allow_existing_live_lease: bool = False,
    ) -> None:
        """Reserve or retry only the same current-process cleanup operation."""
        checked_scope, digest = _checked_scope(scope)
        if (not isinstance(operation_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None
                or not isinstance(request_sha256, str)
                or _HEX64.fullmatch(request_sha256) is None):
            raise ProductSlotLeaseMismatch("operator fence reservation identity is invalid")
        workspace_id = checked_scope["workspace_id"]
        with self._lock:
            if workspace_id not in self._bindings:
                raise ProductSlotUnavailable("No Product ACP slot is configured for this workspace")
            lease = self._leases.get(workspace_id)
            if lease is None:
                self._leases[workspace_id] = _Lease(
                    digest, checked_scope, fence_operation_id=operation_id,
                    fence_request_sha256=request_sha256)
            elif (allow_existing_live_lease is True
                  and hmac.compare_digest(lease.digest, digest)
                  and lease.fence_operation_id is None
                  and lease.fence_request_sha256 is None
                  and not lease.backend_acknowledged and not lease.cleanup_proven):
                lease.fence_operation_id = operation_id
                lease.fence_request_sha256 = request_sha256
            elif (not hmac.compare_digest(lease.digest, digest)
                  or lease.fence_operation_id != operation_id
                  or lease.fence_request_sha256 != request_sha256
                  or lease.backend_acknowledged or lease.cleanup_proven):
                raise ProductSlotBusy("Product ACP workspace slot is busy")

    def acknowledge(self, scope: Mapping[str, object]) -> None:
        """Record a Backend ACK for the exact root and release if cleanup is proven."""
        checked_scope, digest = _checked_scope(scope)
        with self._lock:
            lease = self._matching_lease(checked_scope["workspace_id"], digest)
            lease.backend_acknowledged = True
            self._release_if_complete(checked_scope["workspace_id"], lease)

    def cleanup(self, scope: Mapping[str, object], receipt: wire.RunnerExit) -> None:
        """Record signed cleanup for the exact root and release if Backend ACKed."""
        checked_scope, digest = _checked_scope(scope)
        if not isinstance(receipt, wire.RunnerExit) or receipt.cleanup not in {"proven", "unknown"}:
            raise ProductSlotUnknown("Product ACP cleanup proof is invalid")
        with self._lock:
            lease = self._matching_lease(checked_scope["workspace_id"], digest)
            if receipt.cleanup != "proven":
                raise ProductSlotUnknown("Product ACP cleanup remains unknown")
            lease.cleanup_proven = True
            self._release_if_complete(checked_scope["workspace_id"], lease)

    def release_operator_fence(
        self, scope: Mapping[str, object], *, persist_observation: Callable[[], None],
        operation_id: str | None = None,
    ) -> bool:
        """Persist one operator-fence observation before releasing its exact lease.

        The callback is deliberately scoped to this one operation: retaining the
        registry lock across the durable Runtime binding write prevents another
        cleanup or reservation from changing the workspace lease between the
        exact-scope check and release. It is not a general lease transaction API.
        """
        checked_scope, digest = _checked_scope(scope)
        if not callable(persist_observation):
            raise ProductSlotLeaseMismatch("operator fence persistence is unavailable")
        if operation_id is not None and (not isinstance(operation_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None):
            raise ProductSlotLeaseMismatch("operator fence operation identity is invalid")
        with self._lock:
            lease = self._leases.get(checked_scope["workspace_id"])
            if lease is None:
                return False
            if not hmac.compare_digest(lease.digest, digest):
                raise ProductSlotLeaseMismatch(
                    "operator fence does not match the active workspace lease")
            if operation_id is not None and lease.fence_operation_id != operation_id:
                raise ProductSlotLeaseMismatch(
                    "operator fence lease belongs to another operation")
            persist_observation()
            if self._leases.get(checked_scope["workspace_id"]) is not lease:
                raise ProductSlotLeaseMismatch(
                    "operator fence lease changed before release")
            del self._leases[checked_scope["workspace_id"]]
            return True

    def verify_local_validation_cleanup(
        self, scope: Mapping[str, object],
    ) -> tuple[dict[str, object], str]:
        """Verify the existing signed cleanup receipt for one exact local Root."""
        checked_scope, _digest = _checked_scope(scope)
        with self._lock:
            binding = self._bindings.get(checked_scope["workspace_id"])
            if binding is None:
                raise ProductSlotUnavailable("No Product ACP slot is configured for this workspace")
            control_key = binding.secret
        return read_product_cleanup_receipt_with_sha256(
            Path(binding.public.socket_path).parent, control_key, checked_scope,
        )

    def release_local_validation_ack(
        self, scope: Mapping[str, object], *, cleanup_receipt_sha256: str,
        persist_observation: Callable[[], None],
        operation_id: str | None = None, request_sha256: str | None = None,
    ) -> bool:
        """Persist one local ACK observation before deleting only its exact lease."""
        checked_scope, digest = _checked_scope(scope)
        if not callable(persist_observation):
            raise ProductSlotLeaseMismatch("local validation ACK persistence is unavailable")
        if ((operation_id is None) != (request_sha256 is None)
                or (operation_id is not None and (not isinstance(operation_id, str)
                    or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None
                    or not isinstance(request_sha256, str) or _HEX64.fullmatch(request_sha256) is None))):
            raise ProductSlotLeaseMismatch("local validation ACK operation identity is invalid")
        with self._lock:
            lease = self._leases.get(checked_scope["workspace_id"])
            if lease is None:
                return False
            if not hmac.compare_digest(lease.digest, digest):
                raise ProductSlotLeaseMismatch("local validation ACK does not match the active lease")
            if lease.scope != checked_scope:
                raise ProductSlotLeaseMismatch("local validation lease scope changed")
            if (operation_id is not None
                    and (lease.fence_operation_id != operation_id
                         or lease.fence_request_sha256 != request_sha256)):
                raise ProductSlotLeaseMismatch("local validation lease belongs to another operation")
            if operation_id is None and lease.cleanup_proven is not True:
                raise ProductSlotLeaseMismatch("local validation lease lacks exact proven cleanup")
            binding = self._bindings.get(checked_scope["workspace_id"])
            if binding is None:
                raise ProductSlotUnavailable("No Product ACP slot is configured for this workspace")
            cleanup, raw_sha256 = read_product_cleanup_receipt_with_sha256(
                Path(binding.public.socket_path).parent, binding.secret, checked_scope,
            )
            if (cleanup.get("cleanup") != "proven"
                    or not isinstance(cleanup_receipt_sha256, str)
                    or not hmac.compare_digest(raw_sha256, cleanup_receipt_sha256)):
                raise ProductSlotLeaseMismatch("local validation signed cleanup changed before release")
            if operation_id is not None:
                lease.cleanup_proven = True
            persist_observation()
            if self._leases.get(checked_scope["workspace_id"]) is not lease:
                raise ProductSlotLeaseMismatch("local validation ACK lease changed before release")
            del self._leases[checked_scope["workspace_id"]]
            return True

    def _resolved(self, workspace_id: str) -> _ResolvedBinding:
        with self._lock:
            binding = self._bindings.get(workspace_id)
            if binding is None:
                raise ProductSlotUnavailable("No Product ACP slot is configured for this workspace")
            return binding

    def _abandon_before_dispatch(self, scope: Mapping[str, object]) -> None:
        """Release a lease only when the client has not sent START bytes."""
        checked_scope, digest = _checked_scope(scope)
        with self._lock:
            lease = self._matching_lease(checked_scope["workspace_id"], digest)
            del self._leases[checked_scope["workspace_id"]]

    def _reject_without_launch(self, scope: Mapping[str, object]) -> None:
        """Release after a correctly authenticated runner REJECT response."""
        self._abandon_before_dispatch(scope)

    def _matching_lease(self, workspace_id: str, digest: str) -> _Lease:
        lease = self._leases.get(workspace_id)
        if lease is None or not hmac.compare_digest(lease.digest, digest):
            raise ProductSlotLeaseMismatch("Product ACP receipt does not match the active root")
        return lease

    def _release_if_complete(self, workspace_id: str, lease: _Lease) -> None:
        if lease.cleanup_proven and lease.backend_acknowledged:
            if self._leases.get(workspace_id) is lease:
                del self._leases[workspace_id]


def _checked_scope(scope: Mapping[str, object]) -> tuple[dict[str, str], str]:
    if not isinstance(scope, Mapping):
        raise ValueError("Product ACP scope is invalid")
    try:
        value = validate_product_scope(dict(scope))
        digest = product_scope_digest(value)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Product ACP scope is invalid") from exc
    if set(value) != set(PRODUCT_SCOPE_KEYS) or _HEX64.fullmatch(digest) is None:
        raise ValueError("Product ACP scope is invalid")
    return dict(value), digest


def _checked_environment(
    env: Mapping[str, str], scope: Mapping[str, str], secret_env: str,
) -> dict[str, str]:
    try:
        result = validate_product_environment(env, scope)
    except (TypeError, ValueError) as exc:
        raise ValueError("Product ACP environment is invalid") from exc
    if (
        secret_env in result
        or any(key in _CONTROL_ENV_DENY for key in result)
        or any(key.startswith(PRODUCT_SECRET_ENV_PREFIX) for key in result)
    ):
        raise ValueError("Product ACP environment is invalid")
    return result


class ProductRunnerClient:
    """Start one Product ACP process through its workspace-bound slot."""

    def __init__(
        self,
        registry: ProductSlotRegistry,
        *,
        connect_timeout_s: float = 5.0,
        cleanup_timeout_s: float = 5.0,
        socket_factory: Any = socket.socket,
    ) -> None:
        if connect_timeout_s <= 0 or cleanup_timeout_s <= 0:
            raise ValueError("Product ACP timeout is invalid")
        self.registry = registry
        self._connect_timeout_s = connect_timeout_s
        self._cleanup_timeout_s = cleanup_timeout_s
        self._socket_factory = socket_factory

    def start(
        self,
        scope: Mapping[str, object],
        env: Mapping[str, str],
        deadline_at_ms: int | None,
        expected_cwd: str,
        guard_b64: str | None = None,
        prepare_start: Callable[[Mapping[str, str], str, Callable[[], Mapping[str, object]]],
                                Mapping[str, object]] | None = None,
        prelaunch_reject: Callable[[Mapping[str, str], str,
                                    Mapping[str, object]],
                                   ProductSlotPrebindRetirement] | None = None,
    ) -> wire.RunnerSession:
        """Reserve before connect, send one signed START, and return ACP relay."""
        checked_scope, digest = _checked_scope(scope)
        workspace_id = checked_scope["workspace_id"]
        binding = self.registry._resolved(workspace_id)
        if binding.public.require_prebind and (prepare_start is None or prelaunch_reject is None):
            raise ProductSlotUnavailable("qualified Product ACP start is unavailable")
        checked_env = _checked_environment(env, checked_scope, binding.public.control_secret_env)
        cwd_leaf = checked_scope["cwd_leaf"]
        if (deadline_at_ms is not None
                and (type(deadline_at_ms) is not int
                     or deadline_at_ms <= int(time.time() * 1000))):
            raise ValueError("Product ACP start boundary is invalid")
        if (deadline_at_ms is None and guard_b64 is None
                or not isinstance(expected_cwd, str) or not expected_cwd.startswith("/")
                or "\0" in expected_cwd or Path(expected_cwd).name != cwd_leaf):
            raise ValueError("Product ACP start boundary is invalid")

        self.registry.reserve(checked_scope)
        dispatched = False
        sock: socket.socket | None = None
        operator_binding: Mapping[str, object] | None = None
        try:
            if binding.public.require_prebind:
                try:
                    assert prepare_start is not None
                    operator_binding = prepare_start(
                        checked_scope, expected_cwd,
                        lambda: self._read_current_instance(binding),
                    )
                except ProductSlotPrebindNoStart as exc:
                    try:
                        _validate_prebind_retirement(
                            exc.retirement_receipt, checked_scope, digest,
                        )
                        self.registry._abandon_before_dispatch(checked_scope)
                    except BaseException as retirement_error:
                        raise ProductSlotPrebindUncertain(
                            "qualified Product ACP start requires reconciliation"
                        ) from retirement_error
                    raise
                except ProductSlotPrebindUncertain:
                    raise
                except BaseException as exc:
                    raise ProductSlotPrebindUncertain(
                        "qualified Product ACP start requires reconciliation"
                    ) from exc
                if (not isinstance(operator_binding, Mapping)
                        or set(operator_binding) != {
                            "schema_version", "runner_instance_id", "runner_boot_id",
                            "state_generation", "signed_instance_sha256",
                            "prepared_receipt_sha256", "backend_binding_nonce",
                            "install_receipt_sha256", "backend_activation_id",
                            "backend_activation_receipt_sha256",
                        }):
                    raise ProductSlotPrebindUncertain(
                        "qualified Product ACP start requires reconciliation")
            remaining_s = (None if deadline_at_ms is None else
                           (deadline_at_ms - int(time.time() * 1000)) / 1000.0)
            if remaining_s is not None and remaining_s <= 0:
                if operator_binding is None:
                    self.registry._abandon_before_dispatch(checked_scope)
                else:
                    raise ProductSlotPrebindUncertain(
                        "qualified Product ACP start requires reconciliation")
                raise ProductSlotUnavailable("Product ACP start deadline expired")
            sock = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout_s if remaining_s is None else
                             min(self._connect_timeout_s, remaining_s))
            sock.connect(binding.public.socket_path)

            challenge_value = wire._read_json_frame(sock, wire.CHALLENGE)
            challenge_unsigned = wire._verify_reply(
                challenge_value, binding.secret, wire._CHALLENGE_KEYS,
            )
            challenge = challenge_unsigned.get("challenge")
            if (
                challenge_unsigned.get("v") != _PROTOCOL_VERSION
                or not isinstance(challenge, str) or _HEX64.fullmatch(challenge) is None
            ):
                raise wire.RunnerCleanupUnknown("Product ACP challenge is invalid")

            remaining_s = (None if deadline_at_ms is None else
                           (deadline_at_ms - int(time.time() * 1000)) / 1000.0)
            if remaining_s is not None and remaining_s <= 0:
                if operator_binding is None:
                    self.registry._abandon_before_dispatch(checked_scope)
                else:
                    raise ProductSlotPrebindUncertain(
                        "qualified Product ACP start requires reconciliation")
                raise ProductSlotUnavailable("Product ACP start deadline expired")
            sock.settimeout(self._connect_timeout_s if remaining_s is None else
                             min(self._connect_timeout_s, remaining_s))

            nonce = os.urandom(32).hex()
            unsigned_start: dict[str, object] = {
                "v": _PROTOCOL_VERSION,
                "challenge": challenge,
                "nonce": nonce,
                "scope": checked_scope,
                "env": checked_env,
                "deadline_at_ms": deadline_at_ms,
            }
            if guard_b64 is not None:
                if (not isinstance(guard_b64, str) or len(guard_b64) > ((MAX_GUARD_BYTES + 2) // 3) * 4):
                    raise ValueError("Product ACP continuation guard is invalid")
                unsigned_start["guard_b64"] = guard_b64
            if operator_binding is not None:
                unsigned_start["operator_binding"] = dict(operator_binding)
            signed_start = {
                **unsigned_start,
                "mac": wire.sign_runner_start(unsigned_start, binding.secret),
            }
            # Once sendall begins, any partial write makes launch status ambiguous.
            dispatched = True
            wire._send_json(sock, wire.START, signed_start)
            frame_type, payload = wire._read_frame(sock)
            if frame_type == wire.REJECT and payload:
                rejected = wire._verify_reply(
                    wire._decode_json(payload), binding.secret, wire._REJECT_KEYS,
                )
                self._verify_binding(rejected, challenge, nonce, digest)
                code = rejected.get("code")
                if not isinstance(code, str) or code not in _PRODUCT_REJECT_CODES:
                    raise wire.RunnerCleanupUnknown("Product ACP rejection code is invalid")
                if code in _PRE_LAUNCH_REJECT_CODES:
                    retirement_receipt = None
                    if operator_binding is not None:
                        if prelaunch_reject is None:
                            raise ProductSlotPrebindUncertain(
                                "qualified Product ACP rejection requires reconciliation")
                        try:
                            retirement_receipt = prelaunch_reject(
                                checked_scope, code, operator_binding)
                            _validate_prebind_retirement(
                                retirement_receipt, checked_scope, digest,
                            )
                            self.registry._abandon_before_dispatch(checked_scope)
                        except BaseException as exc:
                            raise ProductSlotPrebindUncertain(
                                "qualified Product ACP rejection requires reconciliation"
                            ) from exc
                    else:
                        self.registry._reject_without_launch(checked_scope)
                    dispatched = False
                    raise ProductSlotRejected(code, retirement_receipt)
                raise ProductSlotUnknown("Product ACP runner rejected an uncertain root")
            if frame_type != wire.READY or not payload:
                raise wire.RunnerCleanupUnknown("Product ACP runner did not send authenticated READY")
            ready = wire._verify_reply(
                wire._decode_json(payload), binding.secret, wire._READY_KEYS,
            )
            self._verify_binding(ready, challenge, nonce, digest)
            cwd = ready.get("cwd")
            if not isinstance(cwd, str) or not cwd.startswith("/") or "\0" in cwd:
                raise wire.RunnerCleanupUnknown("Product ACP runner cwd is invalid")
            sock.settimeout(None)
            session = wire.RunnerSession(
                sock, binding.secret, challenge, nonce, digest, cwd,
                cleanup_timeout_s=self._cleanup_timeout_s,
            )
            sock = None
            if cwd != expected_cwd:
                try:
                    session.cancel()
                    receipt = session.wait_exit(self._cleanup_timeout_s)
                    if receipt.cleanup == "proven":
                        self.registry.cleanup(checked_scope, receipt)
                except (wire.RunnerClientError, ProductSlotError) as exc:
                    raise ProductSlotUnknown(
                        "Product ACP runner started outside the requested root"
                    ) from exc
                raise ProductSlotUnavailable("Product ACP runner cwd differs from the requested root")
            return session
        except ProductSlotError:
            raise
        except (OSError, TimeoutError, socket.timeout) as exc:
            if not dispatched:
                if operator_binding is not None:
                    raise ProductSlotPrebindUncertain(
                        "qualified Product ACP start requires reconciliation") from exc
                self.registry._abandon_before_dispatch(checked_scope)
                raise ProductSlotUnavailable("Product ACP slot is unavailable") from exc
            raise ProductSlotUnknown("Product ACP start outcome is unknown") from exc
        except wire.RunnerClientError as exc:
            if not dispatched:
                if operator_binding is not None:
                    raise ProductSlotPrebindUncertain(
                        "qualified Product ACP start requires reconciliation") from exc
                self.registry._abandon_before_dispatch(checked_scope)
                raise ProductSlotUnavailable("Product ACP handshake was rejected") from exc
            raise ProductSlotUnknown("Product ACP start outcome is unknown") from exc
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    @staticmethod
    def _read_current_instance(binding: _ResolvedBinding) -> dict[str, object]:
        """Read the signed descriptor beside the exact configured socket."""
        socket_path = Path(binding.public.socket_path)
        parent_path = socket_path.parent
        descriptor_name = "instance.json"
        dir_fd = -1
        descriptor_fd = -1
        try:
            parent_before = os.lstat(parent_path)
            if (not stat.S_ISDIR(parent_before.st_mode)
                    or parent_before.st_uid != _RUNNER_CONTROL_UID
                    or parent_before.st_gid != _RUNNER_CONTROL_GID
                    or stat.S_IMODE(parent_before.st_mode) != _RUNNER_CONTROL_DIRECTORY_MODE):
                raise ProductSlotUnavailable("Product ACP instance descriptor is unsafe")
            o_path = getattr(os, "O_PATH", None)
            if o_path is None:
                raise ProductSlotUnavailable("Product ACP instance descriptor is unavailable")
            dir_fd = os.open(parent_path, o_path | getattr(os, "O_DIRECTORY", 0)
                             | getattr(os, "O_NOFOLLOW", 0))
            parent_opened = os.fstat(dir_fd)
            if ((parent_opened.st_dev, parent_opened.st_ino)
                    != (parent_before.st_dev, parent_before.st_ino)
                    or parent_opened.st_uid != _RUNNER_CONTROL_UID
                    or parent_opened.st_gid != _RUNNER_CONTROL_GID
                    or stat.S_IMODE(parent_opened.st_mode) != _RUNNER_CONTROL_DIRECTORY_MODE):
                raise ProductSlotUnavailable("Product ACP instance descriptor changed")
            before = os.stat(descriptor_name, dir_fd=dir_fd, follow_symlinks=False)
            mode = stat.S_IMODE(before.st_mode)
            if (not stat.S_ISREG(before.st_mode)
                    or before.st_uid != _RUNNER_CONTROL_UID
                    or before.st_gid != _RUNNER_CONTROL_GID
                    or before.st_nlink != 1 or before.st_size > _INSTANCE_MAX_BYTES
                    or mode != _RUNNER_INSTANCE_MODE):
                raise ProductSlotUnavailable("Product ACP instance descriptor is unsafe")
            descriptor_fd = os.open(descriptor_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                                    dir_fd=dir_fd)
            opened = os.fstat(descriptor_fd)
            if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_uid != _RUNNER_CONTROL_UID
                    or opened.st_gid != _RUNNER_CONTROL_GID
                    or stat.S_IMODE(opened.st_mode) != _RUNNER_INSTANCE_MODE
                    or opened.st_size != before.st_size
                    or opened.st_size > _INSTANCE_MAX_BYTES):
                raise ProductSlotUnavailable("Product ACP instance descriptor changed")
            raw = bytearray()
            while len(raw) <= _INSTANCE_MAX_BYTES:
                chunk = os.read(descriptor_fd, min(4096, _INSTANCE_MAX_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw) != opened.st_size or len(raw) > _INSTANCE_MAX_BYTES:
                raise ProductSlotUnavailable("Product ACP instance descriptor is unsafe")
            after = os.stat(descriptor_name, dir_fd=dir_fd, follow_symlinks=False)
            if ((after.st_dev, after.st_ino, after.st_size, after.st_uid, after.st_gid,
                 stat.S_IMODE(after.st_mode))
                    != (before.st_dev, before.st_ino, before.st_size, before.st_uid,
                        before.st_gid, mode)):
                raise ProductSlotUnavailable("Product ACP instance descriptor changed")
            try:
                value = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_strict_object,
                                   parse_constant=_reject_json_constant)
                instance = validate_instance(value, key=binding.secret)
            except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
                raise ProductSlotUnavailable("Product ACP instance descriptor did not verify") from exc
            if (instance["workspace_id"] != binding.public.workspace_id
                    or canonical_instance_json(instance) != bytes(raw)):
                raise ProductSlotUnavailable("Product ACP instance descriptor is invalid")
            return instance
        except ProductSlotError:
            raise
        except OSError as exc:
            raise ProductSlotUnavailable("Product ACP instance descriptor is unavailable") from exc
        finally:
            if descriptor_fd >= 0:
                os.close(descriptor_fd)
            if dir_fd >= 0:
                os.close(dir_fd)


    @staticmethod
    def _verify_binding(
        reply: Mapping[str, object], challenge: str, nonce: str, digest: str,
    ) -> None:
        if (
            reply.get("v") != _PROTOCOL_VERSION
            or reply.get("challenge") != challenge
            or reply.get("nonce") != nonce
            or reply.get("scope_digest") != digest
        ):
            raise wire.RunnerCleanupUnknown("Product ACP reply belongs to another request")


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _validate_prebind_retirement(
    receipt: ProductSlotPrebindRetirement, scope: Mapping[str, str], digest: str,
) -> None:
    if (not isinstance(receipt, ProductSlotPrebindRetirement)
            or receipt.scope_digest != digest
            or receipt.root_run_id != scope["root_run_id"]
            or _HEX64.fullmatch(receipt.base_binding_sha256) is None
            or _HEX64.fullmatch(receipt.prepared_guard_sha256) is None
            or receipt.disposition not in {"removed", "restored"}
            or (receipt.retired_binding_sha256 is not None
                and _HEX64.fullmatch(receipt.retired_binding_sha256) is None)
            or (receipt.disposition == "removed" and receipt.retired_binding_sha256 is not None)
            or (receipt.disposition == "restored" and receipt.retired_binding_sha256 is None)):
        raise ProductSlotPrebindUncertain(
            "qualified Product ACP retirement proof is invalid")
