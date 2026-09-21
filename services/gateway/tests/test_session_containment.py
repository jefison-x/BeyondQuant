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
    monkeypatch.setattr(main, "_catalog_request", lambda *_a, **_k: {
        "conversation": {"conversation_id": "conversation_1", "runtime_session_id": "runtime-1",
                         "trace_id": "trace-1", "status": "active",
                         "owner_principal": conversation_owner},
        "messages": []})
    calls = {"post": 0, "containment": 0}

    def adapter_post(*_a, **_k):
        calls["post"] += 1
        return {}

    def adapter_containment(*_a, **_k):
        calls["containment"] += 1
        return _containment()

    monkeypatch.setattr(main, "_adapter_post", adapter_post)
    monkeypatch.setattr(main, "_adapter_containment", adapter_containment)
    if cookie_user is not None:
        monkeypatch.setattr(main, "resolve_user", lambda _request: cookie_user)
    return TestClient(main.app), store, calls, main


def _headers(cookie=False):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    return headers


def test_recovery_endpoint_is_read_only_and_never_submits(monkeypatch, tmp_path: Path) -> None:
    client, store, calls, _main = _client(monkeypatch, tmp_path)
    for event in _interrupted_events():
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1/recovery",
                          headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["submitted"] is False
    assert body["containment"]["submission"] == "not_performed"
    # Unverified bootstrap authority pauses; no adapter call at all.
    assert body["containment"]["recovery"]["status"] == "paused"
    assert body["containment"]["recovery"]["reason"] == "authority_unavailable"
    assert calls["post"] == 0


def test_malicious_step_declaration_has_no_effect(monkeypatch, tmp_path: Path) -> None:
    client, store, calls, _main = _client(monkeypatch, tmp_path)
    for event in _interrupted_events():
        store.append(event)
    # A client attempting to declare the step safe must not change anything: the
    # request has no safety field and no adapter prompt is ever sent.
    response = client.request(
        "GET", "/v1/agent/sessions/conversation_1/recovery", headers=_headers(),
        json={"step": {"idempotent": True, "result_verifiable": True},
              "idempotency_key": "original-key-1"})
    assert response.status_code == 200
    assert response.json()["submitted"] is False
    assert calls["post"] == 0


def test_cancel_blocks_with_zero_adapter_calls(monkeypatch, tmp_path: Path) -> None:
    client, store, calls, _main = _client(monkeypatch, tmp_path)
    for event in _interrupted_events(terminal="session.cancelled"):
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1/recovery", headers=_headers())
    assert response.json()["containment"]["recovery"]["status"] == "blocked"
    assert response.json()["containment"]["recovery"]["reason"] == "cancelled"
    assert calls == {"post": 0, "containment": 0}


def test_verified_authority_but_no_budget_metadata_pauses_with_zero_adapter_calls(
    monkeypatch, tmp_path: Path,
) -> None:
    client, store, calls, _main = _client(
        monkeypatch, tmp_path,
        cookie_user={"username": "product-user", "status": "active",
                     "_workspace": {"workspace_id": "workspace_1"}})
    for event in _interrupted_events():
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1/recovery",
                          headers=_headers(), cookies={"byq_session": "s"})
    decision = response.json()["containment"]["recovery"]
    # Owner/workspace/authorization verified; budget is unknown -> paused.
    assert decision["status"] == "paused"
    assert decision["reason"] == "authority_unavailable"
    assert calls["post"] == 0


@pytest.mark.parametrize("authority,reason", [
    ({"budget_available": False}, "budget_exhausted"),
    ({"authorization_current": False}, "authorization_revoked"),
    ({"owner_matches": False}, "owner_workspace_mismatch"),
    ({"workspace_matches": False}, "owner_workspace_mismatch"),
])
def test_authoritative_denial_blocks_with_zero_adapter_calls(
    monkeypatch, tmp_path: Path, authority, reason,
) -> None:
    client, store, calls, main = _client(
        monkeypatch, tmp_path,
        cookie_user={"username": "product-user", "status": "active",
                     "_workspace": {"workspace_id": "workspace_1"}})
    base = _authority(**authority)
    monkeypatch.setattr(main, "_recovery_authority", lambda *_a, **_k: base)
    for event in _interrupted_events():
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1/recovery",
                          headers=_headers(), cookies={"byq_session": "s"})
    decision = response.json()["containment"]["recovery"]
    assert decision["status"] == "blocked"
    assert decision["reason"] == reason
    assert calls["post"] == 0


def test_revoked_user_status_blocks_workspace_and_authorization(monkeypatch, tmp_path: Path) -> None:
    client, store, calls, _main = _client(
        monkeypatch, tmp_path,
        cookie_user={"username": "product-user", "status": "disabled",
                     "_workspace": {"workspace_id": "workspace_other"}})
    for event in _interrupted_events():
        store.append(event)
    decision = client.get("/v1/agent/sessions/conversation_1/recovery",
                          headers=_headers(), cookies={"byq_session": "s"}).json()["containment"]["recovery"]
    assert decision["status"] == "blocked"
    assert decision["reason"] == "owner_workspace_mismatch"
    assert calls["post"] == 0


def test_containment_endpoint_reports_interrupted_and_real_preservation(
    monkeypatch, tmp_path: Path,
) -> None:
    client, store, calls, _main = _client(monkeypatch, tmp_path)
    for event in _interrupted_events():
        store.append(event)
    body = client.get("/v1/agent/sessions/conversation_1/containment", headers=_headers()).json()
    containment = body["containment"]
    assert containment["status"] == "interrupted"
    assert containment["loss_cause"] == "executor-loss"
    assert containment["preservation"]["states"]["conversation"] == "preserved"
    assert containment["preservation"]["states"]["workflow_trace"] == "preserved"
    assert "runtime-1" not in json.dumps(containment)
    assert "dsh" not in json.dumps(containment).lower()


def test_get_product_session_includes_framework_neutral_containment(
    monkeypatch, tmp_path: Path,
) -> None:
    client, store, _calls, _main = _client(monkeypatch, tmp_path)
    for event in _interrupted_events():
        store.append(event)
    response = client.get("/v1/agent/sessions/conversation_1", headers=_headers())
    assert response.status_code == 200
    containment = response.json()["containment"]
    assert containment["status"] == "interrupted"
    assert "runtime-1" not in json.dumps(containment)
