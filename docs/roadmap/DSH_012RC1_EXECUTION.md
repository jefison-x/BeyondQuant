# DSH 0.1.2rc1 执行交接与进度

状态：**U0 MERGED，ADR-0058 Accepted；U1 VERIFIED，等待 push/Draft PR 授权**。2026-09-06。

## 1. 下一模型第一步

先读[主方案](DSH_012RC1_UPGRADE_PLAN.md)、[测试矩阵](DSH_012RC1_TEST_MATRIX.md)、
[发布方案](../operations/DSH_012RC1_ROLLOUT.md)和[ADR-0058](../architecture/adr/ADR-0058-dsh-release-bundles-and-compatibility.md)。
然后检查 `STATUS.md`、Git/worktree 和用户最新授权。不要凭之前聊天摘要直接替换 DSH 版本。

当前修正版由源码发布准备任务承接治理与规划提交；合并后以最新 main 中本文件为唯一入口。
原治理工作树为 `/home/jefison/projects/.byq-worktrees/governance-ci-hardening`，仅用于历史核对。
原 `docs/dsh-012rc1-upgrade-plan` / `/tmp/byq-dsh-012rc1-upgrade-plan` 只保留历史，不再是修正版入口。
历史分支不意味着已推送或已合并；以 GitHub 和最新 main 核实，不依赖工作树仍然存在。

用户后续明确要求实施时，先完成治理整改/修正版方案的审查合并；
不要从尚未合并的规划分支直接叠加 U1–U8。文档-only 提交可在新隔离分支 cherry-pick，
但先核查差异/主分支新增 ADR 编号；有冲突先读最新内容，保留用户改动。

## 2. 授权与状态事实

- 当前用户授权：维护者于 2026-09-06 授权并完成 U0 开发、push、Draft PR、ADR 接受和 U0 验证，
  随后按 ADR-0015 明确授权 PR #250 squash auto-merge；该 PR 已合并。维护者继而授权开始并继续 U1
  开发。U1 的 push/Draft PR、merge，以及 U2–U8、生产部署、正式版本切换和付费模型测试未授权。
- 当前 Product completed phase：97；新 Product phase 未由本方案授权。
- 当前运行基线：Python `0.1.1rc1` / npm `0.1.1-rc.1`（实施前再次核实）。
- 目标：Python `0.1.2rc1` / npm `0.1.2-rc.1`，不可擅自追新版本。
- ADR-0058：Accepted；接受范围是 U0 记录的精确载体与边界，不是候选资格或后续阶段授权。
- 当前升级阶段：U0 `MERGED`；U1 `VERIFIED`，等待 push/Draft PR 授权。
- 当前方案只宣称 U1 候选物料/identity/隔离准备通过；不宣称新版 Runtime 已适配、QUALIFIED、
  正式部署或生产观察已完成。

后续实施时在本节记录授权是单阶段还是 U0–U8、是否覆盖 push/PR/merge/deploy/真实付费模型评测/监控。
依据会话已有授权继续，无须对已授权动作逐个重复确认。授权不足只阻止依赖它的步骤，继续可独立完成的工作。
所有 PR 都要 required CI；预 v1.0 依 ADR-0015/0059 允许 CI-green auto-merge 时仍不能绕过失败检查或 push main。
U0 前核对 `check-github-gates.py`：auto-merge 关闭/服务器门禁不可验证是合并阻碍，不是 DSH 不兼容。
ADR-0060 的一次性私有仓库发布过渡例外仅属于源码发布准备，不适用于任何 U0–U8 PR。
公开后使用标准 GitHub-hosted CI，不重新注册正式机 runner；候选测试依旧是独立资源，
完整回归/工具能力边界不能因 hosted 容量调整而省略。
ADR-0058 的接受、生产 operator 部署和付费模型评测分别记录精确授权；不伪造后续完成。

## 3. 阶段进度表

状态：PLANNED / IN_PROGRESS / VERIFIED / MERGED / DEPLOYED_OBSERVING / COMPLETE / BLOCKED / ROLLED_BACK。
实现阶段在自己的 PR 更新已验证结果，merge 后从 GitHub 实况确认；不要预填未来完成状态。

| 阶段 | 状态 | 工作树/分支 | 验证证据 | 阻碍/下一动作 |
|---|---|---|---|---|
| U0 载体决策 | MERGED | `.byq-worktrees/dsh-u0-compatibility-decision` / `docs/dsh-u0-compatibility-decision` | `docs/evidence/dsh-012rc1/u0/`；Option A bundled executable 已接受；keyless spike、旧版回归和 required CI 通过 | PR #250 已按 ADR-0015 squash auto-merge |
| U1 版本集中/隔离 | VERIFIED | `.byq-worktrees/dsh-u1-release-manifest` / `refactor/dsh-u1-release-manifest` | `docs/evidence/dsh-012rc1/u1/VALIDATION.md`；T01–T07、旧版回归、Integration/浏览器 smoke 通过 | 等待 push/Draft PR 授权；不启动 U2 |
| U2 provenance 解耦 | PLANNED | 未创建 | 未运行 | U1 合并后 |
| U3 旧版适配模块 | PLANNED | 未创建 | 未运行 | U2 合并后 |
| U4 新版候选适配 | PLANNED | 未创建 | 未运行 | U3 合并后 |
| U5 完整认证 | PLANNED | 未创建 | 未运行 | U4 合并后 |
| U6 发布/回滚演练 | PLANNED | 未创建 | 未运行 | U5 合并后 |
| U7 生产晋升 | PLANNED | 未创建 | 未运行 | U6 合并、发布授权/所有门禁满足后 |
| U8 观察/流程复用 | PLANNED | 未创建 | 未运行 | 实际切换后 |

