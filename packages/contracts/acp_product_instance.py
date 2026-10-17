"""Signed local ownership records for the Product ACP runner.

These records bind new START scopes to the runner process which accepted them.
They are not an Engineering deployment binding or proof that an older process
namespace stopped; until a separate prebind exists, qualification is false.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping

from .acp_product_slot import product_scope_digest, validate_product_scope

INSTANCE_SCHEMA = "byq-acp-product-runner-instance.v1"
SCOPE_SCHEMA = "byq-acp-product-runner-scope-binding.v1"
INSTANCE_HMAC_PREFIX = b"byq-acp-product-runner-instance-v1\0"
SCOPE_HMAC_PREFIX = b"byq-acp-product-runner-scope-v1\0"

INSTANCE_FIELDS = frozenset({
    "schema_version", "workspace_id", "runner_instance_id", "runner_boot_id",
    "state_generation", "started_at", "operator_qualified",
    "deployment_binding_sha256", "backend_binding_nonce",
})
SCOPE_FIELDS = frozenset({
    "schema_version", "scope_digest", "scope", "runner_instance_id",
    "runner_boot_id", "state_generation", "operator_qualified",
    "deployment_binding_sha256", "backend_binding_nonce", "dispatch_state",
})

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SCOPE_KEYS = frozenset({
    "workspace_id", "owner_principal", "session_id", "trace_id",
    "root_run_id", "runtime_boot_id", "generation_id", "cwd_leaf",
})


class ProductInstanceContractError(ValueError):
    """A Product ACP instance or scope ownership record is invalid."""


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProductInstanceContractError("Product runner record is not canonical JSON") from exc


def record_digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _sign(value: Mapping[str, object], *, key: bytes, prefix: bytes,
          fields: frozenset[str], schema: str) -> dict[str, object]:
    if len(key) < 32 or set(value) != fields or value.get("schema_version") != schema:
        raise ProductInstanceContractError("Product runner signing input is invalid")
    result = dict(value)
    result["mac"] = hmac.new(key, prefix + canonical_json(value), hashlib.sha256).hexdigest()
    return result


def _verify(raw: object, *, key: bytes, prefix: bytes, fields: frozenset[str],
            schema: str) -> dict[str, object]:
    if (len(key) < 32 or not isinstance(raw, Mapping)
            or set(raw) != fields | {"mac"} or raw.get("schema_version") != schema):
        raise ProductInstanceContractError("Product runner record fields are invalid")
    value = dict(raw)
    mac = value.pop("mac")
    expected = hmac.new(key, prefix + canonical_json(value), hashlib.sha256).hexdigest()
    if not isinstance(mac, str) or not hmac.compare_digest(mac, expected):
        raise ProductInstanceContractError("Product runner record authentication failed")
    return dict(raw)


def sign_instance(value: Mapping[str, object], *, key: bytes) -> dict[str, object]:
    result = _sign(value, key=key, prefix=INSTANCE_HMAC_PREFIX,
                   fields=INSTANCE_FIELDS, schema=INSTANCE_SCHEMA)
    validate_instance(result, key=key)
    return result


def validate_instance(raw: object, *, key: bytes) -> dict[str, object]:
    value = _verify(raw, key=key, prefix=INSTANCE_HMAC_PREFIX,
                    fields=INSTANCE_FIELDS, schema=INSTANCE_SCHEMA)
    if (not isinstance(value["workspace_id"], str)
            or _IDENTIFIER.fullmatch(value["workspace_id"]) is None
            or not isinstance(value["runner_instance_id"], str)
            or _HEX64.fullmatch(value["runner_instance_id"]) is None
            or not isinstance(value["runner_boot_id"], str)
            or _HEX32.fullmatch(value["runner_boot_id"]) is None
            or not isinstance(value["state_generation"], str)
            or _HEX64.fullmatch(value["state_generation"]) is None
            or not isinstance(value["started_at"], str) or not value["started_at"]
            or value["operator_qualified"] is not False
            or value["deployment_binding_sha256"] is not None
            or value["backend_binding_nonce"] is not None):
        raise ProductInstanceContractError("Product runner instance identity is invalid")
    return value


def sign_scope_binding(value: Mapping[str, object], *, key: bytes,
                       instance: Mapping[str, object]) -> dict[str, object]:
    result = _sign(value, key=key, prefix=SCOPE_HMAC_PREFIX,
                   fields=SCOPE_FIELDS, schema=SCOPE_SCHEMA)
    validate_scope_binding(result, key=key, instance=instance)
    return result


def validate_scope_binding(raw: object, *, key: bytes,
                           instance: Mapping[str, object]) -> dict[str, object]:
    value = _verify(raw, key=key, prefix=SCOPE_HMAC_PREFIX,
                    fields=SCOPE_FIELDS, schema=SCOPE_SCHEMA)
    checked_instance = validate_instance(instance, key=key)
    scope = value["scope"]
    try:
        checked_scope = validate_product_scope(scope)
    except (TypeError, ValueError):
        raise ProductInstanceContractError("Product runner scope is invalid") from None
    if (set(scope) != _SCOPE_KEYS or checked_scope != dict(scope)
            or value["scope_digest"] != product_scope_digest(checked_scope)
            or scope.get("workspace_id") != checked_instance["workspace_id"]
            or value["runner_instance_id"] != checked_instance["runner_instance_id"]
            or value["runner_boot_id"] != checked_instance["runner_boot_id"]
            or value["state_generation"] != checked_instance["state_generation"]
            or value["operator_qualified"] is not False
            or value["deployment_binding_sha256"] is not None
            or value["backend_binding_nonce"] is not None
            or value["dispatch_state"] != "may_have_dispatched"):
        raise ProductInstanceContractError("Product runner scope ownership is invalid")
    for field in ("root_run_id", "runtime_boot_id"):
        if not isinstance(scope[field], str) or _HEX32.fullmatch(scope[field]) is None:
            raise ProductInstanceContractError("Product runner scope identity is invalid")
    return value
