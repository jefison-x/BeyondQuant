"""Behaviour and negative tests for the bounded CI status watcher.

The negative cases below encode the CI-A review defects: run-id prefix
collisions and foreign/malformed URLs must not be treated as the requested run;
an expired or superseded run attempt must never inherit the latest rollup; a
``gh`` timeout/OSError must fail closed through the structured retry path; and
``--once`` must be truly single-shot while the wall-time budget is a real bound.
A rerun reuses the same run id, so the authoritative attempt status and
attempt-specific job identity must gate the verdict too: a running or failed
attempt, a stale attempt's jobs, or an attempt/head change during the read can
never inherit an old green.
"""
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def module(name: str):
    spec = importlib.util.spec_from_file_location("byq_watch_ci", ROOT / "scripts/ci" / "watch-ci.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


watch = module("watch-ci")

REPO = "jefison-x/BeyondQuant"
HEAD = "c0ba46d57b51649c79f83c53eb11ffb3b0688d9d"
RUN = "35476417481"
RUN_URL = f"https://github.com/{REPO}/actions/runs/{RUN}/job/1"


def check(name, status, conclusion="", details_url=None):
    payload = {"name": name, "status": status, "conclusion": conclusion}
    if details_url:
        payload["detailsUrl"] = details_url
    return payload


def rollup(url=RUN_URL, head=HEAD):
    return {
        "headRefOid": head,
        "statusCheckRollup": [
            check("local-ci", "COMPLETED", "SUCCESS", url),
            check("ci-gate", "COMPLETED", "SUCCESS", url),
        ],
    }


def run_facts(attempt=1, head=HEAD, name="BeyondQuant CI", repo=REPO, run_id=RUN):
    return {
        "id": int(run_id),
        "run_attempt": int(attempt),
        "run_number": 465,
        "head_sha": head,
        "name": name,
        "status": "in_progress",
        "conclusion": None,
        "repository": {"full_name": repo},
    }


def job_url(job_id, run_id=RUN):
    return f"https://github.com/{REPO}/actions/runs/{run_id}/job/{job_id}"


def green_checks(job_ids=(11, 12)):
    return [check("local-ci", "COMPLETED", "SUCCESS", job_url(job_ids[0])),
            check("ci-gate", "COMPLETED", "SUCCESS", job_url(job_ids[1]))]


def attempt_facts(status="completed", conclusion="success", attempt=2, head=HEAD,
                  jobs=((21, "local-ci"), (22, "ci-gate"))):
    return {
        "id": int(RUN),
        "run_attempt": int(attempt),
        "run_number": 465,
        "head_sha": head,
        "name": "BeyondQuant CI",
        "status": status,
        "conclusion": conclusion,
        "repository": {"full_name": REPO},
        "jobs": [{"id": job_id, "name": name, "status": "completed",
                  "conclusion": "success", "head_sha": head} for job_id, name in jobs],
    }


ALL_PASS = [check("local-ci", "COMPLETED", "SUCCESS"), check("ci-gate", "COMPLETED", "SUCCESS")]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class EvaluateTests(unittest.TestCase):
    def test_pass_requires_success(self):
        self.assertEqual(watch.evaluate("a" * 40, "a" * 40, ALL_PASS)["result"], "PASS")

    def test_skipped_is_not_success(self):
        result = watch.evaluate("a" * 40, "a" * 40,
                                [check("local-ci", "COMPLETED", "SKIPPED"),
                                 check("ci-gate", "COMPLETED", "SUCCESS")])
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("local-ci", result["failed"])

    def test_failure_reported_before_pending(self):
        result = watch.evaluate("a" * 40, "a" * 40,
                                [check("backend", "COMPLETED", "FAILURE"),
                                 check("local-ci", "IN_PROGRESS")])
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["failed"], ["backend"])

    def test_missing_required_is_blocked_not_pass(self):
        result = watch.evaluate("a" * 40, "a" * 40, [check("backend", "COMPLETED", "SUCCESS")])
        self.assertEqual(result["result"], "BLOCKED")

    def test_no_checks_is_blocked(self):
        self.assertEqual(watch.evaluate("a" * 40, "a" * 40, [])["result"], "BLOCKED")

    def test_stale_head_is_not_pass(self):
        self.assertEqual(watch.evaluate("b" * 40, "a" * 40, ALL_PASS)["result"], "STALE")

    def test_run_binding_without_matching_checks_is_blocked(self):
        result = watch.evaluate("a" * 40, "a" * 40,
                                [{"name": "local-ci", "status": "COMPLETED", "conclusion": "SUCCESS",
                                  "detailsUrl": "https://github.com/o/r/actions/runs/111/job/1"}],
                                run_id="222")
        self.assertEqual(result["result"], "BLOCKED")


