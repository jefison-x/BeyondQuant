import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./tests/e2e', testMatch:['h5-index-preparation.spec.ts','h4-pool-recovery.spec.ts','h4-feedback-recovery.spec.ts','h4-paper-recovery.spec.ts','h4-credential-recovery.spec.ts','h4-policy-recovery.spec.ts'], workers:1, retries:0, forbidOnly:true,
  use:{baseURL:process.env.BYQ_REAL_BASE_URL, headless:true, trace:'retain-on-failure'},
});
