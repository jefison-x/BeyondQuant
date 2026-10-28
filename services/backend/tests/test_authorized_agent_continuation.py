"""The default continuation consumer accepts only exact completed Job origins."""

from __future__ import annotations

import json
import math
import os
from uuid import uuid4

import pytest

from app import main
from app.backtest_task import task_id_from_signal_job
from app.conversation_catalog import ConversationCatalogStore
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event
from packages.contracts.continuation_request import RESERVATION_SCHEMA_VERSION_V3
from tests import test_data_ready_continuation as data_ready
from tests.test_acp_backtest_task_submission import (
    _close_setup,
    _post_create,
    _setup_acp_task,
)
from tests.test_acp_domain_call_proof import _abort_tool, _bind, _observe_tool, _settle_tool
from tests.test_data_ready_continuation import (
    _v3_runtime_root,
    _v3_settlement_sha256,
    _v3_usage,
    continuation_budget,
    setup_ready,
    trusted_v3_tool_context,
)


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def _trusted_context(headers: dict[str, str]) -> dict[str, str]:
    return {key.removeprefix("x-byq-").replace("-", "_"): value for key, value in headers.items()}


def _close_source_root(fixture: dict[str, object], outcome: str):
    context = fixture["context"]
    session_id = context["x-byq-session-id"]
    trace_id = context["x-byq-trace-id"]
    kind = {
        "completed": "session.result",
        "failed": "session.failed",
        "cancelled": "session.cancelled",
        "interrupted": "session.closed",
    }[outcome]
    observed = {
        "session_id": session_id,
        "trace_id": trace_id,
        "source": "runtime-adapter",
        "kind": kind,
        "sequence": 2,
        "payload": {"run_id": fixture["root_id"]},
    }
    terminal = project_lifecycle_event(observed, session_id, trace_id)
    assert terminal is not None
    receipt = lifecycle_receipt(terminal)
    response = fixture["client"].post(
        f"/internal/runtime-authority/roots/{fixture['root_id']}/close",
        headers={"Authorization": "Bearer test-runtime-authority"},
        json={
            "schema_version": "byq-runtime-root-close.v1",
            "boot_id": context["x-byq-runtime-boot-id"],
            "sequence": terminal["sequence"],
            "outcome": terminal["outcome"],
            "event_sha256": receipt["event_sha256"],
        },
    )
    return response, receipt


def _assert_root_projection(fixture: dict[str, object], status: str):
    context = fixture["context"]
    response = fixture["client"].get(
        f"/internal/runtime-authority/sessions/{context['x-byq-session-id']}/roots",
        headers={
            "Authorization": "Bearer test-runtime-authority",
            "x-byq-owner-principal": context["x-byq-owner-principal"],
            "x-byq-workspace-id": context["x-byq-workspace-id"],
            "x-byq-trace-id": context["x-byq-trace-id"],
        },
    )
    assert response.status_code == 200, response.text
    projection = response.json()
    assert projection["schema_version"] == "byq-business-root-status.v1"
    root = next(row for row in projection["roots"] if row["root_run_id"] == fixture["root_id"])
    assert root["status"] == status
    assert root["authority_status"] == ("active" if status == "active" else "closed")
    return root


def _backtest_child(fixture: dict[str, object]) -> dict[str, object]:
    """Create the exact authorized child role through the native start/bind flow."""
    store, context, root_identity = fixture["agent_store"], fixture["context"], fixture["identity"]
    parent = store._fetch_one(
        """SELECT agent_run_id FROM agent_acp_native_agent_registrations
           WHERE root_run_id=:root AND native_agent_session_id=:native AND status='bound'""",
        {"root": fixture["root_id"], "native": root_identity["native_root_session_id"]},
    )
    assert parent is not None
    identity = {
        "root_run_id": fixture["root_id"],
        "runtime_boot_id": context["x-byq-runtime-boot-id"],
        "native_root_session_id": root_identity["native_root_session_id"],
        "native_agent_session_id": str(uuid4()),
        "native_parent_session_id": root_identity["native_root_session_id"],
        "origin": "subagent",
        "depth": 1,
    }
    run = store.start_run(
        {
            "role_id": "backtest_analyst",
            "trace_id": context["x-byq-trace-id"],
            "session_id": context["x-byq-session-id"],
            "dsh_run_id": context["x-byq-dsh-run-id"],
            "idempotency_key": f"continuation-child-{uuid4().hex}",
            "parent_run_id": parent["agent_run_id"],
        },
        trusted_owner=context["x-byq-owner-principal"],
        trusted_actor=context["x-byq-actor-principal"],
        trusted_workspace=context["x-byq-workspace-id"],
        trusted_boot_id=context["x-byq-runtime-boot-id"],
        trusted_root_run_id=fixture["root_id"],
        trusted_acp_registration=identity,
        require_runtime_binding=True,
    )
    return {**identity, "agent_run_id": run["run_id"], "parent_run_id": parent["agent_run_id"]}


