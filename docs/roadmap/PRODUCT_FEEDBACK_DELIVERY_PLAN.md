# Built-in Product Feedback Delivery Plan

本计划受 ADR-0049 和 `docs/contracts/product-feedback.md` 约束。Phase 87–90 严格串行，每阶段使用独立
worktree、branch 和 PR；完成自动验证、CI-green squash merge 和部署验证后才能进入下一阶段。

## 用户与运维配置结论

正常用户无需 GitHub 账号、用户名、Token、App、repository 或权限配置。他们只使用 BYQ durable login
提交、确认并查询反馈。官方部署由项目维护者预配置；self-hosted operator 若希望自动发布，只需一次性为固定
仓库安装最小权限 GitHub App，或配置单仓库 fine-grained service token。未配置时内部反馈功能完整保留，
仅外部发布明确停在 `publisher_unconfigured`。

## Phase 87 — Feedback contract and trusted-publisher baseline（`COMPLETE`）

- 只读检查并分类 Community Issue templates、历史 Issue workflow 和现有 EngineeringTask/credential/runtime；
- 接受 ADR-0049，冻结 Feedback/revision/preview/publication/outbox、隐私、去重、滥用和状态合同；
- 固定 Product Feedback 与 EngineeringTask 分离、Product DSH 零 GitHub 权限、独立 publisher 单仓库最小权限；
- 固定用户零 GitHub 配置、operator 一次配置和 publisher-unconfigured 降级；
- 冻结 Phase 88–90 exit gate；不修改 runtime、database、API、MCP、frontend 或 Compose，不创建真实 Issue。

## Phase 88 — Durable feedback domain and Product API（`COMPLETE`）

### 范围

- PostgreSQL migrations/store：feedback identity、immutable revisions、audit、publication snapshot、transactional outbox；
- Backend lifecycle/RBAC/workspace/idempotency/optimistic concurrency、preview/redaction/fingerprint/rate policy；
- Gateway Product API options、owner paged catalog/detail/draft/preview/submit/withdraw 和 admin paged inbox/actions；
- versioned OpenAPI/client types；secret-free structured errors；
- migration/restart/transaction/two-user tests。

### 非目标

- 不调用 GitHub、不实现 publisher service、不把 credential 写入数据库；
- 不实现 Product UI、MCP 或 Xiaoba；
- 不自动创建 EngineeringTask，不允许普通用户/admin 通过 Product API 写 source/Git/PR；
- 不接受附件、截图上传、完整日志、任意 URL/repository/labels。

### Exit gate

- normal/admin/second-workspace state and projection tests；
- deterministic preview/redaction/unsafe report/secret/size/markdown tests；
- transaction rollback guarantees accept+outbox atomicity；
- initial/page/detail API bounded and no secret/internal identity；
- PostgreSQL restart and migration idempotency；
- architecture/unit/contract/smoke all green。

## Phase 89 — Trusted GitHub publisher and operations（`COMPLETE`）

### 范围

- 独立 non-root/read-only `feedback-publisher` image/service；
- Backend internal claim/complete/retry endpoints with service token、lease/fence/reclaim；
- fixed-origin/fixed-repository GitHub adapter and versioned renderer；
- GitHub App installation credential preferred, single-repo fine-grained token fallback；
- 201、ambiguous timeout reconciliation、403/404/410/422/429/5xx classification and bounded retry；
- Compose health/credential isolation/admin read-only publisher status/runbook；
- deployment with publisher disabled/unconfigured by default unless operator credential already exists。

### 非目标

- 不给 Product DSH/Browser/Gateway/Backend GitHub credential；
- 不访问 PostgreSQL/source/Git/Docker/DSH；
- 不支持 arbitrary repo/API、comment/update/close、label creation、assignee/milestone、PR/Contents/Actions；
- required CI 不写真实 GitHub。

### Exit gate

- local fake GitHub server contract matrix and effectively-once reconciliation；
- worker crash/restart/expired lease/stale fence/retry exhaustion；
- image/network/env/mount/secret-negative architecture tests；
- configured/unconfigured/revoked credential operational behavior；
- formal deploy keeps unrelated Product healthy and PostgreSQL volume intact。

## Phase 90 — Product UI and Xiaoba closure（`AUTHORIZED`）

### 范围

- conversation-first shell 增加“反馈与建议”入口，桌面 dialog/移动 full-screen；
- owner catalog、draft editor、privacy disclosure、server preview、explicit confirmation、status/Issue link；
- admin System Settings feedback inbox, paged triage/detail/public snapshot and publisher status；
- MCP minimal owner tools and Xiaoba skill for propose → preview → explicit submit, no admin/publish tool；
- product capability catalogue/help/navigation update；
- lazy page/detail/audit loading, abort stale requests, bounded payload and accessible states。

### Exit gate

- mocked frontend unit/Playwright plus real PostgreSQL/Product API no-mock journeys；
- normal user draft/confirm/submit/status, admin triage/accept and configured fake publisher mapping；
- publisher-unconfigured journey keeps feedback useful；
- two-user isolation, restart, idempotency, duplicate, unsafe/security rejection；
- Chrome MCP desktop/mobile, same-origin, no direct Backend/MCP/DSH/GitHub, empty Console/Issues；
- initial load requests only options + first summary page; detail/audit lazy; performance budgets and no horizontal overflow；
- Community feature checklist and final evidence in `docs/evidence/phase-90/`。

## Stop conditions

任一阶段若需要用户个人 GitHub OAuth/Token、Product Agent GitHub writer、publisher 访问应用源码/Git/Docker/
PostgreSQL、任意 destination/webhook、自动公开聊天/日志、绕过 preview/审核、跨 workspace 泄漏、无法提供
effectively-once mapping 或 GitHub Contents/PR/Actions 权限，立即停止并提交新 ADR。

## Rollback sequence

按 Phase 90 → 88 逆序关闭 UI/MCP/API mutation；优先停 publisher、撤销 GitHub credential，保留 feedback、
publication/outbox/audit 只读。已创建 Issue 不由 BYQ 自动删除或关闭。每个数据库变更只允许 forward repair 或
已验证备份恢复，不执行 destructive rollback。
