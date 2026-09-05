# Self-Hosted CI（本地 GitHub Actions Runner）

Status: **Active** — `scripts/ci/local-ci.sh` 和
`.github/workflows/ci-selfhosted.yml` 的 companion。

2026-09-05 治理修订（ADR-0059）：same-repository PR/nightly/manual 保留 self-hosted；fork PR
改用无生产权限的 GitHub-hosted 临时 runner，`ci-gate` 汇总真实执行与清理结果。下述历史免费运行
动机不代表 hosted 永远可用；billing/approval/runner 阻碍必须如实 NOT_RUN，不能转发 fork 到本机。
配置与验证以 `ci-policy.md` 为准。所有组件镜像先按当前 checkout 构建并使用 run-scoped tag。

## 原因

该账户的 GitHub-hosted Actions runners 需要付费，因此 `ci.yml` 可能因
payments/spending limit 失败。Self-hosted runner 让 GitHub 继续 orchestration
并在 PR 显示 status，但 checks 在本地机器免费执行。

Pull request workflow 运行项目自身的 selective profile：先通过
`scripts/ci/classify-changes.sh` 生成影响计划，再执行受影响组件的完整测试；只有
integration-risk 变化才启动 Compose。Nightly 和人工 Full 仍运行
`--all --with-e2e --with-smoke`。规范见 `docs/operations/ci-policy.md`。

## Architecture

```text
GitHub（仅 orchestration）
  └─ PR / push ─► .github/workflows/ci-selfhosted.yml
                     └─ local-ci on [self-hosted, linux, x64, byq]
                          └─ local actions-runner systemd service
                               ├─ docker（clean CI PostgreSQL）
                               ├─ python3（architecture tests）
                               ├─ node 24（frontend/Cloudflare build + tests）
                               ├─ PR: local-ci.sh --with-e2e --auto-smoke
                               └─ Nightly/manual: --all --with-e2e --with-smoke
```

需要数据库的 component checks 使用 clean CI-only PostgreSQL。Smoke tier 启动 Compose，
但每个 run attempt 都分配 unique project name、network、volumes、Docker loopback
ports、bootstrap identity 和 Product API URL。Shell signal trap 与 workflow
`if: always()` cleanup 双重删除并验证 run-scoped resources，不碰 developer
`beyondquant` stack。

## Runner machine prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| OS | Linux x64 | macOS/Windows 要使用 matching runner package |
| Docker Engine + Compose v2 | recent | runner user 需有 Docker socket access |
| Python 3 | 3.10+ | architecture tests；services 已 containerized |
| Node.js | 22.12+ 或 24 | host 锁文件工具链；fork CI 使用 24，镜像按各自 Dockerfile |
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

`.github/workflows/ci-selfhosted.yml` 在 PR、Nightly schedule 和人工 dispatch 时触发；
PR 执行 selective profile，Nightly/人工 Full 执行完整回归。合并到 `main` 不再重复
同一套 PR 检查。每次 Compose 资源以 run ID + run attempt 唯一，不能与 developer
stack 冲突。

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
| Build OOM | RAM 不足 | 限制构建并发/排队重试，不能为 CI 停止生产栈 |
| Cancel 后遗留资源 | signal/post cleanup regression | 使用 exact run-attempt scope 执行 `scripts/ci/cleanup-resources.sh`，不得 broad prune |
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

工作流 YAML 不是抵御恶意 PR 修改 runner 选择的安全边界。开源前维护者必须核对 runner group/
可信工作流访问限制；不能提供有效限制时禁用生产邻接 self-hosted PR 执行，改用独立临时机器。
不要把匿名贡献者代码搬到同仓分支以规避 fork 隔离。

平台配置（本次代码不自动修改）：启用 strict/up-to-date 的 `local-ci` 与 `ci-gate` required checks；
仅在预 v1.0 和明确授权时启用 squash auto-merge。用
`python3 scripts/ci/check-github-gates.py --repo jefison-x/BeyondQuant --pr <number>` 只读核验。
API 403/ruleset-only 无法验证时由维护者核查实际规则；不得把本地 PASS 当作服务器门禁。
