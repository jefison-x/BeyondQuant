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
   repo 与 attempt，过期/被取代的 attempt 不继承最新 rollup 或陈旧 green。只在状态
   变化时输出；对 429/5xx/timeout 做有限指数退避；403、未知、缺失、过期一律
   BLOCKED/STALE（退出码 3），绝不返回 PASS；失败时用有界脱敏日志。watcher 不是合并授权工具。
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

## CI-B — backend 测试墙钟时间（未开始）

范围：在 CI-A 量化后，针对 `_byq_reset_schema` 的逐测试整库重建与其余慢 setup/
call/teardown 做低风险、可回退的收窄（例如：经验证安全的按测试隔离策略或
schemas/fixtures 复用），保持覆盖与跳过语义等价、cleanup 资源为零、无隐藏失败。
非目标：为达标删测试或降低断言。验收：CI-A 基线对比、pytest 计数/跳过集合等价、
setup 时间可量化下降、失败路径与隔离回归通过。任何 schema/fixture 语义改动需
单独论证；否则延后。

## CI-C — 变更依赖分类细化（未开始）

范围：细化 `scripts/ci/classify-changes.sh` 对 `services/runtime-adapter`、
`scripts/dsh`、`packages` 与未知路径的过宽分类，以及 build-identity 相关路径，
使窄改动不再一律触发 all+integration；保持 unknown/fail-closed 与
`tests/architecture/test_ci_policy.py` 的代表性路由合同。验收：负例（未知、
移除内联 DDL、契约/迁移）仍触发 integration；新增最小影响的分类负例；无漏测。

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