class RunBindingTests(unittest.TestCase):
    """Defect 1: run ids must match as complete numeric path segments and repo."""

    def _checks(self, url):
        return [check("local-ci", "COMPLETED", "SUCCESS", url),
                check("ci-gate", "COMPLETED", "SUCCESS", url)]

    def test_exact_run_and_repo_is_accepted(self):
        result = watch.evaluate(HEAD, HEAD, self._checks(RUN_URL), run_id=RUN, repo=REPO)
        self.assertEqual(result["result"], "PASS")

    def test_run_id_prefix_collision_is_not_a_match(self):
        collision = f"https://github.com/{REPO}/actions/runs/12345/job/9"
        result = watch.evaluate(HEAD, HEAD, self._checks(collision), run_id="123", repo=REPO)
        self.assertEqual(result["result"], "BLOCKED")

    def test_wrong_repository_is_not_a_match(self):
        foreign = f"https://github.com/attacker/BeyondQuant/actions/runs/{RUN}/job/1"
        result = watch.evaluate(HEAD, HEAD, self._checks(foreign), run_id=RUN, repo=REPO)
        self.assertEqual(result["result"], "BLOCKED")

    def test_malformed_urls_are_not_a_match(self):
        malformed = (
            f"https://evil.example/redirect?target=/runs/{RUN}",
            f"https://github.com/{REPO}/actions/runs/{RUN}abc/job/1",
            f"https://github.com/{REPO}/pull/{RUN}/files",
        )
        for url in malformed:
            with self.subTest(url=url):
                result = watch.evaluate(HEAD, HEAD, self._checks(url), run_id=RUN, repo=REPO)
                self.assertEqual(result["result"], "BLOCKED")


class RunAttemptVerificationTests(unittest.TestCase):
    """Defect 2: --run-attempt must bind authoritative run/attempt facts."""

    def test_current_attempt_is_verified(self):
        facts = watch.verify_run_attempt(REPO, RUN, "1", HEAD,
                                         read=lambda _args: run_facts(attempt=1))
        self.assertEqual(facts["run_attempt"], "1")
        self.assertEqual(facts["head_sha"], HEAD)

    def test_expired_attempt_is_structured_failure(self):
        def read(_args):
            raise watch.ApiError("gh: Not Found (HTTP 404)", False)
        with self.assertRaises(watch.ApiError):
            watch.verify_run_attempt(REPO, RUN, "1", HEAD, read=read)

    def test_superseded_attempt_is_rejected(self):
        def read(args):
            return run_facts(attempt=1) if "/attempts/" in " ".join(args) else run_facts(attempt=2)
        with self.assertRaises(watch.ApiError):
            watch.verify_run_attempt(REPO, RUN, "1", HEAD, read=read)

    def test_head_mismatch_is_rejected(self):
        with self.assertRaises(watch.ApiError):
            watch.verify_run_attempt(REPO, RUN, "1", HEAD,
                                     read=lambda _args: run_facts(attempt=1, head="b" * 40))

    def test_repo_mismatch_is_rejected(self):
        with self.assertRaises(watch.ApiError):
            watch.verify_run_attempt(REPO, RUN, "1", HEAD,
                                     read=lambda _args: run_facts(attempt=1, repo="attacker/BeyondQuant"))

    def test_missing_workflow_is_rejected(self):
        with self.assertRaises(watch.ApiError):
            watch.verify_run_attempt(REPO, RUN, "1", HEAD,
                                     read=lambda _args: run_facts(attempt=1, name=""))

    def test_superseded_attempt_does_not_inherit_latest_rollup(self):
        def fake_gh(args, timeout=None):
            joined = " ".join(args)
            if "/attempts/" in joined:
                return run_facts(attempt=1)
            if "/actions/runs/" in joined:
                return run_facts(attempt=2)
            return rollup()

        fetch = watch.fetch_pr(REPO, 326, RUN, run_attempt="1", expected_head=HEAD)
        with mock.patch.object(watch, "_gh_json", side_effect=fake_gh):
            code, final = watch.run_watch(fetch, HEAD, once=True, emit=lambda _: None)
        self.assertEqual(code, 3)
        self.assertEqual(final["result"], "BLOCKED")


