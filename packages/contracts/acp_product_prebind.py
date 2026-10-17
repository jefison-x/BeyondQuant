"""Closed Backend contract for a non-authorizing ACP runner prebind intent.

This contract records an Engineering-prepared candidate only. It does not
qualify a runner, authorize START, or attest native Docker facts by itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any

PREPARE_SCHEMA = "byq-acp-product-runner-prebind.v1"
PREPARE_ACTION = "acp_operator_runner_prebind"
PREPARE_IDEMPOTENCY_PREFIX = "acp-operator-prebind:"
PREPARE_FIELDS = frozenset({"schema_version", "operation_id", "workspace_id",
                            "instance", "deployment", "state_volume"})
INSTANCE_FIELDS = frozenset({"schema_version", "workspace_id", "runner_instance_id",
                             "runner_boot_id", "state_generation", "started_at",
                             "operator_qualified", "deployment_binding_sha256",
                             "backend_binding_nonce", "mac"})
DEPLOYMENT_FIELDS = frozenset({"daemon_id", "deployment_id", "service", "container_id",
                               "image_digest", "started_at", "pid_namespace_id"})
VOLUME_FIELDS = frozenset({"name", "driver", "scope", "source", "mount_destination"})
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

BIRTH_SCHEMA = "byq-acp-product-runner-birth-mode.v1"
BIRTH_HMAC_PREFIX = b"byq-acp-product-runner-birth-mode-v1\0"
BIRTH_FIELDS = frozenset({"schema_version", "workspace_id", "runner_instance_id",
                          "runner_boot_id", "state_generation", "instance_sha256",
                          "require_prebind"})
INSTALL_SCHEMA = "byq-acp-product-runner-prebind-install.v1"
INSTALL_HMAC_PREFIX = b"byq-acp-product-runner-prebind-install-v1\0"
INSTALL_FIELDS = frozenset({"schema_version", "status", "authorizes_start", "workspace_id",
                            "runner_instance_id", "runner_boot_id", "state_generation",
                            "signed_instance_sha256", "birth_mode_sha256",
                            "prepared_receipt_sha256", "backend_binding_nonce",
                            "prepared_receipt", "readback_sha256", "installed_at"})
BACKEND_ACTIVE_SCHEMA = "byq-acp-product-runner-prebind-active.v1"
BACKEND_ACTIVE_FIELDS = frozenset({"schema_version", "status", "activation_id",
                                   "workspace_id", "runner_instance_id", "runner_boot_id",
                                   "state_generation", "signed_instance_sha256",
                                   "prepared_receipt_sha256", "backend_binding_nonce",
                                   "install_receipt_sha256", "native_binding_sha256",
                                   "activated_at", "receipt_sha256"})
ACTIVATION_SCHEMA = "byq-acp-product-runner-activation-delivery.v1"
ACTIVATION_HMAC_PREFIX = b"byq-acp-product-runner-activation-delivery-v1\0"
ACTIVATION_FIELDS = frozenset({"schema_version", "status", "authorizes_start",
                               "workspace_id", "runner_instance_id", "runner_boot_id",
                               "state_generation", "signed_instance_sha256",
                               "prepared_receipt_sha256", "backend_binding_nonce",
                               "install_receipt_sha256", "backend_receipt"})
START_BINDING_SCHEMA = "byq-acp-product-runner-start-binding.v1"
START_BINDING_FIELDS = frozenset({"schema_version", "runner_instance_id", "runner_boot_id",
                                  "state_generation", "signed_instance_sha256",
                                  "prepared_receipt_sha256", "backend_binding_nonce",
                                  "install_receipt_sha256", "backend_activation_id",
                                  "backend_activation_receipt_sha256"})
PREPARED_RECEIPT_FIELDS = frozenset({"schema_version", "status", "authorizes_start",
                                     "native_facts_verified", "runner_install_verified",
                                     "operation_id", "workspace_id", "operator",
                                     "runner_instance_id", "runner_boot_id", "state_generation",
                                     "signed_instance_sha256", "deployment", "state_volume",
                                     "backend_binding_nonce", "request_sha256",
                                     "receipt_sha256"})


class PrebindContractError(ValueError):
    """The Engineering prebind request is not closed or valid."""


def _sign_record(raw: object, *, key: bytes, fields: frozenset[str], schema: str,
                 prefix: bytes) -> dict[str, Any]:
    if (len(key) < 32 or not isinstance(raw, Mapping) or set(raw) != fields
            or raw.get("schema_version") != schema):
        raise PrebindContractError("prebind signing input is invalid")
    result = dict(raw)
    result["mac"] = hmac.new(key, prefix + canonical_json(raw), hashlib.sha256).hexdigest()
    return result


def _verify_record(raw: object, *, key: bytes, fields: frozenset[str], schema: str,
                   prefix: bytes) -> dict[str, Any]:
    if (len(key) < 32 or not isinstance(raw, Mapping)
            or set(raw) != fields | {"mac"} or raw.get("schema_version") != schema):
        raise PrebindContractError("prebind record fields are invalid")
    value = dict(raw)
    mac = value.pop("mac")
    expected = hmac.new(key, prefix + canonical_json(value), hashlib.sha256).hexdigest()
    if not isinstance(mac, str) or not hmac.compare_digest(mac, expected):
        raise PrebindContractError("prebind record authentication failed")
    return dict(raw)


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise PrebindContractError("prebind value is not canonical JSON") from exc


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _bounded_text(value: object, field: str, maximum: int = 512) -> str:
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum
            or "\x00" in value):
        raise PrebindContractError(f"{field} is invalid")
    return value


def validate_prepare_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != PREPARE_FIELDS:
        raise PrebindContractError("prebind request fields are invalid")
    if raw.get("schema_version") != PREPARE_SCHEMA:
        raise PrebindContractError("prebind request version is invalid")
    operation_id = raw.get("operation_id")
    workspace_id = raw.get("workspace_id")
    if not isinstance(operation_id, str) or _HEX32.fullmatch(operation_id) is None:
        raise PrebindContractError("prebind operation identity is invalid")
    if not isinstance(workspace_id, str) or _IDENT.fullmatch(workspace_id) is None:
        raise PrebindContractError("prebind workspace identity is invalid")

    instance = raw.get("instance")
    if not isinstance(instance, Mapping) or set(instance) != INSTANCE_FIELDS:
        raise PrebindContractError("signed instance fields are invalid")
    if (instance.get("schema_version") != "byq-acp-product-runner-instance.v1"
            or instance.get("workspace_id") != workspace_id
            or instance.get("operator_qualified") is not False
            or instance.get("deployment_binding_sha256") is not None
            or instance.get("backend_binding_nonce") is not None
            or not isinstance(instance.get("runner_instance_id"), str)
            or _HEX64.fullmatch(instance["runner_instance_id"]) is None
            or not isinstance(instance.get("runner_boot_id"), str)
            or _HEX32.fullmatch(instance["runner_boot_id"]) is None
            or not isinstance(instance.get("state_generation"), str)
            or _HEX64.fullmatch(instance["state_generation"]) is None
            or not isinstance(instance.get("started_at"), str)
            or not instance["started_at"]
            or not isinstance(instance.get("mac"), str)
            or _HEX64.fullmatch(instance["mac"]) is None):
        raise PrebindContractError("signed instance identity is invalid")

    deployment = raw.get("deployment")
    if not isinstance(deployment, Mapping) or set(deployment) != DEPLOYMENT_FIELDS:
        raise PrebindContractError("native deployment identity fields are invalid")
    for field in ("daemon_id", "deployment_id", "service", "container_id",
                  "started_at", "pid_namespace_id"):
        _bounded_text(deployment.get(field), field)
    image_digest = deployment.get("image_digest")
    if not isinstance(image_digest, str) or _DIGEST.fullmatch(image_digest) is None:
        raise PrebindContractError("native image identity is invalid")

    volume = raw.get("state_volume")
    if not isinstance(volume, Mapping) or set(volume) != VOLUME_FIELDS:
        raise PrebindContractError("state volume identity fields are invalid")
    for field in VOLUME_FIELDS:
        _bounded_text(volume.get(field), field)

    return {
        "schema_version": PREPARE_SCHEMA,
        "operation_id": operation_id,
        "workspace_id": workspace_id,
        "instance": dict(instance),
        "deployment": dict(deployment),
        "state_volume": dict(volume),
    }


def sign_birth_mode(raw: object, *, key: bytes) -> dict[str, Any]:
    return _sign_record(raw, key=key, fields=BIRTH_FIELDS,
                        schema=BIRTH_SCHEMA, prefix=BIRTH_HMAC_PREFIX)


def validate_birth_mode(raw: object, *, key: bytes,
                        instance: Mapping[str, Any]) -> dict[str, Any]:
    value = _verify_record(raw, key=key, fields=BIRTH_FIELDS,
                           schema=BIRTH_SCHEMA, prefix=BIRTH_HMAC_PREFIX)
    expected = {
        "workspace_id": instance["workspace_id"],
        "runner_instance_id": instance["runner_instance_id"],
        "runner_boot_id": instance["runner_boot_id"],
        "state_generation": instance["state_generation"],
        "instance_sha256": digest(instance),
    }
    if (any(value.get(field) != expected[field] for field in expected)
            or not isinstance(value.get("require_prebind"), bool)):
        raise PrebindContractError("runner birth mode identity is invalid")
    return value


def validate_prepared_receipt(raw: object, *, instance: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != PREPARED_RECEIPT_FIELDS:
        raise PrebindContractError("prepared receipt fields are invalid")
    value = dict(raw)
    if (value.get("schema_version") != PREPARE_SCHEMA or value.get("status") != "prepared"
            or value.get("authorizes_start") is not False
            or value.get("native_facts_verified") is not False
            or value.get("runner_install_verified") is not False):
        raise PrebindContractError("prepared receipt is not a non-authorizing candidate")
    if (value.get("workspace_id") != instance.get("workspace_id")
            or value.get("runner_instance_id") != instance.get("runner_instance_id")
            or value.get("runner_boot_id") != instance.get("runner_boot_id")
            or value.get("state_generation") != instance.get("state_generation")
            or value.get("signed_instance_sha256") != digest(instance)):
        raise PrebindContractError("prepared receipt does not bind the current instance")
    if (not isinstance(value.get("operation_id"), str)
            or _HEX32.fullmatch(value["operation_id"]) is None
            or not isinstance(value.get("backend_binding_nonce"), str)
            or _HEX64.fullmatch(value["backend_binding_nonce"]) is None
            or not isinstance(value.get("request_sha256"), str)
            or _HEX64.fullmatch(value["request_sha256"]) is None):
        raise PrebindContractError("prepared receipt identifiers are invalid")
    operator = value.get("operator")
    if (not isinstance(operator, Mapping) or set(operator) != {"uid", "name"}
            or isinstance(operator.get("uid"), bool)
            or not isinstance(operator.get("uid"), int) or operator["uid"] < 0
            or not isinstance(operator.get("name"), str) or not operator["name"]):
        raise PrebindContractError("prepared receipt operator attribution is invalid")
    validate_prepare_request({
        "schema_version": PREPARE_SCHEMA,
        "operation_id": value["operation_id"],
        "workspace_id": value["workspace_id"],
        "instance": instance,
        "deployment": value["deployment"],
        "state_volume": value["state_volume"],
    })
    without_digest = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if (not isinstance(value.get("receipt_sha256"), str)
            or _HEX64.fullmatch(value["receipt_sha256"]) is None
            or digest(without_digest) != value["receipt_sha256"]):
        raise PrebindContractError("prepared receipt digest is invalid")
    return value


def sign_install_record(raw: object, *, key: bytes) -> dict[str, Any]:
    return _sign_record(raw, key=key, fields=INSTALL_FIELDS,
                        schema=INSTALL_SCHEMA, prefix=INSTALL_HMAC_PREFIX)


def validate_install_record(raw: object, *, key: bytes, instance: Mapping[str, Any],
                            birth_mode: Mapping[str, Any]) -> dict[str, Any]:
    value = _verify_record(raw, key=key, fields=INSTALL_FIELDS,
                           schema=INSTALL_SCHEMA, prefix=INSTALL_HMAC_PREFIX)
    prepared_receipt = validate_prepared_receipt(value["prepared_receipt"],
                                                 instance=instance)
    expected = {
        "status": "installed_nonactive",
        "authorizes_start": False,
        "workspace_id": instance["workspace_id"],
        "runner_instance_id": instance["runner_instance_id"],
        "runner_boot_id": instance["runner_boot_id"],
        "state_generation": instance["state_generation"],
        "signed_instance_sha256": digest(instance),
        "birth_mode_sha256": digest(birth_mode),
        "prepared_receipt_sha256": prepared_receipt["receipt_sha256"],
        "backend_binding_nonce": prepared_receipt["backend_binding_nonce"],
    }
    if any(value.get(field) != expected[field] for field in expected):
        raise PrebindContractError("installed candidate does not match the prepared instance")
    for field in ("readback_sha256",):
        if not isinstance(value.get(field), str) or _HEX64.fullmatch(value[field]) is None:
            raise PrebindContractError("installed candidate readback digest is invalid")
    if not isinstance(value.get("installed_at"), str) or not value["installed_at"]:
        raise PrebindContractError("installed candidate time is invalid")
    return value


def validate_backend_active_receipt(raw: object, *, prepared_receipt: Mapping[str, Any],
                                    install_record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != BACKEND_ACTIVE_FIELDS:
        raise PrebindContractError("Backend active receipt fields are invalid")
    value = dict(raw)
    expected = {
        "schema_version": BACKEND_ACTIVE_SCHEMA,
        "status": "active",
        "workspace_id": prepared_receipt["workspace_id"],
        "runner_instance_id": prepared_receipt["runner_instance_id"],
        "runner_boot_id": prepared_receipt["runner_boot_id"],
        "state_generation": prepared_receipt["state_generation"],
        "signed_instance_sha256": prepared_receipt["signed_instance_sha256"],
        "prepared_receipt_sha256": prepared_receipt["receipt_sha256"],
        "backend_binding_nonce": prepared_receipt["backend_binding_nonce"],
        "install_receipt_sha256": digest(install_record),
    }
    if any(value.get(field) != expected[field] for field in expected):
        raise PrebindContractError("Backend active receipt does not match installation")
    if (not isinstance(value.get("activation_id"), str)
            or _HEX32.fullmatch(value["activation_id"]) is None
            or not isinstance(value.get("native_binding_sha256"), str)
            or _HEX64.fullmatch(value["native_binding_sha256"]) is None
            or not isinstance(value.get("activated_at"), str) or not value["activated_at"]
            or not isinstance(value.get("receipt_sha256"), str)
            or _HEX64.fullmatch(value["receipt_sha256"]) is None):
        raise PrebindContractError("Backend active receipt identity is invalid")
    without_digest = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if digest(without_digest) != value["receipt_sha256"]:
        raise PrebindContractError("Backend active receipt digest is invalid")
    return value


def sign_activation_record(raw: object, *, key: bytes) -> dict[str, Any]:
    return _sign_record(raw, key=key, fields=ACTIVATION_FIELDS,
                        schema=ACTIVATION_SCHEMA, prefix=ACTIVATION_HMAC_PREFIX)


def validate_activation_record(raw: object, *, key: bytes, instance: Mapping[str, Any],
                               birth_mode: Mapping[str, Any],
                               prepared_receipt: Mapping[str, Any],
                               install_record: Mapping[str, Any]) -> dict[str, Any]:
    value = _verify_record(raw, key=key, fields=ACTIVATION_FIELDS,
                           schema=ACTIVATION_SCHEMA, prefix=ACTIVATION_HMAC_PREFIX)
    expected = {
        "status": "active",
        "authorizes_start": True,
        "workspace_id": instance["workspace_id"],
        "runner_instance_id": instance["runner_instance_id"],
        "runner_boot_id": instance["runner_boot_id"],
        "state_generation": instance["state_generation"],
        "signed_instance_sha256": digest(instance),
        "prepared_receipt_sha256": prepared_receipt["receipt_sha256"],
        "backend_binding_nonce": prepared_receipt["backend_binding_nonce"],
        "install_receipt_sha256": digest(install_record),
    }
    if any(value.get(field) != expected[field] for field in expected):
        raise PrebindContractError("activation record does not match the current instance")
    backend_receipt = validate_backend_active_receipt(
        value["backend_receipt"], prepared_receipt=prepared_receipt,
        install_record=install_record,
    )
    if (value["backend_receipt"].get("activation_id") != backend_receipt["activation_id"]
            or value["backend_receipt"].get("receipt_sha256")
            != backend_receipt["receipt_sha256"]):
        raise PrebindContractError("Backend activation receipt reference is invalid")
    return value


def validate_start_binding(raw: object, *, activation_record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != START_BINDING_FIELDS:
        raise PrebindContractError("START operator binding fields are invalid")
    value = dict(raw)
    if value.get("schema_version") != START_BINDING_SCHEMA:
        raise PrebindContractError("START operator binding version is invalid")
    backend_receipt = activation_record["backend_receipt"]
    expected = {
        "runner_instance_id": activation_record["runner_instance_id"],
        "runner_boot_id": activation_record["runner_boot_id"],
        "state_generation": activation_record["state_generation"],
        "signed_instance_sha256": activation_record["signed_instance_sha256"],
        "prepared_receipt_sha256": activation_record["prepared_receipt_sha256"],
        "backend_binding_nonce": activation_record["backend_binding_nonce"],
        "install_receipt_sha256": activation_record["install_receipt_sha256"],
        "backend_activation_id": backend_receipt["activation_id"],
        "backend_activation_receipt_sha256": backend_receipt["receipt_sha256"],
    }
    if any(value.get(field) != expected[field] for field in expected):
        raise PrebindContractError("START operator binding differs from active instance")
    return value


def validate_start_binding_shape(raw: object, *, instance: Mapping[str, Any],
                                 install_record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != START_BINDING_FIELDS:
        raise PrebindContractError("START operator binding fields are invalid")
    value = dict(raw)
    expected = {
        "schema_version": START_BINDING_SCHEMA,
        "runner_instance_id": instance["runner_instance_id"],
        "runner_boot_id": instance["runner_boot_id"],
        "state_generation": instance["state_generation"],
        "signed_instance_sha256": digest(instance),
        "prepared_receipt_sha256": install_record["prepared_receipt_sha256"],
        "backend_binding_nonce": install_record["backend_binding_nonce"],
        "install_receipt_sha256": digest(install_record),
    }
    if any(value.get(field) != expected[field] for field in expected):
        raise PrebindContractError("START operator binding differs from installed candidate")
    if (not isinstance(value.get("backend_activation_id"), str)
            or _HEX32.fullmatch(value["backend_activation_id"]) is None
            or not isinstance(value.get("backend_activation_receipt_sha256"), str)
            or _HEX64.fullmatch(value["backend_activation_receipt_sha256"]) is None):
        raise PrebindContractError("START active receipt reference is invalid")
    return value


def make_install_record(*, instance: Mapping[str, Any], birth_mode: Mapping[str, Any],
                        prepared_receipt: Mapping[str, Any], installed_at: str,
                        key: bytes) -> dict[str, Any]:
    candidate = validate_prepared_receipt(prepared_receipt, instance=instance)
    record = {
        "schema_version": INSTALL_SCHEMA,
        "status": "installed_nonactive",
        "authorizes_start": False,
        "workspace_id": instance["workspace_id"],
        "runner_instance_id": instance["runner_instance_id"],
        "runner_boot_id": instance["runner_boot_id"],
        "state_generation": instance["state_generation"],
        "signed_instance_sha256": digest(instance),
        "birth_mode_sha256": digest(birth_mode),
        "prepared_receipt_sha256": candidate["receipt_sha256"],
        "backend_binding_nonce": candidate["backend_binding_nonce"],
        "prepared_receipt": candidate,
        "readback_sha256": digest({
            "instance_sha256": digest(instance),
            "birth_mode_sha256": digest(birth_mode),
            "prepared_receipt_sha256": candidate["receipt_sha256"],
            "backend_binding_nonce": candidate["backend_binding_nonce"],
        }),
        "installed_at": installed_at,
    }
    return sign_install_record(record, key=key)
