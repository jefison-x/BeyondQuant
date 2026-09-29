from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.artifact_contract import project_artifact


def _artifact_row() -> dict[str, object]:
    return {
        "artifact_id": "artifact_0123456789abcdef0123456789abcdef",
        "workspace_id": "workspace_0123456789abcdef0123456789abcdef",
        "owner_principal": "alice",
        "kind": "backtest_result",
        "status": "validated",
        "content_sha256": "a" * 64,
        "content": {
            "metadata": {
                "title": "Backtest result",
                "media_type": "application/json",
                "storage_path": "/internal/object-store/path",
                "credential": "must-not-escape",
            },
            "result_reference": {
                "namespace": "backtest-results",
                "object_id": "b" * 64,
                "media_type": "application/json",
                "size": 10,
                "sha256": "b" * 64,
            },
            "returns": [0.1, 0.2],
        },
        "lineage": [
            {"kind": "research_task", "id": "task_0123456789abcdef0123456789abcdef"},
            {"kind": "strategy_version", "id": "artifact_fedcba9876543210fedcba9876543210"},
        ],
        "created_at": datetime(2026, 9, 29, 1, 2, 3, tzinfo=timezone.utc),
        "task_id": "task_0123456789abcdef0123456789abcdef",
        "experiment_id": "experiment_0123456789abcdef0123456789abcdef",
        "trace_id": "trace-internal",
        "idempotency_key": "write-internal",
        "request_hash": "c" * 64,
        "version": 3,
        "updated_at": datetime(2026, 9, 29, 1, 2, 4, tzinfo=timezone.utc),
    }


def test_artifact_projection_keeps_stable_identity_validation_and_lineage() -> None:
    projected = project_artifact(_artifact_row())

    assert projected == {
        "artifact_id": "artifact_0123456789abcdef0123456789abcdef",
        "workspace_id": "workspace_0123456789abcdef0123456789abcdef",
        "type": "backtest_result",
        "ref": {
            "kind": "artifact",
            "id": "artifact_0123456789abcdef0123456789abcdef",
        },
        "metadata": {
            "title": "Backtest result",
            "media_type": "application/json",
        },
        "owner_principal": "alice",
        "validation": {"status": "validated", "content_sha256": "a" * 64},
        "lineage": [
            {"kind": "research_task", "id": "task_0123456789abcdef0123456789abcdef"},
            {"kind": "strategy_version", "id": "artifact_fedcba9876543210fedcba9876543210"},
        ],
        "created_at": "2026-09-29T01:02:03+00:00",
    }


def test_artifact_projection_does_not_expose_payload_or_storage_internals() -> None:
    projected = project_artifact(_artifact_row())

    assert "content" not in projected
    assert "result_reference" not in projected
    assert "task_id" not in projected
    assert "experiment_id" not in projected
    assert "trace_id" not in projected
    assert "idempotency_key" not in projected
    assert "request_hash" not in projected
    assert "version" not in projected
    assert projected["metadata"] == {
        "title": "Backtest result",
        "media_type": "application/json",
    }


@pytest.mark.parametrize(("field", "value"), [
    ("artifact_id", "artifact_short"),
    ("workspace_id", " "),
    ("owner_principal", None),
    ("status", "completed"),
    ("content_sha256", "not-a-sha256"),
    ("created_at", datetime(2026, 9, 29, 1, 2, 3)),
])
def test_artifact_projection_rejects_invalid_identity_or_validation_fields(
    field: str, value: object,
) -> None:
    row = _artifact_row()
    row[field] = value

    with pytest.raises(ValueError):
        project_artifact(row)


@pytest.mark.parametrize("kind", ["BacktestResult", "custom-kind", "risk model v2"])
def test_artifact_projection_preserves_existing_noncanonical_kind_labels(kind: str) -> None:
    row = _artifact_row()
    row["kind"] = kind

    assert project_artifact(row)["type"] == kind


def test_artifact_projection_skips_malformed_or_oversized_metadata_fields() -> None:
    row = _artifact_row()
    row["content"] = {"metadata": {
        "title": "x" * 201,
        "summary": 42,
        "media_type": "application/json",
        "storage_path": "/internal/object-store/path",
    }}

    assert project_artifact(row)["metadata"] == {"media_type": "application/json"}


def test_artifact_projection_omits_non_object_metadata() -> None:
    row = _artifact_row()
    row["content"] = {"metadata": ["unexpected", "legacy", "shape"]}

    assert project_artifact(row)["metadata"] == {}


@pytest.mark.parametrize(("field", "value"), [
    ("lineage", [{"kind": "task", "id": "task_1", "extra": "raw"}]),
    ("lineage", [None]),
])
def test_artifact_projection_rejects_malformed_provenance(field: str, value: object) -> None:
    row = deepcopy(_artifact_row())
    row[field] = value

    with pytest.raises(ValueError):
        project_artifact(row)
