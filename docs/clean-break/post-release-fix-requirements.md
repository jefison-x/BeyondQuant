# BYQ 0.10 发布后待修复需求

状态：**R1–R4 修复候选已实现，ADR-0092 已接受；R1 实际 DSH 正常释放/硬取消、R2/R4 与 R3 旧书签的隔离真实浏览器检查通过。R3 正式 Hub 接收/状态查询及隔离 Backend→relay→正式 Hub 接收通过；会话创建、用户批准、审核后状态回传仍待验收。**

日期：2026-10-03。当前记录分支基线：`adca19bae7bee1db28e33633f30c3f45bc432d27`。
维护者最初要求先记录问题，随后已明确授权直接修复 R1–R4，并保持现有 DSH runtime。
下方“现状/尚未执行”等文字记录修复前的诊断基线，以末尾实施证据为当前候选状态。
2026-10-03 另有精确运维授权：更改当前正式栈现有 Admin 密码并撤销旧登录；
该一次性账号操作不等于实现以下 R4 产品功能，密码和认证备份不进入 Git。
不改变 Phase17 状态，不启动下一阶段，不表示 R1–R4 整体或全链路验收、部署 PASS。

## 待办总表

| 编号 | 需求 | 状态与证据 |
|---|---|---|
| R1 | 硬取消后不恢复旧 Agent；正常释放及取消后的会话终态不循环重连 | 候选实现；前端单测与 Gateway 合同、隔离真实浏览器合成关闭会话 1/1、实际 DSH 正常释放/硬取消各 1/1 通过；原双均线生产历史案例未重放。 |
| R2 | 菜单消除 Bootstrap Admin 初始化名称 | 候选实现；前端单测与隔离 Gateway/Product API 桌面、手机真实浏览器 1/1 通过。 |
| R3 | 会话反馈作为唯一产品入口，审核集中到 Cloudflare Hub，移除本机直发与独立反馈页面 | 候选实现；合同及隔离真实浏览器旧书签 1/1 通过；ADR-0092 已接受；正式 Hub 直接接收/状态查询与隔离 Backend→relay→正式 Hub 接收通过，会话内提交与审核后状态回传 NOT_RUN。 |
| R4 | 用户在前端修改自己的密码，后端持久更新并注销旧登录 | 候选实现；Backend/Gateway 数据库合同及隔离真实浏览器普通用户/Admin 2/2 通过。 |

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
最初只读部署观察时未调用 Hub、GitHub、模型或数据服务；文末记录了此后
经维护者授权的正式 Hub 定向测试。

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

## 原始验收清单（实施前全部 NOT_RUN；当前结果见文末）

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


## R4：前后端修改密码

### 现状与授权边界

当前 [`user_auth.py`](../../services/backend/app/user_auth.py) 提供创建、登录、退出及
资料更新，但没有用户改密方法；资料更新不接受密码字段。Gateway 与前端也没有
对应的改密接口和入口。后续修复需要完整前后端流程，不能仅更新配置或文本文件。

`BYQ_BOOTSTRAP_ADMIN_PASSWORD` 仅用于空库的首次账号创建；已有账号的登录密码
以 `users.password_hash` 为准。私密 Admin 登录记录是运维记录，不是认证数据源。
修改上述文件或重启服务不会更新已有账号密码。此次精确 Admin 运维改密与未来
普通用户自助改密分开记录，不授予 Product Agent 账号管理或数据库访问权限。

### 功能要求

1. **前端入口与交互。** 已登录用户在个人账号设置中填写当前密码、新密码、确认
   新密码；适用于普通用户与 Admin。通过 Gateway/Product API 提交，不连接 Backend、
   MCP、DSH 或数据库。不将密码保存到本地持久存储、会话消息或可见审计记录。
   提供明确校验、提交状态和错误提示，防止重复提交；成功后清除敏感表单并引导重新登录。
2. **后端身份与权限。** 改密目标从可信登录身份取得，只允许修改自己的密码；拒绝
   请求体指定其他 `user_id` 或越权字段。验证当前密码与账号 active 状态，覆盖普通
   用户。管理员重置他人密码属于另外的明确权限与验收决策，不由本需求隐含授权。
3. **持久性与旧登录撤销。** 沿用 BYQ 的安全密码散列及随机 salt，绝不存明文；
   单个事务更新密码、安全时间并撤销该用户全部旧认证会话，包括提交请求的会话。
   明确处理登录与改密并发，使旧密码登录不能越过撤销边界；不更改身份、角色、
   Workspace、业务 Job 或 Artifact，不停止独立 Job 或恢复旧 DSH 会话。
