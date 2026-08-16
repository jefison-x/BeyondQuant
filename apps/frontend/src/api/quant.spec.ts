import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelBacktest, getBacktest, getBacktestResult, getResearchEntity, runBacktest } from "./quant";

describe("quant api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads a normalized research entity through the Product API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ artifact_id: "artifact_1", status: "validated" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const entity = await getResearchEntity("artifacts", "artifact_1", "test-token");
    expect(entity).toMatchObject({ artifact_id: "artifact_1" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/research/artifacts/artifact_1",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("runs and cancels a backtest through product paths", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ job_id: "job_1", status: "completed" }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    await getBacktest("job_1", "test-token");
    await runBacktest("job_1", "test-token");
    await cancelBacktest("job_1", "test-token");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/backtests/job_1/run",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/backtests/job_1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("reads the immutable backtest result object", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ job_id: "job_1", result: { total_return: 0.05, trade_count: 2, equity_curve: [] } }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const body = await getBacktestResult("job_1", "test-token");
    expect(body.result.total_return).toBe(0.05);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/backtests/job_1/result",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
