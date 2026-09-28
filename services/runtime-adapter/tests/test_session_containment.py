"""In-process Adapter generation and late-terminal fencing tests."""
from __future__ import annotations

import pytest

from packages.contracts import session_failure_containment as containment_contract
from packages.contracts.session_failure_containment import FencedWrite
from app.runtime import RuntimeAdapter, SessionStatus
from .test_process_cleanup import FakeHarness, adapter, wait_for_status  # noqa: F401


def test_stale_generation_terminal_settlement_is_fenced(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.clear()
    adapter.create_session("loss-4", "loss-4-trace", "alice", "workspace_alice")
    adapter.submit_prompt("loss-4", "running")
    assert FakeHarness.run_started.wait(1.0)
    record = adapter._get("loss-4")
    old_generation = record.runtime_generation
    assert adapter._terminal_fenced(record, old_generation, record.executor_epoch) is False

    adapter.cancel_session("loss-4", "hard")
    resumed = adapter.resume_session("loss-4")
    assert resumed["continuity"] == "interrupted"
    assert record.runtime_generation != old_generation
    assert adapter._terminal_fenced(record, old_generation, record.executor_epoch) is True
    adapter.close()
    FakeHarness.allow_run.set()


def test_late_success_cannot_overwrite_a_newer_generation(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.clear()
    adapter.create_session("loss-5", "loss-5-trace", "alice", "workspace_alice")
    root = adapter.submit_prompt("loss-5", "running", idempotency_key="loss-5-key")
    assert FakeHarness.run_started.wait(1.0)
    record = adapter._get("loss-5")
    run = record.active_run
    assert run is not None
    adapter.cancel_session("loss-5", "hard")
    adapter.resume_session("loss-5")
    history_before = list(record.history)
    FakeHarness.allow_run.set()
    wait_for_status(adapter, "loss-5", SessionStatus.READY)
    assert record.history == history_before
    assert record.active_run is None
    assert run.run_id == root
    adapter.close()


def test_terminal_settlement_guard_rejects_duplicate_and_late(adapter: RuntimeAdapter) -> None:
    contract = containment_contract
    contract.assert_terminal_settlement(
        settled={1: "interrupted"}, write_attempt=2, write_terminal="interrupted",
    )
    with pytest.raises(FencedWrite):
        contract.assert_terminal_settlement(
            settled={1: "interrupted"}, write_attempt=1, write_terminal="interrupted",
        )
    with pytest.raises(FencedWrite):
        contract.assert_terminal_settlement(
            settled={1: "interrupted"}, write_attempt=1, write_terminal="completed",
        )
    with pytest.raises(FencedWrite):
        contract.assert_terminal_settlement(
            settled={2: "completed"}, write_attempt=1, write_terminal="interrupted",
        )
