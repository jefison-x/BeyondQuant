# 项目历史工作收尾登记 — 2026-11-02

状态：**已按维护者后续授权完成历史 PR/分支关闭与闲置工作树清理；保护目录保留。**
当前 Clean Break Phase 17 按接受范围 PASS；关闭旧候选不等于其功能已交付，也不
表示 v1.0 长期目标全部完成。

## 当前清理结果 — 2026-11-02

在下文分类整理之后，维护者明确要求：“以上列出来的，全部关闭或删除吧。”
本次按该授权关闭候选、移除历史分支及无环境引用的工作树，不推送新文档 PR，
不合并代码、不发布/部署、不推进 Phase 18，不删除任何容器、卷或镜像。

| 项目 | 已复核结果 |
| --- | --- |
| 历史 PR | #338 及 16 个依赖 PR 全部 CLOSED；全仓 OPEN PR 为 0，无功能合并或依赖升级 |
| 本地历史分支 | 删除 407 个；只保留 main 与当前 `codex/phase17-doc-history-closure-20261102` |
| 远程历史分支 | 245 个均已不存在；231 个使用逐头 lease 的 atomic push 删除，14 个在关闭 PR 后已自动消失 |
| 远程现存分支 | 仅 main，源码仍为 `82e1551e5af5de76a5688e8868d08767306985e7` |
| 工作树目录 | 删除 47 个；清除精确预览确认的 4 个缺失登记；保留 10 个受保护目录 |
| 受保护历史分支 | 8 个旧工作树在原 HEAD 上无 force 脱离分支，文件状态/哈希不变；旧分支引用也已删除 |
| 远程跟踪残留 | 按旧值逐项删除 17 个失效 tracking refs，保留有效 main 及符号引用 |
| 原 10 个脏工作树 | 6 个已加密归档后删除；其余 4 个原地保留，状态、diff 和未跟踪普通文件哈希不变 |
| 环境保留 | 96 个原容器的 ID、镜像、状态和规范化 mount 集合一致；卷及网络清单一致 |
| 回滚材料 | 6 份原路径 retained-u7 镜像归档保留，文件存在且大小不变；既有外部发布/备份目录未清理 |
| 浏览器 | 无导航、刷新或关闭操作；当前 CUA 会话不暴露原三个标签，未将其冒称为新 UI 留存验收 |

受保护目录包括主仓库、当前测试挂载源码/资产工作树、容器引用的
`dsh-acp-maintenance-candidate` 和 `dsh-acp-session-stop-audit`，以及存有原回滚归档的
`dsh-011-residuals`、`post-u8-f2-research-watch`、`post-u8-f7-deploy`、
`post-u8-interface-audit`、`reboot-readiness`、`retire-dsh-011`。
除 main 和当前文档分支外，这些保留目录是原提交快照，不再作为旧分支开发待办。

### 归档、执行边界和复核

加密归档及逐项操作回执位于受保护的非仓库目录
`/home/jefison/.local/state/byq-maintenance/history-closeout-20261102/`：

- `all-refs.bundle.gpg`：967 个引用的完整 Git 历史，所有拟删分支与关闭 PR 的头均覆盖；
  bundle 完整性与加密往返 SHA-256 匹配通过。
- `retired-worktrees.tar.zst.gpg`：原 53 个候选工作树的文件内容，包括后来豁免的 6 个
  回滚工作树。只排除可重建的 .git 元数据、node_modules、.venv 和 Python/工具缓存。
  旧 Git 历史另在 bundle 保存，忽略的独有证据仍在此归档。
- `worktree-patches.tar.zst.gpg`：53 个候选的 staged/unstaged binary patches、状态及
  未跟踪文件清单，保留暂存区与工作区的区分。
- 两个 tar 归档都完成全量解密、解压及对原文件的 compare，gpg/zstd/tar 三项退出码
  分别为 0。密文 SHA-256、受保护解密来源和结果单独保留；真实恢复执行 NOT_RUN。
- 独立 Sol Reviewer 对删除计划及八个保护工作树的同头 detach 增量给出只读预检 PASS；
  Root 在归档完成、头/变更/挂载/进程引用复核通过后执行，不以预检替代归档门槛。

