# BeyondQuant CI optimization plan（CI-A / CI-B / CI-C）

Status: maintenance execution plan，非 Product Phase，非永久授权。
本文是基于一次维护任务（Batch CI-A）写下的执行与验收计划；它记录事实与步骤，
不扩大任何合并、部署或 runner 授权。任务本身不是常驻规则；后续批次仍需维护者
明确指令与工作树/Draft PR 门禁。

约束（适用于 CI-A/B/C 全部批次）：

- 不推进 Product Phase，不开始 D15-4/R3；不与 D15 资格提交混合。
- 不部署、不发布、不改 Accepted ADR；不做 release 架构或 ADR-0070 变更。
- 不使用付费/larger runner；不削弱或删除安全、贡献、脱敏、cleanup 与门禁检查。
- 一次批量一个隔离 worktree/分支/Draft PR；默认停在人工合并门禁。

## 测量基线（2026-09-18T00:00Z 起，已验证）

- 35 个 PR CI 运行：23 success / 8 failure / 3 cancelled / 1 running。
- success 中位总时长约 21m33s；Release Images 中位约 35m51s。
- `run 35471161872`（PR #324，head `7a21d28e2e27d6fe8fb64ec3cad680597608ee2a`，success）：
  总 22m07s；`plan` 6s、`contribution` 13s、`architecture` 33s、`docs` 26s、
  `gateway` 61s、`runtime` 64s、`frontend` 180s、`mcp` 77s、`integration` 560s、
  `backend` 1301s（21m41s）、`local-ci` 3s、`ci-gate` 3s。
  backend pytest：793 passed / 3 skipped in 1227.02s；即 backend 作业约 74s 用于
  镜像/环境准备，其余为测试墙钟时间。
- `run 35444735879`（PR #319，failure）：`contribution` 在 13:05:33（约 5s）失败，
  但 `checks` 矩阵仍继续，`backend` 直到 13:27:06 才结束（约 21m38s 浪费），
  `local-ci` 报 success、`ci-gate` 才因 contribution 失败。这是“重检查未依赖
  快速 plan/contribution”的直接证据。
- `run 35449696326`（failure）：`plan` 因 gitleaks 失败，整次约 25s 结束。
- 失败不等于 flaky：`contribution` 失败是可信基线检查在正常拒绝未授权贡献；
  不得因此删除真实贡献来源或放宽 CLA/审查。
- `services/backend/tests/conftest.py` 的 autouse `_byq_reset_schema` 对每个测试
  `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public` 并按注册顺序执行全部
  `REGISTERED_SCHEMA_DDL`（当前 23 个 store）。这是 backend 墙钟时间的强线索，
  但尚未证明为 1227s 的全部；`--durations` 基线用于量化 setup/call/teardown。

构建与缓存不是本样本的瓶颈（build 约 15s，镜像/buildx 缓存已存在）。

### 第一批 CI-A 实测（run 35475291783，head `8cd0e22…`，attempt 1，success）

- 总时长约 22m56s，与基线同量级。jobs：`backend` 1343s、`integration` 575s、
  `frontend` 157s、`mcp` 73s、`runtime` 61s、`gateway` 44s、`architecture` 28s、
  `docs` 17s、`plan` 8s、`contribution` 6s、`local-ci` 2s、`ci-gate` 4s。
- backend lane（脱敏 `checks.log` 解析）：pytest `793 passed, 3 skipped` / collected 796
  in 1247.96s；`[byq-timing]` 阶段 build 23s、backend 1268s。
- integration lane phases：build 73s、candidate qualification 158s、smoke 200s、
  F6 chain 101s；total 533s。
- `--durations` 观察：backend 中 ≥1s 的 call 项合计 97.47s，≥1s 的 setup 项合计
  5.32s（最大 setup 约 1.96s）。即逐测试 schema reset 的代价分散在大量 <1s 的 setup
  中，而不是某个单点；CI-B 必须用更低阈值或聚合统计量化，top-20 不能单独证明。
- 失败路径见上面的 `run 35444735879`。

