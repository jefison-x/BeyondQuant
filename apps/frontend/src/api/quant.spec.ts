import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cancelBacktest,
  createStrategyVersion,
  deleteBacktest,
  deleteStrategyDraft,
  getBacktest,
  getBacktestResult,
  getResearchEntity,
  getStrategyBacktestCount,
  getStrategyVersions,
  runBacktest,
  saveStrategyDraft,
} from "./quant";

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
      Promise.resolve(new Response(JSON.stringify({ job: { job_id: "job_1", status: "completed" } }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const fetched = await getBacktest("job_1", "test-token");
    expect(fetched.job_id).toBe("job_1");
    expect(fetched.status).toBe("completed");
    const ran = await runBacktest("job_1", "test-token");
    expect(ran.job_id).toBe("job_1");
    const cancelled = await cancelBacktest("job_1", "test-token");
    expect(cancelled.status).toBe("completed");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/backtests/job_1/run",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/backtests/job_1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("deletes a terminal backtest through the product path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job: { job_id: "job_1", status: "completed" } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const deleted = await deleteBacktest("job_1", "test-token");
    expect(deleted.job_id).toBe("job_1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/backtests/job_1",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
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

  it("creates an immutable strategy version through the product path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ artifact: { artifact_id: "artifact_version_1", kind: "strategy_version" } }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const body = await createStrategyVersion(
      { task_id: "task_1", draft_artifact_id: "artifact_draft_1" },
      "test-token",
    );
    expect((body.artifact as { artifact_id: string }).artifact_id).toBe("artifact_version_1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/strategies/versions",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("saves and deletes a strategy draft through the product path", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init: RequestInit) => {
      const body =
        url === "/api/product/strategies/drafts"
          ? { artifact: { artifact_id: "artifact_draft_1", kind: "strategy_draft" }, validation: { success: false } }
          : { artifact: { artifact_id: "artifact_draft_1", kind: "strategy_draft", status: "superseded" } };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 201 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const saved = await saveStrategyDraft(
      { task_id: "task_1", strategy: { strategy_id: "CustomStrategy", script: "class CustomStrategy: pass" } },
      "test-token",
    );
    expect((saved.artifact as { artifact_id: string }).artifact_id).toBe("artifact_draft_1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/strategies/drafts",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );

    const deleted = await deleteStrategyDraft("artifact_draft_1", "test-token");
    expect((deleted.artifact as { status: string }).status).toBe("superseded");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/strategies/drafts/artifact_draft_1",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });

  it("reads version history and backtest counts through the product path", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const body = url.includes("/backtest-count")
        ? { strategy_id: "CustomStrategy", version_count: 1, backtest_count: 3 }
        : { strategy_id: "CustomStrategy", versions: [{ artifact_id: "artifact_version_1", version_id: "v1" }] };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const history = await getStrategyVersions("CustomStrategy", "test-token");
    expect((history.versions as Array<{ artifact_id: string }>)[0].artifact_id).toBe("artifact_version_1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/strategies/CustomStrategy/versions",
      expect.objectContaining({ credentials: "include" }),
    );
    const counts = await getStrategyBacktestCount("CustomStrategy", "test-token");
    expect(counts.backtest_count).toBe(3);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/strategies/CustomStrategy/backtest-count",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
