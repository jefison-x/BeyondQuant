"""ADR-0097 durable prompt fence and exact business receipt journal."""

from __future__ import annotations

import os
import stat

import pytest

from app.research_judgment_acp_control import (
    AcpJudgmentOutcomeUnknown, result_request, result_request_sha256,
)
from app.research_judgment_acp_journal import AcpJudgmentJournal
from app.research_judgment_acp_provider_usage import AcpProviderStreamReceipt
from packages.contracts.agent_run_lifecycle import lifecycle_receipt


TASK = "task_" + "a" * 32
ROOT = "b" * 32
BOOT = "c" * 32
CALL = "byq-judgment-" + "d" * 32
NATIVE = "00000000-0000-4000-8000-000000000001"
BINDING = {"schema_version": "byq-acp-agent-bind-receipt.v1", "status": "bound",
           "root_run_id": ROOT, "runtime_boot_id": BOOT, "origin": "root", "depth": 0,
           "native_agent_session_id": NATIVE, "native_parent_session_id": None,
           "agent_run_id": "agent_run_" + "e" * 32}
BEGIN = {"task_id": TASK, "status": "admitted", "created": True, "call_identity": CALL,
         "attempt_binding": "1:strategy_draft:1",
         "root": {"root_run_id": ROOT, "runtime_boot_id": BOOT,
                  "authority_epoch": 1, "dsh_run_id": "byqjudg-" + "f" * 32}}
RESULT_RECEIPT = {"schema_version": "research-judgment-result-receipt.v1",
                  "call_identity": CALL, "proposal": None, "progress": {"outcome": "no_progress"}}
TERMINAL = lifecycle_receipt({"schema_version": "agent-run-lifecycle.v1",
                              "root_run_id": ROOT, "sequence": 2, "outcome": "completed"})


def _journal(tmp_path):
    directory = tmp_path / "control"
    directory.mkdir(mode=0o700)
    current = {"status": None}

    def post(url, body, headers, timeout):
        assert url.endswith("/acp-root/status")
        assert headers == {"authorization": "Bearer synthetic-runtime-authority"}
        return current["status"]

    return (AcpJudgmentJournal(directory, TASK, CALL,
                               backend_url="http://backend",
                               authority_headers={"authorization": "Bearer synthetic-runtime-authority"},
                               transport=post), current, post)


def _status(request, *, closed=False):
    return {"schema_version": "byq-research-judgment-acp-status-receipt.v1",
            "task_id": TASK, "call_identity": CALL, "attempt_binding": BEGIN["attempt_binding"],
            "root_run_id": ROOT, "runtime_boot_id": BOOT,
            "authority_epoch": BEGIN["root"]["authority_epoch"],
            "dsh_run_id": BEGIN["root"]["dsh_run_id"],
            "native_root_session_id": NATIVE, "agent_run_id": BINDING["agent_run_id"],
            "stage_call_status": "completed", "result_request_sha256": result_request_sha256(request),
            "result_receipt": RESULT_RECEIPT,
            "root_status": "completed" if closed else "active",
            "root_authority_status": "closed" if closed else "active",
            "terminal_sequence": TERMINAL["sequence"] if closed else None,
            "terminal_event_sha256": TERMINAL["event_sha256"] if closed else None,
            "terminal_acp_ingress_sequence": 0 if closed else None,
            "terminal_acp_ingress_sha256": "a" * 64 if closed else None,
            "terminal_unknown_claim_count": 0 if closed else None,
            "terminal_unknown_claims_sha256": "b" * 64 if closed else None}


def _complete_provider(journal):
    limits = {"max_calls": 1, "max_input_bytes": 1000,
              "max_total_input_bytes": 1000, "max_output_tokens": 32,
              "max_total_output_tokens": 32,
              "max_tool_payload_bytes": 1000,
              "max_total_tool_payload_bytes": 1000,
              "deadline_at_ms": 2000}
    journal.reserve_provider_attempt(route="deepseek-official", body=b"synthetic",
                                     declared_output_tokens=16, limits=limits, now_ms=1000)
    journal.settle_provider_attempt(
        index=1, status=200,
        receipt=AcpProviderStreamReceipt("completed", 5, 6, 0, 0),
        transport_complete=True, now_ms=1001)


