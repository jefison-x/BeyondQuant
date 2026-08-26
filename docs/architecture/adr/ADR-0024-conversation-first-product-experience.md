# ADR-0024：Conversation-First Product Experience 与 Durable Conversation Catalog

- Status: Accepted
- Date: 2026-08-23
- Accepted: 2026-08-23
- Decision scope: Post-Phase 40 Product shell、conversation catalog、settings surface 和
  user appearance preference
- Related: ADR-0003、ADR-0012、ADR-0014、ADR-0018、ADR-0022

## 背景

Phase 40 完成当时的 Community feature-parity program，但 Product UI 仍将 implementation
history 暴露为大量 grouped navigation entry、独立 Operations shell 和三栏 Agent
workbench。维护者明确推迟 v1.0 release-candidate review，并选择 conversation-first 产品
方向：类似 ChatGPT 的双栏 shell，以 Xiaoba 为 default workspace，四个 primary domain
destination、recent conversation title、bottom user menu 和统一 settings experience。

当时 Product API 只列出带 `session_id`/`trace_id` 的 live Product session。Frontend
显示 shortened ID，并在 client state 保存 active conversation message；无法满足 durable
title、history restore、archive/search、restart recovery 或 owner-safe conversation
management。DSH 持有 raw session persistence/runtime event，但它们不是稳定 Product
catalog，也不能成为 Browser Contract。

Read-only Community frontend 证明 conversation-history、user-menu、theme-class 和
Operations-navigation interaction 有价值；其 authentication、Agent API、raw event
assumption、state store 和 direct service Contract 与 BYQ 不兼容，只作 reference。

## 决策

1. Authenticated Product shell 改为 conversation-first。Desktop 为一个 collapsible primary
   sidebar 加 main workspace；Xiaoba 是 default route。Primary business entry 只有 New
   Research Conversation、Stock Pool、Strategy、Backtest、Conversation History。
2. BYQ Backend 持有 durable owner-scoped Product conversation catalog。Metadata 包含稳定
   conversation/session reference、title、owner、lifecycle state、create/update time、last-
   message preview 和 optional pin/archive state。DSH 继续持有 raw Runtime Session log；
   其 persistence 是 correlation evidence，不是 Product catalog。
3. Conversation replay 只通过 Gateway/Product API projection 到达 Browser；projection 由
   BYQ-owned conversation metadata 和 normalized WorkflowTrace/message projection 组成。
   Frontend 不直接读 DSH file、raw event、Runtime Adapter internal 或 MCP。
4. Initial title 使用从 first user turn 派生的 deterministic bounded fallback。后续 model-
   generated refinement 可通过 BYQ-owned bounded write 更新；失败不阻塞 conversation
   create，model output 也不提供 owner/lifecycle authority。
5. 三栏 Agent layout 替换为 conversation canvas。Workflow card 保留在 message flow；
   activity/execution context 移入有界 drawer/disclosure；Approval 通过 normalized card 和
   global Approval inbox 继续可用。
6. Personal Profile、Assets、Model Configuration、Agent Policy 移到 bottom user menu 后。
   Paper Trading 仍是实际 Product capability，并成为明确 Asset Management subsection。
   Research/Approval lineage 可从 card、asset detail 和 Approval center 访问。
7. Administrator Operations 移入有独立双栏 navigation 的大型 route-backed System
   Settings dialog。现有 Product API RBAC 保持权威；normal user 看不到 entry，也不能通过
   直接导航 settings route 获得 access。
8. Appearance 是 durable user-scoped BYQ preference，具有 versioned public Contract。
   初始支持 `color_mode`（`system`、`light`、`dark`）和 closed accent palette。Backend
   权威；有界 browser cache 只能用于避免 first-paint theme flash。
9. 全部 frontend color 使用 semantic design token。Accent selection 不改变 success、
   warning、error、Approval 或 destructive-action semantics。Page、chart、dialog、drawer、
   Element Plus override、Workflow card 和 mobile surface 不得定义独立 visual theme。
10. Existing deep link 通过 route preservation/explicit redirect 保持有效。Dialog
    presentation 不得移除 refresh、browser history、audit 或 direct-link behavior。

## Product information architecture

```text
Primary sidebar
├── New Research Conversation
├── Stock Pool
├── Strategy
├── Backtest
├── Conversation History
│   └── recent owner-scoped conversation titles
└── User menu
    ├── Personalization
    ├── Asset Management
    │   └── Paper Trading
    ├── Model Configuration
    ├── Agent Policy
    └── System Settings (admin only)
```

## 后果

- 不移除现有 domain depth 的前提下，Product 更易理解。
- History 只有在新增 Backend/Product API conversation catalog 后才能宣称完成。
- Frontend shell、settings container 和 core workspace 可独立演进，因为数据继续通过
  Product API Contract。
- Appearance Contract 引入小型 persistent schema 和 global design-token migration，但
  防止 per-page theme drift。
- v1.0 RC gate 保持关闭，直到 post-Phase 41 experience program 和新的 real-browser
  golden journey 完成。

## 拒绝的替代方案

- 保留 grouped dashboard-first navigation：保留 implementation history，但与选定
  conversation-first product model 冲突。
- 使用 DSH session file 作为 Browser history：将 Product state 耦合 runtime persistence，
  并泄漏不稳定 framework boundary。
- Title/theme 只存 localStorage：失去 durable multi-device identity，违反 Product
  completion rule。
- 复制 Community Agent/session store：重新引入不兼容 API 和 runtime coupling。
- 允许任意 user-entered color：使 contrast、chart、semantic state 和 cross-page review
  无界。
- 在 redesign 中加入 Cloud tenant UI：tenancy 属于后续独立 architecture program；shell
  只保留 future workspace-switcher seam。

## Migration 与 rollback

Implementation 分隔在 Phase 42-48 的 isolated Phase 中。Existing route 在 replacement
验证前保持可用。Conversation-catalog migration 必须将 existing runtime session 保留为
unclaimed correlation evidence，不能静默分配 unverifiable history。每个 Phase 可 rollback
frontend container/route mapping，而不改变已完成 domain asset。Disable new appearance
setting 后，每个 user 回到 default light emerald token set，不删除 stored preference。

## Acceptance record

维护者于 2026-08-23 接受 conversation-first layout、user-menu consolidation、大型双栏
System Settings dialog、durable titled history 和 global theme requirement。Acceptance 不
授权 raw DSH Browser Contract、移除 existing capability、fake conversation history 或
premature v1.0 release。