def _create_agent_job(monkeypatch, tmp_path, label: str, *, origin: str = "root",
                      ingress_outcome: str = "settled", close_outcome: str | None = "completed",
                      negative_zero_case: bool = False):
    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "test-runtime-authority")
    fixture = _setup_acp_task(monkeypatch, tmp_path, label)
    if origin == "child" or negative_zero_case:
        aborted = _abort_tool(
            fixture["agent_store"], fixture["context"], fixture["identity"],
            "byq_backtest_task_create", fixture["arguments"],
            request_id=fixture["ingress"]["mcp_request_id"],
        )
        assert aborted["outcome"] == "aborted_before_dispatch"

    if origin == "child":
        identity = _backtest_child(fixture)
        _bind(fixture["agent_store"], fixture["context"], identity)
        ingress = _observe_tool(
            fixture["agent_store"], fixture["context"], identity,
            "byq_backtest_task_create", fixture["arguments"],
        )
        headers = {
            **fixture["headers"],
            "x-byq-acp-observation-id": ingress["mcp_request_id"],
            "x-byq-acp-native-root-session-id": identity["native_root_session_id"],
            "x-byq-acp-native-agent-session-id": identity["native_agent_session_id"],
            "x-byq-acp-native-parent-session-id": identity["native_parent_session_id"],
            "x-byq-acp-origin": identity["origin"],
            "x-byq-acp-depth": str(identity["depth"]),
        }
        fixture["identity"] = identity
        created = _post_create(fixture, headers=headers)
    else:
        identity = fixture["identity"]
        headers = dict(fixture["headers"])
        if negative_zero_case:
            arguments = {**fixture["arguments"], "parameters": {"zero": -0.0}}
            ingress = _observe_tool(
                fixture["agent_store"], fixture["context"], identity,
                "byq_backtest_task_create", arguments,
            )
            headers["x-byq-acp-observation-id"] = ingress["mcp_request_id"]
            fixture["arguments"] = arguments
            fixture["ingress"] = ingress
            fixture["headers"] = headers
        else:
            ingress = fixture["ingress"]
        created = _post_create(fixture, headers=headers)
    assert created.status_code == 202, created.text
    _settle_tool(fixture["agent_store"], fixture["context"], identity, ingress, ingress_outcome)

    task_id = fixture["task"]["task_id"]
    job = fixture["jobs"]._fetch_one(
        """SELECT * FROM signal_producer_jobs
           WHERE task_id=:task AND owner_principal=:owner AND idempotency_key=:key""",
        {
            "task": task_id,
            "owner": fixture["context"]["x-byq-owner-principal"],
            "key": fixture["arguments"]["idempotency_key"],
        },
    )
    assert job is not None and job["submission_origin"]["kind"] == "authorized_agent"
    if negative_zero_case:
        assert job["submission_origin"]["mcp_request_id"] == ingress["mcp_request_id"]
        stored_zero = job["preparation_json"]["parameters"]["zero"]
        assert stored_zero == 0.0 and math.copysign(1.0, stored_zero) == 1.0
    artifact = fixture["research"].create_artifact({
        "task_id": task_id,
        "kind": "signal_snapshot",
        "content": {"synthetic": f"authorized-agent-continuation-{label}"},
        "lineage": [],
        "trace_id": fixture["context"]["x-byq-trace-id"],
        "idempotency_key": f"authorized-agent-continuation-{label}",
    })
    fixture["research"].transition(
        "artifact", artifact["artifact_id"], "validated", f"validate-{label}")
    fixture["jobs"]._execute(
        """UPDATE signal_producer_jobs SET status='completed', result_artifact_id=:artifact,
             finished_at=now(), updated_at=now() WHERE job_id=:job""",
        {"artifact": artifact["artifact_id"], "job": job["job_id"]},
    )
    fixture.update({
        "job_id": job["job_id"],
        "artifact_id": artifact["artifact_id"],
        "source_ingress": ingress,
        "source_identity": identity,
        "trusted_context": _trusted_context(fixture["context"]),
    })
    if close_outcome is not None:
        response, receipt = _close_source_root(fixture, close_outcome)
        assert response.status_code == 200, response.text
        assert response.json() == {"receipt": receipt}
        _assert_root_projection(fixture, close_outcome)
    return fixture


def _close_fixture(fixture: dict[str, object]) -> None:
    if "store" in fixture:
        fixture["store"].close()
        fixture["backtests"].close()
        fixture["jobs"].close()
    else:
        _close_setup(fixture)


def _prepare_authorize_dispatch(store, *, conversation_id: str, task_id: str,
                                job_id: str, artifact_id: str, trusted_context: dict[str, str]):
    raw_ledger = continuation_budget(store, task_id)
    assert raw_ledger is None
    eligible = store.peek_default_continuation_v3(
        conversation_id, trusted_context=trusted_context)
    assert eligible == {
        "status": "eligible",
        "reservation_schema_version": RESERVATION_SCHEMA_VERSION_V3,
        "signal_job_id": job_id,
        "task_id": task_id,
        "conversation_id": conversation_id,
        "session_id": trusted_context["session_id"],
        "trace_id": trusted_context["trace_id"],
    }
    assert "receipt" not in eligible and "reservation" not in eligible
    assert continuation_budget(store, task_id) == raw_ledger

    claimed = store.claim_default_continuation_v3(
        conversation_id, signal_job_id=job_id, trusted_context=trusted_context)
    assert claimed["status"] == "intent"
    assert claimed["may_dispatch"] is True
    carrier = claimed["reservation"]
    assert (carrier["signal_job_id"], carrier["task_id"], carrier["conversation_id"],
            carrier["result_artifact_id"], carrier["result_artifact_kind"],
            carrier["result_artifact_status"]) == (
                job_id, task_id, conversation_id, artifact_id, "signal_snapshot", "validated")
    reservation_id = claimed["receipt"]["reservation_id"]
    assert claimed["receipt"]["reservation"] == carrier

    reserved_ledger = continuation_budget(store, task_id)
    assert [(row["status"], row["dispatch_attempts"], row["reservation_id"])
            for row in reserved_ledger] == [("reserved", 0, reservation_id)]
    replay = store.peek_default_continuation_v3(
        conversation_id, trusted_context=trusted_context)
    assert replay["status"] == "intent"
    assert (replay["receipt"]["reservation_id"], replay["reservation"]) == (reservation_id, carrier)
    assert continuation_budget(store, task_id) == reserved_ledger

    dispatch = store.claim_continuation_dispatch(
        task_id, reservation_id, trusted_context=trusted_context)
    assert dispatch == {"dispatch": True, "attempt": 1}
    unknown_ledger = continuation_budget(store, task_id)
    assert [(row["status"], row["dispatch_attempts"], row["reservation_id"])
            for row in unknown_ledger] == [("outcome_unknown", 1, reservation_id)]
    return claimed, carrier, unknown_ledger