`STATUS.md` 只记录当前维护阶段、资格/部署结果和 Next，不存固定 main SHA 或 transient PR 状态。
Git SHA、PR 链接、测试运行身份记录在本执行表/分阶段 evidence，不能替代实时 GitHub 检查。

## 4. 每阶段执行清单

1. **定位**：确认自己在目标 isolated worktree；读主方案该阶段、输入/输出/停止条件和此前 evidence。
2. **检查**：只读查看现有实现和依赖；差异超出计划时先记录证据，不能无声扩大范围。
3. **契约**：针对真正风险先写失败测试；不能先删旧测试再为新实现写自证断言。
4. **实现**：按阶段步骤小批修改；生成物用生成器；不用全仓版本替换或同时做多个阶段。
5. **验证**：先针对性测试，再运行受影响组件完整 suite 与所需 Integration/真实模型 gate。
6. **复核**：确认 release/image/SDK 实际身份，检查 diff、边界、依赖、所有测试层次及资源清理。
7. **交接**：阶段报告记录完成/未运行/阻碍和下一步；提交当前分支，按已有授权推送 Draft PR。
8. **合并**：查询真实 required check 和 review；使用既有预发布例外时仍等待 CI 全绿；禁止直接 push main。
9. **推进**：只在前阶段实际 merged 后同步干净 main，创建下一独立工作树，不在旧分支继续堆代码。

创建后续分支的命令模式（U1 示例；只在 U0 已合并后使用）：

```bash
git fetch origin
git status --short
git rev-parse origin/main
git worktree add --no-track -b refactor/dsh-u1-release-manifest /home/jefison/projects/.byq-worktrees/dsh-u1-release-manifest origin/main
python3 scripts/ci/verify-worktree.py /home/jefison/projects/.byq-worktrees/dsh-u1-release-manifest
```

若 root main 干净，依仓库流程执行 fast-forward-only 同步；若它有用户修改，不 reset/stash 覆盖，
直接从已同步 origin/main 创建独立工作树并记录原因。已有同名工作树先检查是否本阶段未完成，不能覆盖。
默认使用标准 `.byq-worktrees`；确需替换时明确配置专用 `BYQ_ENGINEERING_WORKTREE_ROOT`，
同步宿主与 EngineeringTask 路径合同。无权限先申请，不能自行把整个 `/tmp` 设为根。

## 5. 每阶段交接模板

```text
Stage:
Authorization scope:
Worktree / branch / observed base / current commit:
Default release / candidate release:
Architecture decision status:
Changed files and why:
Tests: T IDs + actual test names + layer + result:
Installed SDK / carrier / image / profile identity:
Not run / blocked / known limitation:
CI and PR evidence (if authorized):
Production changes: none / exact services and result:
Resource cleanup and retained evidence:
Rollback status:
Next stage or blocking decision:
```

压缩上下文/换模型前更新本表和报告；不要把仅存在于聊天的决定留给下一模型猜。
工具失败需记录是网络/权限/依赖/测试断言/上游变化，不能都算“DSH 不兼容”。
没有必要重复跑已经通过且没有失效的昂贵测试；反之，错误镜像下的通过结果不能复用。

## 6. 给 GPT-5.6 中等模型的启动提示词

以下提示词由维护者在准备开始时发送；括号内授权范围由维护者选择填写，不自动视为已经授权。

```text
按照仓库 docs/roadmap/DSH_012RC1_UPGRADE_PLAN.md 及其测试矩阵、发布方案和执行交接文档，
开始 BYQ DSH 0.1.2rc1 升级维护。先读取实际文件和当前状态，再从第一个未完成且已授权的阶段继续。
从最新 main 阅读归档的治理与规划；若文档尚未合并，先核实源码发布准备 PR 的状态，不能
从旧本地规划分支直接开始升级。原 docs/dsh-012rc1-upgrade-plan 只作历史。不得从聊天摘要猜方案。

本次实施授权范围：[填写单阶段或 U0–U8，以及推送/PR/合并/部署、真实模型评测和监控范围]。
已经授权的动作不重复询问；遇到改变权限/业务语义/目标版本或无法满足硬门禁时说明具体证据。

每阶段一个隔离 worktree、分支和 PR，前阶段验证合并后才开始下一阶段。
U1–U3 保持旧 DSH 行为；U4–U6 只认证候选；U7 才可晋升生产。
先确认 U0 载体方案；不能直接采用 sdk-minimal 或旧 demo 路径，不能用私有参数绕过 SDK 变化。
严格保留 MCP、WorkflowTrace、审批、fresh-generation、900/180/120 和分页正常结束语义。
按 T01–T40 记录证据，区分 mock、真实 DSH、真实 Product API、真实模型和生产观察。
不要重建 Agent harness、fork DSH、删除失败测试、放宽权限或凭 healthz 宣称升级完成。
每个阶段结束和上下文压缩前更新执行表，所有报告必须标明未运行项和实际部署状态。
```

## 7. 本次规划交付检查

- [x] 只在隔离文档工作树新增方案，无业务实现和运行版本变更。
- [x] 明确 SDK 字段移除、两个旧包缺少新版、默认 coding profile 风险与 provenance 硬编码。
- [x] 分为 U0–U8，包含每阶段范围、顺序、验证、退出/停止及回滚。
- [x] 明确拟新增路径/命令尚未实现，不能当现有工具运行。
- [x] 测试矩阵、真实模型场景、候选隔离和生产回滚文档已编写。
- [x] 文档链接/diff/架构检查已通过，见[规划验证记录](../evidence/dsh-012rc1/planning/README.md)。

规划分支提交状态用 `git status`/`git log` 核实；不在本文件预写提交 hash 或声称已推送。

以上勾选只表示规划材料交付，不表示相应升级工作已经开发或测试。
