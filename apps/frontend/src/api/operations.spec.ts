import { afterEach, describe, expect, it, vi } from "vitest";
import { getOperationsStatus } from "./operations";

describe("operations api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns secret-free operations status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            backend: "ok",
            runtime: "runtime-adapter",
            storage: "ready",
            migration: "not_started",
            observability: { workflow_trace: "configured", audit: "configured" },
          }),
          { status: 200 },
        ),
      ),
    );
    const status = await getOperationsStatus("test-token");
    expect(status.backend).toBe("ok");
    expect(JSON.stringify(status)).not.toContain("token");
  });
});