4. **密码策略与接口合同。** 当前账号创建采用 8–256 字符；实施前统一创建、登录、
   改密的长度与空白处理合同，前后端一致。新密码确认用于防误输，不能替代后端
   当前密码校验。公开错误不包含明文、散列、cookie、令牌或其他账号信息。
5. **安全与未知结果。** 使用现有认证、请求来源/CSRF 防护及限流边界，不新增
   通用认证平台。敏感请求不得进入日志、trace、反馈或 Artifact；必要审计仅记录
   actor、动作、时间与结果。若响应丢失，先通过既有认证状态/重新登录判断结果，
   不自动重放改密。错误或回滚不得部分更新密码、保留旧有效会话或误删其他用户会话。
6. **配置与运维说明。** 产品页面说明改密立即生效并需要重新登录，无需重启。
   普通用户改密不写部署 `.env`；Admin 私密运维记录与 bootstrap 配置的同步属于
   明确的运维动作，不把服务配置文件当作普通用户账号密码存储。

### 原始受影响验收清单（实施前全部 NOT_RUN；当前结果见文末）

- 定向后端/Gateway 合同：正确与错误当前密码、长度/空白合同、禁用账号、未登录、
  跨用户/越权字段拒绝、无秘密响应与日志、事务回滚、并发登录及重复/未知提交。
- 持久性与隔离：新密码可登录、旧密码拒绝、该用户旧 cookie 全部失效，其他用户
  密码和会话仍有效；原账号、Workspace、业务数据与 Job/Artifact 身份不变。
- 真实浏览器经 Gateway/Product API 验证普通用户及 Admin 的改密、错误提示、
  敏感表单清除、重新登录与刷新后持久性；覆盖桌面/手机可用性。
- Tester → 独立 Reviewer → Root 接受后进入对应 PR/发布门禁；一次性运维改密验证
  不能代替前后端功能验收。不重跑有效 A–D/F6 或触发研究/行情操作。

## 2026-10-03 修复候选与证据边界

隔离分支 `codex/post-release-r1-r4` 保持现有 DSH runtime。R1 识别
`session.closed`、硬取消与 Product 终态错误码，停止旧会话订阅/发送；R2 在菜单
显示 Admin 或昵称（Admin）；R3 删除独立反馈/审核页面、本机 Python publisher
和对应路由，保留 owner MCP/API、Hub outbox/relay、Cloudflare 私有 Publisher，
旧本机表和归档检查继续保留；R4 通过 Gateway 自助改密并在一个数据库事务中
撤销该用户全部会话；当前密码在 15 分钟内输错 5 次后按用户限流 15 分钟，
限流状态持久化。R3 架构变更见已接受的 [ADR-0092](../architecture/adr/ADR-0092-conversation-feedback-cloudflare-review.md)。

- 前端完整单测：69 文件、238 项通过；R1 定向会话测试 18 项通过；
  旧反馈书签 Chromium 浏览器测试 1 项通过，生产构建通过。
- 隔离、无持久卷的 PostgreSQL/Backend 测试：67 项通过；无网络 Gateway
  测试容器：154 项通过；测试容器和网络已清理。
- 架构测试 72 项通过；Hub relay 9 项通过；Compose 用 `.env.example`
  解析通过。上述均为候选代码与隔离环境证据，不代表正式部署。
- 2026-10-03 续验收：隔离网络、无持久卷 PostgreSQL、随机一次性账户和
  loopback 前端组成的真实 Gateway/Product API 浏览器栈中，R2 Admin 工作区
  名称桌面/手机 1/1、R3 旧反馈书签 1/1、R4 普通用户桌面与 Admin 手机改密
  2/2 通过。R4 核对了成功回执、旧 cookie 撤销、旧密码拒绝、新密码重新登录和
  用户角色；测试账户与临时库随容器清理。Nginx 代理改用保留端口的 Host 转发，
  其配置解析通过；跨站来源拒绝仍由 Gateway 合同覆盖。R4 首次试跑暴露测试
  标签/redirect 断言问题及随机端口 Host 丢失，均修正后针对受影响场景重跑通过。
