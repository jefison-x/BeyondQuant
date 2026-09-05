# Governance / CI hardening 验收记录

日期：2026-09-05。独立维护，不推进 Product Phase 97。依据 ADR-0059。
维护者授权：治理与 CI 整改、修正已有 DSH 升级方案；未授权本次 push/PR/merge/deploy 或 DSH U0。
工作树：`/home/jefison/projects/.byq-worktrees/governance-ci-hardening`。
分支：`chore/governance-ci-hardening`。干净 main/origin 基线在本次核验时为 `610f1d6`。
原规划文档提交已整合；原文档分支/工作树保持，不覆盖用户历史。

## 已实现

- AGENTS/架构/流程/ADR/STATUS 明确规则职责、具名例外、阶段与维护分流，以及四项授权。
- 修正 WorkflowTrace 图；EngineeringTask completed 保持 tested Draft PR 语义，不伪报部署。
- 配置化专用 worktree 根，Backend 只验证路径合同，宿主独立验证真实路径/Git 登记。
- 风险分类优先处理机器契约、所有 real-browser specs、依赖/运行时组合及内嵌 DDL（含旧树删除）。
- 本次树构建 run-scoped image；组件与 Compose 同名同制品，构建失败不继续，禁止旧镜像 fallback。
- 不读取生产 .env/Compose override；Product CI 与 Cloudflare fixture environment 隔离。
- fork 使用临时 hosted lane；真实执行汇总 gate；日志脱敏保留；失败/取消/最终清理验证。
- GitHub preflight 只读、超时/403/关闭/缺失/跳过/审批不足均 fail closed，不执行 merge 或设置写入。
- DSH 主方案、执行表、测试矩阵、发布方案和 Proposed ADR-0058 同步修正；U0–U8 均未开始。

## 验证

完整命令（pipeline 启用 `set -o pipefail`，日志先脱敏再落盘）：

```bash
BYQ_CI_SCOPE=governance-20260905-v2 scripts/ci/local-ci.sh --base=origin/main --all --with-e2e --with-smoke
```

结果：退出 0，`Local CI: all 25 checks passed`。

| 验证层 | 实际结果 |
|---|---|
| 最终仓库 tests 根目录 unittest | 108 通过；完整 CI 当时为 106，后补两个故障负例并重新运行完整根目录 suite |
| Backend 完整 suite | 327 通过；1 项明确 opt-in 的真实 Tushare 测试跳过 |
| Publisher / Hub relay | 6 / 2 通过，fake GitHub，无外部 Issue 写入 |
| Cloudflare Hub | typecheck、15 项 workerd 测试、4 项部署脚本测试、Git deployment contract、两个 Worker dry-run 通过 |
| Gateway | 86 通过 |
| Runtime Adapter | 66 Python + 3 Node 测试通过；DSH pin 未改变 |
| MCP | build、live test-only Backend 与全部 MCP contract 检查通过 |
| Frontend | build、148 unit、dependency audit、20 mocked Playwright 通过 |
| 隔离 Product 栈 | 9 条真实 Product API Playwright，ML/反馈重启恢复、双用户隔离与完整 golden flow 通过 |
| 语法与文档 | bash -n、actionlint 1.7.12（官方 checksum 已验证）、文档链接、git diff --check 通过 |
| 取消演练 | 专用无网络/无卷 sleep 容器，向自行启动的 CI shell 发 TERM，退出 143，验证无剩余本次资源 |
| 最终清理 | v1、v2、cancel-check 的容器/网络/卷/镜像 tag 均通过 verify-only；未操作 production 资源 |

本地脱敏完整日志：`.ci-artifacts/governance-v2.log`（gitignored，不上传原始生产日志）。
SHA-256：`acb6ddf9b38bcaabb6ca5412c6773fd80e2cbe0ecb0572a0c81f59245b0568f5`。
本地工作树测试不冒充远端 PR CI；推送后必须由 GitHub 对精确 PR revision 重跑。
最终只删除分类器中已被优先分支覆盖的重复匹配，并重新运行全部 108 项根目录测试；不改变选测结果。

首轮 v1 不作为完整验收：Backend 310 通过，但 Product 的空 repository 环境变量污染 Cloudflare
fixture；开发期间改写仍运行的 shell 也使该次后续结果无效。隔离环境修正并冻结 runner 后执行 v2。
遗留 warning：依赖 deprecation、mocked browser ResizeObserver warning；未借本任务修改 Product UI。

## 平台门禁与未执行项

只读 preflight 真实结果：auto-merge disabled；branch protection API 不可验证（套餐限制 403）。
因此不能证明 strict server-required `local-ci` / `ci-gate` 已生效。代码提供保守 gate，而非伪造平台保护。
ruleset-only 自动识别不在当前 preflight 实现中；出现该配置必须由维护者核验，不自动放行。

维护者后续需决定 GitHub 平台配置/可用性，并核验 self-hosted runner 的可信工作流访问限制；
YAML 条件本身不能防止恶意 PR 改写 runner。fork hosted lane 和 artifact upload 尚未在真实远端 PR 执行，
仅完成结构/契约/actionlint 校验；billing/approval 阻碍不得转交到生产邻接 runner。

本次未推送、未创建 PR、未合并、未部署、未更改 GitHub 设置，未运行真实模型付费认证或升级 DSH。
下一安全步骤：审查并授权推送 Draft PR；平台门禁未解决前不得进入自动合并。DSH 必须在治理合并后另行授权 U0。
