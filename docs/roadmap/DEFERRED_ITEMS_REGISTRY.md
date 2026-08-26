# BeyondQuant Deferred Items Registry（D-Items）

Status: **Active** — `IMPLEMENTATION_PLAN.md` 和 `COMMUNITY_FULL_PARITY_PLAN.md`（Phase 32–40）的 companion。

本 registry 是 phase 中**显式跳过、阻塞或有条件延后**工作的唯一权威清单，使其 precondition 成立时可自动重新拾取。普通未来 phase scope 仍在 phase plans，不放这里。某 phase 的 registry entry 仍为 `OPEN` 时不得宣称该 phase complete，否则违反 AGENTS rule 40。

## State machine 与 trigger

```text
BLOCKED ──(precondition met)──► READY ──(scheduled)──► IN_PROGRESS ──► CLOSED
  │                                                      │
  └──(precondition dropped / intentionally won't do)──► DROPPED
```

`BLOCKED` 表示前置条件未满足；`READY` 表示已满足未开工；`IN_PROGRESS` 表示已进入 worktree/Draft PR；`CLOSED` 表示实现、测试、merge、记录 evidence；`DROPPED` 必须带 rationale。

Trigger checkpoints：

1. ADR-0017/0018/0019 等状态变为 `Accepted` 时，查询依赖并将对应 `BLOCKED` 改为 `READY`。
2. Phase closeout 前遍历本 registry；本 phase 的 `OPEN` 阻止完成，`READY` 应排入下一 worktree。
3. 每次 `STATUS.md` 更新引用本 registry 并列出 `OPEN` entries。
4. Draft PR 的 Known limitations 必须引用未覆盖 registry IDs。

## Entries

### D-0001 — Phase 32 Backtest create wizard

- Phase: 32
- Status: `CLOSED`
- Precondition: ADR-0017 accepted；Triggered/Closed: 2026-08-18（PR #82）。
- Content：browser wizard（Community `BacktestView.vue`，`PORT_UX`）选择 validated StrategyVersion、matching `signal_snapshot` 和 execution parameters，经 Product API 提交。
- Acceptance：不在 browser/DSH 生成 signal；Chrome evidence/contract tests。
- Evidence：本目录 Chrome review 的 Phase 32 wizard（job `backtest_4f64f70c81c146c296874da762cb5d7a`）、六项 backend tests、local/self-hosted CI green。

### D-0002 — Signal producer（strategy source → signal_snapshot）

- Phase: 40
- Status: `CLOSED`
- Precondition: dedicated producer ADR，已由 ADR-0023 于 2026-08-22 满足。
- Content：BYQ-owned boundary 在 frozen universe/bars 上执行 validated strategy，生成 `signal_snapshot`；新 strategy 由此可进入 backtest。
- Acceptance：ADR accepted；worker/import 生成 content-addressed、secret-free snapshots；DSH 不执行 strategy source。
- Evidence：ADR-0023、coordinator/sandbox/adversarial tests、`docs/evidence/phase-40/GOLDEN_JOURNEY.json` 的真实 strategy→signal→backtest flow。

### D-0003 — Backtest result-object GC periodic sweep

- Phase: 40
- Status: `DROPPED`
- Precondition：`BYQ_BACKTEST_OBJECT_ROOT` 测得 orphan accumulation，证明 PR #77 best-effort delete 不足。
- Content/Acceptance：幂等删除仅 unreferenced objects，绝不删除 referenced/tampered object。
- Rationale：Phase 40 audit 测得 `live_reference_count=0`、`object_file_count=0`、`orphan_count=0`、`missing_count=0`，前置条件为 false。未来非零 measurement 应开新 observed issue。

### D-0009 — Strategy draft supersede visibility

- Phase: 40
- Status: `CLOSED`
- Precondition: none；2026-08-22 closed。
- Origin：Phase 33 软删除后 row 仍显示 `superseded`。要求 filter/“已删除”视图，保持 immutable soft-supersede。
- Closure：Product API 默认 active lifecycle；StrategyView 隐藏 superseded，并提供显式 `已归档`，含 component/projection tests 和 Chrome evidence。

