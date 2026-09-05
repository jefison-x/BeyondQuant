# Product Feedback Contract

本合同落实 ADR-0049。Phase 87 冻结合同；Phase 88 已实现 durable schema、domain 与 Product API；Phase 89
已实现隔离 trusted publisher；Phase 90 已完成 Product UI、MCP 与 Xiaoba 闭环。

## 1. 身份、所有权与权限

- schema family：`product-feedback.v1`、`feedback-publication.v1`、`feedback-outbox.v1`；
- `feedback_id`：`feedback_` + 32 lowercase hex；revision/outbox/audit 使用独立 opaque id；
- Feedback 属于 trusted request context 中的 `workspace_id`，`created_by`/`updated_by` 是 actor audit；
- normal user 只能读写自己的 workspace feedback，不能声明 owner/workspace/role/status/Issue mapping；
- draft/revision 始终仅 workspace owner 可见；submit 原子生成最小化、脱敏的 immutable
  `submitted_feedback_snapshot`，作为用户明确披露给 platform feedback moderator 的唯一内容；
- authenticated admin 只通过专用 moderator route 分诊 submitted snapshot 和 bounded audit，不能读取原始
  draft/revision、workspace 其他资源或用户身份；该能力不构成 workspace membership；
- Product Feedback 不授予 EngineeringTask、source、Git、PR、CI、部署或 merge 权限。

## 2. 封闭输入

Draft create/update 只接受：

```json
{
  "schema_version": "product-feedback.v1",
  "category": "bug",
  "component": "model_research",
  "title": "模型研究详情加载缓慢",
  "description": "选择研究后等待时间明显偏长。",
  "reproduction_steps": ["打开模型研究", "选择一条研究"],
  "expected_behavior": "详情在可感知等待内出现。",
  "actual_behavior": "界面长时间处于加载状态。",
  "severity": "normal",
  "diagnostics": {
    "include_product_version": true,
    "include_deployment_kind": true,
    "include_browser_family": true,
    "include_os_family": true,
    "include_performance_summary": false
  },
  "idempotency_key": "feedback-create-01"
}
```

Closed enums：

- category：`bug|feature|performance|usability|other`；
- component：`xiaoba|stock_pool|strategy|model_research|backtest|data_center|system_settings|auth|runtime|other`；
- severity：`low|normal|high`；security/credential/privacy incident 不在此 enum，必须走 private channel；
- diagnostic key 只允许上述 booleans，不能接受任意 map、header、environment、file 或 URL。

限制：title 4–160 chars；description 1–8,000；最多 12 steps、每步 500；expected/actual 各 2,000；
整个 canonical request 不超过 24 KiB。Phase 87–90 不接受附件、截图上传、完整日志、chat export、策略
源码、SQL、任意 HTML/Markdown image、repository、label、assignee、milestone、endpoint 或 external URL。

## 3. Revision 与 lifecycle

每次 draft update 创建 immutable revision；feedback row 只指向 current revision。

```text
draft -> submitted -> triaged -> accepted
   |         |           |         |
   +-------> withdrawn   +-------> rejected
                         +-------> duplicate
```

- 只有 `draft` 可由 owner 更新；submit 要求 `expected_version`、同意 moderator 阅读/可能公开提示和 preview hash；
- `submitted` 可在 triage 前由 owner withdraw；不能 hard delete；
- triage/accept/reject/duplicate 只允许 admin，要求 rationale、expected version 和 idempotency key；
- duplicate 关联同一内部 canonical feedback id；跨 workspace normal projection 不暴露该 id/内容；
- terminal feedback 保留 revisions/audit，只有 publication lifecycle 可继续；
- state/version transition 使用 optimistic concurrency；idempotency replay 返回原 projection，payload mismatch
  返回 conflict。

## 4. 安全预览与 publication snapshot

Submit 前 Gateway 返回由 Backend 生成的 `feedback-publication-preview.v1`，用户确认 exact `preview_hash`。
Backend 在 submit transaction 中重新生成并比较；过期/内容变化必须重新确认。Preview/publication body 只含：

- fixed BYQ template/schema version；
- category/component/severity；
- sanitized title/description/steps/expected/actual；
- explicitly opted-in coarse product version/deployment/browser/OS/performance summary；
- stable, non-authorizing public marker derived from outbox event identity。

