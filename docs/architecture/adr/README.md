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

Proposed 只允许规划/验证，不授权越界实现。Accepted 必须记录维护者对精确 decision scope 的
接受证据；通用“继续开发”不能接受未说明的新边界。替代旧决策必须声明 Supersedes 的具体条款，
历史事实保留并标明不再作为当前通用规范。ADR-0059 统一开发权限、任务分流与 CI 证据门禁。

当前与 Phase 相关的 Accepted 决策也列在 `docs/roadmap/STATUS.md` 中：

- [ADR-0085](ADR-0085-deterministic-research-continuation.md)（Accepted，2026-09-22）针对真实复合研究
  接续失败，提议由 BYQ 持久化机器可执行的领域 next-action 计划和统一事件 reducer；确定性领域转换
  不再启动通用模型回合，研究判断才使用最小有界 DSH 回合，同时收窄 Product Agent 的完整信号快照
  读取。维护者已接受完整决定并授权按 P0→P4 每步独立 PR 实施；该授权不启动 0.10.0。

维护决策：[ADR-0066](ADR-0066-domain-validation-call-admission.md) 已于 2026-09-08 获维护者接受，
为 F7 增加精确领域调用归属与持久纠错准入；先完成隔离资格验证再接入首批两工具，不推进 Product Phase。

后续维护决策：[ADR-0067](ADR-0067-root-scoped-runtime-call-identity.md) 已于 2026-09-08 获维护者接受，
针对官方 MCP 缺少逐调用根身份采用根回合隔离进程；实现、连续对话及生命周期资格仍需验证。

- ADR-0063 允许禁用身份后对精确绑定的既有 AgentRun 做可信终态清理及原子审计/回执，不恢复普通访问或业务续接。
- ADR-0064 允许持久化最小 BYQ 执行证据，并仅在原执行者失效可证明时恢复收尾；不恢复模型或研究。
- ADR-0074 定义 0.10 的数据基准与资格调查边界：先冻结数据基准合同，HIST 只做调查、深度只做环境资格，
  不实现数据扩容、不引入 HIST、不授权 GPU/有限调参/新 Worker 拓扑。
- ADR-0077（Accepted）在既有任务绑定续接合同内增加数据就绪自动续接：`completed` signal job 且
  产出 `validated signal_snapshot` 时经既有事件身份/账本/Gateway 消费者生成至多一个有界续接回合；
  不改数据面、sandbox、模型许可或无关服务，已于 2026-09-19 获维护者接受并成为当前规范。
- ADR-0078（Accepted）定义 reboot 后对 stale lifecycle-journal lease 的显式、可审计、可逆
  re-lease（只改 `lease_identity`，保留全部证据；fail closed；附审计/manifest），并提议以
  boot 无关的稳定执行者身份 + 单调 epoch + 显式 takeover 作为持久修复；已于 2026-09-19
  获维护者接受，`409 stale_session_lease` 分类与归档工具不变。
- [ADR-0079](ADR-0079-runtime-continuity-and-session-recovery.md)（Accepted）定义 Runtime Continuity 六层生命周期（Conversation/AgentSession/Run/
  RuntimeGeneration/TerminalAttachment/DurableJob）与故障矩阵，并实现 R1：以稳定
  `deployment_id` + 卷拥有、可审计 takeover 的单调 `executor_epoch` 取代 boot-bound lease，
  v3→v4 journal 在首次受控 claim 迁移且保留全部证据；`reanchor` 保留为异常修复工具。
  Supervisor/Terminal/DurableJob 为后续阶段，见
  [故障矩阵](../RUNTIME_CONTINUITY_FAILURE_MATRIX.md)。
- ADR-0080（Accepted）定义 release 制品 secret 边界：manifest、target/rollback overlay、
  resolved private config、retained-artifact copy 与备份 MUST NOT 含明文 secret 值，
  只保存 `${ENV_NAME}` 引用；真实值部署时从受保护、非仓库来源（`0600` 宿主 `.env`
  或等价 secrets 来源）注入，并由 `scripts/dsh/release_secrets.py` guard 与部署前
   `verify_injection` fail closed。既有 release 目录/备份不改写、不轮换 token、不改拓扑；
   已于 2026-09-19 获维护者接受。