## CI-A — 测量 + 低风险流程整改（本批，一个 PR）

### 变更

1. 既有入口的低噪声、脱敏计时与慢项统计：
   - `scripts/ci/local-ci.sh` 在既有 `step()` 边界输出 `[byq-timing] phase=... seconds=...`
     与退出时 `[byq-timing] total ... exit=...`；不改变选择、顺序或通过/失败。
   - backend/gateway/runtime 的 pytest 增加 `--durations`/`--durations-min=1.0`，
     在脱敏日志中给出 setup/call/teardown 慢项。
   - `scripts/ci/ci-metrics.py` 只读已脱敏日志，汇总 selection、阶段耗时、pytest
     收集/通过/跳过、慢项、镜像身份与缓存行数；复用共享 redactor，且不抓取、
     不上传任何日志。
   - 不新增额外 Full 运行：本 PR 的既有必需远端验证即产出基线。
2. 重检查早失败：`checks` 矩阵改为 `needs: [plan, contribution]`。plan/contribution
   失败时跳过昂贵的矩阵；`local-ci` 仍要求 plan 与 checks 均 success，`ci-gate` 仍
   要求 `local-ci` 与 `contribution` 均 success。skipped 不计为 success。
   保留可信基线 contribution、token 隔离与 fork 限制；矩阵 `fail-fast: false`、
   每 lane cleanup 与诊断上传不变。
3. 结构化 watcher：重写 `scripts/ci/watch-ci.py`，支持单次读取（`--once`，真正
   单次、不 sleep、不重试）与有界可恢复观察（`--budget-seconds`，整次调用硬上限，
   含 API 读与失败日志）。`--run-id` 只匹配格式正确且 owner/repo 一致的完整数字
   路径段（避免 123 命中 12345）；`--run-attempt` 通过 Actions API 校验 head、workflow、
   repo、attempt 状态与该 attempt 的 job 身份，并在读取前后复核 attempt/head：运行中或
   失败、被取代、job 不属于当前 attempt、或读取窗口内 attempt/head 变化，都不得沿用过
   去 green。只在状态变化时输出；对 429/5xx/timeout 做有限指数退避；403、未知、缺失、
   过期一律 BLOCKED/STALE（退出码 3），绝不返回 PASS；失败时用有界脱敏日志。watcher 不是
   合并授权工具。
4. 合同/负例测试：workflow 结构（依赖、聚合、取消/cleanup）、缺失矩阵/空计划
   必须失败、contribution API 失败/过期 head 失败、watcher 的 PASS/FAIL/PENDING/
   BLOCKED/STALE、退避与预算有界、单次读取不 sleep、仅在状态变化时输出。
5. 本地 `make dev-check` + 定向测试；push 前做提交元数据检查与既有 secret scan。

### 验收标准（CI-A）

- 合同与负例测试全部通过（含缺失矩阵、早失败、取消、API 失败/过期 head）。
- `checks` 依赖 `[plan, contribution]`；plan/contribution 失败时 final `ci-gate`
  必须失败；skipped 不算 success。
- watcher：`--once` 不 sleep；有界观察在预算内结束；403/缺失/过期不为 PASS。
- 脱敏与 cleanup 行为不变；无新增 Full 运行；无付费 runner；无安全检查弱化。
- 本 PR 的必需远端验证产出可解析的 `[byq-timing]`/`--durations` 基线。

## CI-B — backend 测试墙钟时间（本批，测量 + 低风险收窄）

范围：在 CI-A 量化后，针对 `_byq_reset_schema` 的逐测试整库重建与其余慢 setup/
call/teardown 做低风险、可回退的收窄（例如：经验证安全的按测试隔离策略或
schemas/fixtures 复用），保持覆盖与跳过语义等价、cleanup 资源为零、无隐藏失败。
非目标：为达标删测试或降低断言。验收：CI-A 基线对比、pytest 计数/跳过集合等价、
setup 时间可量化下降、失败路径与隔离回归通过。任何 schema/fixture 语义改动需
单独论证；否则延后。

### CI-B 证据分类（估计 / 本机实测 / 远端实测，2026-09-20）

