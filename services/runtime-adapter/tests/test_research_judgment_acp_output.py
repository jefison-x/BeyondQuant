"""One closed dedicated-root result from normalized ACP observations."""

from __future__ import annotations

import json

import pytest

from app.compat.types import RuntimeObservation
from app.research_judgment import ResearchJudgmentError
from app.research_judgment_acp_output import AcpJudgmentRootOutput


NATIVE = "00000000-0000-4000-8000-000000000001"


def _answer(text: str, *, session_id=NATIVE, root=True):
    return RuntimeObservation(kind="assistant.message", session_id=session_id,
                              root_session=root, runtime_activity=True,
                              message_id="message-1", answer_text=text)


def _start():
    return RuntimeObservation(kind="turn.start", session_id=NATIVE,
                              root_session=True, runtime_activity=True)


def _end(reason="completed"):
    return RuntimeObservation(kind="turn.end", session_id=NATIVE,
                              root_session=True, runtime_activity=True,
                              terminal_reason=reason)


def _proposal():
    return {"schema_version": "research-proposal.v1", "task_id": "task_" + "a" * 32,
            "plan_version": 1, "task_version": 1, "stage": "strategy_draft",
            "iteration": 1, "proposal_kind": "strategy_draft",
            "evidence_sufficient": True, "escalate": False,
            "summary": "bounded judgment"}


def test_one_completed_root_answer_returns_closed_validated_result():
    output = AcpJudgmentRootOutput(NATIVE)
    result = {"proposal": _proposal(), "durable_evidence": {"kind": "none"}}
    output.observe(_start())
    output.observe(_answer(json.dumps(result)))
    output.observe(_end())
    assert output.result("completed") == result


@pytest.mark.parametrize("text", [
    '{"proposal":null,"durable_evidence":{"kind":"none"}} trailing',
    '```json\n{"proposal":null,"durable_evidence":{"kind":"none"}}\n```',
    '{"proposal":null,"proposal":null,"durable_evidence":{"kind":"none"}}',
    '{"proposal":null,"durable_evidence":{"kind":"none"},"next_action":"execute"}',
    '{"proposal":null,"durable_evidence":{"kind":"artifact"}}',
    '{"proposal":{},"durable_evidence":{"kind":"none"}}',
    '{"proposal":NaN,"durable_evidence":{"kind":"none"}}',
])
def test_widened_or_non_exact_json_never_becomes_a_result(text):
    output = AcpJudgmentRootOutput(NATIVE)
    output.observe(_start())
    output.observe(_answer(text))
    output.observe(_end())
    with pytest.raises(ResearchJudgmentError):
        output.result("completed")


def test_cancel_unknown_or_missing_terminal_cannot_commit():
    for finish, terminal in (("cancelled", "cancelled"), ("failed", "failed"),
                             ("completed", None)):
        output = AcpJudgmentRootOutput(NATIVE)
        output.observe(_start())
        output.observe(_answer('{"proposal":null,"durable_evidence":{"kind":"none"}}'))
        if terminal is not None:
            output.observe(_end(terminal))
        with pytest.raises(ResearchJudgmentError, match="did not return a completed"):
            output.result(finish)


def test_second_answer_or_child_activity_fails_before_result():
    output = AcpJudgmentRootOutput(NATIVE)
    output.observe(_start())
    output.observe(_answer('{"proposal":null,"durable_evidence":{"kind":"none"}}'))
    with pytest.raises(ResearchJudgmentError, match="single complete root answer"):
        output.observe(_answer('{"proposal":null,"durable_evidence":{"kind":"none"}}'))
    with pytest.raises(ResearchJudgmentError, match="did not return a completed"):
        output.result("completed")
    child_output = AcpJudgmentRootOutput(NATIVE)
    child = RuntimeObservation(kind="private.activity", session_id="other-child",
                               root_session=False, runtime_activity=True)
    with pytest.raises(ResearchJudgmentError, match="foreign session"):
        child_output.observe(child)


def test_ignored_update_with_foreign_session_still_fails_closed():
    output = AcpJudgmentRootOutput(NATIVE)
    with pytest.raises(ResearchJudgmentError, match="foreign session"):
        output.observe(RuntimeObservation(kind="ignored", session_id="other-child"))


def test_duplicate_terminal_update_is_irrevocably_invalid():
    output = AcpJudgmentRootOutput(NATIVE)
    output.observe(_start())
    output.observe(_answer('{"proposal":null,"durable_evidence":{"kind":"none"}}'))
    output.observe(_end())
    with pytest.raises(ResearchJudgmentError, match="terminal update"):
        output.observe(_end())
    with pytest.raises(ResearchJudgmentError, match="did not return a completed"):
        output.result("completed")


def test_oversized_answer_is_rejected_before_json_parse():
    output = AcpJudgmentRootOutput(NATIVE)
    output.observe(_start())
    with pytest.raises(ResearchJudgmentError, match="text bound"):
        output.observe(_answer("x" * 25_000))


def test_answer_before_root_start_irrevocably_fails():
    output = AcpJudgmentRootOutput(NATIVE)
    with pytest.raises(ResearchJudgmentError, match="single complete root answer"):
        output.observe(_answer('{"proposal":null,"durable_evidence":{"kind":"none"}}'))
    with pytest.raises(ResearchJudgmentError, match="did not return a completed"):
        output.result("completed")
