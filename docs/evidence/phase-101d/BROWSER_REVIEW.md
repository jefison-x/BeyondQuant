# Phase 101 Browser Review

Reviewed on 2026-09-17 with Playwright-managed Chromium and the repository-pinned Playwright
(`apps/frontend/playwright.p101d.config.ts`), against an isolated four-container stack
(frontend/gateway/backend/PostgreSQL) on network `byq-h5-browser-0913`, running the merged
`origin/main` sources and the freshly built frontend `dist`. No route mock was used.

- Durable BYQ user login through `/api/product/auth/login` (bootstrap admin, isolated test database).
- Test 1 (success path): selecting a real DeepSeek credential issued
  `GET /api/product/settings/models/credentials/{credential_id}/models` through the Gateway only,
  returned 200, and the model dropdown listed the discovered `deepseek-v4-pro` and `deepseek-flash`;
  the `刷新模型` button triggered a further successful refresh.
- Test 2 (fail-closed path): selecting a credential whose provider rejects the key produced a
  discovery response `>= 400`, a visible failure message, and the reviewed static catalogue remained
  selectable (`DeepSeek V4 Flash`).
- Desktop `1440×1000` and mobile `390×844` were captured
  ([desktop](p101d-desktop-1440.png), [mobile](p101d-mobile-390.png)); the mobile viewport satisfied
  `documentElement.scrollWidth <= innerWidth`.
- All observed requests stayed on the frontend origin (no cross-origin request), no response was `>= 500`,
  the journey collected no `pageerror`, and no secret or ciphertext appeared in any response.

Reproduce (isolated stack up):

```
cd apps/frontend
BYQ_REAL_BASE_URL="http://<frontend-ip>" \
BYQ_E2E_ADMIN_USERNAME=<user> BYQ_E2E_ADMIN_PASSWORD=<password> \
BYQ_E2E_EVIDENCE_DIR=<dir> \
npx playwright test --config playwright.p101d.config.ts
```
