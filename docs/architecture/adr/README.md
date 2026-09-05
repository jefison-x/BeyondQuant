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
- ADR-0039 定义 Market Research Web evidence 的 source、time、claim、research-only Artifact
  promotion 和 Agent least-privilege 边界。
- ADR-0040 定义 Plugin Center desired policy、generated target、active runtime identity 与
  trusted deployment lane 的权限和状态边界。
- ADR-0041 定义指数/动态股票池 definition、trusted materialization 和不可变快照边界。
- ADR-0042 定义 Phase 70 封闭多指数目录、可信同步和精确权重快照完整性。
- ADR-0043 定义 Phase 71–74 的可审计机器学习研究边界、独立 LightGBM 训练、不可变模型
  与样本外预测制品，以及复用现有冻结信号/Backtest 的顺序门禁。
- ADR-0044 定义 Phase 75–79 的版本化产品能力目录、产品帮助技能、固定导航、回测任务 facade、
  机器学习 Agent 接入、逐动作审批和不建设第二工作流的边界。
- ADR-0049 定义 Phase 87–90 workspace-owned Product Feedback、公开预览/隐私去敏、审核与
  transactional outbox、独立固定仓库 GitHub Issue publisher、最小权限凭据和用户零 GitHub 配置边界。
- ADR-0050 定义 Post-Phase 90 的 ML 研究可逆归档、运行证据保留，以及股票池、策略、模型研究、
  回测工作台统一详情管理操作区边界。
- ADR-0051 定义 Agent 人工审批只在全局中心呈现、精确资源绑定、原 durable conversation 幂等续接，
  以及业务页用户主动操作与 Agent approval 分离的边界。
- ADR-0052 定义官方中央 Feedback Hub、匿名 installation relay、中央反滥用/审核/固定仓库发布，
  以及小巴公开预览后只在全局审批中心确认一次并续接原会话的边界。
- ADR-0053 将官方中央 Hub 部署替换为隔离的 Cloudflare Hub/Publisher Workers、D1 transactional outbox、
  per-installation/per-receipt Durable Objects、Queue/DLQ 和 Service Binding，同时保持 ADR-0052 wire contract。
- ADR-0054 定义中央 Hub 的 Cloudflare Workers Builds/GitHub 自动部署、双 Worker project、自动资源绑定、migration-first
  发布、required runtime secret 和仅 `main` 生产部署边界。
- ADR-0055 定义中央 Hub operator 审核控制台、Cloudflare Access + Hub session 双层保护、短期 HttpOnly Cookie、
  same-origin mutation、无持久浏览器 secret 和保持隔离 Publisher 为唯一 Issue writer 的边界。
- ADR-0056 将 Cloudflare Access 改为可选增强，并定义中央管理员密码直登、按来源 HMAC 分片的持久登录节流、
  v2 session 签名和密码轮换失效边界。
