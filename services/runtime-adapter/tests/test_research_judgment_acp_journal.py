"""ADR-0097 durable prompt fence and exact business receipt journal."""

from __future__ import annotations

import os
import json
import stat
import time

import pytest

from app.research_judgment_acp_control import (
    AcpJudgmentOutcomeUnknown, result_request, result_request_sha256,
)
from app.research_judgment_acp_journal import AcpJudgmentJournal
from app.research_judgment_acp_provider_profile import (
    AcpJudgmentProviderProfile, build_provider_profile,
)
from app.research_judgment_acp_provider_usage import AcpProviderStreamReceipt
from app.research_judgment_boundary import derive_call_identity
from packages.contracts.agent_run_lifecycle import lifecycle_receipt


TASK = "task_" + "a" * 32
ROOT = "b" * 32
BOOT = "c" * 32
CALL = derive_call_identity(TASK, "1:strategy_draft:1")
NATIVE = "00000000-0000-4000-8000-000000000001"
BINDING = {"schema_version": "byq-acp-agent-bind-receipt.v1", "status": "bound",
           "root_run_id": ROOT, "runtime_boot_id": BOOT, "origin": "root", "depth": 0,
           "native_agent_session_id": NATIVE, "native_parent_session_id": None,
           "agent_run_id": "agent_run_" + "e" * 32}
BEGIN = {"schema_version": "byq-research-judgment-acp-root-receipt.v1",
         "task_id": TASK, "status": "admitted", "created": True, "call_identity": CALL,
         "attempt_binding": "1:strategy_draft:1",
         "stage": "strategy_draft", "plan_version": 1, "task_version": 1,
         "iteration": 1, "call_index": 1, "model_call_limit": 2,
         "root": {"root_run_id": ROOT, "runtime_boot_id": BOOT,
                  "authority_epoch": 1, "dsh_run_id": "byqjudg-" + "f" * 32,
                  "owner_principal": "alice", "workspace_id": "workspace-alice",
                  "session_id": "session-1", "trace_id": "trace-1",
                  "actor_principal": "byq-product-agent-session-1"}}
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


def _freeze_fixture_profile(journal, limits, *, route="deepseek-official"):
    """Synthetic small limits for the legacy journal boundary fixtures."""
    begin = journal.snapshot()["begin"]
    profile = build_provider_profile({**begin, "created": True}, {
        "source": "environment", "provider": route,
        "model": "synthetic-model", "api_key": "synthetic-secret"},
        request_started_at_ms=int(time.time() * 1000))
    public = {**profile.public, "limits": limits}
    journal.record_provider_profile(AcpJudgmentProviderProfile(
        json.dumps(public).encode(), "synthetic-secret"))


def _small_limits():
    return {"max_calls": 1, "max_input_bytes": 1000,
            "max_total_input_bytes": 1000, "max_output_tokens": 32,
            "max_total_output_tokens": 32,
            "max_tool_payload_bytes": 1000,
            "max_total_tool_payload_bytes": 1000,
            "deadline_at_ms": 2000}


def _complete_provider(journal):
    limits = _small_limits()
    journal.reserve_provider_attempt(route="deepseek-official", body=b"synthetic",
                                     declared_output_tokens=16, limits=limits, now_ms=1000)
    journal.settle_provider_attempt(
        index=1, status=200,
        receipt=AcpProviderStreamReceipt("completed", 5, 6, 0, 0),
        transport_complete=True, now_ms=1001)


