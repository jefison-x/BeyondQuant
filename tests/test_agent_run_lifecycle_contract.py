import unittest

from packages.contracts.agent_run_lifecycle import registration_fingerprint, validate_lifecycle_event


class AgentRunLifecycleContractTests(unittest.TestCase):
    """Use the repository's unittest runner so all contract cases execute."""

    def test_registration_digest_binds_every_trusted_identity_component(self):
        identity = ["alice", "workspace_alice", "agent", "trace", "session", "generation", "key"]
        expected = registration_fingerprint(*identity)
        self.assertEqual(len(expected), 64)
        self.assertEqual(expected, registration_fingerprint(*[" " + item + " " for item in identity]))
        for index in range(len(identity)):
            with self.subTest(index=index):
                changed = identity.copy()
                changed[index] += "-other"
                self.assertNotEqual(registration_fingerprint(*changed), expected)

    def test_lifecycle_event_rejects_ambiguous_or_expanded_contract(self):
        for change in [
            {"root_run_id": "session-instead-of-root"}, {"sequence": True}, {"sequence": 0},
            {"outcome": "queued"}, {"outcome": []}, {"owner_principal": "model-supplied-owner"},
            {"registration_fingerprint": "a" * 64}, {"schema_version": "unknown"},
        ]:
            with self.subTest(change=change):
                event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
                         "sequence": 2, "outcome": "failed", **change}
                with self.assertRaises(ValueError):
                    validate_lifecycle_event(event)

    def test_registration_and_terminal_evidence_remain_separate(self):
        event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
                 "sequence": 1, "outcome": "active"}
        with self.assertRaises(ValueError):
            validate_lifecycle_event(event)
        bound = {**event, "registration_fingerprint": "b" * 64}
        self.assertEqual(validate_lifecycle_event(bound), bound)
        terminal = {**event, "sequence": 2, "outcome": "failed"}
        self.assertEqual(validate_lifecycle_event(terminal), terminal)


if __name__ == "__main__":
    unittest.main()
