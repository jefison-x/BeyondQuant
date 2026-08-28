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
- ADR-0032 定义 Agent 对已持久化 exact-session 估值和 announcement-visible 基本面的
  封闭只读边界、完整性语义和缺失数据行为。
- ADR-0033 定义 Product Agent text-only 最终回答、封闭公共研究术语、领域活动与内部
  control activity 的投影边界。
- ADR-0034 定义真实用户旅程关闭阶段的持久化 Agent 日线读取、面向任务的数据 readiness、
  长任务公开状态、用户任务导向页面和受控跨页面上下文边界。
- ADR-0035 定义普通用户 P3 收口：股票池驱动的有界 readiness、普通页面术语层级和
  ECharts 模块化加载；不扩大 domain/runtime 边界。
- ADR-0037 定义 Product Agent 的双层时间边界：DSH 每轮可信自然时钟，以及 BYQ
  persisted trading-session/data-cutoff 只读投影；两者不得互相推断。
- ADR-0038 定义 Product DSH official plugin 的 AVAILABLE/QUALIFIED/ENABLED 状态、
  capability/risk/Agent assignment、exact qualification、deterministic composition、runtime
  identity 与禁止 online install/self-modification 的治理边界。
