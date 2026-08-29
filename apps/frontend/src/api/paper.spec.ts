import { afterEach, describe, expect, it, vi } from "vitest";
import { createPaperAccount, createStockPool, deletePaperAccount, exportPaperAccount, getPaperOrder, listPaperLedger, listPaperOrders, listPaperSnapshots, replaceStockPoolSnapshot, settlePaperAccount, submitPaperOrder, updatePaperControls } from "./paper";

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
