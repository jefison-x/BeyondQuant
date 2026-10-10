"""Framework-neutral contract for a workspace-scoped ACP execution slot.

The scope binds one Product root invocation to a single workspace-owned
process-owner container.  It deliberately contains no command or arbitrary
filesystem path; ``cwd_leaf`` is resolved below the trusted workspace root.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit


PRODUCT_SCOPE_KEYS = frozenset({
    "workspace_id", "owner_principal", "session_id", "trace_id",
    "root_run_id", "runtime_boot_id", "generation_id", "cwd_leaf",
})

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_ROOT_CWD = re.compile(r"(?:session|root)-[0-9a-f]{32}\Z")
_PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TRACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_GENERATION = re.compile(r"generation-[0-9a-f]{32}\Z")
_NATIVE_SESSION = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)

PRODUCT_ENV_REQUIRED = frozenset({
    "BYQ_MCP_URL", "BYQ_MCP_ACP_DISCOVERY_TOKEN", "BYQ_MCP_ACP_SIGNING_KEY",
    "BYQ_RUNTIME_BOOT_ID", "BYQ_OWNER_PRINCIPAL", "BYQ_WORKSPACE_ID",
    "BYQ_ACTOR_PRINCIPAL", "BYQ_TRACE_ID", "BYQ_SESSION_ID",
    "BYQ_PROVIDER_SESSION_ID", "BYQ_DSH_RUN_ID", "BYQ_ROOT_RUN_ID",
})
PRODUCT_ENV_OPTIONAL = frozenset({
    "BYQ_NATIVE_ROOT_SESSION_ID", "DEEPSEEK_API_KEY", "OPENCODE_API_KEY",
    # Non-secret reservation carrier for a background continuation root. It is
    # the trusted task-bound identity the MCP server uses to advertise only the
    # tools that exact reservation may call; never a caller-selected value.
    "BYQ_CONTINUATION_RESERVATION_ID",
})
PRODUCT_ENV_ALLOWLIST = PRODUCT_ENV_REQUIRED | PRODUCT_ENV_OPTIONAL


class ProductSlotContractError(ValueError):
    """A Product runner scope is malformed or inconsistent."""


def canonical_product_json(value: object) -> bytes:
    """Encode canonical JSON shared by the Adapter client and slot daemon."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProductSlotContractError("Product ACP value is not canonical JSON") from exc


def validate_product_scope(raw: object) -> dict[str, str]:
    """Validate and copy the exact root scope accepted by a Product slot."""
    if not isinstance(raw, Mapping) or set(raw) != PRODUCT_SCOPE_KEYS:
        raise ProductSlotContractError("Product ACP scope fields are invalid")
    scope: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ProductSlotContractError("Product ACP scope values are invalid")
        if not value or "\0" in value or len(value.encode("utf-8")) > 256:
            raise ProductSlotContractError("Product ACP scope value is invalid")
        scope[key] = value

    if _HEX32.fullmatch(scope["root_run_id"]) is None:
        raise ProductSlotContractError("Product ACP root identity is invalid")
    if _HEX32.fullmatch(scope["runtime_boot_id"]) is None:
        raise ProductSlotContractError("Product ACP boot identity is invalid")
    if _GENERATION.fullmatch(scope["generation_id"]) is None:
        raise ProductSlotContractError("Product ACP generation identity is invalid")
    if _ROOT_CWD.fullmatch(scope["cwd_leaf"]) is None:
        raise ProductSlotContractError("Product ACP working directory leaf is invalid")
    if _PRINCIPAL.fullmatch(scope["owner_principal"]) is None:
        raise ProductSlotContractError("Product ACP owner identity is invalid")
    for key in ("workspace_id", "session_id"):
        if _IDENTIFIER.fullmatch(scope[key]) is None:
            raise ProductSlotContractError("Product ACP workspace or session identity is invalid")
    if _TRACE.fullmatch(scope["trace_id"]) is None:
        raise ProductSlotContractError("Product ACP trace identity is invalid")
    return scope


