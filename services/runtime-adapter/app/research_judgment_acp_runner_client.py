"""Authenticated stdio relay client for the isolated ACP judgment runner.

This module transports ACP bytes only. Cleanup is proven only by a correctly
authenticated EXIT frame; a lost connection, invalid frame, or timeout remains
unknown.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import select
import socket
import stat
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

PROTOCOL_VERSION = 1
DEFAULT_RUNNER_SOCKET_PATH = "/run/byq-acp-runner/control.sock"
RUNNER_SOCKET_ENV = "BYQ_ACP_JUDGMENT_RUNNER_SOCKET"
RUNNER_SECRET_ENV = "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET"
MAX_FRAME_BYTES = 1_048_576
MAX_OVERLAY_BYTES = 16_384
MAX_ENV_BYTES = 64 * 1024

CHALLENGE = 0x01
START = 0x02
STDIN = 0x03
CANCEL = 0x04
READY = 0x81
REJECT = 0x82
STDOUT = 0x83
EXIT = 0x84

_START_PREFIX = b"byq-acp-runner-v1\0"
_REPLY_PREFIX = b"byq-acp-runner-reply-v1\0"
_SCOPE_KEYS = frozenset({
    "task_id", "call_identity", "attempt_binding", "root_run_id",
    "runtime_boot_id", "authority_epoch",
})
_ENV_ALLOWLIST = frozenset({
    "BYQ_MCP_URL", "BYQ_MCP_PRODUCT_URL", "BYQ_MCP_ACP_IDENTITY_MODE",
    "BYQ_MCP_ACP_JUDGMENT_TASK_ID", "BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY",
    "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY", "BYQ_RUNTIME_BOOT_ID",
    "BYQ_OWNER_PRINCIPAL", "BYQ_WORKSPACE_ID", "BYQ_ACTOR_PRINCIPAL",
    "BYQ_TRACE_ID", "BYQ_SESSION_ID", "BYQ_DSH_RUN_ID", "BYQ_ROOT_RUN_ID",
})
_REQUIRED_ENV = _ENV_ALLOWLIST - {"BYQ_MCP_PRODUCT_URL"}
_PROXY_TOKEN_ENVS = frozenset({"DEEPSEEK_API_KEY", "OPENCODE_API_KEY"})
_TEXT = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_URLSAFE_B64 = re.compile(r"[A-Za-z0-9_-]+={0,2}\Z")
_PROXY_TOKEN = re.compile(r"byq-acp-proxy-[A-Za-z0-9_-]{43}\Z")
_CHALLENGE_KEYS = frozenset({"v", "challenge", "mac"})
_READY_KEYS = frozenset({"v", "challenge", "nonce", "scope_digest", "cwd", "mac"})
_REJECT_KEYS = frozenset({"v", "challenge", "nonce", "scope_digest", "code", "mac"})
_EXIT_KEYS = frozenset({
    "v", "challenge", "nonce", "scope_digest", "code", "signal",
    "reason", "cleanup", "mac",
})
_REJECT_CODES = frozenset({
    "scope_consumed", "state_unavailable", "deadline_expired", "launch_failed",
})
_EXIT_REASONS = frozenset({
    "process_exit", "cancelled", "deadline", "protocol_error", "transport_lost",
})


class RunnerClientError(RuntimeError):
    """A fail-closed runner protocol error without secret-bearing details."""


class RunnerCleanupUnknown(RunnerClientError):
    """No authenticated EXIT established process cleanup."""

    cleanup: Literal["unknown"] = "unknown"


class RunnerRejected(RunnerClientError):
    """The authenticated runner rejected a one-shot START."""

    cleanup: Literal["unknown"] = "unknown"

    def __init__(self, code: str):
        super().__init__("ACP judgment runner rejected the request")
        self.code = code


class RunnerStartupRejected(RunnerClientError):
    """A valid READY named the wrong cwd and cancellation was acknowledged."""

    def __init__(self, exit_receipt: "RunnerExit"):
        super().__init__("ACP judgment runner cwd differs from the requested root")
        self.exit_receipt = exit_receipt
        self.cleanup = exit_receipt.cleanup


@dataclass(frozen=True)
class RunnerExit:
    code: int | None
    signal: int | None
    reason: str
    cleanup: Literal["proven", "unknown"]

    @property
    def cleanup_proven(self) -> bool:
        return self.cleanup == "proven"


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RunnerClientError("ACP runner JSON has duplicate fields")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise RunnerClientError("ACP runner JSON has an invalid number")


def canonical_json(value: object) -> bytes:
    """Canonical UTF-8 JSON shared with the runner's request and reply MACs."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise RunnerClientError("ACP runner JSON value is invalid") from exc


