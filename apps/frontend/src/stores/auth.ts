import { defineStore } from "pinia";
import type { PersonalWorkspace } from "@/api/types";

interface CurrentUser {
  subject: string;
  display_name?: string;
  role?: string;
  workspace: PersonalWorkspace;
}

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null as CurrentUser | null,
    token: "",
  }),
  getters: {
    isAuthenticated: (state) => state.user !== null,
    isAdmin: (state) => state.user?.role === "admin",
  },
  actions: {
    setUser(user: CurrentUser) {
      this.user = user;
    },
    async login(username: string, password: string) {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
        throw new Error(body.error?.message ?? "登录失败");
      }
      await this.fetchMe();
    },
    async fetchMe() {
      const response = await fetch("/api/auth/me", { credentials: "include" });
      if (!response.ok) {
        this.user = null;
        throw new Error("会话已失效");
      }
      this.user = (await response.json()) as CurrentUser;
    },
    async logout() {
      try {
        const response = await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
        const receipt = await response.json();
        if (!response.ok || receipt?.status !== "ok" || Object.keys(receipt).length !== 1) {
          throw new Error("invalid logout receipt");
        }
      } catch {
        throw new Error("注销结果尚未确认，请重试退出登录。");
      }
      this.user = null;
    },
  },
});
