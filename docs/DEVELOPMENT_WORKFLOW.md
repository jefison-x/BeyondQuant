# BeyondQuant 开发流程

## Current Clean Break task route

For the explicitly authorized BYQ 0.10 Clean Break, [ADR-0088](architecture/adr/ADR-0088-clean-break-baseline-activation.md)
and the [phase plan](clean-break/fidelity-and-execution-plan.md) replace the old
0.9/P4 "Next phase" instructions below. Keep isolated worktrees, tests,
contract-first boundary changes, security separation and the existing human
PR/merge/deployment gates. A Clean Break phase advances only after Tester,
independent Sol Reviewer and Root PASS. Final old-DB backup and exact resource
identity precede Phase 8 data/environment removal. The prior phase-specific
instructions below are historical where they conflict with this route. The
general risk-selected gate below applies to Clean Break and later BYQ work;
the [Clean Break verification gate](clean-break/verification-gates.md) adds its
phase milestones and disposable-runtime rules. No old runtime/user/cache data
restoration is a Clean Break test.

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

## 通用风险分级验证门禁

本节适用于后续 Product Phase、维护、依赖升级和文档工作；专项计划可以增加与
本阶段验收直接相关的证据，但不得把过去阶段的完整日志、历史构建矩阵或全仓
测试机械复制为每个切片的必跑项。每个实现切片先记录 Git 起点与受影响边界，
在隔离分支提交可回退的源码。宿主级资源清理前，源码和配置应另有一份不在待删
资源中的副本；真实 secret 不进 Git。

| 变更范围 | 本地切片验收 | PR/阶段验收 |
|---|---|---|
| 文档、历史归档、无调用者的死代码 | diff、链接/引用、调用者证据；规范性文件运行架构测试 | CI 选择文档/架构检查 |
| 单组件行为或普通缺陷 | 修改行为的定向单元/合同测试及必要构建 | 受影响组件的完整 build/unit/contract suite 由必需 PR CI 执行 |
| 公共 API、MCP、DSH、共享合同、schema、Job/Worker | 边界合同、错误/授权路径、相关集成；schema 从全新基线验证 | 按影响运行组件与集成 CI；用户可见流程变化验证真实 Product API/浏览器 |
| 审批、租户、凭据、资金或不可逆外部动作 | 对应不变量与失败/未知结果路径，必要时隔离真实进程 | 保留专项安全验收；不能用 mock 或无关全仓 PASS 代替 |
| Compose、开发环境、资源清理 | 配置校验、限定资源的预览及受影响服务启动 | 环境里程碑从源码、模板、schema 和 seed 做一次清洁重建 |
| 阶段收口、发布候选 | 阶段功能清单与尚未覆盖的风险 | 阶段规定的 Golden/真实流程；发布候选的最终 Full 由 Release Images 承担 |

本地默认 `make dev-check`、`git diff --check` 和定向测试。长期分支若默认
`dev-check` 的 `origin/main` 基线因已提交的旧切片失败，可用
`python3 scripts/ci/dev-check.py --base <本切片起点提交>` 验证当前切片，并把
继承性失败单独记录；不得借此忽略当前切片引入的问题。规范性架构或合同改动
必须有实际架构测试证据。完整受影响组件套件、集成及浏览器检查由
[CI 策略](operations/ci-policy.md)按影响选择；本地仅在定向验证不足、调试
失败或专项验收要求时重复。没有 PR CI 的本地 PASS 只能证明本地切片，不能
充当合并门禁。

发布默认顺序为 **PR 按影响 CI → 合并 → Release Images 一次最终 Full 并发布同批受测镜像
→ Promote 同 digest → 部署健康/基本业务验证**。不在镜像发布前额外调度一遍 standalone
Full。若阶段明确要求合并前 Full/Golden，保留该独立阶段证据；它不替代可信 main 的
镜像资格验证，也不成为每次修复或普通发布的惯例。Nightly Full 仍用于跨变更漂移检查。
发布失败按 [发布 runbook](operations/image-release.md) 重试必要步骤，不重新运行已成功
且仍可复用的资格验证。不能复用失败、过期或不同构建输入的证据。

开发环境可重建性在环境或阶段里程碑验证，不在每个代码切片重跑完整 Compose。
从空环境重建的测试默认使用新 schema、最小 seed 和新数据，不要求恢复历史用户
数据或缓存。若任务涉及必须保留的真实数据、schema/存储格式迁移、备份恢复或
生产部署，则按其专项计划验证数据安全与恢复；不能把开发期可丢弃数据规则
套用到真实用户数据。任何必需测试未运行须记为 `NOT_RUN` 和门禁限制；失败
的选中测试不能用额外无关测试冲抵。