def decode_control_secret(encoded: str) -> bytes:
    """Decode the URL-safe-base64 control secret, including omitted padding."""
    if (
        not isinstance(encoded, str) or not encoded or len(encoded) > 512
        or _URLSAFE_B64.fullmatch(encoded) is None
    ):
        raise ValueError("ACP runner control secret is invalid")
    try:
        raw = base64.b64decode(
            encoded.encode("ascii") + b"=" * ((-len(encoded)) % 4),
            altchars=b"-_", validate=True,
        )
    except (UnicodeError, binascii.Error, ValueError) as exc:
        raise ValueError("ACP runner control secret is invalid") from exc
    if len(raw) < 32:
        raise ValueError("ACP runner control secret is invalid")
    return raw


_CLEANUP_RECEIPT_SCHEMA = "byq-acp-judgment-runner-cleanup.v1"
_CLEANUP_RECEIPT_DIR = "cleanup-receipts"
_CLEANUP_RECEIPT_KEYS = frozenset({
    "schema_version", "scope_digest", "task_id", "call_identity", "root_run_id",
    "runtime_boot_id", "authority_epoch", "runner_instance_id", "code", "signal",
    "reason", "cleanup", "mac",
})


def read_cleanup_receipt(directory: str | os.PathLike[str], secret: bytes,
                         scope: Mapping[str, object]) -> dict[str, object] | None:
    """Return the verified signed cleanup receipt for the exact one-shot scope.

    A missing, corrupt, unsigned, wrong-scope, wrong-runner-instance or
    non-proven receipt returns ``None`` so cleanup stays unproven.
    """

    if not isinstance(secret, bytes) or len(secret) < 32:
        return None
    checked = _validate_scope(dict(scope))
    digest = scope_digest(checked)
    path = Path(directory) / _CLEANUP_RECEIPT_DIR / f"{digest}.json"
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096 or info.st_nlink != 1:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_strict_object,
            parse_constant=_reject_constant)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(value, dict) or set(value) != _CLEANUP_RECEIPT_KEYS:
        return None
    mac = value.get("mac")
    if not isinstance(mac, str) or _HEX64.fullmatch(mac) is None:
        return None
    unsigned = {key: item for key, item in value.items() if key != "mac"}
    if not hmac.compare_digest(sign_runner_reply(unsigned, secret), mac):
        return None
    if (unsigned.get("schema_version") != _CLEANUP_RECEIPT_SCHEMA
            or unsigned.get("scope_digest") != digest
            or unsigned.get("cleanup") != "proven"
            or unsigned.get("task_id") != checked["task_id"]
            or unsigned.get("call_identity") != checked["call_identity"]
            or unsigned.get("root_run_id") != checked["root_run_id"]
            or unsigned.get("runtime_boot_id") != checked["runtime_boot_id"]
            or unsigned.get("authority_epoch") != checked["authority_epoch"]
            or not isinstance(unsigned.get("runner_instance_id"), str)
            or _HEX64.fullmatch(unsigned["runner_instance_id"]) is None):
        return None
    return value


