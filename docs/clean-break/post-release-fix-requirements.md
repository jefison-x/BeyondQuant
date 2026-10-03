# BYQ 0.10 发布后待修复需求

状态：**OPEN — 需求与源码分析记录，尚未实施。**

日期：2026-10-03。当前记录分支基线：`adca19bae7bee1db28e33633f30c3f45bc432d27`。
维护者要求先记录问题、后续集中安排修复；反馈简化本次只授权分析与需求文档。
不改变 Phase17 状态，不启动下一阶段，不表示代码、真实验收或部署 PASS。

## 待办总表

| 编号 | 需求 | 状态与证据 |
|---|---|---|
| R1 | 硬取消后不恢复旧 Agent；正常释放及取消后的会话终态不循环重连 | OPEN；[已定位问题](runtime-stop-session-issue.md)，有先前实际只读 trace/日志证据。 |
| R2 | 菜单消除 Bootstrap Admin 初始化名称 | OPEN；[用户要求与源码分析](personal-workspace-menu-issue.md)，接受 Admin 或昵称（Admin）形式。 |
| R3 | 会话反馈作为唯一产品入口，审核集中到 Cloudflare Hub，移除本机直发与独立反馈页面 | OPEN；以下是本次源码与依赖分析，尚无修复实测。 |

“一并修复”表示集中跟踪，不免除每项的受影响场景验收；每个子系统保持单一 writer。

## R3：维护者要求与目标链路

维护者明确要求：直接在会话中反馈内容，不需要在具体页面/菜单中独立发布；
审核在 Cloudflare Hub 完成。若本机功能无用，建议删除，并取消前端相关页面。
需要改代码的部分先记录为后续需求，本次不实施。

目标链路：

```text
用户在 BYQ 会话描述问题
  → Product Agent 经 BYQ MCP 创建私有草稿、展示脱敏预览
  → 用户确认发送准确快照
  → BYQ 持久反馈与 Hub 投递队列
  → feedback-hub-relay 投递 Cloudflare Hub
  → Cloudflare Hub 管理员审核
  → 私有 Cloudflare Publisher Worker 发布采纳的反馈
  → Hub 状态回传 BYQ，用户在会话中查询
```

不要求用户访问 `/feedback` 或 BYQ 内的审核页。用户的发送确认与 Hub 管理员的
采纳审核是两个动作：确认只授权披露预览内容，不代表审核通过或已发布。

### 分析结论

**本机 Python `feedback-publisher` 与独立反馈/本地审核页面可作为删除目标；
本地 relay、持久反馈业务和 Cloudflare 两个 Worker 必须保留。**

三个同名/近似组件的职责：

| 组件 | 现有职责 | 目标处置 |
|---|---|---|
| `workers/feedback-publisher/` + Compose `feedback-publisher` | 从本机审核/publication outbox 直接写 GitHub | DELETE；不在维护者要求的目标链路中。 |
| `workers/feedback-hub-relay/` | 将本机快照投递 Hub，并查询审核/发布状态 | KEEP；删掉会使本地反馈留在队列而不能送达 Hub。 |
| `workers/feedback-publisher-cloudflare/` | Hub 审核后，由隔离的私有 Worker 写固定 GitHub 仓库 | KEEP；属于 Cloudflare 链路，与被删除的本机 Docker 镜像不同。 |

先前只读部署观察确认：本机 `feedback-publisher` 已下载但没有使用该镜像的
容器，Compose profile 默认关闭；`feedback-hub-relay` 正在运行且健康。
这不是本次新做的线上观察，也不能证明 Cloudflare 实際审核/发布成功；
本次未调用 Hub、GitHub、模型或数据服务。

## 源码证据与影响范围

1. [`byq-product-feedback` skill](../../plugins/dsh-byq/skills/byq-product-feedback/SKILL.md)
   已规定会话创建草稿、预览、精确确认、提交到中央 Hub，明确不要求访问反馈页。
   [`MCP feedback.ts`](../../services/mcp/src/feedback.ts) 提供创建、更新、预览、
   提交、查询和原请求回执核对；会话反馈并不依赖 Vue 反馈表单。
2. [`Backend main.py`](../../services/backend/app/main.py) 的 `feedback_submit`
   对 Product Agent 核验准确的 `agent_approval_id`、action/resource 与权限。
   [`product_feedback.py`](../../services/backend/app/product_feedback.py) 的 `submit`
   直接在同一事务写入 `product_feedback_hub_outbox`，不要求先执行本机审核。
3. [`router/index.ts`](../../apps/frontend/src/router/index.ts) 当前存在 `/feedback`
   和 `/settings/system/feedback`；
   [`UserSettingsMenu.vue`](../../apps/frontend/src/components/layout/UserSettingsMenu.vue)
   有“反馈与建议”入口；
   [`systemSettingsNavigation.ts`](../../apps/frontend/src/router/systemSettingsNavigation.ts)
   有“反馈审核”入口。
4. `product_feedback.py` 的 `public_options`、owner 列表/详情和 `_owner_projection`
   仍同时读取本机 publisher/publications 与 Hub 状态；不能仅删除表或 worker
   后保留这些 SQL/投影。后续要移除本机审核、claim/create/complete/retry 状态机，
   同时保留 Hub 的 receipt、状态、Issue mapping 与未知结果核对。
5. [`workspace_reset_scope.py`](../../services/backend/app/workspace_reset_scope.py) 和
   [`workspace_reset.py`](../../services/backend/app/workspace_reset.py) 仍分类/检查本机
   `product_feedback_publications`、`product_feedback_outbox`；清理 DDL 时必须同步
   修订 ownership、FK、归档和未决责任分类，不能留下失效表查询或丢失幂等证明。