## 异步与 Agent 接续测试的方法

本节适用于后续 BYQ 开发中的异步 Job、Agent 接续和真实模型整链测试。
遵循现有风险分级门禁，不新增每个切片的全仓测试或静态冻结审批轮次。

1. **先核对观察器合同，再调用真实模型。** 用当前接口、投影代码和已有只读记录，
   一次性核对整条测试路径中的字段、状态、关联、规范化规则、分页和时间假设。
   对确定性的解析、投影和等待逻辑使用离线样本或定向合同测试；静态通过只证明
   观察器准备就绪，不代表真实接续通过。不得把真实模型整链执行作为逐个发现
   测试脚本错误的默认调试方法。
2. **按职责拆分证据。** Job/Worker 验证独立完成及 Artifact 持久化；Agent 接续
   按目标分别验证：健康且获授权的原会话收到通知后按准确 Job ID 继续回答；或旧
   会话结束后，新授权 Agent 按同一 Job ID 查询结果。后者不要求恢复旧 DSH 会话。
   权限、预算、审计各有独立合同验证；整链仍核对相关授权、资源关联和最终结算，
   但不重复所有组件的完整验收。必需的真实安全/生命周期场景仍按专项范围执行，
   不得用离线样本替代真实接续或扩大 BYQ 通用会话恢复职责来迁就测试。
3. **从事实源取证。** 精确审计动作与资源从受权限保护的权威结构化记录核对，
   不从经过产品语言转换的模型回答推断。公开回答只证明用户可见结果；测试不能
   要求浏览器或 Product Agent 绕过 Product API/MCP 读取内部服务或数据库。
   必要的内部核对由已授权的 Engineering 只读检查完成。模型自报成功不是事实源。
4. **显式等待异步结果。** 收到完成事件不等于回答持久化、预算结算等均已完成。
   前台和后台采用一致的有界只读轮询，满足条件立即结束，保留超时和最后观测值。
   不使用固定长等待，不以重复模型调用、写入或事件重放解决持久化延迟。
5. **失败分类后再决定重跑。** 区分观察器缺陷、产品缺陷、环境/依赖限制和未决
   外部动作；一次性检查同类及后续断言，修正后仅重跑受影响场景。已有证据仅在
   相关源码、合同、依赖、配置及数据条件仍适用时复用，并记录适用边界；阶段明确
   要求的最终 Golden/Full CI 不因此省略。未知外部动作先对账，不自动重放。
6. **管理测试连接与资源。** 对已确认无未决副作用的观察器错误，可有界保留原连接
   并只读对账，避免立即关闭浏览器使同会话证据失效。实际执行异常或安全边界不明时
   停止相关动作；所有保留都有期限，最终仍清理测试连接及专用资源。SSE 存活不等于
   DSH 会话仍有效；仅在验证同会话接续时核对原 Runtime 身份与资格，原会话消失
   不得重建后冒称同会话通过。新授权会话按 Job ID 查询结果的场景独立验收。
   等待人工/Root 步骤纳入总时限，尽量提前准备确定性控制步骤。

每轮真实整链测试先写明目标、尚缺证据、最大模型回合/Job 数与总时限。失败后记录
具体停止位置和分类；只有修复了具体原因、条件变化或为诊断一个明确假设时才重跑，
不得因失败自动升级为全量回归、重复已有效通过的场景或新增产品 runtime 抽象。

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
6. 按上述通用门禁运行本地 diff/语法、定向行为与合同测试；规范改动必须运行
   相关架构测试。记录每项 PASS/FAIL/NOT_RUN 与覆盖边界。
7. 依据 [CI 策略](operations/ci-policy.md)确认受影响组件及集成风险，确保 PR CI
   执行完整受影响 build/unit/contract suite；本地无需重复一遍已由 CI 覆盖的套件。
8. 仅在变更影响真实 Product 流程、专项阶段要求或故障诊断时增加本地
   smoke/integration/browser；UI 阶段必须完成规定的真实浏览器验收。
   真实模型评测是独立授权/证据层，不向 required keyless CI 注入真实 secret。
9. 运行 `git diff --check`，检查完整 diff，并执行安全和架构自审。
10. 在 feature branch 上有意识地提交；只有 push/pr 授权覆盖时才 push 该分支。
11. 授权覆盖时创建以 `main` 为目标的 Draft PR，说明范围、证据、已知限制和剩余决策；否则本地交接。
12. 已推送时用 `scripts/ci/watch-ci.py`（精确 PR/head/run、单次读取或有界短观察）
    等待远端 CI 并记录结果，不用长期 grep+sleep 循环；未推送时如实记录本地验证，不能
    冒充远端 CI。只在 feature branch 中修复失败。
