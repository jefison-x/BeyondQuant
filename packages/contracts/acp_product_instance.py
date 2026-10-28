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
STARTED_SCHEMA = "byq-acp-product-runner-started.v1"
SUCCESSOR_TOMBSTONE_SCHEMA = "byq-acp-product-runner-successor-tombstone.v1"
INSTANCE_HMAC_PREFIX = b"byq-acp-product-runner-instance-v1\0"
SCOPE_HMAC_PREFIX = b"byq-acp-product-runner-scope-v1\0"
STARTED_HMAC_PREFIX = b"byq-acp-product-runner-started-v1\0"
SUCCESSOR_TOMBSTONE_HMAC_PREFIX = b"byq-acp-product-runner-successor-tombstone-v1\0"

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
STARTED_FIELDS = frozenset({
    "schema_version", "workspace_id", "runner_instance_id", "runner_boot_id",
    "state_generation", "started_at",
})
SUCCESSOR_CANDIDATE_SCHEMA = "byq-acp-product-runner-successor-candidate.v1"
SUCCESSOR_CANDIDATE_FIELDS = frozenset({
    "schema_version", "operation_id", "old_runner_instance_id", "scope",
    "old_prestart_binding", "engineering_native_fence_evidence_sha256",
    "successor_runner_instance_id", "successor_runner_boot_id",
    "successor_state_generation", "successor_signed_instance_sha256",
    "successor_active_binding_receipt_sha256",
})
SUCCESSOR_TOMBSTONE_FIELDS = frozenset({
    "schema_version", "operation_id", "workspace_id", "scope_digest", "scope",
    "old_runner_instance_id", "old_runner_boot_id", "old_state_generation",
    "old_instance_sha256", "old_birth_mode_sha256", "old_started_marker_sha256",
    "old_scope_ownership_sha256", "consumed_scope_marker_sha256",
    "old_install_record_sha256", "old_activation_record_sha256",
    "old_active_binding_receipt_sha256", "old_prestart_binding",
    "old_prestart_binding_sha256",
    "successor_runner_instance_id", "successor_runner_boot_id",
    "successor_state_generation", "successor_instance_sha256",
    "successor_birth_mode_sha256", "successor_install_record_sha256",
    "successor_activation_record_sha256", "successor_active_binding_receipt_sha256",
    "successor_prestart_binding", "successor_prestart_binding_sha256",
    "engineering_native_fence_evidence_sha256",
})

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SCOPE_KEYS = frozenset({
    "workspace_id", "owner_principal", "session_id", "trace_id",
    "root_run_id", "runtime_boot_id", "generation_id", "cwd_leaf",
})
_START_BINDING_SCHEMA = "byq-acp-product-runner-start-binding.v1"
_START_BINDING_FIELDS = frozenset({
    "schema_version", "runner_instance_id", "runner_boot_id", "state_generation",
    "signed_instance_sha256", "prepared_receipt_sha256", "backend_binding_nonce",
    "install_receipt_sha256", "backend_activation_id",
    "backend_activation_receipt_sha256",
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


def sign_instance_started(value: Mapping[str, object], *, key: bytes,
                          instance: Mapping[str, object]) -> dict[str, object]:
    result = _sign(value, key=key, prefix=STARTED_HMAC_PREFIX,
                   fields=STARTED_FIELDS, schema=STARTED_SCHEMA)
    validate_instance_started(result, key=key, instance=instance)
    return result


def validate_instance_started(raw: object, *, key: bytes,
                               instance: Mapping[str, object]) -> dict[str, object]:
    value = _verify(raw, key=key, prefix=STARTED_HMAC_PREFIX,
                    fields=STARTED_FIELDS, schema=STARTED_SCHEMA)
    checked_instance = validate_instance(instance, key=key)
    if (any(value[field] != checked_instance[field] for field in (
            "workspace_id", "runner_instance_id", "runner_boot_id", "state_generation"))
            or not isinstance(value["started_at"], str) or not value["started_at"]):
        raise ProductInstanceContractError("Product runner started marker identity is invalid")
    return value


def validate_successor_candidate(raw: object, *, key: bytes,
                                 old_instance: Mapping[str, object],
                                 successor_instance: Mapping[str, object]) -> dict[str, object]:
    """Validate the closed, root-private inputs for one successor tombstone.

    Engineering authority comes from the restricted installer invocation and
    its independently collected evidence, not from this unsigned candidate or
    the Product MAC used for the resulting local record.
    """
    old = validate_instance(old_instance, key=key)
    successor = validate_instance(successor_instance, key=key)
    if not isinstance(raw, Mapping) or set(raw) != SUCCESSOR_CANDIDATE_FIELDS:
        raise ProductInstanceContractError("successor candidate fields are invalid")
    value = dict(raw)
    scope = value.get("scope")
    try:
        checked_scope = validate_product_scope(scope)
    except (TypeError, ValueError):
        raise ProductInstanceContractError("successor candidate scope is invalid") from None
    if (value.get("schema_version") != SUCCESSOR_CANDIDATE_SCHEMA
            or not isinstance(value.get("operation_id"), str)
            or _HEX32.fullmatch(value["operation_id"]) is None
            or not isinstance(scope, Mapping) or set(scope) != _SCOPE_KEYS
            or checked_scope != dict(scope)
            or scope.get("workspace_id") != old["workspace_id"]
            or old["workspace_id"] != successor["workspace_id"]
            or old["runner_instance_id"] == successor["runner_instance_id"]
            or old["state_generation"] != successor["state_generation"]
            or not isinstance(value.get("old_runner_instance_id"), str)
            or value["old_runner_instance_id"] != old["runner_instance_id"]
            or value.get("successor_runner_instance_id") != successor["runner_instance_id"]
            or value.get("successor_runner_boot_id") != successor["runner_boot_id"]
            or value.get("successor_state_generation") != successor["state_generation"]
            or value.get("successor_signed_instance_sha256") != record_digest(successor)):
        raise ProductInstanceContractError("successor candidate identity is invalid")
    for field in ("successor_runner_instance_id", "successor_signed_instance_sha256",
                  "successor_active_binding_receipt_sha256"):
        if not isinstance(value.get(field), str) or _HEX64.fullmatch(value[field]) is None:
            raise ProductInstanceContractError("successor candidate anchor is invalid")
    if (not isinstance(value.get("successor_runner_boot_id"), str)
            or _HEX32.fullmatch(value["successor_runner_boot_id"]) is None
            or not isinstance(value.get("successor_state_generation"), str)
            or _HEX64.fullmatch(value["successor_state_generation"]) is None):
        raise ProductInstanceContractError("successor candidate identity is invalid")
    if not _valid_start_binding(value.get("old_prestart_binding")):
        raise ProductInstanceContractError("successor candidate preSTART binding is invalid")
    if (not isinstance(value.get("engineering_native_fence_evidence_sha256"), str)
            or _HEX64.fullmatch(value["engineering_native_fence_evidence_sha256"]) is None):
        raise ProductInstanceContractError("successor candidate evidence digest is invalid")
    for field in ("root_run_id", "runtime_boot_id"):
        if not isinstance(scope.get(field), str) or _HEX32.fullmatch(scope[field]) is None:
            raise ProductInstanceContractError("successor candidate scope identity is invalid")
    return value


def sign_successor_tombstone(raw: Mapping[str, object], *, key: bytes) -> dict[str, object]:
    result = _sign(raw, key=key, prefix=SUCCESSOR_TOMBSTONE_HMAC_PREFIX,
                   fields=SUCCESSOR_TOMBSTONE_FIELDS,
                   schema=SUCCESSOR_TOMBSTONE_SCHEMA)
    validate_successor_tombstone(result, key=key)
    return result


def validate_successor_tombstone(raw: object, *, key: bytes) -> dict[str, object]:
    value = _verify(raw, key=key, prefix=SUCCESSOR_TOMBSTONE_HMAC_PREFIX,
                    fields=SUCCESSOR_TOMBSTONE_FIELDS,
                    schema=SUCCESSOR_TOMBSTONE_SCHEMA)
    scope = value.get("scope")
    try:
        checked_scope = validate_product_scope(scope)
    except (TypeError, ValueError):
        raise ProductInstanceContractError("successor tombstone scope is invalid") from None
    if (not isinstance(scope, Mapping) or set(scope) != _SCOPE_KEYS
            or checked_scope != dict(scope)
            or value.get("scope_digest") != product_scope_digest(checked_scope)
            or value.get("workspace_id") != scope.get("workspace_id")
            or not isinstance(value.get("operation_id"), str)
            or _HEX32.fullmatch(value["operation_id"]) is None
            or not isinstance(value.get("old_runner_instance_id"), str)
            or _HEX64.fullmatch(value["old_runner_instance_id"]) is None
            or not isinstance(value.get("successor_runner_instance_id"), str)
            or _HEX64.fullmatch(value["successor_runner_instance_id"]) is None
            or value["old_runner_instance_id"] == value["successor_runner_instance_id"]
            or not isinstance(value.get("old_runner_boot_id"), str)
            or _HEX32.fullmatch(value["old_runner_boot_id"]) is None
            or not isinstance(value.get("successor_runner_boot_id"), str)
            or _HEX32.fullmatch(value["successor_runner_boot_id"]) is None
            or value["old_runner_boot_id"] == value["successor_runner_boot_id"]
            or value.get("old_state_generation") != value.get("successor_state_generation")
            or not isinstance(value.get("old_state_generation"), str)
            or _HEX64.fullmatch(value["old_state_generation"]) is None):
        raise ProductInstanceContractError("successor tombstone identity is invalid")
    if scope.get("workspace_id") != value["workspace_id"]:
        raise ProductInstanceContractError("successor tombstone workspace is invalid")
    for field in SUCCESSOR_TOMBSTONE_FIELDS - {
            "schema_version", "operation_id", "workspace_id", "scope_digest", "scope",
            "old_runner_instance_id", "old_runner_boot_id", "old_state_generation",
            "successor_runner_instance_id", "successor_runner_boot_id",
            "successor_state_generation", "old_prestart_binding",
            "successor_prestart_binding"}:
        if not isinstance(value.get(field), str) or _HEX64.fullmatch(value[field]) is None:
            raise ProductInstanceContractError("successor tombstone digest is invalid")
    for binding_key, digest_key in (("old_prestart_binding", "old_prestart_binding_sha256"),
                                   ("successor_prestart_binding", "successor_prestart_binding_sha256")):
        binding = value.get(binding_key)
        if (not _valid_start_binding(binding)
                or record_digest(binding) != value[digest_key]):
            raise ProductInstanceContractError("successor tombstone preSTART anchor is invalid")
    return value


def _valid_start_binding(raw: object) -> bool:
    if (not isinstance(raw, Mapping) or set(raw) != _START_BINDING_FIELDS
            or raw.get("schema_version") != _START_BINDING_SCHEMA):
        return False
    return (
        isinstance(raw.get("runner_instance_id"), str)
        and _HEX64.fullmatch(raw["runner_instance_id"]) is not None
        and isinstance(raw.get("runner_boot_id"), str)
        and _HEX32.fullmatch(raw["runner_boot_id"]) is not None
        and isinstance(raw.get("state_generation"), str)
        and _HEX64.fullmatch(raw["state_generation"]) is not None
        and all(isinstance(raw.get(field), str) and _HEX64.fullmatch(raw[field]) is not None
                for field in ("signed_instance_sha256", "prepared_receipt_sha256",
                              "backend_binding_nonce", "install_receipt_sha256",
                              "backend_activation_receipt_sha256"))
        and isinstance(raw.get("backend_activation_id"), str)
        and _HEX32.fullmatch(raw["backend_activation_id"]) is not None
    )


def successor_tombstone_raw_digest(raw: bytes) -> str:
    """Hash the exact canonical signed bytes stored for Backend's later join."""
    if not isinstance(raw, bytes):
        raise ProductInstanceContractError("successor tombstone bytes are invalid")
    return hashlib.sha256(raw).hexdigest()


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