- [ADR-0081](ADR-0081-dsh-native-continuity-and-d15-stage.md)（Accepted）冻结 R3（非回滚）为
  `PAUSED_PENDING_DSH_015_NATIVE_CONTINUITY_QUALIFICATION`，新增 DSH 原生连续性资格阶段
  D15（D15-0..D15-G），要求凡 DSH 0.1.5 原生覆盖的能力（Session V3 迁移、SessionHandle
  持久化、写租约、continuable subagent、persistent terminal）BYQ 只适配/观测/降级而不
  另建；重定义 R3 Thin Runtime Supervisor、R4 TerminalAttachment、R6 全量连续性资格并
  排序 `R0→R1→R2→D15→R3→R4→R5→R6→独立 Production Go/No-Go`；已于 2026-09-19 获维护者接受。

- [ADR-0082](ADR-0082-dsh-continuable-child-resume.md)（Accepted，2026-09-21，**modified**）记录 0.9 严格顺序
  第 4 步维护者决定：**只选 Option 1**——未来由 DSH 提供独立进程 continuable provider /
  `prepareContinuable`；通用子会话恢复与独立子崩溃恢复归 **DSH**。**Option 2（BYQ runtime-adapter
  child-resume bridge）被拒**（当前架构方向），BYQ 不建第二个 session store、不建通用 agent harness。
  接受不代表实现：`subagent-child-crash` / `subagent-byq-adapter-restart` 等 blocker 在合格进程外 provider
  出现并通过资格前保持 `BLOCKED`。决定记录见
  [v090-adr-decisions](../../evidence/v090-adr-decisions/README.md)（非 GitHub approval）。
- [ADR-0083](ADR-0083-terminal-attachment-boundary.md)（Accepted，2026-09-21，**as proposed**）记录同一步决定：
  BYQ 只持久化 `TerminalAttachment` identity/permission/generation/epoch/state，并经 Gateway/Product API 暴露
  **有界**接口；**DSH 继续拥有 PTY/shell/IO**；原生 process-local 状态丢失时 MUST 真实报告
  `lost`/`interrupted`，绝不伪造 `reattached`；**不承诺**跨 runtime restart 的 PTY 连续性。接受只授权候选级、
  可逆的 D15-G 资格路径，不切换生产 selector；未实现。决定记录同上。
- [ADR-0084](ADR-0084-gate-classification-and-external-dependencies.md)（Accepted，2026-09-21）
  将门禁分为 Safety/Integrity、Feature、Promotion/Release 与 External Qualification，并要求每项
  声明阻塞对象；B1/B2 保持 `BLOCKED_EXTERNAL`，但不再冻结 0.9、候选兼容、受限 R3 失败隔离或
  无关路线。当前替代硬门禁是 BYQ session failure containment and business recovery；历史 D15
  verdict 不改写，生产 selector/部署/release 仍独立授权。


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
- ADR-0057 定义回测可读名称与稳定 ID 的分离、PostgreSQL forward repair、名称/ID 双字段目录和
  名称不进入不可变输入及结果身份的边界。
- ADR-0058（Accepted，2026-09-06）定义 DSH release bundle、兼容适配、候选隔离、资格、晋升与
  回滚边界；ADR-0084 后外部可选能力只阻塞其能力声明，仍不代表生产 selector 已切换。
- ADR-0059 定义规则归属、隔离工作树、基于源码的 CI 与精确提交的合并/部署权限门禁。
- ADR-0060 定义个人非商业研究且禁止实盘的源码公开许可、贡献/第三方权属、GitHub 托管 CI，
  以及仅用于一次发布准备 PR 的具名过渡例外。
- ADR-0061 定义保留历史 release 身份不变的 U6 独立 BYQ 构建修订和重新认证，不授权生产部署。
- ADR-0062 定义 Post-U8 未回答需求及失败事实恢复、活动续租、持久提交回执、任务绑定的有限
  后台续接和指数池修复边界；已接受，并具名修订 ADR-0045/0046，不授权生产部署或数据扩容。
- ADR-0065 定义任务后台续接的累计预算准入、持久预留、未知结算及官方接口全调用覆盖资格；
  已接受，但尚未证明可启用后台执行，不授权升级/fork DSH 或安装未合格扩展。

- ADR-0068 按维护者明确授权免除当前及之后所有开发步骤的 Community 原实现检查；
  保留只读保护、主动复用分类与真实数据迁移验证。
