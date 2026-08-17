import { afterEach, describe, expect, it, vi } from "vitest";
import { createPaperAccount, createStockPool, listPaperOrders, submitPaperOrder } from "./paper";

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

  it("lists orders without exposing provider or database internals", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ orders: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await listPaperOrders("a1", "test-token");
    expect(result.orders).toEqual([]);
    expect(String(fetchMock.mock.calls[0][1]?.headers)).not.toContain("tushare");
  });

  it("creates a catalog stock pool with type, description, and weights", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ pool: { pool_id: "p1", pool_type: "index" } }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await createStockPool("沪深300", ["000001.SZ", "600000.SH"], "test-token", {
      poolType: "index",
      description: "指数池",
      weights: { "000001.SZ": 0.6 },
    });
    expect(result.pool.pool_type).toBe("index");
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.pool_type).toBe("index");
    expect(body.weights).toEqual({ "000001.SZ": 0.6 });
  });
});
