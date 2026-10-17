"""One-workspace, one-root-at-a-time ACP process owner for Product DSH."""

from __future__ import annotations

import base64
import binascii
import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import importlib.util
import json
import math
import os
import re
import socket
import socketserver
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from packages.contracts.acp_product_slot import (
    ProductSlotContractError,
    canonical_product_json,
    product_scope_digest,
    validate_product_environment,
    validate_product_scope,
)
from packages.contracts.acp_product_instance import (
    INSTANCE_SCHEMA,
    SCOPE_SCHEMA,
    ProductInstanceContractError,
    canonical_json as canonical_instance_json,
    sign_instance,
    sign_instance_started,
    sign_scope_binding,
    validate_instance_started,
)
from packages.contracts.product_turn_request import (
    PRODUCT_TURN_LIMITS,
    product_turn_execution_output_cap,
    product_turn_execution_limits,
    validate_product_turn_execution_profile,
)
from packages.contracts.continuation_request import (
    validate_task_ready_javascript_values_v2,
)


PROTOCOL_VERSION = 1
LEGACY_MAX_RUN_SECONDS = 3600
AUTH_TIMEOUT_SECONDS = 5.0
MAX_FRAME_BYTES = 1_048_576

CHALLENGE = 0x01
START = 0x02
STDIN = 0x03
CANCEL = 0x04
READY = 0x81
REJECT = 0x82
STDOUT = 0x83
EXIT = 0x84

PINNED_DSH_COMMIT = "639ed015397290b3745d163aafe02ffee4aa3f84"
PRODUCT_SESSION_BASE = Path("/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp")
PRODUCT_STATE_ROOT = Path("/var/lib/byq/acp-product-runner-state")
CONTROL_DIRECTORY = Path("/run/byq-acp-product-runner")
CONTROL_SOCKET = CONTROL_DIRECTORY / "control.sock"
CONTROL_READY = CONTROL_DIRECTORY / "ready"
CONTROL_INSTANCE = CONTROL_DIRECTORY / "instance.json"
PRODUCT_PROFILE_PATCH = Path("/opt/byq/profiles/byq-product.patch.yml")
PRODUCT_WORKSPACE_ENV = "BYQ_ACP_PRODUCT_WORKSPACE_ID"
PRODUCT_SECRET_ENV = "BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET"
CONTROL_GID = 10006
CHILD_UID = 10002
CHILD_GID = 10002

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_B64URL = re.compile(r"[A-Za-z0-9_-]+={0,2}\Z")
_WORKSPACE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_RUNNER_REPLY_HMAC_PREFIX = b"byq-acp-runner-reply-v1\0"
_START_KEYS = frozenset({
    "v", "challenge", "nonce", "scope", "env", "deadline_at_ms", "mac",
})
_START_OPTIONAL_KEYS = frozenset({"guard_b64"})
MAX_GUARD_BYTES = 16_384
_GUARD_SCHEMA_NAME = "file:///opt/byq/runtime/byq-continuation-budget.js"
_GUARD_RESERVATION = re.compile(r"continuation_[0-9a-f]{32}\Z")
# Product-scope cleanup proof, distinct from the judgment receipt contract.
_PRODUCT_CLEANUP_RECEIPT_SCHEMA = "byq-acp-product-runner-cleanup.v1"
_CLEANUP_RECEIPT_DIR = "cleanup-receipts"
_INSTANCE_DIRECTORY = "instances"
_SCOPE_BINDING_DIRECTORY = "scope-bindings"
_STATE_LOCK_NAME = ".runner-lifetime.lock"
_ADMISSION_LOCK_NAME = ".runner-admission.lock"


