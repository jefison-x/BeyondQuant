# BeyondQuant 架构

本文档是 BeyondQuant（BYQ）的规范性架构边界。标为 MUST 或 MUST NOT 的规则属于
架构约束。任何例外都必须在实现前取得 ADR。

## A. 总体架构

BeyondQuant 分为五个逻辑 Plane：

1. Product Plane
2. Agent Plane
3. Quant Domain Plane
4. Data Plane
5. Engineering Plane

预期产品路径为：

```text
User
  ↓
BYQ Frontend
  ↓
BYQ Gateway
  ↓
DSH Runtime Adapter
  ↓ official SDK / stdio JSON-RPC
DSH + dsh-byq Product composition
  ↓
BeyondQuant MCP
  ↓
BYQ Domain
  ↓
Data / Factor / Strategy / Backtest
```

Engineering Plane 与 Product Plane 分离：

```text
Engineering DSH
  ↓
Codex Subagent
  ↓
isolated Git worktree
  ↓
tests
  ↓
Draft PR
```

Product Plane conversation MUST NOT 通过普通 prompt escalation 获得 Engineering
Plane privilege。

Gateway MUST 通过专用 Runtime Adapter 与 DSH 通信。Gateway MUST NOT 持有 DSH
subprocess、import DSH SDK 或解析 raw DSH event/notification schema。Adapter 持有
official SDK 边界、runtime process lifecycle，以及向 BYQ framework-neutral
Contract 的转换。DSH Web surface MUST NOT 用作 Gateway transport。

## B. DSH 职责

DeepSeek Harness（DSH）负责通用 Agent 基础设施：

- Agent Loop
- Session
- Context
- Compaction
- Skills
- Presets
- Subagents
- Generic Workflow
- Web Search / Fetch
- Tool Registry
- MCP Client
- Generic Guards
- Generic Human Interaction
- Code Runtime infrastructure

当 DSH 能提供这些通用能力时，BYQ MUST NOT 重复实现。替换或重复实现必须通过 ADR
说明具体必要性及兼容性影响。

## C. BYQ 职责

BYQ 独占量化和产品领域能力，包括：

- A-share semantics
- Market data abstraction
- Tushare integration
- Factor definitions
- Factor computation
- Strategy definition
- Strategy validation
- Backtest execution
- ResearchTask
- Experiment
- Artifact
- Business Approval
- RBAC
- Audit
- WorkflowTrace
- Quant Research Methodology
- Domain invariants
- Business idempotency

DSH MUST 保持 domain-agnostic。量化 domain invariant MUST 由 BYQ Contract 和 service
强制执行，不能只依赖通用 Agent prompt。

## D. MCP 边界

BeyondQuant MCP 是 Agent Plane 与 Quant Domain Plane 之间唯一稳定的能力边界。

DSH MUST NOT 直接访问 BYQ PostgreSQL。

DSH MUST NOT 为 BYQ business state 直接访问 Redis。

DSH MUST NOT 直接 import BYQ backend internal。

Agent-to-Domain 通信 MUST 经过 BeyondQuant MCP。MCP surface MUST 暴露领域能力和
validation Contract，而不是 storage internal。

## E. Strategy-code 边界

面向用户的 Agent 生成的 Strategy code 属于 Domain Artifact，不是 Application
Source Code。

预期策略流程为：

```text
Agent
  ↓
StrategyDraft Artifact
  ↓
validate_strategy
  ↓
Business Approval if needed
  ↓
Backend
  ↓
Backtest Worker
```

Product Agent MUST NOT 直接写入 `services/backend` source code。生成的 Strategy
MUST NOT 保存为 BYQ application source。Strategy Artifact MUST 具备明确的
ownership、validation、provenance 和 approval semantics。

## F. Workflow 边界

DSH Workflow 负责 research orchestration、subagent、tool orchestration 和通用 Agent
execution。

BYQ Domain Workflow 负责 Artifact state、Approval state、Backtest job state、
Experiment lineage、ResearchTask lifecycle 和 business idempotency。

两者是独立的 state machine，MUST NOT 合并成一个隐式 Workflow model。DSH run 可以
产生 BYQ domain event，但不持有由此产生的 business state。

## G. Workflow 可视化

Frontend MUST NOT 直接依赖 DSH event schema。

必须遵循的转换路径为：

```text
DSH Event
  ↓
BYQ Gateway
  ↓
BYQ WorkflowTrace Contract
  ↓
Frontend
```

WorkflowTrace 是 framework-neutral 的 BYQ Contract。如果替换 DSH，Frontend MUST
NOT 仅因 framework event schema 改变而需要重新实现。

