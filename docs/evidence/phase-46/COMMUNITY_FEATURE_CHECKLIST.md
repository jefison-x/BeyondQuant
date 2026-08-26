# Phase 46 Community feature checklist

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

Community source was inspected read-only. BYQ Product contracts and persisted
projections remain authoritative.

| Capability | Decision | Result |
|---|---|---|
| Catalog beside stable resource detail | `PORT_LAYOUT` / `PORT_UX` / `REFACTOR` | PASS — one responsive BYQ shell composes all three real Product workspaces. |
| Guided Stock Pool creation | `PORT_UX` / `REFACTOR` | PASS — bounded dialog uses the Phase 34 snapshot write contract. |
| Pool identity, members, definition, provenance and history | `REUSE_AS_IS` / `PORT_LAYOUT` | PASS — all five persisted projections and lifecycle actions remain. |
| Strategy editor, version and approval lineage | `REUSE_AS_IS` / `PORT_LAYOUT` | PASS — drafts, immutable versions, history, approval and signal boundary remain distinct. |
| Backtest task list, compare, chart and deep result | `REUSE_AS_IS` / `PORT_STYLE` | PASS — complete BYQ result and creation surfaces remain. |
| Conversation-to-resource deep links and return | `PORT_UX` / `REFACTOR` / `PORT_TESTS` | PASS — closed normalized-card mapping plus exact Product rehydration and durable conversation return. |
| Desktop/mobile catalog behavior | `PORT_LAYOUT` / `PORT_UX` | PASS — desktop tables and mobile cards are mutually exclusive; detail remains reachable below. |
| Community APIs, Agent schemas, ORM/cache and VectorBT | `REFERENCE_ONLY` / `DROP` / `REPLACE` | PASS — none copied or exposed; Browser uses Gateway/Product contracts only. |
