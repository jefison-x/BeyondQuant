"""ADR-0084 session failure containment and business recovery contract.

Runs under ``unittest`` (the architecture lane has no pytest).
"""
from __future__ import annotations

import unittest

from packages.contracts import session_failure_containment as c

RUN_A = "a" * 32
RUN_B = "b" * 32


def _record(**overrides):
    value = {
        "schema_version": c.CONTAINMENT_VERSION,
        "conversation_id": "conversation_1",
        "session_id": "session-1",
        "trace_id": "trace-1",
        "owner_principal": "alice",
        "workspace_id": "workspace_alice",
        "loss_cause": "executor-loss",
        "interrupted_run_id": RUN_A,
        "interrupted_generation": "generation-1",
        "executor_epoch": 1,
        "attempt": 1,
        "preserved": {field: True for field in c.PRESERVED_FIELDS},
        "recorded_at": 1.0,
    }
    value.update(overrides)
    return value


def _classify(**overrides):
    facts = dict(cancelled=False, authorization_current=True, owner_matches=True,
                 workspace_matches=True, budget_available=True, success_receipt_present=False,
                 receipt_queryable=True, step_declared_idempotent=True,
                 step_result_verifiable=True, attempt_in_progress=False, attempts_used=0,
                 previous_run_id=RUN_A)
    facts.update(overrides)
    return c.classify_recovery(**facts)


class ContractTests(unittest.TestCase):
    def test_loss_causes_are_closed(self):
        for cause in c.LOSS_CAUSES:
            self.assertEqual(c.validate_loss_cause(cause), cause)
        for invalid in ("completed", None, 1):
            with self.assertRaises(ValueError):
                c.validate_loss_cause(invalid)

    def test_containment_record_requires_all_business_state_preserved(self):
        self.assertEqual(c.validate_containment_record(_record())["preserved"],
                         {field: True for field in c.PRESERVED_FIELDS})
        # A null conversation id is allowed at the adapter boundary; the Gateway
        # supplies the public conversation identity.
        self.assertIsNone(c.validate_containment_record(_record(conversation_id=None))["conversation_id"])
        broken = _record()
        broken["preserved"] = {**broken["preserved"], "audit_chain": False}
        for invalid in (broken, _record(loss_cause="completed"), _record(executor_epoch=0),
                        _record(interrupted_run_id="not-a-run")):
            with self.assertRaises(ValueError):
                c.validate_containment_record(invalid)

    def test_generation_fence_rejects_stale_writers(self):
        c.assert_fenced(authoritative_epoch=2, authoritative_generation="g2", authoritative_attempt=2,
                        write_epoch=2, write_generation="g2", write_attempt=2)
        for kwargs in (
            {"write_epoch": 1, "write_generation": "g2", "write_attempt": 2},
            {"write_epoch": 2, "write_generation": "g1", "write_attempt": 2},
            {"write_epoch": 2, "write_generation": "g2", "write_attempt": 1},
        ):
            with self.assertRaises(c.FencedWrite):
                c.assert_fenced(authoritative_epoch=2, authoritative_generation="g2",
                                authoritative_attempt=2, **kwargs)

    def test_terminal_settlement_rejects_duplicate_and_reopen(self):
        c.assert_terminal_settlement(settled={}, write_attempt=1, write_terminal="interrupted")
        c.assert_terminal_settlement(settled={1: "interrupted"}, write_attempt=2, write_terminal="completed")
        for kwargs in (
            {"settled": {1: "interrupted"}, "write_attempt": 1, "write_terminal": "interrupted"},
            {"settled": {1: "interrupted"}, "write_attempt": 1, "write_terminal": "completed"},
            {"settled": {3: "interrupted"}, "write_attempt": 2, "write_terminal": "interrupted"},
        ):
            with self.assertRaises(c.FencedWrite):
                c.assert_terminal_settlement(**kwargs)
        with self.assertRaises(ValueError):
            c.assert_terminal_settlement(settled={}, write_attempt=1, write_terminal="reattached")


