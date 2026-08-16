import { defineStore } from "pinia";

const STORAGE_KEY = "byq-product-token";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: localStorage.getItem(STORAGE_KEY) ?? "",
  }),
  getters: {
    isAuthenticated: (state) => state.token.length > 0,
  },
  actions: {
    setToken(token: string) {
      this.token = token.trim();
      localStorage.setItem(STORAGE_KEY, this.token);
    },
    logout() {
      this.token = "";
      localStorage.removeItem(STORAGE_KEY);
    },
  },
});
