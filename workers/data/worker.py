"""Trusted Data Plane worker for daily calendar and full-market snapshots."""

from __future__ import annotations

import os
import signal
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.credentials import CredentialStore
from app.market_automation import MarketAutomationStore, run_scheduler_cycle, sync_declared_inputs
from app.market_data import MarketDataStore
from app.market_readiness import MarketReadinessStore
from app.provider_runtime import resolved_tushare_provider
from app.security_master import SecurityMasterStore


def main() -> int:
    worker_id = os.environ.get("BYQ_DATA_WORKER_ID", "data-worker-1").strip() or "data-worker-1"
    poll_seconds = max(1.0, float(os.environ.get("BYQ_DATA_POLL_SECONDS", "10")))
    credentials = CredentialStore.from_env()
    automation = MarketAutomationStore.from_env()
    market = MarketDataStore.from_env()
    readiness = MarketReadinessStore.from_env()
    securities = SecurityMasterStore.from_env()
    running = True

    def provider_factory():
        return resolved_tushare_provider(credentials)[0]

    def stop(_number: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    automation.recover_stale_jobs()
    automation.heartbeat(worker_id)
    next_scheduler_at = 0.0

    try:
        while running:
            repair = automation.claim_data_repair()
            if repair is not None:
                try:
                    provider = provider_factory()
                    cursor = datetime.strptime(str(repair["start_date"]), "%Y%m%d")
                    end = datetime.strptime(str(repair["end_date"]), "%Y%m%d")
                    while cursor <= end:
                        chunk_end = min(end, cursor + timedelta(days=400))
                        automation.refresh_calendar(
                            provider, start_date=cursor.strftime("%Y%m%d"),
                            end_date=chunk_end.strftime("%Y%m%d"),
                        )
                        cursor = chunk_end + timedelta(days=1)
                    sync_declared_inputs(
                        dict(repair["requirement_json"]), provider=provider,
                        readiness_store=readiness,
                    )
                    assessment = readiness.assess(dict(repair["requirement_json"]))
                    automation.enqueue_dates(
                        list(assessment["missing_trade_dates"]), scheduled_by=str(repair["requested_by"]),
                    )
                    automation.complete_data_repair(str(repair["request_id"]))
                except Exception as error:
                    automation.complete_data_repair(str(repair["request_id"]), error=type(error).__name__)
                continue
            command = automation.claim_run_request()
            force = command is not None
            if force or time.monotonic() >= next_scheduler_at:
                try:
                    created = run_scheduler_cycle(
                        automation,
                        provider_factory=provider_factory,
                        worker_id=worker_id,
                        force=force,
                    )
                    next_scheduler_at = time.monotonic() + 60
                    if command is not None:
                        automation.complete_run_request(command["request_id"], result=created)
                    local_date = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
                    config = automation.get_config()
                    if created and config["security_master_enabled"]:
                        security_job, _ = securities.create_sync_job(
                            {"idempotency_key": f"auto-security-master-{local_date}"},
                            actor="data-worker",
                        )
                        if security_job["status"] == "queued":
                            securities.run_sync_job(security_job["job_id"], provider_factory=provider_factory)
                except Exception as error:  # worker boundary records safe class-only diagnostics
                    message = type(error).__name__
                    next_scheduler_at = time.monotonic() + 300
                    automation.heartbeat(worker_id, last_error=message)
                    if command is not None:
                        automation.complete_run_request(command["request_id"], error=message)

            job = automation.claim_next_job(worker_id=worker_id)
            if job is not None:
                try:
                    provider = provider_factory()
                except Exception as error:
                    result = automation.fail_job(job["job_id"], error)
                else:
                    result = automation.execute_job(
                        job, provider=provider, market_store=market, readiness_store=readiness,
                    )
                automation.heartbeat(
                    worker_id,
                    last_job_id=str(result["job_id"]),
                    last_error=None if result["status"] == "completed" else str(result.get("error_code")),
                )
                continue
            automation.heartbeat(worker_id)
            time.sleep(poll_seconds)
    finally:
        readiness.close()
        securities.close()
        market.close()
        automation.close()
        credentials.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
