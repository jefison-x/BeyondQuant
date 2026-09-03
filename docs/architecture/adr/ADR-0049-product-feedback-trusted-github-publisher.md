# ADR-0049：内置 Product Feedback 与可信 GitHub Issue Publisher

- Status: Accepted
- Date: 2026-09-03
- Accepted: 2026-09-03
- Decision scope: Phase 87–90 内置反馈、隐私、审批/outbox 与固定仓库 GitHub Issue 发布边界
- Related: ADR-0011、ADR-0012、ADR-0015、ADR-0019、ADR-0024、ADR-0025、ADR-0038、ADR-0044

## 背景

开源用户需要在产品中直接报告缺陷、性能问题和需求，而不必理解仓库、Issue 模板或 GitHub
账号配置。维护者也希望这些结构化报告能进入项目的 GitHub Issues，形成持续改进闭环。当前
BeyondQuant 只有 EngineeringTask 记录和仓库级 Issue 模板：前者属于隔离 Engineering Plane，
不向 Product 暴露；后者要求用户离开产品并自行使用 GitHub。Product DSH、小巴、Gateway 和
Backend 都没有 GitHub mutation 权限，这是必须保持的安全边界。

只读 Community 仓库提供两项有效证据：可复现缺陷应包含有界环境和最小脱敏复现；安全漏洞、
Token、Cookie、完整日志、真实用户资产和供应商受限数据不得进入公开 Issue。Community 没有可迁移
的 Product Feedback domain、审批/outbox、publisher 或身份隔离实现；其 Markdown 模板只作
`PORT_UX`/`PORT_TESTS` 证据，旧 Agent/API/runtime 均不复制。

GitHub 官方 REST 合同允许 GitHub App installation token 或 fine-grained token 创建 Issue，最小
repository permission 为 `Issues: write`。GitHub App 默认无权限，并建议只授予所需最小权限。因此
普通用户不应提供个人 GitHub 凭据；部署维护者只需为固定目标仓库进行一次服务级安装/配置。

## 决策

### 1. BYQ 持有独立的 Product Feedback domain

Backend/PostgreSQL 持有 workspace-scoped `ProductFeedback`、不可变 revision、审核记录、发布快照和
transactional outbox。它不是 EngineeringTask，也不会自动授予代码修改、Git、PR、CI、部署或
Engineering DSH 权限。反馈类别为封闭集合：`bug`、`feature`、`performance`、`usability`、`other`；
安全漏洞必须转向独立 private security channel，不能进入公共发布队列。

正常用户可创建草稿、更新自己的未提交草稿、显式提交、查询自己的状态和撤回尚未排队的反馈。
草稿和历史 revision 始终只有 workspace owner 可见。显式提交会生成一份 immutable、最小化且脱敏的
`submitted feedback snapshot`，用户确认把这一份内容披露给 platform feedback moderator；moderator 只能
分诊这份提交快照、拒绝/合并重复项、编辑公开发布快照并批准发布，不能借此读取 workspace 草稿、其他
资产或用户身份。初始 moderator authority 使用 authenticated admin role 的专用 feedback route，并不授予
该 admin 对用户 workspace 的 membership。所有 authority 来自 durable BYQ identity、trusted workspace
context 和 RBAC，不接受 Browser/model 提供 owner、workspace、审核或发布状态。

### 2. 状态与发布是两个相关但分离的状态机

反馈生命周期为：

```text
draft -> submitted -> triaged -> accepted | rejected | duplicate | withdrawn
```

GitHub 发布生命周期只对 `accepted` feedback 存在：

```text
not_queued -> queued -> publishing -> published
                         |            |
                         +-> retry_wait|failed_terminal
```

状态转换、revision 和 outbox enqueue 在一个 PostgreSQL transaction 中完成。发布重试绝不把反馈
倒退成草稿或伪造 Issue 已创建。`published` 必须持久化目标 repository identity、Issue number、
canonical public URL、provider response identity 和 publication snapshot hash。

### 3. 隐私优先，公开内容来自不可变脱敏快照

