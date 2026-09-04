import { afterEach, describe, expect, it, vi } from "vitest";
import { createMLStrategy, createMLTraining, deleteMLStudy, getMLPredictionRows, getMLWorkspace, setMLStudyLifecycle } from "./mlResearch";

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
  it("loads only the requested filtered prediction page", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ rows: [], total: 0, limit: 50, offset: 50 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await getMLPredictionRows("run /1", "000001.SZ", 50, 50);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/product/ml/prediction-runs/run%20%2F1/rows?query=000001.SZ&limit=50&offset=50");
  });
  it("sends a stable transport idempotency key outside the domain payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ training_run: { training_run_id: "mlrun_1" } }), { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await createMLTraining({
      task_id: "task_1", ml_strategy_artifact_id: "artifact_1", stock_pool_snapshot_id: "snapshot_1",
    }, "browser-training-12345678");
    const init = fetchMock.mock.calls[0][1];
    expect(init.headers["x-idempotency-key"]).toBe("browser-training-12345678");
    expect(JSON.parse(init.body)).not.toHaveProperty("idempotency_key");
  });
  it("soft-deletes one encoded study through the Product API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      schema_version: "ml-study-delete.v1", study: { status: "superseded" },
      invalidated_approval_ids: [],
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await deleteMLStudy("artifact /1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/ml/studies/artifact%20%2F1",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });
  it("archives a study through the bounded lifecycle command", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      schema_version: "ml-study-lifecycle.v1", study: { status: "archived" },
      management: { lifecycle_status: "archived", can_restore: true },
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await setMLStudyLifecycle("artifact /1", "archived");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/product/ml/studies/artifact%20%2F1/lifecycle");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ status: "archived" });
    expect(init.headers["x-idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
  });
});
