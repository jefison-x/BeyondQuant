"""Closed Backend contract for a non-authorizing ACP runner prebind intent.

This contract records an Engineering-prepared candidate only. It does not
qualify a runner, authorize START, or attest native Docker facts by itself.
"""

from __future__ import annotations

import hashlib
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


class PrebindContractError(ValueError):
    """The Engineering prebind request is not closed or valid."""


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
