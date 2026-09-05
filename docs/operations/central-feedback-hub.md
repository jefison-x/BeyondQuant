# Cloudflare Central Feedback Hub 安装与配置

本方案只由 `jefison-x/BeyondQuant` 维护者部署一次，适用于 Cloudflare Workers Free。普通 BYQ 用户不需要 Cloudflare 或
GitHub 账号、Token、仓库、域名或 Hub 凭据；他们在小巴会话中预览反馈，在全局审批中心批准后即可提交。

本地 BYQ 的 `feedback-hub-relay` 容器继续运行，它不是中央服务。中央服务由两个 Cloudflare Worker、一个 D1、两个
SQLite Durable Object namespace、一个主 Queue 和一个 DLQ 组成，不再需要中央主机、PostgreSQL 或 Docker。

## 1. 准备账号和 GitHub App

1. 使用一个 Cloudflare account；Free 计划即可起步。安装 Node.js 22 或更高版本。
2. 在 GitHub 创建 App，只安装到 `jefison-x/BeyondQuant`：
   - Repository permissions：`Issues: Read and write`；
   - 不授予 Contents、Pull requests、Actions、Administration、Secrets 或 Deployments；
   - App 不需要 webhook URL/secret；
   - 记录 App ID、installation ID，并下载 private key PEM。
3. 将 `BYQ_FEEDBACK_HUB_STATUS_SECRET` 另存到密码管理器和加密备份。该值生成历史 receipt capability，丢失或轮换后旧安装
   无法查询反馈状态。

## 2. 登录并安装锁定依赖

在仓库根目录执行：

```bash
cd deploy/feedback-hub-cloudflare
npm ci --ignore-scripts --legacy-peer-deps
npx wrangler login
```

依赖已由 `package-lock.json` 精确锁定；不要在正式部署时使用 `latest` 或删除 lockfile。

## 3. 创建 D1 和 Queue

```bash
npx wrangler d1 create byq-feedback-hub
npx wrangler queues create byq-feedback-publish
npx wrangler queues create byq-feedback-publish-dlq
```

把第一条命令返回的 D1 `database_id` 写入 `wrangler.hub.jsonc`，替换
`00000000-0000-0000-0000-000000000000`。repository 已固定为 `jefison-x/BeyondQuant`，不要改成用户输入或任意变量。

## 4. 配置隔离 secret

先生成三个互不相同的值并安全保存：

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

分别作为 Hub status secret、Hub admin token，以及 Hub/Publisher 共享的内部 publisher service token。

将 secret 写入 Hub Worker：

```bash
npx wrangler secret put BYQ_FEEDBACK_HUB_STATUS_SECRET --config wrangler.hub.jsonc
npx wrangler secret put BYQ_FEEDBACK_HUB_ADMIN_TOKEN --config wrangler.hub.jsonc
npx wrangler secret put BYQ_FEEDBACK_PUBLISHER_TOKEN --config wrangler.hub.jsonc
```

将同一个 publisher service token 和 GitHub App 凭据只写入 Publisher Worker：

```bash
npx wrangler secret put BYQ_FEEDBACK_PUBLISHER_TOKEN --config wrangler.publisher.jsonc
npx wrangler secret put BYQ_FEEDBACK_GITHUB_APP_ID --config wrangler.publisher.jsonc
npx wrangler secret put BYQ_FEEDBACK_GITHUB_INSTALLATION_ID --config wrangler.publisher.jsonc
npx wrangler secret put BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY --config wrangler.publisher.jsonc < /absolute/path/app.pem
```

GitHub private key 不得写入 Hub config、`.dev.vars`、D1、日志或仓库。Publisher Worker 未开放 `workers.dev`，并且没有 D1、
Durable Object、Product Backend 或源码绑定。

## 5. 验证、迁移并部署

先做完全本地的 workerd/D1/Durable Object/Queue/fake-GitHub 验证：

```bash
npm run check
npm run dry-run
```

然后应用 D1 migration，并按 Hub → Publisher 顺序部署：

```bash
npx wrangler d1 migrations apply byq-feedback-hub --remote --config wrangler.hub.jsonc
npx wrangler deploy --config wrangler.hub.jsonc
npx wrangler deploy --config wrangler.publisher.jsonc
```

`wrangler deploy` 会显示 Hub 的 `workers.dev` HTTPS 地址。验证：

```bash
curl -fsS https://byq-feedback-hub.<你的workers子域>.workers.dev/healthz
```

