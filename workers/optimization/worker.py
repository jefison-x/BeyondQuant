"""Independent poller for durable completed-candidate parameter-search Jobs."""

from __future__ import annotations

import logging
import os
import signal
import time
import threading

from app.backtest import LocalObjectStore
from app.optimization_job import OptimizationJobStore, OptimizationWorker
from app.research import ResearchStore


def main() -> int:
    logging.basicConfig(level=os.getenv("BYQ_LOG_LEVEL", "INFO"))
    logger = logging.getLogger("byq.optimization.worker")
    jobs = OptimizationJobStore.from_env()
    research = ResearchStore.from_env()
    objects = LocalObjectStore.from_env()
    worker = OptimizationWorker(jobs, research, objects)
    stopping = False

    def stop(_number: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    poll_seconds = max(0.1, float(os.getenv("BYQ_OPTIMIZATION_POLL_SECONDS", "1")))
    try:
        while not stopping:
            if worker.run_once():
                logger.info("completed-candidate comparison turn processed")
                continue
            time.sleep(poll_seconds)
        return 0
    finally:
        research.close()
        jobs.close()


if __name__ == "__main__":
    raise SystemExit(main())
