"""Focused ADR-0097 exact result/terminal readback without a provider call."""

from __future__ import annotations

import urllib.error

import pytest

from app.research_judgment_acp_control import (
    AcpJudgmentOutcomeUnknown,
    close_result_root_once,
    result_request,
    result_request_sha256,
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
