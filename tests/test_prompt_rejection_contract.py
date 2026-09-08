import unittest

from packages.contracts.prompt_rejection import credential_rejection, matches_credential_rejection


class PromptRejectionContractTests(unittest.TestCase):
    def test_exact_identity_without_content_or_credentials(self):
        receipt = credential_rejection("runtime-one", "message-original", "synthetic prompt")
        self.assertTrue(matches_credential_rejection(receipt, "runtime-one", "message-original", "synthetic prompt"))
        self.assertNotIn("synthetic prompt", str(receipt))
        for changed in ({"accepted": 0}, {"accepted": True}, {"session_id": "runtime-two"},
                        {"idempotency_key": "message-other"}, {"extra": True},
                        {"content_sha256": "0" * 64}, {"code": "unavailable"}):
            with self.subTest(changed=changed):
                self.assertFalse(matches_credential_rejection({**receipt, **changed},
                    "runtime-one", "message-original", "synthetic prompt"))

    def test_missing_or_ambiguous_identity_never_becomes_a_known_rejection(self):
        for session, key, content in [("", "message-original", "text"), ("a/b", "message-original", "text"),
                                      ("runtime", None, "text"), ("runtime", "short", "text"),
                                      ("runtime", "message-original", None)]:
            with self.subTest(session=session, key=key):
                self.assertFalse(matches_credential_rejection({}, session, key, content))


if __name__ == "__main__":
    unittest.main()