def _open_authorize_runtime_root(fixture: dict[str, object], trusted_context: dict[str, str],
                                 source_kind: str) -> dict[str, object]:
    if source_kind == "human_v1":
        root_id, runtime_store, boot_id = _v3_runtime_root(fixture, close=False)
        sequence = 1
    else:
        runtime_store = fixture["agent_store"]
        authority = runtime_store.current_runtime_authority()
        assert authority is not None
        source_boot_id = fixture["context"]["x-byq-runtime-boot-id"]
        assert (authority["boot_id"] != source_boot_id
                if source_kind == "agent_child_v2_closed_old_boot"
                else authority["boot_id"] == source_boot_id)
        root_id = uuid4().hex
        sequence = 3
        runtime_event = {
            "schema_version": "agent-run-lifecycle.v1",
            "root_run_id": root_id,
            "sequence": sequence,
            "outcome": "active",
        }
        receipt = runtime_store.consume_runtime_lifecycle_event(
            runtime_event,
            trusted_owner=trusted_context["owner_principal"],
            trusted_workspace=trusted_context["workspace_id"],
            trusted_session_id=trusted_context["session_id"],
            trusted_trace_id=trusted_context["trace_id"],
            trusted_boot_id=authority["boot_id"],
        )
        assert receipt == lifecycle_receipt(runtime_event)
        boot_id = authority["boot_id"]
    return {"root_run_id": root_id, "store": runtime_store,
            "boot_id": boot_id, "close_sequence": sequence + 1}


def _close_authorize_runtime_root(root: dict[str, object]) -> None:
    closed = root["store"].close_runtime_root(
        root["root_run_id"], boot_id=root["boot_id"],
        sequence=root["close_sequence"], outcome="completed", event_sha256="d" * 64)
    assert closed == {
        "schema_version": "agent-run-lifecycle-receipt.v1",
        "sequence": root["close_sequence"],
        "root_run_id": root["root_run_id"],
        "event_sha256": "d" * 64,
    }


def _post_authorize_tool(fixture: dict[str, object], *, trusted_context: dict[str, str],
                         runtime_root: dict[str, object], reservation_id: str,
                         tool: str, arguments: dict[str, object]):
    headers = {f"x-byq-{field.replace('_', '-')}": trusted_context[field]
               for field in ("owner_principal", "actor_principal", "workspace_id",
                             "trace_id", "session_id", "dsh_run_id")}
    headers.update({
        "x-byq-runtime-boot-id": runtime_root["boot_id"],
        "x-byq-root-run-id": runtime_root["root_run_id"],
    })
    return fixture["client"].post(
        f"/internal/task-continuation/{reservation_id}/authorize-tool",
        headers=headers,
        json={"tool": tool, "arguments": arguments,
              "root_run_id": runtime_root["root_run_id"]},
    )


