"""Focused ADR-0097 exact result/terminal readback without a provider call."""

from __future__ import annotations

import urllib.error
import hashlib
import json

import pytest

from app.research_judgment_acp_control import (
    AcpJudgmentOutcomeUnknown,
    close_result_root_once,
    close_settled_root_once,
    result_request,
    result_request_sha256,
    settlement_digest,
    settlement_request,
    submit_settlement_once,
    submit_result_once,
)


TASK = "task_" + "a" * 32
ROOT = "b" * 32
BOOT = "c" * 32
CALL = "byq-judgment-" + "d" * 32
NATIVE = "00000000-0000-4000-8000-000000000001"
RUN = "agent_run_" + "e" * 32
BEGIN = {"task_id": TASK, "status": "admitted", "call_identity": CALL,
         "attempt_binding": "1:strategy_draft:1",
         "root": {"root_run_id": ROOT, "runtime_boot_id": BOOT,
                  "authority_epoch": 1, "dsh_run_id": "byqjudg-" + "f" * 32}}
BINDING = {"schema_version": "byq-acp-agent-bind-receipt.v1", "status": "bound",
           "root_run_id": ROOT, "runtime_boot_id": BOOT,
           "native_agent_session_id": NATIVE, "native_parent_session_id": None,
           "origin": "root", "depth": 0, "agent_run_id": RUN}
RECEIPT = {"schema_version": "research-judgment-result-receipt.v1",
           "call_identity": CALL, "proposal": None, "proposal_identity": None,
           "progress": {"outcome": "no_progress"}}


def _request():
    return result_request(TASK, BEGIN, BINDING, NATIVE, {"durable_evidence": {"kind": "none"}})


def _status(request, *, closed=False, digest=None):
    from packages.contracts.agent_run_lifecycle import lifecycle_receipt

    terminal = lifecycle_receipt({"schema_version": "agent-run-lifecycle.v1",
                                  "root_run_id": ROOT, "sequence": 2,
                                  "outcome": "completed"})
    return {"schema_version": "byq-research-judgment-acp-status-receipt.v1",
            "task_id": TASK, "call_identity": CALL,
            "attempt_binding": request["attempt_binding"], "root_run_id": ROOT,
            "runtime_boot_id": BOOT,
            "authority_epoch": request["authority_epoch"],
            "dsh_run_id": request["dsh_run_id"],
            "agent_run_id": request["agent_run_id"],
            "native_root_session_id": request["native_root_session_id"],
            "stage_call_status": "completed", "result_request_sha256": digest or result_request_sha256(request),
            "result_receipt": RECEIPT, "root_status": "completed" if closed else "active",
            "root_authority_status": "closed" if closed else "active",
            "terminal_sequence": terminal["sequence"] if closed else None,
            "terminal_event_sha256": terminal["event_sha256"] if closed else None,
            "terminal_acp_ingress_sequence": 0 if closed else None,
            "terminal_acp_ingress_sha256": "a" * 64 if closed else None,
            "terminal_unknown_claim_count": 0 if closed else None,
            "terminal_unknown_claims_sha256": "b" * 64 if closed else None}


def test_result_input_uses_only_exact_backend_root_and_native_binding():
    request = _request()
    assert request["root_run_id"] == ROOT and request["agent_run_id"] == RUN
    assert request["durable_evidence"] == {"kind": "none"}
    with pytest.raises(Exception, match="native Agent binding"):
        result_request(TASK, BEGIN, BINDING, "00000000-0000-4000-8000-000000000002", {})
    with pytest.raises(Exception, match="durable evidence identity"):
        result_request(TASK, BEGIN, BINDING, NATIVE,
                       {"durable_evidence": {"kind": "plan_advance"}})


def test_lost_result_response_uses_exact_status_without_reposting():
    request = _request()
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body))
        if url.endswith("/result"):
            raise urllib.error.URLError("synthetic lost result response")
        return _status(request)

    receipt = submit_result_once(backend_url="http://backend", task_id=TASK,
                                 request=request, headers={}, transport=post)
    assert receipt == RECEIPT
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["result", "status"]


def test_changed_result_digest_remains_unknown_and_does_not_close():
    request = _request()
    calls = []

    def post(url, body, headers, timeout):
        calls.append(url)
        if url.endswith("/result"):
            raise urllib.error.URLError("synthetic lost response")
        return _status(request, digest="sha256:" + "0" * 64)

    with pytest.raises(AcpJudgmentOutcomeUnknown, match="not exactly committed"):
        submit_result_once(backend_url="http://backend", task_id=TASK,
                           request=request, headers={}, transport=post)
    assert not any(url.endswith("/close") for url in calls)


