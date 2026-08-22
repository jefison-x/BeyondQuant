import { afterEach, describe, expect, it, vi } from "vitest";
import { createDataSourceCredential, createDataSyncJob, getDataCenterStatus, testDataSource } from "./dataCenter";

describe("data center api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns migration and provider status without secrets", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            schema_version: "data-center.v1", migration: "not_started", provider: "tushare", legacy_providers: [], quality: "empty",
            source: { configured: true, effective_source: "credential_store", credentials: [], encryption: { configured: true, status: "ready" }, secrets_exposed: false, can_manage: true },
            jobs: [], coverage: { checked_at: "2026-08-22T00:00:00Z", provider: "tushare", scope: "persisted_observations", quality: "empty", completeness_claimed: false, row_count: 0, symbol_count: 0, source_issues: 0, ohlc_issues: 0, groups: [], symbols: [] },
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
    await createDataSyncJob({ mode: "range", symbols: ["000001.SZ"], start_date: "20240102", end_date: "20240103", idempotency_key: "sync-1" });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/product/data-center/source/credentials",
      "/api/product/data-center/source/test",
      "/api/product/data-center/sync-jobs",
    ]);
    expect(fetchMock.mock.calls.every((call) => call[1]?.credentials === "include")).toBe(true);
  });
});
