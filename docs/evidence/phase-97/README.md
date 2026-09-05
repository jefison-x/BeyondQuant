# Phase 97 Verification Evidence

Phase 97 resolves GitHub Issue #240 by separating readable Backtest catalogue metadata from immutable execution identity.

Verified from the isolated `fix/backtest-readable-names` worktree:

- ADR-0057 records the owner-scoped persisted `name`, stable `job_id`, default-name ownership and immutable identity boundary;
- a real Phase 96-shaped PostgreSQL table was upgraded in place: the historical row received a deterministic non-empty name while its job ID,
  request hash and result Artifact ID remained unchanged;
- targeted Backtest domain/API/task tests passed 26/26, including custom/default normalization, name and ID search, idempotent replay retaining the
  first name, owner isolation, summary projection and task projection;
- the complete clean-PostgreSQL Backend suite, Feedback Publisher tests, Hub Relay tests and Cloudflare workerd/deploy dry-run passed;
- frontend production build and all 148 Vitest tests passed; the added Backtest view test covers separate name/ID presentation and custom-name submit;
- system Google Chrome 152 with repository-pinned Playwright passed all 20 mocked browser regressions and all 9 no-mock real Product API journeys;
- the Phase 97 real journey created persisted research/strategy/approval/backtest data through the same-origin Gateway, queried by Chinese name,
  inspected the full technical ID and reviewed desktop/mobile layouts without a 5xx or cross-origin request;
- MCP TypeScript build and every contract suite passed, including Backtest task facade and ML-derived Backtest projection;
- rebuilt isolated Compose passed all 13 smoke, non-root, persistence, restart and two-user isolation checks; all temporary containers, volumes and
  networks were removed afterward;
- architecture tests, documentation checks, `git diff --check`, dependency audit and secret-negative review passed.

No production database, Backtest result, GitHub Issue, Cloudflare resource or secret was mutated during validation.

See [browser review](BROWSER_REVIEW.md) and [Community checklist](COMMUNITY_FEATURE_CHECKLIST.md).