def test_journal_fsync_phase_order_and_restart_never_replays_prompt(tmp_path):
    journal, current, post = _journal(tmp_path)
    journal.record_begin(BEGIN)
    assert journal.record_begin({**BEGIN, "created": False})["phase"] == "begun"
    journal.record_binding(BINDING)
    assert stat.S_IMODE(os.stat(journal.path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(journal.directory).st_mode) == 0o700
    journal.mark_prompt_may_dispatch()
    restarted = AcpJudgmentJournal(journal.directory, TASK, CALL,
                                   backend_url="http://backend",
                                   authority_headers={"authorization": "Bearer synthetic-runtime-authority"},
                                   transport=post)
    assert restarted.snapshot()["phase"] == "prompt_may_have_dispatched"
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="already have been dispatched"):
        restarted.mark_prompt_may_dispatch()
    _complete_provider(restarted)
    request = result_request(TASK, BEGIN, BINDING, NATIVE,
                             {"durable_evidence": {"kind": "none"}})
    restarted.record_result_request(request)
    assert restarted.record_result_request(request)["phase"] == "result_prepared"
    current["status"] = _status(request)
    restarted.record_result_receipt(RESULT_RECEIPT)
    current["status"] = _status(request, closed=True)
    restarted.record_terminal_receipt(TERMINAL)
    assert restarted.snapshot()["phase"] == "terminal_closed"


def test_journal_rejects_changed_root_and_result_without_overwriting(tmp_path):
    journal, _, _ = _journal(tmp_path)
    journal.record_begin(BEGIN)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="begin receipt differs"):
        journal.record_begin({**BEGIN, "root": {**BEGIN["root"], "root_run_id": "0" * 32}})
    journal.record_binding(BINDING)
    journal.mark_prompt_may_dispatch()
    _complete_provider(journal)
    request = result_request(TASK, BEGIN, BINDING, NATIVE,
                             {"durable_evidence": {"kind": "none"}})
    journal.record_result_request(request)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="result request changed"):
        journal.record_result_request({**request, "durable_evidence": {"kind": "plan_advance"}})
    assert journal.snapshot()["result_request"] == request


def test_journal_rejects_non_private_file_and_premature_terminal(tmp_path):
    journal, _, _ = _journal(tmp_path)
    journal.record_begin(BEGIN)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="not committed"):
        journal.record_terminal_receipt(TERMINAL)
    os.chmod(journal.path, 0o644)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="not a private regular file"):
        journal.snapshot()


def test_journal_never_promotes_unproven_backend_result_or_terminal(tmp_path):
    journal, current, _ = _journal(tmp_path)
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    journal.mark_prompt_may_dispatch()
    _complete_provider(journal)
    request = result_request(TASK, BEGIN, BINDING, NATIVE,
                             {"durable_evidence": {"kind": "none"}})
    journal.record_result_request(request)
    current["status"] = {**_status(request), "result_request_sha256": "sha256:" + "0" * 64}
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="exact judgment result"):
        journal.record_result_receipt(RESULT_RECEIPT)
    assert journal.snapshot()["phase"] == "result_prepared"
    current["status"] = _status(request)
    journal.record_result_receipt(RESULT_RECEIPT)
    current["status"] = {**_status(request, closed=True), "terminal_unknown_claim_count": 1}
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="terminal ACK"):
        journal.record_terminal_receipt(TERMINAL)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="terminal ACK"):
        current["status"] = _status(request)
        journal.record_terminal_receipt(TERMINAL)
    assert journal.snapshot()["phase"] == "result_committed"


