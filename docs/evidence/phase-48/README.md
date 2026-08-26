# Phase 48 acceptance evidence

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

Phase 48 closes the ADR-0024 Product experience implementation program and
reopens a separate human v1.0 release-candidate review. It does **not** declare
an RC accepted and does not release v1.0.

## 已证明的内容

- A fresh isolated Compose stack used durable username/password login and two
  distinct users.
- One real Product journey created and restored a conversation, Stock Pool,
  strategy draft/version/approval, isolated signal snapshot and deterministic
  Backtest result.
- Profile, durable appearance, encrypted write-only model credential/profile/
  binding and digested asset export/import were exercised through Product API.
- The second user could not observe the owner's conversation, research task,
  pool, strategy, signal job, Backtest or assets and could not enter admin
  operations.
- Admin operations returned only `operations.v1`; `raw_dsh_events=false`.
- Desktop, tablet and mobile Chrome review used the real persisted results and
  observed same-origin Gateway/Product API traffic only.
- Chrome found one mobile dark-theme select contrast defect. It was fixed and
  the authenticated desktop and mobile Lighthouse Accessibility scores both
  returned to 100; Best Practices also scored 100.

The fixture seeder creates only external test prerequisites: a secondary
durable user and three explicitly synthetic canonical daily bars in the fresh
CI database. All journey actions use real Gateway/Product APIs, PostgreSQL,
Runtime Adapter, DSH session handling, Backend workers and signal sandbox; no
HTTP response, browser state or Product result is mocked.

## 证据索引

- [`GOLDEN_JOURNEY.json`](GOLDEN_JOURNEY.json) — sanitized final fresh-stack
  result.
- [`CHROME_MCP_REVIEW.md`](CHROME_MCP_REVIEW.md) — viewports, console,
  network boundary and Lighthouse observations.
- [`COMMUNITY_FEATURE_CHECKLIST.md`](COMMUNITY_FEATURE_CHECKLIST.md) — final
  relocation and disposition check.
- [`PRODUCT_GAP_REGISTER.md`](PRODUCT_GAP_REGISTER.md) — remaining release or
  optimization work, with no hidden parity blocker.
- `lighthouse-desktop.json` and `lighthouse-mobile.json` — machine reports.
- `screenshots/desktop-agent.png`, `screenshots/tablet-backtest.png`,
  `screenshots/mobile-appearance.png`, and
  `screenshots/mobile-system-settings.png` — real-browser visual evidence.

## 可重复命令

```bash
scripts/ci/local-ci.sh --all --with-smoke
```

The smoke stage copies `scripts/evidence/phase48-seed.py` into the isolated
Backend container, then runs `scripts/evidence/phase48-product-golden.py`
against the discovered Gateway port before the real Playwright browser suite.

## Gate 结论

There is no unexplained missing Community capability, raw internal browser
boundary, fake completion state, owner crossover or unresolved theme
inconsistency in the Phase 48 scope. Human v1.0 RC review is now open and
pending; only the maintainer can decide its result.