产品不自动上传聊天全文、Prompt、WorkflowTrace、完整日志、数据库行、策略源码、用户资产、持仓、
凭据、header、内部路径或 Provider 原始数据。诊断上下文必须逐项 opt-in，并先经过 allowlist、大小限制、
secret/identity redaction 和用户预览。Backend 再执行同一套 fail-closed 验证，不能信任前端脱敏。

提交前必须明确提示提交快照将由 platform moderator 读取且 GitHub Issue 可能公开。公开快照不含 BYQ
user/workspace/session/trace 内部 ID、邮箱、
IP 或原始 User-Agent；只保留有用的产品版本、组件、部署形态、浏览器/OS 大类、复现步骤、预期/实际
结果及经过脱敏的有界诊断。安全疑似、命中高置信 secret、无法安全规范化或超限内容拒绝公共排队，
由用户修订或管理员走 private channel。

### 4. 去重、滥用与审计属于 BYQ invariant

Backend 对规范化类别、组件、标题、复现语义和版本生成 `feedback_fingerprint.v1`。同一 workspace 的
idempotency key 防重复写；跨 workspace 相似反馈只向管理员显示候选，不泄漏另一用户内容。管理员可将
反馈标为 duplicate 并关联内部 canonical feedback；公开投影只在对应 Issue 已发布后显示公共链接。

限制包括每用户/workspace 时间窗配额、最大草稿/文本/步骤/诊断字节、固定枚举、禁止附件和任意
repository/endpoint/label/assignee/milestone。每次创建、修订、提交、分诊、拒绝、合并、排队、claim、
重试和发布结果均追加 secret-free audit。发布失败按分类退避并有最大尝试数；GitHub rate limit、`410`
issues-disabled、认证错误和 validation/spam 响应均如实记录为有界错误，不进行无界循环。

### 5. 独立 trusted publisher 是唯一 GitHub writer

新增最小权限、无交互的 `feedback-publisher` worker。它不属于 Product DSH，不使用 DSH，不挂载源码/
Git worktree/Docker socket，不持有 PostgreSQL URL，不运行 shell/Git/Codex，也不能创建 PR 或修改代码。
它只通过 Backend internal lease/result API claim 已批准 outbox，并只调用固定 GitHub API origin 和部署
配置中固定的一个 repository。

首选 GitHub App installation credential：仅目标 repository、`Metadata: read`（GitHub App 隐含的基础
repository metadata）和 `Issues: write`，不授予 Contents、Pull requests、Actions、Administration、
Secrets、Deployments 或 Organization 权限。Fine-grained service token 只作为 self-hosted bootstrap
fallback，必须同样限定单仓库和 Issues write。凭据只注入 publisher，绝不进入 PostgreSQL、Backend、
Gateway、MCP、DSH、Browser、日志、错误或健康响应。

Publisher 只允许 `POST /repos/{fixed_owner}/{fixed_repo}/issues`；Phase 87–90 不实现 arbitrary API、
comment/update/close、label create、assignee 或 milestone mutation。标题/body 由 BYQ 版本化 renderer 从
不可变 publication snapshot 生成；repository、origin 和 route 不能来自反馈内容。每个 outbox event 使用
稳定 marker 和 snapshot hash，网络不确定后先按 marker 进行受限 reconciliation，再决定重试，避免重复 Issue。

### 6. 近零用户配置与明确降级

普通用户永远不填写 GitHub 用户名、Token、App、repository 或权限。官方托管部署可由项目维护者预配置；
self-hosted 部署只需 operator 一次性安装 GitHub App（或配置单仓库 fine-grained service token）以及固定
repository。缺少/失效 publisher 配置时，内部反馈创建、查询、分诊和审批继续工作，发布状态明确为
`publisher_unconfigured`/`retry_wait`，不丢反馈、不伪造 GitHub URL、不向用户索取个人凭据。

管理员 Product API 只显示 `configured`、credential kind、固定 repository identity、last success/error
类别和 queue counts；不回显 credential、App private key、installation token 或 environment value。

### 7. Browser 与小巴边界

Frontend 只调用 Gateway `/api/product/feedback` 投影。小巴只经 BeyondQuant MCP 使用反馈草稿/提交/查询
工具：可以根据对话提出结构化草稿，但必须展示公开预览并取得用户明确确认后才能提交；小巴不能分诊、
批准、排队或发布，也看不到其他 workspace 反馈。Product DSH 不接收 GitHub 凭据、publisher internal
API 或 EngineeringTask capability。