首轮远程预检遇到 14 个已自动消失的 Dependabot 分支即停止，未发删除 push；确认
ALREADY_ABSENT 后才处理其余精确头。一个旧工作树因 root 所有目录删除失败，批次
停止后仅修复待删目录的所有权，完成残留清理；原失败和修复记录均保留。原始 mount
数组的次序差异曾使直接比较失败，按 mount 集合规范化后确认没有容器配置变化。
未新增工具程序、模型调用或业务 Job；临时明文 bundle/补丁副本在密文核验后移除。

`RESULT.json`、`plan-final.json`、`archive-verification.json`、`SHA256SUMS` 及各操作
日志为实际结果来源。下文保留清理授权前的分类、建议及验证记录；其 OPEN、保留旧
分支及待决策措辞均为历史检查点，不再要求续做已关闭候选。

## 清理授权前的文档同步检查点（历史）

## 本次授权与保护范围

维护者要求：“先同步文档，整理历史 Draft、分支和工作树，需要我决定的事项集中列出。
保留未提交改动、测试环境和当前页面，不推进 Phase 18。”

本次只修改文档，在已有隔离工作树使用
`codex/phase17-doc-history-closure-20261102`，从 fetched `origin/main` 建立，
基线为 `82e1551e5af5de76a5688e8868d08767306985e7`。原工作分支
`codex/feedback-status-runner-tests-20261102` 的 `b298e859` 与该基线代码树相同；
通过 #421 squash 交付，不是待合并功能。本次没有 reset/stash、删除或搬移旧改动，
也不关闭 PR、不删分支、不 prune 工作树，不重建服务或导航当前页面。
本次不继承 #421 的一次性合并及发布部署授权；新文档提交默认本地交接。

## 当前结论及历史路线

| 范围 | 当前结论 |
| --- | --- |
| Clean Break Phase 0–17 | [Phase 17 最终限定验收 PASS](../clean-break/phase17-final-acceptance-20261102.md)；已有 A–F 证据按各自边界复用 |
| 用户级运行参数、官方真实 F6 | 已合并验收；测试环境真实 F6 与运行环境启用分开记录 |
| 反馈回传、Runner、最小用量 | 已完成约定维护；Hub 按维护者确认，统计仅 partial |
| #421 镜像及六服务部署 | [可信发布、运行验收及保留检查 PASS](maintenance-release-20261102.md) |
| Phase 18 | 未定义、未授权、NOT_STARTED |
| 旧 Phase 1–100、0.9/P4、早期 0.10 数据路线 | 历史资料，不自动恢复旧 Next phase；按 ADR-0088 判断当前适用性 |
| v1.0 完整产品/ML 支持矩阵 | 长期目标，未整体验收；不能由 Phase 17 或页面存在推定完成 |

原来记录的恢复、历史会话和统计覆盖限制仍保留，不因本次整理变成新一轮必跑验收。
前端分页、中文名称和加载专项已由 #207 交付；H4/H5 等汇总分支已追到合并记录。

## 分支及工作树分类快照

本次审计起点有 **408 本地分支、246 个服务器远程分支、61 个工作树登记**。
本次新增一个文档分支后本地为 409；未新增远程分支或工作树。
更正：先前的 409/410 将远程符号别名 origin 误算为一个本地分支。下表及集成数量
已扣除该别名，原始审计文件保留，不表示有真实本地分支或改动丢失。
本地 origin 跟踪引用有 249 个，其中 3 个对应服务器已不存在的分支，仍保留。
本地 main 落后 origin/main 三次合并，仅登记，不在本次变更中切换/更新主工作区。

| 原 408 个本地分支的证据分类 | 数量 | 当时处理 |
| --- | ---: | --- |
| 原头匹配已合并 PR | 337 | 已有交付记录，保留分支；不据此判定可删除 |
| 原头位于其他已合并 PR 的提交历史 | 43 | 汇总交付已对账，包含 H4/H5/研究交接；不重复开发 |
| 已位于 main 历史 | 8 | 有集成记录，保留 |
| 无匹配 PR/集成历史 | 10 | 下表分类；不是已证实的 10 个产品缺陷 |
| PR 已合并但本地多出提交 | 2 | 保留额外提交，分别登记 |
| PR 关闭未合并 | 6 | 保留为已关闭候选；不自动重开或宣称已交付 |
| 仍开放的人工功能 Draft | 1 | #338，等待维护者决定 |
| 本地 main 指针落后 | 1 | 不是部署失败 |

