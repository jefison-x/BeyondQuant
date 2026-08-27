import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "phase61-acceptance.spec.ts",
  forbidOnly: true,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.BYQ_REAL_BASE_URL ?? "http://127.0.0.1:18081",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
