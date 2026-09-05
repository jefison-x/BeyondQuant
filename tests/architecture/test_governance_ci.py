import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/ci" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class GovernanceCiTests(unittest.TestCase):
    def test_removed_inline_ddl_still_selects_integration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "services/backend/app/store.py"
            source.parent.mkdir(parents=True)
            source.write_text("# DDL removed in this revision\n")
            git = folder / "git"
            git.write_text('#!/bin/bash\nprintf "CREATE TABLE former_table (id TEXT);\\n"\n')
            git.chmod(0o755)
            result = subprocess.run([str(ROOT / "scripts/ci/classify-changes.sh")], cwd=folder,
                input="services/backend/app/store.py\n", capture_output=True, text=True, check=True,
                env={**os.environ, "PATH": f"{folder}:{os.environ['PATH']}", "BYQ_CI_DIFF_BASE": "old-revision"})
            self.assertIn("integration=yes", result.stdout)

    def test_cleanup_failure_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            docker = folder / "docker"
            docker.write_text('''#!/bin/bash
case "$*" in
  info) test "$FAKE_DAEMON" = available;;
  "ps "*) exit 0;;
  "volume inspect byq-ci-postgres-cleanup-contract") exit 0;;
  *) exit 1;;
esac
''')
            docker.chmod(0o755)
            for mode in ("unavailable", "available"):
                with self.subTest(mode=mode):
                    result = subprocess.run([str(ROOT / "scripts/ci/cleanup-resources.sh"),
                        "--scope=cleanup-contract", "--verify-only"], capture_output=True, text=True,
                        env={**os.environ, "PATH": f"{folder}:{os.environ['PATH']}", "FAKE_DAEMON": mode})
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("cleanup verification failed", result.stderr)

    def test_image_build_failure_never_runs_old_image(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            docker = folder / "docker"
            calls = folder / "calls"
            docker.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$FAKE_CALLS"\n'
                              'case "$*" in *" build "*) exit 19;; esac\nexit 0\n')
            docker.chmod(0o755)
            command = '''source scripts/ci/local-ci.sh
NO_CLEANUP=1
ONLY=runtime
acquire_heavy_capacity() { return 0; }
if ! build_test_images; then exit 1; fi
check_runtime
'''
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "PATH": f"{folder}:{os.environ['PATH']}", "FAKE_CALLS": str(calls), "BYQ_CI_SCOPE": "fake-image-contract"})
            self.assertEqual(result.returncode, 1)
            self.assertIn("build runtime-adapter", calls.read_text())
            self.assertNotIn("run --rm", calls.read_text())
            self.assertNotIn("beyondquant-runtime-adapter", calls.read_text())

    def test_build_and_tests_share_scope_and_environment_is_test_only(self):
        command = '''source scripts/ci/local-ci.sh
prepare_ci_compose_env
test "$(ci_image runtime-adapter)" = "byq-ci-stack-fake-env-contract-runtime-adapter"
test "$COMPOSE_FILE" = "$REPO_ROOT/compose.yml"
test "$COMPOSE_DISABLE_ENV_FILE" = 1
test "$BYQ_POSTGRES_VOLUME_EXTERNAL" = false
test "$BYQ_DATABASE_URL" = postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain
test -z "$DEEPSEEK_API_KEY$TUSHARE_TOKEN$BYQ_FEEDBACK_GITHUB_TOKEN$BYQ_FEEDBACK_HUB_URL"
'''
        result = subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, "BYQ_CI_SCOPE": "fake-env-contract", "BYQ_DATABASE_URL": "PRODUCTION",
                 "DEEPSEEK_API_KEY": "private", "TUSHARE_TOKEN": "private",
                 "BYQ_FEEDBACK_GITHUB_TOKEN": "private", "BYQ_FEEDBACK_HUB_URL": "https://production.invalid",
                 "COMPOSE_FILE": "production.yml", "BYQ_POSTGRES_VOLUME_EXTERNAL": "true"})
        self.assertEqual(result.returncode, 0, result.stderr)
        source = (ROOT / "scripts/ci/local-ci.sh").read_text()
        for service in ("backend", "gateway", "runtime-adapter", "mcp"):
            self.assertIn(f'"$(ci_image {service})"', source)
            self.assertNotIn(f"beyondquant-{service}", source)
        self.assertIn("--no-build --wait", source)

    def test_merge_preflight_fails_closed(self):
        evaluate = module("check-github-gates").evaluate
        repo = {"allow_auto_merge": True, "allow_squash_merge": True}
        protection = {"required_status_checks": {"strict": True, "contexts": ["local-ci", "ci-gate"]}}
        self.assertTrue(evaluate(repo, None))
        self.assertTrue(evaluate({**repo, "allow_auto_merge": False}, protection))
        self.assertTrue(evaluate(repo, {"required_status_checks": {"strict": False}}))
        checks = [{"name": name, "status": "COMPLETED", "conclusion": "SUCCESS"} for name in ("local-ci", "ci-gate")]
        pr = {"baseRefName": "main", "mergeable": "MERGEABLE", "statusCheckRollup": checks}
        self.assertEqual(evaluate(repo, protection, pr), [])
        extended = {"required_status_checks": {"strict": True, "contexts": ["local-ci", "ci-gate", "security"]}}
        self.assertTrue(evaluate(repo, extended, pr))
        review = {**protection, "required_pull_request_reviews": {"required_approving_review_count": 1}}
        self.assertTrue(evaluate(repo, review, pr))
        self.assertEqual(evaluate(repo, review, {**pr, "reviewDecision": "APPROVED"}), [])
        for result in ("SKIPPED", "NEUTRAL", "FAILURE", "CANCELLED"):
            with self.subTest(result=result):
                checks[0]["conclusion"] = result
                self.assertTrue(evaluate(repo, protection, pr))

    def test_log_redaction_retains_failure_but_removes_secrets(self):
        redact = module("redact-log").redact
        raw = 'FAILED test_login Authorization: Bearer abc123 password="very secret" https://user:pass@host/path sk-abcdefghijklmnop known-secret-value'
        clean = redact(raw, ("known-secret-value",))
        self.assertIn("FAILED test_login", clean)
        for secret in ("abc123", "very secret", "user:pass", "abcdefghijklmnop", "known-secret-value"):
            self.assertNotIn(secret, clean)
        output = subprocess.check_output(["python3", str(ROOT / "scripts/ci/redact-log.py")],
            input="-----BEGIN RSA PRIVATE KEY-----\nprivatebytes\n-----END RSA PRIVATE KEY-----\nAssertionError\n", text=True)
        self.assertNotIn("privatebytes", output)
        self.assertIn("AssertionError", output)

    def test_fork_routing_and_non_skippable_aggregate_gate(self):
        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        self.assertIn('head.repo.full_name != github.repository && \'["ubuntu-latest"]\'', workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("needs: [local-ci]", workflow)
        self.assertIn('test "$CI_RESULT" = success', workflow)
        self.assertIn("python3 scripts/ci/redact-log.py | tee", workflow)
        self.assertIn("actions/upload-artifact@", workflow)

    def test_worktree_verifier_rejects_primary_unregistered_and_symlink_escape(self):
        verify = module("verify-worktree").verify
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            repo = parent / "repo"
            root = parent / "worktrees"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=CI", "-c", "user.email=ci@example.invalid", "commit", "-qm", "initial", "--allow-empty"], check=True)
            tree = root / "feature"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-qb", "test-feature", str(tree)], check=True)
            verify(tree, root)
            with self.assertRaises(ValueError):
                verify(repo, parent)
            with self.assertRaises(ValueError):
                verify(tree / ".git", root)
            escape = root / "escape"
            escape.symlink_to(repo, target_is_directory=True)
            with self.assertRaises(ValueError):
                verify(escape, root)

    def test_current_phase_comes_from_status_not_frozen_test_literal(self):
        import re
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        plan = (ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md").read_text()
        matches = re.findall(r"<!-- byq:current-completed-phase=(\d+) -->", status)
        self.assertEqual(len(matches), 1)
        self.assertRegex(plan, rf"Phase {matches[0]} .*COMPLETE")


if __name__ == "__main__":
    unittest.main()
