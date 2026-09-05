# ADR-0056：中央管理员密码直登与登录节流

- Status: Accepted
- Date: 2026-09-05
- Accepted: 2026-09-05
- Decision scope: Central Feedback Hub 管理员认证、登录防爆破与可选 Cloudflare Access
- Related: ADR-0015、ADR-0052、ADR-0053、ADR-0054、ADR-0055

## 背景

ADR-0055 交付了 Hub 自有 Admin Token → 短期 HttpOnly session，同时要求维护者额外配置 Cloudflare Access。该双层方案适合
多维护者或需要统一 IdP/MFA 的环境，但当前官方 Hub 只有一名低频维护者；强制 Access 增加了域名 path、身份策略和登录步骤，
与“开源用户零配置、中央维护者尽量少配置”的目标不匹配。维护者明确选择由 Hub 直接提供管理员密码登录，并保留 Zero Trust
作为可选增强。

直接暴露登录端点不能只把 token 改名。密码失败必须在强一致、跨 isolate、可重启的状态中节流；Cookie 也不能用可人工记忆的
密码直接签名，否则获得 Cookie 的攻击者可能离线猜测密码。Community 只读仓库没有中央 Hub、单维护者认证或 Cloudflare 登录
节流实现；Phase 95 的 `REPLACE`、结构化公开候选 `PORT_UX`/`PORT_TESTS` 和人工审批 `REFERENCE_ONLY` 分类继续适用，未复制
Community 源码、数据、credential、runtime 或 Git history。

## 决策

1. `/admin` 默认允许直接打开并输入单一管理员密码，不创建用户名、用户表、密码找回、邮件、Product identity 或第二套认证系统。
   为兼容已部署 secret 和 Bearer 运维合同，密码继续保存在 Cloudflare 加密 secret
   `BYQ_FEEDBACK_HUB_ADMIN_TOKEN`；UI 和文档称其为“管理员密码（兼容变量名）”。长度必须为 16–256 字符，推荐密码管理器生成。
2. 密码只经同源 HTTPS POST 进入 Hub，不写入 HTML、URL、Cookie、D1、日志、`localStorage` 或 `sessionStorage`。比较继续使用
   constant-work equality；成功后只签发最长八小时的 `Secure`、`HttpOnly`、`SameSite=Strict` Cookie。应用不阻止维护者选择的
   浏览器密码管理器，但不自行持久化密码。
3. Hub 按入口请求的 Cloudflare `CF-Connecting-IP` 计算带 Hub status secret 的 HMAC source key；原始 IP 不写入 D1、Durable
   Object、BYQ application log 或响应。每个 source key 路由到独立 SQLite `AdminLoginGate` Durable Object。15 分钟窗口内前四次错误返回通用
   401，第五次开始把该来源锁定 15 分钟并返回 429/`Retry-After`；正确密码在未锁定时原子清除失败状态。缺失 IP header 时使用
   单一 fail-closed bucket，不信任 `X-Forwarded-For`。每次失败设置 window/lock 到期 alarm，成功或 alarm 会删除状态，避免
   分布式扫描形成永久存储。
4. UI session exchange 和 Bearer CLI 都必须经过同一登录门，不能通过旧管理 API 绕过节流。已签发 session 的读取不重复计入登录
   额度；Cookie mutation 继续要求 exact `Origin` 与封闭 UI header。来源锁定不影响其他来源、公开 intake/status/health、Queue
   或 Publisher。
5. v2 session signature 使用高熵 Hub status secret，并加入由该 secret 对当前管理员密码导出的 version fingerprint。Cookie 不含
   fingerprint 或密码；部署 v2 会使旧 v1 Cookie 失效，后续更换管理员密码也立即使旧 session 失效。status capability 与 admin
   session 使用不同 domain-separated message。
6. Cloudflare Access/Zero Trust 改为可选的 defense-in-depth，适合需要 MFA、企业 IdP 或边缘身份审计的维护者。若启用，只保护
   `/admin*` 和 `/v1/admin/*`，不得阻断公开入口。Hub 密码、节流和 session authorization 始终存在，不能因 Access 启用而移除。
7. `workers.dev` 和 preview URL 继续关闭，正式管理入口只使用 TLS Custom Domain。审核状态机、D1/outbox、固定 repository 和
   Publisher-only GitHub writer 边界完全不变。

## 验收

- workerd 覆盖直接密码登录、错误密码、同源约束、第五次锁定、`Retry-After`、锁定时正确密码拒绝、不同来源隔离、成功后清零、
  alarm 到期清理、Bearer 同门节流、v2 Cookie 的 tamper/expiry/logout 和密码不进入 Cookie；
- Wrangler/部署契约验证 `ADMIN_LOGIN_GATE` binding 与独立 `v2 new_sqlite_classes` migration，并对 Hub/Publisher 双包 dry-run；
- 静态/架构测试拒绝 raw IP 持久化、密码浏览器持久化、密码直接作为 Cookie HMAC key、Access 强制依赖、`workers.dev` 回归和
  Hub GitHub credential；
- desktop/mobile 真实 Chrome 覆盖直接密码登录、刷新保留 session、错误/锁定提示、无横向溢出、同源网络与空 Console。

## 拒绝的替代方案

- 继续强制 Cloudflare Access：安全性最高，但不符合维护者选择的最少配置默认路径；仍保留为可选增强。
- 自建用户名、密码哈希数据库、找回和 MFA：单维护者不需要，且会建立第二套身份生命周期。
- 只把 Token 文案改成密码：没有公开登录防爆破，且 Bearer API 可绕过 UI 限制。
- 使用 D1 全局计数或 isolate 内存：前者形成并发争用，后者在多 isolate、驱逐或部署后失效。
- 将原始 IP 写入 D1/audit：对完成节流不必要，并扩大个人数据留存。

## 回滚

代码可通过新 PR 恢复强制 Access 或回到高熵 token-only 操作；不得删除 Durable Object namespace、D1 feedback、audit、outbox 或
Issue mapping。紧急情况下先在 Cloudflare 轮换 `BYQ_FEEDBACK_HUB_ADMIN_TOKEN` 使所有 session 失效，再禁用 Custom Domain；
Publisher 和本地 outbox 可独立继续保留。

## 官方参考

- [Cloudflare `CF-Connecting-IP`](https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-connecting-ip)
- [Durable Objects strongly consistent storage](https://developers.cloudflare.com/durable-objects/best-practices/access-durable-objects-storage/)
- [Cloudflare Access application paths](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/)
