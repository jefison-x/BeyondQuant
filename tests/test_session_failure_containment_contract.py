"""ADR-0084 session failure containment and business recovery contract.

Runs under ``unittest`` (the architecture lane has no pytest).
"""
from __future__ import annotations

import unittest

from packages.contracts import session_failure_containment as c

RUN_A = "a" * 32


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
        "boundary_invariant": c.BOUNDARY_INVARIANT,
        "recorded_at": 1.0,
    }
    value.update(overrides)
    return value


def _classify(**overrides):
    facts = dict(cancelled=False, authorization_current=True, owner_matches=True,
                 workspace_matches=True, budget_available=True, success_receipt_present=False,
                 receipt_queryable=True, step_declared_idempotent=True,
                 step_result_verifiable=True, previous_run_id=RUN_A)
    facts.update(overrides)
    return c.classify_recovery(**facts)


class ContractTests(unittest.TestCase):
    def test_loss_causes_are_closed(self):
        for cause in c.LOSS_CAUSES:
            self.assertEqual(c.validate_loss_cause(cause), cause)
        for invalid in ("completed", None, 1):
            with self.assertRaises(ValueError):
                c.validate_loss_cause(invalid)

    def test_containment_record_carries_the_boundary_assertion_not_business_evidence(self):
        record = c.validate_containment_record(_record())
        self.assertEqual(record["boundary_invariant"], c.BOUNDARY_INVARIANT)
        self.assertNotIn("preserved", record)
        self.assertIsNone(c.validate_containment_record(_record(conversation_id=None))["conversation_id"])
        for invalid in (_record(loss_cause="completed"), _record(executor_epoch=0),
                        _record(interrupted_run_id="not-a-run"),
                        _record(boundary_invariant="self-verified")):
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


class PreservationTests(unittest.TestCase):
    def _projection(self, **overrides):
        states = {field: "unknown" for field in c.PRESERVED_FIELDS}
        value = {
            "schema_version": c.PRESERVATION_SCHEMA_VERSION,
            "states": states,
            "boundary_invariant": c.BOUNDARY_INVARIANT,
            "boundary_verified": False,
            "sources": {"boundary": "execution-boundary-assertion"},
        }
        value.update(overrides)
        return value

    def test_preservation_requires_a_source_for_a_preserved_field(self):
        value = self._projection()
        value["states"] = {**value["states"], "conversation": "preserved"}
        with self.assertRaises(ValueError):
            c.validate_preservation(value)

    def test_boundary_invariant_cannot_be_self_verified(self):
        value = self._projection()
        value["boundary_verified"] = True
        with self.assertRaises(ValueError):
            c.validate_preservation(value)

    def test_preservation_accepts_a_sourced_projection(self):
        value = self._projection()
        value["states"] = {**value["states"], "conversation": "preserved"}
        value["sources"] = {**value["sources"], "conversation": "backend-product-catalog"}
        self.assertEqual(c.validate_preservation(value), value)


class RecoveryClassificationTests(unittest.TestCase):
    def test_cancel_blocks_recovery_before_anything_else(self):
        decision = _classify(cancelled=True, success_receipt_present=True)
        self.assertEqual((decision.status, decision.reason), ("blocked", "cancelled"))

    def test_authoritative_denials_block(self):
        for overrides, reason in (
            ({"owner_matches": False}, "owner_workspace_mismatch"),
            ({"workspace_matches": False}, "owner_workspace_mismatch"),
            ({"authorization_current": False}, "authorization_revoked"),
            ({"budget_available": False}, "budget_exhausted"),
        ):
            self.assertEqual(_classify(**overrides).reason, reason)

    def test_unverifiable_authority_pauses_and_is_never_allowed(self):
        for field in ("owner_matches", "workspace_matches", "authorization_current", "budget_available"):
            decision = _classify(**{field: None})
            self.assertEqual((decision.status, decision.reason), ("paused", "authority_unavailable"))
            self.assertTrue(decision.requires_confirmation)
            self.assertFalse(decision.auto_retry)

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

    def test_eligible_only_for_verified_authority_and_declared_safe_step(self):
        decision = _classify()
        self.assertEqual((decision.status, decision.auto_retry), ("eligible", True))
        self.assertEqual(decision.lineage, {"previous_run_id": RUN_A})

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