永不包含：BYQ username/user/workspace/session/trace/conversation ids、email/IP/raw User-Agent、request headers、
cookies/tokens/passwords/API keys/private keys/connection strings、environment values、internal host/path/stack、raw
logs/WorkflowTrace/DSH objects/prompts/tool payloads、positions/assets/strategy source、market/provider licensed rows。

Normalization performs Unicode/control-character validation, markdown link/image stripping, fixed newline/section rendering,
credential/high-confidence identity scanning and maximum byte checks. A detected security report or non-redactable secret
returns `public_feedback_unsafe`; it is not persisted in a publication snapshot or queued. Redaction must be deterministic and
record redaction categories/counts, never matched values.

The accepted moderator action creates immutable `feedback-publication.v1` with `snapshot_hash`. Moderator may edit only the
bounded submitted fields through a new public revision and must preview/confirm it; the workspace draft remains owner-only.

## 5. Fingerprint、rate limits 与 duplicate

`feedback_fingerprint.v1 = sha256(category + component + normalized_title + normalized_reproduction_semantics +
coarse_product_version)`。Fingerprint is evidence, not automatic cross-workspace disclosure or rejection.

- create/submit rate policy defaults are code-owned and bounded; exact Phase 88 values become versioned configuration；
- rate limit response returns retry-after/category only, not another user's count/content；
- same-workspace identical idempotency replays；same fingerprint may suggest an existing own/public issue；
- moderator may merge to canonical feedback or already-published Issue；publisher never searches arbitrary repositories/content；
- a public Issue marker can reconcile only an exact outbox id + snapshot hash in the configured repository。

## 6. Transactional outbox 与 publisher lease

Accept + enqueue is atomic. `feedback-outbox.v1` stores event id, feedback/publication ids, snapshot hash, fixed destination
key, state, attempt, next-attempt time, lease owner/expiry/fence, last safe error category and timestamps. It never stores a
credential or arbitrary URL.

Internal endpoints are service-authenticated and not Product/OpenAPI/MCP routes：

- `POST /internal/feedback-publications/claim`：publisher claims at most 10 due events with lease/fence；
- `POST /internal/feedback-publications/{event_id}/complete`：requires matching fence and canonical GitHub mapping；
- `POST /internal/feedback-publications/{event_id}/retry`：requires matching fence and stable safe error category；
- expired lease may be reclaimed with a higher fence；stale completion/retry fails closed。

Publication attempts are finite. Exponential backoff includes jitter and honors bounded provider retry hints. Retryable:
transport ambiguity, `429`, selected `5xx`. Terminal/operator-action: invalid credential/permission, repository/Issues
unavailable (`404/410`), unsafe payload, validation/spam (`422`) after one reconciliation, and exhausted attempts.

Before retrying an ambiguous create, publisher performs a bounded exact-marker reconciliation in the single configured repo.
If exactly one matching Issue exists, complete with it; zero retries; multiple matches become terminal conflict. This provides
effectively-once mapping without claiming GitHub offers an idempotency key.

## 7. GitHub destination 与 credential

Deployment config is operator-owned and fixed at startup：

- `BYQ_FEEDBACK_GITHUB_REPOSITORY`：exact `owner/repo`, validated against deployment allowlist；
- preferred GitHub App settings：App id, installation id and private key injected only into publisher；
- fallback fine-grained service token injected only into publisher and limited to that repository；
- API origin defaults to fixed `https://api.github.com`; non-default origin is test-only unless a future ADR qualifies GitHub
  Enterprise, and never comes from Browser/feedback/database。

Required permission: repository `Issues: write`; no Contents/Pull requests/Actions/Administration/Secrets/Deployments or
organization permission. Publisher only performs create Issue plus exact-marker reconciliation reads required by the adapter.
It does not create labels; renderer uses only deployment allowlisted labels and gracefully omits missing optional labels.

Normal users do not configure or supply GitHub identity/credential. Public projection exposes only：

```json
{
  "publication_status": "publisher_unconfigured",
  "github_issue": null
}
```

or, after success, canonical `issue_number` and `html_url` verified against the fixed repository. Admin status exposes
`configured`, credential kind, fixed repository, queue counts and safe last error category, never secret material.

## 8. Product API projection

Planned Phase 88/90 routes under `/api/product/feedback`：

- `GET /options` — code-owned enums, limits, privacy copy and publisher availability；
- `GET /items?status=&category=&query=&limit=&offset=` — owner-scoped paged summaries；
- `POST /items`, `GET/PUT /items/{feedback_id}` — draft/revision；
- `POST /items/{feedback_id}/preview|submit|withdraw`；
- admin paged inbox/detail and `triage|accept|reject|duplicate` actions；
- admin publisher status is read-only; Browser cannot restart worker or set credential/repository。