def validate_product_environment(
    raw: object, scope: Mapping[str, Any],
) -> dict[str, str]:
    """Validate the closed, root-scoped Product ACP child environment."""
    validated_scope = validate_product_scope(scope)
    if not isinstance(raw, Mapping):
        raise ProductSlotContractError("Product ACP environment is invalid")
    if (not PRODUCT_ENV_REQUIRED <= set(raw)
            or not set(raw) <= PRODUCT_ENV_ALLOWLIST):
        raise ProductSlotContractError("Product ACP environment fields are invalid")
    env: dict[str, str] = {}
    total = 0
    try:
        for key, value in raw.items():
            if (not isinstance(key, str) or not isinstance(value, str)
                    or not value or "\0" in value):
                raise ProductSlotContractError("Product ACP environment value is invalid")
            encoded = value.encode("utf-8")
            total += len(key.encode("ascii")) + len(encoded)
            if len(encoded) > 16_384 or total > 64 * 1024:
                raise ProductSlotContractError("Product ACP environment exceeds its bound")
            env[key] = value
    except UnicodeError as exc:
        raise ProductSlotContractError("Product ACP environment encoding is invalid") from exc

    provider_keys = {key for key in ("DEEPSEEK_API_KEY", "OPENCODE_API_KEY") if key in env}
    if len(provider_keys) != 1:
        raise ProductSlotContractError("Product ACP requires exactly one selected provider key")
    reservation = env.get("BYQ_CONTINUATION_RESERVATION_ID")
    if reservation is not None and re.fullmatch(r"continuation_[0-9a-f]{32}", reservation) is None:
        raise ProductSlotContractError("Product ACP continuation reservation is invalid")
    endpoint = urlsplit(env["BYQ_MCP_URL"])
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
            or endpoint.username is not None or endpoint.password is not None
            or endpoint.query or endpoint.fragment):
        raise ProductSlotContractError("Product ACP MCP endpoint is invalid")
    if len(env["BYQ_MCP_ACP_DISCOVERY_TOKEN"].encode("utf-8")) < 32:
        raise ProductSlotContractError("Product ACP discovery credential is invalid")
    if len(env["BYQ_MCP_ACP_SIGNING_KEY"].encode("utf-8")) < 32:
        raise ProductSlotContractError("Product ACP signing credential is invalid")
    secrets = [env["BYQ_MCP_ACP_DISCOVERY_TOKEN"], env["BYQ_MCP_ACP_SIGNING_KEY"]]
    secrets.extend(env[key] for key in provider_keys)
    if len(set(secrets)) != len(secrets):
        raise ProductSlotContractError("Product ACP credentials must be distinct")

    identity_map = {
        "BYQ_WORKSPACE_ID": "workspace_id",
        "BYQ_OWNER_PRINCIPAL": "owner_principal",
        "BYQ_SESSION_ID": "session_id",
        "BYQ_TRACE_ID": "trace_id",
        "BYQ_ROOT_RUN_ID": "root_run_id",
        "BYQ_RUNTIME_BOOT_ID": "runtime_boot_id",
        "BYQ_DSH_RUN_ID": "generation_id",
    }
    if any(env[name] != validated_scope[scope_name]
           for name, scope_name in identity_map.items()):
        raise ProductSlotContractError("Product ACP environment identity differs from scope")
    if env["BYQ_ACTOR_PRINCIPAL"] != f"byq-product-agent-{validated_scope['session_id']}":
        raise ProductSlotContractError("Product ACP actor identity differs from session")
    provider_session = env["BYQ_PROVIDER_SESSION_ID"]
    if _UUID.fullmatch(provider_session) is None:
        raise ProductSlotContractError("Product ACP provider session identity is invalid")
    if ("BYQ_NATIVE_ROOT_SESSION_ID" in env
            and _NATIVE_SESSION.fullmatch(env["BYQ_NATIVE_ROOT_SESSION_ID"]) is None):
        raise ProductSlotContractError("Product ACP native session identity is invalid")
    return env


def product_scope_digest(scope: Mapping[str, Any]) -> str:
    """Return SHA-256 over the canonical, fully validated Product root scope."""
    validated = validate_product_scope(scope)
    return hashlib.sha256(canonical_product_json(validated)).hexdigest()
