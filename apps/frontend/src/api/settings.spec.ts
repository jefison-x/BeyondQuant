import { afterEach, describe, expect, it, vi } from "vitest";
import { getSettingsStatus } from "./settings";

describe("settings api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns masked, secret-free platform status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          profile: { configured: true },
          model_provider: { configured: false },
          data_provider: { provider: "tushare", migration: "not_started" },
          storage: { status: "ready" },
          approval_inbox: { pending: 0 },
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const status = await getSettingsStatus("test-token");
    expect(status.model_provider.configured).toBe(false);
    expect(JSON.stringify(status)).not.toContain("token");
    expect(JSON.stringify(status)).not.toContain("secret");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/settings/status",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
