import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "real-product.spec.ts",
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
