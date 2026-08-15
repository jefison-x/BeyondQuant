from __future__ import annotations

import pytest

from app.learning_loop import (
    LearningConflict,
    LearningForbidden,
    LearningLoopStore,
)
from app.research import ResearchStore


def make_task(store: ResearchStore, owner: str = "alice") -> dict[str, object]:
    return store.create_task(
        {
            "owner_principal": owner,
            "title": "learning task",
            "objective": "prove bounded learning",
            "trace_id": "trace-learning-task",
            "idempotency_key": "task-learning-1",
        }
    )


def make_artifact(
    research: ResearchStore,
    task_id: str,
    *,
    experiment_id: str | None = None,
    owner: str = "alice",
) -> dict[str, object]:
    artifact = research.create_artifact(
        {
            "task_id": task_id,
            "experiment_id": experiment_id,
            "kind": "research_evidence",
            "content": {"summary": "validated evidence"},
            "lineage": [],
            "trace_id": "trace-learning-artifact",
            "idempotency_key": f"artifact-learning-{task_id}-{experiment_id or 'none'}",
        }
    )
    return research.transition(
        "artifact",
        artifact["artifact_id"],
        "validated",
        f"validate-{artifact['artifact_id']}",
    )


def test_learning_run_is_bounded_idempotent_and_reaches_human_gate(tmp_path) -> None:
    research = ResearchStore(tmp_path / "research.sqlite3")
    task = make_task(research)
    store = LearningLoopStore(tmp_path / "learning.sqlite3", research)

    run = store.start_run(
        {
            "task_id": task["task_id"],
            "budget": {"max_iterations": 2, "max_repairs": 0},
            "lineage": [{"kind": "research_task", "id": task["task_id"]}],
            "trace_id": "trace-learning-run",
            "idempotency_key": "run-learning-1",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert run["status"] == "active"

    same = store.start_run(
        {
            "task_id": task["task_id"],
            "budget": {"max_iterations": 2, "max_repairs": 0},
            "lineage": [{"kind": "research_task", "id": task["task_id"]}],
            "trace_id": "trace-learning-run",
            "idempotency_key": "run-learning-1",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert same["learning_run_id"] == run["learning_run_id"]

    first = store.record_iteration(
        {
            "run_id": run["learning_run_id"],
            "iteration_index": 1,
            "attempt": 1,
            "outcome": "produced",
            "feedback": {"sharpe": 0.4},
            "trace_id": "trace-learning-iteration",
            "idempotency_key": "iteration-learning-1",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert first["run"]["status"] == "active"

    second = store.record_iteration(
        {
            "run_id": run["learning_run_id"],
            "iteration_index": 2,
            "attempt": 1,
            "outcome": "produced",
            "feedback": {"sharpe": 0.7},
            "trace_id": "trace-learning-iteration",
            "idempotency_key": "iteration-learning-2",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert second["run"]["status"] == "awaiting_review"

    with pytest.raises(LearningForbidden, match="budget"):
        store.record_iteration(
            {
                "run_id": run["learning_run_id"],
                "iteration_index": 3,
                "attempt": 1,
                "outcome": "produced",
                "trace_id": "trace-learning-iteration",
                "idempotency_key": "iteration-learning-3",
            },
            trusted_owner="alice",
            trusted_actor="alice",
        )

    listed = store.list_iterations(run["learning_run_id"], trusted_owner="alice")
    assert [item["iteration_index"] for item in listed["iterations"]] == [1, 2]
    store.close()
    research.close()


def test_failed_iteration_retry_and_human_review_are_explicit(tmp_path) -> None:
    research = ResearchStore(tmp_path / "research.sqlite3")
    task = make_task(research)
    store = LearningLoopStore(tmp_path / "learning.sqlite3", research)

    run = store.start_run(
        {
            "task_id": task["task_id"],
            "budget": {"max_iterations": 1, "max_repairs": 1},
            "trace_id": "trace-learning-retry",
            "idempotency_key": "run-retry-1",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    failed = store.record_iteration(
        {
            "run_id": run["learning_run_id"],
            "iteration_index": 1,
            "attempt": 1,
            "outcome": "failed",
            "feedback": {"reason": "retryable"},
            "trace_id": "trace-learning-retry",
            "idempotency_key": "retry-1",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert failed["run"]["status"] == "active"

    repaired = store.record_iteration(
        {
            "run_id": run["learning_run_id"],
            "iteration_index": 1,
            "attempt": 2,
            "outcome": "produced",
            "feedback": {"sharpe": 1.1},
            "trace_id": "trace-learning-retry",
            "idempotency_key": "retry-2",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert repaired["run"]["status"] == "awaiting_review"

    with pytest.raises(LearningForbidden, match="self-review"):
        store.review_run(
            {"run_id": run["learning_run_id"], "decision": "approved"},
            trusted_owner="alice",
            trusted_actor="alice",
        )

    approved = store.review_run(
        {"run_id": run["learning_run_id"], "decision": "approved", "rationale": "ok"},
        trusted_owner="alice",
        trusted_actor="human-reviewer",
    )
    assert approved["status"] == "completed"

    with pytest.raises(LearningForbidden, match="not awaiting"):
        store.review_run(
            {"run_id": run["learning_run_id"], "decision": "rejected"},
            trusted_owner="alice",
            trusted_actor="human-reviewer",
        )
    store.close()
    research.close()


def test_evaluation_signals_and_experiment_comparison_are_deterministic(tmp_path) -> None:
    research = ResearchStore(tmp_path / "research.sqlite3")
    task = make_task(research)
    experiment_a = research.create_experiment(
        {
            "task_id": task["task_id"],
            "name": "a",
            "input_snapshot": {"sources": [{"provider": "tushare", "endpoint": "daily", "request_fingerprint": "fp"}]},
            "trace_id": "trace-learning-exp-a",
            "idempotency_key": "experiment-a",
        }
    )
    experiment_b = research.create_experiment(
        {
            "task_id": task["task_id"],
            "name": "b",
            "input_snapshot": {"sources": [{"provider": "tushare", "endpoint": "daily", "request_fingerprint": "fp"}]},
            "trace_id": "trace-learning-exp-b",
            "idempotency_key": "experiment-b",
        }
    )
    artifact_a = make_artifact(research, task["task_id"], experiment_id=experiment_a["experiment_id"])
    artifact_b = make_artifact(research, task["task_id"], experiment_id=experiment_b["experiment_id"], owner="alice")

    store = LearningLoopStore(tmp_path / "learning.sqlite3", research)
    store.create_signal(
        {
            "task_id": task["task_id"],
            "experiment_id": experiment_a["experiment_id"],
            "source_artifact_id": artifact_a["artifact_id"],
            "metric": "sharpe",
            "value": 1.2,
            "trace_id": "trace-learning-signal",
            "idempotency_key": "signal-a",
        },
        trusted_owner="alice",
    )
    store.create_signal(
        {
            "task_id": task["task_id"],
            "experiment_id": experiment_b["experiment_id"],
            "source_artifact_id": artifact_b["artifact_id"],
            "metric": "sharpe",
            "value": 0.8,
            "trace_id": "trace-learning-signal",
            "idempotency_key": "signal-b",
        },
        trusted_owner="alice",
    )
    comparison = store.compare_experiments(
        {
            "task_id": task["task_id"],
            "experiment_a_id": experiment_a["experiment_id"],
            "experiment_b_id": experiment_b["experiment_id"],
            "metric": "sharpe",
        },
        trusted_owner="alice",
    )
    assert comparison["winner"] == "a"
    assert comparison["difference"] == pytest.approx(-0.4)
    store.close()
    research.close()


def test_lesson_promotion_requires_validated_evidence_and_human_review(tmp_path) -> None:
    research = ResearchStore(tmp_path / "research.sqlite3")
    task = make_task(research)
    artifact = make_artifact(research, task["task_id"])
    store = LearningLoopStore(tmp_path / "learning.sqlite3", research)

    proposed = store.propose_lesson(
        {
            "task_id": task["task_id"],
            "content": {"lesson": "validated evidence supports this"},
            "evidence": [{"kind": "artifact", "id": artifact["artifact_id"]}],
            "validation": {"source": "unit-test"},
            "trace_id": "trace-learning-lesson",
            "idempotency_key": "lesson-1",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert proposed["status"] == "proposed"
    assert proposed["evidence"] == [{"kind": "artifact", "id": artifact["artifact_id"]}]

    with pytest.raises(ValueError, match="at least one"):
        store.propose_lesson(
            {
                "task_id": task["task_id"],
                "content": {"lesson": "chat only"},
                "evidence": [],
                "validation": {},
                "trace_id": "trace-learning-lesson",
                "idempotency_key": "lesson-no-evidence",
            },
            trusted_owner="alice",
            trusted_actor="alice",
        )

    with pytest.raises(LearningForbidden, match="self-promote"):
        store.review_lesson(
            {"lesson_id": proposed["lesson_id"], "decision": "approved"},
            trusted_owner="alice",
            trusted_actor="alice",
        )

    approved = store.review_lesson(
        {"lesson_id": proposed["lesson_id"], "decision": "approved", "rationale": "reviewed"},
        trusted_owner="alice",
        trusted_actor="human-reviewer",
    )
    assert approved["status"] == "approved"
    assert [item["decision"] for item in approved["history"]] == ["approved"]
    store.close()
    research.close()


def test_learning_payloads_reject_secret_material(tmp_path) -> None:
    research = ResearchStore(tmp_path / "research.sqlite3")
    task = make_task(research)
    store = LearningLoopStore(tmp_path / "learning.sqlite3", research)
    with pytest.raises(ValueError, match="credential"):
        store.start_run(
            {
                "task_id": task["task_id"],
                "budget": {"max_iterations": 1, "max_repairs": 0},
                "stopping_rules": {"target_metric": "token", "target_value": 1, "operator": "gte"},
                "trace_id": "trace-learning-secret",
                "idempotency_key": "run-secret",
            },
            trusted_owner="alice",
            trusted_actor="alice",
        )
    store.close()
    research.close()
