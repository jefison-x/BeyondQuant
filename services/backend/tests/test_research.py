from __future__ import annotations

import hashlib
import json

import pytest

from app.research import (
    IdempotencyConflict,
    InvalidTransition,
    ResearchNotFound,
    ResearchStore,
)


def task_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "owner_principal": "product-user",
        "title": "Daily signal study",
        "objective": "Compare a bounded daily input snapshot.",
        "trace_id": "byq-trace-test-1",
        "idempotency_key": "task-create-1",
    }
    payload.update(overrides)
    return payload


def snapshot() -> dict[str, object]:
    return {
        "sources": [
            {
                "provider": "tushare",
                "endpoint": "daily",
                "request_fingerprint": "fixture-fingerprint",
                "row_count": 2,
            }
        ],
        "symbols": ["000001.SZ"],
    }


def experiment_payload(task_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_id": task_id,
        "name": "Daily input experiment",
        "input_snapshot": snapshot(),
        "trace_id": "byq-trace-test-1",
        "idempotency_key": "experiment-create-1",
    }
    payload.update(overrides)
    return payload


def artifact_payload(task_id: str, experiment_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_id": task_id,
        "experiment_id": experiment_id,
        "kind": "evidence",
        "content": {"close": 10.5, "observation": "fixture"},
        "lineage": [{"kind": "data_snapshot", "id": "fixture-fingerprint"}],
        "trace_id": "byq-trace-test-1",
        "idempotency_key": "artifact-create-1",
    }
    payload.update(overrides)
    return payload


def test_research_entities_persist_with_lineage_and_provenance(tmp_path) -> None:
    path = tmp_path / "domain.sqlite3"
    store = ResearchStore(path)
    task = store.create_task(task_payload())
    experiment = store.create_experiment(experiment_payload(task["task_id"]))
    artifact = store.create_artifact(artifact_payload(task["task_id"], experiment["experiment_id"]))
    store.close()

    reopened = ResearchStore(path)
    assert reopened.get_task(task["task_id"])["status"] == "planned"
    assert reopened.get_experiment(experiment["experiment_id"])["input_snapshot"] == snapshot()
    assert artifact["status"] == "draft"
    assert artifact["lineage"][:2] == [
        {"kind": "research_task", "id": task["task_id"]},
        {"kind": "experiment", "id": experiment["experiment_id"]},
    ]
    canonical = json.dumps(
        {"close": 10.5, "observation": "fixture"},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert artifact["content_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert "request_hash" not in artifact
    assert "idempotency_key" not in artifact
    reopened.close()


def test_create_and_transition_are_idempotent_and_conflicts_are_rejected(tmp_path) -> None:
    store = ResearchStore(tmp_path / "domain.sqlite3")
    first = store.create_task(task_payload())
    retry = store.create_task(task_payload())
    assert retry == first

    with pytest.raises(IdempotencyConflict):
        store.create_task(task_payload(title="different"))

    running = store.transition("research_task", first["task_id"], "running", "transition-1")
    assert running["status"] == "running"
    repeated = store.transition("research_task", first["task_id"], "running", "transition-1")
    assert repeated == running
    completed = store.transition("research_task", first["task_id"], "completed", "transition-2")
    assert completed["status"] == "completed"
    original_retry = store.transition("research_task", first["task_id"], "running", "transition-1")
    assert original_retry == running
    with pytest.raises(InvalidTransition):
        store.transition("research_task", first["task_id"], "running", "transition-3")
    store.close()


def test_experiment_requires_phase8_provenance_and_artifact_rejects_secrets(tmp_path) -> None:
    store = ResearchStore(tmp_path / "domain.sqlite3")
    task = store.create_task(task_payload())

    with pytest.raises(ValueError, match="sources"):
        store.create_experiment(experiment_payload(task["task_id"], input_snapshot={"symbols": []}))
    with pytest.raises(ValueError, match="credential"):
        store.create_artifact(
            artifact_payload(task["task_id"], "experiment_deadbeefdeadbeefdeadbeefdeadbeef", content={"token": "secret"})
        )
    with pytest.raises(ValueError, match="credential"):
        store.create_artifact(
            artifact_payload(
                task["task_id"],
                "experiment_deadbeefdeadbeefdeadbeefdeadbeef",
                content={"nested": {"provider_token": "secret", "apiKey": "secret"}},
            )
        )
    with pytest.raises(ResearchNotFound):
        store.get_task("task_00000000000000000000000000000000")
    store.close()


def test_artifact_content_hash_is_canonical_across_object_key_order(tmp_path) -> None:
    store = ResearchStore(tmp_path / "domain.sqlite3")
    task = store.create_task(task_payload(idempotency_key="task-hash-1"))
    experiment = store.create_experiment(
        experiment_payload(task["task_id"], idempotency_key="experiment-hash-1")
    )
    first = store.create_artifact(
        artifact_payload(
            task["task_id"],
            experiment["experiment_id"],
            idempotency_key="artifact-hash-1",
            content={"b": 2, "a": 1},
        )
    )
    second = store.create_artifact(
        artifact_payload(
            task["task_id"],
            experiment["experiment_id"],
            idempotency_key="artifact-hash-2",
            content={"a": 1, "b": 2},
        )
    )
    assert first["content_sha256"] == second["content_sha256"]
    store.close()


def test_list_tasks_and_experiments_are_owner_scoped(tmp_path) -> None:
    store = ResearchStore(tmp_path / "domain.sqlite3")
    task = store.create_task(task_payload(idempotency_key="task-list-1"))
    experiment = store.create_experiment(experiment_payload(task["task_id"], idempotency_key="experiment-list-1"))

    listed_tasks = store.list_tasks(owner_principal="product-user")
    listed_experiments = store.list_experiments(owner_principal="product-user")
    assert listed_tasks["tasks"][0]["task_id"] == task["task_id"]
    assert listed_experiments["experiments"][0]["experiment_id"] == experiment["experiment_id"]
    assert store.list_tasks(owner_principal="someone-else")["tasks"] == []
    assert store.list_experiments(owner_principal="someone-else")["experiments"] == []
    store.close()