本节严格区分三类证据，**不得把外推当成同条件 old/new 测量**：

**(a) 远端同 lane 实测（最强对照，不同 run、同类 ubuntu-24.04 runner）**

- CI-A 基线：run `35475291783`，`793 passed + 3 skipped` / collected 796 in
  **1247.96s**；backend job 1343s；仅 ≥1s 的 call 合计 97.47s、≥1s 的 setup 合计
  5.32s，说明成本分散在阈值以下，必须聚合。
- 本批 **old head 中间测量**（head `b04cd10`，修复前隔离模块；**不是最终验收口径**，
  最终结果见 (d)）：run `35483981710` attempt 2，backend job
  `106006956776`：`800 passed, 3 skipped, 1 warning, 7 subtests passed` in
  **951.10s**；backend job **1033s**；`[byq-timing] pytest_setup=95.27 (n=803)
  pytest_call=850.99 (n=809) pytest_teardown=0.43 (n=803) session_wall=951.12`；
  `schema_resets=568 schema_reset_seconds=665.38 store_bootstraps=2224
  store_bootstrap_seconds=40.90`；backend phase 980s。
- 即同 lane 实测：job 1343s→1033s（−310s），pytest 1247.96s→951.10s（−296.9s），
  且新 run 比基线**多 7 个测试**，方向保守。

**(b) 本机隔离 test DB 实测（postgres:16 容器 + worktree backend 镜像）**

- 单次整库重建（`DROP SCHEMA public CASCADE` + `CREATE SCHEMA public` + 23 个 store 的
  247 条 DDL，116 张表）：DROP+CREATE 25ms，DDL 约 0.92–0.95s，合计约 1.0–1.18s/次；
  对已存在 schema 重跑全部 DDL 仅 74ms；`TRUNCATE` 全部 116 张表 394ms。
- 采用延迟重建后整批（修复前隔离模块）：`800 passed, 3 skipped` in **904.40s**；
  `schema_resets=568`（803 个测试中 **803−568=235** 个从不打开数据库连接）、
  `store_bootstraps=2224`、`store_bootstrap_seconds≈39.4s`（不含重建）。
- 本机日志为临时文件（已清理），持久证据是 (a) 的远端 job 与脱敏 artifact。

**(c) 估计（外推，非测量）**

- 若旧实现对这 235 个纯逻辑测试各再付一次约 1.17s 重建，则本机等价旧值约
  `904.40 + 235×~1.17 ≈ 1179s`；相对本机新值约低 23%。这是**逐 DDL/逐测试外推**，
  不是同条件 old/new 测量，只用于解释 (a) 的机制；不得单独引用为实测加速。

**(d) 最终 head 实测（CI-B 验收口径）**

- **CI-B 的最终验收结果是最终 head（合并前最后提交）的 backend lane：
  `799 passed + 3 skipped`，pytest in 975.06s。**
- (a) 的 `800 passed + 3 skipped` / 951.10s 是更早的 old-head 中间测量（head
  `b04cd10`，修复隔离模块之前）；两者相差 1 个测试。**不得把 old-head 的
  800/951.10s 当作 CI-B 最终验收数字**。以最终 head 对 CI-A 基线同 lane 比较：
  `793 passed + 3 skipped` / 1247.96s → `799 passed + 3 skipped` / 975.06s
  （−272.90s，约 21.9%，且最终 head 多 6 个测试，方向保守）。跳过集合始终为
  3 个，未新增跳过、未删除断言。

### 采用方案（最小、可回退，且不削弱隔离）

`_byq_reset_schema` 改为**延迟重建**：autouse fixture 只声明本测试“可能用库”；真正的
`DROP SCHEMA + CREATE + 全部注册 DDL` 在该测试**第一次取用数据库连接时**执行一次。
所有生产与测试路径都经 `app.db.create_db_engine` 取引擎，因此只需插桩该单一工厂
（`engine_connect` + 创建时即刻触发）。不打开的连接的测试（纯逻辑/纯契约）不再付
整库重建。数据库测试的隔离语义**完全不变**：仍是每测试一次 DROP/CREATE + 全量 DDL，
动态 schema（测试 `DROP TABLE`/`DROP COLUMN`/`CREATE TABLE`）仍由下一次全量 DDL 复原，
多连接/提交语义不变，无全局回滚、无 SQLite/mock、无“测试跳过迁移”分支。

