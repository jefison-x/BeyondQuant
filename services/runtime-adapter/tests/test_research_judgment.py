"""ADR-0085 P3 runtime-adapter invocation of one bounded judgment turn.

The adapter is the concrete trusted caller: it admits a bounded model call, runs
the DSH turn INSIDE the dedicated bounded judgment persona, and submits the
CLOSED model result to the atomic server-side result operation. No model,
provider or production database is used here.
"""
from __future__ import annotations

import urllib.error

import pytest

from app import research_judgment as judgment


def _recording_transport(responses):
    calls = []

    def transport(url, payload, headers, timeout):
        calls.append({"url": url, "payload": payload, "headers": headers})
        if not responses:
            raise AssertionError("unexpected extra transport call")
        return responses.pop(0)

    return transport, calls


def test_admit_then_submit_the_closed_result_inside_the_bounded_persona():
    transport, calls = _recording_transport([
        {"call_identity": "turn-a", "call_index": 1, "model_call_limit": 2,
         "stage": "backtest_analysis", "stage_input": {"stage": "backtest_analysis"}},
        {"schema_version": "research-judgment-result-receipt.v1", "progress": {"continue": False},
         "proposal": {"stage": "iteration_comparison"}},
    ])
    headers = {"x-byq-owner-principal": "owner", "x-byq-actor-principal": "owner",
               "x-byq-workspace-id": "ws"}
    seen: list[tuple] = []

    def turn_runner(admission, persona_tool):
        seen.append((admission["call_identity"], persona_tool))
        return {"proposal": {"summary": "bounded"}, "durable_evidence": {"kind": "none"}}

    receipt = judgment.run_bounded_research_judgment(
        backend_url="http://backend:8000", task_id="task_" + "a" * 32, trusted_headers=headers,
        call_identity="turn-a", transport=transport, turn_runner=turn_runner)
    assert receipt["proposal"]["stage"] == "iteration_comparison"
    assert seen == [("turn-a", judgment.RESEARCH_JUDGMENT_PERSONA_TOOL)]
    assert calls[0]["url"].endswith("/internal/research-judgment/task_" + "a" * 32 + "/admit")
    assert calls[0]["payload"] == {"call_identity": "turn-a"}
    assert calls[1]["url"].endswith("/internal/research-judgment/task_" + "a" * 32 + "/result")
    assert calls[1]["payload"] == {"call_identity": "turn-a",
                                   "durable_evidence": {"kind": "none"},
                                   "proposal": {"summary": "bounded"}}


def test_submit_defaults_to_no_progress_and_requires_a_closed_result():
    transport, calls = _recording_transport([{"ok": True}])
    judgment.submit_research_judgment_result(
        backend_url="http://backend", task_id="task_" + "b" * 32, trusted_headers={},
        call_identity="turn-b", model_result={}, transport=transport)
    assert calls[0]["payload"]["durable_evidence"] == {"kind": "none"}
    for invalid in ("not-an-object", {"next_action": "execute"}, {"unknown": 1},
                    {"proposal": "not-an-object"}):
        with pytest.raises(judgment.ResearchJudgmentError):
            judgment.submit_research_judgment_result(
                backend_url="http://backend", task_id="task_" + "b" * 32, trusted_headers={},
                call_identity="turn-b", model_result=invalid, transport=transport)


def test_backend_rejection_and_unavailability_fail_closed():
    def rejecting(url, payload, headers, timeout):
        raise urllib.error.HTTPError(url, 409, "conflict", {}, None)

    with pytest.raises(judgment.ResearchJudgmentError):
        judgment.admit_research_judgment_turn(
            backend_url="http://backend", task_id="task_" + "c" * 32, trusted_headers={},
            call_identity="turn-c", transport=rejecting)

    def unavailable(url, payload, headers, timeout):
        raise urllib.error.URLError("down")

    with pytest.raises(judgment.ResearchJudgmentError):
        judgment.submit_research_judgment_result(
            backend_url="http://backend", task_id="task_" + "c" * 32, trusted_headers={},
            call_identity="turn-c", model_result={}, transport=unavailable)


def test_persona_binding_is_the_enforcement_channel_not_a_header():
    assert judgment.RESEARCH_JUDGMENT_PERSONA_TOOL == "byq_research_judgment_turn"
    source = open(judgment.__file__, encoding="utf-8").read()
    # No client-optional header or generic write route is used.
    assert "x-byq-research-judgment-stage" not in source
    for forbidden in ("/v1/research/tasks", "continuation-events", "execution-plan"):
        assert forbidden not in source