def test_journal_freezes_nonsecret_profile_to_admitted_root_and_provider_requests(tmp_path):
    task = "task_" + "a" * 32
    attempt = "1:strategy_draft:1"
    call = derive_call_identity(task, attempt)
    begin = {
        "schema_version": "byq-research-judgment-acp-root-receipt.v1",
        "task_id": task, "status": "admitted", "created": True,
        "call_identity": call, "attempt_binding": attempt,
        "stage": "strategy_draft", "plan_version": 1, "task_version": 1,
        "iteration": 1, "call_index": 1, "model_call_limit": 2,
        "root": {"root_run_id": ROOT, "runtime_boot_id": BOOT,
                 "authority_epoch": 1, "dsh_run_id": "byqjudg-" + "f" * 32,
                 "owner_principal": "alice", "workspace_id": "workspace-alice",
                 "session_id": "session-1", "trace_id": "trace-1",
                 "actor_principal": "byq-product-agent-session-1"},
    }
    resolution = {"source": "user_binding", "provider": "deepseek-official",
                  "model": "selected-model", "api_key": "synthetic-secret",
                  "profile_id": "profile_" + "1" * 32, "profile_version": 2,
                  "credential_id": "cred_" + "2" * 32, "credential_version": 3,
                  "binding_version": 4}
    directory = tmp_path / "control"
    directory.mkdir(mode=0o700)
    journal = AcpJudgmentJournal(
        directory, task, call, backend_url="http://backend",
        authority_headers={"authorization": "Bearer synthetic-runtime-authority"})
    request_started_at_ms = int(time.time() * 1000) - 10_000
    journal.record_request_start(request_started_at_ms)
    journal.record_begin(begin)
    profile = build_provider_profile(
        begin, resolution, request_started_at_ms=request_started_at_ms)
    extended = AcpJudgmentProviderProfile(json.dumps({
        **profile.public,
        "limits": {**profile.public["limits"],
                   "deadline_at_ms": profile.public["limits"]["deadline_at_ms"] + 1},
    }).encode(), "synthetic-secret")
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="durable request start"):
        journal.record_provider_profile(extended)
    future = AcpJudgmentProviderProfile(json.dumps({
        **profile.public,
        "limits": {**profile.public["limits"],
                   "deadline_at_ms": int(time.time() * 1000) + 3600000},
    }).encode(), "synthetic-secret")
    with pytest.raises(ValueError, match="named budget"):
        journal.record_provider_profile(future)
    secret_model = AcpJudgmentProviderProfile(json.dumps({
        **profile.public, "model": "synthetic-secret",
    }).encode(), "synthetic-secret")
    with pytest.raises(ValueError, match="nonsecret"):
        journal.record_provider_profile(secret_model)
    frozen = journal.record_provider_profile(profile)
    assert frozen["provider_profile"] == profile.public
    assert frozen["provider_limits"] == profile.public["limits"]
    assert b"synthetic-secret" not in journal.path.read_bytes()
    malformed = AcpJudgmentProviderProfile(
        json.dumps({**profile.public, "api_key": "synthetic-secret"}).encode(),
        "synthetic-secret")
    with pytest.raises(ValueError, match="nonsecret"):
        journal.record_provider_profile(malformed)
    assert b"synthetic-secret" not in journal.path.read_bytes()
    assert journal.record_provider_profile(profile) == frozen
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="profile changed"):
        journal.record_provider_profile(build_provider_profile(
            begin, {**resolution, "model": "different-model"},
            request_started_at_ms=request_started_at_ms))
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="Backend root"):
        journal.record_provider_profile(build_provider_profile(
            {**begin, "root": {**begin["root"], "root_run_id": "0" * 32}},
            resolution, request_started_at_ms=request_started_at_ms))
    journal.record_binding(BINDING)
    journal.mark_prompt_may_dispatch()
    limits = profile.public["limits"]
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="frozen root profile"):
        journal.reserve_provider_attempt(
            route="opencode-go-chat", body=b"synthetic",
            declared_output_tokens=16, limits=limits)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="provider limits changed"):
        journal.reserve_provider_attempt(
            route="deepseek-official", body=b"synthetic",
            declared_output_tokens=16, limits={**limits, "max_calls": 2})
    attempt_row = journal.reserve_provider_attempt(
        route="deepseek-official", body=b"synthetic",
        declared_output_tokens=16, limits=limits)
    assert attempt_row["index"] == 1


