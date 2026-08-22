import { afterEach, describe, expect, it, vi } from "vitest";
import { getOperationsStatus, updateOperationsBudget } from "./operations";

describe("operations api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns secret-free operations status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: "operations.v1",
          services: { backend: "ready", runtime_adapter: "ready" },
          database: { engine: "postgresql", status: "ready" },
          runtime: { usage: { total_tokens: 10 }, raw_dsh_events: false },
          observability: { workflow_trace: "normalized", audit: "append_only", raw_dsh_events: false },
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const status = await getOperationsStatus("test-token");
    expect(status.services.backend).toBe("ready");
    expect(status.runtime.raw_dsh_events).toBe(false);
    expect(JSON.stringify(status)).not.toContain("api_key");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/operations/status",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("updates only the bounded audited budget threshold contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      budget: { policy_id: "product-agent", enabled: true, alert_total_tokens: 500000, alert_requests: 60, version: 2, updated_by: "admin", updated_at: "2026-08-22T00:00:00Z" },
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const budget = await updateOperationsBudget({ enabled: true, alert_total_tokens: 500000, alert_requests: 60, expected_version: 1, idempotency_key: "budget-test-1" });
    expect(budget.version).toBe(2);
    expect(fetchMock).toHaveBeenCalledWith("/api/product/operations/budget", expect.objectContaining({ method: "PUT", credentials: "include" }));
  });
});
