# Conversation-First Frontend Experience Plan

Status: **IMPLEMENTATION COMPLETE — human v1.0 RC review open**

本计划以有界 Product experience program 取代即时 v1.0 release-candidate review。它不重新打开已完成 domain semantics，也不授权第二套 frontend/backend/runtime boundary。ADR-0024 是规范性的 experience/conversation ownership 决策。

## 每个 phase 的 invariants

- Browser traffic 只使用 Gateway/Product API。
- DSH 负责 generic Agent runtime；BYQ 负责 Product conversation metadata、domain state、authorization、audit 和 normalized projections。
- 现有 Product capabilities 必须有意迁移，不能因简化 navigation 而删除。
- 改动每个匹配 surface 前，只读检查并分类 Community。
- 所有 UI 使用 semantic design tokens；不允许 page-specific brand theme。
- 每个 phase 使用一个 isolated worktree/branch/PR，按 ADR-0015 在 CI-green 后 squash auto-merge；merge 后重建 Compose、login smoke，并对 UI changes 提供真实 browser desktop/mobile evidence。
- 完成单个 phase 不声明 v1.0 ready；只有 Phase 48 可重新开放独立 human release-candidate review。

## Global experience target

```text
Desktop
┌──────────────────────┬──────────────────────────────────────┐
│ New conversation     │ current conversation / workspace     │
│ Stock Pool           │                                      │
│ Strategy             │ Xiaoba is the default                │
│ Backtest             │                                      │
│ Conversation History │ cards, approvals, domain deep links  │
│ recent titles        │                                      │
│                      │                                      │
│ user menu            │ composer / workspace actions         │
└──────────────────────┴──────────────────────────────────────┘
```

## Theme contract

初始封闭 preference values：

```json
{"schema_version":"ui-preferences.v1","color_mode":"system","accent_theme":"emerald"}
```

Allowed accent themes 为 `emerald`、`ocean`、`indigo`、`amber`、`graphite`。Semantic status colors 不变。Backend persistence 是 source of truth；pre-mount cache 非权威，不含 identity/secret。

## Phase 42 — Conversation-first Product shell

以 single-level sidebar、compact workspace toolbar、默认 Xiaoba route、recent-session section、bottom user trigger 和 mobile navigation drawer 取代 grouped navigation/large route header。保留或 redirect 每个 existing route，并为 Paper Trading、research/approval lineage、assets、personal models/policy、Data Center、status 和 Operations 提供显式 destination。使用默认 semantic theme tokens；暂不声明 durable titled history。

Acceptance：desktop/mobile navigation、keyboard/focus、route preservation、auth/admin visibility 和现有 Product API flows 通过真实 browser review。

## Phase 43 — Durable conversation catalog 与 Xiaoba workspace（`COMPLETE`）

实现 ADR-0024 owner-scoped Backend catalog/Product API projections；deterministic first-turn titles；rename、pin、archive、有界 pagination/search；restart-safe message/card replay；以及带 activity/context drawers 的 centered conversation canvas。Existing DSH session persistence 仍为 private correlation state。

Acceptance：Compose restart recovery、two-user isolation、title lifecycle、history switching 无 message/trace crossover、normalized-only replay 和 desktop/mobile journeys 通过。

## Phase 44 — User center 与 durable appearance（`COMPLETE`）

将 Profile、Assets、Models、Agent Policy、Paper Trading 入口移入 user menu/user-center surfaces。增加 versioned durable appearance contract、system/light/dark、五种 accent themes、live preview、pre-mount restoration 和 cross-device persistence。

Acceptance：write-only credential behavior、asset transfer、policy precedence、Paper Trading reachability、theme persistence、contrast 和 owner isolation 继续通过真实 Product API。

## Phase 45 — Route-backed System Settings dialog（`COMPLETE`）

在大型 two-column dialog/full-screen mobile surface 中嵌入 System Overview、Data、Sources、Cache、Database、platform Models、Agents、Budget、Runtime、Workflow diagnostics、Access、Audit。保留 route history/deep links 和所有 ADR-0022 RBAC/audit/destructive-action limits。

