# Phase 47 Chrome DevTools MCP review

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

Date: 2026-08-24

The review used the live `beyondquant` Compose stack on `0.0.0.0:80`, durable
admin login, persisted Product data and the Phase 47 production frontend.
Mocked browser routes were not used.

## Responsive and interaction review

- 1440x900 Appearance and Backtest, 820x1180 Stock Pool, and 390x844 dark
  Appearance were reviewed. The measured document width equalled the viewport
  at tablet and mobile sizes; no page-level horizontal overflow was present.
- Route navigation from Stock Pool to the lazy Backtest view moved focus from
  the initiating sidebar control to `h2` “回测任务与完整结果” with
  `tabindex=-1`. The retry loop was added after Chrome exposed an async chunk
  timing race in the first implementation.
- An unsaved Profile nickname edit opened the leave confirmation. Dismissing
  retained the route and edit; accepting left the route without a Product API
  write. The persisted nickname was not changed.
- A real completed Backtest exposed its ECharts canvas as an accessibility
  image named for the equity curve and included the visible summary
  “展示 2 个交易日的组合权益变化。”
- The reduced-motion stylesheet rule was present; unit coverage verifies that
  chart animation is disabled when the media query matches.

## Accessibility and theme review

- Desktop Lighthouse: Accessibility 100, Best Practices 100.
- Mobile Lighthouse: Accessibility 100, Best Practices 100.
- The initial 96 score identified only the shallow light `text-soft` token.
  Raising that semantic token from `#8a94a6` to `#5f6b7a` removed all ten
  affected shell/user-center findings. No component-specific color override
  was required.
- The light/dark plus five-accent computed contrast matrix passed in all ten
  combinations. Details are in `THEME_CONTRAST_MATRIX.md`.

The remaining Lighthouse SEO 91 and Agentic Browsing 67 findings are the
existing `robots.txt` and optional `llms.txt` discovery recommendations. They
are not accessibility failures and are outside Phase 47's authenticated
Product interaction scope.

## Boundary review

- Preserved console warnings/errors: none.
- Observed requests were same-origin `/api/auth/*` and `/api/product/*` only.
- No Backend-internal, MCP, raw DSH event, PostgreSQL, Redis, provider or
  Community endpoint crossed the browser boundary.
