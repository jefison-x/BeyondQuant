"""Independent BYQ backtest worker over durable queued jobs.

The worker receives a durable BYQ job identity.  It never receives strategy
source, provider credentials, a database socket, or DSH runtime state.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time

from app.backtest import BacktestJobStore, BacktestWorker, LocalObjectStore
from app.research import ResearchStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run queued BeyondQuant backtest jobs")
    parser.add_argument("--job-id", default=os.getenv("BYQ_BACKTEST_JOB_ID"))
    arguments = parser.parse_args()
    logging.basicConfig(level=os.getenv("BYQ_LOG_LEVEL", "INFO"))
    logger = logging.getLogger("byq.backtest.worker")
    jobs = BacktestJobStore.from_env()
    research = ResearchStore.from_env()
    worker = BacktestWorker(jobs, research, LocalObjectStore.from_env())
    running = True

    def stop(_number: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if arguments.job_id:
            result = worker.run_once(arguments.job_id)
            print(result["status"])
            return 0 if result["status"] in {"completed", "queued", "running"} else 1
        poll = max(0.1, float(os.getenv("BYQ_BACKTEST_POLL_SECONDS", "1")))
        while running:
            # The backtest engine has a bounded 300-second run. A longer stale
            # window avoids requeueing ordinary live work after worker restart.
            recovered = jobs.requeue_stale(older_than_seconds=900)
            if recovered:
                logger.warning("requeued %d stale backtest job(s)", recovered)
            job_id = jobs.next_queued_id()
            if job_id is None:
                time.sleep(poll)
                continue
            result = worker.run_once(job_id)
            logger.info("backtest job %s: %s", job_id, result["status"])
        return 0
    finally:
        research.close()
        jobs.close()


if __name__ == "__main__":
    raise SystemExit(main())