def _validate_scope(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != _SCOPE_KEYS:
        raise ValueError("ACP runner scope fields are invalid")
    scope = dict(raw)
    for key in _SCOPE_KEYS - {"authority_epoch"}:
        value = scope.get(key)
        if not isinstance(value, str) or _TEXT.fullmatch(value) is None:
            raise ValueError("ACP runner scope value is invalid")
    if type(scope.get("authority_epoch")) is not int or scope["authority_epoch"] <= 0:
        raise ValueError("ACP runner authority epoch is invalid")
    return scope


def scope_digest(scope: Mapping[str, object]) -> str:
    """Compute the deterministic one-shot session leaf for the exact scope."""
    return hashlib.sha256(canonical_json(_validate_scope(dict(scope)))).hexdigest()


def sign_runner_start(message: Mapping[str, object], secret: bytes) -> str:
    """Create a START MAC; the supplied object must omit its mac field."""
    if not isinstance(secret, bytes) or len(secret) < 32 or "mac" in message:
        raise ValueError("ACP runner START authentication input is invalid")
    return hmac.new(
        secret, _START_PREFIX + canonical_json(dict(message)), hashlib.sha256,
    ).hexdigest()


def sign_runner_reply(message: Mapping[str, object], secret: bytes) -> str:
    """Reply-MAC helper, also used by the fake-runner qualification tests."""
    if not isinstance(secret, bytes) or len(secret) < 32 or "mac" in message:
        raise ValueError("ACP runner reply authentication input is invalid")
    return hmac.new(
        secret, _REPLY_PREFIX + canonical_json(dict(message)), hashlib.sha256,
    ).hexdigest()


def _validate_environment(
    raw: Mapping[str, str], scope: Mapping[str, object],
    proxy_token_env: str, proxy_token: str,
) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ValueError("ACP runner environment is invalid")
    env = dict(raw)
    if (
        not _REQUIRED_ENV <= set(env) or not set(env) <= _ENV_ALLOWLIST
        or any(not isinstance(k, str) or not isinstance(v, str) or not v or "\0" in v
               for k, v in env.items())
    ):
        raise ValueError("ACP runner environment fields are invalid")
    total = 0
    try:
        for key, value in env.items():
            total += len(key.encode("ascii")) + len(value.encode("utf-8"))
            if len(value.encode("utf-8")) > 16_384 or total > MAX_ENV_BYTES:
                raise ValueError("ACP runner environment exceeds its bound")
    except UnicodeError as exc:
        raise ValueError("ACP runner environment encoding is invalid") from exc
    if (
        env.get("BYQ_MCP_ACP_IDENTITY_MODE") != "research-judgment-root-v1"
        or env.get("BYQ_MCP_ACP_JUDGMENT_TASK_ID") != scope.get("task_id")
        or env.get("BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY") != scope.get("call_identity")
        or env.get("BYQ_ROOT_RUN_ID") != scope.get("root_run_id")
        or env.get("BYQ_RUNTIME_BOOT_ID") != scope.get("runtime_boot_id")
    ):
        raise ValueError("ACP runner environment identity differs from scope")
    if (
        not isinstance(proxy_token_env, str) or proxy_token_env not in _PROXY_TOKEN_ENVS
        or not isinstance(proxy_token, str)
        or _PROXY_TOKEN.fullmatch(proxy_token) is None
    ):
        raise ValueError("ACP runner local proxy credential is invalid")
    # The exact allowlist excludes upstream provider and runner master secrets.
    if "DEEPSEEK_API_KEY" in env or "OPENCODE_API_KEY" in env:
        raise ValueError("ACP runner environment contains a provider credential")
    return env


def _validate_overlay(overlay_b64: str) -> None:
    if not isinstance(overlay_b64, str) or len(overlay_b64) > ((MAX_OVERLAY_BYTES + 2) // 3) * 4:
        raise ValueError("ACP runner overlay exceeds its bound")
    try:
        overlay = base64.b64decode(overlay_b64.encode("ascii"), validate=True)
        value = json.loads(
            overlay.decode("utf-8"), object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, binascii.Error, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("ACP runner overlay is invalid") from exc
    if len(overlay) > MAX_OVERLAY_BYTES or not isinstance(value, list) or not value:
        raise ValueError("ACP runner overlay is invalid")


def encode_frame(frame_type: int, payload: bytes) -> bytes:
    if type(frame_type) is not int or not 0 <= frame_type <= 255 or not isinstance(payload, bytes):
        raise RunnerClientError("ACP runner frame is invalid")
    length = len(payload) + 1
    if length > MAX_FRAME_BYTES:
        raise RunnerClientError("ACP runner frame exceeds its bound")
    return struct.pack("!I", length) + bytes((frame_type,)) + payload


def _read_exact(sock: socket.socket, count: int) -> bytes:
    parts: list[bytes] = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RunnerCleanupUnknown("ACP runner connection ended before signed reply")
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


def _read_frame(sock: socket.socket) -> tuple[int, bytes]:
    header = _read_exact(sock, 4)
    (length,) = struct.unpack("!I", header)
    if length < 1 or length > MAX_FRAME_BYTES:
        raise RunnerCleanupUnknown("ACP runner frame length is invalid")
    body = _read_exact(sock, length)
    return body[0], body[1:]


def _decode_json(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (RunnerClientError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RunnerCleanupUnknown("ACP runner control JSON is invalid") from exc
    if not isinstance(value, dict):
        raise RunnerCleanupUnknown("ACP runner control JSON is invalid")
    return value


def _verify_reply(
    value: Mapping[str, object], secret: bytes, expected_fields: frozenset[str],
) -> dict[str, object]:
    if set(value) != expected_fields:
        raise RunnerCleanupUnknown("ACP runner signed reply fields are invalid")
    mac = value.get("mac")
    if not isinstance(mac, str) or _HEX64.fullmatch(mac) is None:
        raise RunnerCleanupUnknown("ACP runner signed reply MAC is invalid")
    unsigned = {key: item for key, item in value.items() if key != "mac"}
    if not hmac.compare_digest(sign_runner_reply(unsigned, secret), mac):
        raise RunnerCleanupUnknown("ACP runner signed reply authentication failed")
    return unsigned


def _read_json_frame(sock: socket.socket, expected_type: int) -> dict[str, object]:
    frame_type, payload = _read_frame(sock)
    if frame_type != expected_type or not payload:
        raise RunnerCleanupUnknown("ACP runner sent an unexpected control frame")
    return _decode_json(payload)


def _send_json(sock: socket.socket, frame_type: int, value: Mapping[str, object]) -> None:
    sock.sendall(encode_frame(frame_type, canonical_json(dict(value))))


def _write_all(fd: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        try:
            count = os.write(fd, remaining)
        except InterruptedError:
            continue
        if count <= 0:
            raise OSError("ACP stdout relay could not write")
        remaining = remaining[count:]


class RunnerClient:
    """A single authenticated AF_UNIX connection to the isolated ACP runner."""

    def __init__(
        self, socket_path: str | os.PathLike[str], control_secret: str | bytes, *,
        connect_timeout_s: float = 5.0, cleanup_timeout_s: float = 5.0,
        socket_factory: Any = socket.socket,
    ) -> None:
        path = os.fspath(socket_path)
        if not isinstance(path, str) or not path.startswith("/") or "\0" in path:
            raise ValueError("ACP runner socket path is invalid")
        if len(path.encode("utf-8")) >= 104:
            raise ValueError("ACP runner socket path exceeds its bound")
        if isinstance(control_secret, str):
            secret = decode_control_secret(control_secret)
        elif isinstance(control_secret, bytes) and len(control_secret) >= 32:
            secret = control_secret
        else:
            raise ValueError("ACP runner control secret is invalid")
        if connect_timeout_s <= 0 or cleanup_timeout_s <= 0:
            raise ValueError("ACP runner timeout is invalid")
        self.socket_path = path
        self._secret = secret
        self._connect_timeout_s = connect_timeout_s
        self._cleanup_timeout_s = cleanup_timeout_s
        self._socket_factory = socket_factory

    @classmethod
    def from_environment(cls, **kwargs: Any) -> "RunnerClient":
        """Read the dedicated socket and URL-safe-base64 control secret."""
        path = os.environ.get(RUNNER_SOCKET_ENV, DEFAULT_RUNNER_SOCKET_PATH)
        encoded_secret = os.environ.get(RUNNER_SECRET_ENV, "")
        if not encoded_secret:
            raise ValueError("ACP runner control secret is unavailable")
        return cls(path, encoded_secret, **kwargs)

    def cleanup_receipt(self, scope: Mapping[str, object]) -> dict[str, object] | None:
        """Return the verified signed cleanup receipt for the exact scope."""
        return read_cleanup_receipt(
            Path(self.socket_path).parent, self._secret, scope)

    def start(
        self, *, scope: Mapping[str, object], env: Mapping[str, str],
        proxy_token_env: str, proxy_token: str, overlay_b64: str,
        deadline_at_ms: int, expected_cwd: str,
    ) -> "RunnerSession":
        """Verify signed CHALLENGE, send START, then verify bound READY."""
        checked_scope = _validate_scope(dict(scope))
        checked_env = _validate_environment(env, checked_scope, proxy_token_env, proxy_token)
        _validate_overlay(overlay_b64)
        if type(deadline_at_ms) is not int or deadline_at_ms <= int(time.time() * 1000):
            raise ValueError("ACP runner deadline has expired")
        if not isinstance(expected_cwd, str) or not expected_cwd.startswith("/") or "\0" in expected_cwd:
            raise ValueError("ACP runner expected cwd is invalid")
        digest = scope_digest(checked_scope)
        nonce = secrets.token_hex(32)
        sock: socket.socket | None = None
        try:
            sock = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout_s)
            sock.connect(self.socket_path)

            challenge_value = _read_json_frame(sock, CHALLENGE)
            challenge_unsigned = _verify_reply(
                challenge_value, self._secret, _CHALLENGE_KEYS,
            )
            challenge = challenge_unsigned.get("challenge")
            if (
                challenge_unsigned.get("v") != PROTOCOL_VERSION
                or not isinstance(challenge, str) or _HEX64.fullmatch(challenge) is None
            ):
                raise RunnerCleanupUnknown("ACP runner challenge is invalid")

            unsigned_start: dict[str, object] = {
                "v": PROTOCOL_VERSION,
                "challenge": challenge,
                "nonce": nonce,
                "scope": checked_scope,
                "env": checked_env,
                "proxy_token_env": proxy_token_env,
                "proxy_token": proxy_token,
                "overlay_b64": overlay_b64,
                "deadline_at_ms": deadline_at_ms,
            }
            start_value = {
                **unsigned_start, "mac": sign_runner_start(unsigned_start, self._secret),
            }
            _send_json(sock, START, start_value)
            frame_type, payload = _read_frame(sock)
            if frame_type == REJECT and payload:
                rejected = _verify_reply(_decode_json(payload), self._secret, _REJECT_KEYS)
                self._verify_binding(rejected, challenge, nonce, digest)
                code = rejected.get("code")
                if not isinstance(code, str) or code not in _REJECT_CODES:
                    raise RunnerCleanupUnknown("ACP runner rejection code is invalid")
                raise RunnerRejected(code)
            if frame_type != READY or not payload:
                raise RunnerCleanupUnknown("ACP runner did not send authenticated READY")
            ready = _verify_reply(_decode_json(payload), self._secret, _READY_KEYS)
            self._verify_binding(ready, challenge, nonce, digest)
            cwd = ready.get("cwd")
            if not isinstance(cwd, str) or not cwd.startswith("/") or "\0" in cwd:
                raise RunnerCleanupUnknown("ACP runner cwd is invalid")
            sock.settimeout(None)
            session = RunnerSession(
                sock, self._secret, challenge, nonce, digest, cwd,
                cleanup_timeout_s=self._cleanup_timeout_s,
            )
            sock = None
            if cwd != expected_cwd:
                try:
                    session.cancel()
                    exit_receipt = session.wait_exit(self._cleanup_timeout_s)
                except RunnerClientError as exc:
                    raise RunnerCleanupUnknown(
                        "ACP runner started outside the exact requested cwd"
                    ) from exc
                raise RunnerStartupRejected(exit_receipt)
            return session
        except (OSError, TimeoutError, socket.timeout) as exc:
            raise RunnerCleanupUnknown("ACP runner handshake did not complete") from exc
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
            reply.get("v") != PROTOCOL_VERSION
            or reply.get("challenge") != challenge
            or reply.get("nonce") != nonce
            or reply.get("scope_digest") != digest
        ):
            raise RunnerCleanupUnknown("ACP runner reply belongs to another request")


class RunnerSession:
    """Relay ACP bytes and preserve an exact authenticated process receipt."""

    def __init__(
        self, sock: socket.socket, secret: bytes, challenge: str, nonce: str,
        digest: str, cwd: str, *, cleanup_timeout_s: float,
    ) -> None:
        self._socket = sock
        self._secret = secret
        self._challenge = challenge
        self._nonce = nonce
        self._digest = digest
        self.cwd = cwd
        self._cleanup_timeout_s = cleanup_timeout_s
        self._buffer = bytearray()
        self._send_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._exit: RunnerExit | None = None
        self._closed = False

    @property
    def cleanup(self) -> Literal["proven", "unknown"]:
        return self._exit.cleanup if self._exit is not None else "unknown"

    def send_stdin(self, content: bytes) -> None:
        if not isinstance(content, bytes) or not content:
            raise ValueError("ACP stdin chunk must be nonempty bytes")
        if self._cancelled.is_set() or self._closed:
            raise RunnerClientError("ACP runner session no longer accepts input")
        with self._send_lock:
            if self._cancelled.is_set() or self._closed:
                raise RunnerClientError("ACP runner session no longer accepts input")
            chunk_size = MAX_FRAME_BYTES - 1
            for offset in range(0, len(content), chunk_size):
                self._socket.sendall(encode_frame(STDIN, content[offset:offset + chunk_size]))

    def cancel(self) -> None:
        """Ask the runner to stop; this does not itself prove cleanup."""
        if self._closed or self._exit is not None:
            return
        with self._send_lock:
            if self._cancelled.is_set():
                return
            self._cancelled.set()
            try:
                self._socket.sendall(encode_frame(CANCEL, b""))
            except OSError as exc:
                self._close_socket()
                raise RunnerCleanupUnknown("ACP runner cancellation was not acknowledged") from exc

    def receive(self, timeout_s: float | None = None) -> bytes | RunnerExit | None:
        """Return one STDOUT chunk, signed EXIT, or None when the poll times out."""
        if self._exit is not None:
            return self._exit
        if self._closed:
            raise RunnerCleanupUnknown("ACP runner session closed before signed EXIT")
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("ACP runner receive timeout is invalid")
        try:
            frame = self._next_frame(timeout_s)
        except (OSError, TimeoutError, socket.timeout) as exc:
            self._close_socket()
            raise RunnerCleanupUnknown("ACP runner connection ended before signed EXIT") from exc
        if frame is None:
            return None
        frame_type, payload = frame
        if frame_type == STDOUT:
            if not payload:
                self._fail_unknown("ACP runner sent an empty STDOUT frame")
            return payload
        if frame_type != EXIT or not payload:
            self._fail_unknown("ACP runner sent an unexpected relay frame")
        try:
            value = _verify_reply(_decode_json(payload), self._secret, _EXIT_KEYS)
            RunnerClient._verify_binding(value, self._challenge, self._nonce, self._digest)
            code = value.get("code")
            child_signal = value.get("signal")
            reason = value.get("reason")
            cleanup = value.get("cleanup")
            if (
                (code is not None and (type(code) is not int or code < 0))
                or (child_signal is not None and (type(child_signal) is not int or child_signal <= 0))
                or not isinstance(reason, str) or reason not in _EXIT_REASONS
                or cleanup not in ("proven", "unknown")
                # A reaped child killed on cancel/deadline has no exit code;
                # the runner instead signs its terminating signal.
                or (cleanup == "proven" and (code is None) == (child_signal is None))
            ):
                self._fail_unknown("ACP runner EXIT facts are invalid")
        except RunnerCleanupUnknown:
            self._close_socket()
            raise
        self._exit = RunnerExit(code, child_signal, reason, cleanup)  # type: ignore[arg-type]
        self._close_socket()
        return self._exit

    def wait_exit(self, timeout_s: float | None = None) -> RunnerExit:
        """Wait for signed EXIT; timeout and EOF are cleanup-unknown failures."""
        timeout = self._cleanup_timeout_s if timeout_s is None else timeout_s
        if timeout <= 0:
            raise ValueError("ACP runner cleanup timeout is invalid")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._close_socket()
                raise RunnerCleanupUnknown("ACP runner EXIT was not received before timeout")
            event = self.receive(remaining)
            if isinstance(event, RunnerExit):
                return event

    def relay_stdio(
        self, input_fd: int, output_fd: int, *,
        cancel_event: threading.Event | None = None,
        cancel_exit_timeout_s: float | None = None,
    ) -> RunnerExit:
        """Relay parent ACP stdio and wait for signed cleanup after cancellation."""
        stop = threading.Event()
        send_errors: list[BaseException] = []
        cancel_sent = threading.Event()
        cancel_times: list[float] = []
        cancel_timeout = (
            self._cleanup_timeout_s if cancel_exit_timeout_s is None
            else cancel_exit_timeout_s
        )
        if cancel_timeout <= 0:
            raise ValueError("ACP runner cancellation timeout is invalid")

        def pump_input() -> None:
            try:
                while not stop.is_set():
                    if cancel_event is not None and cancel_event.is_set():
                        self.cancel()
                        cancel_times.append(time.monotonic())
                        cancel_sent.set()
                        return
                    readable, _, _ = select.select([input_fd], [], [], 0.05)
                    if not readable:
                        continue
                    data = os.read(input_fd, 64 * 1024)
                    if not data:
                        self.cancel()
                        cancel_times.append(time.monotonic())
                        cancel_sent.set()
                        return
                    self.send_stdin(data)
            except BaseException as exc:
                send_errors.append(exc)
                stop.set()

        thread = threading.Thread(target=pump_input, name="byq-acp-runner-stdin", daemon=True)
        thread.start()
        try:
            while True:
                if send_errors:
                    raise RunnerCleanupUnknown(
                        "ACP runner stdin relay failed before signed EXIT"
                    ) from send_errors[0]
                if (
                    cancel_sent.is_set() and cancel_times
                    and time.monotonic() - cancel_times[0] >= cancel_timeout
                ):
                    self._close_socket()
                    raise RunnerCleanupUnknown(
                        "ACP runner did not acknowledge cancellation with signed EXIT"
                    )
                event = self.receive(0.05)
                if isinstance(event, RunnerExit):
                    return event
                if isinstance(event, bytes):
                    try:
                        _write_all(output_fd, event)
                    except OSError as exc:
                        self.cancel()
                        raise RunnerCleanupUnknown(
                            "ACP runner stdout relay failed before signed EXIT"
                        ) from exc
        finally:
            stop.set()
            thread.join(timeout=0.2)
            self._close_socket()

    def _next_frame(self, timeout_s: float | None) -> tuple[int, bytes] | None:
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            if len(self._buffer) >= 4:
                (length,) = struct.unpack("!I", self._buffer[:4])
                if length < 1 or length > MAX_FRAME_BYTES:
                    self._fail_unknown("ACP runner frame length is invalid")
                if len(self._buffer) >= 4 + length:
                    body = bytes(self._buffer[4:4 + length])
                    del self._buffer[:4 + length]
                    return body[0], body[1:]
            wait = None if deadline is None else max(0.0, deadline - time.monotonic())
            if wait == 0:
                return None
            readable, _, _ = select.select([self._socket], [], [], wait)
            if not readable:
                return None
            data = self._socket.recv(64 * 1024)
            if not data:
                self._fail_unknown("ACP runner connection ended before signed EXIT")
            self._buffer.extend(data)
            if len(self._buffer) > MAX_FRAME_BYTES + 4 + 64 * 1024:
                self._fail_unknown("ACP runner receive buffer exceeds its bound")

    def _fail_unknown(self, message: str) -> None:
        self._close_socket()
        raise RunnerCleanupUnknown(message)

    def _close_socket(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError:
            pass