Git 分支名中的斜杠只表示命名分组。squash 合并不能只用 `branch --merged`
判断；已对账 388 个真实本地分支的集成记录，但不证明其全部测试范围或删除安全性。

### 尚未匹配集成证据的 10 个分支

| 分支（均原地保留） | 观察到的内容及处置建议 |
| --- | --- |
| `codex/acp-artifact-summary-read` | MCP Artifact 读取源码/测试及未提交证据；后续只对账有效差异，不整支合并 |
| `codex/acp-development-retrospective` | ACP 开发复盘文档；作为历史候选登记，不影响产品验收 |
| `codex/acp-real-f6-20261101` | ADR-0116 早期提案；其功能方向后来已由 #419 验收，不算再次缺失 F6 |
| `codex/adr0086-accepted-budget` | 旧 ADR/路线及测试候选；当前架构下仅作历史记录 |
| `codex/adr0086-request-scoped-budget` | 旧请求预算 ADR 候选；不恢复旧运行时 |
| `codex/dsh-acp-session-stop-audit` | 历史取消/会话故障证据和未提交 MCP 源码；保留失败，单独对账源码必要性 |
| `codex/runtime-stop-issue-record` | 原会话缺陷记录；当前主线已有具名问题文档，不据此重新打开验收 |
| `codex/v091-continuation-p4c2` | 旧 0.9 接续 ledger/测试候选；ADR-0088 后不直接回迁 |
| `docs/version-roadmap` | 长期路线图/ML 门禁文档候选；不当作当前 Next phase |
| `ops/backup-retention-20260925` | 旧备份清理回执；只归档其事实，不重新执行清理 |

另外两支的 PR 后增量已核对：`codex/phase-42-conversation-shell` 相比已合并 #106
多一个前端测试路由提交 `0f8fb5c1`；`phase-79-ml-prediction-backtest-closure` 相比
已合并 #187 多一个 Lighthouse 证据规范化提交 `ecb738ff`。它们不等于两个阶段未交付，
仍需保留额外提交；本次不 cherry-pick。

已关闭但未合并候选：`codex/phase-20d-wrapup` #307、`codex/phase-d15-0-1` #318、
`codex/phase-d15-1-rc1` #320、`codex/phase-d15-1-rc1-clean` #321、
`codex/phase-sec-release-secrets` #313、`perf/research-workspaces` #209。
关闭状态不证明其代码已交付，也不自动构成当前阶段阻塞。

### 10 个有未提交内容的工作树

以下名称对应的真实路径、逐文件状态及分支头保存在完整清单中。原地保留所有内容，
不把未跟踪文件视为垃圾。数量按 Git 状态条目计，目录条目可包含多个文件。

| 工作树分支 | 已跟踪改动 / 未跟踪条目 | 分类 |
| --- | ---: | --- |
| `codex/inherit-user-model-defaults` | 3 / 0 | 用户模型/Agent 配置和规则 |
| `codex/acp-artifact-summary-read` | 0 / 13 | 未提交证据 |
| `codex/dsh-acp-maintenance-candidate` | 0 / 3 | 隔离候选及测试材料 |
| `codex/ci-schema-reset-fastpath` | 2 / 0 | CI schema 测试代码 |
| `codex/dsh-acp-session-stop-audit` | 6 / 124 | MCP 源码与历史证据混合 |
| `codex/dsh-acp-single-version` | 1 / 226 | 回归脚本、候选材料及大量证据；保留环境相关内容 |
| `codex/personal-workspace-menu-name` | 1 / 1 | 历史问题文档 |
| `codex/phase-r3-supervisor` | 14 / 6 | 旧运行时/supervisor 候选；不得恢复旧架构 |
| `ops/post-u8-f7-deploy` | 0 / 8 | 运维证据及命令材料 |
| `fix/production-reboot-readiness` | 0 / 3 | 运维证据及命令材料 |

61 个登记中有 47 个干净且存在、10 个有改动、4 个路径已不存在。
缺失登记为 `/tmp/byq-agent-analysis-runtime`、`/tmp/byq-release-ci-once`、
`/tmp/byq-runtime-stop-issue-record-20261003`、`/tmp/opencode/clean-base`。
缺失路径不证明可安全丢弃登记；本次不执行 prune。