def test_journal_fsync_phase_order_and_restart_never_replays_prompt(tmp_path):
    journal, current, post = _journal(tmp_path)
    journal.record_request_start(int(time.time() * 1000))
    journal.record_begin(BEGIN)
    assert journal.record_begin({**BEGIN, "created": False})["phase"] == "begun"
    journal.record_binding(BINDING)
    assert stat.S_IMODE(os.stat(journal.path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(journal.directory).st_mode) == 0o700
    _freeze_fixture_profile(journal, _small_limits())
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


def test_request_start_is_durable_before_begin_and_cannot_be_reset(tmp_path):
    journal, _, post = _journal(tmp_path)
    started_at_ms = int(time.time() * 1000) - 1000
    assert journal.record_request_start(started_at_ms)["phase"] == "prepared"
    assert journal.record_request_start(started_at_ms)["request_started_at_ms"] == started_at_ms
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="start time changed"):
        journal.record_request_start(started_at_ms + 1)
    restarted = AcpJudgmentJournal(
        journal.directory, TASK, CALL, backend_url="http://backend",
        authority_headers={"authorization": "Bearer synthetic-runtime-authority"},
        transport=post)
    assert restarted.snapshot()["request_started_at_ms"] == started_at_ms
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="replayed judgment root"):
        restarted.record_begin({**BEGIN, "created": False})
    assert restarted.snapshot()["phase"] == "prepared"
    assert restarted.record_begin(BEGIN)["phase"] == "begun"
    assert restarted.record_begin({**BEGIN, "created": False})["phase"] == "begun"
    assert restarted.snapshot()["request_started_at_ms"] == started_at_ms
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="start time changed"):
        restarted.record_request_start(started_at_ms + 1)


def test_journal_refuses_prompt_without_frozen_provider_profile(tmp_path):
    journal, _, _ = _journal(tmp_path)
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="profile is not frozen"):
        journal.mark_prompt_may_dispatch()
    assert journal.snapshot()["phase"] == "bound"


def test_journal_rejects_changed_root_and_result_without_overwriting(tmp_path):
    journal, _, _ = _journal(tmp_path)
    journal.record_request_start(int(time.time() * 1000))
    journal.record_begin(BEGIN)
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="begin receipt differs"):
        journal.record_begin({**BEGIN, "root": {**BEGIN["root"], "root_run_id": "0" * 32}})
    journal.record_binding(BINDING)
    _freeze_fixture_profile(journal, _small_limits())
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
    journal.record_request_start(int(time.time() * 1000))
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    _freeze_fixture_profile(journal, _small_limits())
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
    journal.record_request_start(int(time.time() * 1000))
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    _freeze_fixture_profile(journal, _small_limits())
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


def _provider_ready(tmp_path, *, route="opencode-go-chat", override=None):
    journal, _, post = _journal(tmp_path)
    journal.record_request_start(int(time.time() * 1000))
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    limits = {"max_calls": 2, "max_input_bytes": 1000,
              "max_total_input_bytes": 1500, "max_output_tokens": 32,
              "max_total_output_tokens": 64,
              "max_tool_payload_bytes": 1000,
              "max_total_tool_payload_bytes": 1500,
              "deadline_at_ms": 2000}
    limits = {**limits, **(override or {})}
    _freeze_fixture_profile(journal, limits, route=route)
    journal.mark_prompt_may_dispatch()
    return journal, limits, post


def test_provider_attempt_is_fsynced_before_dispatch_and_unknown_after_restart(tmp_path):
    journal, limits, post = _provider_ready(tmp_path, route="deepseek-official")
    attempt = journal.reserve_provider_attempt(
        route="deepseek-official", body=b'{"synthetic":true}',
        declared_output_tokens=16, limits=limits, now_ms=1000)
    assert attempt["phase"] == "may_have_dispatched"
    assert '"synthetic":true' not in journal.path.read_text()
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
    journal, limits, _ = _provider_ready(tmp_path, override=override)
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
    journal, limits, _ = _provider_ready(tmp_path, override=override)
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