### 被排除的方案（及隔离风险）

- **session 初始化一次 + 逐测试 TRUNCATE**：`TRUNCATE` 无法复原被测试 DROP 的表/列
  （`test_operations_api` DROP `market_daily_bars`；`test_backtest`/`test_feedback_
  publisher_create_permit` DROP 列），若补跑全量 DDL 也只能修列、不能清除测试自建的
  额外对象；收益仅约 2x，且无法证明动态 schema 清理，故放弃。
- **独立 DB/容器分片**：保持完全隔离、可线性缩短墙钟，但需要多数据库编排与资源上限，
  超出本批“最小可靠”的范围，延后到后续批次（需先有分片隔离回归）。
- 未采用 pytest-xdist（未知共享状态）、未把 autouse 改 session（污染风险）、未改断言/
  跳过集合/生产代码。

### CI-B 验收与隔离回归

- **测试/跳过集合**：基线集合为 `793 passed + 3 skipped`（collected 796）；**最终 head
  验收集合为 `799 passed + 3 skipped` / 975.06s（见 (d)）**。old-head 中间测量曾为
  `800 passed + 3 skipped`（collected 803 = 796 + 7 个新隔离测试），**不作为最终验收**。
  跳过集合不变（仍 3 个，无新增跳过、无删除断言）。old-head 的远端 summary/job 见 (a)；
  脱敏 `checks.log` 位于 run `35483981710` attempt 2 backend job `106006956776` 的
  artifact `ci-35483981710-2-backend`。
- 新增 `services/backend/tests/test_schema_isolation.py`：
  - **真实失败后自动恢复（有界嵌套 pytest 子进程）**：第一个用例提交脏行并创建动态表
    （`CREATE TABLE`/`CREATE INDEX`）后**真的失败**；第二个用例**不调用任何手动 reset**，
    仅靠正常 autouse/首次取用路径自动恢复；断言失败数=1、通过数=1、`schema_resets=2`
    （证明自动路径每测试恰好执行一次，未用手动 reset 代替），并断言脏行与动态对象已清除、
    注册表仍在。`conftest.py` 中手动 reset 夹具 `byq_force_schema_reset` 已删除，杜绝替
    代路径。
  - **确定性写后读（两类顺序位置）**：生成模块按定义顺序固定 writer 在 reader 之前；
    reader 首先断言"writer 已运行"（污染前置条件），若顺序被倒置则显式失败而非空证据；
    两个 variant 分别把 writer/reader 对放在套件不同位置（前置/中间/后置噪声测试之间），
    并各自断言脏行/动态对象清除与 `schema_resets=2`。嵌套子进程会清除
    `BYQ_TEST_SHUFFLE_SEED`，确保外层乱序无法倒置该前置条件。
  - 注册迁移真的执行（迁移列存在）、独立连接可见已提交写入（未用全局回滚）、纯逻辑
    测试不触发重建、用库测试每测试恰好重建一次。
- `scripts/ci/local-ci.sh` 在 backend lane 之后以 `BYQ_TEST_SHUFFLE_SEED=1` 固定种子乱序
  重跑该隔离模块，证明外层模块用例顺序无关（跨用例写后读证据由上述确定性嵌套子进程提供，
  不依赖乱序顺序）。
- 聚合统计由 `services/backend/tests/conftest.py` 在 pytest 结束时以单行
  `[byq-timing] pytest_setup=… schema_resets=…` 输出（沿用 CI-A 脱敏日志）。

## CI-C — 变更依赖分类细化（本批实现，Draft）

状态：已在隔离 worktree `codex/phase-ci-c` 实现；默认停在人工合并门禁。范围仍为
细化 `scripts/ci/classify-changes.sh` 对 `services/runtime-adapter`、`scripts/dsh`、
`packages` 与 build-identity 路径的过宽分类，使窄改动不再一律触发 all+integration；
未知路径仍 fail-closed。

