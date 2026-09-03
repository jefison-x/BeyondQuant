# BeyondQuant

<!-- byq:current-completed-phase=90 -->

BeyondQuant（BYQ）是一个 AI 原生量化研究平台。当前已完成的项目阶段为
**Phase 90**：可靠 LightGBM、自动化通道和按需数据准备均已接入小巴；机器学习 V2 已实现可扩展能力
注册、purged walk-forward、确定性 Ridge JSON、冻结沪深300市场状态、独立专家 ModelBundle、确定性路由，
以及动态 Product API、分页/懒加载模型研究工作台和小巴最小权限入口。内置 Product Feedback 已完成
PostgreSQL 反馈修订、隐私预览、审核/outbox 与分页 Product API，以及隔离、固定仓库、有限重试的
GitHub publisher；Product UI、管理员审核工作台、MCP 与小巴跨回合确认入口现已闭环，普通用户始终无需配置 GitHub。
大范围数据准备按原子分片推进，
后台任务进度可在数据中心持续查看；持久对话在 idle release 或
服务重启后会用新的私有 DSH generation 恢复已完成的公开上下文，继续追问不再复用冲突的 Runtime
身份。策略批准及预测、回测等有后果动作仍由用户分别确认，DSH 不接收 Provider 凭据、模型对象、
raw features、raw predictions 或 raw signals。
Product Runtime baseline 仍保持 Python `0.1.1rc1` / npm `0.1.1-rc.1`。
当前状态以
[`docs/roadmap/STATUS.md`](docs/roadmap/STATUS.md) 为准。

## 项目定位

- Agent 基础：DeepSeek Harness（DSH）
- 领域：BeyondQuant Quant Platform

DSH 是通用 Agent Harness。BYQ 是围绕自身领域不变量、Contract 和产品体验构建的
专业量化领域平台。

BYQ 不 fork DSH。DSH 版本通过明确的依赖策略和兼容性 Contract 固定。BYQ 提供
自己的产品 UI；Agent 与量化领域之间的通信统一经过 BeyondQuant MCP。

## 当前能力

- Browser Product Plane：提供持久化用户名/密码会话和按 owner 隔离的 Product API
  访问。
- Gateway → Runtime Adapter → 固定版本的 DSH JSON-RPC runtime 集成，并使用
  BYQ 自有的规范化 WorkflowTrace projection。
- BeyondQuant MCP 是唯一的 Agent-to-Domain 能力边界。
- PostgreSQL 是 BYQ 唯一的 domain store，并提供逻辑迁移及备份/恢复工具。
- 支持 ResearchTask、Experiment、Artifact、Approval、因子研究、策略草稿/版本、
  确定性的 signal-snapshot Backtest、Stock Pool，以及仅模拟的 Paper Trading 领域。
- 提供 Vue 产品工作区，覆盖研究、策略、Backtest、Stock Pool、Paper Trading、
  资产/设置、Data Center、Plugin Center 和受保护的运维界面。
- 提供按 owner 隔离的加密模型凭证、profile 和 Product Agent binding；规范化的
  workspace 资产传输；以及受平台 Approval 优先级约束的个人 Agent Policy
  preset/rule。
- 九个响应式管理员运维工作台，由有界 Product API projection、规范化 DSH
  runtime/usage 计量及带审计的监控阈值支撑。
- 仅使用 Tushare 的 Data Center：提供加密只写凭证、不可变 `L/P/D` 股票主数据
  snapshot、由 catalogue/Stock Pool 驱动的持久化日线同步任务、真实增量刷新、
  如实的 PostgreSQL coverage 审计，以及由可信交易日历驱动的全市场日同步 worker。
- 在隔离、无凭证的 Pandas 环境中执行信号；冻结规范化 bar，并为已批准的策略版本
  和 Backtest 生成不可变、规范化的 `signal_snapshot` Artifact。
- 基于内容寻址的前复权研究输入，同时保留原始执行 bar、持久化复权因子，并按声明
  日期结算已实现的分红和送转行动。
- 闭合的基准、历史指数成分、日估值和财务指标输入，具备 point-in-time、
  no-look-ahead readiness 及运行前修复能力。
- 独立、无 Provider/模型凭证的可信 LightGBM CPU Worker，使用固定 Python/LightGBM/NumPy
  profile，从冻结股票池和市场输入生成可审计 FeatureSnapshot 与 native-text ModelArtifact。

## 当前限制

- DSH Upgrade Lane 是 Phase 40 之后的维护事项；它不改变当前已验证的 runtime pin。
- conversation-first frontend、personal-workspace 和 Beta Data Center 计划已完成至
  Phase 63。项目仍处于 Beta：ADR-0015 授权 CI-green 的 phase PR auto-merge，
  但在维护者明确下达正式发布任务前，不授权 release-candidate 评审、tag、部署或
  正式发布。team workspace、邀请、共享及商业 control-plane 能力仍不在范围内。

基础 Compose topology 需要 `BYQ_MCP_TOKEN` 等内部服务 secret 和 bootstrap
兼容配置。Provider secret 仍由 Backend/Runtime Adapter 持有，绝不能暴露给 DSH、
MCP、Gateway response 或 frontend code。无密钥 CI 和 smoke test 不得嵌入真实凭证。

参见 [ADR-0002](docs/architecture/adr/ADR-0002-initial-runtime-topology.md)、
[ADR-0003](docs/architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md)、
[DSH 集成方案](docs/architecture/dsh-runtime-integration-options.md)、
[实施计划](docs/roadmap/IMPLEMENTATION_PLAN.md)和
[开发流程](docs/DEVELOPMENT_WORKFLOW.md)。

本项目的架构规则具有规范性。修改前请阅读
[ARCHITECTURE.md](ARCHITECTURE.md) 和 [AGENTS.md](AGENTS.md)。