def _valid_local_proxy_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    matched = re.fullmatch(r"http://([0-9.]+):([1-9][0-9]{0,4})", value)
    if matched is None or int(matched[2]) > 65535:
        return False
    import ipaddress
    try:
        address = ipaddress.ip_address(matched[1])
    except ValueError:
        return False
    return (isinstance(address, ipaddress.IPv4Address)
            and any(address in network for network in (
                ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"))))


def _strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate guard key")
        value[key] = item
    return value


def _reject_constant(_value):
    raise ValueError("non-finite guard number")


def _validate_task_ready_guard(value: object) -> dict:
    if not isinstance(value, list) or len(value) != 5:
        raise ProductSlotError("task-ready guard is invalid")
    first, second, default_provider, route, insert = value
    if (not isinstance(first, dict) or set(first) != {"id", "disabled"}
            or first.get("id") != "web-search-deepseek"
            or type(first.get("disabled")) is not bool or first["disabled"] is not True
            or not isinstance(second, dict) or set(second) != {"id", "disabled"}
            or second.get("id") != "tool-web"
            or type(second.get("disabled")) is not bool or second["disabled"] is not True
            or not isinstance(default_provider, dict)
            or set(default_provider) != {"id", "config"}
            or default_provider.get("id") != "llm-deepseek"
            or not isinstance(default_provider.get("config"), dict)):
        raise ProductSlotError("task-ready provider overlay is invalid")
    route_config = route.get("config") if isinstance(route, dict) else None
    providers = route_config.get("providers") if isinstance(route_config, dict) else None
    if not isinstance(route_config, dict) or set(route_config) != {"providers"}:
        raise ProductSlotError("task-ready route overlay is invalid")
    chat = providers.get("opencode-go-chat") if isinstance(providers, dict) else None
    headers = chat.get("headers") if isinstance(chat, dict) else None
    retry_policy = chat.get("retryPolicy") if isinstance(chat, dict) else None
    models = chat.get("models") if isinstance(chat, dict) else None
    if (not isinstance(route, dict) or set(route) != {"id", "config"}
            or route.get("id") != "llm-pi-ai"
            or not isinstance(providers, dict) or set(providers) != {"opencode-go-chat"}
            or not isinstance(chat, dict)
            or set(chat) != {"api", "apiKeyEnv", "baseURL", "retryPolicy", "headers", "models"}
            or chat.get("api") != "openai-completions"
            or chat.get("apiKeyEnv") != "OPENCODE_API_KEY"
            or not _valid_local_proxy_url(chat.get("baseURL"))
            or not isinstance(retry_policy, dict)
            or set(retry_policy) != {"mode", "maxRetries"}
            or retry_policy.get("mode") != "normal"
            or type(retry_policy.get("maxRetries")) is not int
            or retry_policy["maxRetries"] != 0
            or not isinstance(headers, dict) or set(headers) != {"x-opencode-session"}
            or not isinstance(headers.get("x-opencode-session"), str)
            or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                            headers["x-opencode-session"]) is None
            or not isinstance(models, list) or len(models) != 1
            or not isinstance(models[0], dict)
            or models[0].get("id") != "deepseek-v4.1-flash"):
        raise ProductSlotError("task-ready route overlay is invalid")
    if (not isinstance(insert, dict) or set(insert) != {"insert"}
            or not isinstance(insert["insert"], list) or len(insert["insert"]) != 1):
        raise ProductSlotError("task-ready tool guard is invalid")
    entry = insert["insert"][0]
    config = entry.get("config") if isinstance(entry, dict) else None
    if (not isinstance(entry, dict) or set(entry) != {"id", "name", "config"}
            or entry.get("id") != "byq-continuation-budget"
            or entry.get("name") != _GUARD_SCHEMA_NAME
            or not isinstance(config, dict)
            or set(config) != {"guardMode", "rootRunId", "idempotencyKey",
                               "sourceFactSha256", "executionProfile", "requestLimits"}
            or config.get("guardMode") != "task-ready-options"
            or not isinstance(config.get("rootRunId"), str)
            or re.fullmatch(r"[0-9a-f]{32}", config["rootRunId"]) is None
            or not isinstance(config.get("idempotencyKey"), str)
            or re.fullmatch(r"task-ready-event:[0-9a-f]{64}",
                            config["idempotencyKey"]) is None
            or not isinstance(config.get("sourceFactSha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", config["sourceFactSha256"]) is None):
        raise ProductSlotError("task-ready tool guard is invalid")
    try:
        profile, _limits = validate_task_ready_javascript_values_v2(
            config["executionProfile"], config["requestLimits"])
    except (TypeError, ValueError):
        raise ProductSlotError("task-ready profile or limits are invalid") from None
    output_values = [profile["options"][field] for field in (
        "max_output_tokens_per_call", "max_output_tokens_total",
    ) if profile["options"][field] is not None]
    output_cap = min(output_values) if output_values else None
    expected_default = {} if output_cap is None else {"maxTokens": output_cap}
    default_config = default_provider["config"]
    if (set(default_config) != set(expected_default)
            or (output_cap is not None and
                (type(default_config.get("maxTokens")) is not int
                 or default_config["maxTokens"] != output_cap))):
        raise ProductSlotError("task-ready registered provider output cap is invalid")
    expected_model = {"id": "deepseek-v4.1-flash"}
    if output_cap is not None:
        expected_model["maxTokens"] = output_cap
    if (models != [expected_model]
            or (output_cap is not None and type(models[0].get("maxTokens")) is not int)):
        raise ProductSlotError("task-ready model output cap is invalid")
    return value


def _validate_guard(encoded: object) -> dict:
    """Return a closed legacy, ordinary, or task-ready guard overlay.

    Legacy F6 keeps its two disabled web tools and fixed DeepSeek output cap.
    Task-ready keeps those tools disabled and the default adapter registered,
    while applying only an optional user-derived cap to the selected Go route;
    a null user ceiling stays uncapped by this BYQ overlay. Arbitrary plugin
    config and extra entries are refused. The model and browser cannot supply
    any of these trusted guard profiles.
    """
    if not isinstance(encoded, str) or not encoded \
            or len(encoded) > ((MAX_GUARD_BYTES + 2) // 3) * 4:
        raise ProductSlotError("continuation guard is invalid")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeError, binascii.Error, ValueError) as exc:
        raise ProductSlotError("continuation guard is invalid") from exc
    if len(raw) > MAX_GUARD_BYTES:
        raise ProductSlotError("continuation guard exceeds its bound")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object,
                           parse_constant=_reject_constant)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise ProductSlotError("continuation guard is invalid") from exc
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], dict) \
            and value[0].get("id") == "llm-pi-ai":
        # Ordinary Product overlays have an explicit mode. v1 is retained for
        # already-qualified receipts; newly generated ordinary roots must use
        # v2 with the exact trusted options revision and no legacy defaults.
        route = value[0]
        route_config = route.get("config") if set(route) == {"id", "config"} else None
        providers = route_config.get("providers") if isinstance(route_config, dict) else None
        chat = providers.get("opencode-go-chat") if isinstance(providers, dict) else None
        if (not isinstance(providers, dict) or set(providers) != {"opencode-go-chat"}
                or not isinstance(chat, dict)
                or set(chat) != {"api", "apiKeyEnv", "baseURL", "retryPolicy", "headers", "models"}
                or chat.get("api") != "openai-completions"
                or chat.get("apiKeyEnv") != "OPENCODE_API_KEY"
                or not _valid_local_proxy_url(chat.get("baseURL"))
                or chat.get("retryPolicy") != {"mode": "normal", "maxRetries": 0}
                or not isinstance(chat.get("headers"), dict)
                or set(chat["headers"]) != {"x-opencode-session"}
                or not isinstance(chat["headers"]["x-opencode-session"], str)
                or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                                chat["headers"]["x-opencode-session"]) is None
                or not isinstance(chat.get("models"), list) or len(chat["models"]) != 1
                or not isinstance(chat["models"][0], dict)
                or chat["models"][0].get("id") != "deepseek-v4.1-flash"):
            raise ProductSlotError("product-turn route overlay is invalid")
        insert = value[1]
        entry = (insert.get("insert") if isinstance(insert, dict) and set(insert) == {"insert"}
                 else None)
        guard_config = (entry[0].get("config")
                        if isinstance(entry, list) and len(entry) == 1
                        and isinstance(entry[0], dict)
                        and set(entry[0]) == {"id", "name", "config"} else None)
        profile = (guard_config.get("executionProfile")
                   if isinstance(guard_config, dict) else None)
        limits = (guard_config.get("requestLimits")
                  if isinstance(guard_config, dict) else None)
        if (not isinstance(entry, list) or len(entry) != 1
                or entry[0].get("id") != "byq-continuation-budget"
                or entry[0].get("name") != "file:///opt/byq/runtime/byq-continuation-budget.js"
                or not isinstance(guard_config, dict)):
            raise ProductSlotError("product-turn tool guard is invalid")
        guard_mode = guard_config.get("guardMode")
        if guard_mode == "count-only":
            # The Adapter sends the PRE-injection overlay: exactly the closed
            # identity + limits, and NEVER a journalPath. Keep legacy F6/v1
            # validation unchanged; the trusted Adapter owns the on-disk path.
            if (set(guard_config) != {"guardMode", "deadlineEpochMs", "executionProfile",
                                     "requestLimits"}
                    or type(guard_config.get("deadlineEpochMs")) is not int
                    or guard_config["deadlineEpochMs"] <= 0
                    or not isinstance(profile, dict)
                    or set(profile) != {"profile_id", "profile_version", "profile_sha256"}
                    or profile.get("profile_id") != "product-turn.v1"
                    or profile.get("profile_version") != 1
                    or not isinstance(profile.get("profile_sha256"), str)
                    or re.fullmatch(r"[a-f0-9]{64}", profile["profile_sha256"]) is None
                    or not isinstance(limits, dict) or limits != PRODUCT_TURN_LIMITS):
                raise ProductSlotError("product-turn tool guard is invalid")
            return value
        if guard_mode != "ordinary-options":
            raise ProductSlotError("product-turn tool guard mode is invalid")
        try:
            execution_profile = validate_product_turn_execution_profile(profile)
            expected_limits = product_turn_execution_limits(execution_profile["options"])
        except (TypeError, ValueError):
            raise ProductSlotError("ordinary execution profile is invalid") from None
        if (set(guard_config) != {"guardMode", "executionProfile", "requestLimits"}
                or not isinstance(limits, dict) or limits != expected_limits):
            raise ProductSlotError("ordinary execution limits are invalid")
        output_limit = product_turn_execution_output_cap(execution_profile["options"])
        expected_model = {"id": "deepseek-v4.1-flash"}
        if output_limit is not None:
            expected_model["maxTokens"] = output_limit
        if chat["models"] != [expected_model]:
            raise ProductSlotError("ordinary output parameter does not match options")
        return value
    if not isinstance(value, list) or len(value) != 5:
        raise ProductSlotError("continuation guard is invalid")
    disable_a, disable_b, disable_ds, route, insert = value
    task_ready_config = (insert.get("insert")[0].get("config")
                         if isinstance(insert, dict)
                         and isinstance(insert.get("insert"), list)
                         and len(insert["insert"]) == 1
                         and isinstance(insert["insert"][0], dict)
                         else None)
    if (isinstance(task_ready_config, dict)
            and task_ready_config.get("guardMode") == "task-ready-options"):
        return _validate_task_ready_guard(value)
    if (not isinstance(disable_a, dict) or set(disable_a) != {"id", "disabled"}
            or disable_a["id"] != "web-search-deepseek" or disable_a["disabled"] is not True):
        raise ProductSlotError("continuation guard is invalid")
    if (not isinstance(disable_b, dict) or set(disable_b) != {"id", "disabled"}
            or disable_b["id"] != "tool-web" or disable_b["disabled"] is not True):
        raise ProductSlotError("continuation guard is invalid")
    if (not isinstance(disable_ds, dict) or set(disable_ds) != {"id", "config"}
            or disable_ds["id"] != "llm-deepseek" or not isinstance(disable_ds["config"], dict)
            or set(disable_ds["config"]) != {"maxTokens"}
            or type(disable_ds["config"]["maxTokens"]) is not int
            or not 1 <= disable_ds["config"]["maxTokens"] <= 8192):
        raise ProductSlotError("continuation guard is invalid")
    providers = (route.get("config", {}).get("providers")
                 if isinstance(route, dict) and set(route) == {"id", "config"} else None)
    chat = providers.get("opencode-go-chat") if isinstance(providers, dict) else None
    if (route.get("id") != "llm-pi-ai" or not isinstance(providers, dict)
            or set(providers) != {"opencode-go-chat"} or not isinstance(chat, dict)
            or set(chat) != {"api", "apiKeyEnv", "baseURL", "retryPolicy", "headers", "models"}
            or chat.get("api") != "openai-completions"
            or chat.get("apiKeyEnv") != "OPENCODE_API_KEY"
            or not _valid_local_proxy_url(chat.get("baseURL"))
            or chat.get("retryPolicy") != {"mode": "normal", "maxRetries": 0}
            or not isinstance(chat.get("headers"), dict)
            or set(chat["headers"]) != {"x-opencode-session"}
            or not isinstance(chat["headers"]["x-opencode-session"], str)
            or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                            chat["headers"]["x-opencode-session"]) is None
            or not isinstance(chat.get("models"), list) or len(chat["models"]) != 1
            or chat["models"][0].get("id") != "deepseek-v4.1-flash"
            or type(chat["models"][0].get("maxTokens")) is not int
            or not 1 <= chat["models"][0]["maxTokens"] <= 8192):
        raise ProductSlotError("continuation guard is invalid")
    if (not isinstance(insert, dict) or set(insert) != {"insert"}
            or not isinstance(insert["insert"], list) or len(insert["insert"]) != 1):
        raise ProductSlotError("continuation guard is invalid")
    entry = insert["insert"][0]
    if (not isinstance(entry, dict) or set(entry) != {"id", "name", "config"}
            or entry["id"] != "byq-continuation-budget" or entry["name"] != _GUARD_SCHEMA_NAME
            or not isinstance(entry["config"], dict)
            or set(entry["config"]) != {
                "deadlineEpochMs", "reservationId", "executionProfile", "requestLimits"}
            or type(entry["config"]["deadlineEpochMs"]) is not int
            or entry["config"]["deadlineEpochMs"] <= int(time.time() * 1000)
            or not isinstance(entry["config"]["reservationId"], str)
            or _GUARD_RESERVATION.fullmatch(entry["config"]["reservationId"]) is None
            or not isinstance(entry["config"]["executionProfile"], dict)
            or not isinstance(entry["config"]["requestLimits"], dict)):
        raise ProductSlotError("continuation guard is invalid")
    return value


