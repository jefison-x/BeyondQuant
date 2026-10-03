from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest

from app.agent_research import AgentConflict, AgentResearchStore, AgentUnauthorized
from app.conversation_catalog import ConversationCatalogStore
from app.db import execute
from app.research import ResearchStore
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, registration_fingerprint
from packages.contracts.domain_call_admission import call_evidence_receipt, request_evidence
from tests.test_agent_run_lifecycle import apply, start
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="requires isolated PostgreSQL")


def _task(research, ctx, conversation, key):
    assert conversation["runtime_session_id"] == ctx["x-byq-session-id"]
    return research.create_task({
        "owner_principal": ctx["x-byq-owner-principal"],
        "title": "Synthetic authority task",
        "objective": "Bounded authority test",
        "trace_id": ctx["x-byq-trace-id"],
        "idempotency_key": key,
    }, trusted_context={
        "owner_principal": ctx["x-byq-owner-principal"],
        "workspace_id": ctx["x-byq-workspace-id"],
        "actor_principal": ctx["x-byq-actor-principal"],
        "trace_id": ctx["x-byq-trace-id"],
        "session_id": ctx["x-byq-session-id"],
    })


def _evidence(task_id, run_id, ctx, root, key, sequence):
    action = "byq_strategy_validate"
    payload = {"task_id": task_id, "agent_run_id": run_id,
               "idempotency_key": key, "strategy": {"code": "synthetic"}}
    return payload, {
        "schema_version": "domain-call-observed.v1", "sequence": sequence,
        "root_run_id": root, "generation": ctx["x-byq-dsh-run-id"],
        "call_id": f"synthetic-call-{sequence}",
        **request_evidence(action, payload, trace_id=ctx["x-byq-trace-id"]),
    }


def _proof_scope(ctx, conversation):
    return {
        "trusted_owner": ctx["x-byq-owner-principal"],
        "trusted_workspace": ctx["x-byq-workspace-id"],
        "trusted_session_id": ctx["x-byq-session-id"],
        "trusted_trace_id": ctx["x-byq-trace-id"],
        "trusted_boot_id": ctx["x-byq-runtime-boot-id"],
        "conversation_id": conversation["conversation_id"],
    }


def _claim_scope(ctx, root):
    return {
        "trusted_owner": ctx["x-byq-owner-principal"],
        "trusted_workspace": ctx["x-byq-workspace-id"],
        "trusted_session_id": ctx["x-byq-session-id"],
        "trusted_trace_id": ctx["x-byq-trace-id"],
        "trusted_generation": ctx["x-byq-dsh-run-id"],
        "trusted_root": root,
        "trusted_boot_id": ctx["x-byq-runtime-boot-id"],
    }


