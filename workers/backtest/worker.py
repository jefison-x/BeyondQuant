"""One-shot Phase 12 backtest worker entry point.

The worker receives a durable BYQ job identity.  It never receives strategy
source, provider credentials, a database socket, or DSH runtime state.
"""

from __future__ import annotations

import argparse
import os

from app.backtest import BacktestJobStore, BacktestWorker, LocalObjectStore
from app.research import ResearchStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one queued BeyondQuant backtest job")
    parser.add_argument("--job-id", default=os.getenv("BYQ_BACKTEST_JOB_ID"))
    arguments = parser.parse_args()
    if not arguments.job_id:
        parser.error("--job-id or BYQ_BACKTEST_JOB_ID is required")
    jobs = BacktestJobStore.from_env()
    research = ResearchStore.from_env()
    try:
        result = BacktestWorker(jobs, research, LocalObjectStore.from_env()).run_once(arguments.job_id)
        print(result["status"])
        return 0 if result["status"] in {"completed", "queued", "running"} else 1
    finally:
        research.close()
        jobs.close()


if __name__ == "__main__":
    raise SystemExit(main())
