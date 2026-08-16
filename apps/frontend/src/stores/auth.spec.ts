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
    auth.setUser({ subject: "testuser" });
    expect(auth.isAuthenticated).toBe(true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 })));
    await auth.logout();
    expect(auth.isAuthenticated).toBe(false);
  });
});
