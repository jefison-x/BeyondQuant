# ADR-0055：中央反馈审核控制台与短期管理员会话

- Status: Accepted
- Date: 2026-09-05
- Accepted: 2026-09-05
- Decision scope: 官方 Central Feedback Hub 的维护者审核界面、管理员认证和浏览器安全边界
- Related: ADR-0015、ADR-0049、ADR-0052、ADR-0053、ADR-0054

## 背景

ADR-0052/0053 已建立 `received → triaged → accepted|rejected|duplicate` 的中央审核状态机，只有中央采纳后才允许隔离
Publisher 创建固定仓库 Issue。Phase 93/94 只提供 Bearer 管理 API 和命令行 runbook；正式部署完成后，维护者无法在
Cloudflare 或 BYQ 页面中直接查看和处理中央反馈，必须手写 curl。维护者明确要求增加易用的中央管理员界面。

这个界面属于官方 Hub 的 operator surface，不是普通 BYQ Product 页面。它不能把 Hub admin secret、GitHub App
credential 或中央反馈内容下放到普通安装，也不能改变 local user approval 与 central acceptance 的分离。

Community 只读仓库没有中央匿名反馈或审核控制台；Issue template 的结构化内容与敏感信息提示继续为
`PORT_UX`/`PORT_TESTS`，人工审批 UX 为 `REFERENCE_ONLY`，新的中央界面为 `REPLACE`。不复制 Community 源码、运行时、
credential、数据库或 Git history。

## 决策

1. Hub Worker 在同一自定义域名提供 `/admin` 中文审核控制台及同源静态资源。控制台只调用既有、分页的
   `/v1/admin/*` 合同，不访问 Product Backend、Gateway、MCP、DSH、PostgreSQL、GitHub 或 Publisher Worker。
2. Operator 必须为 `/admin*` 和 `/v1/admin/*` 配置 Cloudflare Access，只允许维护者身份。Hub 自身仍执行第二层认证；
   Access 不能替代 Hub authorization，且不能保护整个 hostname，以免阻断公开 intake/status/health 路径。
3. 首次进入时，维护者把现有 `BYQ_FEEDBACK_HUB_ADMIN_TOKEN` 通过同源 HTTPS POST 交给 Hub。Token 只用于本次交换，
   不写入 HTML、URL、Cookie、D1、日志、`localStorage` 或 `sessionStorage`。验证成功后 Hub 使用该 secret 的 HMAC 签发
   最长八小时的无状态 session capability，并仅写入 `Secure`、`HttpOnly`、`SameSite=Strict`、`Path=/` Cookie；secret
   轮换会立即使旧会话失效。
4. Cookie-authenticated mutation 必须同时满足 exact same-origin `Origin` 和封闭的 UI request header，防止跨站请求；
   Bearer CLI 路径保持兼容。logout 清除 Cookie。admin response、HTML 和资源均禁止敏感缓存。
5. 页面只呈现 D1 已保存的不可变公开候选快照、状态、时间、fingerprint、duplicate/Issue 结果和允许的状态转换。
   所有动态内容使用 DOM text nodes，不解释为 HTML。列表必须使用服务端 status filter 与 offset/limit 分页；详情按当前
   有界页懒加载呈现，不增加全量读取。
6. UI 只允许 `received → triaged`，以及 `triaged → accepted|rejected|duplicate`。每次动作都要求 3–1000 字审核理由；
   duplicate 还要求有效 receipt。Worker/Durable Object 继续负责状态、CAS、audit 与 outbox invariant，页面按钮不成为
   authority。`accepted` 仍只写 D1 outbox，只有隔离 Publisher 可创建 Issue。
7. 页面只使用 Worker 自带 HTML/CSS/JavaScript，不加载 CDN、字体、分析脚本或第三方资源。CSP 限制到同源脚本、样式和
   connect，禁止 framing/base/object；代码不得把 token 写入 console/error。Publisher 的 secret/binding 和 Product Plane
   均不改变。

## 验收

- workerd tests 覆盖页面/资源 CSP 与 no-store、错误 token、短期 Cookie 属性、logout、过期/篡改 Cookie、Bearer 兼容、
  cookie mutation same-origin/自定义 header、分页目录和完整审核状态转换；
- 静态安全测试证明页面无外部资源、inline script、`localStorage`/`sessionStorage`、GitHub credential 或 secret literal，
  动态反馈只通过 `textContent`/DOM node 呈现；
- UI 支持 desktop/mobile、loading/error/empty、状态筛选、分页、详情、动作确认和明确的公开 Issue 风险提示；
- architecture、typecheck、Hub/Publisher regression、dual Worker dry-run 和 Git deploy verifier 通过；Cloudflare Access 配置和
  真实生产部署仍是维护者运维步骤。

## 拒绝的替代方案

- 把 Admin Token 放入前端构建变量或 HTML：公开 Worker bundle 无法保密。
- Token 放在 URL、普通 Cookie、`localStorage` 或 `sessionStorage`：会扩大 history、日志、持久浏览器存储或脚本读取风险。
- 只信任 Cloudflare Access header 并移除 Hub credential：改变既有 API authorization 且使 Access 配置错误直接变成越权。
- 把页面加入 BYQ Product 前端：会让普通安装感知中央 credential/content，并混淆本地 admin 与官方维护者权限。
- 让 Hub 直接创建 GitHub Issue：会破坏 ADR-0049/0053 的 Publisher 隔离。

## 回滚

移除 `/admin` 静态路由和 session exchange 即可回到原 Bearer CLI 管理方式；D1 schema、receipt、audit、outbox、Queue、
Publisher 和已创建 Issue 均不变。紧急失效所有浏览器会话可轮换 Hub Admin Token；不得为回滚删除反馈或审核记录。
