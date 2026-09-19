"""Behaviour and negative tests for the bounded CI status watcher."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name: str):
    spec = importlib.util.spec_from_file_location("byq_watch_ci", ROOT / "scripts/ci" / "watch-ci.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


watch = module("watch-ci")


def check(name, status, conclusion=""):
    return {"name": name, "status": status, "conclusion": conclusion}


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


class RetryTests(unittest.TestCase):
    def test_403_is_permanent_and_not_pass(self):
        def fetch():
            raise watch.ApiError("HTTP 403: Forbidden", watch.is_retryable("HTTP 403: Forbidden"))

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=100, emit=lambda _: None)
        self.assertEqual(code, 3)
        self.assertEqual(final["result"], "BLOCKED")

    def test_unknown_required_never_passes(self):
        code, final = watch.run_watch(lambda: {"head": "a" * 40, "checks": []}, "a" * 40,
                                      budget_seconds=1, once=True, emit=lambda _: None)
        self.assertEqual(code, 3)
        self.assertEqual(final["result"], "BLOCKED")

    def test_retryable_failure_backs_off_then_succeeds(self):
        calls = {"n": 0}
        recorded = []
        clock = FakeClock()

        def fake_sleep(seconds):
            recorded.append(seconds)
            clock.now += seconds

        def fetch():
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

        def fetch():
            calls["n"] += 1
            return {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]}

        code, final = watch.run_watch(fetch, "a" * 40, budget_seconds=25, interval=20,
                                      emit=lambda _: None, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 2)
        self.assertEqual(final["result"], "PENDING")
        self.assertLessEqual(calls["n"], 4)

    def test_once_never_sleeps(self):
        clock = FakeClock()
        code, _ = watch.run_watch(lambda: {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]},
                                  "a" * 40, budget_seconds=25, once=True,
                                  emit=lambda _: None, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 2)
        self.assertEqual(clock.now, 0)

    def test_emits_only_on_state_change(self):
        states = [
            {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]},
            {"head": "a" * 40, "checks": [check("local-ci", "IN_PROGRESS")]},
            {"head": "a" * 40, "checks": ALL_PASS},
        ]
        clock = FakeClock()
        lines = []
        cursor = {"n": 0}

        def fetch():
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
