# Phase 82 Acceptance Report

- Date: 2026-08-31
- Branch: `phase-82-scalable-data-jobs`
- Architecture: ADR-0047

## Provider evidence

- Tushare official permission table: RMB 200/year maps to 2,000 points; the
  2,000-point row documents 200 calls/minute and 100,000 calls per API/day.
  Source: <https://tushare.pro/document/1?doc_id=290>
- Tushare official A-share daily contract: one request returns at most 6,000
  rows. Source: <https://tushare.pro/document/1?doc_id=27>
- Theoretical `100,000 × 6,000` arithmetic is not throughput or an SLA. BYQ
  configures a 0.34-second minimum request interval and keeps 50,000 cells as
  one atomic readiness partition.

## Automated verification

- Local CI docs, architecture, Backend against isolated PostgreSQL, Gateway,
  frontend production build, 43 frontend files / 124 tests, and dependency
  audit: PASS.
- Explicit 300-symbol/five-year partition test: contiguous first/last coverage,
  at most 32 partitions and every projected atomic partition <=50,000 cells:
  PASS.
- Provider budget timing, per-run ML preparation failure isolation and legacy
  single-partition frozen identity tests: PASS.
- Isolated Compose build and health: Backend, Gateway, Frontend, PostgreSQL,
  MCP, Runtime Adapter, Data Worker, ML Worker, Signal Worker and sandbox PASS.
- Real Product API Playwright: 6/6 PASS, including LightGBM training →
  out-of-sample prediction → frozen signal → Backtest.
- ML Worker restart identity, artifact persistence and second-user isolation:
  PASS.

An initial browser run correctly rejected prediction because a new aggregate
hash had wrapped the legacy single-partition identity. Phase 82 now preserves
the exact identity for one partition and uses an ordered composite identity
only for multiple partitions. Targeted tests and the complete real journey
passed after the correction.

## Chrome DevTools MCP review

- Route: `/settings/system/data`, authenticated administrator, isolated Phase
  82 Compose stack.
- Desktop and 390×844 mobile accessibility snapshots expose the Tushare budget,
  Worker health, durable “后台任务进度” table, status, stage, completed/total
  units, rows, safe explanation and five-second refresh semantics.
- Lighthouse snapshot: desktop Accessibility 100 / Best Practices 100; mobile
  Accessibility 100 / Best Practices 100.
- Console warnings/errors: none.
- Network: all observed data-center polling was same-origin
  `/api/product/data-center/status` with HTTP 200. No Browser request reached
  Backend, MCP, DSH, PostgreSQL or Tushare directly.

## Community checklist

| Community behavior | Phase 82 result |
|---|---|
| Hardcoded pools, TODO API and fake 50% progress | Dropped. Only persisted BYQ tasks and measured units render. |
| Durable status/progress/rows/error UX | Refactored into additive `data-task.v1` over existing BYQ records. |
| Lease/retry/stale recovery | Existing BYQ workers remain authoritative; a bad ML run is isolated. |
| ORM/thread/direct Provider architecture | Dropped. Data Worker remains the sole Provider caller. |

No Community source, data, credentials, runtime or Git history was modified or
copied.
