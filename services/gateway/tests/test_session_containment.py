"""ADR-0084 Product-visible containment and read-only recovery classification.

The Gateway derives everything from normalized BYQ WorkflowTrace + the fenced
adapter containment summary. These tests break the fail-closed behaviour with
negative controls: a malicious client cannot declare a step safe, an unverified
authority cannot recover, and ordinary failures are never misreported as
executor loss.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import session_containment as sc

TOKEN = "test-product-token"
RUN_A, RUN_B = "a" * 32, "b" * 32


def _event(sequence, kind, *, run_id=None, source="runtime-adapter", payload=None):
    body = dict(payload or {})
    if run_id is not None:
        body["run_id"] = run_id
    return {
        "trace_id": "trace-1", "session_id": "runtime-1", "sequence": sequence,
        "timestamp": "2026-09-21T00:00:00+00:00", "kind": kind, "source": source,
        "payload": body,
    }


def _interrupted_events(*, terminal="session.failed", run_id=RUN_A):
    return [_event(1, "session.started", run_id=run_id), _event(2, terminal, run_id=run_id)]


def _containment(*, run_id=RUN_A, trace_id="trace-1", session_id="runtime-1", cause="executor-loss"):
    return {"schema_version": "session-containment-summary.v1", "session_id": session_id,
            "contained": True, "attempts": 1,
            "latest": {"trace_id": trace_id, "loss_cause": cause,
                       "interrupted_run_id": run_id, "interrupted_generation": "generation-dead",
                       "executor_epoch": 1, "attempt": 1}}


def _authority(**overrides):
    base = {"owner_matches": True, "workspace_matches": True,
            "authorization_current": True, "budget_available": None,
            "source": "backend-auth-session"}
    base.update(overrides)
    return base


# --- loss evidence binding (Blocker 4) ---------------------------------------

def test_ordinary_failed_run_is_not_interrupted() -> None:
    loss = sc.loss_from_evidence(_interrupted_events(terminal="session.failed"),
                                 "runtime-1", "trace-1", _containment(run_id=RUN_B))
    # Containment is for a different run: an ordinary failure stays failed.
    assert loss["status"] == "failed"
    assert loss["interrupted"] is False
    assert loss["interrupted_run_id"] is None


def test_containment_for_another_trace_is_not_applied() -> None:
    loss = sc.loss_from_evidence(_interrupted_events(terminal="session.failed"),
                                 "runtime-1", "trace-1", _containment(trace_id="trace-other"))
    assert loss["status"] == "failed"
    assert loss["interrupted"] is False


def test_containment_without_a_run_identity_is_not_evidence() -> None:
    loss = sc.loss_from_evidence(_interrupted_events(terminal="session.failed"),
                                 "runtime-1", "trace-1", _containment(run_id=None))
    assert loss["status"] == "failed"


def test_missing_summary_session_binding_is_not_evidence() -> None:
    containment = _containment()
    containment.pop("session_id")
    loss = sc.loss_from_evidence(_interrupted_events(terminal="session.failed"),
                                 "runtime-1", "trace-1", containment)
    assert loss["status"] == "failed"
    assert loss["interrupted"] is False
    assert loss["interrupted_run_id"] is None


def test_missing_terminal_run_is_not_interruption() -> None:
    events = _interrupted_events(terminal="session.failed")
    events[-1]["payload"] = {}
    loss = sc.loss_from_evidence(events, "runtime-1", "trace-1", _containment())
    assert loss["status"] == "failed"
    assert loss["interrupted"] is False


def test_invalid_terminal_run_is_not_interruption() -> None:
    events = _interrupted_events(terminal="session.failed")
    events[-1]["payload"] = {"run_id": "not-a-run"}
    loss = sc.loss_from_evidence(events, "runtime-1", "trace-1", _containment())
    assert loss["status"] == "failed"
    assert loss["interrupted"] is False


def test_no_terminal_and_matching_containment_is_the_loss_terminal() -> None:
    loss = sc.loss_from_evidence([_event(1, "session.started", run_id=RUN_A)],
                                 "runtime-1", "trace-1", _containment())
    assert loss["status"] == "interrupted"
    assert loss["interrupted_run_id"] == RUN_A


def test_matching_fenced_containment_projects_interrupted() -> None:
    loss = sc.loss_from_evidence(_interrupted_events(terminal="session.failed"),
                                 "runtime-1", "trace-1", _containment())
    assert loss["status"] == "interrupted"
    assert loss["interrupted_run_id"] == RUN_A
    assert loss["loss_cause"] == "executor-loss"


def test_cancelled_and_discarded_keep_their_semantics() -> None:
    assert sc.loss_from_evidence(_interrupted_events(terminal="session.cancelled"),
                                 "runtime-1", "trace-1", None)["status"] == "cancelled"
    assert sc.loss_from_evidence(_interrupted_events(terminal="session.result.discarded"),
                                 "runtime-1", "trace-1", None)["status"] == "discarded"
    # A raw DSH event is never a source, so it cannot prove an interruption.
    raw = [_event(1, "session.failed", run_id=RUN_A, source="dsh")]
    assert sc.loss_from_evidence(raw, "runtime-1", "trace-1", _containment())["status"] == "interrupted"
    assert sc.loss_from_evidence(raw, "runtime-1", "trace-1", None)["status"] == "active"


# --- classification / preservation -------------------------------------------

def test_unverified_authority_pauses_and_preservation_is_not_constant() -> None:
    projection = sc.project_containment(
        _interrupted_events(), session_id="runtime-1", trace_id="trace-1",
        conversation_id="conversation_1", adapter_containment=_containment(),
        authority=_authority(budget_available=None))
    assert projection["status"] == "interrupted"
    assert projection["recovery"]["status"] == "paused"
    assert projection["recovery"]["reason"] == "authority_unavailable"
    assert projection["submission"] == "not_performed"
    states = projection["preservation"]["states"]
    assert states["conversation"] == "preserved"
    assert states["workflow_trace"] == "preserved"
    assert states["durable_job"] == "unknown"
    assert states["idempotency_keys"] == "unknown"
    assert projection["preservation"]["boundary_verified"] is False
    assert projection["preservation"]["boundary_invariant"].startswith("execution-boundary")


def test_no_authoritative_step_metadata_never_becomes_eligible() -> None:
    # Even with fully verified authority, the absent step-safety metadata keeps
    # the classification paused; it can never auto-retry.
    projection = sc.project_containment(
        _interrupted_events(), session_id="runtime-1", trace_id="trace-1",
        conversation_id="conversation_1", adapter_containment=_containment(),
        authority=_authority(budget_available=True))
    assert projection["recovery"]["status"] == "paused"
    assert projection["recovery"]["auto_retry"] is False
    assert projection["recovery"]["reason"] in {"non_idempotent_step", "receipt_unknown", "receipt_absent"}


def test_preservation_rejects_a_preserved_field_without_a_source() -> None:
    from packages.contracts import session_failure_containment as c
    with pytest.raises(ValueError, match="authoritative source"):
        c.validate_preservation({
            "schema_version": c.PRESERVATION_SCHEMA_VERSION,
            "states": {field: ("preserved" if field == "conversation" else "unknown")
                       for field in c.PRESERVED_FIELDS},
            "boundary_invariant": c.BOUNDARY_INVARIANT,
            "boundary_verified": False, "sources": {"workflow_trace": "trace-store"}})
    with pytest.raises(ValueError, match="self-verified"):
        c.validate_preservation({
            "schema_version": c.PRESERVATION_SCHEMA_VERSION,
            "states": {field: "unknown" for field in c.PRESERVED_FIELDS},
            "boundary_invariant": c.BOUNDARY_INVARIANT,
            "boundary_verified": True, "sources": {"boundary": "assertion"}})


# --- route-level tests --------------------------------------------------------

def _client(monkeypatch, tmp_path, *, cookie_user=None, conversation_owner="product-user"):
    from fastapi.testclient import TestClient
    from app import main
    from app.trace_store import TraceStore

    monkeypatch.setattr(main, "PRODUCT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "product_sessions", main.ProductSessionRegistry())
    store = TraceStore(tmp_path / "traces")
    monkeypatch.setattr(main, "trace_store", store)
    principal = main.Principal(subject=main.PRODUCT_PRINCIPAL)
    main.product_sessions.add(main.ProductSession(
        conversation_id="conversation_1", session_id="runtime-1", trace_id="trace-1",
        principal=principal, workspace_id="workspace_1"))
    calls = {"post": 0, "containment": 0, "catalog": []}

    def catalog_request(method, path, owner, workspace, **_kwargs):
        calls["catalog"].append((method, path, owner.subject, workspace))
        if owner.subject != conversation_owner:
            raise main.HTTPException(status_code=404, detail="conversation not found")
        return {
            "conversation": {"conversation_id": "conversation_1", "runtime_session_id": "runtime-1",
                             "trace_id": "trace-1", "status": "active",
                             "owner_principal": conversation_owner},
            "messages": [],
        }

    def adapter_post(*_args, **_kwargs):
        calls["post"] += 1
        return {}

    def adapter_containment(*_args, **_kwargs):
        calls["containment"] += 1
        return _containment()

    monkeypatch.setattr(main, "_catalog_request", catalog_request)
    monkeypatch.setattr(main, "_adapter_post", adapter_post)
    monkeypatch.setattr(main, "_adapter_containment", adapter_containment)
    if cookie_user is not None:
        monkeypatch.setattr(main, "resolve_user", lambda _request: cookie_user)
    return TestClient(main.app), store, calls, main


def _headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_removed_standalone_routes_return_404_without_side_effects(monkeypatch, tmp_path: Path) -> None:
    client, _store, calls, _main = _client(monkeypatch, tmp_path)
    for suffix in ("containment", "recovery"):
        response = client.get(f"/v1/agent/sessions/conversation_1/{suffix}", headers=_headers())
        assert response.status_code == 404
    assert calls == {"post": 0, "containment": 0, "catalog": []}


def test_session_replay_is_owner_scoped_and_includes_neutral_containment(
    monkeypatch, tmp_path: Path,
) -> None:
    client, store, calls, _main = _client(
        monkeypatch, tmp_path,
        cookie_user={"username": "product-user", "status": "active",
                     "_workspace": {"workspace_id": "workspace_1"}})
    for event in _interrupted_events():
        store.append(event)

    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers(),
                          cookies={"byq_session": "s"})
    assert response.status_code == 200
    assert calls["catalog"] == [(
        "GET", "/v1/product/conversations/conversation_1", "product-user", "workspace_1")]
    assert calls["containment"] == 1
    assert calls["post"] == 0

    body = response.json()
    projection = body["containment"]
    assert projection["status"] == "interrupted"
    assert projection["loss_cause"] == "executor-loss"
    assert projection["interrupted_run_id"] == RUN_A
    assert projection["trace_id"] == "trace-1"
    assert projection["preservation"]["states"]["conversation"] == "preserved"
    assert projection["preservation"]["states"]["workflow_trace"] == "preserved"
    assert projection["submission"] == "not_performed"
    assert projection["recovery"]["status"] == "paused"
    assert projection["recovery"]["reason"] == "authority_unavailable"
    serialized = json.dumps(body)
    assert "runtime-1" not in serialized
    assert '"dsh"' not in serialized.lower()


def test_session_replay_does_not_apply_containment_from_another_run_or_trace(
    monkeypatch, tmp_path: Path,
) -> None:
    client, store, _calls, main = _client(monkeypatch, tmp_path)
    for event in _interrupted_events():
        store.append(event)
    monkeypatch.setattr(main, "_adapter_containment",
                        lambda _session_id: _containment(run_id=RUN_B))
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers())
    assert response.status_code == 200
    assert response.json()["containment"]["status"] == "failed"
    assert response.json()["containment"]["interrupted_run_id"] is None

    client, store, _calls, main = _client(monkeypatch, tmp_path / "other-trace")
    for event in _interrupted_events():
        store.append(event)
    monkeypatch.setattr(main, "_adapter_containment",
                        lambda _session_id: _containment(trace_id="trace-other"))
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers())
    assert response.status_code == 200
    assert response.json()["containment"]["status"] == "failed"
    assert response.json()["containment"]["interrupted_run_id"] is None


def test_session_replay_returns_404_for_another_owner(monkeypatch, tmp_path: Path) -> None:
    client, _store, calls, _main = _client(
        monkeypatch, tmp_path, conversation_owner="another-user",
        cookie_user={"username": "product-user", "status": "active",
                     "_workspace": {"workspace_id": "workspace_1"}})
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers(),
                          cookies={"byq_session": "s"})
    assert response.status_code == 404
    assert calls["catalog"] == [(
        "GET", "/v1/product/conversations/conversation_1", "product-user", "workspace_1")]
    assert calls["containment"] == 0
    assert calls["post"] == 0


def test_session_replay_of_cancelled_run_blocks_without_submission(monkeypatch, tmp_path: Path) -> None:
    client, store, calls, _main = _client(monkeypatch, tmp_path)
    for event in _interrupted_events(terminal="session.cancelled"):
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers())
    projection = response.json()["containment"]
    assert projection["recovery"]["status"] == "blocked"
    assert projection["recovery"]["reason"] == "cancelled"
    assert projection["submission"] == "not_performed"
    assert calls["post"] == 0


def test_session_replay_with_unknown_budget_pauses(monkeypatch, tmp_path: Path) -> None:
    client, store, calls, _main = _client(
        monkeypatch, tmp_path,
        cookie_user={"username": "product-user", "status": "active",
                     "_workspace": {"workspace_id": "workspace_1"}})
    for event in _interrupted_events():
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers(),
                          cookies={"byq_session": "s"})
    decision = response.json()["containment"]["recovery"]
    assert decision["status"] == "paused"
    assert decision["reason"] == "authority_unavailable"
    assert calls["post"] == 0


@pytest.mark.parametrize("authority,reason", [
    ({"budget_available": False}, "budget_exhausted"),
    ({"authorization_current": False}, "authorization_revoked"),
    ({"owner_matches": False}, "owner_workspace_mismatch"),
    ({"workspace_matches": False}, "owner_workspace_mismatch"),
])
def test_session_replay_fails_closed_on_authoritative_denial(
    monkeypatch, tmp_path: Path, authority, reason,
) -> None:
    client, store, calls, main = _client(
        monkeypatch, tmp_path,
        cookie_user={"username": "product-user", "status": "active",
                     "_workspace": {"workspace_id": "workspace_1"}})
    base = _authority(**authority)
    monkeypatch.setattr(main, "_recovery_authority", lambda *_args, **_kwargs: base)
    for event in _interrupted_events():
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers(),
                          cookies={"byq_session": "s"})
    decision = response.json()["containment"]["recovery"]
    assert decision["status"] == "blocked"
    assert decision["reason"] == reason
    assert calls["post"] == 0


def test_disabled_user_status_blocks_replay_recovery(monkeypatch, tmp_path: Path) -> None:
    client, store, calls, _main = _client(
        monkeypatch, tmp_path,
        cookie_user={"username": "product-user", "status": "disabled",
                     "_workspace": {"workspace_id": "workspace_1"}})
    for event in _interrupted_events():
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers(),
                          cookies={"byq_session": "s"})
    decision = response.json()["containment"]["recovery"]
    assert decision["status"] == "blocked"
    assert decision["reason"] == "authorization_revoked"
    assert calls["post"] == 0
