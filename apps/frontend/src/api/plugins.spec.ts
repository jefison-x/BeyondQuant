import { afterEach, describe, expect, it, vi } from "vitest";
import { getPluginCenter, requestPluginChange, requestPluginQualification } from "./plugins";

describe("plugin center Product API client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses only same-origin Product API and reads active identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      schema_version: "plugin-center.v1", policy: { version: 1 }, plugins: [],
      runtime: { active_composition_hash: "sha256:test" }, boundaries: { secrets_exposed: false },
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await getPluginCenter();
    expect(result.runtime.active_composition_hash).toBe("sha256:test");
    expect(fetchMock).toHaveBeenCalledWith("/api/product/plugins", { credentials: "include" });
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("runtime-adapter");
  });

  it("submits bounded policy and qualification requests", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ request: { request_id: "plugin_request_1" } }), { status: 202 })));
    vi.stubGlobal("fetch", fetchMock);
    await requestPluginChange({ action: "disable", plugin_id: "web-search", expected_version: 1, idempotency_key: "one", reason: "test" });
    await requestPluginQualification({ plugin_id: "guard", version: "0.1.1-rc.1", expected_version: 2, idempotency_key: "two", reason: "test" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/product/plugins/changes");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/product/plugins/qualifications");
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "POST", credentials: "include" }));
  });
});