### 分类器审计（实际消费者与传递依赖）

- `services/runtime-adapter/app`、`services/runtime-adapter/runtime`：生产 runtime 协议边界，
  由 `runtime` lane 执行，跨边界行为由 integration 的 candidate/F6 资格覆盖 → 保持
  all+integration。
- `services/runtime-adapter/tests`：审查后**不纳入收窄**。虽是测试，但目录内文件众多且
  `d15_candidate_probe.py`/`f6_synthetic_runtime.py` 等由 integration 挂载；无法以单文件
  级更省的证据替代保守覆盖 → 整族显式 fail-closed（full+integration+unknown）。
- `services/runtime-adapter/Dockerfile*`、`pyproject.toml`、`requirements*.lock`：build identity、
  依赖与容器启动 → 保持保守。
- `scripts/dsh/*`：`release.py`/`promotion.py`/`build_revision.py`/`historical_inputs.py`/
  `plugin_registry.py`/`web_evidence_provenance.py` 属 build identity/selector → 保持
  all+integration。仅逐个审计过的 operator 脚本（见下表）收窄为 architecture；其余
  `scripts/dsh/production_*` 显式 fail-closed（`production_application_backup.py` 与
  `production_restore_check.py` 无根测试消费者，保持保守）。
- `packages/contracts/*`：由 backend/gateway/runtime 引入且属共享机器可读契约 → 保持
  all+integration；`packages/operations/` 目录下只有 `admission.py` 被逐一审计（仅
  `services/gateway/app/main.py` 与 `services/runtime-adapter/app/main.py` 引入，根 `tests/`
  覆盖，是 Gateway/Adapter 跨边界启动门）→ gateway+runtime+architecture+integration；
  目录内其它文件不推断，显式 fail-closed。
- 未知/新路径：仍 `unknown=yes` + all+integration，未放宽。

### 收窄（精确审计文件白名单，不使用前缀/glob）

| 精确文件 | 新选择 | 逐一审计依据 |
|---|---|---|
| `packages/operations/admission.py` | gateway+runtime+architecture+integration | 仅 gateway/runtime-app import；根 `tests/test_chat_admission.py`；跨边界启动门保留 integration |
| `scripts/dsh/production_backup.py` | architecture | 仅根 `tests/test_dsh_production_backup.py` 与同族 operator 脚本引用；无服务/镜像/CI |
| `scripts/dsh/production_observe.py` | architecture | 仅根 `tests/test_dsh_production_observe.py`；无服务/镜像/CI |
| `scripts/dsh/production_session_backup.py` | architecture | 仅根 `tests/test_dsh_session_backup.py`；无服务/镜像/CI |

三族各自的**未列入白名单成员**（新文件、同族未审计文件、嵌套子目录、rename 目标、被删除的
白名单文件）都由显式 guard 归为 `unknown=yes` + all+integration。

delete/rename：`plan.py` 与 `local-ci.sh` 的 diff 增加 `--no-renames`，使移动的旧路径也进入
风险并集；被删除/改名的白名单文件因 `[ ! -f ]` 也 fail-closed。

### 离线回放（ESTIMATE，非测量）

- 输入：最近 13 个 PR（含 #326/#329/#327/#324 等）的 changed-file 列表，本地 git 计算，
  **未触发任何新 Full 运行**。
- 结果：这些 PR 同时改动 build-identity/依赖/契约/runtime-protocol 路径，收窄类不改变其
  选择（**13 个 PR 合计 0 lane 变化**）；最近 80 个提交中精确白名单文件从未单独出现。
- 单类隔离估计（假设未来 PR 只改该类；复用基线 run `35471161872` 的 lane 秒数）：
  `packages/operations/admission.py` 约 −1558s、`production_backup.py` 约 −2243s；
  runtime-adapter tests 已不再收窄，估计为 0。
- 原始输入/输出：`docs/operations/ci_c_offline_replay.json`。**全部标记为 ESTIMATE，
  不是测量值；CI-C 未交付整体加速，不得据此声称墙钟收益。**

