import { defineConfig } from "@playwright/test";

const port = process.env.BYQ_MOCK_E2E_PORT ?? "15173";

export default defineConfig({
  testDir: "./tests/e2e",
  testIgnore: ["real-product.spec.ts", "phase61-acceptance.spec.ts"],
  forbidOnly: true,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npm run dev -- --port ${port}`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
  },
});
