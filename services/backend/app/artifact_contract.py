"""Stable, bounded projection for BYQ-owned Artifact rows.

ResearchStore remains the authority for Artifact content and lifecycle. This
contract exposes a durable Artifact identity and provenance without copying
the stored payload or object-store details into an Agent-facing response.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime


_ARTIFACT_ID = re.compile(r"^artifact_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_STATUSES = frozenset({"draft", "validated", "superseded"})
_METADATA_TEXT_LIMITS = {
    "title": 200,
    "summary": 512,
    "media_type": 128,
    "schema_version": 64,
}
_MAX_LINEAGE = 64


def project_artifact(row: Mapping[str, object]) -> dict[str, object]:
    """Project one stored Artifact into its stable, storage-independent shape."""
    artifact_id = _required_text(row.get("artifact_id"), "artifact_id", max_length=42)
    if _ARTIFACT_ID.fullmatch(artifact_id) is None:
        raise ValueError("artifact_id has an invalid format")

    workspace_id = _required_text(row.get("workspace_id"), "workspace_id", max_length=128)
    owner_principal = _required_text(row.get("owner_principal"), "owner_principal", max_length=128)
    artifact_type = _required_text(row.get("kind"), "kind", max_length=64)

    status = row.get("status")
    if not isinstance(status, str) or status not in _STATUSES:
        raise ValueError("artifact validation status is unknown")

    content_sha256 = row.get("content_sha256")
    if not isinstance(content_sha256, str) or _SHA256.fullmatch(content_sha256) is None:
        raise ValueError("artifact content hash is invalid")

    content = row.get("content")
    if not isinstance(content, Mapping):
        raise ValueError("artifact content must be an object")

    return {
        "artifact_id": artifact_id,
        "workspace_id": workspace_id,
        "type": artifact_type,
        "ref": {"kind": "artifact", "id": artifact_id},
        "metadata": _project_metadata(content.get("metadata", {})),
        "owner_principal": owner_principal,
        "validation": {"status": status, "content_sha256": content_sha256},
        "lineage": _project_lineage(row.get("lineage")),
        "created_at": _timestamp(row.get("created_at")),
    }


def _required_text(value: object, field: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > max_length:
        raise ValueError(f"artifact {field} is invalid")
    return value


def _project_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for field, limit in _METADATA_TEXT_LIMITS.items():
        item = value.get(field)
        if (
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or len(item) > limit
        ):
            continue
        result[field] = item
    return result


def _project_lineage(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > _MAX_LINEAGE:
        raise ValueError("artifact lineage is invalid")
    lineage: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"kind", "id"}:
            raise ValueError("artifact lineage entry is invalid")
        lineage.append({
            "kind": _required_text(item.get("kind"), "lineage.kind", max_length=64),
            "id": _required_text(item.get("id"), "lineage.id", max_length=128),
        })
    return lineage


def _timestamp(value: object) -> str:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("artifact created_at is invalid") from error
    else:
        raise ValueError("artifact created_at is invalid")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("artifact created_at must include a timezone")
    return timestamp.isoformat()
