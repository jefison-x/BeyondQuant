# Central Feedback Hub 安装与配置

本方案只由 `jefison-x/BeyondQuant` 维护者部署一次。普通 BYQ 用户不需要 GitHub 账号、Token、仓库或 Hub 凭据；他们在小巴
会话中预览反馈，在全局审批中心批准后即可提交。

## 1. 准备域名与 TLS

为 Hub 准备一个专用 HTTPS 域名，例如 `feedback.example.org`。`deploy/feedback-hub/compose.yml` 默认只把 Hub 绑定到
`127.0.0.1:8800`，请使用现有 Caddy/Nginx/云负载均衡器终止 TLS，并只反向代理到该端口。公网只开放：

- `POST /v1/intake`
- `GET /v1/status/{receipt_id}`
- `GET /healthz`

不要公开 `/internal/*`；`/v1/admin/*` 最好再用 VPN、IP allowlist 或独立管理入口保护。边缘代理应设置请求体上限 32 KiB，
按源 IP 做辅助限速，并保留 Hub 自己的 installation 级限流。Hub 不需要 Cookie 或用户身份。

## 2. 创建中央 GitHub App

在 GitHub 创建一个 App，并只安装到 `jefison-x/BeyondQuant`：

- Repository permissions：`Issues: Read and write`；
- 不授予 Contents、Pull requests、Actions、Administration、Secrets 或 Deployments；
- 记录 App ID 和 installation ID，把 private key 保存到主机 secret 目录，权限设为仅部署账号可读；
- App 不需要 webhook URL/secret。

## 3. 配置 Hub secret

在 `deploy/feedback-hub/.env` 写入下列值（此文件已被 Git 忽略；不要提交）：

```dotenv
BYQ_FEEDBACK_HUB_POSTGRES_PASSWORD=<随机数据库密码>
BYQ_FEEDBACK_HUB_ADMIN_TOKEN=<至少32字节随机值>
BYQ_FEEDBACK_HUB_STATUS_SECRET=<至少32字节随机值，后续不要轮换或丢失>
BYQ_FEEDBACK_PUBLISHER_TOKEN=<至少32字节随机值>
BYQ_FEEDBACK_GITHUB_APP_ID=<GitHub App ID>
BYQ_FEEDBACK_GITHUB_INSTALLATION_ID=<installation ID>
BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY_HOST_FILE=/absolute/secret/path/app.pem
```

可用 `openssl rand -hex 32` 分别生成三个独立 secret。`STATUS_SECRET` 用于生成 receipt capability token；丢失后旧安装将无法
查询状态，因此应纳入加密备份。不要在 Hub 上设置 `BYQ_FEEDBACK_GITHUB_TOKEN`，除非临时使用仅限该仓库、仅 Issues write 的
fine-grained token 作为故障降级。

以下命令需要读取 admin token 时，先只在当前维护终端导出该文件；退出终端后环境变量即失效：

```bash
set -a
. deploy/feedback-hub/.env
set +a
```

## 4. 启动与验证中央服务

在仓库根目录执行：

```bash
docker compose --env-file deploy/feedback-hub/.env \
  -f deploy/feedback-hub/compose.yml \
  -f deploy/feedback-hub/compose.github-app.yml \
  up -d --build --wait
curl -fsS https://feedback.example.org/healthz
```

首次启动只建空表，不会创建 GitHub Issue。用 admin API 分页查看待审核项：

```bash
curl -fsS -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  'https://feedback.example.org/v1/admin/feedback?status=received&limit=20&offset=0'
```

对一个 receipt 依次调用 `triage` 和 `accept`；每次 body 必须有审核理由：

```bash
curl -fsS -X POST -H "Authorization: Bearer $BYQ_FEEDBACK_HUB_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"rationale":"已确认信息完整且不含敏感数据"}' \
  "https://feedback.example.org/v1/admin/feedback/<receipt>/triage"
```

将最后的路径改为 `/accept` 后，中央 publisher 才会创建 Issue。也可用 `/reject`，或用
`/duplicate` 并附带 `duplicate_of`。建议先用一条明确标注为安装验收的反馈走完整链路，再关闭测试 Issue。

## 5. 连接普通 BYQ 部署

中央服务验证后，在每个 BYQ 部署的根 `.env` 只增加：

```dotenv
BYQ_FEEDBACK_HUB_URL=https://feedback.example.org
BYQ_FEEDBACK_HUB_RELAY_TOKEN=<该本地部署已有的独立随机 relay token>
```

然后重建 Backend/relay：

```bash
docker compose up -d --build --wait backend feedback-hub-relay
```

installation ID 由 Backend 首次启动自动生成并持久化，不需要用户填写。浏览器和小巴看不到 relay token；relay 也没有 GitHub
credential。若 URL 为空或中央服务不可达，提交仍保存在本地 outbox，界面显示等待配置/重试。

中央 Hub 启用后，不要同时把旧的 local direct publisher 配到同一个官方仓库；旧 publisher 仅作为高级 self-hosted 兼容出口，
双出口可能把同一反馈发布两次。

正式域名验证稳定后，维护者应再把该 HTTPS 地址写入 BeyondQuant 后续发行包/安装器的默认
`BYQ_FEEDBACK_HUB_URL`。当前代码刻意保持空默认值，因为尚未确定和验证官方域名；不要把示例域名发布成默认值。完成这一步后，
普通开源用户连 Hub URL 都不需要填写，只需按常规方式启动 BeyondQuant。relay token 仍由部署模板生成或保存在服务端 `.env`，
不会展示给产品用户。

## 6. 运维与恢复

- 先停止 `publisher` 可安全暂停 GitHub 写入，Hub intake 和审核继续工作；
- 先清空 local `BYQ_FEEDBACK_HUB_URL` 可暂停某个安装外发，本地队列不丢失；
- 备份中央 PostgreSQL volume 和 `.env` 中的 status secret；恢复后 worker lease 会超时重领；
- Publisher 每次创建前按 immutable marker 对账，超时不确定时不会盲目重复 Issue；
- 不要删除 receipt/outbox 解决失败。修复 App 权限后重启 publisher；终态失败需通过受控运维迁移重新排队，当前没有公开重放 API；
- Hub 不是 Engineering Plane。采纳反馈不会自动改代码、创建 PR、合并或部署。
