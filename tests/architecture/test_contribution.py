import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("contribution", ROOT / "scripts/ci/check-contribution.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
HEAD = "a" * 40
DIGEST = "b" * 64


class ContributionTests(unittest.TestCase):
    def setUp(self):
        self.pr = {"number": 1, "state": "open", "base": {"ref": "main", "repo": {"full_name": policy.REPOSITORY}},
                   "head": {"sha": HEAD}, "user": {"login": "contributor", "type": "User"}}
        self.commits = [{"author": self.pr["user"], "commit": {"message": "original change"}}]
        self.comments = [{"user": self.pr["user"], "body": policy.acceptance(1, HEAD, DIGEST)}]
        self.reviews = [{"user": {"login": policy.MAINTAINER}, "state": "APPROVED",
                         "commit_id": HEAD, "submitted_at": "2026-09-05T00:00:00Z"}]

    def evaluate(self):
        return policy.evaluate(self.pr, self.commits, self.comments, self.reviews, DIGEST, HEAD)

    def test_exact_head_and_base_agreement_with_review_pass(self):
        self.assertEqual(self.evaluate(), [])

    def test_checkbox_body_and_other_account_are_not_acceptance(self):
        for body in ("[x] CLA accepted", policy.acceptance(1, "c" * 40, DIGEST),
                     policy.acceptance(1, HEAD, "c" * 64), policy.acceptance(2, HEAD, DIGEST)):
            self.comments[0]["body"] = body
            self.assertTrue(self.evaluate())
        self.comments[0] = {"user": {"login": "someone-else", "type": "User"}, "body": policy.acceptance(1, HEAD, DIGEST)}
        self.assertTrue(self.evaluate())

    def test_owner_pr_needs_no_self_signature_but_not_forged_git_author(self):
        self.pr["user"] = {"login": policy.MAINTAINER, "type": "User"}
        self.commits[0]["author"] = self.pr["user"]
        self.comments = []
        self.reviews = []
        self.assertEqual(self.evaluate(), [])
        self.pr["user"] = {"login": "outsider", "type": "User"}
        self.assertTrue(self.evaluate())

    def test_missing_unmapped_bot_and_coauthored_commits_fail_closed(self):
        for author in (None, {"login": "robot", "type": "Bot"}):
            self.commits[0]["author"] = author
            self.assertTrue(self.evaluate())
        self.commits[0]["author"] = self.pr["user"]
        self.commits[0]["commit"]["message"] += "\nCo-authored-by: Unverified <test@example.invalid>"
        self.assertTrue(self.evaluate())
        self.commits = []
        self.assertTrue(self.evaluate())

    def test_review_required_on_current_head_and_latest_decision(self):
        self.reviews[0]["commit_id"] = "c" * 40
        self.assertTrue(self.evaluate())
        self.reviews[0]["commit_id"] = HEAD
        rejected = copy.deepcopy(self.reviews[0])
        rejected.update(state="CHANGES_REQUESTED", submitted_at="2026-09-05T01:00:00Z")
        self.reviews.append(rejected)
        self.assertTrue(self.evaluate())

    def test_closed_wrong_repository_or_stale_revision_fails(self):
        self.pr["state"] = "closed"
        self.assertTrue(self.evaluate())
        self.pr["state"] = "open"
        self.pr["head"]["sha"] = "c" * 40
        self.assertTrue(self.evaluate())
        self.pr["head"]["sha"] = HEAD
        self.pr["base"]["repo"]["full_name"] = "someone/fork"
        self.assertTrue(self.evaluate())

    def test_third_party_commits_need_their_own_acceptance(self):
        self.commits.append({"author": {"login": "coauthor", "type": "User"}, "commit": {"message": "second change"}})
        self.assertTrue(self.evaluate())
        self.comments.append({"user": {"login": "coauthor", "type": "User"}, "body": policy.acceptance(1, HEAD, DIGEST)})
        self.assertEqual(self.evaluate(), [])

    def test_bot_cannot_accept_on_behalf_of_individual(self):
        self.comments[0]["user"] = {"login": "contributor", "type": "Bot"}
        self.assertTrue(self.evaluate())
