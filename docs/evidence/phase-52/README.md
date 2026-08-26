# Phase 52 — Personal workspace closure evidence

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

Phase 52 closes ADR-0025 without adding a team product. Durable login and
session bootstrap expose the same bounded `personal-workspace.v1` summary;
the browser receives no membership identifier, owner user identifier, trusted
header, or workspace selector. The shell and Assets page identify the current
personal scope, and bundle diagnostics name source/destination scope while the
destination continues to come only from the durable session.

The real two-user Product journey covers durable conversation replay, Stock
Pool, strategy draft/version/approval, signal production, deterministic
Backtest, Paper Trading, profile, appearance, encrypted model binding, asset
bundle transfer, and administrator settings. It proves distinct workspace
identities, logout/login stability, guessed-ID denial, browser workspace-header
stripping, and absence of resource crossover. The journey found and fixed one
metadata oracle: cross-workspace Paper account access now returns the same 404
as an absent account instead of revealing existence through 403.

## Verification results

- Complete local CI: all 14 checks passed, including isolated Compose, real
  browser smoke, and the no-mock Product journey.
- Backend: 127 tests passed; 1 environment-dependent test skipped.
- Gateway: 55 tests passed.
- Frontend: production TypeScript/Vite build passed; 32 files / 79 tests passed.
- No-mock two-user Product journey: passed; result is in
  `GOLDEN_JOURNEY.json`.
- Chrome DevTools MCP: desktop shell/menu and desktop/mobile Assets reviewed;
  same-origin Gateway/Product traffic only, no console errors.
- Recovery drill: fresh provisioning, portable backup/restore, PostgreSQL
  restart, Phase 51 pre-contract restore, and current forward repair passed.
- Contract after fresh restore: 31 tables enforced; all 22 relationship checks
  zero; manifest
  `188a7f30060a0346c5729cdc60c9b8ebb29f934be004b8991fffa73ca19f1387`.
- Contract after legacy forward repair: 31 tables enforced; all 22 checks zero;
  quarantine count zero; manifest
  `989eaf593bd4646cc4a8a304b1815a618ab0f5c4968d2386256ba589ab385fc7`.
- Fresh backup: `/tmp/byq-phase52-workspace.dump`, 151756 bytes, SHA-256
  `0029de93500494e072c3b094a6b510b7f89ec57083e3b6c6bf35be1371209eff`.

The recovery drill is repeatable with:

```bash
scripts/evidence/phase52-workspace-recovery.sh \
  /tmp/byq-phase52-workspace.dump \
  /tmp/byq-phase51-pre-contract.dump
```

The script uses only exact `byq-phase52-*` temporary containers/network and
cleans them on exit. It never mutates the running development PostgreSQL.

## Closure statement

There are no quarantined legacy rows. No compatibility read fallback accepts
missing or client-selected workspace context: normal browser operations require
the durable session workspace, Gateway constructs the trusted context, Backend
validates its active owner membership, and PostgreSQL requires workspace keys.
The retained `owner_principal` columns are creator/audit selectors after this
mandatory validation, not an alternate authorization path. Product Token
bootstrap compatibility still resolves to an explicit deployment workspace and
fails closed when unresolved; it is not normal browser authentication.

No organization, invitation, sharing, member-management, workspace creation,
or workspace-switching affordance was introduced.
