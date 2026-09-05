# Phase 95 Verification Evidence

Phase 95 adds a maintainer-only central moderation console to the existing Cloudflare Hub. It does not change the ordinary BYQ feedback flow,
Product API, DSH/MCP boundary, D1 schema, Queue/Publisher contract or fixed GitHub repository.

Verified from the isolated `feat/cloudflare-feedback-admin-console` worktree:

- ADR-0055 fixes the operator/UI authentication boundary and preserves the isolated Publisher as the only Issue writer;
- TypeScript strict checking and 12 real workerd/Vitest tests pass against D1, Durable Objects and Queue bindings;
- tests cover non-cacheable self-contained assets, CSP, incorrect token, exact-origin login, bounded signed HttpOnly Cookie, tamper/expiry/logout,
  Bearer compatibility, CSRF rejection, server pagination and the existing moderation/publication state machine;
- four shell-free D1 bootstrap tests and the Git deployment verifier pass;
- the repository path-aware local CI passes all seven selected checks: docs, architecture, clean-PostgreSQL backend, fake-GitHub Publisher,
  feedback Hub Relay, Cloudflare workerd tests and deploy bundles;
- both production configs pass `wrangler deploy --dry-run`: Hub 64.45 KiB (17.53 KiB gzip), Publisher unchanged at 11.60 KiB
  (4.02 KiB gzip), with no upload or production credential;
- the locked Cloudflare dependency tree passes `npm audit --audit-level=high` with zero reported vulnerabilities;
- architecture tests reject persistent browser token storage, GitHub credential/API access from Hub/UI, an enabled `workers.dev` fallback and
  missing Access path documentation;
- local real-Chrome desktop/mobile review is recorded in [`BROWSER_REVIEW.md`](BROWSER_REVIEW.md);
- the Community classification is recorded in [`COMMUNITY_FEATURE_CHECKLIST.md`](COMMUNITY_FEATURE_CHECKLIST.md);
- no production secret was read, no production D1 row was modified and no real GitHub Issue was created during validation.

Production activation remains `main`-only through the existing Cloudflare Workers Builds project. After deployment, the maintainer must protect
both `/admin*` and `/v1/admin/*` with an exact-identity Cloudflare Access policy before using the console.