@pytest.mark.parametrize("source_kind", ["human_v1", "agent_root_v2", "agent_child_v2_closed_old_boot"])
def test_v3_source_origin_reserves_exact_human_and_agent_jobs(monkeypatch, tmp_path, source_kind):
    if source_kind == "human_v1":
        fixture = setup_ready(monkeypatch, tmp_path)
        store = fixture["store"]
        trusted_context = fixture["context"]
        conversation_id = fixture["conversation"]
        task_id = fixture["payload"]["task_id"]
        job_id = fixture["job_id"]
        catalog = ConversationCatalogStore()
        try:
            raw_ledger_baseline = continuation_budget(store, task_id)
            assert raw_ledger_baseline is None
            catalog.update_execution_options(
                trusted_context["owner_principal"], trusted_context["workspace_id"],
                conversation_id, {
                    "schema_version": "agent-execution-options.v1",
                    "expected_revision": 0,
                    "options": {"auto_continue": False},
                })
            assert store.peek_default_continuation_v3(
                conversation_id, trusted_context=trusted_context) == {"status": "waiting"}
            assert continuation_budget(store, task_id) == raw_ledger_baseline
            catalog.update_execution_options(
                trusted_context["owner_principal"], trusted_context["workspace_id"],
                conversation_id, {
                    "schema_version": "agent-execution-options.v1",
                    "expected_revision": 1,
                    "options": {"auto_continue": True},
                })
        finally:
            catalog.close()
    else:
        fixture = _create_agent_job(monkeypatch, tmp_path, source_kind,
            origin="child" if source_kind == "agent_child_v2_closed_old_boot" else "root",
            negative_zero_case=source_kind == "agent_root_v2")
        store = fixture["research"]
        trusted_context = fixture["trusted_context"]
        conversation_id = fixture["conversation"]["conversation_id"]
        task_id = fixture["task"]["task_id"]
        job_id = fixture["job_id"]
        if source_kind == "agent_child_v2_closed_old_boot":
            rotated = fixture["client"].post(
                "/internal/runtime-authority/boot",
                headers={"Authorization": "Bearer test-runtime-authority"},
                json={"schema_version": "byq-runtime-authority-boot.v1", "boot_id": uuid4().hex},
            )
            assert rotated.status_code == 200, rotated.text
        if source_kind != "human_v1":
            raw_ledger_baseline = continuation_budget(store, task_id)
            assert raw_ledger_baseline is None

    try:
        first = store.peek_default_continuation_v3(
            conversation_id, trusted_context=trusted_context)
        assert first == {
            "status": "eligible",
            "reservation_schema_version": RESERVATION_SCHEMA_VERSION_V3,
            "signal_job_id": job_id,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "session_id": trusted_context["session_id"],
            "trace_id": trusted_context["trace_id"],
        }
        assert "receipt" not in first and "reservation" not in first
        assert continuation_budget(store, task_id) == raw_ledger_baseline

        claimed = store.claim_default_continuation_v3(
            conversation_id, signal_job_id=job_id, trusted_context=trusted_context)
        assert claimed["status"] == "intent"
        assert claimed["reservation_schema_version"] == RESERVATION_SCHEMA_VERSION_V3
        assert claimed["task_id"] == task_id
        assert claimed["conversation_id"] == conversation_id
        assert claimed["session_id"] == first["session_id"]
        assert claimed["trace_id"] == first["trace_id"]
        assert claimed["may_dispatch"] is True
        carrier = claimed["reservation"]
        assert carrier["signal_job_id"] == job_id
        assert carrier["signal_job_status"] == "completed"
        assert carrier["task_id"] == task_id
        assert carrier["conversation_id"] == conversation_id
        assert carrier["owner_principal"] == trusted_context["owner_principal"]
        assert carrier["workspace_id"] == trusted_context["workspace_id"]
        assert carrier["result_artifact_id"] == fixture["artifact_id"]
        assert carrier["result_artifact_kind"] == "signal_snapshot"
        assert carrier["result_artifact_status"] == "validated"
        assert claimed["receipt"]["reservation"] == carrier
        claimed_ledger = continuation_budget(store, task_id)
        assert len(claimed_ledger) == 1
        assert claimed_ledger[0]["status"] == "reserved"
        assert claimed_ledger[0]["dispatch_attempts"] == 0
        assert claimed_ledger[0]["reservation_id"] == claimed["receipt"]["reservation_id"]

        replay = store.peek_default_continuation_v3(
            conversation_id, trusted_context=trusted_context)
        assert replay["status"] == "intent"
        assert replay["receipt"]["reservation_id"] == claimed["receipt"]["reservation_id"]
        assert replay["reservation"] == carrier
        assert continuation_budget(store, task_id) == claimed_ledger

        dispatch = store.claim_continuation_dispatch(
            task_id, claimed["receipt"]["reservation_id"], trusted_context=trusted_context)
        assert dispatch == {"dispatch": True, "attempt": 1}
        dispatched_ledger = continuation_budget(store, task_id)
        assert len(dispatched_ledger) == 1
        assert dispatched_ledger[0]["status"] == "outcome_unknown"
        assert dispatched_ledger[0]["dispatch_attempts"] == 1
        assert dispatched_ledger[0]["reservation_id"] == claimed["receipt"]["reservation_id"]
        if source_kind == "agent_root_v2":
            runtime_store = fixture["agent_store"]
            runtime_context = fixture["context"]
            authority = runtime_store.current_runtime_authority()
            assert authority is not None
            assert authority["boot_id"] == runtime_context["x-byq-runtime-boot-id"]
            run_id = uuid4().hex
            assert run_id != fixture["root_id"]
            runtime_event = {
                "schema_version": "agent-run-lifecycle.v1",
                "root_run_id": run_id,
                "sequence": 3,
                "outcome": "active",
            }
            runtime_receipt = runtime_store.consume_runtime_lifecycle_event(
                runtime_event,
                trusted_owner=runtime_context["x-byq-owner-principal"],
                trusted_workspace=runtime_context["x-byq-workspace-id"],
                trusted_session_id=runtime_context["x-byq-session-id"],
                trusted_trace_id=runtime_context["x-byq-trace-id"],
                trusted_boot_id=authority["boot_id"],
            )
            assert runtime_receipt == lifecycle_receipt(runtime_event)
            receipt_scope = {
                "owner": runtime_context["x-byq-owner-principal"],
                "workspace": runtime_context["x-byq-workspace-id"],
                "session": runtime_context["x-byq-session-id"],
                "trace": runtime_context["x-byq-trace-id"],
            }
            source_receipt = runtime_store._fetch_one(
                """SELECT trace_id, receipt_json FROM agent_runtime_receipts
                   WHERE owner_principal=:owner AND workspace_id=:workspace
                     AND session_id=:session AND trace_id=:trace AND sequence=1""",
                receipt_scope,
            )
            new_receipt = runtime_store._fetch_one(
                """SELECT trace_id, receipt_json FROM agent_runtime_receipts
                   WHERE owner_principal=:owner AND workspace_id=:workspace
                     AND session_id=:session AND trace_id=:trace AND sequence=3""",
                receipt_scope,
            )
            assert source_receipt is not None
            assert source_receipt["trace_id"] == runtime_context["x-byq-trace-id"]
            assert source_receipt["receipt_json"]["root_run_id"] == fixture["root_id"]
            assert new_receipt is not None
            assert new_receipt["trace_id"] == runtime_context["x-byq-trace-id"]
            assert new_receipt["receipt_json"] == runtime_receipt
            assert runtime_store._fetch_one(
                """SELECT owner_principal, workspace_id, session_id, trace_id, authority_boot_id,
                          status, authority_status, terminal_sequence
                   FROM agent_runtime_turns WHERE root_run_id=:root""",
                {"root": fixture["root_id"]},
            ) == {
                "owner_principal": runtime_context["x-byq-owner-principal"],
                "workspace_id": runtime_context["x-byq-workspace-id"],
                "session_id": runtime_context["x-byq-session-id"],
                "trace_id": runtime_context["x-byq-trace-id"],
                "authority_boot_id": authority["boot_id"],
                "status": "completed", "authority_status": "closed", "terminal_sequence": 2,
            }
            assert runtime_store._fetch_one(
                """SELECT owner_principal, workspace_id, session_id, trace_id, authority_boot_id,
                          status, authority_status, terminal_sequence
                   FROM agent_runtime_turns WHERE root_run_id=:root""",
                {"root": run_id},
            ) == {
                "owner_principal": runtime_context["x-byq-owner-principal"],
                "workspace_id": runtime_context["x-byq-workspace-id"],
                "session_id": runtime_context["x-byq-session-id"],
                "trace_id": runtime_context["x-byq-trace-id"],
                "authority_boot_id": authority["boot_id"],
                "status": "active", "authority_status": "active", "terminal_sequence": None,
            }
            accepted = store.record_continuation_receipt(
                task_id, trusted_context=trusted_context,
                reservation_id=claimed["receipt"]["reservation_id"],
                idempotency_key=carrier["idempotency_key"], status="accepted", run_id=run_id,
            )
            assert accepted["status"] == "accepted" and accepted["run_id"] == run_id
            accepted_ledger = continuation_budget(store, task_id)
            assert len(accepted_ledger) == 1
            assert accepted_ledger[0]["status"] == "accepted"
            assert accepted_ledger[0]["run_id"] == run_id
            close_receipt = runtime_store.close_runtime_root(
                run_id, boot_id=authority["boot_id"], sequence=4,
                outcome="completed", event_sha256="d" * 64)
            assert close_receipt == {
                "schema_version": "agent-run-lifecycle-receipt.v1",
                "sequence": 4,
                "root_run_id": run_id,
                "event_sha256": "d" * 64,
            }
            assert runtime_store._fetch_one(
                "SELECT status, authority_status, terminal_sequence FROM agent_runtime_turns WHERE root_run_id=:root",
                {"root": run_id},
            ) == {"status": "completed", "authority_status": "closed", "terminal_sequence": 4}
            usage = _v3_usage(carrier)
            settlement = _v3_settlement_sha256(
                claimed["receipt"]["reservation_id"], carrier, run_id, "completed", usage)
            settled = store.record_continuation_receipt(
                task_id, trusted_context=trusted_context,
                reservation_id=claimed["receipt"]["reservation_id"],
                idempotency_key=carrier["idempotency_key"], status="settled",
                request_usage=usage, settlement_sha256=settlement, outcome="completed",
            )
            assert settled["status"] == "settled" and settled["run_id"] == run_id
            assert settled["request_usage"] == usage
            assert settled["settlement_sha256"] == settlement
            assert settled["outcome"] == "completed"
            ledger = continuation_budget(store, task_id)
            assert len(ledger) == 1 and ledger[0]["status"] == "settled"
    finally:
        _close_fixture(fixture)
