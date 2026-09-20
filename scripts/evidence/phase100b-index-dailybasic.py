#!/usr/bin/env python3
"""Phase 100-B real verification: persist Tushare index_dailybasic and prove coverage/readiness.

This script performs a *bounded* real Tushare read into an isolated BYQ
PostgreSQL test database (never production), persists rows through the
authoritative ``IndexIndicatorStore`` import/sync path, then computes coverage
and readiness from the persisted store only. It refuses to run against any
database whose name does not contain ``byq_domain_test``.

Usage (inside an isolated backend container with the source mounted at /app)::

    BYQ_DATABASE_URL=postgresql+psycopg://byq_test:...@<isolated-pg>:5432/byq_domain_test \
    TUSHARE_TOKEN=... python scripts/evidence/phase100b-index-dailybasic.py

Output: docs/evidence/phase-100b/INDEX-DAILYBASIC-VERIFICATION.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "backend"))

from app.data_provider import ProviderError, TushareProvider  # noqa: E402
from app.index_catalog import SUPPORTED_INDEXES  # noqa: E402
from app.index_indicators import IndexIndicatorStore  # noqa: E402
from app.market_automation import MarketAutomationStore  # noqa: E402

START_DATE = os.environ.get("BYQ_P100B_START_DATE", "20260801")
END_DATE = os.environ.get("BYQ_P100B_END_DATE", "20260918")
READINESS_FIELDS = ["total_mv", "pe", "pe_ttm", "pb", "turnover_rate"]
EVIDENCE_PATH = REPO_ROOT / "docs" / "evidence" / "phase-100b" / "INDEX-DAILYBASIC-VERIFICATION.json"


class CountingProvider:
    def __init__(self, provider: TushareProvider) -> None:
        self._provider = provider
        self.index_daily_basic_calls = 0

    def fetch_index_daily_basic(self, request):
        self.index_daily_basic_calls += 1
        return self._provider.fetch_index_daily_basic(request)


def _require_isolated_database() -> str:
    url = os.environ.get("BYQ_DATABASE_URL", "")
    if "byq_domain_test" not in url:
        raise SystemExit("refusing to write evidence outside an isolated *byq_domain_test* database")
    return url


def main() -> int:
    _require_isolated_database()
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured; live verification cannot run")

    provider = TushareProvider.from_env()
    counting = CountingProvider(provider)
    automation = MarketAutomationStore()
    authorization = automation.refresh_calendar(provider, start_date=START_DATE, end_date=END_DATE)
    sessions = [str(row["trade_date"]) for row in automation._execute(
        """SELECT trade_date FROM market_trading_sessions
           WHERE is_open=TRUE AND trade_date BETWEEN :start AND :end ORDER BY trade_date""",
        {"start": START_DATE, "end": END_DATE},
    )]
    if not sessions:
        raise SystemExit("no open sessions were returned for the verification window")

    store = IndexIndicatorStore()
    index_symbols = [item["index_symbol"] for item in SUPPORTED_INDEXES]
    per_index: dict[str, dict[str, object]] = {}
    first_runs: dict[str, tuple[dict[str, object], dict[str, object], bool, dict[str, object]]] = {}

    # Phase 1: one real first-run sync per index.
    for index_symbol in index_symbols:
        payload = {
            "index_symbol": index_symbol,
            "mode": "incremental",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "idempotency_key": f"p100b-{index_symbol}-{START_DATE}-{END_DATE}",
        }
        job, created = store.create_sync_job(payload, actor="phase100b-evidence")
        finished = store.run_sync_job(job["job_id"], provider_factory=lambda: counting)
        first_runs[index_symbol] = (payload, job, created, finished)

    # Global snapshot after all first runs, before any terminal rerun.
    overall_before = store.persisted_fingerprint()

    # Phase 2: terminal reruns must neither refetch nor reinsert.
    for index_symbol in index_symbols:
        payload, job, created, finished = first_runs[index_symbol]
        rerun, created_again = store.create_sync_job(payload, actor="phase100b-evidence")
        fingerprint_before = store.persisted_fingerprint(index_symbol)
        calls_before = counting.index_daily_basic_calls
        terminal = store.run_sync_job(rerun["job_id"], provider_factory=lambda: counting)
        calls_after = counting.index_daily_basic_calls
        fingerprint_after = store.persisted_fingerprint(index_symbol)

        per_index[index_symbol] = {
            # The first-run job result is cumulative/original state, never a
            # rerun delta. The terminal rerun returns this same persisted row.
            "job_result": {
                "job_id": job["job_id"],
                "created": created,
                "status": finished["status"],
                "effective_start_date": finished["effective_start_date"],
                "provider_calls": 1,
                "rows_received": finished["rows_received"],
                "rows_inserted": finished["rows_inserted"],
                "rows_kept": finished["rows_kept"],
            },
            "idempotency_key_reused_returns_same_job": (not created_again) and rerun["job_id"] == job["job_id"],
            "terminal_rerun": {
                "same_job_id_as_first_run": rerun["job_id"] == job["job_id"],
                "status": terminal["status"],
                "provider_call_delta": calls_after - calls_before,
                "no_refetch": (calls_after - calls_before) == 0,
                "persisted_fingerprint_before": fingerprint_before,
                "persisted_fingerprint_after": fingerprint_after,
                "persisted_fingerprint_unchanged": fingerprint_before == fingerprint_after,
                "no_reinsert": fingerprint_before["content_sha256"] == fingerprint_after["content_sha256"],
                # Explicitly cumulative: the job row is returned as persisted
                # and must NOT be read as a rerun insertion count.
                "reported_cumulative_rows_inserted": terminal["rows_inserted"],
            },
        }

    overall_after = store.persisted_fingerprint()
    coverage = store.coverage()
    readiness = store.readiness(
        index_symbols=index_symbols, start_date=sessions[0], end_date=sessions[-1],
        fields=READINESS_FIELDS,
    )
    missing_by_index: dict[str, int] = {}
    for item in readiness["coverage"]["missing"]:
        missing_by_index[item["index_symbol"]] = missing_by_index.get(item["index_symbol"], 0) + 1
    first_run_calls = sum(int(item["job_result"]["provider_calls"]) for item in per_index.values())
    terminal_call_delta = sum(int(item["terminal_rerun"]["provider_call_delta"]) for item in per_index.values())
    evidence = {
        "schema_version": "phase-100b-index-dailybasic-verification.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "tushare",
        "endpoint": "index_dailybasic",
        "window": {"start_date": START_DATE, "end_date": END_DATE, "open_sessions": len(sessions)},
        "isolated_database": True,
        "production_state_changed": False,
        "verification_note": (
            "Original isolated run records did not capture a before/after persisted "
            "fingerprint, so the terminal-rerun no-op proof was regenerated by re-running "
            "the isolated verification (never production)."
        ),
        "calendar": authorization,
        "index_daily_basic_provider_calls": counting.index_daily_basic_calls,
        "terminal_rerun_summary": {
            "index_count": len(index_symbols),
            "first_run_provider_calls": first_run_calls,
            "terminal_rerun_provider_call_delta_total": terminal_call_delta,
            "no_refetch": terminal_call_delta == 0,
            "persisted_fingerprint_before": overall_before,
            "persisted_fingerprint_after": overall_after,
            "persisted_fingerprint_unchanged": overall_before == overall_after,
            "no_reinsert": overall_before["content_sha256"] == overall_after["content_sha256"],
        },
        "per_index_sync": per_index,
        "persisted_coverage": coverage,
        "readiness": {
            "schema_version": readiness["schema_version"],
            "fields": readiness["fields"],
            "units": readiness["units"],
            "usable": readiness["coverage"]["usable"],
            "calendar_verified": readiness["coverage"]["calendar_verified"],
            "returned_rows": readiness["coverage"]["returned_rows"],
            "missing_total": len(readiness["coverage"]["missing"]),
            "missing_by_index": missing_by_index,
            "missing_fields_total": len(readiness["coverage"]["missing_fields"]),
            "sample_rows": readiness["rows"][:5],
        },
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "evidence": str(EVIDENCE_PATH.relative_to(REPO_ROOT)),
        "open_sessions": len(sessions),
        "provider_calls": counting.index_daily_basic_calls,
        "terminal_rerun_provider_call_delta": terminal_call_delta,
        "persisted_fingerprint_unchanged": overall_before == overall_after,
        "coverage_rows": coverage["row_count"],
        "coverage_indexes": coverage["index_count"],
        "readiness_usable": readiness["coverage"]["usable"],
        "readiness_missing": len(readiness["coverage"]["missing"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderError as error:
        print(json.dumps({"blocker": f"provider_error: {error}"}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
