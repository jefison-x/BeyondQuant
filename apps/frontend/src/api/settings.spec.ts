import { afterEach, describe, expect, it, vi } from "vitest";
import {
  exportAssets,
  getAppearance,
  getAgentPolicyStatus,
  getAssetSummary,
  getModelSettings,
  getProfile,
  importAssets,
  updateAppearance,
  updateAgentPolicy,
  updateProfile,
} from "./settings";

describe("settings api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("loads and updates durable profile fields", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ profile: { subject: "testuser", display_name: "老李", preferences: "低波动", default_prompt: "先结论" } }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    const profile = await getProfile();
    expect(profile.profile.display_name).toBe("老李");
    expect(fetchMock).toHaveBeenCalledWith("/api/product/profile", expect.objectContaining({ credentials: "include" }));

    await updateProfile({ display_name: "量化小周" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/profile",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    );
  });

  it("loads and updates the closed durable appearance contract", async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify({ preferences: {
        schema_version: "ui-preferences.v1", color_mode: "system", accent_theme: "emerald", version: 0, updated_at: null,
      } }), { status: 200 })))
      .mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify({ preferences: {
        schema_version: "ui-preferences.v1", color_mode: "dark", accent_theme: "indigo", version: 1, updated_at: "2026-08-24T00:00:00Z",
      } }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    expect((await getAppearance()).preferences.accent_theme).toBe("emerald");
    const updated = await updateAppearance({
      schema_version: "ui-preferences.v1", color_mode: "dark", accent_theme: "indigo", expected_version: 0,
    });
    expect(updated.preferences.version).toBe(1);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/product/settings/appearance",
      expect.objectContaining({ method: "PUT", body: expect.stringContaining('"expected_version":0') }),
    );
  });

  it("returns masked model settings without credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ provider: "deepseek", configured: false, models: [], credentials: { masked: true, write_only: true } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const models = await getModelSettings();
    expect(models.configured).toBe(false);
    expect(JSON.stringify(models)).not.toContain("token");
    expect(JSON.stringify(models)).not.toContain("secret");
  });

  it("loads owner-scoped asset summary and policy status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ strategies: [], backtests: [], pools: [], paper_accounts: [], summary: { strategies: 0, backtests: 0, pools: 0, paper_accounts: 0 } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const assets = await getAssetSummary();
    expect(assets.summary.strategies).toBe(0);

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ platform_policy: { automation_enabled: false, paused: false, default_decision_mode: "manual" }, approval_inbox: { pending: 0 } }), { status: 200 }),
    );
    const policy = await getAgentPolicyStatus();
    expect(policy.approval_inbox.pending).toBe(0);
  });

  it("exports and imports asset bundles", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ schema_version: "byq-workspace-assets-v2", assets: {}, manifest_sha256: "abc" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const bundle = await exportAssets();
    expect(bundle.schema_version).toBe("byq-workspace-assets-v2");

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ imported: { pools: 1, paper_accounts: 0 }, skipped: { strategies: 0, backtests: 0, reason: "research artifacts require validation or recomputation" }, errors: [] }), { status: 200 }),
    );
    const report = await importAssets(bundle);
    expect(report.imported.pools).toBe(1);
  });

  it("updates personal agent approval policy", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ personal_policy: { automation_enabled: true, paused: false, default_decision_mode: "manual" } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await updateAgentPolicy({ automation_enabled: true });
    expect(result.personal_policy.automation_enabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/settings/agent-policy",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    );
  });
});