def test_lost_close_response_requires_exact_terminal_status():
    request = _request()
    calls = []
    closed = False

    def post(url, body, headers, timeout):
        nonlocal closed
        calls.append((url, body))
        if url.endswith("/close"):
            closed = True
            raise urllib.error.URLError("synthetic lost close response")
        return _status(request, closed=closed)

    receipt = close_result_root_once(backend_url="http://backend", task_id=TASK,
                                     result_request=request, headers={}, transport=post)
    assert receipt["schema_version"] == "agent-run-lifecycle-receipt.v1"
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["status", "close", "status"]
    assert calls[1][1]["event_sha256"] == receipt["event_sha256"]


def test_unproven_close_stays_unknown_even_after_status_readback():
    request = _request()
    calls = []

    def post(url, body, headers, timeout):
        calls.append(url)
        if url.endswith("/close"):
            raise urllib.error.URLError("synthetic lost close response")
        return _status(request, closed=False)

    with pytest.raises(AcpJudgmentOutcomeUnknown, match="terminal ACK"):
        close_result_root_once(backend_url="http://backend", task_id=TASK,
                               result_request=request, headers={}, transport=post)
    assert len([url for url in calls if url.endswith("/close")]) == 1


SETTLEMENT_CALL = "byq-judgment-" + hashlib.sha256(
    f"{TASK}:1:strategy_draft:1".encode()).hexdigest()[:32]
SETTLEMENT_BEGIN = {
    "schema_version": "byq-research-judgment-acp-root-receipt.v1",
    "status": "admitted", "task_id": TASK, "call_identity": SETTLEMENT_CALL,
    "attempt_binding": "1:strategy_draft:1", "plan_version": 1, "task_version": 1,
    "stage": "strategy_draft", "iteration": 1, "call_index": 1,
    "model_call_limit": 2,
    "stage_input": {
        "schema_version": "research-stage-input.v1", "task_id": TASK,
        "plan_version": 1, "task_version": 1, "stage": "strategy_draft",
        "iteration": 1, "status": "active", "objective": "synthetic",
        "stage_instruction": "synthetic", "proposal_kinds": ["strategy_draft"],
        "evidence": [], "allowed_tools": ["byq_agent_context"],
        "model_call_limit": 2, "escalation_allowed": False,
    },
    "root": {
        "root_run_id": ROOT, "owner_principal": "user_synthetic",
        "workspace_id": "workspace_synthetic", "actor_principal": "byq-product-agent-byqjdg-" + "1" * 32,
        "session_id": "byqjdg-" + "1" * 32, "trace_id": "trace_synthetic",
        "runtime_boot_id": BOOT, "authority_epoch": 7,
        "dsh_run_id": "byqjudg-" + "2" * 32,
    },
    "created": True,
}
SETTLEMENT_EVIDENCE = {
    "schema_version": "byq-research-judgment-acp-settlement-evidence.v1",
    "journal_status": "available", "journal_sha256": "sha256:" + "1" * 64,
    "prompt_dispatch": "not_dispatched", "prompt_sha256": None,
    "provider_attempt": "not_started", "provider_attempt_sha256": None,
    "process_fence": "stopped", "process_fence_sha256": "sha256:" + "3" * 64,
    "known_usage": {"status": "unknown"}, "cancellation_intent_receipt": None,
}
SETTLEMENT = settlement_request(
    TASK, SETTLEMENT_BEGIN, settlement_kind="never_dispatched",
    terminal_outcome="failed", durably_recorded_evidence=SETTLEMENT_EVIDENCE)


def _settlement_receipt(request=SETTLEMENT, *, digest=None, owner=None, root=None, outcome=None):
    begin = SETTLEMENT_BEGIN
    root_facts = begin["root"]
    request_digest = digest or settlement_digest(begin, request)
    return {
        "schema_version": "byq-research-judgment-acp-settlement-receipt.v1",
        "status": "settled", "task_id": TASK,
        "owner_principal": owner or root_facts["owner_principal"],
        "workspace_id": root_facts["workspace_id"],
        "actor_principal": root_facts["actor_principal"],
        "call_identity": begin["call_identity"],
        "attempt_binding": begin["attempt_binding"],
        "root_run_id": root or root_facts["root_run_id"],
        "runtime_boot_id": root_facts["runtime_boot_id"],
        "authority_epoch": root_facts["authority_epoch"],
        "dsh_run_id": root_facts["dsh_run_id"],
        "plan_version": begin["plan_version"], "stage": begin["stage"],
        "iteration": begin["iteration"], "call_index": begin["call_index"],
        "settlement_kind": request["settlement_kind"],
        "terminal_outcome": outcome or request["terminal_outcome"],
        "settlement_digest": request_digest, "evidence": request["evidence"],
        "backend_ingress_evidence": {
            "schema_version": "byq-acp-terminal-evidence-snapshot.v1",
            "terminal_acp_ingress_sequence": 0,
            "terminal_acp_ingress_sha256": "a" * 64,
            "terminal_unknown_claim_count": 0,
            "terminal_unknown_claims_sha256": "b" * 64,
        },
        "attention": {"state": "needs_attention", "reason": "synthetic",
                      "task_status": "active", "task_version": 2, "plan_version": 2},
        "settled_at": "2026-10-05T00:00:00Z",
    }


