import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchDashboard, fetchHealth, ProductApiError } from "./client";

describe("product api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends the bearer token and parses product responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", service: "byq-gateway" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await fetchHealth("test-token");
    expect(result.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/health",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("normalizes product error envelopes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "product_authentication_required", message: "auth", request_id: "1" } }), { status: 401 }),
      ),
    );
    await expect(fetchDashboard("bad-token")).rejects.toBeInstanceOf(ProductApiError);
  });
});