### D-0010 — Version-history projection bound

- Phase: 40
- Status: `CLOSED`
- Origin：versions/backtest-count 曾复用 newest-200 `list_artifacts`，可能漏旧数据。
- Closure：direct owner/kind/strategy queries 与 grouped counts 独立于 200-row list；205-version scale test 验证 totals/pages/history/counts。

### D-0011 — StrategyView component-level tests

- Phase: 40
- Status: `CLOSED`
- Origin：已有 API/backend/Gateway/MCP/Chrome，无 Vitest view tests。
- Closure：`StrategyView.spec.ts` 覆盖 archive visibility、pagination、immutable history/read-only、stats、save/soft delete，并进入标准 frontend CI。

### D-0012 — Community deep strategy profile fields

- Phase: 40
- Status: `CLOSED`
- Content：description、parameters、`parameter_schema`、enable/disable/non-artifact CRUD 的逐项决策。
- Closure：前三项成为 editable draft fields 并冻结到 versions/signal inputs；mutable enable/disable/non-artifact CRUD 为 `DROP`/`REPLACE`；explicit owner approval 授权 execution。

### D-0005 — Phase 36 Agent workbench structured cards

- Phase: 36
- Status: `CLOSED`
- Precondition: ADR-0018 已于 2026-08-22 满足。
- Content：strategy-draft、stock-candidates、optimization、backtest-context、approval cards，以及 drawer/thinking。
- Acceptance/closure：cards 可见可操作；raw DSH 不跨 Gateway；真实 Product API desktop/mobile evidence 在 `docs/evidence/phase-36/`。

### D-0006 — Phase 37 My Space depth

- Phase: 37
- Status: `CLOSED`
- Precondition: ADR-0019 已于 2026-08-22 满足。
- Content：credential CRUD/Agent binding（never echoed）、strategy/backtest re-import、policy presets/rule CRUD。
- Closure：audited encryption/private resolution、owner-safe asset v2 re-import、effective rules 和 browser evidence 在 `docs/evidence/phase-37/`。

### D-0007 — Phase 38 Operations workbenches

- Phase: 38
- Status: `CLOSED`
- Precondition: ADR-0019/ADR-0022 已于 2026-08-22 满足。
- Content：database/PostgreSQL-cache/model/agent/budget/runtime/graph/access/data-source/sync，无 placeholder；cache 不用 Redis，budget 为 normalized DSH model-call tokens。
- Closure：九个 Product API workbenches、normalized usage、audited thresholds、desktop/mobile evidence/full CI 在 `docs/evidence/phase-38/`。

### D-0008 — Phase 39 Data Center / Data Sync

- Phase: 39
- Status: `CLOSED`
- Precondition: ADR-0019 已于 2026-08-22 满足。
- Content：Tushare-only source CRUD、test、sync jobs、coverage audit。
- Closure：durable Product API、credential resolution、PostgreSQL persistence、desktop/mobile evidence/checklist 在 `docs/evidence/phase-39/`。

## Dependency quick-reference

| Decision | Status | Unblocks |
|---|---|---|
| ADR-0017（`signal_snapshot`） | Accepted 2026-08-18 | D-0001 |
| ADR-0023（isolated signal producer） | Accepted 2026-08-22 | D-0002 `CLOSED` |
| ADR-0018（WorkflowTrace cards） | Accepted 2026-08-22 | D-0005 `CLOSED` |
| ADR-0019（encrypted credentials） | Accepted 2026-08-22 | D-0006/7/8 `CLOSED` |
| ADR-0022（component ownership） | Accepted 2026-08-22 | D-0007 `CLOSED` |
| Phase 40 shared components | complete 2026-08-22 | D-0009/10/11/12 `CLOSED` |

## 维护规则

任何 phase 发现的新 skipped/blocked item 必须在记录 limitation 的同一 PR 加入本 registry，一项 conditional work 对应一个 entry。Closeout 时 genuinely out-of-scope 的 `OPEN` 可显式转移到后续 phase；不得静默丢失。`DROPPED` 必须记录 rationale。本 registry 不是通用 backlog；相关 ADR 状态变化时更新 dependency table。
