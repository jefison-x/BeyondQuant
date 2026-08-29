import { afterEach, describe, expect, it, vi } from "vitest";
import { createMLStrategy, getMLWorkspace } from "./mlResearch";

describe("ML research Product API client", () => {
  afterEach(() => vi.restoreAllMocks());
  it("loads the browser-safe workspace with durable session credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ tasks: [], pools: [], artifacts: [], training_runs: [], prediction_runs: [], backtests: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await getMLWorkspace()).artifacts).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith("/api/product/ml/workspace", expect.objectContaining({ credentials: "include" }));
  });
  it("does not accept browser-owned trace or idempotency fields in its typed strategy command", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ artifact: { artifact_id: "artifact_ml" } }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    await createMLStrategy({ task_id: "task_1", strategy: { schema_version: "ml-strategy-version.v1" } });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ task_id: "task_1", strategy: { schema_version: "ml-strategy-version.v1" } });
    expect(body.trace_id).toBeUndefined();
  });
});