def test_journal_rejects_changed_root_generation_in_prepared_result(tmp_path):
    journal, _, _ = _journal(tmp_path)
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    journal.mark_prompt_may_dispatch()
    _complete_provider(journal)
    request = result_request(TASK, BEGIN, BINDING, NATIVE,
                             {"durable_evidence": {"kind": "none"}})
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="differs from durable root"):
        journal.record_result_request({**request, "dsh_run_id": "byqjudg-" + "0" * 32})
    assert journal.snapshot()["phase"] == "prompt_may_have_dispatched"


def test_journal_requires_preprovisioned_private_directory(tmp_path):
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="pre-provisioned"):
        AcpJudgmentJournal(tmp_path / "missing", TASK, CALL,
                           backend_url="http://backend",
                           authority_headers={"authorization": "Bearer synthetic-runtime-authority"})


def test_empty_journal_rejects_replayed_backend_root(tmp_path):
    journal, _, _ = _journal(tmp_path)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="no durable prompt fence"):
        journal.record_begin({**BEGIN, "created": False})
    assert journal.snapshot() is None


def _provider_ready(tmp_path):
    journal, _, post = _journal(tmp_path)
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    journal.mark_prompt_may_dispatch()
    limits = {"max_calls": 2, "max_input_bytes": 1000,
              "max_total_input_bytes": 1500, "max_output_tokens": 32,
              "max_total_output_tokens": 64,
              "max_tool_payload_bytes": 1000,
              "max_total_tool_payload_bytes": 1500,
              "deadline_at_ms": 2000}
    return journal, limits, post


def test_provider_attempt_is_fsynced_before_dispatch_and_unknown_after_restart(tmp_path):
    journal, limits, post = _provider_ready(tmp_path)
    attempt = journal.reserve_provider_attempt(
        route="deepseek-official", body=b'{"synthetic":true}',
        declared_output_tokens=16, limits=limits, now_ms=1000)
    assert attempt["phase"] == "may_have_dispatched"
    assert "synthetic" not in journal.path.read_text()
    restarted = AcpJudgmentJournal(journal.directory, TASK, CALL,
                                   backend_url="http://backend",
                                   authority_headers={"authorization": "Bearer synthetic-runtime-authority"},
                                   transport=post)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="previous provider attempt is unknown"):
        restarted.reserve_provider_attempt(
            route="deepseek-official", body=b'{"synthetic":true}',
            declared_output_tokens=16, limits=limits, now_ms=1001)
    request = result_request(TASK, BEGIN, BINDING, NATIVE,
                             {"durable_evidence": {"kind": "none"}})
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="provider outcome is unknown"):
        restarted.record_result_request(request)


def test_result_cannot_commit_without_any_provider_gate_receipt(tmp_path):
    journal, _, _ = _provider_ready(tmp_path)
    request = result_request(TASK, BEGIN, BINDING, NATIVE,
                             {"durable_evidence": {"kind": "none"}})
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="provider outcome is unknown"):
        journal.record_result_request(request)


def test_provider_receipt_allows_next_bounded_call_only_after_complete_usage(tmp_path):
    journal, limits, _ = _provider_ready(tmp_path)
    first = journal.reserve_provider_attempt(
        route="opencode-go-chat", body=b"first", declared_output_tokens=16,
        limits=limits, now_ms=1000)
    receipt = AcpProviderStreamReceipt("completed", 5, 6, 0, 0)
    closed = journal.settle_provider_attempt(
        index=first["index"], status=200, receipt=receipt,
        transport_complete=True, now_ms=1001)
    assert closed["phase"] == "completed"
    second = journal.reserve_provider_attempt(
        route="opencode-go-chat", body=b"second", declared_output_tokens=16,
        limits=limits, now_ms=1002)
    assert second["index"] == 2
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="previous provider attempt is unknown"):
        journal.reserve_provider_attempt(
            route="opencode-go-chat", body=b"third", declared_output_tokens=16,
            limits=limits, now_ms=1003)
    journal.settle_provider_attempt(index=2, status=200, receipt=receipt,
                                    transport_complete=True, now_ms=1004)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="budget exhausted"):
        journal.reserve_provider_attempt(
            route="opencode-go-chat", body=b"third", declared_output_tokens=16,
            limits=limits, now_ms=1005)