预期为 `{"service":"central-feedback-hub","status":"ok"}`。首次部署不会创建 GitHub Issue；只有中央管理员显式
`triage` 后再 `accept` 才会进入 D1 outbox。

## 6. 自定义域名和访问保护

可以先使用 `workers.dev` 地址。准备正式域名后，在 Cloudflare Dashboard 为 `byq-feedback-hub` Worker 添加 Custom Domain，
例如 `feedback.example.org`，无需自建 TLS 代理。

公网只需要：

- `POST /v1/intake`
- `GET /v1/status/{receipt_id}`
- `GET /healthz`

为 `/v1/admin/*` 增加 Cloudflare Access application 或等价的维护者访问策略；Worker 内部仍会验证 admin bearer。边缘设置
32 KiB body limit 和按源 IP 的辅助限速。`/internal/*` 只供 Publisher Service Binding 使用，即使被公网探测也必须通过共享
service token。

## 7. 中央审核验收

在当前维护终端临时设置变量，不要写入 shell history 或仓库：

```bash
export BYQ_FEEDBACK_HUB_ORIGIN=https://feedback.example.org
export BYQ_FEEDBACK_HUB_ADMIN_TOKEN=<刚才保存的admin-token>
```

分页查看待审核项：

```bash
curl -fsS -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  "$BYQ_FEEDBACK_HUB_ORIGIN/v1/admin/feedback?status=received&limit=20&offset=0"
```

对一条明确标为安装验收的 feedback 依次分诊、采纳：

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"rationale":"已确认信息完整且不含敏感数据"}' \
  "$BYQ_FEEDBACK_HUB_ORIGIN/v1/admin/feedback/<receipt>/triage"

curl -fsS -X POST \
  -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"rationale":"批准安装验收反馈进入官方Issue队列"}' \
  "$BYQ_FEEDBACK_HUB_ORIGIN/v1/admin/feedback/<receipt>/accept"
```

Cron 最迟约一分钟扫描 D1 outbox，Queue Consumer 再创建 Issue。也可使用 `/reject`，或用 `/duplicate` 并附带
`duplicate_of`。验收结束后在 GitHub 手工关闭测试 Issue；Hub 不自动删除或关闭 Issue。

## 8. 连接当前 BYQ 正式环境

中央链路验收后，在 BYQ 根 `.env` 增加：

```dotenv
BYQ_FEEDBACK_HUB_URL=https://feedback.example.org
BYQ_FEEDBACK_HUB_RELAY_TOKEN=<该本地部署独立的随机relay-token>
```

relay token 可用 `openssl rand -hex 32` 生成；它只保护本地 Backend/relay internal API，不上传中央 Hub。重建本地组件：

```bash
docker compose up -d --build --wait backend feedback-hub-relay
```

installation ID 由 Backend 自动生成并持久化。浏览器和小巴看不到 relay token；relay 没有 GitHub credential。若 URL 为空、
Cloudflare 超免费额度或中央服务不可达，提交仍保存在本地 outbox并重试，不伪造成功。

中央地址稳定后，应把 HTTPS 地址写入后续 BYQ 发行包/安装器默认 `BYQ_FEEDBACK_HUB_URL`。届时普通用户连 Hub URL 都无需
填写。不要同时把旧 local direct publisher 配置到官方仓库，否则可能产生双出口。

## 9. 免费额度、监控和恢复

- Workers Free、D1、SQLite Durable Objects 和 Queues 都有每日硬额度；超限会失败而不是自动计费；
- 免费 Queue 的保留期较短，但 Queue 不是事实来源。未完成项持续保存在 D1 outbox，`enqueued`/`dispatching` 超时会重投；
- 监控 Worker errors、D1 rows read/written、Queue backlog/retries/DLQ 和 GitHub rate limit；
- 使用 D1 Time Travel/导出能力，并单独加密备份 status secret。只有数据库没有 status secret 不能完整恢复历史状态查询；
- 暂停发布只需停用 Publisher Queue Consumer，intake/审核和 D1 outbox 继续工作；
- 暂停某个 BYQ 安装外发只需清空该安装的 `BYQ_FEEDBACK_HUB_URL`，本地队列不丢失；
- 不要通过删除 receipt/outbox 解决失败。修复 App 权限或 secret 后重新部署 Publisher，让 D1 dispatcher/reconciliation 恢复；
- Hub 不是 Engineering Plane。采纳反馈不会自动改代码、创建 PR、合并或部署。