Initial UI loads options plus first summary page only. Detail/revisions/public preview load on selection; admin audit/outbox
history loads only when its disclosure/tab opens, always paged. Product responses use the standard safe error envelope and
exclude internal lease/fence, request hashes, actor identifiers, raw errors and credential state.

## 9. MCP 与小巴

Phase 90 tools：`byq_feedback_options`、`byq_feedback_list`、`byq_feedback_get`、
`byq_feedback_create_draft`、`byq_feedback_update_draft`、`byq_feedback_preview`、`byq_feedback_submit`。All use trusted context and the same Backend domain
contract. No admin triage/publish/publisher tool is exposed to Product DSH.

Xiaoba may summarize the current user's stated problem into a draft. It must not silently attach conversation content, infer
consent, submit during an unrelated action, or claim GitHub publication before the persisted status says `published`.
`preview` must be shown and the user must explicitly confirm the exact draft before `submit`.

## 10. Public Issue renderer

Title prefix is fixed by category (`[Bug]`, `[Feature]`, `[Performance]`, `[UX]`, `[Feedback]`). Body section order is fixed：
summary → reproduction (when present) → expected → actual → coarse environment (opt-in) → privacy note → BYQ marker.
Renderer escapes content so user text cannot create hidden HTML, external images or mention-notification storms. No raw
internal JSON is embedded.

## 11. Required verification

- schema/unknown-field/size/Unicode/secret/security/markdown negative tests；
- workspace ownership, admin RBAC, optimistic version, idempotency, lifecycle and append-only audit tests；
- preview hash, immutable publication revision, fingerprint and cross-workspace non-disclosure tests；
- transaction rollback, lease/fence/reclaim/restart, retry budget and exact-marker reconciliation tests；
- fake GitHub server contract for 201/ambiguity/403/404/410/422/429/5xx；required CI makes zero real GitHub writes；
- Compose/image tests prove publisher is non-root, read-only, no source/Git/Docker/DB/DSH and credential isolation；
- Product API/MCP secret-negative schemas, same-origin frontend, lazy pagination, two-user and Chrome desktop/mobile evidence。

## 12. Community classification

| Community evidence | Classification | Disposition |
|---|---|---|
| `.github/ISSUE_TEMPLATE/reproducible_bug.md` bounded environment/minimal fixture/privacy copy | `PORT_UX` + `PORT_TESTS` | Re-express as BYQ fields, preview and safety tests; do not copy free-form upload behavior. |
| `.github/ISSUE_TEMPLATE/strategy_plugin.md` boundary checklist | `REFERENCE_ONLY` | Preserve no-network/no-token/no-private-data intent; plugin proposal workflow is not Phase 87–90 feedback scope. |
| `.github/ISSUE_TEMPLATE/config.yml` private security link | `PORT_UX` | Route suspected security reports away from public Issue queue. |
| Historical GitHub Issue references in requirements docs | `REFERENCE_ONLY` | Evidence that Issues are useful backlog, not a runtime/persistence contract. |
| Community Agent/API/runtime/storage | `REPLACE` / `DROP` | Implement BYQ Product API + PostgreSQL + trusted publisher; no PydanticAI/Hermes/direct GitHub Agent path. |

Community repository remains read-only and no source, credential, database or Git history is copied or modified.

## 13. Phase 88 implementation record

Phase 88 实现 `product_feedback`、immutable revisions/audit/publications、commands 和 transactional outbox，
以及 owner/admin 的 Backend 与 Gateway Product API。接受动作与 publication/outbox 写入处于同一 PostgreSQL
transaction；部署未配置 publisher 时，公开状态稳定为 `publisher_unconfigured`，内部反馈仍可完整流转。
Gateway 的 moderator authority 不携带 workspace membership，owner projection 不暴露 actor/workspace，moderator
projection 只展示用户已确认的 submitted snapshot。Phase 88 runtime 不包含 GitHub client、credential、外部写入、
frontend 页面或 MCP 工具。

## 14. Phase 89 implementation record

Phase 89 扩展 outbox 为 `queued|publishing|retry_wait|published|failed_terminal`，通过 service-authenticated internal
API 实现最多 10 条 claim、15–300 秒 lease、单调 fence、过期重领、stale result 拒绝和最多 6 次 publication
attempt。6 次上限仅约束 GitHub 外部副作用重试，不约束用户反馈、小巴分析、分页或其他领域操作。

