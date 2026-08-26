# Architecture Decision Records

Architecture Decision Record（ADR）记录改变或澄清持久系统边界的决策。以下边界的
变更必须取得 ADR：

- DSH boundary
- MCP boundary
- Database boundary
- WorkflowTrace
- Authentication
- Engineering Plane
- Container topology
- Strategy runtime
- Data-provider abstraction
- Artifact / Approval semantics

每份 ADR 应说明背景、决策、后果、相关备选方案，以及迁移或回滚考虑。任何偏离
`ARCHITECTURE.md` 的例外都 MUST 在实现前取得 ADR。

当前与 Phase 相关的 Accepted 决策也列在 `docs/roadmap/STATUS.md` 中：

- ADR-0020 定义 Phase 34 的 Stock Pool identity、不可变 snapshot、lifecycle 和
  cross-domain reference 边界。
- ADR-0021 定义 Phase 35 的 Paper Trading account、settlement、risk、ledger 和
  portable bundle 边界。
- ADR-0018 定义 Phase 36 的结构化 WorkflowTrace card、public activity、
  normalization、authority、replay 和固定 Product action 边界。
- ADR-0019 定义 Phase 37 和 39 的加密 credential storage、key rotation、public
  masking、model binding/runtime resolution、Tushare resolution、audit 和
  bootstrap fallback 边界。
- ADR-0024 定义 Phase 42-48 的 conversation-first Product shell、持久化 BYQ
  conversation catalog 与 DSH Session 的边界、route-backed settings 整合，以及
  持久化 semantic appearance/theme Contract。
- ADR-0025 将 personal workspace 定义为 BYQ tenancy/authorization 边界，分离
  resource ownership 与 actor identity，固定 trusted context propagation 和经过验证
  的 compatibility migration，并明确将 team product 能力延后到后续 ADR。
- ADR-0026 定义 Beta security-master snapshot、有界 catalogue Product API、冻结的
  daily-bar selection 和真实增量同步边界。
- ADR-0027 定义 calendar-driven 全市场日自动化和可信 Data Worker 边界。
- ADR-0028 定义 lifecycle-aware readiness、有界 repair 和不可变 ready input。
- ADR-0029 定义 adjusted research view、raw execution price 和已实现 corporate-action
  settlement semantics。
- ADR-0030 定义冻结的 benchmark performance、point-in-time index membership，以及
  封闭的 strategy-declared valuation/fundamental research input。
- ADR-0031 定义 Agent owner-scoped Stock Pool 动作边界、唯一 StrategyDraft 合同、
  有界校验反馈与单次 repair 约束。