### 路由合同与负例

`tests/architecture/test_ci_policy.py` 的 `CiRoutingContractTests`：未知/新路径 fail-closed；
契约、内联 DDL 移除、迁移、lock/依赖、容器启动、runtime-protocol 跨边界、build-identity
保持覆盖；混合变更取风险并集；delete/rename 取旧+新并做真实 git rename 端到端回放；
精确白名单文件只保留所需 lane。新增逐族负例：**未审计同族文件/新文件/嵌套子目录/被删除或
改名的白名单文件/混合变更**都必须 full+integration+`unknown=yes`（这些负例在修复前的
wildcard 版本上失败，在精确白名单上通过）。

### 构建身份

本批改动 `scripts/`、`tests/` 等 build inputs → 按规则新建不可变
`config/dsh/builds/dsh-0.1.2rc1-post-u8.158.json`（首个 CI-C 提交）；精确白名单修复再次改动
build inputs → 再新建 `config/dsh/builds/dsh-0.1.2rc1-post-u8.159.json`，selector 与候选
Dockerfile COPY 指向 `.159`。`.158` 不覆盖、不删除，历史清单与既有证据保持只读。

验收：负例（未知、移除内联 DDL、契约/迁移）仍触发 integration；新增最小影响的分类负例；
无漏测；`make dev-check` + 定向合同测试通过；无付费 runner、无安全检查弱化。

## 批次验收标准（CI-A/B/C 通用）

- 一工作树/分支/Draft PR 一批；不推进 Product Phase；不改 Accepted ADR。
- 每个批次：定向测试 + 受影响合同测试 + `make dev-check` 通过；change-impact
  负例不退化；安全/脱敏/cleanup 不弱化；无付费 runner。
- 只有实测支持的性能结论才可写入；不得声称未测得的加速。
- 每个批次默认停在人工合并门禁；合并与部署是独立授权。

## 基线 vs 候选（事实）

- CI-A 成功路径不声称墙钟下降：本 PR 触及 `scripts/ci/*` 与 `tests/*`，预计仍运行
  全部 component + integration lane，候选总时长应与基线同量级。
- CI-A 的实测收益在失败路径：`contribution`/`plan` 失败时重检查被跳过，可避免
  约 21 分钟的无谓矩阵运行（见 `run 35444735879`）。这会增加成功路径上
  `checks` 等待 `contribution` 的少量固定开销（约数秒量级）。
- 21min→10min 之类的成功路径加速未在本批测量或声称；那属于 CI-B。

## 覆盖/跳过等价与资源清理

- CI-A 不修改测试集合、断言或跳过条件；backend 计数应保持 793 passed / 3 skipped
  （脚本/测试改动会重跑，但不应改变该集合）。
- 资源清理与 scope 隔离逻辑不变；skipped lane 不触碰资源。

## 剩余限制

- CI-A 只测量，不解决 backend 逐测试 schema 重建；该问题在 CI-B 处理。
- 有界 watcher 以短调用+重入实现“可恢复”，调用方需在退出码 2 时重新调用，
  不能把它当作常驻进程或合并判据。
- 队列时间来自平台 run API，不在脱敏日志内；`ci-metrics.py` 允许显式传入。
- Release Images 的 `--all` 串行 Full 与独立 publish 是 ADR-0070 现行要求；
  CI-A/B/C 均不删除重复验证，也不复用未证明身份的 PR 制品。
- CI-C 的收益只对“仅含收窄类路径”的未来窄 PR 生效；采样到的近期 PR 均为 build-identity/
  依赖/契约类，收益为 0（见离线回放）。`config/dsh/builds/*`、`scripts/d15/*`、
  `scripts/ops/*` 等仍按未知/保守路径 fail-closed，未纳入本批收窄。
- CI-C 未测量真实墙钟节省；`ci_c_offline_replay.json` 的数值是基线 lane 秒数外推的
  ESTIMATE。真实的隔离 runtime 连续性资格（D15-4+）不在本批范围。
