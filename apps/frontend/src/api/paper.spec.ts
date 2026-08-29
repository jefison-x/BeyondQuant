import { afterEach, describe, expect, it, vi } from "vitest";
import { createDynamicStockPool, createIndexStockPool, createPaperAccount, createStockPool, deletePaperAccount, diffStockPoolSnapshots, exportPaperAccount, getPaperOrder, getStockPoolReadiness, listIndexPoolCatalog, listPaperLedger, listPaperOrders, listPaperSnapshots, listStockPoolMaterializations, previewDynamicStockPool, refreshIndexStockPool, replaceStockPoolSnapshot, settlePaperAccount, submitPaperOrder, updateDynamicStockPoolDefinition, updatePaperControls } from "./paper";
import type { DynamicStockPoolRule } from "./types";

describe("paper trading api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("creates simulation accounts and stock pools through product paths", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ account: { account_id: "a1", cash: 100000 } }), { status: 201 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const account = await createPaperAccount("sim", 100000, "test-token");
    expect(account.account.account_id).toBe("a1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/paper/accounts",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("submits simulation orders with normalized fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ order: { order_id: "o1", status: "blocked", blocked_reason: "suspended" } }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await submitPaperOrder(
      { account_id: "a1", pool_id: "p1", symbol: "000001.SZ", side: "buy", quantity: 100, price: 10, trade_date: "20240102", idempotency_key: "x" },
      "test-token",
    );
    expect(result.order.blocked_reason).toBe("suspended");
  });

  it("tombstones an account through the Product API with optimistic identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ account_id: "paper_account_1", deleted: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await deletePaperAccount("paper_account_1", 3, "test-token");
    const request = fetchMock.mock.calls[0];
    expect(request[0]).toBe("/api/product/paper/accounts/paper_account_1");
    expect(request[1]).toEqual(expect.objectContaining({ method: "DELETE", credentials: "include" }));
    expect(JSON.parse(String(request[1]?.body))).toEqual(expect.objectContaining({ expected_version: 3 }));
  });

  it("lists orders without exposing provider or database internals", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ orders: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await listPaperOrders("a1", "test-token");
    expect(result.orders).toEqual([]);
    expect(String(fetchMock.mock.calls[0][1]?.headers)).not.toContain("tushare");
  });

  it("creates a custom catalog stock pool with description and complete weights", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ pool: { pool_id: "p1", pool_type: "custom" } }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await createStockPool("沪深300", ["000001.SZ", "600000.SH"], "test-token", {
      poolType: "custom",
      description: "自建池",
      weights: { "000001.SZ": 0.6, "600000.SH": 0.4 },
    });
    expect(result.pool.pool_type).toBe("custom");
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.pool_type).toBe("custom");
    expect(body.weights).toEqual({ "000001.SZ": 0.6, "600000.SH": 0.4 });
    expect(body.provenance).toBeUndefined();
  });

  it("replaces membership through an immutable snapshot product path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ snapshot: { snapshot_id: "s2" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await replaceStockPoolSnapshot("p1", {
      expected_current_snapshot_id: "s1", idempotency_key: "edit-1", symbols: ["000001.SZ"],
    }, "test-token");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/paper/pools/p1/snapshot",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    );
  });

  it("uses bounded Product paths for index catalog, creation and materialization", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      indices: [], pool: { pool_id: "stock_pool_1", pool_type: "index" }, runs: [], run: { run_id: "run_1" },
    }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    await listIndexPoolCatalog("test-token");
    await createIndexStockPool({ index_symbol: "000300.SH", name: "沪深300" }, "test-token");
    await listStockPoolMaterializations("stock_pool_1", "test-token");
    await refreshIndexStockPool("stock_pool_1", "20240131", "test-token");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/product/paper/index-pools/catalog",
      "/api/product/paper/index-pools",
      "/api/product/paper/pools/stock_pool_1/materializations",
      "/api/product/paper/pools/stock_pool_1/materializations",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual(expect.objectContaining({ index_symbol: "000300.SH" }));
    expect(fetchMock.mock.calls[3][1]).toEqual(expect.objectContaining({ method: "POST" }));
  });

  it("uses only Product paths for dynamic preview, creation and definition update", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      authoritative: false, members: [], member_count: 0, pool: { pool_id: "dynamic-1" }, run: null, producer: {},
    }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const rule: DynamicStockPoolRule = {
      schema_version: "dynamic-stock-pool-rule.v1",
      base_universe: { kind: "security_master" }, filters: [],
      ranking: { field: "daily_basic.total_mv", direction: "desc" }, top_n: 20,
      missing_policy: "exclude", weight_mode: "equal_weight", cadence: "daily",
    };
    await previewDynamicStockPool(rule, "20240103", "test-token");
    await createDynamicStockPool({ name: "动态大盘池", rule, activate: true }, "test-token");
    await updateDynamicStockPoolDefinition("dynamic-1", { rule, status: "paused", expected_version: 1 }, "test-token");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/product/paper/dynamic-pools/preview",
      "/api/product/paper/dynamic-pools",
      "/api/product/paper/pools/dynamic-1/producer",
    ]);
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "PUT" }));
  });

  it("reads normalized readiness and immutable snapshot diffs", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ readiness: { state: "current" }, diff: { added: [] } }), { status: 200 }),
    ));
    vi.stubGlobal("fetch", fetchMock);
    await getStockPoolReadiness("pool 1", "test-token");
    await diffStockPoolSnapshots("pool 1", "snapshot a", "snapshot b", "test-token");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/product/paper/pools/pool%201/readiness",
      "/api/product/paper/pools/pool%201/snapshot-diff?from_snapshot_id=snapshot+a&to_snapshot_id=snapshot+b",
    ]);
  });

  it("lists the persisted paper ledger", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ledger: [{ fill_id: "f1", cash_delta: -1000 }] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await listPaperLedger("a1", "test-token");
    expect(result.ledger[0].cash_delta).toBe(-1000);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/paper/accounts/a1/ledger",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("uses bounded product paths for order detail, settlement, controls, snapshots, and bundle", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ order: {}, snapshot: {}, snapshots: [], controls: { version: 2 }, bundle: {} }), { status: 200 }),
    ));
    vi.stubGlobal("fetch", fetchMock);
    await getPaperOrder("a1", "o1", "test-token");
    await listPaperSnapshots("a1", "test-token");
    await settlePaperAccount("a1", { trade_date: "20240103", expected_version: 2, idempotency_key: "s1", marks: { "000001.SZ": 11 } }, "test-token");
    await updatePaperControls("a1", { kill_switch_engaged: true, expected_version: 1, idempotency_key: "r1" }, "test-token");
    await exportPaperAccount("a1", "test-token");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/product/paper/accounts/a1/orders/o1",
      "/api/product/paper/accounts/a1/snapshots",
      "/api/product/paper/accounts/a1/settlements",
      "/api/product/paper/accounts/a1/controls",
      "/api/product/paper/accounts/a1/export",
    ]);
  });
});