def _revoke_human_permission(fixture: dict[str, object]) -> None:
    job = fixture["jobs"]._fetch_one(
        "SELECT strategy_version_artifact_id FROM signal_producer_jobs WHERE job_id=:job",
        {"job": fixture["job_id"]},
    )
    context = _trusted_context(fixture["human_context"])
    fixture["research"].create_continuation_permission(
        fixture["task"]["task_id"],
        {
            "idempotency_key": f"revoked-before-agent-continuation-{uuid4().hex}",
            "confirmed_artifact_ids": [job["strategy_version_artifact_id"]],
        },
        trusted_context=context,
    )
    fixture["research"].revoke_continuation_permission(
        fixture["task"]["task_id"], grant_version=1, trusted_context=context)


@pytest.mark.parametrize("source_state", ["source_root_active", "source_root_cancelled", "source_ingress_unknown"])
def test_v3_source_root_must_be_normally_closed(monkeypatch, tmp_path, source_state):
    if source_state == "source_root_cancelled":
        fixture = _create_agent_job(monkeypatch, tmp_path, source_state, close_outcome="cancelled")
    else:
        fixture = _create_agent_job(
            monkeypatch, tmp_path, source_state,
            ingress_outcome="unknown" if source_state == "source_ingress_unknown" else "settled",
            close_outcome=None,
        )
    try:
        store = fixture["research"]
        conversation_id = fixture["conversation"]["conversation_id"]
        task_id = fixture["task"]["task_id"]
        trusted_context = fixture["trusted_context"]
        raw_ledger_baseline = continuation_budget(store, task_id)
        assert raw_ledger_baseline is None
        if source_state == "source_ingress_unknown":
            response, _receipt = _close_source_root(fixture, "completed")
            assert response.status_code == 409, response.text
            _assert_root_projection(fixture, "active")
            assert continuation_budget(store, task_id) == raw_ledger_baseline

        assert store.peek_default_continuation_v3(
            conversation_id, trusted_context=trusted_context) == {"status": "waiting"}
        assert continuation_budget(store, task_id) == raw_ledger_baseline

        if source_state == "source_root_active":
            _revoke_human_permission(fixture)
            response, receipt = _close_source_root(fixture, "completed")
            assert response.status_code == 200, response.text
            assert response.json() == {"receipt": receipt}
            _assert_root_projection(fixture, "completed")
            assert continuation_budget(store, task_id) == raw_ledger_baseline
            assert store.peek_default_continuation_v3(
                conversation_id, trusted_context=trusted_context) == {"status": "waiting"}
            assert continuation_budget(store, task_id) == raw_ledger_baseline
    finally:
        _close_fixture(fixture)