def _settlement_status(*, request=SETTLEMENT, settled=None, closed=False,
                       digest=None, owner=None, status_root=None, outcome=None,
                       unknown_claims=0, terminal_outcome=None, authority_epoch=None,
                       dsh_run_id=None, binding_status="root_created",
                       late_ingress=False):
    receipt = settled or _settlement_receipt(request, digest=digest, owner=owner,
                                               root=status_root, outcome=outcome)
    from packages.contracts.agent_run_lifecycle import lifecycle_receipt

    terminal = lifecycle_receipt({"schema_version": "agent-run-lifecycle.v1",
                                  "root_run_id": ROOT, "sequence": 2,
                                  "outcome": request["terminal_outcome"]})
    terminal_state = terminal_outcome or request["terminal_outcome"]
    return {
        "schema_version": "byq-research-judgment-acp-status-receipt.v1",
        "task_id": TASK, "call_identity": SETTLEMENT_BEGIN["call_identity"],
        "attempt_binding": SETTLEMENT_BEGIN["attempt_binding"],
        "root_run_id": status_root or ROOT, "runtime_boot_id": BOOT,
        "authority_epoch": (SETTLEMENT_BEGIN["root"]["authority_epoch"]
                            if authority_epoch is None else authority_epoch),
        "dsh_run_id": dsh_run_id or SETTLEMENT_BEGIN["root"]["dsh_run_id"],
        "binding_status": binding_status,
        "agent_run_id": None, "native_root_session_id": None,
        "stage_call_status": "settled", "stage_call_outcome": outcome or request["terminal_outcome"],
        "result_request_sha256": None, "result_receipt": None,
        "settlement_digest": receipt["settlement_digest"],
        "settlement_kind": request["settlement_kind"],
        "settlement_terminal_outcome": outcome or request["terminal_outcome"],
        "terminal_outcome": outcome or request["terminal_outcome"],
        "settlement_evidence": request["evidence"],
        "settlement_receipt": receipt,
        "cancellation_intent_receipt": request["evidence"]["cancellation_intent_receipt"],
        "root_status": terminal_state if closed else "active",
        "root_authority_status": "closed" if closed else "active",
        "terminal_sequence": terminal["sequence"] if closed else None,
        "terminal_event_sha256": terminal["event_sha256"] if closed else None,
        "terminal_acp_ingress_sequence": (1 if late_ingress else 0) if closed else None,
        "terminal_acp_ingress_sha256": ("c" * 64 if late_ingress else "a" * 64) if closed else None,
        "terminal_unknown_claim_count": unknown_claims if closed else None,
        "terminal_unknown_claims_sha256": "b" * 64 if closed else None,
    }


def test_settlement_digest_matches_backend_admission_and_request_hashes():
    request = settlement_request(
        TASK, SETTLEMENT_BEGIN, settlement_kind="never_dispatched",
        terminal_outcome="failed", durably_recorded_evidence=SETTLEMENT_EVIDENCE)
    admission = {
        "task_id": TASK, "owner_principal": "user_synthetic",
        "workspace_id": "workspace_synthetic", "actor_principal": SETTLEMENT_BEGIN["root"]["actor_principal"],
        "call_identity": SETTLEMENT_CALL, "attempt_binding": "1:strategy_draft:1",
        "root_run_id": ROOT, "runtime_boot_id": BOOT, "authority_epoch": 7,
        "dsh_run_id": SETTLEMENT_BEGIN["root"]["dsh_run_id"],
        "plan_version": 1, "stage": "strategy_draft", "iteration": 1, "call_index": 1,
    }
    backend_style = {
        "admission": admission,
        "request_sha256": "sha256:" + hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest(),
        "settlement_kind": request["settlement_kind"],
        "terminal_outcome": request["terminal_outcome"],
        "evidence": request["evidence"],
    }
    expected = "sha256:" + hashlib.sha256(
        json.dumps(backend_style, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    assert settlement_digest(SETTLEMENT_BEGIN, request) == expected


def test_lost_settlement_response_uses_exact_status_without_reposting():
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body))
        if url.endswith("/settle"):
            raise urllib.error.URLError("synthetic lost settlement response")
        return _settlement_status()

    receipt = submit_settlement_once(
        backend_url="http://backend", task_id=TASK, begin=SETTLEMENT_BEGIN,
        request=SETTLEMENT, headers={}, transport=post)
    assert receipt["settlement_digest"] == settlement_digest(SETTLEMENT_BEGIN, SETTLEMENT)
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["settle", "status"]