def test_turn_diagnostic_error_name_and_code_are_a_closed_allowlist():
    # A short dynamic class/code name can itself carry a secret, so only exact
    # known class names and the closed runner REJECT code enum may survive.
    from app.research_judgment_acp_journal import _bounded_error_class, _bounded_error_code
    fake = type("FAKE_SECRET_123", (Exception,), {})()
    fake.code = "FAKE_SECRET_123"
    assert _bounded_error_class(fake) is None
    assert _bounded_error_code(fake) is None

    known = type("AcpJudgmentOutcomeUnknown", (Exception,), {})()
    assert _bounded_error_class(known) == "outcome_unknown"

    mapped = type("RunnerRejected", (Exception,), {})()
    mapped.code = "scope_consumed"
    assert _bounded_error_class(mapped) == "runner_rejected"
    assert _bounded_error_code(mapped) == "scope_consumed"
    mapped.code = "FAKE_SECRET_123"
    assert _bounded_error_code(mapped) is None


def test_turn_diagnostic_code_enum_stays_in_sync_with_runner_reject_codes():
    from app.research_judgment_acp_journal import _TURN_ERROR_CODES
    from app.research_judgment_acp_runner_client import _REJECT_CODES
    assert _TURN_ERROR_CODES == _REJECT_CODES


def test_turn_diagnostic_never_persists_a_dynamic_class_or_code_name(tmp_path):
    journal, _, _ = _journal(tmp_path)
    journal.record_begin(BEGIN)
    fake = type("FAKE_SECRET_123", (Exception,), {})()
    fake.code = "FAKE_SECRET_123"
    diagnostic = journal.record_turn_outcome(
        finish="completed", error=fake, result_failure="none")["turn_diagnostic"]
    assert diagnostic["error_class"] is None
    assert diagnostic["error_code"] is None
    assert b"FAKE_SECRET_123" not in journal.path.read_bytes()


def test_turn_diagnostic_is_admitted_before_settlement_and_then_immutable(tmp_path):
    journal, _, _ = _journal(tmp_path)
    journal.record_begin(BEGIN)
    result = journal.record_turn_outcome(
        finish="completed", error=None, result_failure="none")
    assert result["turn_diagnostic"]["finish"] == "completed"
    again = journal.record_turn_outcome(
        finish="cancelled", error=None, result_failure="none")
    assert again["turn_diagnostic"]["finish"] == "completed"


def test_turn_diagnostic_is_refused_after_settlement_without_touching_sealed_bytes(tmp_path):
    journal, current, _ = _journal(tmp_path)
    journal.record_request_start(int(time.time() * 1000))
    journal.record_begin(BEGIN)
    journal.record_binding(BINDING)
    _freeze_fixture_profile(journal, _small_limits())
    journal.mark_prompt_may_dispatch()
    _complete_provider(journal)
    request = result_request(TASK, BEGIN, BINDING, NATIVE,
                             {"durable_evidence": {"kind": "none"}})
    journal.record_result_request(request)
    current["status"] = _status(request)
    journal.record_result_receipt(RESULT_RECEIPT)
    assert journal.snapshot()["phase"] == "result_committed"
    sealed = journal.path.read_bytes()
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="pre-settlement"):
        journal.record_turn_outcome(finish="completed", error=None, result_failure="none")
    assert journal.path.read_bytes() == sealed
    assert "turn_diagnostic" not in journal.snapshot()

    current["status"] = _status(request, closed=True)
    journal.record_terminal_receipt(TERMINAL)
    assert journal.snapshot()["phase"] == "terminal_closed"
    sealed = journal.path.read_bytes()
    with pytest.raises(AcpJudgmentOutcomeUnknown, match="pre-settlement"):
        journal.record_turn_outcome(finish="completed", error=None, result_failure="none")
    assert journal.path.read_bytes() == sealed
