# Cloudflare Central Feedback Hub：GitHub 自动部署

本方案只由 `jefison-x/BeyondQuant` 维护者配置一次，适用于 Cloudflare Workers Free。Cloudflare 直接读取 GitHub，后续
`main` 更新会自动构建并部署，不需要在 BYQ 主机安装 Wrangler。普通 BYQ 用户仍不需要 Cloudflare/GitHub 账号、Token、
仓库、域名或 Hub credential。

安全边界要求保留两个 Cloudflare project：公网 `byq-feedback-hub` 和私有 Queue Consumer
`byq-feedback-publisher`。两者连接同一仓库，但使用不同 deploy command 和 runtime secrets。Cloudflare 官方不支持用一个
Deploy button 同时发布 monorepo 中多个 Worker；不要为了单按钮把它们合并。

## 1. 一次性准备

1. 使用一个 Cloudflare account，Free 计划即可起步。
2. 在 GitHub 创建 BYQ Issue Publisher App，只安装到 `jefison-x/BeyondQuant`：
   - Repository permissions：`Issues: Read and write`；
   - 不授予 Contents、Pull requests、Actions、Administration、Secrets 或 Deployments；
   - 不需要 webhook URL/secret；
   - 保存 App ID、installation ID 和 private key PEM。
3. 在密码管理器生成并保存三个互不相同的 64 位十六进制随机值：
   - Hub status secret；
   - Hub admin token；
   - Hub/Publisher 共享的 publisher service token。

也可只用下面的命令生成三次；这些值不要写入仓库、GitHub Actions 或 Workers build variables：

```bash
openssl rand -hex 32
```

Cloudflare 用于 source build/check 的 `Cloudflare Workers and Pages` GitHub App 与上面的 BYQ Issue Publisher App 是两个不同
主体：前者的 repository access 只选择 `BeyondQuant`，后者只授予固定仓库 Issues read/write。

## 2. 从 GitHub 导入 Hub Worker

在 Cloudflare Dashboard 打开 **Workers & Pages → Create → Import a repository**，授权 Cloudflare GitHub App 时选择
**Only select repositories → `jefison-x/BeyondQuant`**。使用以下配置：

| 设置 | 值 |
|---|---|
| Project/Worker name | `byq-feedback-hub` |
| Git repository | `jefison-x/BeyondQuant` |
| Production branch | `main` |
| Root directory | `deploy/feedback-hub-cloudflare` |
| Build command | `npm run cloudflare:build` |
| Deploy command | `npm run cloudflare:deploy:hub` |
| Non-production branch builds | Disabled |
| 如果界面必须填写 preview command | `npm run cloudflare:preview` |

首次 build 如果提示缺少 required secrets，是预期的 fail-closed 行为。Project 已创建后，进入
**Settings → Variables and Secrets → Add → Secret**，添加：

| Hub runtime secret | 值 |
|---|---|
| `BYQ_FEEDBACK_HUB_STATUS_SECRET` | 保存的 status secret |
| `BYQ_FEEDBACK_HUB_ADMIN_TOKEN` | 保存的 admin token |
| `BYQ_FEEDBACK_PUBLISHER_TOKEN` | 保存的 publisher service token |

保存后回到 **Deployments/Builds** 对失败 build 选择 **Retry**。Hub deploy command 会以 `DB` binding 应用 D1 migration，
再发布 Worker；Wrangler config 会自动配置 `byq-feedback-hub` D1、两个 SQLite Durable Object namespace 和
`byq-feedback-publish` Queue。仓库不保存 Cloudflare account id 或 D1 id。

在 **Settings → Builds → Build watch paths** 中设置 include：

```text
deploy/feedback-hub-cloudflare/*
services/feedback-hub-cloudflare/*
```

## 3. 从同一 GitHub 仓库导入 Publisher Worker

Hub 首次成功后，再次选择 **Import a repository**，仍连接同一个仓库：

| 设置 | 值 |
|---|---|
| Project/Worker name | `byq-feedback-publisher` |
| Git repository | `jefison-x/BeyondQuant` |
| Production branch | `main` |
| Root directory | `deploy/feedback-hub-cloudflare` |
| Build command | `npm run cloudflare:build` |
| Deploy command | `npm run cloudflare:deploy:publisher` |
| Non-production branch builds | Disabled |
| 如果界面必须填写 preview command | `npm run cloudflare:preview` |

在 Publisher 的 **Settings → Variables and Secrets** 添加：

| Publisher runtime secret | 值 |
|---|---|
| `BYQ_FEEDBACK_PUBLISHER_TOKEN` | 与 Hub 完全相同的 publisher service token |
| `BYQ_FEEDBACK_GITHUB_APP_ID` | GitHub App ID |
| `BYQ_FEEDBACK_GITHUB_INSTALLATION_ID` | GitHub App installation ID |
| `BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY` | private key PEM 全文 |

然后 Retry build。Publisher config 会绑定已有 `byq-feedback-hub` Service Binding、主 Queue，并自动配置
`byq-feedback-publish-dlq`。它的 `workers.dev` 与 preview URL 都关闭，且没有 D1、Product Backend、PostgreSQL、源码、Git、
Docker 或 DSH binding。

Publisher build watch include：