def test_rotation_serializes_new_claims_and_keeps_inflight_claim_unknown():
    old_boot, new_boot = "a" * 32, "b" * 32
    root = "c" * 32
    ctx = trusted_agent_context("authority-user", actor="byq-product-agent-session-authority",
        session_id="session-authority", trace_id="trace-authority", dsh_run_id="generation-authority")
    catalog, research, store = ConversationCatalogStore(), ResearchStore(), AgentResearchStore()
    try:
        store.rotate_runtime_authority(old_boot)
        conversation = catalog.create("authority-user", ctx["x-byq-session-id"], ctx["x-byq-trace-id"])
        task1 = _task(research, ctx, conversation, "authority-task-one")
        apply(store, ctx, root, key="authority-agent")
        run = start(store, ctx, "authority-agent")
        payload1, evidence1 = _evidence(task1["task_id"], run["run_id"], ctx, root, "external-one", 1)
        proof_scope = _proof_scope(ctx, conversation)
        proof_receipt = store.consume_domain_call_evidence(evidence1, **proof_scope)
        claim1 = store.claim_domain_call("byq_strategy_validate", payload1, **_claim_scope(ctx, root))
        assert claim1["state"] == "claimed"
        with store._transaction() as connection:
            execute(connection, "UPDATE agent_domain_call_claims SET status='executing' WHERE claim_id=:id",
                    {"id": claim1["claim_id"]})
        pending = start(store, ctx, "pending-before-rotation")
        assert pending["status"] == "pending_binding"

        task2 = _task(research, ctx, conversation, "authority-task-two")
        payload2, evidence2 = _evidence(task2["task_id"], run["run_id"], ctx, root, "racing-call", 2)
        store.consume_domain_call_evidence(evidence2, **proof_scope)
        barrier = Barrier(2)

        def race_claim():
            barrier.wait(timeout=5)
            return store.claim_domain_call("byq_strategy_validate", payload2, **_claim_scope(ctx, root))

        def race_rotate():
            barrier.wait(timeout=5)
            return store.rotate_runtime_authority(new_boot)

        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_future = executor.submit(race_claim)
            rotate_future = executor.submit(race_rotate)
            rotation = rotate_future.result(timeout=15)
            try:
                race_result = claim_future.result(timeout=15)
            except (AgentConflict, AgentUnauthorized):
                race_result = None

        assert rotation["revoked_root_count"] == 1
        assert rotation["revoked_agent_run_count"] == 2
        assert store.rotate_runtime_authority(new_boot) == rotation
        root_row = store._fetch_one("SELECT status,authority_status FROM agent_runtime_turns WHERE root_run_id=:id",
                                    {"id": root})
        run_row = store._fetch_one("SELECT status,authority_status FROM agent_runs WHERE run_id=:id",
                                   {"id": run["run_id"]})
        pending_row = store._fetch_one("SELECT status,authority_status FROM agent_runs WHERE run_id=:id",
                                       {"id": pending["run_id"]})
        assert root_row == {"status": "active", "authority_status": "authority_revoked_unconfirmed"}
        assert run_row == {"status": "active", "authority_status": "authority_revoked_unconfirmed"}
        assert pending_row == {"status": "pending_binding",
                               "authority_status": "authority_revoked_unconfirmed"}

        if race_result is None:
            assert store._fetch_one("SELECT claim_id FROM agent_domain_call_claims WHERE task_id=:task",
                                    {"task": task2["task_id"]}) is None
        else:
            assert race_result["state"] == "claimed"
            assert store._fetch_one("SELECT status FROM agent_domain_call_claims WHERE task_id=:task",
                                    {"task": task2["task_id"]})["status"] == "claimed"
        assert store.consume_domain_call_evidence(evidence1, **proof_scope) == proof_receipt
        assert store.claim_domain_call("byq_strategy_validate", payload1,
            **{**_claim_scope(ctx, root), "trusted_boot_id": old_boot}) == {"state": "unknown"}
        executed = []
        with pytest.raises(AgentConflict):
            store.execute_domain_call(claim1, lambda _connection: executed.append(True))
        assert executed == []
        assert store._fetch_one("SELECT status FROM agent_domain_call_claims WHERE claim_id=:id",
                                {"id": claim1["claim_id"]})["status"] == "executing"
        with pytest.raises((AgentConflict, AgentUnauthorized)):
            store.rotate_runtime_authority(old_boot)
        with pytest.raises((AgentConflict, AgentUnauthorized)):
            store.consume_runtime_lifecycle_event({
                "schema_version": "agent-run-lifecycle.v1", "root_run_id": "d" * 32,
                "sequence": 3, "outcome": "active",
                "registration_fingerprint": registration_fingerprint(
                    ctx["x-byq-owner-principal"], ctx["x-byq-workspace-id"],
                    ctx["x-byq-actor-principal"], ctx["x-byq-trace-id"],
                    ctx["x-byq-session-id"], ctx["x-byq-dsh-run-id"], "late-old-boot"),
            }, trusted_owner=ctx["x-byq-owner-principal"], trusted_workspace=ctx["x-byq-workspace-id"],
                trusted_session_id=ctx["x-byq-session-id"], trusted_trace_id=ctx["x-byq-trace-id"],
                trusted_boot_id=old_boot)
    finally:
        store.close()
        research.close()
        catalog.close()


def test_terminal_close_persists_exact_adapter_digest_and_is_idempotent_after_rotation():
    first_boot, second_boot = "e" * 32, "f" * 32
    root = "1" * 32
    digest = "2" * 64
    ctx = trusted_agent_context("authority-close-user", actor="byq-product-agent-close",
        session_id="session-close", trace_id="trace-close", dsh_run_id="generation-close")
    store = AgentResearchStore()
    try:
        store.rotate_runtime_authority(first_boot)
        apply(store, ctx, root, key="close-agent")
        run = start(store, ctx, "close-agent")
        receipt = store.close_runtime_root(root, boot_id=first_boot, sequence=7,
                                           outcome="failed", event_sha256=digest)
        assert receipt == {"schema_version": "agent-run-lifecycle-receipt.v1", "sequence": 7,
                          "root_run_id": root, "event_sha256": digest}
        assert store.close_runtime_root(root, boot_id=first_boot, sequence=7,
                                        outcome="failed", event_sha256=digest) == receipt
        with pytest.raises(AgentConflict):
            store.close_runtime_root(root, boot_id=first_boot, sequence=7,
                                     outcome="failed", event_sha256="3" * 64)
        store.rotate_runtime_authority(second_boot)
        assert store.close_runtime_root(root, boot_id=first_boot, sequence=7,
                                        outcome="failed", event_sha256=digest) == receipt
        root_row = store._fetch_one("""SELECT status,authority_status,terminal_sequence,terminal_event_sha256
            FROM agent_runtime_turns WHERE root_run_id=:id""", {"id": root})
        run_row = store._fetch_one("SELECT status,authority_status FROM agent_runs WHERE run_id=:id",
                                   {"id": run["run_id"]})
        assert root_row == {"status": "failed", "authority_status": "closed",
                            "terminal_sequence": 7, "terminal_event_sha256": digest}
        assert run_row == {"status": "failed", "authority_status": "closed"}
    finally:
        store.close()