Acceptance：每个 existing operations surface 仍可访问、admin-only、有界、可刷新，且经 browser 验证，不使用 direct internal APIs。

## Phase 46 — Core management workspace redesign（`COMPLETE`）

将 Stock Pool、Strategy、Backtest 统一为一致 catalog/detail workspaces。保留 immutable snapshots、version/approval/signal lineage、完整 backtest results 和 direct Workflow-card navigation。Global theme 应用于每个 table、editor、chart、dialog、mobile card。

Acceptance：无 domain feature regression；conversation-to-pool/strategy/backtest journey 与 return links 使用真实 Product data 通过。

## Phase 47 — Interaction、responsive 与 accessibility closure（`COMPLETE`）

标准化 loading/empty/error/success/disabled states、search/filter/pagination、unsaved-change protection、dates/numbers/status labels、responsive tables/cards/settings、keyboard navigation、focus management、reduced motion 和 theme-aware chart palettes。

Acceptance：完整 color-mode/accent matrix 通过 contrast/responsive review；Lighthouse accessibility 目标为 100，除非接受 documented external blocker。

## Phase 48 — Product coherence 与 golden journey（`COMPLETE`）

运行新的 no-mock、two-user Compose journey，覆盖 login、conversation、candidate pool、strategy、approval、signal、backtest、history restore、assets、models、appearance 和 administrator settings。对全部迁移后的 Community capabilities 对账，记录 desktop/tablet/mobile Chrome evidence，并发布 remaining Product gaps。

Acceptance：不存在无法解释的 missing capability、raw internal-browser boundary、fake state、owner crossover 或 theme inconsistency。完成仅重新开放 human v1.0 RC review，不自动通过。

已交付可重复 no-mock two-user Compose gate，覆盖完整 Product journey/personal/admin settings、最终 Community relocation reconciliation 和 desktop/tablet/mobile Chrome evidence。最终 review 发现的 mobile dark-mode selector contrast 缺陷已修复；desktop/mobile authenticated Lighthouse Accessibility 与 Best Practices 均为 100。Implementation program 已完成；human RC review 仍是独立待定决策。

## Post-merge preview contract

每个 phase merge 后同步 `main`、保留 volumes，并以 frontend `0.0.0.0:80`、Gateway `127.0.0.1:8100` 运行最新 stack。交付 maintainer 前验证 container health、homepage HTTP 200、durable login、phase journey 和 LAN address。

## Post-program UI optimization backlog（未授权实施）

本节只登记 Phase 42–48 完成后发现的非阻断界面问题，不重新打开已完成 Phase，也不授权实现
新的 Product scope。每一项在实施前仍需维护者明确授权，并按隔离 worktree、测试、PR 和 browser
review 流程交付。

### BQ-UI-001 — 股票池“版本”语义消歧

- **状态／优先级**：`PLANNED` / P3。
- **涉及界面**：股票池目录、股票池概览、动态规则和快照历史。
- **现状**：目录列“版本”和概览“当前版本”实际表示 current immutable member snapshot 的
  `version_number`，但动态股票池同时存在独立的规则定义版本，名称/说明更新还使用不公开的
  metadata concurrency version。通用“版本”标签容易让用户误以为修改名称、规则或刷新任务都会
  推进同一个版本号。
- **计划调整**：目录列改为“当前快照”，概览改为“当前成员快照”；动态定义继续明确显示
  “规则 vN”，历史记录明确显示“快照 vN”。metadata concurrency version 保持内部实现，不作为
  普通用户概念展示。
- **必须保留的语义**：只有当前指针指向的不可变成员快照决定目录中的 `vN`；规则修改、元数据
  修改、等待数据、失败任务和相同内容的幂等刷新不得伪装成新成员快照。
- **验收标准**：custom/index/dynamic 三类目录和详情不再出现无上下文的“版本”；desktop/mobile
  均能区分当前快照、规则版本和历史快照；补充 frontend unit/Playwright 文案与行为回归；不修改
  Product API、snapshot identity、producer version、metadata concurrency 或下游冻结引用语义。