WorkflowTrace SHOULD 能表示：

- Agent nodes
- Subagent nodes
- Tool nodes
- Artifact
- Approval
- Backtest
- Experiment
- Errors
- Repair
- Completion

## H. Browser 和 Web 边界

一般 Web research 中，BYQ SHOULD 优先使用 DSH Web Search / Fetch。BYQ MUST NOT
成为第二套通用 browser-agent framework。

如后续需要真实 browser 能力，SHOULD 将其实现为独立 DSH web-browser plugin。
Chrome / Chromium、CDP 和 Playwright 是可接受的实现技术，但该 plugin MUST NOT
成为 BYQ Core。

## I. Product source-code 保护

这是最高级别的安全架构边界。

Production Product DSH：

- MUST NOT mount BeyondQuant source repository。
- MUST NOT 暴露 source-editing tool。
- MUST NOT 暴露 Git write tool。
- MUST NOT 暴露 Engineering Codex 能力。
- MUST NOT 允许普通 conversation 将自身提升为 Engineering privilege。

如果普通用户要求 Product Agent 修改 BYQ source code，Product Agent MAY 解释、分析
并生成 EngineeringTask，但 MUST NOT 直接修改 source code。

## J. Engineering Plane

Engineering Plane 是独立安全域，可以：

- 分析 bug
- 分析 metric
- 检测 regression
- 提出改进
- 修改 code
- 运行 test
- 创建 Draft PR

Engineering Plane MAY 使用隔离 Git worktree、feature branch、DSH coding tool、Codex
subagent、test、lint、integration test、contract test 和 E2E test。

Engineering Plane MUST NOT：

- 直接 push 到 `main`
- force push
- 直接部署到 production
- 执行自动 destructive database migration
- 在初始运行模型下自动 merge

Engineering agent MUST 使用 disposable worktree，例如
`/home/jefison/projects/.byq-worktrees/`，不得直接修改
`/home/jefison/projects/BeyondQuant`。

## K. Agent 与 execution

不得仅因角色名称不同就将 Agent role 分别容器化。Chief Quant Researcher、Market
Researcher、Fundamental Researcher、Quant Researcher、Strategy Designer、Strategy
Optimizer、Backtest Analyst 和 Quant Verifier 等角色 SHOULD 表示为运行于 DSH
runtime 的 DSH Preset、Skill 或 Subagent。

execution capability 可以独立容器化：

- backend
- mcp
- backtest-worker
- data-worker
- postgres
- redis
- optional browser worker
- optional engineering agent

## L. Container 原则

Phase 12 Backtest 使用 BYQ 自有的确定性 signal-snapshot engine。Backtest worker 可以
独立部署，且只接收持久化 job identity；它不执行 strategy source，不访问 DSH state，
也不访问 provider credential。完整 result 是由 Backend/Domain Plane 持有的不可变
object reference，而 business job state 留在 BYQ storage。

Phase 13 quant role 使用 DSH Preset、Skill 和 official subagent seam。role allowlist、
owner/actor authorization、approval state、audit record 和 evidence promotion 仍是通过
MCP 访问的 BYQ 自有 Contract。DSH 不获得 business storage access、provider
credential、application source access 或自行批准 consequential action 的权限。

未来 core component MUST 能够独立部署、独立升级且故障隔离。

目标产品 topology 为：

```text
frontend
gateway
runtime-adapter
mcp
backend
backtest-worker
data-worker
postgres
redis
```

Phase 5 DSH Web bootstrap 仅用于 diagnostic profile，不是 Gateway request transport。
Product request 使用 Gateway → Runtime Adapter → owned stdio JSON-RPC DSH → MCP。

Engineering Plane 独立存在：

```text
engineering-dsh
```

本文档只定义 topology 原则，不授权在初始化 Phase 创建 container。

## M. DSH 依赖策略

DeepSeek Harness 预计会快速迭代。BYQ MUST：

- 固定准确的 DSH 版本。
- 禁用自动 latest-version upgrade。
- 在集成需要时维护 compatibility adapter。
- 为 adapter 和 MCP boundary 维护 contract test。
- 每次 production upgrade 前运行 upgrade test。

BYQ MUST NOT fork DSH。fork 需要新的架构决策和明确的 governance review。

## N. Quant Learning

BYQ 后续可以建立 Quant Learning Loop：

```text
ResearchTask
  ↓
Experiment
  ↓
evidence
  ↓
validated lesson
  ↓
candidate Quant Skill
  ↓
review
  ↓
BYQ Quant Skill
```

普通 chat content MUST NOT 直接成为可信量化知识。Lesson 需要 evidence、validation、
review、provenance 和受控的 promotion path。