class AttemptStatusTests(unittest.TestCase):
    """A rerun reuses the same run id, so the attempt number alone is not proof
    that the rollup belongs to the running attempt: the authoritative attempt
    status and attempt-specific job identity must gate the verdict."""

    def _watch_once(self, observation):
        return watch.run_watch(lambda _remaining=None: observation, HEAD, once=True,
                               emit=lambda _: None)

    def test_running_attempt_with_old_green_is_not_pass(self):
        observation = {"head": HEAD, "checks": green_checks((1, 1)), "run_id": RUN,
                       "run_attempt": "2",
                       "run": attempt_facts(status="in_progress", conclusion=None, attempt=2,
                                            jobs=((21, "local-ci"), (22, "ci-gate")))}
        code, final = self._watch_once(observation)
        self.assertNotEqual(code, 0)
        self.assertNotEqual(final["result"], "PASS")
        self.assertEqual(final["result"], "PENDING")

    def test_failed_attempt_with_old_green_is_not_pass(self):
        observation = {"head": HEAD, "checks": green_checks((1, 1)), "run_id": RUN,
                       "run_attempt": "2",
                       "run": attempt_facts(status="completed", conclusion="failure", attempt=2,
                                            jobs=((21, "local-ci"), (22, "ci-gate")))}
        code, final = self._watch_once(observation)
        self.assertNotEqual(code, 0)
        self.assertNotEqual(final["result"], "PASS")
        self.assertEqual(final["result"], "FAIL")

    def test_stale_attempt_jobs_with_old_green_are_blocked(self):
        # Attempt 2 is completed+success but the rollup still carries attempt 1
        # job ids, so check identity cannot be proven and the green is not PASS.
        observation = {"head": HEAD, "checks": green_checks((1, 2)), "run_id": RUN,
                       "run_attempt": "2",
                       "run": attempt_facts(attempt=2, jobs=((21, "local-ci"), (22, "ci-gate")))}
        code, final = self._watch_once(observation)
        self.assertNotEqual(final["result"], "PASS")
        self.assertEqual(final["result"], "BLOCKED")

    def test_attempt_change_during_read_does_not_inherit_old_green(self):
        # verify_run_attempt sees attempt 2, the rollup is old green, and the
        # post-read shows attempt 3: the read must fail closed.
        latest = {"n": 0}

        def fake_gh(args, timeout=None):
            joined = " ".join(args)
            if "/jobs" in joined:
                return {"jobs": [
                    {"id": 31, "name": "local-ci", "status": "in_progress",
                     "conclusion": None, "head_sha": HEAD},
                    {"id": 32, "name": "ci-gate", "status": "in_progress",
                     "conclusion": None, "head_sha": HEAD},
                ]}
            if "/attempts/" in joined:
                return run_facts(attempt=2)
            if "/actions/runs/" in joined:
                latest["n"] += 1
                return run_facts(attempt=2 if latest["n"] == 1 else 3)
            return rollup()

        fetch = watch.fetch_pr(REPO, 326, RUN, run_attempt="2", expected_head=HEAD)
        with mock.patch.object(watch, "_gh_json", side_effect=fake_gh):
            code, final = watch.run_watch(fetch, HEAD, once=True, emit=lambda _: None)
        self.assertNotEqual(final["result"], "PASS")
        self.assertEqual(final["result"], "BLOCKED")
        self.assertEqual(code, 3)

    def test_current_attempt_success_still_passes(self):
        observation = {"head": HEAD, "checks": green_checks((21, 22)), "run_id": RUN,
                       "run_attempt": "2",
                       "run": attempt_facts(attempt=2, jobs=((21, "local-ci"), (22, "ci-gate")))}
        code, final = self._watch_once(observation)
        self.assertEqual(final["result"], "PASS")
        self.assertEqual(code, 0)


class GhJsonFailureTests(unittest.TestCase):
    """Defect 3: subprocess timeout/OSError must become structured ApiError."""

    def test_timeout_becomes_retryable_api_error(self):
        with mock.patch.object(watch.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("gh", 60)):
            with self.assertRaises(watch.ApiError) as caught:
                watch._gh_json(["pr", "view", "1"])
        self.assertTrue(caught.exception.retryable)

    def test_oserror_becomes_retryable_api_error(self):
        with mock.patch.object(watch.subprocess, "run", side_effect=OSError("no gh binary")):
            with self.assertRaises(watch.ApiError) as caught:
                watch._gh_json(["pr", "view", "1"])
        self.assertTrue(caught.exception.retryable)

    def test_timeout_backs_off_then_fails_closed(self):
        clock = FakeClock()
        sleeps = []

        def fetch(_remaining=None):
            raise watch.ApiError("gh read timed out after 60s", True)

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock.now += seconds

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=100, max_api_retries=2,
                                      emit=lambda _: None, clock=clock, sleep=fake_sleep)
        self.assertEqual(code, 3)
        self.assertEqual(final["result"], "BLOCKED")
        self.assertEqual(sleeps, [5, 10])