### 8. 串行交付

- Phase 87：只接受本 ADR、规范合同、Community 分类和 Phase 88–90 gate，不修改 runtime/schema/API/UI；
- Phase 88：实现 durable Feedback domain、Product API、审核/outbox 和迁移/安全测试，不连接 GitHub；
- Phase 89：实现独立 publisher、GitHub adapter、credential/config、reconciliation 与 Compose 运维，不开放
  普通用户 Browser/Agent mutation；
- Phase 90：完成 Product UI、小巴/MCP、真实 Product API、浏览器、重启、双用户、性能与无凭据降级闭环。

每阶段独立 worktree、branch 和 PR；前一阶段 CI-green 合并并部署验证后才能开始下一阶段。

## 验收与停止条件

- 证明普通用户零 GitHub 配置，publisher 缺失时内部反馈仍可用；
- 证明 Browser only Product API、Agent only MCP、publisher only fixed Issue create route；
- 证明跨 workspace 拒绝、管理员审核、transactional outbox、lease/fencing、幂等/reconciliation、重启恢复；
- 证明 secret/PII/安全报告/超限内容无法进入 public snapshot，请求/日志/审计/错误无 credential；
- 证明 publisher image 无源码/Git/Docker/DB/DSH 权限，GitHub credential 不进入其他容器；
- 使用本地 fake GitHub server 验证 201、超时后已创建、403/404/410/422/429/5xx 和限速；required CI
  不创建真实 GitHub Issue；
- Phase 90 通过 Chrome desktop/mobile、same-origin、空 Console、懒加载分页、two-user 和 restart 验收。

若需要 Product DSH/Gateway/Browser 持有 GitHub 凭据、Publisher 访问 PostgreSQL/源码/Git/Docker、用户
指定 repository/URL、未确认即公开对话、绕过审核/隐私策略、无法保证 at-most-one public Issue，或必须给
GitHub Contents/PR/Actions 权限，则停止并提交新 ADR，不以 prompt 或兼容层绕过。

## 后果

- 开源用户能在 BYQ 内提交并跟踪问题，维护者获得结构化、可去重、可审计的 GitHub backlog。
- 外部发布成为可禁用且故障隔离的副作用；GitHub 故障不阻断核心量化产品。
- 部署维护者承担一次性服务 credential/仓库配置和公开内容治理，普通用户无 GitHub 配置负担。
- Product Feedback 与 EngineeringTask 保持分离；未来从已接受反馈创建 EngineeringTask 需要新的显式
  管理员动作/合同，Phase 87–90 不自动触发代码修改。

## 拒绝的替代方案

- 让每个用户 OAuth GitHub：增加账号/授权负担并扩大身份与 Token 风险。
- Product DSH 直接调用 GitHub：把外部 mutation 和 credential 交给 prompt-driven runtime。
- Backend 直接同步创建 Issue：外部延迟/失败污染 Product transaction，且扩大 credential trust boundary。
- GitHub-only、无内部记录：无法离线、审核、去敏、去重、重试或按 workspace 查询。
- 直接把对话/日志作为 Issue：可能公开 secret、PII、用户资产、Prompt 和内部实现。
- 复用 EngineeringTask：错误地把用户反馈等同于代码变更授权。
- 通用 webhook/任意仓库 publisher：形成 SSRF 和外部 mutation 平台，超出领域需求。

## 回滚

先禁用/停止 publisher 并撤销 GitHub App installation 或 service token；未发布 outbox 保留并显示
`publisher_unconfigured`，不得删除反馈。再按 Phase 90 → 88 逆序关闭 Agent/UI/API mutation，保留所有
feedback revision、审核、publication snapshot、Issue mapping 和 audit 为只读。已创建的公开 Issue 不自动
关闭或删除；任何 GitHub 清理必须由维护者在 GitHub 独立决定。

## 官方参考

- GitHub REST Issues：<https://docs.github.com/en/rest/issues/issues>
- GitHub App permissions：<https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app>
- REST endpoints permission matrix：<https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps>
