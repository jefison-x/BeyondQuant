import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: [
    "real-product.spec.ts",
    "post-release-r1-terminal-session.real.spec.ts",
    "post-release-r2-workspace-menu.real.spec.ts",
    "post-release-r4-password-change.real.spec.ts",
  ],
  forbidOnly: true,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: process.env.BYQ_REAL_BASE_URL ?? "http://127.0.0.1:18080",
    headless: true,
    trace: "retain-on-failure",
  },
});