13. 最终复核文件、测试、依赖 pin 和边界变更。
14. 默认停在人工合并门禁；仅本文件明确的预发布例外可进入 auto-merge，绝不直接 push 到 `main`。

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

merge preflight 只评估**精确 PR head 上最新的有效 BeyondQuant CI run**（按 check 的
`/actions/runs/<id>` run identity 分组，而非按 check 名称）。同一 head 上更旧的 run 若被较新 run
取代（工作流使用 `cancel-in-progress`），其 cancelled/failed rollup 不得污染结论；最新的 run 出现任何
failure/cancel/skip/neutral/incomplete、缺少 required context、head 不符、非 BeyondQuant CI 工作流，
或无法确认 run 归属时一律停在 Draft。

仅源码公开过渡任务适用 [ADR-0060](architecture/adr/ADR-0060-source-publication-and-hosted-ci.md)
中已获维护者批准的一次性例外；它不能用于后续 runner PR、DSH 升级或普通开发。
公开贡献还须遵守根 CONTRIBUTING.md / CONTRIBUTOR_LICENSE_AGREEMENT.md；技术 CI 成功
不代表权属或贡献授权已完成。

生产部署独立于合并。只有获授权的 Product 外 trusted operator 可按 ADR-0040/0059 的
runbook 发布指定已验证制品，记录 backup（必要时）、服务范围、readiness、业务 smoke、rollback。
这不允许 Engineering/Product 自主部署，也不允许自动 destructive migration。

常规升级采用 ADR-0059 的 2026-09-10 轻量流程：升级前备份数据并保留当前配置和精确旧镜像 →
部署通过 CI 的目标镜像（必要时排空会话）→ 健康与基本业务验证 → 失败时切回旧镜像及配置。
不每次重新研究回滚方案或执行完整数据库恢复演练；只有数据库结构、存储格式、不兼容或不可逆
数据变更，或已有恢复证据失效时，补充针对性的恢复验证。普通应用回退保留当前数据库；
实际数据恢复须另行授权。检查备份成功、可读和校验和，不能冒称已完成本次备份的完整恢复测试。


## 证据要求

浏览器验证不绑定工具：按 ADR-0059 的 2026-09-09 修订，使用 Playwright 管理的
Chromium 等测试浏览器即可，不要求 Chrome MCP、系统安装的 Chrome 或维护者个人浏览器。
真实 Product API、持久化、隔离以及按影响要求的桌面/移动端、网络/Console、视觉检查仍须验证；
不能仅凭 mock 页面或 HTTP 200 宣称完成。历史文件中的 Chrome MCP 专属门禁不再生效，
历史实际使用该工具的证据保持不变。

架构变更需要新增 ADR 或更新相关 Accepted ADR。集成边界需要 framework-neutral
Contract 和 translation test。外部依赖必须有准确的 metadata/version 证据。
Runtime 变更需要 lifecycle 和 cleanup 证据。Product/Engineering 能力变更需要
明确的隔离测试。仅有绿色测试不足以作为架构验收证据。

## Community 参考与迁移纪律（ADR-0068）

当前及之后所有开发步骤免除 Community 原实现检查。不得因旧源码不存在、未读取或
未重新检查而阻塞开发，也不再重复请求豁免。历史 Phase/专项计划中的强制原实现检查
由 ADR-0068 覆盖；现有 BYQ 合同、领域不变量、测试与真实 Product API 验收仍必须满足。

如主动复用旧代码，先核对来源、许可和 `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`
中的迁移分类；不能盲目复制旧架构。Community 源码与数据保持只读。
真实缓存迁移仍必须验证来源、单位、schema、时点、覆盖和完整性，采用只读逻辑导出
及可重复导入，不允许物理目录复制/挂载。

BaoStock、AKShare、VectorBT、PydanticAI/Hermes 主运行时、Agent 直连数据库或前端
依赖 raw DSH schema 等禁止项不变；不得用 compatibility layer 绕过架构。

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
- Product UI Phase 必须具备真实浏览器/Product API evidence 和功能
  checklist，才能视为完成；
- PR body 必须包含 Product Evidence：适用的功能来源（无需 Community 原实现检查）、已测试的 browser
  journey、所用测试浏览器及审查结果、frontend test、backend/Product API test、已完成的
  screen/surface，以及仍缺失的项目。
