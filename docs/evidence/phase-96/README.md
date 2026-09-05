# Phase 96 Verification Evidence

Phase 96 replaces mandatory Cloudflare Access with direct single-maintainer password login while preserving the Hub's own authorization and
all central feedback publication boundaries.

Verified from the isolated `fix/feedback-admin-direct-login` worktree:

- ADR-0056 records why direct login is the default and why Access remains an optional MFA/IdP layer;
- TypeScript strict checking and 15 real workerd/Vitest tests pass against D1, three SQLite Durable Object bindings and Queue bindings;
- password and Bearer attempts share a source-keyed `AdminLoginGate`; tests cover four 401 responses, fifth-attempt 429, 900-second
  `Retry-After`, correct-password rejection while locked, independent source success, success-state clearing and alarm expiry cleanup;
- v2 session tests cover exact-origin exchange, high-entropy signing with password-version binding, HttpOnly/Secure/SameSite=Strict,
  tamper, expiry and logout without exposing the password;
- four shell-free D1 bootstrap tests and the Git deployment verifier cover the additive v2 Durable Object migration;
- both production configs pass `wrangler deploy --dry-run`: Hub 68.06 KiB (18.37 KiB gzip) with `ADMIN_LOGIN_GATE`, and Publisher remains
  11.60 KiB (4.02 KiB gzip), without upload or production credentials;
- the locked Cloudflare and frontend dependency trees each report zero npm audit vulnerabilities;
- architecture tests enforce optional Access, persistent HMAC-source throttling, no `X-Forwarded-For`, no application password storage,
  no Hub GitHub credential and disabled `workers.dev`;
- real Chrome desktop/mobile and lockout review is recorded in [`BROWSER_REVIEW.md`](BROWSER_REVIEW.md);
- the continued Community classification is recorded in [`COMMUNITY_FEATURE_CHECKLIST.md`](COMMUNITY_FEATURE_CHECKLIST.md).
- the repository path-aware local CI passes all seven selected checks: docs, architecture, clean-PostgreSQL backend, fake-GitHub Publisher,
  Hub Relay, Cloudflare workerd tests and deployment bundles.

No production secret was read, no production D1/DO/Queue was contacted, no production feedback was changed and no GitHub Issue was created
during validation. Deployment uses the existing `main`-only Cloudflare Workers Builds path and requires no new runtime secret.