@pytest.mark.parametrize("tamper", ["digest", "owner", "root", "outcome"])
def test_wrong_settlement_identity_or_outcome_stays_unknown_without_repost(tamper):
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body))
        if url.endswith("/settle"):
            raise urllib.error.URLError("synthetic lost settlement response")
        if tamper == "digest":
            return _settlement_status(digest="sha256:" + "0" * 64)
        if tamper == "owner":
            return _settlement_status(owner="different_user")
        if tamper == "root":
            return _settlement_status(status_root="9" * 32)
        return _settlement_status(outcome="interrupted")

    with pytest.raises(AcpJudgmentOutcomeUnknown):
        submit_settlement_once(
            backend_url="http://backend", task_id=TASK, begin=SETTLEMENT_BEGIN,
            request=SETTLEMENT, headers={}, transport=post)
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["settle", "status"]


@pytest.mark.parametrize("scope", ["authority_epoch", "dsh_run_id", "binding_status"])
def test_settlement_readback_requires_exact_authority_and_agent_binding(scope):
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body))
        if url.endswith("/settle"):
            raise urllib.error.URLError("synthetic lost settlement response")
        if scope == "authority_epoch":
            return _settlement_status(authority_epoch=8)
        if scope == "dsh_run_id":
            return _settlement_status(dsh_run_id="byqjudg-" + "9" * 32)
        return _settlement_status(binding_status="invalid")

    with pytest.raises(AcpJudgmentOutcomeUnknown):
        submit_settlement_once(
            backend_url="http://backend", task_id=TASK, begin=SETTLEMENT_BEGIN,
            request=SETTLEMENT, headers={}, transport=post)
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["settle", "status"]


def test_lost_non_success_close_response_requires_exact_terminal_ack_without_repost():
    calls = []
    closed = False

    def post(url, body, headers, timeout):
        nonlocal closed
        calls.append((url, body))
        if url.endswith("/close"):
            assert body["outcome"] == "failed"
            closed = True
            raise urllib.error.URLError("synthetic lost close response")
        return _settlement_status(closed=closed)

    terminal = close_settled_root_once(
        backend_url="http://backend", task_id=TASK, begin=SETTLEMENT_BEGIN,
        settlement=SETTLEMENT, headers={}, transport=post)
    assert terminal["sequence"] == 2 and terminal["root_run_id"] == ROOT
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["status", "close", "status"]
    assert calls[1][1] == {
        "schema_version": "byq-runtime-root-close.v1", "boot_id": BOOT,
        "sequence": 2, "outcome": "failed", "event_sha256": terminal["event_sha256"],
    }


def test_missing_terminal_ack_or_unknown_claim_keeps_settlement_unacknowledged():
    calls = []
    closed = False

    def post(url, body, headers, timeout):
        nonlocal closed
        calls.append(url)
        if url.endswith("/close"):
            closed = True
            return {"receipt": "synthetic close response is not used as ACK"}
        return _settlement_status(closed=closed, unknown_claims=1)

    with pytest.raises(AcpJudgmentOutcomeUnknown, match="terminal ACK"):
        close_settled_root_once(
            backend_url="http://backend", task_id=TASK, begin=SETTLEMENT_BEGIN,
            settlement=SETTLEMENT, headers={}, transport=post)
    assert [url.rsplit("/", 1)[-1] for url in calls] == ["status", "close", "status"]


def test_late_ingress_after_never_dispatched_settlement_cannot_be_terminal_ack():
    calls = []
    closed = False

    def post(url, body, headers, timeout):
        nonlocal closed
        calls.append(url)
        if url.endswith("/close"):
            closed = True
            return {"receipt": "synthetic close response is not an ACK"}
        return _settlement_status(closed=closed, late_ingress=closed)

    with pytest.raises(AcpJudgmentOutcomeUnknown, match="terminal ACK"):
        close_settled_root_once(
            backend_url="http://backend", task_id=TASK, begin=SETTLEMENT_BEGIN,
            settlement=SETTLEMENT, headers={}, transport=post)
    assert [url.rsplit("/", 1)[-1] for url in calls] == ["status", "close", "status"]


def test_exact_already_closed_root_is_read_back_without_close_repost():
    calls = []

    def post(url, body, headers, timeout):
        calls.append(url)
        return _settlement_status(closed=True)

    terminal = close_settled_root_once(
        backend_url="http://backend", task_id=TASK, begin=SETTLEMENT_BEGIN,
        settlement=SETTLEMENT, headers={}, transport=post)
    assert terminal["sequence"] == 2 and terminal["root_run_id"] == ROOT
    assert [url.rsplit("/", 1)[-1] for url in calls] == ["status", "status"]
