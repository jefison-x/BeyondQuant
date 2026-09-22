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
