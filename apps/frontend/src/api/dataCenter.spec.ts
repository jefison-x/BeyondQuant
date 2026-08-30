import { afterEach, describe, expect, it, vi } from "vitest";
import { createDataSourceCredential, createDataSyncJob, createSecurityMasterSyncJob, getDataCenterStatus, listSecurities, queryDataReadiness, runMarketSyncNow, testDataSource, updateMarketSyncAutomation } from "./dataCenter";

describe("data center api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns migration and provider status without secrets", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            schema_version: "data-center.v3", migration: "not_started", provider: "tushare", legacy_providers: [], quality: "empty", data_tasks: [],
            provider_budget: { schema_version: "provider-budget.v1", profile: "tushare-personal-2000", official_calls_per_minute: 200, official_calls_per_api_per_day: 100000, daily_rows_per_call: 6000, configured_request_interval_seconds: 0.34, actual_credential_tier_detected: false },
            source: { configured: true, effective_source: "credential_store", credentials: [], encryption: { configured: true, status: "ready" }, secrets_exposed: false, can_manage: true },
            jobs: [], data_demands: [], security_master_jobs: [], security_master: { schema_version: "security-master.v1", quality: "empty", latest_snapshot: null, total: 0, status_counts: { L: 0, P: 0, D: 0 }, exchange_counts: { SSE: 0, SZSE: 0, BSE: 0 } }, coverage: { checked_at: "2026-08-22T00:00:00Z", provider: "tushare", scope: "persisted_observations", quality: "empty", completeness_claimed: false, row_count: 0, symbol_count: 0, source_issues: 0, ohlc_issues: 0, groups: [], symbols: [] },
            automation: { schema_version: "market-sync-automation.v1", config: { enabled: false, schedule_time: "18:30", timezone: "Asia/Shanghai", catchup_days: 7, security_master_enabled: true, datasets: ["trade_calendar", "stock_daily"], version: 1, updated_by: "system", updated_at: "2026-08-25T00:00:00Z" }, worker: { healthy: false }, latest_calendar_open_date: null, latest_complete_session: null, next_run_at: "2026-08-25T18:30:00+08:00", jobs: [], run_requests: [], index_catalog_sync_runs: [] },
            index_catalog: { schema_version: "index-catalogue.v1", total: 6, available_total: 0, indices: [] },
          }),
          { status: 200 },
        ),
      ),
    );
    const status = await getDataCenterStatus();
    expect(status.migration).toBe("not_started");
    expect(status.source.configured).toBe(true);
    expect(status.source.effective_source).toBe("credential_store");
    expect(JSON.stringify(status)).not.toContain("token");
    expect(JSON.stringify(status)).not.toContain("password");
  });

  it("uses only Product API routes for credential, test, and sync writes", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ credential: {}, test: {}, job: {}, created: true }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    await createDataSourceCredential({ label: "Tushare", secret: "write-only", idempotency_key: "create-1" });
    await testDataSource({ symbol: "000001.SZ", trade_date: "20240102" });
    await createSecurityMasterSyncJob();
    await listSecurities({ query: "平安", statuses: ["L"], exchanges: ["SZSE"] });
    await createDataSyncJob({ mode: "range", symbols: ["000001.SZ"], start_date: "20240102", end_date: "20240103", idempotency_key: "sync-1" });
    await updateMarketSyncAutomation({ enabled: true, schedule_time: "18:30", catchup_days: 7, security_master_enabled: true, expected_version: 1, idempotency_key: "automation-1" });
    await runMarketSyncNow();
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/product/data-center/source/credentials",
      "/api/product/data-center/source/test",
      "/api/product/data-center/security-master/sync-jobs",
      "/api/product/data-center/securities?query=%E5%B9%B3%E5%AE%89&statuses=L&exchanges=SZSE&limit=50&offset=0",
      "/api/product/data-center/sync-jobs",
      "/api/product/data-center/automation/config",
      "/api/product/data-center/automation/run-now",
    ]);
    expect(fetchMock.mock.calls.every((call) => call[1]?.credentials === "include")).toBe(true);
  });

  it("checks a bounded task through the Product API without triggering sync", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      schema_version: "data-readiness-product.v1", verdict: "usable",
      scope: { symbol_count: 1, symbols: ["600036.SH"], start_date: "20260101", end_date: "20260630", use_case: "research" },
      summary: { required_sessions: 120, ready_items: 120, missing_items: 0, calendar_complete: true },
      datasets: [], issues: [], issues_truncated: false, checked_against: "persisted_byq",
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await queryDataReadiness({
      symbols: ["600036.SH"], start_date: "20260101", end_date: "20260630", use_case: "research",
    });

    expect(result.verdict).toBe("usable");
    expect(fetchMock).toHaveBeenCalledWith("/api/product/data-center/readiness", expect.objectContaining({
      method: "POST", credentials: "include",
    }));
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({
      symbols: ["600036.SH"], start_date: "20260101", end_date: "20260630", use_case: "research",
    }));
  });
});
