"""Authenticated transport client for Product ACP execution slots.

The process that owns an ACP child lives behind a dedicated Unix socket. This
module only relays ACP bytes and keeps a process-local workspace lease until
both the runner proves cleanup and Backend acknowledges the exact root.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from packages.contracts.acp_product_slot import (
    PRODUCT_SCOPE_KEYS,
    product_scope_digest,
    validate_product_environment,
    validate_product_scope,
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
})
_PRE_LAUNCH_REJECT_CODES = frozenset({
    "workspace_mismatch", "environment_rejected", "deadline_expired",
})
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

    def __init__(self, code: str):
        super().__init__("Product ACP runner rejected the request")
        self.code = code


class ProductSlotLeaseMismatch(ProductSlotError):
    """An ACK or cleanup receipt did not identify the held root exactly."""


@dataclass(frozen=True)
class ProductSlotBinding:
    workspace_id: str
    socket_path: str
    control_secret_env: str


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


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Product ACP slot bindings contain duplicate fields")
        value[key] = item
    return value


def _parse_bindings(raw: str) -> dict[str, dict[str, str]]:
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Product ACP slot bindings are invalid") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError("Product ACP slot bindings are invalid")
    bindings: dict[str, dict[str, str]] = {}
    socket_paths: set[str] = set()
    secret_names: set[str] = set()
    for workspace_id, item in value.items():
        if not isinstance(workspace_id, str) or _TEXT.fullmatch(workspace_id) is None:
            raise ValueError("Product ACP workspace binding is invalid")
        if not isinstance(item, dict) or set(item) != {"socket_path", "control_secret_env"}:
            raise ValueError("Product ACP workspace binding is invalid")
        socket_path = item.get("socket_path")
        secret_env = item.get("control_secret_env")
        if (
            not isinstance(socket_path, str) or not socket_path.startswith("/")
            or "\0" in socket_path or len(socket_path.encode("utf-8")) >= 104
            or not isinstance(secret_env, str) or _ENV_NAME.fullmatch(secret_env) is None
            or secret_env in _CONTROL_ENV_DENY
            or not secret_env.startswith(PRODUCT_SECRET_ENV_PREFIX)
        ):
            raise ValueError("Product ACP workspace binding is invalid")
        if socket_path in socket_paths or secret_env in secret_names:
            raise ValueError("Product ACP slot bindings must be distinct per workspace")
        socket_paths.add(socket_path)
        secret_names.add(secret_env)
        bindings[workspace_id] = {
            "socket_path": socket_path,
            "control_secret_env": secret_env,
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
                socket_path=item["socket_path"],
                control_secret_env=item["control_secret_env"],
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
        deadline_at_ms: int,
        expected_cwd: str,
        guard_b64: str | None = None,
    ) -> wire.RunnerSession:
        """Reserve before connect, send one signed START, and return ACP relay."""
        checked_scope, digest = _checked_scope(scope)
        workspace_id = checked_scope["workspace_id"]
        binding = self.registry._resolved(workspace_id)
        checked_env = _checked_environment(env, checked_scope, binding.public.control_secret_env)
        cwd_leaf = checked_scope["cwd_leaf"]
        if (
            type(deadline_at_ms) is not int or deadline_at_ms <= int(time.time() * 1000)
            or not isinstance(expected_cwd, str) or not expected_cwd.startswith("/")
            or "\0" in expected_cwd or Path(expected_cwd).name != cwd_leaf
        ):
            raise ValueError("Product ACP start boundary is invalid")

        self.registry.reserve(checked_scope)
        dispatched = False
        sock: socket.socket | None = None
        try:
            remaining_s = (deadline_at_ms - int(time.time() * 1000)) / 1000.0
            if remaining_s <= 0:
                self.registry._abandon_before_dispatch(checked_scope)
                raise ProductSlotUnavailable("Product ACP start deadline expired")
            sock = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(min(self._connect_timeout_s, remaining_s))
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

            remaining_s = (deadline_at_ms - int(time.time() * 1000)) / 1000.0
            if remaining_s <= 0:
                self.registry._abandon_before_dispatch(checked_scope)
                raise ProductSlotUnavailable("Product ACP start deadline expired")
            sock.settimeout(min(self._connect_timeout_s, remaining_s))

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
                    self.registry._reject_without_launch(checked_scope)
                    dispatched = False
                    raise ProductSlotRejected(code)
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
                self.registry._abandon_before_dispatch(checked_scope)
                raise ProductSlotUnavailable("Product ACP slot is unavailable") from exc
            raise ProductSlotUnknown("Product ACP start outcome is unknown") from exc
        except wire.RunnerClientError as exc:
            if not dispatched:
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
