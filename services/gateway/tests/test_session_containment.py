"""ADR-0084 Product-visible containment and bounded recovery (Gateway).

The Gateway derives everything from normalized BYQ WorkflowTrace + the durable
adapter containment summary. These tests break the fail-closed classification and
the exactly-one-attempt guarantee with negative controls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.contracts import session_failure_containment as contract
from app import session_containment as sc

TOKEN = "test-product-token"


def _event(sequence, kind, *, run_id=None, source="runtime-adapter"):
    return {
        "trace_id": "trace-1", "session_id": "runtime-1", "sequence": sequence,
        "timestamp": "2026-09-21T00:00:00+00:00", "kind": kind, "source": source,
        "payload": ({} if run_id is None else {"run_id": run_id}),
    }


def _interrupted_events(*, terminal="session.failed", run_id="a" * 32):
    return [
        _event(1, "session.started", run_id=run_id),
        _event(2, terminal, run_id=run_id),
    ]


def _project(events, **overrides):
    base = dict(session_id="runtime-1", trace_id="trace-1", conversation_id="conversation_1")
    base.update(overrides)
    return sc.project_containment(events, **base)


def test_unknown_side_effect_is_paused_with_a_visible_reason() -> None:
    projection = _project(_interrupted_events(), adapter_containment={
        "contained": True, "latest": {"loss_cause": "executor-loss", "interrupted_run_id": "a" * 32}})
    assert projection["status"] == "interrupted"
    assert projection["loss_cause"] == "executor-loss"
    assert projection["interrupted_run_id"] == "a" * 32
    assert projection["recovery"]["status"] == "paused"
    assert projection["recovery"]["reason"] == "non_idempotent_step"
    assert projection["recovery"]["requires_confirmation"] is True
    assert projection["recovery"]["auto_retry"] is False


def test_existing_success_receipt_is_never_replayed() -> None:
    projection = _project(
        _interrupted_events(),
        step={"idempotent": True, "result_verifiable": True},
        receipts={"success": True, "queryable": True})
    assert projection["recovery"]["status"] == "settled"
    assert projection["recovery"]["reason"] == "existing_success_receipt"
    assert projection["recovery"]["auto_retry"] is False


def test_declared_idempotent_result_verifiable_step_is_eligible() -> None:
    projection = _project(
        _interrupted_events(),
        step={"idempotent": True, "result_verifiable": True},
        receipts={"success": False, "queryable": True})
    assert projection["recovery"]["status"] == "eligible"
    assert projection["recovery"]["auto_retry"] is True
    assert projection["recovery"]["lineage"]["previous_run_id"] == "a" * 32


@pytest.mark.parametrize("terminal,reason", [
    ("session.cancelled", "cancelled"),
])
def test_cancel_blocks_recovery(terminal, reason) -> None:
    projection = _project(_interrupted_events(terminal=terminal),
                          step={"idempotent": True, "result_verifiable": True},
                          receipts={"success": False, "queryable": True})
    assert projection["status"] == "cancelled"
    assert projection["recovery"]["status"] == "blocked"
    assert projection["recovery"]["reason"] == reason


@pytest.mark.parametrize("overrides,reason", [
    ({"authorization_current": False}, "authorization_revoked"),
    ({"owner_matches": False}, "owner_workspace_mismatch"),
    ({"workspace_matches": False}, "owner_workspace_mismatch"),
    ({"budget_available": False}, "budget_exhausted"),
])
def test_hard_invariants_block_recovery(overrides, reason) -> None:
    projection = _project(
        _interrupted_events(),
        step={"idempotent": True, "result_verifiable": True},
        receipts={"success": False, "queryable": True}, **overrides)
    assert projection["recovery"]["status"] == "blocked"
    assert projection["recovery"]["reason"] == reason
    assert projection["recovery"]["auto_retry"] is False


def test_recovery_attempt_store_creates_exactly_one_attempt_with_lineage(tmp_path: Path) -> None:
    store = sc.RecoveryAttemptStore(tmp_path, now=lambda: 1.0)
    ledger = store.guard(
        "conversation_1", previous_run_id="a" * 32, idempotency_key="original-key-1",
        submit=lambda: "b" * 32)
    assert [row["attempt"] for row in ledger["attempts"]] == [1]
    assert ledger["attempts"][0]["previous_run_id"] == "a" * 32
    assert ledger["attempts"][0]["new_run_id"] == "b" * 32
    assert ledger["attempts"][0]["state"] == "in_progress"
    contract.validate_attempt_ledger(ledger)

    # A concurrent request while the first attempt is open must not create a second.
    with pytest.raises(sc.RecoveryConflict):
        store.guard("conversation_1", previous_run_id="a" * 32,
                    idempotency_key="original-key-1", submit=lambda: "c" * 32)
    assert len(store.read("conversation_1")["attempts"]) == 1

    # Only after the attempt settles may a new one be created, chaining lineage.
    store.settle("conversation_1", attempt=1, state="failed")
    second = store.guard("conversation_1", previous_run_id="a" * 32,
                         idempotency_key="original-key-1", submit=lambda: "d" * 32)
    assert [row["attempt"] for row in second["attempts"]] == [1, 2]
    assert second["attempts"][1]["previous_run_id"] == "b" * 32


def test_recovery_attempt_store_is_bounded(tmp_path: Path) -> None:
    store = sc.RecoveryAttemptStore(tmp_path)
    for index in range(contract.RECOVERY_ATTEMPT_MAX):
        store.guard("conversation_1", previous_run_id="a" * 32,
                    idempotency_key="original-key-1", submit=lambda i=index: f"{i:032x}")
        store.settle("conversation_1", attempt=index + 1, state="failed")
    with pytest.raises(sc.RecoveryConflict):
        store.guard("conversation_1", previous_run_id="a" * 32,
                    idempotency_key="original-key-1", submit=lambda: "f" * 32)


def test_projection_ignores_raw_dsh_events() -> None:
    raw = _event(1, "session.failed", run_id="a" * 32, source="dsh")
    projection = _project([raw])
    assert projection["status"] == "active"
    assert projection["recovery"] is None


def _client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main
    from app.trace_store import TraceStore

    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path / "traces")
    monkeypatch.setattr(main, "trace_store", store)
    monkeypatch.setattr(main, "recovery_attempts", sc.RecoveryAttemptStore(tmp_path / "attempts"))
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    main.product_sessions.add(main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-1", trace_id="trace-1",
        principal=principal, workspace_id="workspace_bootstrap_unresolved"))
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: {
        "conversation": {"conversation_id": "conversation_1", "runtime_session_id": "runtime-1",
                         "trace_id": "trace-1", "status": "active"},
        "messages": [], "message": {"message_id": "original-key-1"}})
    monkeypatch.setattr(main, "project_recovery", lambda *_a, **_k: ([], {
        "schema_version": "conversation-recovery.v2", "session_id": "runtime-1",
        "trace_id": "trace-1", "status": "resolved",
        "unanswered_turn": {"message_id": "original-key-1", "content": "继续原研究"},
        "failure": {"sequence": 3, "run_id": "a" * 32, "code": "model-run-failed"}}))
    monkeypatch.setattr(main, "_adapter_containment", lambda *_a, **_k: {
        "contained": True, "latest": {"loss_cause": "executor-loss",
                                      "interrupted_run_id": "a" * 32}})
    for event in _interrupted_events():
        store.append(event)
    return TestClient(main.app), store, main


def test_recovery_attempt_endpoint_records_lineage(monkeypatch, tmp_path: Path) -> None:
    client, _store, main = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "_adapter_prompt_receipt", lambda *_a, **_k: None)
    monkeypatch.setattr(main, "_adapter_post", lambda *_a, **_k: {"accepted": True, "run_id": "b" * 32})

    response = client.post(
        "/v1/agent/sessions/conversation_1/recovery-attempt",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"idempotency_key": "original-key-1", "step": {"idempotent": True, "result_verifiable": True}})

    assert response.status_code == 200
    body = response.json()
    assert body["previous_run_id"] == "a" * 32
    assert body["new_run_id"] == "b" * 32
    assert [row["attempt"] for row in body["lineage"]] == [1]
    # The projection now exposes the new-attempt lineage.
    projection = client.get(
        "/v1/agent/sessions/conversation_1/containment",
        headers={"Authorization": f"Bearer {TOKEN}"}).json()["containment"]
    assert projection["attempts"][0]["new_run_id"] == "b" * 32


def test_recovery_attempt_endpoint_refuses_unknown_side_effect(monkeypatch, tmp_path: Path) -> None:
    client, _store, main = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "_adapter_prompt_receipt", lambda *_a, **_k: None)
    calls: list[str] = []
    monkeypatch.setattr(main, "_adapter_post", lambda path, **_k: calls.append(path) or {})

    response = client.post(
        "/v1/agent/sessions/conversation_1/recovery-attempt",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"idempotency_key": "original-key-1"})

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "non_idempotent_step"
    assert calls == []  # no replay was attempted


def test_recovery_attempt_endpoint_settles_existing_receipt_without_replay(
    monkeypatch, tmp_path: Path,
) -> None:
    client, _store, main = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "_adapter_prompt_receipt",
                        lambda *_a, **_k: {"state": "accepted", "run_id": "a" * 32})
    calls: list[str] = []
    monkeypatch.setattr(main, "_adapter_post", lambda path, **_k: calls.append(path) or {})

    response = client.post(
        "/v1/agent/sessions/conversation_1/recovery-attempt",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"idempotency_key": "original-key-1", "step": {"idempotent": True, "result_verifiable": True}})

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "existing_success_receipt"
    assert calls == []


def test_get_product_session_includes_framework_neutral_containment(monkeypatch, tmp_path: Path) -> None:
    client, _store, _main = _client(monkeypatch, tmp_path)
    response = client.get("/v1/agent/sessions/conversation_1",
                          headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    containment = response.json()["containment"]
    assert containment["status"] == "interrupted"
    serialized = json.dumps(containment)
    assert "runtime-1" not in serialized
    assert "generation-" not in serialized
    assert "dsh" not in serialized.lower()
