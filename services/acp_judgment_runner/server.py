"""Internal ACP DSH process owner and authenticated stdio relay."""

from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import hmac
import json
import os
import re
import signal
import socket
import socketserver
import stat
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1_048_576
MAX_OVERLAY_BYTES = 16_384
MAX_ENV_BYTES = 64 * 1024
AUTH_TIMEOUT_SECONDS = 5.0
KILL_GRACE_SECONDS = 1.0
GROUP_REAP_TIMEOUT_SECONDS = 2.0
PROCESS_QUIESCENCE_SECONDS = 0.15
MAX_RUN_SECONDS = 3600
PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37

CHALLENGE = 0x01
START = 0x02
STDIN = 0x03
CANCEL = 0x04
READY = 0x81
REJECT = 0x82
STDOUT = 0x83
EXIT = 0x84

PINNED_DSH_COMMIT = "639ed015397290b3745d163aafe02ffee4aa3f84"
RUNNER_HMAC_PREFIX = b"byq-acp-runner-v1\0"
RUNNER_REPLY_HMAC_PREFIX = b"byq-acp-runner-reply-v1\0"
SHARED_SESSION_ROOT = Path("/var/lib/byq/acp-judgment-sessions")
RUNNER_STATE_ROOT = Path("/var/lib/byq/acp-runner-state")
CONTROL_DIRECTORY = Path("/run/byq-acp-runner")
CONTROL_SOCKET = CONTROL_DIRECTORY / "control.sock"
RUNNER_READY_FILE = CONTROL_DIRECTORY / "ready"
CONTROL_GID = 10005
PROFILE_PATCH = Path("/opt/byq/profiles/byq-research-judgment.patch.yml")

SCOPE_KEYS = frozenset({
    "task_id", "call_identity", "attempt_binding", "root_run_id",
    "runtime_boot_id", "authority_epoch",
})
START_KEYS = frozenset({
    "v", "challenge", "nonce", "scope", "env", "proxy_token_env",
    "proxy_token", "overlay_b64", "deadline_at_ms", "mac",
})
RUNNER_ENV_ALLOWLIST = frozenset({
    "BYQ_MCP_URL", "BYQ_MCP_PRODUCT_URL", "BYQ_MCP_ACP_IDENTITY_MODE",
    "BYQ_MCP_ACP_JUDGMENT_TASK_ID", "BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY",
    "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY", "BYQ_RUNTIME_BOOT_ID",
    "BYQ_OWNER_PRINCIPAL", "BYQ_WORKSPACE_ID", "BYQ_ACTOR_PRINCIPAL",
    "BYQ_TRACE_ID", "BYQ_SESSION_ID", "BYQ_DSH_RUN_ID", "BYQ_ROOT_RUN_ID",
})
_REQUIRED_ENV = RUNNER_ENV_ALLOWLIST - {"BYQ_MCP_PRODUCT_URL"}
_TOKEN_ENV_NAMES = frozenset({"DEEPSEEK_API_KEY", "OPENCODE_API_KEY"})
_LOCAL_PROXY_TOKEN = re.compile(r"byq-acp-proxy-[A-Za-z0-9_-]{43}\Z")
_SCOPE_TEXT = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")
_HEX_32 = re.compile(r"[0-9a-f]{64}\Z")


class ProtocolError(ValueError):
    """Malformed or unauthorized runner protocol input."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ProtocolError("nonstandard JSON number")


def canonical_json(value: object) -> bytes:
    """Canonical UTF-8 JSON used by the START request MAC and scope digest."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("value is not canonical JSON") from exc


def sign_start_message(message: dict[str, Any], secret: str | bytes) -> str:
    """MAC a START object which does not yet contain its mac field."""
    if not isinstance(message, dict) or "mac" in message:
        raise ProtocolError("START MAC input must omit mac")
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if not isinstance(key, bytes) or len(key) < 32:
        raise ProtocolError("runner control secret is invalid")
    return hmac.new(key, RUNNER_HMAC_PREFIX + canonical_json(message),
                    hashlib.sha256).hexdigest()


def sign_runner_reply(message: dict[str, Any], secret: str | bytes) -> str:
    """MAC a CHALLENGE/READY/EXIT/REJECT object which omits its mac field."""
    if not isinstance(message, dict) or "mac" in message:
        raise ProtocolError("runner reply MAC input must omit mac")
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if not isinstance(key, bytes) or len(key) < 32:
        raise ProtocolError("runner control secret is invalid")
    return hmac.new(key, RUNNER_REPLY_HMAC_PREFIX + canonical_json(message),
                    hashlib.sha256).hexdigest()


def _validate_scope(scope: object) -> dict[str, Any]:
    if not isinstance(scope, dict) or set(scope) != SCOPE_KEYS:
        raise ProtocolError("scope fields are invalid")
    for key in SCOPE_KEYS - {"authority_epoch"}:
        value = scope.get(key)
        if not isinstance(value, str) or _SCOPE_TEXT.fullmatch(value) is None:
            raise ProtocolError("scope value is invalid")
    if type(scope.get("authority_epoch")) is not int or scope["authority_epoch"] <= 0:
        raise ProtocolError("authority epoch is invalid")
    return scope