def test_same_root_transfer_is_exact_idempotent_and_preserves_unknown_call_receipts():
    old_boot, new_boot = "8" * 32, "9" * 32
    root = "a" * 32
    ctx = trusted_agent_context("authority-transfer-user", actor="byq-product-agent-session-transfer",
        session_id="session-transfer", trace_id="trace-transfer", dsh_run_id="generation-transfer")
    catalog, research, store = ConversationCatalogStore(), ResearchStore(), AgentResearchStore()
    try:
        old_authority = store.rotate_runtime_authority(old_boot)
        ctx["x-byq-runtime-boot-id"] = old_boot
        conversation = catalog.create("authority-transfer-user", "session-transfer", "trace-transfer")
        task = _task(research, ctx, conversation, "transfer-task")
        apply(store, ctx, root, key="transfer-agent")
        run = start(store, ctx, "transfer-agent")
        payload, evidence = _evidence(task["task_id"], run["run_id"], ctx, root,
                                     "transfer-call", 1)
        proof_scope = _proof_scope(ctx, conversation)
        evidence_receipt = store.consume_domain_call_evidence(evidence, **proof_scope)
        claim_scope = _claim_scope(ctx, root)
        claim = store.claim_domain_call("byq_strategy_validate", payload, **claim_scope)
        assert claim["state"] == "claimed"
        store._execute("UPDATE agent_domain_call_claims SET status='executing' WHERE claim_id=:id",
                       {"id": claim["claim_id"]})

        evidence_before = store._fetch_one("""SELECT evidence_json,receipt_json FROM agent_domain_call_evidence
            WHERE root_run_id=:root""", {"root": root})
        claim_before = store._fetch_one("""SELECT status,result_json,evidence_sequence,agent_run_id
            FROM agent_domain_call_claims WHERE root_run_id=:root""", {"root": root})
        new_authority = store.rotate_runtime_authority(new_boot)
        assert old_authority["authority_epoch"] + 1 == new_authority["authority_epoch"]

        kwargs = {
            "previous_boot_id": old_boot,
            "previous_authority_epoch": old_authority["authority_epoch"],
            "boot_id": new_boot,
            "authority_epoch": new_authority["authority_epoch"],
            "owner_principal": ctx["x-byq-owner-principal"],
            "workspace_id": ctx["x-byq-workspace-id"],
            "session_id": ctx["x-byq-session-id"],
            "trace_id": ctx["x-byq-trace-id"],
        }
        receipt = store.transfer_runtime_root_authority(root, **kwargs)
        assert receipt == {
            "schema_version": "byq-runtime-root-authority-transfer-receipt.v1",
            "root_run_id": root,
            "previous_boot_id": old_boot,
            "previous_authority_epoch": old_authority["authority_epoch"],
            "boot_id": new_boot,
            "authority_epoch": new_authority["authority_epoch"],
            "status": "transferred",
        }
        assert store.transfer_runtime_root_authority(root, **kwargs) == receipt
        assert store._fetch_one("""SELECT status,authority_status,authority_boot_id,
                previous_authority_boot_id,previous_authority_epoch
            FROM agent_runtime_turns WHERE root_run_id=:root""", {"root": root}) == {
                "status": "active", "authority_status": "active", "authority_boot_id": new_boot,
                "previous_authority_boot_id": old_boot,
                "previous_authority_epoch": old_authority["authority_epoch"],
            }
        assert store._fetch_one("SELECT status,authority_status,authority_boot_id FROM agent_runs WHERE run_id=:id",
                                {"id": run["run_id"]}) == {
                                    "status": "active", "authority_status": "active", "authority_boot_id": new_boot,
                                }
        assert store._fetch_one("""SELECT evidence_json,receipt_json FROM agent_domain_call_evidence
            WHERE root_run_id=:root""", {"root": root}) == evidence_before
        assert store._fetch_one("""SELECT status,result_json,evidence_sequence,agent_run_id
            FROM agent_domain_call_claims WHERE root_run_id=:root""", {"root": root}) == claim_before
        assert evidence_receipt == store.consume_domain_call_evidence(evidence, **proof_scope)

        # The exact retry remains an unknown call, not a second execution.
        resumed_scope = {**claim_scope, "trusted_boot_id": new_boot}
        assert store.claim_domain_call("byq_strategy_validate", payload, **resumed_scope) == {"state": "unknown"}
        executed = []
        with pytest.raises((AgentConflict, AgentUnauthorized)):
            store.execute_domain_call(claim, lambda _connection: executed.append(True))
        assert executed == []

        # A changed prior epoch cannot reuse the root's committed transfer proof.
        with pytest.raises(AgentConflict, match="previous runtime boot receipt"):
            store.transfer_runtime_root_authority(root,
                **{**kwargs, "previous_authority_epoch": old_authority["authority_epoch"] + 1})
    finally:
        store.close()
        research.close()
        catalog.close()