@pytest.mark.parametrize("status,receipt,transport_complete", [
    (200, AcpProviderStreamReceipt("completed", 5, 6, 0, 0), False),
    (302, AcpProviderStreamReceipt("completed", 5, 6, 0, 0), True),
    (200, AcpProviderStreamReceipt("completed", 5, 17, 0, 0), True),
    (200, AcpProviderStreamReceipt("completed", 5, 6, "unknown", 0), True),
    (200, AcpProviderStreamReceipt("completed", -1, -1, -1, -1), True),
    (200, AcpProviderStreamReceipt("incomplete", 5, 6, 0, 0), True),
])
def test_unproved_provider_outcome_permanently_blocks_following_call(
        tmp_path, status, receipt, transport_complete):
    journal, limits, _ = _provider_ready(tmp_path)
    journal.reserve_provider_attempt(route="opencode-go-chat", body=b"first",
                                     declared_output_tokens=16, limits=limits, now_ms=1000)
    row = journal.settle_provider_attempt(
        index=1, status=status, receipt=receipt,
        transport_complete=transport_complete, now_ms=1001)
    assert row["phase"] == "unknown"
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="previous provider attempt is unknown"):
        journal.reserve_provider_attempt(route="opencode-go-chat", body=b"second",
                                         declared_output_tokens=16, limits=limits, now_ms=1002)


@pytest.mark.parametrize("override,body,declared,now_ms", [
    ({"max_input_bytes": 4}, b"five!", 16, 1000),
    ({"max_tool_payload_bytes": 4}, b"five!", 16, 1000),
    ({"max_output_tokens": 8}, b"first", 9, 1000),
    ({}, b"first", 16, 2000),
])
def test_provider_first_call_bounds_refuse_before_attempt_marker(
        tmp_path, override, body, declared, now_ms):
    journal, limits, _ = _provider_ready(tmp_path)
    limits = {**limits, **override}
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="budget exhausted"):
        journal.reserve_provider_attempt(route="opencode-go-chat", body=body,
                                         declared_output_tokens=declared,
                                         limits=limits, now_ms=now_ms)
    assert journal.snapshot().get("provider_attempts") is None


@pytest.mark.parametrize("override", [
    {"max_total_input_bytes": 8},
    {"max_total_tool_payload_bytes": 8},
    {"max_total_output_tokens": 20},
])
def test_provider_cumulative_bounds_refuse_second_call(tmp_path, override):
    journal, limits, _ = _provider_ready(tmp_path)
    limits = {**limits, **override}
    journal.reserve_provider_attempt(route="opencode-go-chat", body=b"first",
                                     declared_output_tokens=16, limits=limits, now_ms=1000)
    journal.settle_provider_attempt(index=1, status=200,
                                    receipt=AcpProviderStreamReceipt("completed", 5, 6, 0, 0),
                                    transport_complete=True, now_ms=1001)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="budget exhausted"):
        journal.reserve_provider_attempt(route="opencode-go-chat", body=b"second",
                                         declared_output_tokens=16, limits=limits,
                                         now_ms=1002)
    assert len(journal.snapshot()["provider_attempts"]) == 1


def test_provider_completion_at_deadline_is_unknown(tmp_path):
    journal, limits, _ = _provider_ready(tmp_path)
    journal.reserve_provider_attempt(route="opencode-go-chat", body=b"first",
                                     declared_output_tokens=16, limits=limits, now_ms=1000)
    row = journal.settle_provider_attempt(
        index=1, status=200, receipt=AcpProviderStreamReceipt("completed", 5, 6, 0, 0),
        transport_complete=True, now_ms=limits["deadline_at_ms"])
    assert row["phase"] == "unknown"
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="previous provider attempt is unknown"):
        journal.reserve_provider_attempt(route="opencode-go-chat", body=b"second",
                                         declared_output_tokens=16, limits=limits, now_ms=1002)