def scope_digest(scope: dict[str, Any]) -> str:
    """SHA-256 leaf shared with the Adapter for this exact one-shot scope."""
    return hashlib.sha256(canonical_json(_validate_scope(scope))).hexdigest()


def encode_frame(frame_type: int, payload: bytes) -> bytes:
    """Encode uint32-be length (including type), one type byte, then payload."""
    if type(frame_type) is not int or not 0 <= frame_type <= 255 or not isinstance(payload, bytes):
        raise ProtocolError("frame is invalid")
    length = len(payload) + 1
    if length > MAX_FRAME_BYTES:
        raise ProtocolError("frame exceeds its bound")
    return struct.pack("!I", length) + bytes((frame_type,)) + payload


def _read_exact(stream: BinaryIO | socket.socket, count: int,
                *, allow_clean_eof: bool = False) -> bytes | None:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = stream.recv(remaining) if isinstance(stream, socket.socket) else stream.read(remaining)
        if not chunk:
            if allow_clean_eof and remaining == count:
                return None
            raise ProtocolError("truncated frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO | socket.socket) -> tuple[int, bytes] | None:
    """Read a bounded frame, returning None only for clean EOF between frames."""
    header = _read_exact(stream, 4, allow_clean_eof=True)
    if header is None:
        return None
    (length,) = struct.unpack("!I", header)
    if length < 1 or length > MAX_FRAME_BYTES:
        raise ProtocolError("frame length is invalid")
    body = _read_exact(stream, length)
    assert body is not None
    return body[0], body[1:]


def _read_json_frame(stream: BinaryIO | socket.socket, expected_type: int) -> dict[str, Any]:
    frame = read_frame(stream)
    if frame is None or frame[0] != expected_type or not frame[1]:
        raise ProtocolError("unexpected control frame")
    try:
        value = json.loads(frame[1].decode("utf-8"), object_pairs_hook=_strict_object,
                           parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("control JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ProtocolError("control JSON object is required")
    return value


def _send_json(sock: socket.socket, frame_type: int, value: dict[str, Any]) -> None:
    sock.sendall(encode_frame(frame_type, canonical_json(value)))


def _validate_environment(raw: object, scope: dict[str, Any], proxy_env: object,
                          proxy_token: object) -> dict[str, str]:
    if (not isinstance(raw, dict) or not _REQUIRED_ENV <= set(raw)
            or not set(raw) <= RUNNER_ENV_ALLOWLIST):
        raise ProtocolError("child environment fields are invalid")
    total = 0
    env: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value or "\0" in value:
            raise ProtocolError("child environment value is invalid")
        encoded = value.encode("utf-8")
        total += len(key.encode("ascii")) + len(encoded)
        if total > MAX_ENV_BYTES or len(encoded) > 16_384:
            raise ProtocolError("child environment exceeds its bound")
        env[key] = value
    if (env.get("BYQ_MCP_ACP_IDENTITY_MODE") != "research-judgment-root-v1"
            or env.get("BYQ_MCP_ACP_JUDGMENT_TASK_ID") != scope["task_id"]
            or env.get("BYQ_MCP_ACP_JUDGMENT_CALL_IDENTITY") != scope["call_identity"]
            or env.get("BYQ_ROOT_RUN_ID") != scope["root_run_id"]
            or env.get("BYQ_RUNTIME_BOOT_ID") != scope["runtime_boot_id"]):
        raise ProtocolError("child identity environment differs from scope")
    if proxy_env not in _TOKEN_ENV_NAMES or not isinstance(proxy_token, str):
        raise ProtocolError("local provider proxy token is invalid")
    if _LOCAL_PROXY_TOKEN.fullmatch(proxy_token) is None:
        raise ProtocolError("local provider proxy token is invalid")
    if proxy_env in env or "DEEPSEEK_API_KEY" in env or "OPENCODE_API_KEY" in env:
        raise ProtocolError("provider credential fields are forbidden")
    return env


def _validate_start(value: dict[str, Any], challenge: str, secret: bytes) -> tuple[
        dict[str, Any], dict[str, str], str, str, bytes, float, str]:
    expected_keys = START_KEYS
    if set(value) != expected_keys or type(value.get("v")) is not int or value["v"] != PROTOCOL_VERSION:
        raise ProtocolError("START fields are invalid")
    if value.get("challenge") != challenge or _HEX_32.fullmatch(challenge) is None:
        raise ProtocolError("START challenge differs")
    if not isinstance(value.get("nonce"), str) or _HEX_32.fullmatch(value["nonce"]) is None:
        raise ProtocolError("START nonce is invalid")
    scope = _validate_scope(value.get("scope"))
    env = _validate_environment(value.get("env"), scope, value.get("proxy_token_env"), value.get("proxy_token"))
    overlay_text = value.get("overlay_b64")
    if not isinstance(overlay_text, str) or len(overlay_text) > ((MAX_OVERLAY_BYTES + 2) // 3) * 4:
        raise ProtocolError("private overlay is invalid")
    try:
        overlay = base64.b64decode(overlay_text.encode("ascii"), validate=True)
        decoded_overlay = json.loads(overlay.decode("utf-8"), object_pairs_hook=_strict_object,
                                     parse_constant=_reject_constant)
    except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("private overlay is invalid") from exc
    if len(overlay) > MAX_OVERLAY_BYTES or not isinstance(decoded_overlay, list) or not decoded_overlay:
        raise ProtocolError("private overlay exceeds its bound")
    deadline_at_ms = value.get("deadline_at_ms")
    if type(deadline_at_ms) is not int or deadline_at_ms <= 0:
        raise ProtocolError("absolute run deadline is invalid")
    remaining_ms = deadline_at_ms - int(time.time() * 1000)
    if remaining_ms <= 0:
        raise ProtocolError("absolute run deadline has expired")
    deadline_monotonic = time.monotonic() + min(
        remaining_ms, MAX_RUN_SECONDS * 1000,
    ) / 1000.0
    mac = value.get("mac")
    if not isinstance(mac, str) or _HEX_32.fullmatch(mac) is None:
        raise ProtocolError("START MAC is invalid")
    unsigned = {key: item for key, item in value.items() if key != "mac"}
    expected_mac = hmac.new(secret, RUNNER_HMAC_PREFIX + canonical_json(unsigned),
                            hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_mac, mac):
        raise ProtocolError("START authentication failed")
    return (scope, env, value["proxy_token_env"], value["proxy_token"],
            overlay, deadline_monotonic, value["nonce"])


def _ensure_private_directory(path: Path, *, uid: int, gid: int) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("private directory is not a directory")
    if info.st_uid != uid or info.st_gid != gid:
        os.chown(path, uid, gid, follow_symlinks=False)
    os.chmod(path, 0o700, follow_symlinks=False)
    final = os.stat(path, follow_symlinks=False)
    if final.st_uid != uid or final.st_gid != gid or stat.S_IMODE(final.st_mode) != 0o700:
        raise OSError("private directory permissions are invalid")


def _assign_private_directory(path: Path, *, uid: int, gid: int) -> None:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("private child path is not a directory")
    os.chmod(path, 0o700, follow_symlinks=False)
    # The runner deliberately lacks CAP_FOWNER. Set mode while still owned by
    # root, then transfer ownership to the DSH UID with CAP_CHOWN.
    os.chown(path, uid, gid, follow_symlinks=False)
    final = os.lstat(path)
    if (not stat.S_ISDIR(final.st_mode) or final.st_uid != uid or final.st_gid != gid
            or stat.S_IMODE(final.st_mode) != 0o700):
        raise OSError("private child directory permissions are invalid")


def _write_private_overlay(directory: Path, content: bytes, uid: int, gid: int) -> Path:
    path = directory / "selected-provider.patch.yml"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, uid, gid)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    info = os.lstat(path)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != len(content)):
        raise OSError("private overlay permissions are invalid")
    return path


def _make_launcher(runtime_root: Path, profile_patch: Path) -> tuple[str, ...]:
    """Read back and verify the fixed official CLI path and source commit."""
    runtime_root = runtime_root.resolve(strict=True)
    marker = runtime_root / ".byq-source-commit"
    if marker.read_text(encoding="ascii").strip() != PINNED_DSH_COMMIT:
        raise RuntimeError("fixed official DSH source identity differs")
    node = Path("/usr/local/bin/node")
    entry = runtime_root / "apps" / "cli" / "lib" / "bin.js"
    if not node.is_file() or not os.access(node, os.X_OK) or not entry.is_file():
        raise RuntimeError("fixed official DSH ACP executable is unavailable")
    profile_patch = profile_patch.resolve(strict=True)
    if not profile_patch.is_file():
        raise RuntimeError("fixed ACP composition is unavailable")
    return (str(node), str(entry), "--profile", "acp", "--patch", str(profile_patch))


def _consume_scope(state_dir: Path, scope: dict[str, Any], owner_uid: int,
                   owner_gid: int) -> str:
    """Durably consume a scope before process creation; never roll back a marker."""
    digest = scope_digest(scope)
    marker = state_dir / f"{digest}.used"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(marker, flags, 0o600)
    try:
        os.fchown(descriptor, owner_uid, owner_gid)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(b"byq-acp-runner-one-shot.v1\n")
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(state_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # Preserve a partial marker if present. It still blocks retries.
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    info = os.lstat(marker)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or info.st_gid != owner_gid
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise OSError("one-shot tombstone permissions are invalid")
    return digest


@dataclass(frozen=True)
class _ProcEntry:
    pid: int
    ppid: int
    start_time: int
    uids: tuple[int, int, int, int]
    no_new_privs: int


def _prctl_child_subreaper(*, enabled: bool | None = None) -> bool:
    """Read or set Linux child-subreaper state, failing closed on other systems."""
    if os.name != "posix" or not Path("/proc/self/status").is_file():
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.restype = ctypes.c_int
    if enabled is None:
        value = ctypes.c_int()
        result = prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(value), 0, 0, 0)
        return result == 0 and value.value == 1
    result = prctl(PR_SET_CHILD_SUBREAPER, ctypes.c_ulong(1 if enabled else 0), 0, 0, 0)
    return result == 0


def _read_proc_entry(pid: int) -> _ProcEntry | None:
    """Read the identity fields needed for tree tracking; None means a race."""
    base = Path("/proc") / str(pid)
    try:
        first_stat = (base / "stat").read_text(encoding="ascii")
        status = (base / "status").read_text(encoding="ascii")
        last_stat = (base / "stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    except OSError:
        raise

    def parse_stat(raw: str) -> tuple[int, int]:
        close = raw.rfind(")")
        if close < 0:
            raise ValueError("proc stat has no command terminator")
        fields = raw[close + 2:].split()
        # The suffix starts at field 3 (state). PPID is field 4 and starttime
        # is field 22, hence suffix offsets 1 and 19.
        if len(fields) <= 19:
            raise ValueError("proc stat is truncated")
        return int(fields[1]), int(fields[19])

    try:
        ppid, start_time = parse_stat(first_stat)
        final_ppid, final_start = parse_stat(last_stat)
        if (start_time, ppid) != (final_start, final_ppid):
            return None
        fields = {line.partition(":")[0]: line.partition(":")[2].strip()
                  for line in status.splitlines() if ":" in line}
        uid_fields = tuple(int(item) for item in fields["Uid"].split())
        no_new_privs = int(fields["NoNewPrivs"])
        if len(uid_fields) != 4:
            raise ValueError("proc Uid field is invalid")
    except (KeyError, ValueError, IndexError) as exc:
        raise OSError("process identity could not be verified") from exc
    return _ProcEntry(pid, final_ppid, final_start, uid_fields, no_new_privs)


def _read_proc_table() -> dict[int, _ProcEntry] | None:
    """Read /proc completely. Permission or parse failures invalidate proof."""
    table: dict[int, _ProcEntry] = {}
    try:
        with os.scandir("/proc") as proc_entries:
            entries = list(proc_entries)
    except OSError:
        return None
    for item in entries:
        if not item.name.isdecimal():
            continue
        try:
            entry = _read_proc_entry(int(item.name))
        except OSError:
            return None
        if entry is not None:
            table[entry.pid] = entry
    return table


def _execution_processes(table: dict[int, _ProcEntry], *, root_pid: int,
                         runner_pid: int, child_uid: int) -> tuple[set[int], bool]:
    """Return this run's live tree plus adopted child-UID processes.

    The runner has one serialized run and starts only after proving that no
    process with the dedicated DSH UID exists. Linux subreaper adoption then
    makes double-forked/orphaned DSH descendants direct children of the runner.
    We include those exact adopted children, while reporting any unrelated
    child-UID process as an unprovable state instead of killing it.
    """
    by_parent: dict[int, list[_ProcEntry]] = {}
    for entry in table.values():
        by_parent.setdefault(entry.ppid, []).append(entry)

    adopted = {
        entry.pid for entry in by_parent.get(runner_pid, [])
        if entry.pid != root_pid and entry.uids[0] == child_uid
    }
    owned: set[int] = set()
    pending = [root_pid, *adopted]
    while pending:
        parent = pending.pop()
        if parent in owned:
            continue
        entry = table.get(parent)
        if entry is None:
            continue
        owned.add(parent)
        pending.extend(child.pid for child in by_parent.get(parent, []))

    unknown_child_uid = any(
        entry.ppid == runner_pid and child_uid in entry.uids and entry.pid not in owned
        for entry in table.values()
    )
    safe_nnp = all(table[pid].no_new_privs == 1 for pid in owned if pid in table)
    return owned, not unknown_child_uid and safe_nnp


def _has_preexisting_child_uid(table: dict[int, _ProcEntry], child_uid: int) -> bool:
    runner_pid = os.getpid()
    return any(entry.ppid == runner_pid and child_uid in entry.uids
               for entry in table.values())


def _pidfd_signal(entry: _ProcEntry, sig: int) -> bool:
    """Signal a still-matching process identity; return False if unprovable."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return False

    try:
        descriptor = os.pidfd_open(entry.pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    try:
        current = _read_proc_entry(entry.pid)
        if current is None:
            return True
        if (current.start_time, current.ppid, current.uids) != (
                entry.start_time, entry.ppid, entry.uids):
            return False
        signal.pidfd_send_signal(descriptor, sig)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False
    finally:
        os.close(descriptor)


def _reap_adopted(table: dict[int, _ProcEntry], runner_pid: int, root_pid: int,
                  child_uid: int) -> bool:
    """Reap dead DSH children adopted by this subreaper, excluding Popen root."""
    complete = True
    for entry in table.values():
        if (entry.ppid != runner_pid or entry.pid == root_pid
                or entry.uids[0] != child_uid):
            continue
        try:
            os.waitpid(entry.pid, os.WNOHANG)
        except ChildProcessError:
            current = _read_proc_entry(entry.pid)
            if current is not None and current.start_time == entry.start_time:
                complete = False
        except OSError:
            complete = False
    return complete


def _terminate_and_reap(process: subprocess.Popen[bytes], *, child_uid: int
                        ) -> tuple[int | None, int | None, str]:
    """Stop the DSH tree, including setsid/double-fork children, or say unknown."""
    runner_pid = os.getpid()
    certifiable = (
        _prctl_child_subreaper()
        and _read_no_new_privs(runner_pid) is True
        and hasattr(os, "pidfd_open")
        and hasattr(signal, "pidfd_send_signal")
    )
    code: int | None = None
    term_deadline = time.monotonic() + KILL_GRACE_SECONDS
    term_empty_since: float | None = None
    while time.monotonic() < term_deadline:
        process.poll()
        table = _read_proc_table()
        if table is None:
            certifiable = False
            try:
                process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError:
                pass
            break
        owned, state_safe = _execution_processes(
            table, root_pid=process.pid, runner_pid=runner_pid, child_uid=child_uid)
        certifiable = certifiable and state_safe
        for pid in owned:
            entry = table.get(pid)
            if entry is not None and not _pidfd_signal(entry, signal.SIGTERM):
                certifiable = False
        if not _reap_adopted(table, runner_pid, process.pid, child_uid):
            certifiable = False
        if not owned:
            if term_empty_since is None:
                term_empty_since = time.monotonic()
            elif time.monotonic() - term_empty_since >= PROCESS_QUIESCENCE_SECONDS:
                break
        else:
            term_empty_since = None
        time.sleep(0.025)

    kill_deadline = time.monotonic() + GROUP_REAP_TIMEOUT_SECONDS
    empty_since: float | None = None
    while time.monotonic() < kill_deadline:
        polled = process.poll()
        if polled is not None:
            code = polled
        table = _read_proc_table()
        if table is None:
            certifiable = False
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except OSError:
                pass
            break
        owned, state_safe = _execution_processes(
            table, root_pid=process.pid, runner_pid=runner_pid, child_uid=child_uid)
        certifiable = certifiable and state_safe
        for pid in owned:
            entry = table.get(pid)
            if entry is not None and not _pidfd_signal(entry, signal.SIGKILL):
                certifiable = False
        if not _reap_adopted(table, runner_pid, process.pid, child_uid):
            certifiable = False
        # Re-scan after reaping: /proc may still have shown an adopted zombie.
        after_reap = _read_proc_table()
        if after_reap is None:
            certifiable = False
            break
        remaining, state_safe = _execution_processes(
            after_reap, root_pid=process.pid, runner_pid=runner_pid, child_uid=child_uid)
        certifiable = certifiable and state_safe
        if not remaining:
            if empty_since is None:
                empty_since = time.monotonic()
            elif time.monotonic() - empty_since >= PROCESS_QUIESCENCE_SECONDS:
                break
        else:
            empty_since = None
        time.sleep(0.025)

    try:
        code = process.wait(timeout=0.1)
    except subprocess.TimeoutExpired:
        certifiable = False
    final_table = _read_proc_table()
    if final_table is None:
        certifiable = False
        remaining = {process.pid}
    else:
        remaining, state_safe = _execution_processes(
            final_table, root_pid=process.pid, runner_pid=runner_pid, child_uid=child_uid)
        certifiable = certifiable and state_safe
        if not _reap_adopted(final_table, runner_pid, process.pid, child_uid):
            certifiable = False
        after_final_reap = _read_proc_table()
        if after_final_reap is None:
            certifiable = False
            remaining = {process.pid}
        else:
            remaining, state_safe = _execution_processes(
                after_final_reap, root_pid=process.pid, runner_pid=runner_pid,
                child_uid=child_uid)
            certifiable = certifiable and state_safe

    child_signal = -code if code is not None and code < 0 else None
    if code is None or remaining or not certifiable:
        return code, child_signal, "unknown"
    return code, child_signal, "proven"


def _read_no_new_privs(pid: int) -> bool | None:
    try:
        status = (Path("/proc") / str(pid) / "status").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("NoNewPrivs:"):
            try:
                return int(line.partition(":")[2].strip()) == 1
            except ValueError:
                return None
    return None


def _minimal_child_environment(env: dict[str, str], proxy_env: str, proxy_token: str,
                               home: Path, session_root: Path) -> dict[str, str]:
    result = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(home / "tmp"),
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "DSH_HOME": str(home),
        "DSH_SESSION_ROOT": str(session_root),
        "DSH_TELEMETRY_DISABLED": "1",
        "DSH_PERMISSION_MODE": "read-only",
        "DSH_MAX_TOKENS_AS_SUCCESS": "false",
    }
    result.update(env)
    result[proxy_env] = proxy_token
    for forbidden in (
        "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET", "BYQ_ACP_JUDGMENT_RUNNER_SECRET",
        "BYQ_RUNTIME_AUTHORITY_TOKEN", "BYQ_BACKEND_AUTHORITY_TOKEN",
        "BYQ_MCP_BACKEND_PROOF_TOKEN", "DEEPSEEK_API_KEY_UPSTREAM",
        "OPENCODE_API_KEY_UPSTREAM", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "NODE_OPTIONS", "PYTHONPATH",
    ):
        result.pop(forbidden, None)
    return result


class JudgmentRunnerServer(socketserver.UnixStreamServer):
    """Sequential root-only Unix socket server for one authenticated run."""

    # SO_REUSEADDR is an IP-socket option and is invalid for AF_UNIX sockets.
    allow_reuse_address = False
    request_queue_size = 1

    def __init__(self, socket_path: Path = CONTROL_SOCKET, *, secret: bytes,
                 state_dir: Path = RUNNER_STATE_ROOT,
                 session_root: Path = SHARED_SESSION_ROOT,
                 launcher: tuple[str, ...] | None = None,
                 profile_patch: Path = PROFILE_PATCH,
                 runtime_root: Path = Path("/opt/dsh-runtime"),
                 child_uid: int = 10002, child_gid: int = 10002,
                 prepare_roots: bool = True,
                 ready_file: Path = RUNNER_READY_FILE,
                 control_gid: int = CONTROL_GID,
                 state_uid: int | None = None, state_gid: int = 0,
                 runner_uid: int = 0) -> None:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("runner control secret must contain at least 32 bytes")
        self.secret = secret
        self.state_dir = Path(state_dir)
        self.session_root = Path(session_root)
        self.profile_patch = Path(profile_patch)
        self.child_uid = child_uid
        self.child_gid = child_gid
        self.control_gid = control_gid
        self.runner_uid = runner_uid
        self.socket_path = Path(socket_path)
        self.ready_file = Path(ready_file)
        self.state_uid = os.geteuid() if state_uid is None else state_uid
        self.state_gid = state_gid
        self.launcher = launcher
        if prepare_roots:
            self._prepare_roots()
        if self.launcher is None:
            self.launcher = _make_launcher(Path(runtime_root), self.profile_patch)
        self._clear_ready_file()
        self._remove_stale_socket()
        super().__init__(str(self.socket_path), _RunnerRequestHandler, bind_and_activate=True)
        os.chown(self.socket_path, self.runner_uid, self.control_gid, follow_symlinks=False)
        os.chmod(self.socket_path, 0o660, follow_symlinks=False)
        socket_info = os.stat(self.socket_path, follow_symlinks=False)
        if (not stat.S_ISSOCK(socket_info.st_mode) or socket_info.st_uid != self.runner_uid
                or socket_info.st_gid != self.control_gid
                or stat.S_IMODE(socket_info.st_mode) != 0o660):
            self.server_close()
            raise RuntimeError("runner control socket permissions are invalid")
        self._publish_ready()

    def _prepare_roots(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chown(self.state_dir, self.state_uid, self.state_gid, follow_symlinks=False)
        os.chmod(self.state_dir, 0o700, follow_symlinks=False)
        state_info = os.stat(self.state_dir, follow_symlinks=False)
        if (not stat.S_ISDIR(state_info.st_mode) or state_info.st_uid != self.state_uid
                or state_info.st_gid != self.state_gid or stat.S_IMODE(state_info.st_mode) != 0o700):
            raise RuntimeError("runner tombstone volume permissions are invalid")
        # Keep the shared root writable only by the runner, while allowing the
        # DSH UID to traverse to its deterministic leaf. Each leaf itself is
        # owned by the child UID and mode 0700 so DSH owns its private session.
        self.session_root.mkdir(parents=True, exist_ok=True, mode=0o710)
        os.chown(self.session_root, self.runner_uid, self.child_gid, follow_symlinks=False)
        os.chmod(self.session_root, 0o710, follow_symlinks=False)
        session_info = os.stat(self.session_root, follow_symlinks=False)
        if (not stat.S_ISDIR(session_info.st_mode) or session_info.st_uid != self.runner_uid
                or session_info.st_gid != self.child_gid
                or stat.S_IMODE(session_info.st_mode) != 0o710):
            raise RuntimeError("shared judgment session root permissions are invalid")
        control_dir = self.socket_path.parent
        control_dir.mkdir(parents=True, exist_ok=True, mode=0o710)
        os.chown(control_dir, self.runner_uid, self.control_gid, follow_symlinks=False)
        os.chmod(control_dir, 0o710, follow_symlinks=False)
        control_info = os.stat(control_dir, follow_symlinks=False)
        if (not stat.S_ISDIR(control_info.st_mode)
                or control_info.st_uid != self.runner_uid
                or control_info.st_gid != self.control_gid
                or stat.S_IMODE(control_info.st_mode) != 0o710):
            raise RuntimeError("runner control directory permissions are invalid")

    def _clear_ready_file(self) -> None:
        try:
            info = os.lstat(self.ready_file)
        except FileNotFoundError:
            return
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.runner_uid
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError("stale runner readiness marker is not private")
        os.unlink(self.ready_file)

    def _remove_stale_socket(self) -> None:
        try:
            info = os.lstat(self.socket_path)
        except FileNotFoundError:
            return
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.runner_uid
                or info.st_gid != self.control_gid
                or stat.S_IMODE(info.st_mode) != 0o660):
            raise RuntimeError("stale runner control path is not a private socket")
        os.unlink(self.socket_path)

    def _publish_ready(self) -> None:
        self.ready_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.ready_file, flags, 0o600)
        os.fchown(fd, self.runner_uid, self.control_gid)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(b"ready\n")
            output.flush()
            os.fsync(output.fileno())

    def server_close(self) -> None:
        super().server_close()
        try:
            info = os.lstat(self.socket_path)
            if (stat.S_ISSOCK(info.st_mode) and info.st_uid == self.runner_uid
                    and info.st_gid == self.control_gid):
                os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        try:
            info = os.lstat(self.ready_file)
            if stat.S_ISREG(info.st_mode) and info.st_uid == self.runner_uid:
                os.unlink(self.ready_file)
        except FileNotFoundError:
            pass


class _RunnerRequestHandler(socketserver.BaseRequestHandler):
    server: JudgmentRunnerServer

    def handle(self) -> None:
        connection: socket.socket = self.request
        connection.settimeout(AUTH_TIMEOUT_SECONDS)
        challenge = os.urandom(32).hex()
        try:
            challenge_reply = {"v": 1, "challenge": challenge}
            challenge_reply["mac"] = sign_runner_reply(challenge_reply, self.server.secret)
            _send_json(connection, CHALLENGE, challenge_reply)
            value = _read_json_frame(connection, START)
            scope, env, proxy_env, proxy_token, overlay, deadline, nonce = _validate_start(
                value, challenge, self.server.secret)
        except (OSError, ProtocolError, ValueError):
            return
        try:
            digest = _consume_scope(self.server.state_dir, scope, self.server.state_uid,
                                    self.server.state_gid)
        except FileExistsError:
            self._reject(connection, "scope_consumed", challenge, nonce,
                         scope_digest(scope), self.server.secret)
            return
        except OSError:
            self._reject(connection, "state_unavailable", challenge, nonce,
                         scope_digest(scope), self.server.secret)
            return

        session_dir = self.server.session_root / digest
        process: subprocess.Popen[bytes] | None = None
        try:
            # Prepare the private tree while the runner still owns the leaf;
            # after ownership changes to the child UID, the runner deliberately
            # has no DAC override capability with which to traverse it.
            session_dir.mkdir(mode=0o700)
            tmp_dir = session_dir / "tmp"
            tmp_dir.mkdir(mode=0o700)
            overlay_path = _write_private_overlay(
                session_dir, overlay, self.server.child_uid, self.server.child_gid)
            _assign_private_directory(tmp_dir, uid=self.server.child_uid,
                                      gid=self.server.child_gid)
            _assign_private_directory(session_dir, uid=self.server.child_uid,
                                      gid=self.server.child_gid)
            if time.monotonic() >= deadline:
                self._reject(connection, "deadline_expired", challenge, nonce,
                             digest, self.server.secret)
                return
            supervisor_state = _read_proc_table()
            if (not _prctl_child_subreaper()
                    or _read_no_new_privs(os.getpid()) is not True
                    or supervisor_state is None
                    or _has_preexisting_child_uid(supervisor_state, self.server.child_uid)):
                self._reject(connection, "runner_process_fence_unverified", challenge, nonce,
                             digest, self.server.secret)
                return
            assert self.server.launcher is not None
            command = (*self.server.launcher, "--patch", str(overlay_path))
            if not os.path.isfile(command[0]) or not os.access(command[0], os.X_OK):
                raise OSError("fixed ACP launcher is unavailable")
            child_env = _minimal_child_environment(
                env, proxy_env, proxy_token, session_dir, self.server.session_root)
            # The supervisor has no DAC override and cannot chdir into the
            # 0700 DSH-owned leaf. Drop UID first, then let the child enter it.
            child_command = ("/bin/sh", "-c", 'cd "$DSH_HOME" && exec "$@"',
                             "--", *command)
            process = subprocess.Popen(
                child_command,
                cwd="/",
                env=child_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                user=self.server.child_uid,
                group=self.server.child_gid,
                extra_groups=(),
                umask=0o077,
                start_new_session=True,
                bufsize=0,
            )
        except (OSError, ValueError, RuntimeError):
            if process is not None:
                _terminate_and_reap(process, child_uid=self.server.child_uid)
            self._reject(connection, "launch_failed", challenge, nonce,
                         digest, self.server.secret)
            return

        # The child inherits the container's no-new-privileges flag. Verify
        # that before exposing READY, since cleanup ownership relies on the
        # dedicated child UID remaining stable across exec/fork.
        if _read_no_new_privs(process.pid) is not True:
            _terminate_and_reap(process, child_uid=self.server.child_uid)
            self._reject(connection, "child_isolation_unverified", challenge, nonce,
                         digest, self.server.secret)
            return

        connection.settimeout(None)
        try:
            ready_reply = {
                "v": 1, "challenge": challenge, "nonce": nonce,
                "scope_digest": digest, "cwd": str(session_dir),
            }
            ready_reply["mac"] = sign_runner_reply(ready_reply, self.server.secret)
            _send_json(connection, READY, ready_reply)
        except OSError:
            _terminate_and_reap(process, child_uid=self.server.child_uid)
            return
        self._relay(connection, process, deadline, challenge, nonce, digest)

    @staticmethod
    def _reject(connection: socket.socket, code: str, challenge: str,
                nonce: str, digest: str, secret: bytes) -> None:
        try:
            reply = {
                "v": 1, "challenge": challenge, "nonce": nonce,
                "scope_digest": digest, "code": code,
            }
            reply["mac"] = sign_runner_reply(reply, secret)
            _send_json(connection, REJECT, reply)
        except OSError:
            pass

    def _relay(self, connection: socket.socket, process: subprocess.Popen[bytes],
               deadline: float, challenge: str, nonce: str, digest: str) -> None:
        assert process.stdin is not None and process.stdout is not None
        stop = threading.Event()
        output_done = threading.Event()
        state_lock = threading.Lock()
        state: dict[str, str | None] = {"reason": None}

        def set_reason(reason: str) -> None:
            with state_lock:
                if state["reason"] is None:
                    state["reason"] = reason
            stop.set()

        def receive_input() -> None:
            try:
                while not stop.is_set():
                    frame = read_frame(connection)
                    if frame is None:
                        set_reason("transport_lost")
                        return
                    frame_type, payload = frame
                    if frame_type == STDIN and payload:
                        process.stdin.write(payload)
                        process.stdin.flush()
                    elif frame_type == CANCEL and payload == b"":
                        set_reason("cancelled")
                        return
                    else:
                        set_reason("protocol_error")
                        return
            except (OSError, ProtocolError, BrokenPipeError):
                set_reason("transport_lost")
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        def send_output() -> None:
            try:
                while True:
                    data = process.stdout.read(64 * 1024)
                    if not data:
                        return
                    connection.sendall(encode_frame(STDOUT, data))
            except (OSError, ProtocolError):
                set_reason("transport_lost")
            finally:
                output_done.set()

        input_thread = threading.Thread(target=receive_input, name="runner-stdin", daemon=True)
        output_thread = threading.Thread(target=send_output, name="runner-stdout", daemon=True)
        input_thread.start()
        output_thread.start()
        reason: str | None = None
        while True:
            with state_lock:
                requested_reason = state["reason"]
            if requested_reason is not None:
                reason = requested_reason
                break
            if time.monotonic() >= deadline:
                reason = "deadline"
                break
            if process.poll() is not None:
                reason = "process_exit"
                break
            time.sleep(0.02)

        code, child_signal, cleanup = _terminate_and_reap(
            process, child_uid=self.server.child_uid)
        if reason == "process_exit" and not output_done.wait(GROUP_REAP_TIMEOUT_SECONDS):
            cleanup = "unknown"
        if reason != "transport_lost":
            try:
                connection.shutdown(socket.SHUT_RD)
            except OSError:
                pass
        input_thread.join(timeout=GROUP_REAP_TIMEOUT_SECONDS)
        output_thread.join(timeout=GROUP_REAP_TIMEOUT_SECONDS)
        if input_thread.is_alive() or output_thread.is_alive():
            cleanup = "unknown"
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        exit_payload = {
            "v": 1,
            "challenge": challenge,
            "nonce": nonce,
            "scope_digest": digest,
            "code": code if code is not None and code >= 0 else None,
            "signal": child_signal,
            "reason": reason or "protocol_error",
            "cleanup": cleanup,
        }
        if reason != "transport_lost":
            try:
                exit_payload["mac"] = sign_runner_reply(exit_payload, self.server.secret)
                _send_json(connection, EXIT, exit_payload)
            except OSError:
                pass


def _load_secret() -> bytes:
    value = os.environ.get("BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET")
    if value is None:
        raise RuntimeError("runner control secret is missing")
    try:
        secret = base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))
    except (UnicodeError, binascii.Error, ValueError) as exc:
        raise RuntimeError("runner control secret is invalid") from exc
    if len(secret) < 32:
        raise RuntimeError("runner control secret is too short")
    return secret


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("ACP judgment runner must start as container root")
    if os.getpid() != 1:
        raise RuntimeError("ACP judgment runner must be container PID 1")
    if _read_no_new_privs(os.getpid()) is not True:
        raise RuntimeError("ACP judgment runner requires no-new-privileges")
    if not _prctl_child_subreaper(enabled=True) or not _prctl_child_subreaper():
        raise RuntimeError("ACP judgment runner could not enable child subreaper")
    secret = _load_secret()
    server = JudgmentRunnerServer(secret=secret)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
