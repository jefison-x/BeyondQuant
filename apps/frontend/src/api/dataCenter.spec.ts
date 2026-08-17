import { afterEach, describe, expect, it, vi } from "vitest";
import { getDataCenterStatus } from "./dataCenter";

describe("data center api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns migration and provider status without secrets", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ migration: "not_started", datasets: [], provider: "tushare", quality: "not_audited", provider_status: { configured: true, sync: "not_started" } }),
          { status: 200 },
        ),
      ),
    );
    const status = await getDataCenterStatus();
    expect(status.migration).toBe("not_started");
    expect(status.provider_status.configured).toBe(true);
    expect(status.provider_status.sync).toBe("not_started");
    expect(JSON.stringify(status)).not.toContain("token");
    expect(JSON.stringify(status)).not.toContain("password");
  });
});
