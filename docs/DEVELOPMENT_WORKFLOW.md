# BeyondQuant 开发流程

本流程对后续 Codex Phase 和 Engineering Plane 变更具有强制性。“Continue
development”是指：读取 `docs/roadmap/STATUS.md`，识别其中的 `Next phase`，并执行
`docs/roadmap/IMPLEMENTATION_PLAN.md` 所定义的该 Phase 范围；它不表示可以从仓库
历史中任意选择无关任务。

## 规则归属与任务分流（ADR-0059）

AGENTS 为入口，ARCHITECTURE 定义持久边界，Accepted ADR 定义具名例外；本文件定义执行与
权限门禁，STATUS 定义当前 Product Phase，专项计划定义步骤，ci-policy/受测脚本定义验证。
历史 Phase 叙述不是当前通用流程；只有带精确 scope/supersedes/维护者接受记录的 ADR 可覆盖旧规则。

| 请求 | 执行范围 |
|---|---|
| 继续开发 / Product Phase | 只执行 STATUS 已授权的 Next phase |
| 明确 bugfix / 治理维护 | 独立维护任务，一工作树/分支/PR；不推进 Product Phase |
| DSH / dependency upgrade | 专项资格计划，默认版本不因候选通过自动升级 |
| 调研 / 审查 / 文档 | 调研不授权改实现；文档任务不授权部署 |
| 运维 / 发布 | 单独确认目标、授权与 runbook；不授予 Product 能力 |

授权分为 `develop`、`push/pr`、`merge`、`deploy`，可在一次明确指令中全部授予。记录原始授权
及范围，不重复询问已授权的正常步骤；新增生产服务、数据破坏、release/tag 或架构扩权须另行决策。
当前任务的授权记录放在专项执行表/证据中，不把一次会话授权写成永久通用规则。

## 必须遵循的顺序

1. 阅读 `AGENTS.md`、`ARCHITECTURE.md`、`docs/roadmap/STATUS.md`、
   `docs/roadmap/IMPLEMENTATION_PLAN.md`、本流程，以及与该 Phase 有关的全部
   Accepted ADR。
2. 在仓库根目录通过 fast-forward-only 更新将干净的 `main` 与 `origin/main` 同步。
   使用 `git rev-parse origin/main` 动态取得预期基线；`STATUS.md` 不是 Git SHA 的
   事实来源，不得用其中的硬编码 SHA 进行比较。主工作区有用户修改时不 reset/stash，
   直接以 fetched origin/main 建立隔离 worktree 并记录原因。
3. 编辑前检查该 Phase 的范围、依赖、非目标、架构约束、验收标准和停止条件。
4. 在 `/home/jefison/projects/.byq-worktrees/` 或明确配置的专用 `BYQ_ENGINEERING_WORKTREE_ROOT`
   下创建隔离 worktree 和 feature branch，运行 `python3 scripts/ci/verify-worktree.py <worktree>`。
   所有实现修改必须在其中完成。无权限时申请适当目录权限，不能自行把整个 /tmp 当作根。
5. 实现满足当前 Phase 的最小 contract-first 变更。不得修改旧 Community 仓库。
6. 按 ci-policy 运行所需 architecture test；规范修改必须运行。
7. 运行受影响组件完整 unit test。
8. 运行受影响组件完整 contract test 和 build。
9. integration-risk 才运行无密钥 smoke/integration/browser；专项验收要求更严格时不能降低。
   真实模型评测是独立授权/证据层，不向 required keyless CI 注入真实 secret。
10. 运行 `git diff --check`，检查完整 diff，并执行安全和架构自审。
11. 在 feature branch 上有意识地提交；只有 push/pr 授权覆盖时才 push 该分支。
12. 授权覆盖时创建以 `main` 为目标的 Draft PR，说明范围、证据、已知限制和剩余决策；否则本地交接。
13. 已推送时等待远端 CI 并记录结果；未推送时如实记录本地验证，不能冒充远端 CI。只在 feature branch 中修复失败。
14. 最终复核文件、测试、依赖 pin 和边界变更。
15. 默认停在人工合并门禁；仅本文件明确的预发布例外可进入 auto-merge，绝不直接 push 到 `main`。

CI 必须遵循 `docs/operations/ci-policy.md`：PR 运行 change-impact selective profile，
受影响组件运行完整 suite；Compose/真实浏览器只由 integration-risk 变化触发。任何 CI
创建的容器、网络和卷必须在 success/failure/cancel 后按 run-attempt scope 清理并验证为零。
不得为了浏览器证据默认使用 `--no-cleanup`，也不得让 CI 与正式 `beyondquant` 栈共享资源。

## 单维护者 Human Merge Gate

以下是默认门禁；仅下方具名例外覆盖，不由历史 Phase 的重复措辞额外覆盖：

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

ADR-0059 补充：必须有覆盖本任务的 merge 授权，并在动作前运行只读
`python3 scripts/ci/check-github-gates.py --repo jefison-x/BeyondQuant --pr <number>`。
核对精确 PR head、真实执行的 local-ci/ci-gate、全部 required checks/review、strict/up-to-date
服务器规则和 auto-merge/squash 设置。工具只做保守 preflight，不代替授权或最终平台判定。
API 403、ruleset-only 尚未验证、设置关闭、skipped/neutral、未知/过期检查时停在 Draft；
不得使用 `--admin`、取消必需检查或直接即时 merge 作为 fallback。修复平台配置需维护者另行授权。

生产部署独立于合并。只有获授权的 Product 外 trusted operator 可按 ADR-0040/0059 的
runbook 发布指定已验证制品，记录 backup（必要时）、服务范围、readiness、业务 smoke、rollback。
这不允许 Engineering/Product 自主部署，也不允许自动 destructive migration。

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
merge。暂停仅针对受影响的不安全路径；只读调查、隔离复现、测试和 Proposed ADR 可继续。
恢复越界实现前必须由维护者选择方向并明确接受必要 ADR；仅“编写 ADR”不能代替 Accepted。

## 交接格式

每个 Phase 的交接应说明 branch、worktree、base 和 commit SHA、Draft PR、修改文件、
架构决策/状态、测试和 CI、外部依赖版本、已知限制、blocker，以及是否修改了 `main`
或 legacy 仓库。最后一行必须说明是否允许进入下一 Phase，或该 Phase 是否因等待
review 而 blocked。

## Product Completion Phase Gate

以下保留 Phase 24-30 的历史验收约束；合并动作统一受本文件当前门禁与预发布例外控制：

- 每个隔离 worktree/branch/Draft PR 只处理一个 Phase；
- 默认在 Draft PR 创建且 CI 通过后停止，ready/merge 仅适用当前具名例外；
- Product UI Phase 必须具备 Chrome MCP browser evidence 和 Community feature
  checklist，才能视为完成；
- PR body 必须包含 Product Evidence：已检查的 Community reference、已测试的 browser
  journey、Chrome MCP review、frontend test、backend/Product API test、已完成的
  screen/surface，以及仍缺失的项目。
