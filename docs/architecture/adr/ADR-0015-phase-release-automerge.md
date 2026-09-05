# ADR-0015：预发布阶段对单维护者门禁的 CI Auto-Merge 例外

- Status: Accepted
- Date: 2026-08-17
- Decision scope: BeyondQuant Next 预发布 Product-depth 工作期间的 Engineering Plane
  pull-request merge gate

## 背景

仓库采用单维护者 Human Merge Gate：Codex 必须停在 Draft PR，不得标记 ready，也不得
merge；CI 通过后由 Human maintainer merge。Product-depth Phase（Backtest、Strategy、
Stock Pool、Paper Trading、Agent、My Space、Operations）各自产生一个 PR，因此在 v1.0
发布前会反复出现手工 merge 步骤。

维护者明确要求在 BeyondQuant Next v1.0 正式发布前放宽该门禁，采用 CI-green
auto-merge，并在发布后提醒关闭 auto-merge。

## 决策

1. 在 BeyondQuant Next v1.0 正式 tag/delivery 前，Codex Engineering Plane MAY 创建
   non-draft PR、将其标记为 ready，并在所有 required CI check 通过后启用 GitHub
   `squash` auto-merge。
2. Auto-merge 只适用于 mergeable 且 required check 全绿的 PR。Codex 仍必须检查并修复
   CI failure，绝不能直接 push 到 `main`，也绝不能 force-push。
3. 该例外在 v1.0 release boundary 自动失效。发布后，无需进一步 code change 即恢复
   `AGENTS.md` 和 `docs/DEVELOPMENT_WORKFLOW.md` 中的单维护者 Human Merge Gate。
4. 维护者必须在发布时禁用 GitHub auto-merge，并向 Codex 确认门禁已关闭。
   `docs/roadmap/STATUS.md` 将该提醒作为 release-blocking checklist item 跟踪。

## 后果

- 预发布期间合并的 PR 仍经过 CI 和相同 diff/architecture review evidence，但移除每个
  PR 的 Human merge click。
- Release boundary 是硬停止点：正式发布后不能继续 auto-merge。
- 直接写 `main`、以 Engineering 开发权限进行 production deployment 和合并 failing-check PR 仍被禁止。
  ADR-0059 澄清：另行明确授权的 Product 外 trusted operator 可执行既有部署 lane；本合并例外本身不授予部署权。

## 2026-09-05 执行澄清（ADR-0059）

本例外不是自动忽略更严格专项验收或平台设置的授权。动作前验证当前任务的合并授权、
GitHub auto-merge 与严格 required checks；设置关闭、API 403、检查跳过或不可验证时停在 Draft。
不得以直接即时 merge/admin bypass 代替不可用的 auto-merge。v1.0 失效边界不变。

## 拒绝的替代方案

- 保留每个 PR 的 Human Merge Gate：会减慢维护者希望加速的 Product-depth sequence。
- 永久 auto-merge：与单维护者 audit model 冲突，明确不在范围内。