def test_same_root_transfer_fails_closed_for_unbound_registration_and_wrong_scope():
    old_boot, new_boot = "c" * 32, "d" * 32
    root = "e" * 32
    ctx = trusted_agent_context("authority-transfer-pending-user", actor="byq-product-agent-transfer-pending",
        session_id="session-transfer-pending", trace_id="trace-transfer-pending",
        dsh_run_id="generation-transfer-pending")
    store = AgentResearchStore()
    try:
        old_authority = store.rotate_runtime_authority(old_boot)
        ctx["x-byq-runtime-boot-id"] = old_boot
        apply(store, ctx, root, key="bound-agent")
        start(store, ctx, "bound-agent")
        start(store, ctx, "unbound-agent")
        new_authority = store.rotate_runtime_authority(new_boot)
        kwargs = {
            "previous_boot_id": old_boot,
            "previous_authority_epoch": old_authority["authority_epoch"],
            "boot_id": new_boot,
            "authority_epoch": new_authority["authority_epoch"],
            "owner_principal": ctx["x-byq-owner-principal"],
            "workspace_id": ctx["x-byq-workspace-id"],
            "session_id": ctx["x-byq-session-id"],
            "trace_id": ctx["x-byq-trace-id"],
        }
        with pytest.raises(AgentConflict, match="unbound AgentRun registration"):
            store.transfer_runtime_root_authority(root, **kwargs)
        with pytest.raises(AgentUnauthorized, match="transfer scope"):
            store.transfer_runtime_root_authority(root, **{**kwargs, "trace_id": "other-trace"})
        assert store._fetch_one("SELECT authority_status FROM agent_runtime_turns WHERE root_run_id=:root",
                                {"root": root})["authority_status"] == "authority_revoked_unconfirmed"
    finally:
        store.close()


def test_plain_agent_turn_without_domain_registration_closes_exact_root():
    boot = uuid4().hex
    root = uuid4().hex
    ctx = trusted_agent_context("authority-plain-turn-user", actor="byq-product-agent-plain",
        session_id="session-plain", trace_id="trace-plain", dsh_run_id="generation-plain")
    store = AgentResearchStore()
    try:
        store.rotate_runtime_authority(boot)
        event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root,
                 "sequence": 1, "outcome": "active"}
        receipt = store.consume_runtime_lifecycle_event(event,
            trusted_owner=ctx["x-byq-owner-principal"],
            trusted_workspace=ctx["x-byq-workspace-id"],
            trusted_session_id=ctx["x-byq-session-id"],
            trusted_trace_id=ctx["x-byq-trace-id"], trusted_boot_id=boot)
        assert receipt == lifecycle_receipt(event)
        assert store._fetch_one("SELECT status,authority_status,terminal_sequence FROM agent_runtime_turns "
                                "WHERE root_run_id=:id", {"id": root}) == {
            "status": "active", "authority_status": "active", "terminal_sequence": None,
        }
        assert store.close_runtime_root(root, boot_id=boot, sequence=2,
            outcome="completed", event_sha256="5" * 64)["root_run_id"] == root
    finally:
        store.close()