def _load_judgment_helpers():
    """Load reviewed framing and process cleanup helpers from the image copy."""
    candidates = (
        Path(__file__).resolve().parents[1] / "acp_judgment_runner" / "server.py",
        Path("/opt/byq/acp_judgment_runner/server.py"),
    )
    source = next((item for item in candidates if item.is_file()), None)
    if source is None:
        raise RuntimeError("shared ACP process helpers are unavailable")
    name = "_byq_acp_judgment_runner_helpers"
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError("shared ACP process helpers cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_helpers = _load_judgment_helpers()


class ProductSlotError(ValueError):
    """Malformed or unauthorized Product slot request."""


class RetireSlot(SystemExit):
    """Exit this dedicated slot container after an unproven root cleanup."""


def _reply_mac(value: dict[str, Any], secret: bytes) -> str:
    if "mac" in value:
        raise ProductSlotError("reply MAC input must omit mac")
    return hmac.new(
        secret, _RUNNER_REPLY_HMAC_PREFIX + canonical_product_json(value), hashlib.sha256,
    ).hexdigest()


def _decode_secret(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 512 or _B64URL.fullmatch(value) is None:
        raise RuntimeError("Product runner control secret is invalid")
    try:
        secret = base64.b64decode(
            value.encode("ascii") + b"=" * ((-len(value)) % 4),
            altchars=b"-_", validate=True,
        )
    except (UnicodeError, binascii.Error, ValueError) as exc:
        raise RuntimeError("Product runner control secret is invalid") from exc
    if len(secret) < 32:
        raise RuntimeError("Product runner control secret is too short")
    return secret


def _persist_product_cleanup_receipt(control_dir: Path, scope: dict[str, Any],
                                     digest: str, instance_id: str,
                                     exit_fields: dict[str, Any], secret: bytes,
                                     control_gid: int) -> None:
    """Durably record the signed proven-cleanup receipt for a Product scope.

    Binds the complete Product scope (workspace/owner/session/trace/root/boot/
    generation/cwd), the exact scope digest, the runner instance and the real
    cleanup result. Written atomically (temp + fsync + rename + dir fsync) and
    signed with the runner reply MAC. Any failure must leave cleanup unknown.
    """
    checked = validate_product_scope(scope)
    if product_scope_digest(checked) != digest:
        raise ValueError("Product cleanup scope digest is invalid")
    payload = {
        "schema_version": _PRODUCT_CLEANUP_RECEIPT_SCHEMA,
        "scope_digest": digest,
        "workspace_id": checked["workspace_id"],
        "owner_principal": checked["owner_principal"],
        "session_id": checked["session_id"],
        "trace_id": checked["trace_id"],
        "root_run_id": checked["root_run_id"],
        "runtime_boot_id": checked["runtime_boot_id"],
        "generation_id": checked["generation_id"],
        "cwd_leaf": checked["cwd_leaf"],
        "runner_instance_id": instance_id,
        "code": exit_fields["code"],
        "signal": exit_fields["signal"],
        "reason": exit_fields["reason"],
        "cleanup": "proven",
    }
    payload["mac"] = _reply_mac(payload, secret)
    directory = Path(control_dir) / _CLEANUP_RECEIPT_DIR
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        os.chown(directory, 0, control_gid)
    except OSError:
        pass
    path = directory / f"{digest}.json"
    temporary = directory / f".{digest}.{os.urandom(8).hex()}.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                 | getattr(os, "O_NOFOLLOW", 0), 0o640)
    try:
        os.write(fd, canonical_product_json(payload))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.chown(temporary, 0, control_gid)
    except OSError:
        pass
    os.rename(temporary, path)
    dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _canonical_directory(path: Path) -> Path:
    """Resolve an existing directory without accepting symlinks in its leaf."""
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("Product runner storage path is not a directory")
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise OSError("Product runner storage path is not canonical")
    return resolved


def _prepare_root_directory(path: Path, *, uid: int, gid: int, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    _canonical_directory(path)
    os.chown(path, uid, gid, follow_symlinks=False)
    os.chmod(path, mode, follow_symlinks=False)
    info = os.lstat(path)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != mode):
        raise OSError("Product runner directory permissions are invalid")


def _verify_root_directory(path: Path, *, uid: int, gid: int, mode: int) -> None:
    _canonical_directory(path)
    info = os.lstat(path)
    if (info.st_uid != uid or info.st_gid != gid or stat.S_IMODE(info.st_mode) != mode):
        raise OSError("Product runner read-only parent permissions are invalid")


def _minimal_child_environment(env: dict[str, str], home: Path,
                               session_root: Path, runtime_root: Path) -> dict[str, str]:
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
    # The input is already validated against the closed Product slot contract;
    # only that explicit field can carry the dedicated search credential.
    result.update(env)
    for forbidden in (
        "BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET",
        "BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET",
        "BYQ_ACP_JUDGMENT_RUNNER_SECRET",
        "BYQ_RUNTIME_AUTHORITY_TOKEN", "BYQ_RUNTIME_JUDGMENT_TOKEN",
        "BYQ_BACKEND_AUTHORITY_TOKEN", "BYQ_MCP_BACKEND_PROOF_TOKEN",
        "BYQ_MCP_TOKEN", "BYQ_PRODUCT_TOKEN", "BYQ_GATEWAY_SERVICE_TOKEN",
        "BYQ_CREDENTIAL_RESOLVER_TOKEN", "BYQ_MCP_READ_ONLY_TOKEN",
        "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY", "BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN",
        "DEEPSEEK_API_KEY_UPSTREAM", "OPENCODE_API_KEY_UPSTREAM",
        "DEEPSEEK_BASE_URL", "DEEPSEEK_SEARCH_BASE_URL",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
        "all_proxy", "NO_PROXY", "no_proxy", "NODE_OPTIONS", "NODE_PATH",
        "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
    ):
        result.pop(forbidden, None)
    # The byq-acp-mcp-identity plugin resolves the official MCP client from this
    # runner-owned runtime root. Set it after the allowlisted env merge and the
    # forbidden pop so no Product-supplied value (present or future allowlist
    # expansion) can redirect the fixed launcher.
    result["BYQ_DSH_RUNTIME_ROOT"] = str(runtime_root)
    return result


class ProductSlotServer(socketserver.UnixStreamServer):
    """Synchronous daemon for one fixed workspace and one active root at a time."""

    allow_reuse_address = False
    request_queue_size = 1

    def __init__(
        self,
        *,
        secret: bytes,
        workspace_id: str,
        socket_path: Path = CONTROL_SOCKET,
        control_directory: Path = CONTROL_DIRECTORY,
        session_base: Path = PRODUCT_SESSION_BASE,
        state_dir: Path = PRODUCT_STATE_ROOT,
        profile_patch: Path = PRODUCT_PROFILE_PATCH,
        runtime_root: Path = Path("/opt/dsh-runtime"),
        launcher: tuple[str, ...] | None = None,
        child_uid: int = CHILD_UID,
        child_gid: int = CHILD_GID,
        runner_uid: int = 0,
        control_gid: int = CONTROL_GID,
        state_gid: int = 0,
        prepare_roots: bool = True,
        ready_file: Path = CONTROL_READY,
        instance_descriptor: Path | None = None,
    ) -> None:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("Product runner control secret is invalid")
        if not isinstance(workspace_id, str) or _WORKSPACE_ID.fullmatch(workspace_id) is None:
            raise ValueError("Product runner workspace identity is invalid")
        self.secret = secret
        # One opaque identity per runner process for the signed cleanup receipt.
        self.instance_id = os.urandom(32).hex()
        self.workspace_id = workspace_id
        self.session_base = Path(session_base)
        self.session_root = self.session_base / workspace_id
        self.state_dir = Path(state_dir)
        self.profile_patch = Path(profile_patch)
        self.runtime_root = Path(runtime_root)
        self.child_uid = child_uid
        self.child_gid = child_gid
        self.runner_uid = runner_uid
        self.control_gid = control_gid
        self.state_gid = state_gid
        self.socket_path = Path(socket_path)
        self.control_directory = Path(control_directory)
        self.ready_file = Path(ready_file)
        self.instance_descriptor = (Path(instance_descriptor) if instance_descriptor is not None
                                    else self.control_directory / CONTROL_INSTANCE.name)
        if self.instance_descriptor.parent != self.control_directory:
            raise ValueError("Product runner instance descriptor must be in its control directory")
        self.retire_requested = False
        self.launcher = launcher
        self._state_lock_fd: int | None = None
        self._admission_lock_fd: int | None = None
        self._instance_record: dict[str, object] | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._ready_identity: tuple[int, int] | None = None
        self._instance_descriptor_identity: tuple[int, int] | None = None

        if self.session_root.name != workspace_id or self.session_root.parent != self.session_base:
            raise ValueError("Product runner session root is not workspace-canonical")
        if prepare_roots:
            self._prepare_roots()
        # Acquire the private state-volume lock before touching any old control
        # socket or readiness marker. It protects this volume for the complete
        # runner lifetime; it is not evidence that another container stopped.
        self._acquire_state_locks()
        try:
            self._persist_instance_record()
            if self.launcher is None:
                self.launcher = _helpers._make_launcher(self.runtime_root, self.profile_patch)
            self._remove_stale_file(self.ready_file, socket_file=False,
                                    group=self.control_gid, mode=0o600)
            self._remove_stale_file(self.socket_path, socket_file=True,
                                    group=self.control_gid, mode=0o660)
            self._remove_stale_file(self.instance_descriptor, socket_file=False,
                                    group=self.control_gid, mode=0o640)
            control_dir_fd = os.open(
                self.control_directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                # Make removal of the old workspace-only ready sentinel durable
                # before a new instance pointer can become visible.
                os.fsync(control_dir_fd)
            finally:
                os.close(control_dir_fd)
            # Publish the current signed instance before bind/listen makes the
            # control socket accept any Adapter connection.
            self._publish_instance_descriptor()
            super().__init__(str(self.socket_path), _ProductRequestHandler,
                             bind_and_activate=True)
            self._socket_identity = self._path_identity(self.socket_path)
            os.chown(self.socket_path, self.runner_uid, self.control_gid, follow_symlinks=False)
            os.chmod(self.socket_path, 0o660, follow_symlinks=False)
            info = os.stat(self.socket_path, follow_symlinks=False)
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.runner_uid
                    or info.st_gid != self.control_gid
                    or stat.S_IMODE(info.st_mode) != 0o660):
                raise RuntimeError("Product ACP control socket permissions are invalid")
            self._publish_ready()
        except BaseException:
            try:
                self._close_owned_startup_resources()
            except BaseException:
                pass
            raise

    def _prepare_roots(self) -> None:
        _prepare_root_directory(self.state_dir, uid=self.runner_uid,
                                gid=self.state_gid, mode=0o700)
        _verify_root_directory(self.session_base, uid=self.runner_uid,
                               gid=self.child_gid, mode=0o710)
        _prepare_root_directory(self.session_root, uid=self.runner_uid,
                                gid=self.child_gid, mode=0o770)
        _prepare_root_directory(self.control_directory, uid=self.runner_uid,
                                gid=self.control_gid, mode=0o710)

    def server_bind(self) -> None:
        # Capture the filesystem socket identity immediately after bind, before
        # server_activate or later permission/readiness steps can fail.
        super().server_bind()
        self._socket_identity = self._path_identity(self.socket_path)

    def _acquire_state_locks(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _canonical_directory(self.state_dir)
        state_info = os.lstat(self.state_dir)
        if (state_info.st_uid != self.runner_uid or state_info.st_gid != self.state_gid
                or stat.S_IMODE(state_info.st_mode) != 0o700):
            raise RuntimeError("Product runner private state directory is invalid")
        try:
            for name, target in ((_STATE_LOCK_NAME, "state"),
                                 (_ADMISSION_LOCK_NAME, "admission")):
                path = self.state_dir / name
                flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(path, flags, 0o600)
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != self.runner_uid or info.st_gid != self.state_gid
                        or stat.S_IMODE(info.st_mode) != 0o600):
                    os.close(descriptor)
                    raise RuntimeError("Product runner private state lock is invalid")
                if target == "state":
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError:
                        os.close(descriptor)
                        raise RuntimeError("Product runner state volume is already owned") from None
                    self._state_lock_fd = descriptor
                else:
                    self._admission_lock_fd = descriptor
            instances = self.state_dir / _INSTANCE_DIRECTORY
            bindings = self.state_dir / _SCOPE_BINDING_DIRECTORY
            _prepare_root_directory(instances, uid=self.runner_uid,
                                    gid=self.state_gid, mode=0o700)
            _prepare_root_directory(bindings, uid=self.runner_uid,
                                    gid=self.state_gid, mode=0o700)
        except BaseException:
            self._release_state_locks()
            raise

    def _release_state_locks(self) -> None:
        for name in ("_admission_lock_fd", "_state_lock_fd"):
            descriptor = getattr(self, name)
            if descriptor is not None:
                setattr(self, name, None)
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _persist_instance_record(self) -> None:
        assert self._state_lock_fd is not None
        record = sign_instance({
            "schema_version": INSTANCE_SCHEMA,
            "workspace_id": self.workspace_id,
            "runner_instance_id": self.instance_id,
            "runner_boot_id": os.urandom(16).hex(),
            "state_generation": self._state_generation(),
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "operator_qualified": False,
            # Reserved for the later Engineering/Backend prebind. A null value
            # explicitly means this instance is not process-proof qualified.
            "deployment_binding_sha256": None,
            "backend_binding_nonce": None,
        }, key=self.secret)
        self._persist_immutable_record(
            self.state_dir / _INSTANCE_DIRECTORY / f"{self.instance_id}.json", record,
        )
        self._instance_record = record

    def _publish_instance_descriptor(self) -> None:
        if self._instance_record is None:
            raise OSError("Product runner instance record is unavailable")
        directory = self.instance_descriptor.parent
        _canonical_directory(directory)
        temporary = directory / f".{self.instance_descriptor.name}.{os.urandom(8).hex()}.tmp"
        data = canonical_instance_json(self._instance_record)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.fchown(descriptor, self.runner_uid, self.control_gid)
            os.fchmod(descriptor, 0o640)
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write to Product runner control instance")
                view = view[written:]
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        else:
            os.close(descriptor)
        temporary_info = os.lstat(temporary)
        if (not stat.S_ISREG(temporary_info.st_mode) or temporary_info.st_nlink != 1
                or temporary_info.st_uid != self.runner_uid
                or temporary_info.st_gid != self.control_gid
                or stat.S_IMODE(temporary_info.st_mode) != 0o640):
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise OSError("Product runner control instance staging file is invalid")
        # Record the staged inode before linking so startup-failure cleanup can
        # remove the pointer even if the post-link verification itself fails.
        self._instance_descriptor_identity = (temporary_info.st_dev, temporary_info.st_ino)
        try:
            # link() publishes without replacing a retained or concurrent
            # control pointer. The temporary is removed after the link.
            os.link(temporary, self.instance_descriptor, follow_symlinks=False)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        info = os.lstat(self.instance_descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != self.runner_uid or info.st_gid != self.control_gid
                or stat.S_IMODE(info.st_mode) != 0o640):
            raise OSError("Product runner control instance permissions are invalid")
        read_fd = os.open(self.instance_descriptor,
                          os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(read_fd)
            raw = bytearray()
            while len(raw) <= len(data):
                block = os.read(read_fd, min(4096, len(data) + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            after = os.fstat(read_fd)
            if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                    or bytes(raw) != data or len(raw) != after.st_size):
                raise OSError("Product runner control instance changed while publishing")
        finally:
            os.close(read_fd)

    def _state_generation(self) -> str:
        path = self.state_dir / ".state-generation"
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            value = os.urandom(32).hex()
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0), 0o600,
            )
            try:
                os.fchown(descriptor, self.runner_uid, self.state_gid)
                os.fchmod(descriptor, 0o600)
                payload = (value + "\n").encode("ascii")
                if os.write(descriptor, payload) != len(payload):
                    raise OSError("short write to Product runner state generation")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            directory_fd = os.open(self.state_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return value
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != self.runner_uid or info.st_gid != self.state_gid
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError("Product runner state generation is invalid")
        raw = path.read_bytes()
        if len(raw) != 65 or raw[-1:] != b"\n":
            raise RuntimeError("Product runner state generation is invalid")
        value = raw[:-1].decode("ascii", errors="strict")
        if _HEX64.fullmatch(value) is None:
            raise RuntimeError("Product runner state generation is invalid")
        return value

    def _persist_immutable_record(self, path: Path, record: dict[str, object]) -> None:
        directory = path.parent
        _canonical_directory(directory)
        temporary = directory / f".{path.name}.{os.urandom(8).hex()}.tmp"
        data = canonical_instance_json(record)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.fchown(descriptor, self.runner_uid, self.state_gid)
            os.fchmod(descriptor, 0o600)
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write to Product runner state")
                view = view[written:]
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        else:
            os.close(descriptor)
        try:
            # link() gives immutable O_EXCL semantics; rename would overwrite a
            # retained identity or consumed scope if a digest were reused.
            os.link(temporary, path, follow_symlinks=False)
        finally:
            os.unlink(temporary)
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        info = os.lstat(path)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != self.runner_uid or info.st_gid != self.state_gid
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise OSError("Product runner state record permissions are invalid")

    @contextlib.contextmanager
    def _admission_guard(self):
        descriptor = self._admission_lock_fd
        if descriptor is None:
            raise RuntimeError("Product runner admission lock is unavailable")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)

    def _persist_scope_ownership(self, scope: dict[str, str], digest: str) -> None:
        if self._instance_record is None:
            raise OSError("Product runner instance record is unavailable")
        record = sign_scope_binding({
            "schema_version": SCOPE_SCHEMA,
            "scope_digest": digest,
            "scope": dict(scope),
            "runner_instance_id": self.instance_id,
            "runner_boot_id": self._instance_record["runner_boot_id"],
            "state_generation": self._instance_record["state_generation"],
            "operator_qualified": False,
            "deployment_binding_sha256": None,
            "backend_binding_nonce": None,
            "dispatch_state": "may_have_dispatched",
        }, key=self.secret, instance=self._instance_record)
        self._persist_immutable_record(
            self.state_dir / _SCOPE_BINDING_DIRECTORY / f"{digest}.json", record,
        )

    def _persist_instance_started_marker(self) -> None:
        """Durably record that this instance may have accepted a START."""
        if self._instance_record is None:
            raise OSError("Product runner instance record is unavailable")
        path = (self.state_dir / _INSTANCE_DIRECTORY
                / f"{self.instance_id}.started.json")
        try:
            raw, identity = self._read_instance_started_marker(path)
        except FileNotFoundError:
            marker = sign_instance_started({
                "schema_version": "byq-acp-product-runner-started.v1",
                "workspace_id": self.workspace_id,
                "runner_instance_id": self.instance_id,
                "runner_boot_id": self._instance_record["runner_boot_id"],
                "state_generation": self._instance_record["state_generation"],
                "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }, key=self.secret, instance=self._instance_record)
            try:
                self._persist_immutable_record(path, marker)
            except FileExistsError:
                # A concurrent/previous write is reusable only if it is the
                # exact authenticated marker for this immutable instance.
                pass
            # Read back the exact immutable inode. This also lets recovery from
            # a prior parent-directory fsync error finish durability before
            # START proceeds.
            raw, identity = self._read_instance_started_marker(path)
        try:
            validate_instance_started(raw, key=self.secret, instance=self._instance_record)
        except ProductInstanceContractError as exc:
            raise OSError("Product runner started marker is invalid") from exc
        self._fsync_instance_started_marker(path, identity)

    def _read_instance_started_marker(
        self, path: Path,
    ) -> tuple[object, tuple[int, int]]:
        try:
            before = os.lstat(path)
        except FileNotFoundError:
            raise
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != self.runner_uid or before.st_gid != self.state_gid
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > 4096):
            raise OSError("Product runner started marker permissions are invalid")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_uid != self.runner_uid or opened.st_gid != self.state_gid
                    or stat.S_IMODE(opened.st_mode) != 0o600 or opened.st_size > 4096):
                raise OSError("Product runner started marker changed while opening")
            raw = bytearray()
            while len(raw) <= 4096:
                block = os.read(descriptor, min(4096, 4097 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            after = os.fstat(descriptor)
            if (len(raw) > 4096 or len(raw) != after.st_size
                    or (opened.st_dev, opened.st_ino, opened.st_size,
                        opened.st_mtime_ns, opened.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns)):
                raise OSError("Product runner started marker changed while reading")
        finally:
            os.close(descriptor)
        try:
            value = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_strict_object,
                               parse_constant=_reject_constant)
        except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
            raise OSError("Product runner started marker JSON is invalid") from exc
        return value, (opened.st_dev, opened.st_ino)

    def _fsync_instance_started_marker(
        self, path: Path, expected_identity: tuple[int, int],
    ) -> None:
        expected_path = (self.state_dir / _INSTANCE_DIRECTORY
                         / f"{self.instance_id}.started.json")
        if path != expected_path:
            raise OSError("Product runner started marker path is invalid")
        directory = path.parent
        _canonical_directory(directory)
        directory_info = os.lstat(directory)
        if (directory_info.st_uid != self.runner_uid
                or directory_info.st_gid != self.state_gid
                or stat.S_IMODE(directory_info.st_mode) != 0o700):
            raise OSError("Product runner started marker directory is not private")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            if ((info.st_dev, info.st_ino) != expected_identity
                    or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != self.runner_uid or info.st_gid != self.state_gid
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
                raise OSError("Product runner started marker changed before fsync")
            os.fsync(descriptor)
            after = os.fstat(descriptor)
            if ((after.st_dev, after.st_ino) != expected_identity
                    or after.st_size != info.st_size):
                raise OSError("Product runner started marker changed during fsync")
        finally:
            os.close(descriptor)
        directory_fd = os.open(
            directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened_directory = os.fstat(directory_fd)
            if ((opened_directory.st_dev, opened_directory.st_ino)
                    != (directory_info.st_dev, directory_info.st_ino)
                    or opened_directory.st_uid != self.runner_uid
                    or opened_directory.st_gid != self.state_gid
                    or stat.S_IMODE(opened_directory.st_mode) != 0o700):
                raise OSError("Product runner started marker directory changed")
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _remove_stale_file(path: Path, *, socket_file: bool,
                           group: int, mode: int) -> None:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return
        correct_type = stat.S_ISSOCK(info.st_mode) if socket_file else stat.S_ISREG(info.st_mode)
        if (not correct_type or info.st_uid != os.geteuid() or info.st_gid != group
                or stat.S_IMODE(info.st_mode) != mode):
            raise RuntimeError("stale Product runner control path is not private")
        os.unlink(path)

    @staticmethod
    def _path_identity(path: Path) -> tuple[int, int]:
        info = os.lstat(path)
        return info.st_dev, info.st_ino

    @staticmethod
    def _unlink_if_owned(path: Path, identity: tuple[int, int] | None,
                         *, socket_file: bool) -> None:
        if identity is None:
            return
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return
        correct_type = stat.S_ISSOCK(info.st_mode) if socket_file else stat.S_ISREG(info.st_mode)
        if correct_type and (info.st_dev, info.st_ino) == identity:
            os.unlink(path)

    def _close_owned_startup_resources(self) -> None:
        if hasattr(self, "socket"):
            try:
                socketserver.UnixStreamServer.server_close(self)
            except BaseException:
                pass
        for path, identity, socket_file in (
            (self.socket_path, self._socket_identity, True),
            (self.ready_file, self._ready_identity, False),
            (self.instance_descriptor, self._instance_descriptor_identity, False),
        ):
            try:
                self._unlink_if_owned(path, identity, socket_file=socket_file)
            except OSError:
                pass
        self._release_state_locks()

    def _publish_ready(self) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.ready_file, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            self._ready_identity = (info.st_dev, info.st_ino)
            os.fchown(descriptor, self.runner_uid, self.control_gid)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write((self.workspace_id + "\n").encode("ascii"))
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise

    def _consume_scope(self, scope: dict[str, str]) -> str:
        digest = product_scope_digest(scope)
        marker = self.state_dir / f"{digest}.used"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(marker, flags, 0o600)
        try:
            os.fchown(descriptor, self.runner_uid, self.state_gid)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(b"byq-acp-product-slot-one-shot.v1\n")
                output.flush()
                os.fsync(output.fileno())
            directory_fd = os.open(
                self.state_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
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
        info = os.lstat(marker)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.runner_uid
                or info.st_gid != self.state_gid or stat.S_IMODE(info.st_mode) != 0o600):
            raise OSError("Product scope tombstone permissions are invalid")
        return digest

    def service_actions(self) -> None:
        if self.retire_requested:
            raise RetireSlot(70)

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            try:
                self._unlink_if_owned(self.socket_path, self._socket_identity,
                                      socket_file=True)
            finally:
                try:
                    self._unlink_if_owned(self.ready_file, self._ready_identity,
                                          socket_file=False)
                finally:
                    try:
                        self._unlink_if_owned(self.instance_descriptor,
                                              self._instance_descriptor_identity,
                                              socket_file=False)
                    finally:
                        self._release_state_locks()


class _ProductRequestHandler(_helpers._RunnerRequestHandler):
    server: ProductSlotServer

    def handle(self) -> None:
        connection: socket.socket = self.request
        connection.settimeout(AUTH_TIMEOUT_SECONDS)
        challenge = os.urandom(32).hex()
        try:
            challenge_reply = {"v": PROTOCOL_VERSION, "challenge": challenge}
            challenge_reply["mac"] = _reply_mac(challenge_reply, self.server.secret)
            _helpers._send_json(connection, CHALLENGE, challenge_reply)
            value = _helpers._read_json_frame(connection, START)
            scope, raw_env, deadline, nonce, guard = self._validate_start(
                value, challenge, self.server.secret,
            )
        except (OSError, ProductSlotError, _helpers.ProtocolError,
                ProductSlotContractError, ValueError):
            return

        if scope["workspace_id"] != self.server.workspace_id:
            self._reject(connection, "workspace_mismatch", challenge, nonce,
                         product_scope_digest(scope))
            return
        try:
            env = validate_product_environment(raw_env, scope)
        except ProductSlotContractError:
            self._reject(connection, "environment_rejected", challenge, nonce,
                         product_scope_digest(scope))
            return
        try:
            with self.server._admission_guard():
                # This durable per-instance fact precedes tombstone consumption,
                # scope ownership, and any child dispatch. It only means this
                # instance may have accepted START; it is not cleanup or proof
                # that no business effect occurred.
                self.server._persist_instance_started_marker()
                digest = self.server._consume_scope(scope)
                self.server._persist_scope_ownership(scope, digest)
        except FileExistsError:
            self._reject(connection, "scope_consumed", challenge, nonce,
                         product_scope_digest(scope))
            return
        except (OSError, ProductInstanceContractError):
            self._reject(connection, "state_unavailable", challenge, nonce,
                         product_scope_digest(scope))
            return

        if deadline is not None and time.monotonic() >= deadline:
            # The durable one-shot tombstone has already been written. Report
            # that this exact scope is consumed so the client does not treat
            # the reject as a retryable prelaunch failure.
            self._reject(connection, "scope_consumed", challenge, nonce, digest)
            return

        cwd = self.server.session_root / scope["cwd_leaf"]
        process: subprocess.Popen[bytes] | None = None
        try:
            self._prepare_cwd(cwd)
            proc_table = _helpers._read_proc_table()
            if (not _helpers._prctl_child_subreaper()
                    or _helpers._read_no_new_privs(os.getpid()) is not True
                    or proc_table is None
                    or _helpers._has_preexisting_child_uid(proc_table, self.server.child_uid)):
                self._reject(connection, "runner_process_fence_unverified", challenge,
                             nonce, digest)
                return
            assert self.server.launcher is not None
            child_env = _minimal_child_environment(
                env, cwd, self.server.session_root, self.server.runtime_root)
            child_command = (
                "/bin/sh", "-c", 'cd "$DSH_HOME" && exec "$@"', "--",
                *self.server.launcher,
                *(("--patch", str(cwd / "continuation-guard.patch.json"))
                  if guard is not None else ()),
            )
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
                cleanup = _helpers._terminate_and_reap(
                    process, child_uid=self.server.child_uid,
                )
                if cleanup[2] != "proven":
                    self.server.retire_requested = True
            self._reject(connection, "launch_failed", challenge, nonce, digest)
            return

        if _helpers._read_no_new_privs(process.pid) is not True:
            cleanup = _helpers._terminate_and_reap(
                process, child_uid=self.server.child_uid,
            )
            if cleanup[2] != "proven":
                self.server.retire_requested = True
            self._reject(connection, "launch_failed", challenge, nonce, digest)
            return

        connection.settimeout(None)
        try:
            ready_reply = {
                "v": PROTOCOL_VERSION, "challenge": challenge, "nonce": nonce,
                "scope_digest": digest, "cwd": str(cwd),
            }
            ready_reply["mac"] = _reply_mac(ready_reply, self.server.secret)
            _helpers._send_json(connection, READY, ready_reply)
        except OSError:
            cleanup = _helpers._terminate_and_reap(process, child_uid=self.server.child_uid)
            if cleanup[2] != "proven":
                self.server.retire_requested = True
            else:
                # No authenticated client received READY, so this START is
                # unknown to the caller and cannot be safely reused.
                self.server.retire_requested = True
            return

        relay_state: dict[str, Any] = {
            "cleanup": None, "exit_sent": False, "exit_cleanup": None,
        }
        self._run_relay(connection, process, deadline, challenge, nonce, digest,
                        relay_state, scope)
        if (relay_state["cleanup"] != "proven" or not relay_state["exit_sent"]
                or relay_state["exit_cleanup"] != "proven"):
            self.server.retire_requested = True

    @staticmethod
    def _validate_start(value: dict[str, Any], challenge: str, secret: bytes) -> tuple[
            dict[str, str], object, float | None, str, dict | None]:
        if set(value) not in {_START_KEYS, _START_KEYS | _START_OPTIONAL_KEYS} \
                or type(value.get("v")) is not int \
                or value["v"] != PROTOCOL_VERSION:
            raise ProductSlotError("START fields are invalid")
        if value.get("challenge") != challenge or _HEX64.fullmatch(challenge) is None:
            raise ProductSlotError("START challenge differs")
        nonce = value.get("nonce")
        if not isinstance(nonce, str) or _HEX64.fullmatch(nonce) is None:
            raise ProductSlotError("START nonce is invalid")
        scope = validate_product_scope(value.get("scope"))
        deadline_at_ms = value.get("deadline_at_ms")
        mac = value.get("mac")
        if not isinstance(mac, str) or _HEX64.fullmatch(mac) is None:
            raise ProductSlotError("START MAC is invalid")
        unsigned = {key: item for key, item in value.items() if key != "mac"}
        expected = _helpers.sign_start_message(unsigned, secret)
        if not hmac.compare_digest(expected, mac):
            raise ProductSlotError("START authentication failed")
        guard = _validate_guard(value["guard_b64"]) if "guard_b64" in value else None
        ordinary_config = None
        task_ready_config = None
        if guard is not None:
            try:
                candidate_config = guard[4]["insert"][0]["config"]
                if candidate_config.get("guardMode") == "task-ready-options":
                    task_ready_config = candidate_config
            except (IndexError, KeyError, TypeError, AttributeError):
                task_ready_config = None
            try:
                candidate_config = guard[1]["insert"][0]["config"]
                if candidate_config.get("guardMode") == "ordinary-options":
                    ordinary_config = candidate_config
            except (IndexError, KeyError, TypeError, AttributeError):
                ordinary_config = None
        if task_ready_config is not None:
            if task_ready_config["rootRunId"] != scope["root_run_id"]:
                raise ProductSlotError("task-ready guard root differs from signed Product scope")
            raw_env = value.get("env")
            if isinstance(raw_env, dict) and "DEEPSEEK_API_KEY" in raw_env:
                raise ProductSlotError(
                    "task-ready START contains an unselected provider credential")
            max_runtime = task_ready_config["executionProfile"]["options"][
                "max_runtime_seconds"]
            if max_runtime is None:
                if deadline_at_ms is not None:
                    raise ProductSlotError("task-ready START deadline has no user limit")
                deadline = None
            else:
                if type(deadline_at_ms) is not int or deadline_at_ms <= 0:
                    raise ProductSlotError("task-ready START deadline is missing")
                remaining_ms = deadline_at_ms - int(time.time() * 1000)
                if remaining_ms <= 0:
                    raise ProductSlotError("task-ready START deadline expired")
                try:
                    bounded_seconds = min(remaining_ms, max_runtime * 1000) / 1000.0
                    deadline = time.monotonic() + bounded_seconds
                    if not math.isfinite(bounded_seconds) or not math.isfinite(deadline):
                        raise OverflowError
                except (OverflowError, ValueError):
                    raise ProductSlotError("task-ready START deadline is not representable") from None
        elif ordinary_config is not None:
            max_runtime = ordinary_config["executionProfile"]["options"]["max_runtime_seconds"]
            if max_runtime is None:
                if deadline_at_ms is not None:
                    raise ProductSlotError("ordinary START deadline has no user limit")
                deadline = None
            else:
                if type(deadline_at_ms) is not int or deadline_at_ms <= 0:
                    raise ProductSlotError("ordinary START deadline is missing")
                remaining_ms = deadline_at_ms - int(time.time() * 1000)
                if remaining_ms <= 0:
                    raise ProductSlotError("ordinary START deadline expired")
                # Never extend the trusted user setting, and do not impose the
                # legacy one-hour process-runner cap on a v2 ordinary execution.
                deadline = time.monotonic() + min(remaining_ms, max_runtime * 1000) / 1000.0
        else:
            if type(deadline_at_ms) is not int or deadline_at_ms <= 0:
                raise ProductSlotError("START deadline is invalid")
            remaining_ms = deadline_at_ms - int(time.time() * 1000)
            if remaining_ms <= 0:
                raise ProductSlotError("START deadline expired")
            # Archived/F6 profiles keep their existing finite runner boundary.
            deadline = time.monotonic() + min(
                remaining_ms, LEGACY_MAX_RUN_SECONDS * 1000) / 1000.0
        return (scope, value.get("env"), deadline, nonce, guard)

    def _reject(self, connection: socket.socket, code: str, challenge: str,
                nonce: str, digest: str) -> None:
        try:
            reply = {
                "v": PROTOCOL_VERSION, "challenge": challenge, "nonce": nonce,
                "scope_digest": digest, "code": code,
            }
            reply["mac"] = _reply_mac(reply, self.server.secret)
            _helpers._send_json(connection, REJECT, reply)
        except OSError:
            pass

    def _persist_cleanup_proof(self, scope: dict[str, Any], digest: str,
                               exit_payload: dict[str, Any]) -> None:
        """Persist the Product-scope cleanup proof (override of the shared hook)."""
        _persist_product_cleanup_receipt(
            self.server.socket_path.parent, scope, digest,
            self.server.instance_id, exit_payload, self.server.secret,
            self.server.control_gid)

    def _prepare_cwd(self, cwd: Path) -> None:
        if cwd.parent != self.server.session_root or cwd.name in {"", ".", ".."}:
            raise OSError("Product ACP cwd is outside the workspace root")
        info = os.lstat(cwd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.server.child_uid
                or info.st_gid != self.server.child_gid
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise OSError("Product ACP cwd is not Adapter-prepared and private")
        if cwd.resolve(strict=True) != cwd:
            raise OSError("Product ACP cwd is not canonical")

    def _run_relay(self, connection: socket.socket, process: subprocess.Popen[bytes],
                   deadline: float | None, challenge: str, nonce: str, digest: str,
                   state: dict[str, Any], scope: dict[str, str]) -> None:
        """Reuse the reviewed relay while observing whether cleanup and EXIT were proven."""
        original_cleanup = _helpers._terminate_and_reap
        original_send = _helpers._send_json

        def tracked_cleanup(child: subprocess.Popen[bytes], *, child_uid: int):
            result = original_cleanup(child, child_uid=child_uid)
            state["cleanup"] = result[2]
            return result

        def tracked_send(sock: socket.socket, frame_type: int, value: dict[str, Any]):
            if frame_type == EXIT:
                state["exit_sent"] = True
                state["exit_cleanup"] = value.get("cleanup")
                if value.get("cleanup") != "proven":
                    # Retire the only workspace slot BEFORE the client observes an
                    # unproven EXIT, so no new root can be admitted for an
                    # unconfirmed cleanup (deterministic, not a post-relay race).
                    self.server.retire_requested = True
            return original_send(sock, frame_type, value)

        _helpers._terminate_and_reap = tracked_cleanup
        _helpers._send_json = tracked_send
        try:
            self._relay(connection, process, deadline, challenge, nonce, digest, scope)
        except BaseException:
            try:
                cleanup = original_cleanup(process, child_uid=self.server.child_uid)
                state["cleanup"] = cleanup[2]
            except BaseException:
                state["cleanup"] = "unknown"
            self.server.retire_requested = True
        finally:
            _helpers._terminate_and_reap = original_cleanup
            _helpers._send_json = original_send


def _load_secret() -> bytes:
    value = os.environ.get(PRODUCT_SECRET_ENV)
    if value is None:
        raise RuntimeError("Product runner control secret is missing")
    return _decode_secret(value)


def main() -> int:
    if os.geteuid() != 0 or os.getpid() != 1:
        raise RuntimeError("Product ACP runner must start as container root PID 1")
    if _helpers._read_no_new_privs(os.getpid()) is not True:
        raise RuntimeError("Product ACP runner requires no-new-privileges")
    if not _helpers._prctl_child_subreaper(enabled=True) or not _helpers._prctl_child_subreaper():
        raise RuntimeError("Product ACP runner could not enable child subreaper")
    workspace_id = os.environ.get(PRODUCT_WORKSPACE_ENV, "")
    secret = _load_secret()
    server = ProductSlotServer(secret=secret, workspace_id=workspace_id)
    exit_code = 0
    try:
        server.serve_forever(poll_interval=0.2)
    except RetireSlot as exc:
        exit_code = int(exc.code or 70)
    finally:
        server.server_close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
