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
    expect(auth.user?.workspace.display_name).toBe("Alice 的个人工作区");
  });
});