class RetryTests(unittest.TestCase):
    def test_403_is_permanent_and_not_pass(self):
        def fetch(_remaining=None):
            raise watch.ApiError("HTTP 403: Forbidden", watch.is_retryable("HTTP 403: Forbidden"))

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=100, emit=lambda _: None)
        self.assertEqual(code, 3)
        self.assertEqual(final["result"], "BLOCKED")

    def test_unknown_required_never_passes(self):
        code, final = watch.run_watch(lambda _remaining=None: {"head": "a" * 40, "checks": []},
                                      "a" * 40, budget_seconds=1, once=True, emit=lambda _: None)
        self.assertEqual(code, 3)
        self.assertEqual(final["result"], "BLOCKED")

    def test_retryable_failure_backs_off_then_succeeds(self):
        calls = {"n": 0}
        recorded = []
        clock = FakeClock()

        def fake_sleep(seconds):
            recorded.append(seconds)
            clock.now += seconds

        def fetch(_remaining=None):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise watch.ApiError("HTTP 503 service unavailable", True)
            return {"head": "a" * 40, "checks": ALL_PASS}

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=100,
                                      emit=lambda _: None, clock=clock, sleep=fake_sleep)
        self.assertEqual(code, 0)
        self.assertEqual(final["result"], "PASS")
        self.assertEqual(recorded, [5, 10])
        self.assertEqual(calls["n"], 3)

    def test_backoff_is_finite(self):
        self.assertEqual(watch.backoff_delay(1, 5, 60), 5)
        self.assertEqual(watch.backoff_delay(4, 5, 60), 40)
        self.assertEqual(watch.backoff_delay(10, 5, 60), 60)

    def test_is_retryable_classification(self):
        self.assertTrue(watch.is_retryable("HTTP 429 rate limit"))
        self.assertTrue(watch.is_retryable("HTTP 502 bad gateway"))
        self.assertTrue(watch.is_retryable("request timed out"))
        self.assertFalse(watch.is_retryable("HTTP 403: Forbidden"))


class BoundedWatchTests(unittest.TestCase):
    def test_budget_exhaustion_returns_pending_without_spinning(self):
        clock = FakeClock()
        calls = {"n": 0}

        def fetch(_remaining=None):
            calls["n"] += 1
            return {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]}

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=25, interval=20,
                                      emit=lambda _: None, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 2)
        self.assertEqual(final["result"], "PENDING")
        self.assertLessEqual(calls["n"], 4)

    def test_once_never_sleeps(self):
        clock = FakeClock()
        code, _ = watch.run_watch(
            lambda _remaining=None: {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]},
            "a" * 40, budget_seconds=25, once=True,
            emit=lambda _: None, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 2)
        self.assertEqual(clock.now, 0)

    def test_once_does_not_retry_or_sleep_on_retryable_error(self):
        clock = FakeClock()
        sleeps = []

        def fetch(_remaining=None):
            raise watch.ApiError("HTTP 503 service unavailable", True)

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock.now += seconds

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=100, once=True,
                                      emit=lambda _: None, clock=clock, sleep=fake_sleep)
        self.assertEqual(code, 3)
        self.assertEqual(final["result"], "BLOCKED")
        self.assertEqual(sleeps, [])
        self.assertEqual(clock.now, 0)

    def test_total_time_is_measured_and_bounded(self):
        clock = FakeClock()
        observed = []

        def fetch(remaining=None):
            observed.append(remaining)
            clock.now += min(remaining or 0.0, 10)
            return {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]}

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=25, interval=20,
                                      emit=lambda _: None, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 2)
        self.assertLessEqual(final["elapsed_seconds"], 25.0)
        self.assertAlmostEqual(final["elapsed_seconds"], clock.now)

    def test_fetch_timeout_is_clamped_to_remaining(self):
        captured = {}

        def fake_gh(args, timeout=None):
            captured["timeout"] = timeout
            return {"headRefOid": "a" * 40, "statusCheckRollup": []}

        with mock.patch.object(watch, "_gh_json", side_effect=fake_gh):
            fetch = watch.fetch_pr(REPO, 326, None)
            fetch(3.0)
            self.assertGreater(captured["timeout"], 0)
            self.assertLessEqual(captured["timeout"], 3.0)
            fetch(None)
            self.assertEqual(captured["timeout"], watch.FETCH_TIMEOUT_SECONDS)

    def test_emits_only_on_state_change(self):
        states = [
            {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]},
            {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]},
            {"head": "a" * 40, "checks": ALL_PASS},
        ]
        clock = FakeClock()
        lines = []
        cursor = {"n": 0}

        def fetch(_remaining=None):
            state = states[min(cursor["n"], len(states) - 1)]
            cursor["n"] += 1
            return state

        code, _ = watch.run_watch(fetch, "a" * 40, budget_seconds=50, interval=1,
                                  emit=lines.append, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 0)
        payloads = [json.loads(line) for line in lines]
        self.assertEqual([payload["result"] for payload in payloads], ["PENDING", "PASS"])


if __name__ == "__main__":
    unittest.main()