@pytest.mark.parametrize("tamper", [
    "origin_root_binding",
    "ingress_settlement",
    "terminal_ingress_cursor",
    "job_idempotency",
    "snapshot_content_hash",
])
def test_v3_source_recheck_rejects_changed_facts_without_ledger_mutation(
        monkeypatch, tmp_path, tamper):
    fixture = _create_agent_job(monkeypatch, tmp_path, f"tamper-{tamper}")
    store, task_id, context = (
        fixture["research"], fixture["task"]["task_id"], fixture["trusted_context"])
    try:
        raw_ledger_baseline = continuation_budget(store, task_id)
        assert raw_ledger_baseline is None
        entry = store.reserve_default_continuation_v3(
            fixture["conversation"]["conversation_id"],
            signal_job_id=fixture["job_id"], trusted_context=context)
        carrier = entry["reservation"]
        before = continuation_budget(store, task_id)
        assert before == [entry]
        assert len(before) == 1
        assert before[0]["status"] == "reserved"
        assert before[0]["dispatch_attempts"] == 0
        if tamper == "origin_root_binding":
            job = fixture["jobs"]._fetch_one(
                "SELECT submission_origin FROM signal_producer_jobs WHERE job_id=:job",
                {"job": fixture["job_id"]},
            )
            changed = dict(job["submission_origin"])
            changed["root_run_id"] = "0" * 32 if changed["root_run_id"] != "0" * 32 else "1" * 32
            fixture["jobs"]._execute(
                "UPDATE signal_producer_jobs SET submission_origin=CAST(:origin AS jsonb) WHERE job_id=:job",
                {"origin": json.dumps(changed), "job": fixture["job_id"]},
            )
        elif tamper == "ingress_settlement":
            row = fixture["agent_store"]._fetch_one(
                "SELECT settlement_json FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
                {"id": fixture["source_ingress"]["mcp_request_id"]},
            )
            changed = dict(row["settlement_json"])
            changed["unexpected"] = "changed"
            fixture["agent_store"]._execute(
                """UPDATE agent_acp_tool_ingress_observations SET settlement_json=CAST(:value AS jsonb)
                   WHERE mcp_request_id=:id""",
                {"value": json.dumps(changed), "id": fixture["source_ingress"]["mcp_request_id"]},
            )
        elif tamper == "terminal_ingress_cursor":
            row = fixture["agent_store"]._fetch_one(
                "SELECT event_sha256 FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
                {"id": fixture["source_ingress"]["mcp_request_id"]},
            )
            changed = "f" * 64 if row["event_sha256"] != "f" * 64 else "e" * 64
            fixture["agent_store"]._execute(
                "UPDATE agent_acp_tool_ingress_observations SET event_sha256=:digest WHERE mcp_request_id=:id",
                {"digest": changed, "id": fixture["source_ingress"]["mcp_request_id"]},
            )
        elif tamper == "job_idempotency":
            fixture["jobs"]._execute(
                "UPDATE signal_producer_jobs SET idempotency_key=:key WHERE job_id=:job",
                {"key": fixture["arguments"]["idempotency_key"] + "-changed",
                 "job": fixture["job_id"]},
            )
        elif tamper == "snapshot_content_hash":
            fixture["research"]._execute(
                "UPDATE artifacts SET content_sha256=:digest WHERE artifact_id=:artifact",
                {"digest": "0" * 64, "artifact": fixture["artifact_id"]},
            )
        assert continuation_budget(store, task_id) == before

        with pytest.raises(ValueError):
            store.claim_continuation_dispatch(
                task_id, entry["reservation_id"], trusted_context=context)
        assert continuation_budget(store, task_id) == before
        with pytest.raises(ValueError):
            store.record_continuation_receipt(
                task_id, trusted_context=context,
                reservation_id=entry["reservation_id"], status="accepted",
                run_id="a" * 32, idempotency_key=carrier["idempotency_key"],
            )
        assert continuation_budget(store, task_id) == before
    finally:
        _close_fixture(fixture)


