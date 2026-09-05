import path from "node:path";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest(async () => ({
      wrangler: { configPath: "./wrangler.hub.jsonc" },
      miniflare: {
        bindings: {
          TEST_MIGRATIONS: await readD1Migrations(path.join(import.meta.dirname, "migrations")),
          BYQ_FEEDBACK_HUB_STATUS_SECRET: "test-status-secret-that-is-at-least-32-bytes",
          BYQ_FEEDBACK_HUB_ADMIN_TOKEN: "test-admin-token-that-is-at-least-32-bytes",
          BYQ_FEEDBACK_PUBLISHER_TOKEN: "test-publisher-token-at-least-32-bytes"
        }
      }
    }))
  ],
  test: {
    setupFiles: ["./tests/setup.ts"],
    include: ["./tests/**/*.test.ts"]
  }
});