6. [`scripts/release/images.py`](../../scripts/release/images.py)、
   [`scripts/ci/build-images.py`](../../scripts/ci/build-images.py) 和
   [`local-ci.sh`](../../scripts/ci/local-ci.sh) 仍包含本机 publisher 的镜像、profile、
   单测与 smoke。架构测试还断言其存在；后续要改为目标边界的正例及权限负例。

## KEEP / DELETE / REWRITE 清单

| 分类 | 范围 | 要求 |
|---|---|---|
| KEEP | 会话 skill、owner-scoped MCP、反馈/修订/确认快照/业务审计/幂等回执 | Product Agent 只经 BYQ MCP；身份、Workspace 权限、隐私和未知结果核对保持。 |
| KEEP | `feedback-hub-relay`、Hub outbox、`workers/feedback_http_deadline.py` | 有界投递与状态等待，准确 receipt/fence、防重放、失败不丢反馈。共享 deadline 仍由 relay 使用。 |
| KEEP | Cloudflare Hub/D1/DO/Queue、审核控制台、私有 Publisher Worker | 审核集中在 Hub；GitHub 写凭据只在私有 Cloudflare Publisher。 |
| DELETE | 本机 `workers/feedback-publisher/`、Dockerfile、Compose profile 及本机专用配置引用 | 从新发布构建目标删除；不得误删 Cloudflare 同名 token/凭据。 |
| DELETE | `FeedbackView.vue`、`FeedbackAdminView.vue`、两条路由、两类菜单入口、AppShell 反馈 overlay 特例 | 不是仅隐藏菜单；同时删除实际页面与无调用者的页面专用 API/helper。旧书签有明确返回会话的行为。 |
| DELETE | 本机 moderation 与 direct publication 的专用 Backend/Gateway API、worker API、死状态机 | 按调用者证据删除；保留 Agent 所需的 owner 域与精确确认 API。 |
| REWRITE | 共享 `product_feedback.py`、Product API/types/OpenAPI、能力目录/帮助文本 | 查询/公开状态只来自目标 Hub 链路，不伪造本机审核、发布或已完成；保留所有权与对账语义。 |
| REWRITE | 全新 schema 与 reset ownership/归档/责任分类 | 仅在受授权的未来切片执行；生产现有表/历史记录的迁移与保留另行分类。 |
| REWRITE | CI/镜像发布清单、依赖与许可证清单、架构/组件/合同及真实验收 | 去除本机 publisher 的构建/测试成本，保留 Cloudflare 和 relay 的有效安全验证。 |

`BYQ_FEEDBACK_PUBLISHER_TOKEN` 在本机与 Cloudflare 都有引用。
**同名不等于同一部署作用域**：只移除本机专用引用；Hub/私有 Worker 的 Service
Binding 认证仍需保留，不能全仓按变量名删除。前端反馈 API/helper 是否可整文件
删除，要在实施时核对当前所有调用者，不从删除页面直接推断。

## 后续边界决策

- 此需求不取消用户对外发送的明确同意。现行 `byq_feedback_submit` 精确业务授权
  和通用 ACTION 确认保留；它不是本机管理员审核。若要将既有全局确认改为完全
  会话内确认，须另行说明用户动作如何由服务器准确绑定，不把模型自报同意当授权。
- 本次只记录目标。实施前提出具名 ADR/架构边界修订，明确唯一产品入口、唯一
  Cloudflare 审核和删除本机直发出口；以当前 Clean Break baseline 为准。已归档
  ADR-0049/0052/0053 可用于历史解释，不能直接作为今天实施/部署的授权。
- 只删除应用代码与未来配置引用，不在本次删除 Docker/GHCR 镜像、线上容器、
  既有数据库、用户数据、备份、凭据或历史发布清单。历史 digest/SBOM/回滚证明保持。
- 未来发布应用镜像清单应从实际保留目标派生：如只删除这一项，原 14 项变为 13 项，
  每项仍须精确 digest/SBOM/来源证明。不能把已通过的 14 项旧发布记录改写成 13 项，
  或在当前发布中临时降低门禁。

## 后续验收需求（全部 NOT_RUN）

1. 定向合同验证会话创建 → 脱敏预览 → 准确确认 → 幂等提交 → Hub outbox/receipt →
   状态查询；覆盖第二用户拒绝、未批准/版本变更拒绝、敏感内容拒绝和未知结果对账。
2. Hub 审核和私有 Publisher 的有效依赖/合同保持；本机 API/配置/代码不再提供
   direct GitHub writer，也不暴露本地审核入口。保留真实 secret 检出负例。
3. 真实 Gateway/Product API 浏览器验证桌面与移动端无两类反馈页面/菜单；用户能
   在原健康会话完成反馈提交并查询准确反馈状态，不通过隐藏页面替代验收。
4. 用已有记录/离线 Hub 样本/定向 relay 合同先验证回执与错误分类。受影响的实际
   会话反馈仍需实测；若需真实 Cloudflare intake 或 GitHub 写入，事先说明准确范围，
   按当时授权与服务权限执行。模拟 Hub/静态 PASS 不冒充线上审核/发布成功。
5. Tester → 独立 Reviewer → Root 接受受影响切片后，才进入对应 PR/发布门禁。
   不重跑有效 A–D/F6，不默认全仓回归、整栈重建、模型调用或行情操作。

本次文档校验只检查 diff、文件引用和需求覆盖；不计为以上任何真实功能验收。