## O. Engineering Learning

BYQ 后续可以建立 Engineering Learning Loop：

```text
Trace / Metrics / Error
  ↓
Problem hypothesis
  ↓
EngineeringTask
  ↓
isolated code change
  ↓
tests
  ↓
Draft PR
```

软件演进 MUST 可验证、可审计、可逆。Engineering learning MUST NOT 绕过 worktree
isolation、test、review 或 branch protection。

## P. Product Feedback 与外部 Issue 发布

Product Feedback 是 BYQ-owned、workspace-scoped domain record，不是 EngineeringTask，也不授予
source、Git、PR、CI、merge 或部署权限。Browser MUST 只经 Gateway/Product API 访问反馈；Product
Agent MUST 只经 BeyondQuant MCP 提出、预览、提交或查询 owner-scoped feedback。

Draft/revision MUST 保持 workspace-private。用户显式提交后，只有经其确认的最小化脱敏 snapshot 可由
platform feedback moderator 读取；moderator authority 不构成该 workspace membership，也不能读取其他
workspace resource。

公开 GitHub Issue 是经过用户确认、Backend 脱敏和管理员策略/审核后的外部副作用。Product DSH、
Frontend、Gateway、MCP 和 Backend MUST NOT 持有 GitHub credential 或直接创建 Issue。唯一 writer
是 ADR-0049 定义的独立 `feedback-publisher`：它 MUST 只 claim 有界 transactional outbox，只访问
固定 GitHub origin/repository 的 Issue API，并且 MUST NOT 挂载源码/Git/Docker socket、访问
PostgreSQL、使用 DSH/Codex 或获得 Contents/Pull requests/Actions 权限。

普通 Product 用户 MUST NOT 被要求提供 GitHub 账号或 credential。Publisher 未配置或不可用时，
内部 feedback persistence、审核和查询 MUST 继续工作，且不得伪造发布成功。

ADR-0052 的默认开源路径使用 local transactional Hub outbox → 独立 HTTPS relay → 官方 Central Feedback Hub。
Hub 只能接收不可变公开候选快照，并以匿名 installation HMAC 限流/去重；不得接收用户、workspace、session、trace、
聊天全文或本地数据库访问。中央审核通过后，只有中央隔离 publisher 可写固定 `jefison-x/BeyondQuant` Issues。
小巴提交必须绑定全局审批中心中的精确 feedback resource；批准后续接原会话，不在业务页重复审批。

ADR-0053 的官方 Central Feedback Hub 使用 Cloudflare Hub Worker + D1/分片 Durable Objects/transactional outbox，
经 Cron/Queue/DLQ 投递给第二个不可公开的 Publisher Worker。Hub MUST NOT 持有 GitHub App credential；Publisher
MUST NOT 绑定 D1、Product Backend、源码、Git、Docker 或 DSH，只能通过带 service token 的 Worker Service Binding
claim/complete/retry 固定 outbox。Queue 不是权威状态，免费额度或消息过期不得删除 local/D1 outbox。

ADR-0054 允许 Cloudflare Workers Builds 直接读取官方 GitHub 仓库并只从 `main` 自动部署这两个 Worker。Hub 与 Publisher
MUST 保持两个独立 Cloudflare project、独立 runtime secret 集和独立 deploy command；不得为了单按钮部署把 GitHub credential
并入公网 Hub。Cloudflare source integration 不得成为 GitHub Issue writer或绕过 `main` 的 PR/CI merge gate，也不授予
Product、DSH 或 PostgreSQL 权限；runtime secret 不得作为 GitHub/Workers build variable、文件或仓库内容传递。

ADR-0055/0056 的中央审核控制台属于 Hub operator surface，不是 BYQ Product 页面。Hub MUST 以加密管理员密码、按
`CF-Connecting-IP` HMAC 分片且可重启的登录节流，以及短期管理员会话/Bearer 保护 `/v1/admin/*`；Cloudflare Access MAY
作为 MFA/IdP 外层增强，但不是默认运行依赖，且不得阻断公开 intake/status/health。管理员密码和原始 IP MUST NOT 写入前端
资源、URL、持久应用浏览器存储、Cookie、D1 或 BYQ application log；session 必须由独立高熵 secret 派生并绑定密码版本。
Issue 写入仍只能由隔离 Publisher 完成。

## 治理

DSH boundary、MCP boundary、database boundary、WorkflowTrace、authentication、
Engineering Plane、container topology、strategy runtime、data-provider abstraction，
或 Artifact / Approval semantics 的变更必须取得 ADR。参见
`docs/architecture/adr/README.md`。
