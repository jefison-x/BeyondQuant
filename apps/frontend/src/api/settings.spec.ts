import { afterEach, describe, expect, it, vi } from "vitest";
import {
  assertSearchCredentialMutation,
  assertSearchCredentialReceipt,
  exportAssets,
  createModelCredential,
  getAppearance,
  getAgentPolicyStatus,
  getAssetSummary,
  getModelSettings,
  getProfile,
  discoverModelCredentialModels,
  disableModelProfile,
  enableModelProfile,
  importAssets,
  updateAppearance,
  updateAgentPolicy,
  updateProfile,
  reconcileModelCredential,
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
      new Response(JSON.stringify({
        provider: "deepseek", configured: false, models: [], credentials: { masked: true, write_only: true },
        credential_items: [],
        search_credential: { configured: false, status: "missing", masked: null, version: null, credential_id: null, provider: "deepseek" },
      }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const models = await getModelSettings();
    expect(models.configured).toBe(false);
    expect(models.search_credential).toEqual({
      configured: false, status: "missing", masked: null, version: null, credential_id: null, provider: "deepseek",
    });
    expect(JSON.stringify(models)).not.toContain("token");
    expect(JSON.stringify(models)).not.toContain("secret");
  });

  it("creates a search-purpose credential through the cookie-backed Product API", async () => {
    const credentialId = "cred_0123456789abcdef0123456789abcdef";
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ credential: {
      credential_id: credentialId, purpose: "web_search_api_key", provider: "deepseek", scope: "user",
      label: "DeepSeek 搜索服务", status: "active", configured: true, masked: "sk-…abcd", version: 1,
    } }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await createModelCredential({
      purpose: "web_search_api_key", provider: "deepseek", label: "DeepSeek 搜索服务",
      secret: "synthetic-search-secret", idempotency_key: "search-write-123",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/product/settings/models/credentials", expect.objectContaining({
      method: "POST", credentials: "include",
      body: JSON.stringify({
        purpose: "web_search_api_key", provider: "deepseek", label: "DeepSeek 搜索服务",
        secret: "synthetic-search-secret", idempotency_key: "search-write-123",
      }),
    }));
    expect(result.credential).not.toHaveProperty("secret");
    expect(JSON.stringify(result)).not.toContain("synthetic-search-secret");
  });

  it("scopes original credential receipt lookup to the search purpose", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
      state: "confirmed", operation: "create", credential_id: "cred_0123456789abcdef0123456789abcdef", committed_version: 1,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state: "not_found" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const receipt = await reconcileModelCredential({ operation: "create", key: "search-write-123" }, "web_search_api_key");

    expect(receipt.state).toBe("confirmed");
    expect(String(fetchMock.mock.calls[0][0])).toContain("purpose=web_search_api_key");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/settings/models/credentials/receipts?operation=create&request_id=search-write-123&purpose=web_search_api_key",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(await reconcileModelCredential({ operation: "create", key: "search-write-123" }, "web_search_api_key")).toEqual({ state: "not_found" });
  });

  it("requires complete search credential metadata and mutation receipts", () => {
    const credential = {
      credential_id: "cred_0123456789abcdef0123456789abcdef", purpose: "web_search_api_key", provider: "deepseek",
      scope: "user", status: "active", version: 1,
    };
    expect(() => assertSearchCredentialMutation(credential, "create")).not.toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, scope: "system" }, "create")).toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, status: "disabled" }, "create")).toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 2 }, "create")).toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 3 }, "update", 2, "active")).not.toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 3, status: "disabled" }, "update", 2, "disabled")).not.toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 3, status: "disabled" }, "update", 2, "active")).toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 4 }, "update", 2, "active")).toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 3, status: "revoked" }, "revoke", 2)).not.toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 4, status: "revoked" }, "revoke", 2)).toThrow();
    expect(() => assertSearchCredentialMutation({ ...credential, version: 3 }, "revoke", 2)).toThrow();
  });

  it("accepts only purpose-matched search receipts for the expected version", () => {
    expect(() => assertSearchCredentialReceipt({ state: "confirmed", operation: "create", committed_version: 1 }, "create")).not.toThrow();
    expect(() => assertSearchCredentialReceipt({ state: "confirmed", operation: "create", committed_version: 2 }, "create")).toThrow();
    expect(() => assertSearchCredentialReceipt({ state: "confirmed", operation: "update", committed_version: 3 }, "update", 2)).not.toThrow();
    expect(() => assertSearchCredentialReceipt({ state: "confirmed", operation: "revoke", committed_version: 4 }, "revoke", 2)).toThrow();
    expect(() => assertSearchCredentialReceipt({ state: "not_found", operation: "update", committed_version: 3 }, "update", 2)).toThrow();
  });

  it("refreshes credential models through the product API only", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ provider: "opencode-go", models: [{ model: "kimi-k3", display_name: "kimi-k3", reasoning_supported: false, runtime_provider: "opencode-go-chat", supported: true }] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await discoverModelCredentialModels("cred_0123456789abcdef0123456789abcdef");
    expect(result.models[0].runtime_provider).toBe("opencode-go-chat");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/settings/models/credentials/cred_0123456789abcdef0123456789abcdef/models",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("issues profile disable and enable commands through the product API", async () => {
    const profileId = "profile_" + "a".repeat(32);
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ profile: { profile_id: profileId, status: "disabled", version: 2 } }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await disableModelProfile(profileId, 1);
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/product/settings/models/profiles/${profileId}/disable`,
      expect.objectContaining({ method: "POST", body: JSON.stringify({ expected_version: 1 }) }),
    );

    await enableModelProfile(profileId, 2);
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/product/settings/models/profiles/${profileId}/enable`,
      expect.objectContaining({ method: "POST", body: JSON.stringify({ expected_version: 2 }) }),
    );
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
    const result = await updateAgentPolicy({ automation_enabled: true, request_id:"settings-test" });
    expect(result.personal_policy.automation_enabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/settings/agent-policy",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    );
  });
});
