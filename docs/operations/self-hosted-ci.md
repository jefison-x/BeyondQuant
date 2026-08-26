# Self-Hosted CI（本地 GitHub Actions Runner）

Status: **Active** — `scripts/ci/local-ci.sh` 和
`.github/workflows/ci-selfhosted.yml` 的 companion。

## 原因

该账户的 GitHub-hosted Actions runners 需要付费，因此 `ci.yml` 可能因
payments/spending limit 失败。Self-hosted runner 让 GitHub 继续 orchestration
并在 PR 显示 status，但 checks 在本地机器免费执行。

Workflow 运行项目自身
`scripts/ci/local-ci.sh --all --with-e2e --with-smoke`，覆盖 locked frontend
build/unit suite、mocked browser、isolated full Compose、real Product API
browser flow 和 service checks；high/critical npm advisories 会使 frontend gate
失败。

## Architecture

```text
GitHub（仅 orchestration）
  └─ PR / push ─► .github/workflows/ci-selfhosted.yml
                     └─ local-ci on [self-hosted, linux, x64, byq]
                          └─ local actions-runner systemd service
                               ├─ docker（clean CI PostgreSQL）
                               ├─ python3（architecture tests）
                               ├─ node 22（frontend build + Vitest）
                               └─ local-ci.sh --all --with-e2e --with-smoke
```

Core checks 使用 clean CI-only PostgreSQL。Smoke tier 也启动 Compose，但每次
run 都分配 unique project name、network、volumes、images、Docker loopback
ports、bootstrap identity 和 Product API URL；cleanup 只删除 run-scoped
resources，不碰 developer `beyondquant` stack。

## Runner machine prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| OS | Linux x64 | macOS/Windows 要使用 matching runner package |
| Docker Engine + Compose v2 | recent | runner user 需有 Docker socket access |
| Python 3 | 3.10+ | architecture tests；services 已 containerized |
| Node.js | 22.12+、<23 | locked Vite/Vitest/Playwright |
| Disk | ≥ 50 GB free | images、node_modules、PG volumes |
| RAM | ≥ 8 GB | Compose build/parallel tests |
| `git`、`bash` | — | runner/local-ci requirements |

快速检查：

```bash
docker --version && docker compose version
python3 --version
node --version && npm --version
git --version
id -nG | tr ' ' '\n' | grep -q docker && echo "docker group OK"
```

## 一次性注册 runner

1. 打开 **GitHub → jefison-x/BeyondQuant → Settings → Actions → Runners →
   New self-hosted runner → Linux → x64**。
2. 复制页面上的 download/configure 命令（含一次性 token），在本机执行：

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -sL -o actions-runner-linux-x64.tar.gz <URL-from-GitHub>
tar xzf actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/jefison-x/BeyondQuant \
            --token <TOKEN> \
            --name byq-local-runner \
            --labels byq,linux,x64 \
            --work _work
```

3. 运行 `./run.sh`，确认出现 `Listening for Jobs`。
4. GitHub Runners 页面应显示 `Idle`，然后停止 foreground runner 并安装
   service。

Labels 必须含 `byq`、`linux`、`x64`，因为 workflow 固定
`runs-on: [self-hosted, linux, x64, byq]`；改 label 时同步改 workflow。

## 以 systemd service 运行

```bash
cd ~/actions-runner
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
sudo ./svc.sh check
```

确保 service user 可访问 Docker：

```bash
sudo usermod -aG docker <runner-user>
sudo systemctl restart actions.runner.jefison-x-BeyondQuant.byq-local-runner.service
```

## Workflow 与端到端验证

`.github/workflows/ci-selfhosted.yml` 在 PR 及 push 到 `main` /
`bootstrap/**` 时触发；使用 `fetch-depth: 0` 并 fetch `origin/main`，运行
完整 local CI。每次 Compose 资源唯一，不能与 developer stack 冲突。旧
`ci.yml` 保留供 reference/rollback；runner 稳定后可在 GitHub 禁用或后续 PR
删除，避免调度付费 jobs。

验证：runner 在 GitHub 显示 `Idle`；更新 PR 后出现
`BeyondQuant Self-Hosted CI / local-ci`；可在
`~/actions-runner/_diag` 或 `sudo ./svc.sh check` 查看 logs；预期 core、
mocked UI、isolated Compose 和 real browser 全部 PASS。

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Job 一直 `Queued` | runner offline/wrong label | 检查 online、`byq` label、`svc.sh status` |
| `docker.sock` permission denied | user 无 Docker access | 加入 `docker` group 并 restart service |
| `tsc: not found` | host `node_modules` partial | rebuild current MCP image |
| Backend `no schema has been selected` | stale shared PG volume | 应使用 clean `byq-ci-postgres`，检查 stale container |
| Build OOM | RAM 不足 | serial build，heavy job 时停 local Compose |
| Playwright 无 Chromium | browser cache 缺失 | `cd apps/frontend && npx playwright install chromium` |
| 需要固定 debug ports | CI 动态分配 | 设置 `BYQ_CI_FRONTEND_BIND` / `BYQ_CI_GATEWAY_BIND` |
| CI 改变 local stack | isolation regression | CI resources 必须以 `byq-ci-*` 开头 |

## Security notes

- Self-hosted runner token 对注册 repository 有 write access；只放在 trusted
  machine，并按配置优先运行 contents-read-only `pull_request`。
- 不在 runner 上执行 untrusted third-party workflows；只调度 same-repository
  PRs/trusted pushes。
- Runner 不需要 Tushare/DeepSeek secrets；使用 keyless tests。Real browser
  tier 使用 run-scoped bootstrap account/env vars；真实 secrets 不得进入 runner
  environment。