- R1 在同类隔离真实浏览器栈中，用测试夹具向临时 Backend/Gateway 注入
  合成 `session.closed` 终态与持久用户消息，历史重放 1/1 通过：消息可见、
  新会话入口可见，旧会话无事件订阅或写入。R1 另以镜像 digest
  `20f673f520c83bf9bdbc94b64d2ed5e24e18f357496a6c5245c956e5cc9a4e72`
  的 Adapter、现有 Phase7 脚本化 provider、一次性 PostgreSQL、Gateway 与
  前端组成隔离栈，经普通用户 Product API 创建并运行会话。正常路径释放脚本
  provider，确认真实 DSH `session.result`，打开再断开 Product SSE 以触发 5 秒
  空闲释放，确认 replay 出现 `session.closed`；强制取消路径在 provider 等待时
  经 Product API 提交 `mode=hard`，确认 replay 出现 `session.cancelled` 且
  `mode=hard`。随后对两个真实终态各运行同一真实 Chromium 历史会话用例，
  各 1/1 通过：旧会话不再订阅或写入，新会话入口可见。脚本化 provider 不证明
  真实付费模型或原双均线生产历史案例的语义，这两个场景仍为 **NOT_RUN**；
  R3 真实会话反馈到 Cloudflare Hub 的整链验收亦为 **NOT_RUN**。两次隔离栈的
  容器、网络和临时数据库均已清理。镜像内 build identity 为
  `dsh-0.1.5rc1-post-u8.302`，该 identity 文件与 Adapter `runtime.py` 的
  SHA-256 均与当前 worktree 对应文件一致。R1 脚本限定 loopback、
  `BYQ_R1_DISPOSABLE_STACK=1` 与 `r1-test-user-` 前缀账号。R4 脚本要求 loopback 上的一次性测试栈、
  `BYQ_R4_DISPOSABLE_STACK=1` 和 `r4-test-user-` / `r4-test-admin-` 前缀账号；
  成功后测试账号密码停留在新值，重新运行须重新预置一次性账号。
  本次采用全新临时账号并销毁数据库。独立 Tester/Reviewer 与 Root 的增量
  结论需另行记录；PR、合并和
  部署均是独立门槛。生产旧反馈表、历史镜像、备份不在本次删除范围。

## 2026-10-03 正式 Hub 定向验收

维护者明确选择正式 Hub。先对正式域名 `/healthz` 做只读检查，返回
`central-feedback-hub: ok`。随后只提交两条明确标记的合成反馈；测试结束时
两条均为 `received`，未调用 `accept` 或 Publisher，未创建公开 Issue。

1. 直接向正式 `/v1/intake` 提交一条符合 `central-feedback-intake.v1` 的合成
   envelope，HTTP 202、回执状态 `received`。其标题为
   `R3正式Hub验收测试 20261003T132947Z be7561`，回执 ID 的 SHA-256 前 16 位为
   `612decfdf9901062`。无令牌查询该回执状态返回 401；持回执 token 查询返回
   HTTP 200、`central-feedback-status.v1`、`received`，无 `github_issue`。
   token 曾仅存于本机权限 0600 的临时文件，不入 Git；拒绝状态核验后已清理。
2. 以当前候选 Backend 源码、当前 relay 源码、一次性 PostgreSQL 和隔离 Docker
   网络启动独立测试栈。测试用户在该 Backend 创建私有草稿、取服务端预览、明确
   确认提交，owner 投影先为 `queued`。relay 向正式 Hub 投递后，owner 再读到
   `received` 与回执，且无 `github_issue`；回执 ID 的 SHA-256 前 16 位为
   `77d340ed89967232`。标题前缀为 `R3正式Hub隔离链路验收`，创建时间在
   2026-10-03 13:29–13:33 UTC。隔离栈容器、网络及无持久卷数据库已清理。

这证明正式 Hub 接收/鉴权及候选 Backend outbox→relay→正式 Hub 回执写回，
不证明 DSH 会话内创建、MCP 与全局批准、浏览器确认，也不证明 Hub 管理员
审核后 BYQ 状态轮询。正式 Hub 管理员凭据不在本工作区。维护者随后报告已将
两条记录先分诊再拒绝；2026-10-03 13:41 UTC 用第一条记录的私有回执令牌
只读查询正式 Hub，HTTP 200、状态 `rejected`，仍无公开 Issue。第二条记录的
隔离数据库和回执令牌已随测试栈清理，因此其 `rejected` 状态仅有维护者操作
回报，未能由本工作区独立查询；不把它计作 BYQ 审核后状态轮询验收。候选未部署，
发布前仍需重新执行旧记录切换预检。Tester、独立 Reviewer、Root 对本增量
证据的结论另行记录。