def test_read_only_mcp_endpoint_is_dedicated_and_fails_closed():
    # A dedicated read-only endpoint is accepted.
    assert judgment.resolve_read_only_mcp_endpoint({
        "BYQ_MCP_READ_ONLY_URL": "http://mcp-readonly:8301/mcp/v1",
        "BYQ_MCP_READ_ONLY_TOKEN": "read-only-token",
        "BYQ_MCP_URL": "http://mcp:8300/mcp/v1",
        "BYQ_MCP_TOKEN": "product-token",
    }) == {"url": "http://mcp-readonly:8301/mcp/v1", "token": "read-only-token"}

    # Missing URL/token fails closed (never silently falls back to the Product MCP).
    for missing in (
        {},
        {"BYQ_MCP_READ_ONLY_TOKEN": "read-only-token"},
        {"BYQ_MCP_READ_ONLY_URL": "http://mcp-readonly:8301/mcp/v1"},
        {"BYQ_MCP_READ_ONLY_URL": "  ", "BYQ_MCP_READ_ONLY_TOKEN": "x"},
    ):
        with pytest.raises(judgment.ResearchJudgmentError):
            judgment.resolve_read_only_mcp_endpoint(missing)

    # A collision with the Product endpoint or credential fails closed.
    for collision in (
        {"BYQ_MCP_READ_ONLY_URL": "http://mcp:8300/mcp/v1",
         "BYQ_MCP_READ_ONLY_TOKEN": "read-only-token", "BYQ_MCP_URL": "http://mcp:8300/mcp/v1"},
        {"BYQ_MCP_READ_ONLY_URL": "http://mcp-readonly:8301/mcp/v1",
         "BYQ_MCP_READ_ONLY_TOKEN": "product-token", "BYQ_MCP_TOKEN": "product-token"},
    ):
        with pytest.raises(judgment.ResearchJudgmentError):
            judgment.resolve_read_only_mcp_endpoint(collision)


def test_completed_admission_replays_without_running_the_model():
    transport, calls = _recording_transport([{
        "call_identity": "turn-a", "status": "completed", "created": False,
        "receipt": {"schema_version": "research-judgment-result-receipt.v1",
                    "call_identity": "turn-a", "progress": {"continue": False}}}])
    seen: list = []

    def turn_runner(admission, persona_tool):
        seen.append(admission)
        return {"proposal": {}}

    receipt = judgment.run_bounded_research_judgment(
        backend_url="http://backend:8000", task_id="task_" + "a" * 32, trusted_headers={},
        call_identity="turn-a", transport=transport, turn_runner=turn_runner)
    assert receipt["replayed"] is True and receipt["model_turn_skipped"] is True
    assert seen == []
    assert len(calls) == 1


def test_in_flight_admission_does_not_terminate_the_live_turn():
    # A duplicate request for an already-admitted attempt must fail closed with an
    # explicit in-progress and write NOTHING (it must not fence the live turn to
    # needs_attention, and it must not run a model turn).
    transport, calls = _recording_transport([
        {"call_identity": "turn-a", "status": "admitted", "created": False,
         "call_index": 1, "stage_input": {}}])
    seen: list = []

    def turn_runner(admission, persona_tool):
        seen.append(admission)
        return {"proposal": {}}

    with pytest.raises(judgment.ResearchJudgmentInProgress):
        judgment.run_bounded_research_judgment(
            backend_url="http://backend:8000", task_id="task_" + "a" * 32, trusted_headers={},
            call_identity="turn-a", transport=transport, turn_runner=turn_runner)
    assert seen == []
    assert len(calls) == 1  # admit only; no result write


def test_concurrent_duplicate_cannot_preempt_the_original_turn():
    # First owner admits and is still running; a second owner's duplicate request
    # gets an in-progress and writes nothing. The original owner then commits its
    # real proposal; the duplicate never replaced it with a no-progress fence.
    class Transport:
        def __init__(self):
            self.payloads = []
            self.admitted = False

        def __call__(self, url, payload, headers, timeout):
            self.payloads.append({"url": url, "payload": payload})
            if url.endswith("/admit"):
                if not self.admitted:
                    self.admitted = True
                    return {"call_identity": "turn-a", "status": "admitted",
                            "created": True, "call_index": 1, "stage_input": {}}
                return {"call_identity": "turn-a", "status": "admitted", "created": False,
                        "call_index": 1, "stage_input": {}}
            return {"schema_version": "research-judgment-result-receipt.v1",
                    "progress": {"outcome": "advance"}, "proposal": {"summary": "real"}}

    transport = Transport()

    def turn_runner(admission, persona_tool):
        # Simulate a concurrent duplicate arriving while the original turn runs.
        with pytest.raises(judgment.ResearchJudgmentInProgress):
            judgment.run_bounded_research_judgment(
                backend_url="http://backend:8000", task_id="task_" + "a" * 32,
                trusted_headers={}, call_identity="turn-a", transport=transport,
                turn_runner=lambda *_: {"proposal": {}})
        return {"proposal": {"summary": "real"}}

    receipt = judgment.run_bounded_research_judgment(
        backend_url="http://backend:8000", task_id="task_" + "a" * 32, trusted_headers={},
        call_identity="turn-a", transport=transport, turn_runner=turn_runner)
    assert receipt["proposal"]["summary"] == "real"
    result_writes = [p for p in transport.payloads if p["url"].endswith("/result")]
    assert len(result_writes) == 1
    assert result_writes[0]["payload"]["proposal"]["summary"] == "real"
    assert result_writes[0]["payload"]["durable_evidence"] == {"kind": "none"}


def test_attempt_binding_is_sent_to_admit():
    transport, calls = _recording_transport([
        {"call_identity": "turn-a", "status": "admitted", "created": True,
         "call_index": 1, "stage_input": {"stage": "backtest_analysis"}},
        {"ok": True}])
    judgment.run_bounded_research_judgment(
        backend_url="http://backend:8000", task_id="task_" + "a" * 32, trusted_headers={},
        call_identity="turn-a", attempt="3:backtest_analysis:1", transport=transport,
        turn_runner=lambda admission, tool: {"proposal": {}})
    assert calls[0]["payload"] == {"call_identity": "turn-a",
                                   "attempt_binding": "3:backtest_analysis:1"}
