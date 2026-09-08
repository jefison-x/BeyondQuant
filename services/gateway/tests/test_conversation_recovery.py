from app.conversation_recovery import project_recovery
import pytest

from packages.contracts.conversation_recovery import normalize_recovery
from packages.contracts.conversation_rehydration import rehydrated_prompt


def message(identity, content, at="2026-09-07T01:00:00Z", role="user", **extra):
    return {"message_id": identity, "content": content, "created_at": at, "role": role, **extra}


def events():
    return [
        {"session_id": "s1", "trace_id": "t1", "sequence": 10, "kind": "session.started",
         "timestamp": "2026-09-07T01:00:01Z", "payload": {"run_id": "run1"}},
        {"session_id": "s1", "trace_id": "t1", "sequence": 11, "kind": "session.failed",
         "timestamp": "2026-09-07T01:03:02Z", "payload": {"code": "runtime-subagent-timeout", "error": "private"}},
    ]


def test_recovers_original_unanswered_request_with_stable_public_identity():
    messages = [message("m1", "沪深300近三年周频双均线，凯利仓位")]
    _, recovery = project_recovery(messages, events(), "s1", "t1")
    assert recovery["status"] == "resolved"
    assert recovery["unanswered_turn"] == {"message_id": "m1", "content": messages[0]["content"]}
    assert recovery["failure"]["run_id"] == "run1"
    assert recovery["failure"]["sequence"] == 11
    assert "private" not in str(recovery)


def test_current_followup_already_persisted_after_failure_does_not_replace_subject():
    messages = [message("m1", "原始研究"), message("m2", "继续", "2026-09-07T01:04:00Z")]
    _, recovery = project_recovery(messages, events(), "s1", "t1")
    assert recovery["unanswered_turn"]["message_id"] == "m1"


def test_repeated_short_continuations_preserve_subject_but_distinct_topics_require_confirmation():
    messages = [message("m1", "原始研究"), message("m2", "继续"), message("m3", "原始研究")]
    assert project_recovery(messages, events(), "s1", "t1")[1]["unanswered_turn"]["message_id"] == "m1"
    messages.append(message("m4", "另一个不同研究"))
    recovery = project_recovery(messages, events(), "s1", "t1")[1]
    assert recovery["status"] == "needs_confirmation"
    assert recovery["unanswered_turn"] is None


def test_rejects_missing_identity_oversize_and_cross_session_evidence():
    for messages in [[message("m1", "x" * 6001)], [{"role": "user", "content": "subject"}]]:
        assert project_recovery(messages, events(), "s1", "t1")[1]["status"] == "needs_confirmation"
    assert project_recovery([message("m1", "subject")], events(), "other", "t1")[1] is None
    assert project_recovery([message("m1", "subject")], events(), "s1", "other")[1] is None


def test_partial_answer_from_failed_run_is_not_completed_history():
    messages = [message("m1", "原始研究"), message("m2", "部分答案", role="assistant", workflow_sequence=11)]
    completed, recovery = project_recovery(messages, events(), "s1", "t1")
    assert all(item["role"] != "assistant" for item in completed)
    assert recovery["unanswered_turn"]["message_id"] == "m1"


def test_prompt_separates_failure_and_current_input_and_deduplicates_retry():
    subject = "沪深300近三年周频双均线，凯利仓位"
    recovery = project_recovery([message("m1", subject)], events(), "s1", "t1")[1]
    prompt = rehydrated_prompt([], subject, recovery)
    assert prompt.count(subject) == 1
    assert "runtime-subagent-timeout" in prompt
    assert "同文重试" in prompt
    changed = rehydrated_prompt([], "改为研究中证500", recovery)
    assert "[CURRENT_USER_MESSAGE]\n改为研究中证500\n" in changed
    assert "当前用户明确的新指令优先" in changed


def test_ambiguous_continue_requires_confirmation_but_new_question_is_allowed():
    recovery = project_recovery([], events(), "s1", "t1")[1]
    with pytest.raises(ValueError, match="请明确"):
        rehydrated_prompt([], "继续", recovery)
    assert "新的明确问题" in rehydrated_prompt([], "新的明确问题", recovery)


@pytest.mark.parametrize("field,value", [("status", []), ("status", {}), ("code", []), ("code", {})])
def test_malformed_recovery_types_raise_validation_error(field, value):
    recovery = project_recovery([message("m1", "subject")], events(), "s1", "t1")[1]
    if field == "code":
        recovery["failure"][field] = value
    else:
        recovery[field] = value
    with pytest.raises(ValueError):
        normalize_recovery(recovery, "s1", "t1")


def test_recovery_rejects_cross_session_and_private_fields():
    recovery = project_recovery([message("m1", "subject")], events(), "s1", "t1")[1]
    with pytest.raises(ValueError):
        normalize_recovery(recovery, "s2", "t1")
    recovery["private_state"] = "forbidden"
    with pytest.raises(ValueError):
        normalize_recovery(recovery, "s1", "t1")
