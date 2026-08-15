import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAuthStore } from "./auth";

describe("auth store", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it("stores and clears the product token", () => {
    const auth = useAuthStore();
    expect(auth.isAuthenticated).toBe(false);
    auth.setToken("test-token");
    expect(auth.isAuthenticated).toBe(true);
    auth.logout();
    expect(auth.isAuthenticated).toBe(false);
  });
});