@pytest.mark.parametrize("source_kind", [
    "human_v1", "agent_root_v2", "agent_child_v2_closed_old_boot",
])
def test_authorize_tool_admits_exact_source_after_start_and_two_reads(
        monkeypatch, tmp_path, source_kind):
    if source_kind == "human_v1":
        runtime_session = f"session-authorize-{uuid4().hex}"
        assert data_ready.TRACE == "byq-trace-task-receipt"
        monkeypatch.setattr(data_ready, "SESSION", runtime_session)
        fixture = setup_ready(monkeypatch, tmp_path)
        assert fixture["context"]["session_id"] == runtime_session
        assert fixture["context"]["trace_id"] == data_ready.TRACE
        store = fixture["store"]
        trusted_context = trusted_v3_tool_context(fixture)
        conversation_id = fixture["conversation"]
        task_id = fixture["payload"]["task_id"]
    else:
        fixture = _create_agent_job(
            monkeypatch, tmp_path, f"authorize-{source_kind}",
            origin="child" if source_kind == "agent_child_v2_closed_old_boot" else "root",
        )
        store = fixture["research"]
        trusted_context = fixture["trusted_context"]
        conversation_id = fixture["conversation"]["conversation_id"]
        task_id = fixture["task"]["task_id"]
        if source_kind == "agent_child_v2_closed_old_boot":
            rotated = fixture["client"].post(
                "/internal/runtime-authority/boot",
                headers={"Authorization": "Bearer test-runtime-authority"},
                json={"schema_version": "byq-runtime-authority-boot.v1", "boot_id": uuid4().hex},
            )
            assert rotated.status_code == 200, rotated.text

    runtime_root = None
    try:
        job_id = fixture["job_id"]
        claimed, carrier, unknown_ledger = _prepare_authorize_dispatch(
            store, conversation_id=conversation_id, task_id=task_id,
            job_id=job_id, artifact_id=fixture["artifact_id"],
            trusted_context=trusted_context,
        )
        runtime_root = _open_authorize_runtime_root(fixture, trusted_context, source_kind)
        reservation_id = claimed["receipt"]["reservation_id"]
        expected = {
            "schema_version": "continuation-action-admission.v1",
            "admitted": True,
            "reservation_id": reservation_id,
            "task_id": task_id,
        }
        # MCP's schema makes parent_run_id optional, so omit it to represent a root.
        actions = [
            ("byq_agent_run_start", {
                "role_id": "quant_orchestrator",
                "idempotency_key": f"continuation-authorize-{runtime_root['root_run_id']}",
            }),
            ("byq_research_get", {
                "entity_type": "research_task", "entity_id": task_id,
            }),
            ("byq_backtest_task_get", {
                "backtest_task_id": task_id_from_signal_job(job_id),
            }),
        ]
        for index, (tool, arguments) in enumerate(actions):
            response = _post_authorize_tool(
                fixture, trusted_context=trusted_context, runtime_root=runtime_root,
                reservation_id=reservation_id, tool=tool, arguments=arguments,
            )
            assert response.status_code == 200, response.text
            assert response.json() == expected
            ledger = continuation_budget(store, task_id)
            if index == 0:
                assert len(ledger) == 1
                assert ledger[0]["status"] == "accepted"
                assert ledger[0]["run_id"] == runtime_root["root_run_id"]
                assert ledger[0]["dispatch_attempts"] == 1
                accepted_ledger = ledger
            else:
                assert ledger == accepted_ledger
        assert unknown_ledger[0]["status"] == "outcome_unknown"
        _close_authorize_runtime_root(runtime_root)
        runtime_root = None
    finally:
        if runtime_root is not None:
            _close_authorize_runtime_root(runtime_root)
        _close_fixture(fixture)


def _tamper_authorize_source_fact(fixture: dict[str, object], tamper: str) -> None:
    if tamper == "origin_root_binding":
        job = fixture["jobs"]._fetch_one(
            "SELECT submission_origin FROM signal_producer_jobs WHERE job_id=:job",
            {"job": fixture["job_id"]},
        )
        changed = dict(job["submission_origin"])
        changed["root_run_id"] = "0" * 32 if changed["root_run_id"] != "0" * 32 else "1" * 32
        fixture["jobs"]._execute(
            "UPDATE signal_producer_jobs SET submission_origin=CAST(:origin AS jsonb) WHERE job_id=:job",
            {"origin": json.dumps(changed), "job": fixture["job_id"]},
        )
    elif tamper == "ingress_settlement":
        row = fixture["agent_store"]._fetch_one(
            "SELECT settlement_json FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": fixture["source_ingress"]["mcp_request_id"]},
        )
        changed = dict(row["settlement_json"])
        changed["unexpected"] = "changed"
        fixture["agent_store"]._execute(
            """UPDATE agent_acp_tool_ingress_observations SET settlement_json=CAST(:value AS jsonb)
               WHERE mcp_request_id=:id""",
            {"value": json.dumps(changed), "id": fixture["source_ingress"]["mcp_request_id"]},
        )
    elif tamper == "terminal_ingress_cursor":
        row = fixture["agent_store"]._fetch_one(
            "SELECT event_sha256 FROM agent_acp_tool_ingress_observations WHERE mcp_request_id=:id",
            {"id": fixture["source_ingress"]["mcp_request_id"]},
        )
        changed = "f" * 64 if row["event_sha256"] != "f" * 64 else "e" * 64
        fixture["agent_store"]._execute(
            "UPDATE agent_acp_tool_ingress_observations SET event_sha256=:digest WHERE mcp_request_id=:id",
            {"digest": changed, "id": fixture["source_ingress"]["mcp_request_id"]},
        )
    elif tamper == "job_idempotency":
        fixture["jobs"]._execute(
            "UPDATE signal_producer_jobs SET idempotency_key=:key WHERE job_id=:job",
            {"key": fixture["arguments"]["idempotency_key"] + "-changed",
             "job": fixture["job_id"]},
        )
    elif tamper == "snapshot_content_hash":
        fixture["research"]._execute(
            "UPDATE artifacts SET content_sha256=:digest WHERE artifact_id=:artifact",
            {"digest": "0" * 64, "artifact": fixture["artifact_id"]},
        )
    elif tamper == "job_request_hash_malformed":
        fixture["jobs"]._execute(
            "UPDATE signal_producer_jobs SET request_hash='bad' WHERE job_id=:job",
            {"job": fixture["job_id"]},
        )
    elif tamper == "job_submission_hash_missing":
        fixture["jobs"]._execute(
            "UPDATE signal_producer_jobs SET submission_hash=NULL WHERE job_id=:job",
            {"job": fixture["job_id"]},
        )