def test_product_agent_mutation_holds_boot_gate_through_rotation_and_human_decision_stays_available(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    old_boot, new_boot = uuid4().hex, uuid4().hex
    main.agent_store.rotate_runtime_authority(old_boot)
    monkeypatch.setattr(main.workspace_tenancy_store, "resolve_context",
                        lambda owner, workspace: {"owner_principal": owner, "workspace_id": workspace})

    entered_mutation = Event()
    finish_mutation = Event()
    mutations = []

    def blocked_create_task(payload, *, trusted_context):
        entered_mutation.set()
        if not finish_mutation.wait(timeout=10):
            raise TimeoutError("test mutation was not released")
        mutations.append((payload, trusted_context))
        return {"task_id": "researchtask_synthetic"}

    monkeypatch.setattr(main.research_store, "create_task", blocked_create_task)
    actor_headers = {
        "x-byq-workspace-id": "workspace-authority-race",
        "x-byq-owner-principal": "authority-race-user",
        "x-byq-actor-principal": "byq-product-agent-authority-race",
        "x-byq-trace-id": "trace-authority-race",
        "x-byq-session-id": "session-authority-race",
        "x-byq-dsh-run-id": "generation-authority-race",
        "x-byq-runtime-boot-id": old_boot,
    }
    task_payload = {
        "owner_principal": actor_headers["x-byq-owner-principal"],
        "title": "Gate race test", "objective": "Synthetic bounded operation",
        "trace_id": actor_headers["x-byq-trace-id"], "idempotency_key": "authority-race-task",
    }

    client = TestClient(main.app)
    with ThreadPoolExecutor(max_workers=3) as executor:
        request_future = executor.submit(
            client.post, "/v1/research/tasks", json=task_payload, headers=actor_headers,
        )
        assert entered_mutation.wait(timeout=5)
        rotation_started = Event()

        def rotate():
            rotation_started.set()
            return main.agent_store.rotate_runtime_authority(new_boot)

        rotation_future = executor.submit(rotate)
        assert rotation_started.wait(timeout=5)
        time.sleep(0.1)
        assert not rotation_future.done(), "rotation passed an in-flight Product Agent mutation"
        finish_mutation.set()
        response = request_future.result(timeout=10)
        receipt = rotation_future.result(timeout=15)

    assert response.status_code == 201
    assert len(mutations) == 1
    assert receipt["boot_id"] == new_boot
    assert main.agent_store.current_runtime_authority()["boot_id"] == new_boot

    # A stale boot cannot reach the same mutating route after rotation.
    stale_response = client.post("/v1/research/tasks", json=task_payload, headers=actor_headers)
    assert stale_response.status_code == 401
    assert len(mutations) == 1
    current_headers = {**actor_headers, "x-byq-runtime-boot-id": new_boot}
    for invalid_headers in (
        {key: value for key, value in current_headers.items() if key != "x-byq-runtime-boot-id"},
        {**current_headers, "x-byq-runtime-boot-id": "A" * 32},
    ):
        assert client.post("/v1/research/tasks", json=task_payload, headers=invalid_headers).status_code == 401
    duplicate_headers = list(current_headers.items()) + [
        ("x-byq-runtime-boot-id", new_boot),
    ]
    assert client.post("/v1/research/tasks", json=task_payload, headers=duplicate_headers).status_code == 401
    duplicate_actor_headers = list(current_headers.items()) + [
        ("x-byq-actor-principal", "authority-human-reviewer"),
    ]
    assert client.post("/v1/research/tasks", json=task_payload,
                       headers=duplicate_actor_headers).status_code == 401
    assert len(mutations) == 1

    # A human Gateway approval decision remains usable without a runtime boot.
    decision_actor = []
    monkeypatch.setattr(main.agent_store, "decide_approval", lambda _payload, **kwargs: (
        decision_actor.append(kwargs["trusted_actor"]) or {"business_action": None, "status": "approved"}
    ))
    human_headers = {
        **{key: value for key, value in actor_headers.items()
           if key not in {"x-byq-actor-principal", "x-byq-runtime-boot-id"}},
        "x-byq-actor-principal": "authority-human-reviewer",
    }
    human_response = client.post(
        "/v1/agents/approvals/agent_approval_0123456789abcdef0123456789abcdef/decision",
        json={"decision": "approved", "rationale": "Human-reviewed synthetic decision"},
        headers=human_headers,
    )
    assert human_response.status_code == 200
    assert decision_actor == ["authority-human-reviewer"]

    # JSON cannot assert the Product Agent identity in place of its trusted header.
    from fastapi import HTTPException
    from starlette.requests import Request

    for json_actor in ("byq-product-agent-json-spoof", "authority-human-json-spoof"):
        with pytest.raises(HTTPException) as rejected:
            main._agent_context(Request({"type": "http", "headers": []}),
                                {"actor_principal": json_actor})
        assert rejected.value.status_code == 401