独立 publisher 只消费 Backend snapshot，固定调用一个 `owner/repo` 的 issue list/create route；每次 create 前按
exact event/snapshot marker 做有界 reconciliation。GitHub App 优先，单仓库 fine-grained token 仅作 fallback。
Publisher profile 默认关闭；未配置或撤销 credential 时内部反馈保持可用并显示 unconfigured。映射成功后 owner/
moderator 只获得验证过的 repository、issue number 和 canonical public URL。

## 15. Phase 90 implementation record

Phase 90 在 conversation-first shell 增加 owner 反馈工作台，在 System Settings 增加 admin-only 审核工作台。
首屏只并发读取 options 与第一摘要页；详情、审计和后续页按用户动作懒加载，筛选由服务端分页执行并取消过期请求。
用户必须先保存草稿、生成服务端公开候选快照，再通过二次明确确认提交；环境诊断默认不携带。管理员只能看到
submitted snapshot，可执行分诊、采纳、拒绝和关联重复项，并读取安全 publisher 状态。

BeyondQuant MCP 只注册七个 owner tool，不注册 moderator/publisher/GitHub tool。`byq-product-feedback` skill 固定
“起草/预览 → 展示精确预览 → 等待后续用户回合明确同意 → 提交”，不得在同一回合自动提交。普通用户仍无需
GitHub 账号、Token 或仓库配置；publisher 未配置时反馈完整持久化与审核，采纳项明确保持
`publisher_unconfigured`。

## 16. Phase 92 central Hub contract

Agent 提交改为“起草/预览 → 展示精确预览 → 请求全局审批 → 原会话续接 → 携带
`agent_approval_id` 提交”。Approval 必须绑定 `byq_feedback_submit`、`product_feedback` 和 exact feedback ID；
网页用户本人仍可在同一 Product 页面直接确认。两条路径均只提交 exact preview version/hash。

每次 submit 在同一 PostgreSQL transaction 写入 `feedback-hub-delivery.v1` outbox。local relay 的 intake envelope 为：

```json
{
  "schema_version": "central-feedback-intake.v1",
  "installation_id": "byq-installation-<32 hex>",
  "event_id": "feedback_hub_event_<opaque>",
  "snapshot_hash": "sha256",
  "snapshot": {"schema_version": "submitted-feedback-snapshot.v1"}
}
```

Hub 返回不可猜的 `central_feedback_*` receipt 与 HMAC status capability。公开 status endpoint 必须同时验证二者，
且只返回 `received|triaged|accepted|rejected|duplicate|publishing|published` 和最终 canonical Issue link。Hub 不接收
user/workspace/session/trace、聊天全文、附件或任意 destination。

Hub 对大小、hash、schema、secret/PII/security report 再次 fail closed，按匿名 installation 限制每小时五次 intake，
并以跨安装 fingerprint 辅助审核去重。中央 `accept` 才创建 `feedback-publication.v1` outbox；publisher route 固定
`jefison-x/BeyondQuant`。Local relay 最多八次网络投递，GitHub publisher 最多六次外部副作用尝试；两个预算都不限制
小巴推理、分页或用户新会话。

## 17. Phase 93 Cloudflare deployment contract

Phase 92 的 intake/receipt/status/moderation/publication schema 和 URL 保持 wire-compatible。官方中央实现由两个隔离 Worker
组成：Hub Worker 绑定 D1、`INSTALLATION_GATE`、`FEEDBACK_GATE` 和 Queue producer；Publisher Worker 只绑定主 Queue
consumer、DLQ、Hub Service Binding 和 GitHub App secrets。Hub 不持有 GitHub credential，Publisher 不绑定 D1 或 Product。

`accept` 必须以 D1 batch 原子写 feedback 状态和 `central_feedback_outbox`。Cron dispatcher 的 Queue envelope 只含：

```json
{"schema_version":"feedback-publish-queue.v1","event_id":"feedback_outbox_<32 hex>"}
```

Queue delivery 不授予发布权；Publisher 必须用 service token 回 Hub 对 exact event 执行 lease/fence claim，再使用不可变 snapshot。
Queue send/ack 可重复，D1 outbox 不可因免费额度、24 小时消息保留、Worker eviction 或 callback failure 删除。GitHub create 前始终
按 event/snapshot marker reconciliation。只有 Hub complete 写入 fixed repository/number/canonical URL 后，公开 status 才为
`published`。