@pytest.mark.parametrize("tamper", [
    "origin_root_binding",
    "ingress_settlement",
    "terminal_ingress_cursor",
    "job_idempotency",
    "snapshot_content_hash",
    "job_request_hash_malformed",
    "job_submission_hash_missing",
])
def test_authorize_tool_rejects_changed_v2_source_without_ledger_mutation(
        monkeypatch, tmp_path, tamper):
    fixture = _create_agent_job(monkeypatch, tmp_path, f"authorize-tamper-{tamper}")
    store, task_id, trusted_context = (
        fixture["research"], fixture["task"]["task_id"], fixture["trusted_context"])
    runtime_root = None
    try:
        claimed, carrier, unknown_ledger = _prepare_authorize_dispatch(
            store, conversation_id=fixture["conversation"]["conversation_id"],
            task_id=task_id, job_id=fixture["job_id"],
            artifact_id=fixture["artifact_id"], trusted_context=trusted_context,
        )
        runtime_root = _open_authorize_runtime_root(fixture, trusted_context, "agent_root_v2")
        _tamper_authorize_source_fact(fixture, tamper)
        assert continuation_budget(store, task_id) == unknown_ledger

        response = _post_authorize_tool(
            fixture, trusted_context=trusted_context, runtime_root=runtime_root,
            reservation_id=claimed["receipt"]["reservation_id"],
            tool="byq_agent_run_start",
            arguments={"role_id": "quant_orchestrator",
                       "idempotency_key": f"continuation-authorize-{runtime_root['root_run_id']}"},
        )
        assert response.status_code == 422, response.text
        assert continuation_budget(store, task_id) == unknown_ledger

        with pytest.raises(ValueError):
            store.record_continuation_receipt(
                task_id, trusted_context=trusted_context,
                reservation_id=claimed["receipt"]["reservation_id"],
                idempotency_key=carrier["idempotency_key"],
                status="accepted", run_id=runtime_root["root_run_id"],
            )
        assert continuation_budget(store, task_id) == unknown_ledger
    finally:
        if runtime_root is not None:
            _close_authorize_runtime_root(runtime_root)
        _close_fixture(fixture)


@pytest.mark.parametrize("violation", ["wrong_task_read", "write_action"])
def test_authorize_tool_blocks_scope_violation_without_ledger_mutation(
        monkeypatch, tmp_path, violation):
    fixture = _create_agent_job(monkeypatch, tmp_path, f"authorize-scope-{violation}")
    store, task_id, trusted_context = (
        fixture["research"], fixture["task"]["task_id"], fixture["trusted_context"])
    runtime_root = None
    try:
        claimed, _carrier, unknown_ledger = _prepare_authorize_dispatch(
            store, conversation_id=fixture["conversation"]["conversation_id"],
            task_id=task_id, job_id=fixture["job_id"],
            artifact_id=fixture["artifact_id"], trusted_context=trusted_context,
        )
        runtime_root = _open_authorize_runtime_root(fixture, trusted_context, "agent_root_v2")
        if violation == "wrong_task_read":
            other = store.create_task({
                "owner_principal": trusted_context["owner_principal"],
                "title": "Other task",
                "objective": "Unrelated continuation target",
                "trace_id": trusted_context["trace_id"],
                "idempotency_key": f"authorize-wrong-target-{uuid4().hex}",
            }, trusted_context=trusted_context)
            tool, arguments = "byq_research_get", {
                "entity_type": "research_task", "entity_id": other["task_id"],
            }
        else:
            tool, arguments = "byq_backtest_task_execute", {
                "backtest_task_id": task_id_from_signal_job(fixture["job_id"]),
            }

        response = _post_authorize_tool(
            fixture, trusted_context=trusted_context, runtime_root=runtime_root,
            reservation_id=claimed["receipt"]["reservation_id"],
            tool=tool, arguments=arguments,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "schema_version": "continuation-action-admission.v1",
            "admitted": False,
            "reservation_id": claimed["receipt"]["reservation_id"],
            "task_id": task_id,
        }
        blocked = store._fetch_one(
            """SELECT continuation_blocked_reason, continuation_blocked_event_key
               FROM research_tasks WHERE task_id=:task""",
            {"task": task_id},
        )
        assert blocked == {
            "continuation_blocked_reason": "continuation_needs_attention",
            "continuation_blocked_event_key": claimed["receipt"]["event_key"],
        }
        assert continuation_budget(store, task_id) == unknown_ledger
    finally:
        if runtime_root is not None:
            _close_authorize_runtime_root(runtime_root)
        _close_fixture(fixture)
