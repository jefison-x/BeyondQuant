"""Arrival order must not decide which research request was answered."""
import unittest

from app.conversation_recovery import project_recovery


def event(sequence, kind, second, payload=None):
    return dict(session_id="s1", trace_id="t1", sequence=sequence, kind=kind,
                timestamp=f"2026-09-08T00:00:{second:02d}Z", payload=payload or {})


def message(identity, role, second, **extra):
    return dict(message_id=identity, role=role, content=identity,
                created_at=f"2026-09-08T00:00:{second:02d}Z", **extra)


class LateAnswerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.events = [event(1, "session.started", 2, {"run_id": "old"}),
                       event(2, "agent.output.delta", 3, {"delta": "old-answer"}),
                       event(3, "session.result", 4),
                       event(4, "session.started", 12, {"run_id": "new"}),
                       event(5, "session.failed", 15, {"code": "runtime-subagent-timeout"})]
        self.messages = [message("old-question", "user", 1),
                         message("new-question", "user", 10),
                         message("old-answer", "assistant", 13, workflow_sequence=2)]

    def recover(self):
        return project_recovery(self.messages, self.events, "s1", "t1")[1]

    def test_late_old_answer_does_not_close_new_question(self):
        result = self.recover()
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["unanswered_turn"]["message_id"], "new-question")

    def test_unanswered_question_is_not_injected_as_completed_history(self):
        history, _ = project_recovery(self.messages, self.events, "s1", "t1")
        self.assertEqual([m["message_id"] for m in history], ["old-question", "old-answer"])

    def test_unanchored_answer_cannot_create_false_completed_history(self):
        self.events.pop(1)
        history, _ = project_recovery(self.messages, self.events, "s1", "t1")
        self.assertEqual(history, [])

    def test_delivery_permutation_does_not_change_recovered_subject(self):
        self.messages[1], self.messages[2] = self.messages[2], self.messages[1]
        self.assertEqual(self.recover()["unanswered_turn"]["message_id"], "new-question")

    def test_missing_answer_trace_requires_confirmation(self):
        self.events.pop(1)
        self.assertEqual(self.recover()["status"], "needs_confirmation")

    def test_mismatched_answer_content_requires_confirmation(self):
        self.events[1]["payload"]["delta"] = "different answer"
        self.assertEqual(self.recover()["status"], "needs_confirmation")

    def test_failed_old_turn_is_not_proof_of_answered_question(self):
        self.events[2]["kind"] = "session.failed"
        self.assertEqual(self.recover()["status"], "needs_confirmation")

    def test_user_sent_after_old_start_is_not_closed_by_old_answer(self):
        self.messages[1]["created_at"] = "2026-09-08T00:00:02.500000Z"
        self.assertEqual(self.recover()["unanswered_turn"]["message_id"], "new-question")


if __name__ == "__main__":
    unittest.main()
