import { describe, expect, it } from "vitest";
import type { DataCenterStatus } from "@/api/types";
import { mergeDataCenterProgress } from "./dataCenterProgress";

function statusFixture(marker: number): DataCenterStatus {
  return {
    schema_version: "data-center.v3",
    migration: `migration-${marker}`,
    provider: "tushare",
    provider_budget: {
      schema_version: "provider-budget.v1", profile: `profile-${marker}`,
      official_calls_per_minute: 200, official_calls_per_api_per_day: 100000,
      daily_rows_per_call: 6000, configured_request_interval_seconds: 0.34,
      actual_credential_tier_detected: false,
    },
    legacy_providers: [], quality: `quality-${marker}`,
    source: {
      configured: true, effective_source: "credential_store", credentials: [],
      encryption: { configured: true, status: "ready" }, secrets_exposed: false, can_manage: true,
    },
    jobs: [{ job_id: `job-${marker}`, provider: "tushare", mode: "range", symbols: [], symbols_truncated: false, selection: { type: "explicit" }, symbol_count: 0, result_count: 0, results_truncated: false, start_date: "20260101", end_date: "20260102", status: "queued", progress: marker, rows_received: 0, rows_inserted: 0, rows_kept: 0, symbol_results: [], requested_by: "test", created_at: "2026-01-01", updated_at: "2026-01-01" }],
    data_demands: [],
    data_tasks: [{ schema_version: "data-task.v1", task_id: `task-${marker}`, kind: "manual_sync", purpose: "market_data", title: "同步", status: "running", stage: "synchronizing", progress: { completed: marker, total: 100, percent: marker, unit: "symbols" }, rows: marker, reference: { kind: "job", id: `job-${marker}` }, created_at: "2026-01-01", updated_at: "2026-01-01" }],
    security_master_jobs: [],
    security_master: { schema_version: "security-master.v1", quality: "empty", latest_snapshot: null, total: marker, status_counts: { L: 0, P: 0, D: 0 }, exchange_counts: { SSE: 0, SZSE: 0, BSE: 0 } },
    coverage: { checked_at: "2026-01-01", provider: "tushare", scope: "persisted_observations", quality: "observed", completeness_claimed: false, row_count: marker, symbol_count: marker, date_min: null, date_max: null, source_issues: 0, ohlc_issues: 0, groups: [], symbols: [] },
    automation: {
      schema_version: "market-sync-automation.v1",
      config: { enabled: false, schedule_time: "18:30", timezone: "Asia/Shanghai", catchup_days: marker, security_master_enabled: true, datasets: ["stock_daily"], version: marker, updated_by: "test", updated_at: "2026-01-01" },
      worker: { healthy: true, heartbeat_at: `heartbeat-${marker}` },
      latest_calendar_open_date: `2026010${marker}`, latest_complete_session: null,
      next_run_at: `next-${marker}`, jobs: [], run_requests: [{ marker }], index_catalog_sync_runs: [{ marker }],
    },
    index_catalog: { schema_version: "index-catalogue.v1", indices: [], total: marker, available_total: marker },
  } as DataCenterStatus;
}

describe("mergeDataCenterProgress", () => {
  it("updates task progress without replacing page-level data or editable config", () => {
    const current = statusFixture(1);
    const next = statusFixture(2);

    const merged = mergeDataCenterProgress(current, next);

    expect(merged.data_tasks).toBe(next.data_tasks);
    expect(merged.jobs).toBe(next.jobs);
    expect(merged.automation.worker).toBe(next.automation.worker);
    expect(merged.automation.run_requests).toBe(next.automation.run_requests);
    expect(merged.coverage).toBe(current.coverage);
    expect(merged.security_master).toBe(current.security_master);
    expect(merged.source).toBe(current.source);
    expect(merged.automation.config).toBe(current.automation.config);
    expect(merged.index_catalog).toBe(current.index_catalog);
  });
});
