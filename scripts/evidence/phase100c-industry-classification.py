#!/usr/bin/env python3
"""Phase 100-C real verification: Shenwan ``index_classify``/``index_member_all``.

Performs a bounded real Tushare read into an isolated BYQ PostgreSQL test
database (never production), persists rows through the authoritative
``IndustryClassificationStore`` sync/import path, then proves:

- the classification tree and membership intervals are persisted idempotently;
- a terminal sync rerun neither refetches nor reinserts;
- point-in-time membership is reconstructed from ``in_date``/``out_date``
  intervals and differs across historical as-of dates;
- the provider has no as-of date parameter and date-like parameters are rejected
  at the BYQ boundary, so history can never be backfilled from the current set.

It refuses to run against any database whose name does not contain
``byq_domain_test``.

Usage (inside an isolated backend container with the source mounted at /app)::

    BYQ_DATABASE_URL=postgresql+psycopg://byq_test:...@<isolated-pg>:5432/byq_domain_test \
    TUSHARE_TOKEN=... python scripts/evidence/phase100c-industry-classification.py

Output: docs/evidence/phase-100c/SHENWAN-INDUSTRY-VERIFICATION.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "backend"))

from app.data_provider import (  # noqa: E402
    IndexClassifyRequest,
    IndexMemberAllRequest,
    ProviderError,
    TushareProvider,
)
from app.industry_classification import IndustryClassificationStore  # noqa: E402

PIT_LEVEL = "L3"
PIT_CODES = ["850531.SI", "850551.SI", "857831.SI"]
PIT_DATES = ["20150101", "20180101", "20200101", "20220101", "20250901"]
EVIDENCE_PATH = REPO_ROOT / "docs" / "evidence" / "phase-100c" / "SHENWAN-INDUSTRY-VERIFICATION.json"


class CountingProvider:
    def __init__(self, provider: TushareProvider) -> None:
        self._provider = provider
        self.classify_calls = 0
        self.member_calls = 0

    def fetch_index_classify(self, request):
        self.classify_calls += 1
        return self._provider.fetch_index_classify(request)

    def fetch_index_member_all(self, request):
        self.member_calls += 1
        return self._provider.fetch_index_member_all(request)


def _require_isolated_database() -> None:
    url = os.environ.get("BYQ_DATABASE_URL", "")
    if "byq_domain_test" not in url:
        raise SystemExit("refusing to write evidence outside an isolated *byq_domain_test* database")


def _sync_summary(job: dict, finished: dict, *, created: bool, calls: int) -> dict:
    return {
        "job_id": job["job_id"],
        "created": created,
        "status": finished["status"],
        "provider_calls": calls,
        "rows_received": finished["rows_received"],
        "rows_inserted": finished["rows_inserted"],
        "rows_updated": finished["rows_updated"],
        "rows_kept": finished["rows_kept"],
        "rows_quarantined": finished["rows_quarantined"],
    }


def main() -> int:
    _require_isolated_database()
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured; live verification cannot run")

    provider = TushareProvider.from_env()
    counting = CountingProvider(provider)
    store = IndustryClassificationStore()

    # --- classification tree (SW2021 + SW2014) ---------------------------
    classify_jobs: dict[str, dict] = {}
    for src in ("SW2021", "SW2014"):
        payload = {"kind": "classify", "mode": "refresh", "src": src,
                   "idempotency_key": f"p100c-classify-{src}"}
        before = counting.classify_calls
        job, created = store.create_sync_job(payload, actor="phase100c-evidence")
        finished = store.run_sync_job(job["job_id"], provider_factory=lambda: counting)
        classify_jobs[src] = _sync_summary(job, finished, created=created,
                                           calls=counting.classify_calls - before)

    # --- membership intervals (current Y + removed N) --------------------
    member_payload = {"kind": "member", "mode": "incremental", "selector": "all",
                      "idempotency_key": "p100c-member-all"}
    member_before = counting.member_calls
    member_job, member_created = store.create_sync_job(member_payload, actor="phase100c-evidence")
    member_finished = store.run_sync_job(member_job["job_id"], provider_factory=lambda: counting)
    member_summary = _sync_summary(member_job, member_finished, created=member_created,
                                   calls=counting.member_calls - member_before)

    fingerprint_before = store.persisted_fingerprint()
    classify_calls_before = counting.classify_calls
    member_calls_before = counting.member_calls

    # --- terminal reruns must neither refetch nor reinsert ---------------
    terminal = {}
    for src, summary in classify_jobs.items():
        rerun = store.get_sync_job(summary["job_id"])
        result = store.run_sync_job(rerun["job_id"], provider_factory=lambda: counting)
        terminal[f"classify:{src}"] = {
            "same_job_id": result["job_id"] == rerun["job_id"],
            "status": result["status"],
            "no_refetch": counting.classify_calls == classify_calls_before,
            "reported_cumulative_rows_inserted": result["rows_inserted"],
        }
    member_rerun = store.run_sync_job(member_job["job_id"], provider_factory=lambda: counting)
    terminal["member:all"] = {
        "same_job_id": member_rerun["job_id"] == member_job["job_id"],
        "status": member_rerun["status"],
        "no_refetch": counting.member_calls == member_calls_before,
        "reported_cumulative_rows_inserted": member_rerun["rows_inserted"],
    }
    fingerprint_after = store.persisted_fingerprint()

    coverage = store.coverage()

    # --- point-in-time reconstruction ------------------------------------
    point_in_time = {}
    for code in PIT_CODES:
        by_date = {}
        for as_of in PIT_DATES:
            result = store.membership_asof(level=PIT_LEVEL, code=code, as_of_date=as_of)
            by_date[as_of] = {
                "member_count": result["member_count"],
                "members": [item["ts_code"] for item in result["members"]],
                "intervals": [
                    {"ts_code": item["ts_code"], "in_date": item["in_date"], "out_date": item["out_date"]}
                    for item in result["members"]
                ],
            }
        counts = {as_of: entry["member_count"] for as_of, entry in by_date.items()}
        point_in_time[code] = {
            "as_of": by_date,
            "member_counts": counts,
            "varies_across_dates": len(set(counts.values())) > 1,
        }

    # --- explicit negative: no as-of date can reach the provider ---------
    member_params = IndexMemberAllRequest(is_new="N").normalized().provider_params()
    classify_params = IndexClassifyRequest(src="SW2021").normalized().provider_params()
    date_like_rejected = False
    try:
        store.create_sync_job(
            {"kind": "member", "selector": "all", "trade_date": "20200101",
             "idempotency_key": "p100c-negative-date"},
            actor="phase100c-evidence",
        )
    except ValueError:
        date_like_rejected = True

    # --- readiness for a bounded set of current members ------------------
    current = store.membership_asof(level=PIT_LEVEL, code=PIT_CODES[0], as_of_date="20260901")
    readiness_symbols = [item["ts_code"] for item in current["members"]][:20]
    readiness = store.readiness(symbols=readiness_symbols, as_of_date="20260901", level="L1") \
        if readiness_symbols else {"coverage": {"usable": None, "requested_symbols": 0}}

    evidence = {
        "schema_version": "phase-100c-shenwan-industry-verification.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "tushare",
        "endpoints": ["index_classify", "index_member_all"],
        "isolated_database": True,
        "production_state_changed": False,
        "points_requirement": {"index_classify": 2000, "index_member_all": 2000},
        "provider_call_counts": {
            "index_classify": counting.classify_calls,
            "index_member_all": counting.member_calls,
        },
        "classify_sync": classify_jobs,
        "member_sync": member_summary,
        "terminal_rerun": terminal,
        "persisted_fingerprint": {
            "before": fingerprint_before,
            "after": fingerprint_after,
            "unchanged": fingerprint_before == fingerprint_after,
        },
        "persisted_coverage": coverage,
        "point_in_time": {
            "inclusion_exclusion_dates_present": coverage["member"]["missing_in_date"] == 0
            and coverage["member"]["settled_count"] > 0,
            "provider_has_as_of_parameter": False,
            "date_like_sync_field_rejected": date_like_rejected,
            "member_request_params": sorted(member_params),
            "classify_request_params": sorted(classify_params),
            "reconstruction": point_in_time,
        },
        "readiness": {
            "level": "L1",
            "as_of_date": "20260901",
            "symbols": readiness_symbols,
            "usable": readiness["coverage"]["usable"],
            "classify_present": readiness["coverage"].get("classify_present"),
            "missing_total": len(readiness["coverage"].get("missing", [])),
            "ambiguous_total": len(readiness["coverage"].get("ambiguous", [])),
        },
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "evidence": str(EVIDENCE_PATH.relative_to(REPO_ROOT)),
        "classify_calls": counting.classify_calls,
        "member_calls": counting.member_calls,
        "member_rows": coverage["member"]["row_count"],
        "settled": coverage["member"]["settled_count"],
        "open": coverage["member"]["open_count"],
        "fingerprint_unchanged": fingerprint_before == fingerprint_after,
        "date_like_rejected": date_like_rejected,
        "readiness_usable": readiness["coverage"]["usable"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderError as error:
        print(json.dumps({"blocker": f"provider_error: {error}"}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