当前测试仍依赖本隔离工作树的源码/已构建资产只读挂载，故即使旧工作分支已合并，
也不得以“分支已交付”为由删除本工作树或清理 dist。

## 历史 Draft 和依赖 PR

- [#338](https://github.com/jefison-x/BeyondQuant/pull/338)，
  `codex/phase-100c`，头 `8139e5c019261895d70b7c014ee6cec2516f95ec`：
  OPEN/Draft，原说明明确 “Draft — do not merge”。早期 0.10 数据路线的 Tushare
  申万行业分类、历史成员区间与 readiness 候选；未进入当前主线。原隔离证据仍有效于
  原范围，不等于当前版本资格。本次未新增 Tushare/模型调用或直接迁移旧代码。
- 当前服务依赖 PR：#397、#398、#400、#406、#407、#409、#411、#412、#414，
  共 9 个，涉及 MCP 及 Python 构建依赖。
- `scripts/d15` 历史工具依赖 PR：#401、#402、#403、#408、#410、#415、#416，
  共 7 个。路径属于历史工具不等于已确认可删除；先确认是否仍维护再做版本资格。
- 16 个依赖 PR 均维持 OPEN，不自动合并、关闭或调整 Dependabot 配置。

## 集中待维护者决定

| 编号 | 需要决定的事项 | 建议 | 决定前状态 |
| --- | --- | --- | --- |
| D1 | #338 申万行业功能继续、暂存还是关闭归档？ | 暂存 Draft；如仍需要功能，再以当前架构单独维护切片重评，避免整支合并 | 原 Draft 保留，不自动实现 |
| D2 | 依赖升级的维护范围是否包括历史 `scripts/d15` 工具？ | 优先当前 9 个服务 PR；7 个历史工具 PR 先确定用途，再决定升级或停止维护 | 16 个 PR 全部保留；尚未授权升级切片 |
| D3 | 是否结束旧 0.9/P4、DSH/supervisor 等候选的开发路由，仅保留历史，并对 MCP/CI 未提交源码单独对账？ | 是；不搬移或删除改动，不把旧候选整支合并 | 只分类登记；无删除授权 |
| D4 | 是否推送本次文档分支，创建 Draft PR 并运行对应 CI？ | 本地验收通过后推送 Draft；保留人工合并门禁 | 本地提交；新 PR/合并/发布/部署未授权 |

分支/工作树的实际删除不是上述默认处理的一部分。若将来需要物理清理，必须先给出
精确对象清单、改动/证据保留位置及测试挂载排除结果，再单独决定；本次不要求先清理
才能保持 Phase 17 的已接受结论。运行环境启用 F6、全量统计、恢复演练和 v1.0 长期
目标不属于本次收尾的隐含任务。

## 验证和可追溯证据

复用 `.ci-artifacts/project-closure-audit-20261102/` 的全量 Git/PR 审计；
`branch-worktree-inventory.txt` 是原分支、246 个远程分支及 61 个登记的逐项清单；其
409 行本地分类含上述 origin 别名。`branch-closure.json` / `closure-summary.json`
保留原分类，本页更正与实际清理 RESULT 是此次关闭结果的来源。
本次刷新了 origin/main 和开放 PR 元数据；未重新运行已有业务验收。
`preservation-before-docs.json` 记录 10 个脏工作树的 Git 状态、tracked diff 和未跟踪
文件内容哈希，供本次结束时只读对比；内容和凭据不复制进 Git。

本次本地验证：`make dev-check`、`git diff --check` PASS；现有
`python3 -m unittest tests.architecture.test_architecture -q` **73 PASS**；
六个文档的 **137 个本地文件引用**有效。上述 10 个脏工作树的状态、tracked diff
及未跟踪普通文件内容哈希在结束对比中保持相同。独立 Sol Reviewer 对六文件与
原始回执只读审查后给出 Functional/证据一致性、Tests、Architecture/权限 PASS；
Reviewer 复用 Root 的测试结果，只独立运行 diff 检查，未重复业务测试。

新 PR CI、模型、业务 Job、浏览器测试及部署均 **NOT_RUN**，本地 PASS 不替代
平台合并门禁。以上证据路径为保留工作树中的本地路径，不假称它们已作为 GitHub
PR 附件发布。
