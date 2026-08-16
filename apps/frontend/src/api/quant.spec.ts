import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelBacktest, getBacktest, getResearchEntity, runBacktest } from "./quant";

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
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer test-token" }) }),
    );
  });

  it("runs and cancels a backtest through product paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ job_id: "job_1", status: "completed" }), { status: 200 }));
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
});
