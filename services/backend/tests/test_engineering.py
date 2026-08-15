from __future__ import annotations

import pytest

from app.engineering import EngineeringForbidden, EngineeringTaskStore


def create(store: EngineeringTaskStore, **overrides: object) -> dict[str, object]:
    payload = {
        "title": "isolate a small bug fix",
        "description": "Fix a bounded regression with tests and a draft PR.",
        "scope": "services/backend",
        "trace_id": "trace-engineering",
        "idempotency_key": "engineering-task-1",
    }
    payload.update(overrides)
    return store.create_task(payload, trusted_owner="alice", trusted_actor="alice")


def test_engineering_task_requires_isolated_evidence_before_completion(tmp_path) -> None:
    store = EngineeringTaskStore(tmp_path / "engineering.sqlite3")
    task = create(store)
    assert task["status"] == "proposed"
    assert create(store)["task_id"] == task["task_id"]

    with pytest.raises(EngineeringForbidden, match="approved"):
        store.transition(
            {"task_id": task["task_id"], "target_status": "in_progress", "idempotency_key": "bad-start"},
            trusted_owner="alice",
            trusted_actor="alice",
        )

    approved = store.transition(
        {"task_id": task["task_id"], "target_status": "approved", "idempotency_key": "approve"},
        trusted_owner="alice",
        trusted_actor="human-reviewer",
    )
    assert approved["status"] == "approved"

    in_progress = store.transition(
        {"task_id": task["task_id"], "target_status": "in_progress", "idempotency_key": "start"},
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert in_progress["status"] == "in_progress"

    with pytest.raises(EngineeringForbidden, match="worktree"):
        store.transition(
            {"task_id": task["task_id"], "target_status": "review_required", "idempotency_key": "no-worktree"},
            trusted_owner="alice",
            trusted_actor="alice",
        )

    store.report_evidence(
        {
            "task_id": task["task_id"],
            "worktree_path": "/home/jefison/projects/.byq-worktrees/phase-15-engineering-plane",
            "branch_name": "codex/phase-15-engineering-plane",
            "idempotency_key": "evidence-worktree",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    review = store.transition(
        {"task_id": task["task_id"], "target_status": "review_required", "idempotency_key": "review"},
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert review["status"] == "review_required"

    with pytest.raises(EngineeringForbidden, match="draft PR"):
        store.transition(
            {"task_id": task["task_id"], "target_status": "completed", "idempotency_key": "no-pr"},
            trusted_owner="alice",
            trusted_actor="alice",
        )

    store.report_evidence(
        {
            "task_id": task["task_id"],
            "draft_pr_number": 15,
            "ci_status": "success",
            "self_review": True,
            "architecture_evidence": {"boundary": "Product/Engineering separation"},
            "idempotency_key": "evidence-complete",
        },
        trusted_owner="alice",
        trusted_actor="alice",
    )
    completed = store.transition(
        {"task_id": task["task_id"], "target_status": "completed", "idempotency_key": "complete"},
        trusted_owner="alice",
        trusted_actor="alice",
    )
    assert completed["status"] == "completed"
    assert completed["merge_status"] == "not_merged"

    with pytest.raises(EngineeringForbidden, match="self"):
        store.record_human_merge(
            {"task_id": task["task_id"], "decision": "merged", "idempotency_key": "merge-self"},
            trusted_owner="alice",
            trusted_actor="alice",
        )
    merged = store.record_human_merge(
        {"task_id": task["task_id"], "decision": "merged", "rationale": "human reviewed", "idempotency_key": "merge-human"},
        trusted_owner="alice",
        trusted_actor="human-reviewer",
    )
    assert merged["merge_status"] == "merged"
    assert [item["decision"] for item in merged["history"][-1:]] == ["merge_merged"]
    store.close()


def test_engineering_task_rejects_non_isolated_worktree_and_secrets(tmp_path) -> None:
    store = EngineeringTaskStore(tmp_path / "engineering.sqlite3")
    task = create(store)
    with pytest.raises(ValueError, match="worktree"):
        store.report_evidence(
            {
                "task_id": task["task_id"],
                "worktree_path": "/home/jefison/projects/BeyondQuant",
                "branch_name": "codex/phase-15-engineering-plane",
                "idempotency_key": "bad-worktree",
            },
            trusted_owner="alice",
            trusted_actor="alice",
        )
    with pytest.raises(ValueError, match="credential"):
        store.report_evidence(
            {
                "task_id": task["task_id"],
                "architecture_evidence": {"nested": [{"github_token": "must-not-be-recorded"}]},
                "idempotency_key": "secret-evidence",
            },
            trusted_owner="alice",
            trusted_actor="alice",
        )
    store.close()