class RecoveryClassificationTests(unittest.TestCase):
    def test_cancel_blocks_recovery_before_anything_else(self):
        decision = _classify(cancelled=True, success_receipt_present=True)
        self.assertEqual((decision.status, decision.reason), ("blocked", "cancelled"))

    def test_hard_invariants_block(self):
        for overrides, reason in (
            ({"owner_matches": False}, "owner_workspace_mismatch"),
            ({"workspace_matches": False}, "owner_workspace_mismatch"),
            ({"authorization_current": False}, "authorization_revoked"),
            ({"budget_available": False}, "budget_exhausted"),
        ):
            self.assertEqual(_classify(**overrides).reason, reason)

    def test_success_receipt_is_settled_never_replayed(self):
        decision = _classify(success_receipt_present=True)
        self.assertEqual((decision.status, decision.auto_retry), ("settled", False))

    def test_unknown_effects_pause_for_the_user(self):
        for overrides, reason in (
            ({"step_declared_idempotent": False}, "non_idempotent_step"),
            ({"step_result_verifiable": False, "receipt_queryable": True}, "receipt_absent"),
            ({"step_result_verifiable": False, "receipt_queryable": False}, "receipt_unknown"),
        ):
            decision = _classify(**overrides)
            self.assertEqual((decision.status, decision.reason), ("paused", reason))
            self.assertTrue(decision.requires_confirmation)
            self.assertFalse(decision.auto_retry)

    def test_eligible_only_for_declared_idempotent_result_verifiable(self):
        decision = _classify()
        self.assertEqual((decision.status, decision.auto_retry), ("eligible", True))
        self.assertEqual(decision.lineage, {"previous_run_id": RUN_A, "attempt": 1})

    def test_concurrent_attempt_blocks_and_exhaustion_is_bounded(self):
        self.assertEqual(_classify(attempt_in_progress=True).reason, "attempt_in_progress")
        exhausted = _classify(attempts_used=c.RECOVERY_ATTEMPT_MAX)
        self.assertEqual((exhausted.status, exhausted.reason), ("exhausted", "attempts_exhausted"))


class AttemptLedgerTests(unittest.TestCase):
    def test_attempt_ledger_is_gapless_chained_and_bounded(self):
        first = c.build_attempt(attempt=1, previous_run_id=RUN_A, new_run_id=RUN_B,
                                generation="g1", idempotency_key="original-key-1",
                                state="failed", created_at=1.0)
        second = c.build_attempt(attempt=2, previous_run_id=RUN_B, new_run_id="c" * 32,
                                 generation="g2", idempotency_key="original-key-1",
                                 state="in_progress", created_at=2.0)
        ledger = {"schema_version": c.ATTEMPTS_SCHEMA_VERSION, "session_id": "session-1",
                  "max_attempts": c.RECOVERY_ATTEMPT_MAX, "attempts": [first, second]}
        self.assertEqual(c.validate_attempt_ledger(ledger), ledger)
        self.assertTrue(c.ledger_has_open_attempt(ledger))
        for broken in (
            {**ledger, "attempts": [first, {**second, "previous_run_id": "d" * 32}]},
            {**ledger, "attempts": [{**second, "attempt": 3}]},
            {**ledger, "attempts": [{**first, "state": "in_progress"}, second]},
            {**ledger, "max_attempts": 99},
        ):
            with self.assertRaises(ValueError):
                c.validate_attempt_ledger(broken)

    def test_recovery_decision_view_is_closed(self):
        view = _classify().view()
        self.assertEqual(view["status"], "eligible")
        self.assertEqual(view["schema_version"], c.CONTAINMENT_VERSION)
        self.assertEqual(set(view), {"schema_version", "status", "reason", "auto_retry",
                                     "requires_confirmation", "lineage"})
        for invalid in (dict(status="completed", reason="cancelled"),
                        dict(status="eligible", reason="made_up_reason"),
                        dict(status="paused", reason="non_idempotent_step", auto_retry=True)):
            with self.assertRaises(ValueError):
                c.RecoveryDecision(**invalid)


if __name__ == "__main__":
    unittest.main()
