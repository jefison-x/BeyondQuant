import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "phase62-polish.spec.ts",
  workers: 1,
  retries: 0,
  use: {
    baseURL: process.env.BYQ_REAL_BASE_URL ?? "http://127.0.0.1:15174",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