```text
deploy/feedback-hub-cloudflare/*
services/feedback-hub-cloudflare/src/contracts.ts
workers/feedback-publisher-cloudflare/*
```

## 4. 验证中央链路

Hub 首次部署会显示 `workers.dev` HTTPS 地址。打开：

```text
https://byq-feedback-hub.<你的workers子域>.workers.dev/healthz
```

预期：

```json
{"service":"central-feedback-hub","status":"ok"}
```

检查 Cloudflare Dashboard：

- Hub bindings 有 D1、`INSTALLATION_GATE`、`FEEDBACK_GATE` 和 `PUBLISH_QUEUE`；
- Publisher bindings 只有 Hub Service Binding、Queue Consumer、固定 repository var 和四个加密 secret；
- D1 migration `0001_central_feedback.sql` 已记录为 applied；
- 主 Queue 和 DLQ 均存在；
- GitHub App 仍只有 Issues read/write。

首次部署不会创建 GitHub Issue。只有匿名 intake 被中央管理员依次 `triage`、`accept` 后，Publisher 才会创建固定仓库 Issue。

## 5. 自定义域名和管理入口

可以先使用 `workers.dev`。准备正式域名后，为 Hub 添加 Custom Domain，例如 `feedback.example.org`。公网只需要：

- `POST /v1/intake`
- `GET /v1/status/{receipt_id}`
- `GET /healthz`

为 `/v1/admin/*` 叠加 Cloudflare Access 或等价维护者策略；Worker 内仍验证 admin bearer。边缘设置 32 KiB body limit 和按源
IP 的辅助限速。`/internal/*` 只供 Publisher Service Binding 使用，即使被公网探测仍必须通过 publisher token。

## 6. 中央审核验收

在当前维护终端临时设置 origin 和 admin token，不要写入仓库或 shell profile：

```bash
export BYQ_FEEDBACK_HUB_ORIGIN=https://feedback.example.org
export BYQ_FEEDBACK_HUB_ADMIN_TOKEN=<保存的admin-token>
```

分页查看并审核一条明确标为安装验收的反馈：

```bash
curl -fsS -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  "$BYQ_FEEDBACK_HUB_ORIGIN/v1/admin/feedback?status=received&limit=20&offset=0"

curl -fsS -X POST -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"rationale":"已确认信息完整且不含敏感数据"}' \
  "$BYQ_FEEDBACK_HUB_ORIGIN/v1/admin/feedback/<receipt>/triage"

curl -fsS -X POST -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"rationale":"批准安装验收反馈进入官方Issue队列"}' \
  "$BYQ_FEEDBACK_HUB_ORIGIN/v1/admin/feedback/<receipt>/accept"
```

Cron 最迟约一分钟扫描 D1 outbox，Queue Consumer 再创建 Issue。验收后手工关闭测试 Issue；Hub 不自动关闭或删除 Issue。

## 7. 连接当前 BYQ 正式环境

中央链路验收后，在 BYQ 根 `.env` 增加：

```dotenv
BYQ_FEEDBACK_HUB_URL=https://feedback.example.org
BYQ_FEEDBACK_HUB_RELAY_TOKEN=<该BYQ部署独立的随机relay-token>
```

relay token 只保护本地 Backend/relay internal API，不上传中央 Hub。重建本地组件：

```bash
docker compose up -d --build --wait backend feedback-hub-relay
```

installation ID 由 Backend 自动生成并持久化。浏览器、小巴和 relay 都没有 GitHub credential。Cloudflare 不可达或免费额度耗尽
时，提交继续保存在本地 outbox并重试，不伪造成功。

## 8. 后续自动更新和回滚

- 只有通过仓库 CI 并合并到 `main` 的提交触发生产部署；PR branch 不创建 Cloudflare state；
- Hub pipeline 在部署新代码前应用尚未执行的 D1 migration；Publisher pipeline 不访问 D1；
- Dashboard runtime secrets 不会因后续 Wrangler code deploy 被删除；
- 暂停自动部署：分别进入 Worker **Settings → Builds → Disable builds**；现有 Worker/D1/Queue 继续工作；
- 回滚代码：通过正常 Git PR revert 并合并到 `main`，不得 force push；
- D1 schema 只做兼容 forward repair，不自动降级、删表或删除 outbox；
- 暂停 GitHub 写入：禁用 Publisher Queue Consumer或撤销 BYQ GitHub App，Hub intake/outbox 继续持久化；
- Cloudflare source GitHub App 只需保留 `BeyondQuant` 仓库访问；断开它不会删除现有 Worker。

## 9. CLI fallback

Git integration 故障时才使用 CLI。仓库根目录执行：

```bash
cd deploy/feedback-hub-cloudflare
npm ci --ignore-scripts --legacy-peer-deps
npx wrangler login
npm run cloudflare:build
```

用 `wrangler secret put --config <对应config>` 配置上表中的 runtime secrets，然后依次运行：

```bash
npm run cloudflare:deploy:hub
npm run cloudflare:deploy:publisher
```

不要把 Cloudflare API token 放进 GitHub Actions，也不要同时启用旧 local direct publisher 指向同一官方仓库。Hub 不是
Engineering Plane；采纳反馈不会自动改代码、创建 PR、合并或部署 BYQ。
