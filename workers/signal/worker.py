"""Trusted signal coordinator: PostgreSQL jobs in, secret-free sandbox JSON out."""

from __future__ import annotations

import json
import os
import signal
import time
import urllib.error
import urllib.request

from app.research import ResearchStore
from app.market_readiness import MarketReadinessStore
from app.signal_producer import SignalJobStore, SignalProducerCoordinator, promote_waiting_signal_jobs


class SandboxFailure(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = code


class HttpSandboxExecutor:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    def execute(self, payload: dict[str, object], *, timeout_seconds: float) -> dict[str, object]:
        body = json.dumps(
            {**payload, "timeout_seconds": timeout_seconds},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/v1/execute", data=body, headers={"content-type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds + 3.0) as response:
                result = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SandboxFailure("sandbox_unavailable", "signal sandbox is unavailable") from error
        if not isinstance(result, dict):
            raise SandboxFailure("invalid_output", "signal sandbox returned an invalid response")
        if result.get("ok") is not True:
            code = result.get("error_code", "execution_failed")
            detail = result.get("error_detail", "strategy execution failed")
            raise SandboxFailure(str(code), str(detail))
        result.pop("ok", None)
        return result


def main() -> int:
    jobs = SignalJobStore.from_env()
    research = ResearchStore.from_env()
    readiness = MarketReadinessStore.from_env()
    coordinator = SignalProducerCoordinator(
        jobs,
        research,
        HttpSandboxExecutor(os.environ.get("BYQ_SIGNAL_SANDBOX_URL", "http://signal-sandbox:8500")),
    )
    poll = max(0.1, float(os.environ.get("BYQ_SIGNAL_POLL_SECONDS", "1")))
    running = True

    def stop(_number: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            promote_waiting_signal_jobs(jobs, readiness)
            if coordinator.run_next() is None:
                time.sleep(poll)
    finally:
        readiness.close()
        research.close()
        jobs.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
