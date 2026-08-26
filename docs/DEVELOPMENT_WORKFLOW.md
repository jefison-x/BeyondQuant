# BeyondQuant 开发流程

本流程对后续 Codex Phase 和 Engineering Plane 变更具有强制性。“Continue
development”是指：读取 `docs/roadmap/STATUS.md`，识别其中的 `Next phase`，并执行
`docs/roadmap/IMPLEMENTATION_PLAN.md` 所定义的该 Phase 范围；它不表示可以从仓库
历史中任意选择无关任务。

## 必须遵循的顺序

1. 阅读 `AGENTS.md`、`ARCHITECTURE.md`、`docs/roadmap/STATUS.md`、
   `docs/roadmap/IMPLEMENTATION_PLAN.md`、本流程，以及与该 Phase 有关的全部
   Accepted ADR。
2. 在仓库根目录通过 fast-forward-only 更新将干净的 `main` 与 `origin/main` 同步。
   使用 `git rev-parse origin/main` 动态取得预期基线；`STATUS.md` 不是 Git SHA 的
   事实来源，不得用其中的硬编码 SHA 进行比较。
3. 编辑前检查该 Phase 的范围、依赖、非目标、架构约束、验收标准和停止条件。
4. 在 `/home/jefison/projects/.byq-worktrees/` 下创建隔离 worktree 和 feature branch。
   所有实现修改必须在其中完成。
5. 实现满足当前 Phase 的最小 contract-first 变更。不得修改旧 Community 仓库。
6. 运行 architecture test。
7. 运行 unit test。
8. 运行 contract test。
9. 运行无密钥 smoke/integration test。如果需要真实模型 key，将其记录为 Phase 边界，
   且绝不向测试加入 secret。
10. 运行 `git diff --check`，检查完整 diff，并执行安全和架构自审。
11. 在 feature branch 上有意识地提交，且只 push 该分支。
12. 创建以 `main` 为目标的 Draft PR，说明范围、证据、已知限制和剩余决策。
13. 等待 CI 并记录结果；只在 feature branch 中修复失败。
14. 最终复核文件、测试、依赖 pin 和边界变更。
15. 停在人工合并门禁；Codex 不得 merge，也不得直接 push 到 `main`。

## 单维护者 Human Merge Gate

当仓库只有一名人工维护者，且维护者同时也是 PR 作者时：

- CI 和所有 required status check 必须通过。
- Codex 必须停在 Draft PR，且不得直接 push 到 `main`。
- 人工仓库 owner 必须手动审查 PR，并应留下 GitHub review 或 comment 作为审计记录。
- 若 GitHub 禁止 PR 作者批准自己的 PR，则不要求 GitHub `APPROVED` 状态。
- Codex 不得 merge，也不得将 PR 标记为 ready for review。
- 只有人工维护者可以将 PR 标记为 ready 并 merge。
- 如果仓库规则随后要求独立 approval，则必须满足这些 approval。

预发布例外（ADR-0015）：在 BeyondQuant Next v1.0 正式发布前，Codex 可以创建
非 Draft PR、将其标记为 ready，并在全部 required check 通过后启用 GitHub
auto-merge（squash）。该例外在发布边界失效；届时恢复上述单维护者门禁，并必须
禁用 auto-merge。

## 证据要求

架构变更需要新增 ADR 或更新相关 Accepted ADR。集成边界需要 framework-neutral
Contract 和 translation test。外部依赖必须有准确的 metadata/version 证据。
Runtime 变更需要 lifecycle 和 cleanup 证据。Product/Engineering 能力变更需要
明确的隔离测试。仅有绿色测试不足以作为架构验收证据。

## Phase 9+ Community 迁移纪律

实现 Phase 9 或更晚的领域能力前，Codex 必须：

1. 检查 `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`。
2. 检查对应的 BeyondQuant-Community 实现和测试。
3. 将每个可复用资产分类为 `REUSE_AS_IS`、`PORT_LOGIC`、`PORT_TESTS`、
   `REFACTOR`、`REFERENCE_ONLY`、`REPLACE` 或 `DROP`。
4. 保持现有 BYQ ownership 和 MCP/DSH 架构边界。
5. 仅将有依据的领域语义和 regression test 移植到 BYQ 自有 Contract。
6. 在 inventory 中记录迁移决策及任何未来 Phase candidate。

未检查并分类现有 Community 实现属于 STOP CONDITION。重新引入 BaoStock、AKShare、
VectorBT、PydanticAI、Hermes、旧 Agent runtime coupling、Agent 直接访问数据库，或
frontend 依赖 raw Agent schema，同样属于 STOP CONDITION。不得创建 compatibility
layer 来规避该决策。

## STOP CONDITIONS

发生以下任一情况时，Codex 必须停止，并报告证据、可选方案和建议：

- 架构规则与请求的实现冲突；
- DSH 行为发生 breaking 或尚未文档化的变化；
- 安全边界将发生变化；
- domain invariant 不明确；
- legacy migration classification 不明确；
- 测试需要绕过架构；
- 无法取得准确的依赖基线。

停止意味着不得静默绕过、推测性地创建 compatibility layer、fork、修改协议或
merge。必须由人工选择后续方向，或在恢复实现前编写 ADR。

## 交接格式

每个 Phase 的交接应说明 branch、worktree、base 和 commit SHA、Draft PR、修改文件、
架构决策/状态、测试和 CI、外部依赖版本、已知限制、blocker，以及是否修改了 `main`
或 legacy 仓库。最后一行必须说明是否允许进入下一 Phase，或该 Phase 是否因等待
review 而 blocked。

## Product Completion Phase Gate

对于 Phase 24-30，上述流程增加以下要求：

- 每个隔离 worktree/branch/Draft PR 只处理一个 Phase；
- Draft PR 创建且 CI 通过后停止；
- 不得 merge 或标记为 ready；
- Product UI Phase 必须具备 Chrome MCP browser evidence 和 Community feature
  checklist，才能视为完成；
- PR body 必须包含 Product Evidence：已检查的 Community reference、已测试的 browser
  journey、Chrome MCP review、frontend test、backend/Product API test、已完成的
  screen/surface，以及仍缺失的项目。
