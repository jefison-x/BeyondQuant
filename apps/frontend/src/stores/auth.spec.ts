import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAuthStore } from "./auth";

describe("auth store", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it("tracks the current durable user and logs out", async () => {
    const auth = useAuthStore();
    expect(auth.isAuthenticated).toBe(false);
    auth.setUser({
      subject: "testuser",
      workspace: {
        contract: "personal-workspace.v1",
        workspace_id: "workspace_test",
        kind: "personal",
        display_name: "测试用户的个人工作区",
        role: "owner",
      },
    });
    expect(auth.isAuthenticated).toBe(true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 })));
    await auth.logout();
    expect(auth.isAuthenticated).toBe(false);
  });

  it("bootstraps the bounded personal workspace from the durable session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      subject: "alice",
      display_name: "量化小周",
      role: "user",
      workspace: {
        contract: "personal-workspace.v1",
        workspace_id: "workspace_alice",
        kind: "personal",
        display_name: "Alice 的个人工作区",
        role: "owner",
      },
    }), { status: 200 })));
    const auth = useAuthStore();
    await auth.fetchMe();
    expect(auth.user?.display_name).toBe("量化小周");
    expect(auth.user?.workspace.display_name).toBe("Alice 的个人工作区");
  });

  it.each(["transport", "server", "json", "wrong_ack"])("retains the user for exact logout retry after %s", async (failure) => {
    const auth = useAuthStore();
    auth.setUser({ subject: "synthetic-user", workspace: { contract: "personal-workspace.v1", workspace_id: "workspace_test",
      kind: "personal", display_name: "合成测试", role: "owner" } });
    const request = vi.fn();
    if (failure === "transport") request.mockRejectedValueOnce(new Error("synthetic transport error"));
    else request.mockResolvedValueOnce(new Response(failure === "json" ? "invalid" : "{}", { status: failure === "server" ? 503 : 200 }));
    request.mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", request);
    await expect(auth.logout()).rejects.toThrow("注销结果尚未确认");
    expect(auth.isAuthenticated).toBe(true);
    await auth.logout();
    expect(auth.isAuthenticated).toBe(false);
    expect(request.mock.calls[0]).toEqual(request.mock.calls[1]);
  });
});
