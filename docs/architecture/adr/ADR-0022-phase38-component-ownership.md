# ADR-0022：Phase 38 Operations Component Ownership

- Status: Accepted
- Date: 2026-08-22
- Decision scope: Phase 38 Operations workbench 与 Phase 40 shared-component gate
- Related: ADR-0012、ADR-0015、ADR-0016、ADR-0018、ADR-0019

## 背景

Community full-parity plan 原先将 Phase 40 shared component 描述为 Phase 38
prerequisite；但 Phase 40 同时是排在 Phase 38/39 之后的最终 parity-closure Phase。这会
形成 circular delivery gate：Phase 38 不能在 Phase 40 前开始，而 Phase 40 又不能在
Phase 38 完成前进行 final closure。

Phase 36/37 已安全解决同类 ownership 问题：每个 Phase 持有其 acceptance criteria 所需
specific component，Phase 40 只负责 extract/generalize 已验证 reusable component。
Phase 38 实现前需要相同明确规则。

ADR-0019 已 Accepted。因此，Phase 38 剩余 prerequisite 是 Backend projection、Product
API authorization、audit Contract、Community inspection/classification 和真实 browser
evidence，而不是由后续 Phase 执行 generic component extraction。

## 决策

1. Phase 38 持有替换 placeholder 并满足 acceptance criteria 所需的 Operations-specific
   view/component。
2. Phase 40 不是 Phase 38 prerequisite。Phase 40 可 extract/consolidate/generalize Phase
   38 已验证 component，但不能仅为通用化 component 而改变 Product API 或 security
   boundary。
3. Phase 38 必须在适用处复用 existing BYQ base component；不得创建 speculative generic
   component library 或复制 Community component architecture。
4. 所有 Operations browser request 仍只使用 Gateway/Product API。Read-only projection
   必须真实且有界；每个 write action 必须明确由 RBAC 保护、audited、在适用时
   idempotent，并 fail closed。
5. Community Redis assumption 替换为 PostgreSQL market-data cache status。Product DSH
   不获得 database、runtime-control、credential-read、application-source 或 deployment
   authority。
6. Data-source credential CRUD 和 data-sync execution 保持 Phase 39 scope。Phase 38 可
   显示有界 configuration/readiness status，但不得吸收 Phase 39 或暴露 secret。
7. DSH model-call budget projection 必须使用 normalized BYQ accounting。Raw DSH event
   schema、hidden reasoning、tool argument 和 provider secret 不得越过 Runtime Adapter/
   Gateway boundary。

## 后果

- 消除 Phase 38/40 circular dependency，且不削弱 Phase 38 acceptance criteria。
- Phase 38 可在 ADR-0019 后使用 Phase-owned Operations component 开始。
- Phase 40 保持 final shared-component/parity-closure Phase，只能 generalize 已在 Product
  flow 验证的 implementation。
- Phase 38 仍是大型 Phase，必须在一个 isolated Phase worktree/PR 中，以 contract-first
  slice 交付，不能用 placeholder 冒充完成。

## 必需实现证据

- Code 前 inspect/classify Community Operations page/component；
- admin/role denial、audit、secret-redaction 和 bounded-projection test；
- 每项 Operations projection/action 的 Backend/Product API contract test；
- Browser 不直接调用 Backend、DSH、MCP、PostgreSQL、Redis 或 provider；
- 真实 Product API desktop/mobile Chrome MCP review 和 feature checklist；
- 标准 architecture、unit、contract、integration 和 local CI check。

## 拒绝的替代方案

- 在 Phase 38 前执行 Phase 40：破坏 ordered phase source of truth，并要求 final closure
  generalize 尚不存在的 component。
- 让 Phase 38 持续阻塞于 Phase 40：保留 circular dependency。
- 不通过 ADR 就豁免 shared-component concern：与 `STATUS.md` 和开发流程中的明确 blocker
  冲突。
- 复制 Community workbench：引入 obsolete topology、Redis assumption、不安全 direct
  control API 和不兼容 authorization semantics。

## 回滚

如果 Phase-owned component 不合适，停止 Phase 38，并通过 superseding Accepted ADR 恢复
gate。不得静默将 Operations authority 移入 Browser、DSH 或 generic component abstraction。
