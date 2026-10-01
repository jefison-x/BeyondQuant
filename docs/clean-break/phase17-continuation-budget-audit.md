# Phase 17 — continuation 预算与 F6 观察器审计

Status: **ADR-0090 已实施；v11 FG1/FG2/BG、独立请求限额及持久化结算真实通过；完整 F6 因 Root 收尾观察器超时保留 FAIL；失败清理完成，CLI 窄修正及独立空队列控制实测通过；成功 UI NOT_RUN，Phase17 OPEN**。
本记录使用当前 Clean Break ADR-001–006/ADR-0088；历史 ADR-0086 不作为现行规范。
[ADR-0090](../architecture/adr/ADR-0090-continuation-request-limits.md) 已于 2026-10-01 获维护者“明确接受”。以下第 1–6 节保留接受前限定验收的事实边界；当前实施及实测状态见第 13–14 节；旧节保留其记录时边界。

## 1. 同步、停机状态与证据保护

维护者指定的 PR #380 提交 `84943da350b8a9e185d3ee100b65ceaee08692d0`
已经用普通 merge 纳入 `codex/clean-break-phase17`。没有 reset、stash、覆盖未提交文件、
推送、远程合并、部署或数据库操作。合入前隔离分支 tracked/untracked Git 状态干净。
合入只新增 workflow/gates 文档；原业务源码与 `.280` 运行镜像未因此改变。

暂停时保存到 `/tmp/byq-phase17-budget-simplification-20261001/`：

- `pre-sync-worktree.json`：合入前分支/HEAD/status；`protected-f6-files.json`：175 份 F6 私有文件哈希。
- `paused-live-state.json` 与 `paused-ml-identities-supplement.json`：精确 ML Job ID（初次清单遗漏该 DTO 字段，原记录保留）及 Compose `byq-dev-dd33416d94` 的 13 个容器身份/镜像/状态。
- Host F6 runner/launcher/audit/native 进程 0；Runtime SDK active 0、active_prompts 0。
- Runtime normalized model counter 24；raw provider HTTP **NOT_OBSERVED**，不能把该计数当全部原始 HTTP。
- 已核对的 Signal/Backtest/Training/Prediction 共 8 个 Job 均终态；其目录完整性按各接口上限检查。
  Factor Job/Data Demand 不具有此处完整只读 Product 枚举证明，未声称全域队列已审计。
- Signal/Data/ML Worker 均 exited。F6 v6 无 `RUN-F6`、无 freeze、无批准/许可/新 Job。
- v2/v3/v4/v5 的失败和只读对账保留，不重放未知调用，不重写成 PASS。

## 2. 通用规则落实到观察器

依据 [异步与 Agent 接续测试的方法](../DEVELOPMENT_WORKFLOW.md#异步与-agent-接续测试的方法)，
在任何新真实调用前集中核对整路径，而不是逐个断言失败后反复跑模型。
当前私有候选在 `/tmp/byq-phase17-280-f6-v6/`，Root 是唯一 writer；子代理仅审计/定向测试。

- 精确动作/resource/run 从 Root owner-scoped 结构化 AgentRun audit 与 Domain 记录核对。
  `系统能力` 只校验公开投影展示；不替代原始 byq action、ID、顺序、角色、owner/workspace/root/boot。
- 修正 Draft `[Task]`、Version `[Task,Draft]` lineage，与现行 ResearchStore 合同一致。
- FG/BG 成功事件后均只读等待持久化；后台另外等待同一许可由 reserved
  `unconfirmed_reservations=1` 转 settled `=0`。60 秒截止，每个 GET 最大 10 秒且取剩余时间；
  条件满足立即退出，超时保留最后样本。不能以 SSE terminal 代替答案和结算。
- 已记录成功终态、无未知测试写入的 observer-only 错误先保存 error/SSE，再最多 900 秒保留连接只读。
  已捕获片段逐项比对；观察遗漏的额外 Product assistant 仅保存序号/hash供对账，不冒充 PASS。
  拒绝新的 SDK root、额外用户输入或身份/资源变化。Task 未知时只读 exact session/delivery，Task ID 保持 null。
- Root `observer-reconcile-stop` 只做 bootstrap login 与按已知 ID 的精确 Product GET，独占写对账/停止信号；
  不查 latest、不创建对象、不重放、不调用模型或 SQL。原失败仍 FAIL，最终 finally 才断 SSE/关闭浏览器。
  900 秒截止或安全异常同样结束保持。专用 Worker/grant/session 清理需按实际创建事实执行，不凭猜测删除。
- 未知调用先对账，未确认副作用/执行异常不自动归为 observer-only；原健康 Runtime 资格与 SSE 存活分别核对。
- 原健康会话自动接续与新授权会话按同一 Job ID 查询各自验收；不要求 BYQ 恢复旧 DSH 会话。

旧 v6 preflight 和 source pins 属于暂停前候选，不能据其直接启动。
预算切换接受、实施、合同验证后再准备真实 F6，明确回合/Job/总时限和清理，不新增一轮轮静态审批仪式。

## 3. 当前机制与最小 KEEP / DELETE / REWRITE

| 决定 | 对象 | 当前事实与处理 |
|---|---|---|
| KEEP | Backend continuation_permission、grant version/期限/撤销/准确策略 hash | 活跃授权事实；Workspace/用户校验、幂等、确认和逐动作许可保持 |
| KEEP | continuation_budget 的 reservation/event/input/run/未决和终态回执 | 活跃业务责任和 at-most-once 事实；未知结果不可删除、退款或重派 |
| KEEP | research_judgment_stage_calls | 研究请求独立 admission/attempt 幂等事实，不是 provider 消耗余额 |
| KEEP | 原健康会话资格、Domain root authority fence、Job/Artifact/audit | 独立安全边界；Job 不依赖 Agent；Product DSH 只经 MCP |
| DELETE（ADR 接受后） | grant token_limit 减历史 charged 的派发算法 | 当前 `reserve_continuation_budget` 与 poll 活调用；不能按 dead code 删除 |
| DELETE（ADR 接受后） | JS 从 tokenLimit/固定 1MiB 推导调用次数并将 ceiling 当 charge 的新请求路径 | 用具名请求限额取代；保留旧回执只用于对账 |
| REWRITE（ADR 接受后） | Adapter reservation carrier / guard / settlement 与 Gateway DTO | 绑定 profile/hash、请求身份；安全 limits、实际 usage 和业务结果分开 |
| REWRITE（ADR 接受后） | 单次 research_request_budget / research_request_gate 复用边界 | 复用前置 bytes/output/time/usage 方法，不照搬历史 3-call/stage/persona 规范；补累计量/全请求 deadline/工具 dispatch 限额 |
| DELETE（待定向验证的独立死常量切片） | JS `RESEARCH_JUDGMENT_MAX_CALLS=2` 与只读取它的镜像断言 | 不参与 runtime guard；不能据此删除活跃 Backend stage admission 上限 2；当前尚未删除 |
| REWRITE（已完成现行错误修复） | provider usage parser | bool/负数必须 unknown；无可靠 output 仍拒绝回传；不改变预算授权 |

关键源码：Backend `research_continuation.py` 的 `_continuation_view`、
`reserve_continuation_budget`、`poll_continuation`、`record_continuation_receipt`；
Adapter `continuation_budget.py` 的 `create_guard_patch/read_guard` 和 runtime 的
`_budget_receipt`；Gateway `_consume_admitted_task_continuation` 回执对账；JS `createBudgetGate/apply`。

固定 ceiling 的合计经 `read_guard` 写成 `charged_tokens`；Product 已明确 actual_usage
为未知，并另列 reserved_token_ceiling。因此不是 UI 已经把 ceiling 冒充 actual，
但授权派发与保守会计仍耦合。JS 调用次数还受 256 的绝对上限及 monotonic/expiry 限制。

单次研究请求 gate 计量实际 provider body、声明输出、tool payload 和 elapsed，
provider 实际 usage 单独解析；Backend durable admission 防止同请求跨进程重发。
既有 gate 的 180 秒 proxy deadline 不是完整 DSH 回合 watchdog；不能直接宣布 F6 全部限额已具备。
现行 continuation journal 独占创建，失去 Adapter 原会话则 unknown；没有需要维持的旧预算恢复义务。

## 4. 接受前切片的修改、测试和剩余门禁

应用源码仅修正 `services/runtime-adapter/app/research_request_gate.py` 的真实用量类型检查，
并在对应 test 添加反例：bool/负数不是真实用量，nested cache 的 bool 也 unknown，合法 0 保留。
10 个新增案例在原实现失败；修正后与选中的现有纯合同测试合计 **20 passed /6 deselected**。
Node 现行 continuation guard 文件测试 PASS。未启动真实模型、proxy 网络测试、数据库测试或全仓回归。
这些测试仅证明当前组件合同及该 parser 修复，不证明新的 profile、权限切换或 F6 真实接续通过。

独立 Tester 的 observer 故障验证和独立 Reviewer/Root 限定验收已完成，见第 6 节；不计真实 F6 PASS。
当前 Phase 17 仍 OPEN；A–D 历史有效证据保留，预算架构与新 profile 尚未实施，F6/E/F 与最终阶段/CI 门禁不省略。


## 5. 失败收尾是后续真实 F6 的必要门禁

当前 `root-closeout.py` 只接受成功观察器结果；只读保活/Root STOP 不等于已验证失败资源自动收尾。
未来 F6 前准备精确 Root 收尾控制/runbook，以下步骤只依据已保存的实际创建回执与 exact GET，
不从 catalog/latest 猜测资源，不为此次暂停机械注入完整失败链：

1. 保存原 error、终态、SSE、所有写入 attempt/receipt 和只读对账；区分 observer、产品、安全/环境、未知动作。
   实际未知的请求保持 UNKNOWN，禁止 POST/Docker 命令重放。
2. 若精确 Signal Worker start 回执证明已启动，核对原 CID/image/scope 后只停该专用 Worker；未启动就记录未执行。
   Job 本身独立存在，不删 Job/Artifact 或将其假置为终态。
3. 对确有创建回执的精确 Task/grant 做 GET；同版本未撤销时，以独占 attempt marker 发送一次现行 revoke 并 GET。
   已撤销直接读回；未知 POST 只查同一版本，不重复写。不清除未决 liability。
4. 对原健康会话核对 Runtime/Domain root 权威状态与请求是否未决；结束保持后关闭测试连接。
   若需要删除专用 Product 会话，先保存证据并证明无活跃请求，独占标记一次 DELETE/GET；保留 Job/Artifact 与对账责任。
   丢失 SDK 会话则记 session_missing，不重建。
5. 仅在13资源身份/镜像/挂载和运行态准确核对后，以现有专用流程将 backend/gateway/runtime-adapter 的 F6 flag 关闭；
   不改变其余服务/volume，不部署。新 generation 计数与旧 usage 分开留存。

上述失败分支控制/合同和实际清理证据尚未完成，**不计 PASS，不据当前离线门禁直接启动 F6**。
本轮 v6 未启动，SDK/active prompts=0，Signal/Data/ML Worker 已停；未新建专用对象可供清理。
当前预算 ADR 未接受也构成 F6 暂停边界。


## 6. 接受前切片的 Tester → 独立 Reviewer → Root 限定验收

- Tester：`/tmp/byq-phase17-280-f6-v6/offline-targeted-tester-report.json`，
  SHA256 `18fd70be9ee70a2d1a8b441bcb1bf8acddd156810b416fc96f421f88c07e19f4`。
  13 组内存/离线故障用例覆盖 poll、task=null/空fragment 保活、新 root/unknown/SSE 拒绝、
  Root 精确 GET/null task/独占写入及 receipt 解析；终态绑定和证据先于 finally 另作静态检查。
  当前源码 focused Python 20 passed/6 deselected、Node guard 文件 1 passed、worktree 检查 PASS。
- 独立 Reviewer：`/tmp/byq-phase17-budget-simplification-20261001/independent-review.json`，
  SHA256 `17ede836811c9604935471de5d0cee5c04fafbc9526cb66fa4ab62d886d098a6`。
  Functional、Tests、Clean Break Architecture PASS，仅限上述现行修复、离线 observer 和 Proposed 设计。
- Root：`/tmp/byq-phase17-budget-simplification-20261001/root-acceptance.json`，
  SHA256 `362dcd41378de19738b225132c4bc9d565a8ef58d9f8988c9669e660bb502217`；逐项核对 Tester/Reviewer 和实际源码、observer/helper 字节一致。
  审计正文后续仅补证据索引与方法名称勘误，预算/验收边界不变。
- `git diff --check`、`dev-check --base bb321a2ad373bf1d298269893f2b0d866d027e23` syntax PASS；
  仅选中受影响组件合同，没有全仓/全环境/模型重跑。当前隔离 Runtime 仍是原 `.280` 镜像，未部署此源码修复。

结论：**当前 bugfix + 离线观察器机制 + 最小方案设计 local PASS**。
ADR-0090 未接受；新 profile/预算合同未实施或实测；失败资源收尾 NOT_RUN；
真实 F6 NOT_RUN，Phase 17 OPEN，最终阶段/hosted CI 门禁仍必要。不得据本记录启动真实 F6。
下一步是维护者明确接受或调整 ADR-0090，之后实施准确授权与单请求限额及失败收尾合同，再验收受影响 F6。


## 7. ADR-0090 接受后的实施切片（尚未验收）

维护者明确接受了持久授权与单请求限额分离；不需要再次确认同一架构决策。
Root 维护 `packages/contracts/continuation_request.py`，Backend、Adapter、Frontend
各一个 writer，独立 Tester 只读核对剩余观察器断言；没有第二个会话并行修改这些子系统。
新 grant/reservation 为 v2，usage receipt 单独为 v1。工具名称使用实际
`byq_agent_run_start`、`byq_agent_authorize`、`byq_agent_audit`，领域只允许当前
Task 读取及精确 BacktestTask 读取；DSH 精确 MCP alias 由公开调用前 hook 核验。

`provider_calls` 与 `provider_attempts` 都定义为实际 HTTP attempts，包含重试和压缩，
必须相等；拒绝记录与已准入 attempts 分开。输入 bytes、声明输出和工具 payload
各有单次峰值与累计总量，终态责任记录能够核对两种上限。真实 input/cache/output
仍以 provider 响应为来源，缺失不填安全上限或 0。

Root 用现有 Gateway 镜像、无网络/只读源挂载临时测试容器执行受影响两个测试文件：
**41 passed**。共享合同定向测试 **44 passed**，覆盖不可篡改 profile、单次/累计超限事实、
未知用量和合法 zero 的区分；相关架构边界定向测试 **4 passed / 68 deselected**。这是正在实施切片的组件测试结果，未经本切片完整
Tester/Reviewer/Root 门禁；不代表 Backend/Adapter 整条链或 F6 已通过。

锁定 DSH 二进制 SHA256
`6f68ce88d98307533ee8fa58a8125de4dc019ab16fac8b512cec141a2d1961f8`
的公开 catalog 定义 `tools/pre-execute` waterfall。实际 prepareExecution 先等待该 hook，
拒绝进入 error 结果；仅 allow 且 caller 未取消才进入 dispatch。此源码核验不是动态资格。
必须继续以相同版本、无外部 provider 的样本证明安装及第 17 次真实 dispatch 前拦截。

原 `.280` 栈未更新；F6 v6 未 freeze/run；历史 A–D、v1–v5 和接受前门禁不改写。
完成此切片及观察器/失败资源收尾的定向验证，独立 Reviewer 和 Root 验收后，
才执行受影响 F6。阶段总门禁继续 OPEN，推送、远程合并及部署不在授权内。


### 当前观察器与失败收尾候选

新私有 v7 候选复制历史观察器，v6 原件和旧证据保持不变；没有 freeze/run。
前后台有界等待同时核对回答持久化与 request usage settlement。精确业务责任
从 owner-scoped Product permission 的 `request_state.request_identity` 读取，包含
reservation、run、事件、输入摘要、grant version、dispatch attempts、outcome 和
settlement hash；Root helper 不再查询 SQL，也不把公开“系统能力”当动作身份。

Frontend 新授权只提交固定 profile，展示 Backend 的单次请求限额。未知 POST
后的空 GET 不解除提交锁；只有同一确认 nonce、资产、profile 和 Task 的确切
授权被确认才解除锁定。历史 v1 可读/撤销，不能转换或继续派发。

失败收尾候选保存原 FAIL，先有界只读对账并结束 hold，再清理准确专用资源。
单次 revoke 的 Tester 离线故障注入 **7 cases passed**，覆盖丢失 POST 回执后
GET 确认、已有 marker 仅 GET、空许可不确认、身份/资产/profile 不符拒绝，以及
未知 request usage / unconfirmed responsibility 原样保留；仍是 provisional
组件证据，尚未经整个当前切片独立 Reviewer 与 Root 验收。

### 接受后定向验证与剩余阻塞（2026-10-01）

- Backend 使用新建 internal network 和 tmpfs PostgreSQL 测试库执行受影响合同；没有连接 `.280` 的业务库。合并去重证据为 **82 个 scoped cases 通过**。首次临时库 256 MiB WAL 用尽导致的环境失败原样保留；仅重跑受影响案例，使用 1536 MiB 专用 tmpfs 后完成。并发 poll 的第二读允许 waiting，不要求提前获得第一个线程尚未持久化的 intent；仍证明只有一个 reservation/dispatch。
- 原子 dispatch 后的精确未接受拒绝保留一次已消耗请求身份、attempts 和 liability；禁止重新打开。Gateway 仅认同一会话的三个明确 admission 拒绝详情。身份冲突或其他 409 保持 unknown，不笼统退款或重发。受影响 Gateway 新增/修改 **9 cases passed**，其余此前证据复用。
- Backend 纯 profile 合同 **10 passed**。Frontend permission panel **7 passed**，类型检查通过。历史 v1 仅读取/撤销；新授权仅固定 v2 profile，未知 POST 后空 GET 不能解锁。
- Runtime 首批 **46 passed / 4 failed / 2 deselected** 及后续失败原样保留；只复验受影响案例。当前去重 **59 个 scoped Python cases 通过**（首批 50 个、新增未知 transport 不重放 1 个、业务恢复与长 reservation 8 个），Node guard **8 passed**。实际输出超声明如实记 partial；已修正小型 503 buffered body 的 closed socket 处理及总 deadline。上游断连后拒绝 SDK 后续外发，不重放未知结果。两个固定 `0.1.5rc1` SDK 机制用例均通过真实本地模拟 provider/MCP：各 Agent 的目录仅五个别名，根/子 Agent 共用 dispatch 计数并在第 17 次前阻止；子 Agent 仅测试公开创建 API，生产 profile 仍禁止委派。公开 scoped `agent.ctx.tools.restrict` 在同步创建事件安装；ready fence 表示监听器已安装，不等待延迟至 SDK run 的 Agent 创建。私有 cache noexec、fixture import 位置和重复 wrapper 失败不计为通过。真实外部 provider 与业务库调用为 0，F6 NOT_RUN。
- 新 v7 失败收尾候选增加安全/未知失败的精确 GET 对账；未知读结果阻止后续清理写入。未知请求不重放。已知 healthy-session observer hold 仍使用原有有界握手；新分支的离线资格正在验证。
- 最新只读栈清单：`/tmp/byq-phase17-adr0090-implementation/paused-stack-readonly-20261001-refresh.json`。13 个原服务，SDK active/active prompts 均 0，Signal/Data/ML Worker 均 exited，normalized model counter 仍 24；raw HTTP NOT_OBSERVED。没有新 F6、模型请求、Grant 或 Job。

完整当前切片 Tester、独立 Reviewer、Root 验收尚未完成；上述定向组件证据不能替代实际 F6 接续、阶段最终验收或 hosted CI。

### 最终离线门禁候选边界

私有 v7 将观察器、plan、全部 Root/native/只读 UI helper 字节及完整源码切片纳入同一离线 Tester → Reviewer → Root 门禁。构建后仅由 Root 核对实际镜像、原健康会话、端口、身份和新鲜资源 pins，不重复一轮静态审阅，也不据准备 PASS 宣称 F6 PASS。准备阶段若原 Runtime authority 或完整 usage counter 变化，重建前停止并保留证据；未知 transition 不自动重放。仅四个源码变更服务重建，其他九个资源、五个卷和两个网络保留，复用 98 个交易日缓存。

FG/BG 的回答持久化和 request settlement 采用有界 GET；BG 先核对权威 Job/Artifact 生命周期再解释公开回执。错误证据及 SSE 先 fsync，已确认 observer-only 错误保留原健康连接进行有界只读对账；安全/未知错误精确 GET 对账，未确认读结果阻止清理写入。离线 7 revoke、18 合同反例与 3 延迟等待、收尾/只读对账证据按函数 hash 复用；新增门禁漂移与资源保护反例定向验证，不将重复运行相加。

F6 成功收尾后的独立真实浏览器检查只读取同一 Task 已撤销/花完的 v2 grant，验证 11 个可信限额、实际用量分离、不可再次提交/撤销与刷新；不发送 Agent、模型、Grant 或 Job 操作。该检查仍 NOT_RUN，未知提交锁的故障反例维持离线证据边界。


## 8. ADR-0090 实施门禁及 F6 v7 实际结果（2026-10-01）

本节记录 v7 当时状态；当前实测与修正见第13–14节，前面段落保留其记录时的历史边界。
源码切片在隔离分支本地提交 `cdeeb6dbdc497133d20a4bca87a36a98b511e677`。
PR #380 已纳入，不重复同步。没有推送、远程合并、部署或现有数据库操作。

### 限定离线验收

共享合同、Backend、Adapter、Gateway、Frontend 与私有观察器／失败收尾完成
Tester → 独立 Reviewer → Root 限定离线门禁。私有完整源码快照
`/tmp/byq-phase17-adr0090-source-snapshot-20261001/manifest.json`，SHA256
`d8391774fc05b95d312f136b6cd4768d6acae81851c8f6906ee97fa57a039801`。
计数去重：shared 44、Backend 82 scoped、Gateway 45 scoped、Frontend 7、
Runtime 59 Python、Node 8；Backend 纯 profile 10 的重叠边界保留，不能直接累加。
Frontend 类型检查、31 文件 syntax、diff check 与受影响架构检查通过。
失败样本及环境／fixture 修正原样保留，仅复验受影响案例；没有全仓回归。
这些结果证明组件和离线边界，不证明真实后台接续。

v7 最终离线门禁路径均位于 `/tmp/byq-phase17-adr0090-f6-v7/`：

| 证据 | SHA256 | 范围 |
| --- | --- | --- |
| `tester-offline-gate.json` | `88a9e907205e859b5c5cf0086bdde78455e211a90b04d7c9266ff528611b14f6` | 实施及观察器 offline PASS |
| `reviewer-offline-gate.json` | `67cedf2b68934fb25b8dd3da4259fe385de08d374f83716bd1fcaf8a83bb20df` | 独立限定审查 PASS |
| `root-offline-gate.json` | `c60922c133dd23ffe8372f630e4aa30ea29e36efb2fe1b8def6632571fd23c4d` | Root offline PASS，写入时 F6 NOT_RUN |

构建只涉及 backend/frontend/gateway/runtime-adapter 四项，实际镜像源码与 pin
核对通过；其余九项容器、五个卷、两个网络及 98 个交易日缓存保留。
首次 preflight 的 public_projection 路径错误发生在真实模型调用前，原失败保留；
仅修正工程 helper 路径并完成窄范围门禁补充，没有重新构建整套环境。

### 一次实际执行与失败对账

上述门禁及新鲜 preflight 后，v7 只启动一次。实际 source 为上述提交；
原健康会话 `conversation_632003b85c884ee3881ba9b8dca3a4b1`，
首轮 SDK root `29bb59311e3d46a2ad4bff47317293a9` 已 completed，回答持久化 up_to_date。
新增 **12 次 normalized model calls**；raw provider HTTP **NOT_OBSERVED**。
只有一轮前台输入，未执行第二轮、grant、Signal Worker 或后台接续。

原 `RUN-F6/error.json` 保留 FAIL：观察器要求完整 objective 精确匹配，
实际持久化 objective 缺少末尾的精确读动作审计说明，title 一致。
Task ID 当时尚未赋值，原 error 的 task_id=null 不改写；finally 已关闭 SSE，
因此本轮不具备继续验收原健康会话自动接续的条件，不恢复旧 DSH 会话。

随后通过原会话绑定的非 baseline Task、exact Product GET 与 owner-scoped
结构化 AgentRun audit 有界只读对账，确认：

- 仅一个 Task：`task_0a1214efd13140d6b1c6e92941c88697`。
- Draft：`artifact_9f58ad49de5d49e6be6a48e6706d4cbb`；Version：`artifact_70687acd7e514b84a0957ccd6b854efb`。
- 三项原始动作 task_create／strategy_validate／strategy_version_create 的 action、resource、run、owner/workspace/trace/boot 与实际 audit ID 匹配。
  公开回答的“系统能力”仅展示，不作为权威动作。
- 没有新 SignalJob 或 continuation grant；对账新增模型输入、业务写入、SQL、未知调用重放均为 0。

只读证据 `root-control/first-turn-readonly-diagnostic.json`，SHA256
`ef3ef93d2ce453ce91864e2ab5fb8dc1bdb52e657a041cac3d65e7ec6c2b4123`。
这项事后对账不补写观察器未执行的后续断言，也不升级本轮为 PASS。

### 实际失败收尾及剩余门禁

准确专用会话已删除；Signal/Data/ML Worker 停止；只将 backend/gateway/runtime-adapter
的 F6 开关关闭。同镜像、原挂载和其余十项资源身份／状态保持，五卷两网络保留。
新 Runtime generation SDK active／active_prompts／normalized model calls 均为 0；
旧 generation 的 12 次调用和实际 normalized usage 另行保留，不用新计数覆盖历史消耗。
不删除 Task、Artifact、Job 或数据，不重放未知调用。

`f6-off-final-environment.json` 为 **FAILURE_CLEANED_NOT_F6_PASS**，SHA256
`7c8e009d0a53da48ce58f70d946a9f403efdb8abb9401e3761e181fb8a03a80b`。
v7 60 份文件的清理后哈希清单在 `/tmp/byq-phase17-adr0090-f6-v7-protected-after-cleanup.json`。

下一步集中检查全部剩余断言及失败分类：先记录精确资源身份再检查内容，
已确认无未决副作用的观察错误先保全证据并有界保留连接只读对账；
不得把内容不符降格为 PASS、自动改写业务 objective 或重放本轮。
完成受影响离线 Tester → 独立 Reviewer → Root 后才准备必要的真实 F6。
**F6 scenario FAILED；真实后台接续／只读权限 UI NOT_RUN；Phase 17 OPEN。**
A–D 适用证据继续复用；E/F／最终 Golden、hosted CI 与仓库门禁仍必需。


## 9. F6 v8 限定门禁、实际观察器失败与收尾（2026-10-01）

本节记录 v8 收口时状态；最新 v9 实测及门禁见第 10 节。历史失败及门禁不改写。
产品实现仍为 `cdeeb6dbdc497133d20a4bca87a36a98b511e677`；实际工程 HEAD 为
`4bbf6737b3f8c6dd50b21e7b5acd8bcf62d990d1`，其差异只有证据文档。

### 集中离线核对与实测前门禁

v8 一次性核对余下断言：完整 objective 不缩短；Task 身份先保存；全部
runtime binding/逐项 authorize/result 按权威审计核对；准确 BacktestTask
引用和未执行状态；到期余量；稳定 Job 结果字段；F6-2 仅使用 create 回执。
既有持久化/结算等待、usage 和权限校验按相同函数哈希复用，没有重跑 A–D。
67 个定向动态案例及静态检查通过；静态观察有重叠，不声称 6 个独立案例。
Reviewer/Root 又发现启用与收尾 reload 标记碰撞、pool 路径误用 snapshot ID；
两处一起修正，另有 2 个 mocked Worker guard 案例和 1 个标记静态检查通过。
前面的报告字段遗漏、测试计数勘误与 helper amendment 都保留原版本。

v8 门禁位于 `/tmp/byq-phase17-adr0090-f6-v8/`，写入时仅资格为 offline：

| 证据 | SHA256 | 边界 |
| --- | --- | --- |
| `tester-offline-gate.json` | `4650b4e82f399e19db6d0857aa3cda447d01f045158f3a2f9e81720ae3096248` | 限定实现/观察器及定向补充 |
| `reviewer-offline-gate.json` | `9eb4b7e762f6ad69a9319588ae928553f00a6f4e29fdbb3b647c5019a01a69c4` | 独立审查 |
| `root-offline-gate.json` | `6b156287146860c11ee0522b256bab856bbfcdfd58fc5fede938380e3b1bc868` | Root offline；F6 NOT_RUN |

完整 admission 通过，绑定 41 个源码文件、16 个 helper、静态输入合同和 profile/限额。
实测前只读确认测试 runner/SDK active/prompts/runnable Jobs 为 0。
只以原镜像切换 backend/gateway/runtime-adapter 三个 F6 开关服务；
没有 build/pull/下载，其他十项资源、五卷两网络和 98 日缓存保留。
新鲜 preflight SHA256 `0e46da0a54833b4a72427e9c8ae2292846a11a583d855f9bd76e17068e046e2f`；
frozen-plan SHA256 `c01e5ffcbc6aeca4d3072c9ac715d0b85beff04c943197d4322a3d3bb7b63959`。

### 一次实际 F6 与错误合同分类

仅运行一次 v8。会话 `conversation_994cf11a867347ddb39c21e406079f0d`，
首轮 SDK root `d15ccddec0e64741b2461aaa6ce3d177` completed；完整 title/objective
精确匹配、回答持久化及三项完整权威审计通过。
Task `task_bbe20e59c62448cc857b1996ccb37301`，StrategyVersion
`artifact_d159f39a763347b48e879c692aad1902`；Root 阅读实际源码后精确审批。
唯一 v2 grant POST201/GET200 一致：确认资产/hash/profile/11 个限额/身份正确，
requests_reserved=0、remaining=1、unconfirmed=0、usage/identity=null。
这证明授权写入与读回，不证明后台请求的限额/usage 实测。

随后观察器对 execution-plan GET 要求 Backend `body.detail`，但当前 Gateway
规范化为 Product `body.error.code/message/request_id`；因此在第二轮前停止。
原 `RUN-F6/error.json` **FAIL 保留**，没有 SignalJob、Worker start、F6-2 或 BG。
新增 **12 normalized model calls**，raw provider HTTP **NOT_OBSERVED**。
精确只读诊断得到 HTTP404、code=`product_domain_rejected`、
message=`research execution plan not found`，确认未隐式创建 plan。
诊断 SHA256 `c505a7bc37f0e2bc385b565479a8190fb13b961d40e0f82ac64eec1585fc6a60`。
这是观察器合同错误；不能以诊断将原 F6 失败升级为 PASS。

独立审查对所有 Product fault/detail 路径集中扫描，仅此处存在同类错层。
报告 `/tmp/byq-phase17-adr0090-f6-v8-product-envelope-independent-review-20261001/review.json`，
SHA256 `a12f2bf1433bce1c7297bfd5c27ff61b38b96973a6a1cf2752f4abafaf841aa1`。

### 精确收尾及下一步边界

有界 GET 对账 STOP_NOT_PASS、unresolved=[]；准确 grant_version1 已撤销并读回。
Worker 未启动；只删除专用 session，保留 Task/Artifact/责任记录。
三个 F6 开关已关闭；镜像、挂载、其余十资源、五卷两网络保持。
旧 generation 的 12 次 normalized 调用保留；新 SDK/prompts/model counter 都为 0。
`f6-off-final-environment.json` 为 **FAILURE_CLEANED_NOT_F6_PASS**，SHA256
`76316ebfac9aad623c883468fc8a5a2d970cdc3e4f6de9b3437bf35c28a84a66`。
86 份文件冻结于 `/tmp/byq-phase17-adr0090-f6-v8-protected-after-cleanup.json`，
SHA256 `91f33eba7a6cacd516d03aa1e764f82e0a1029919718859854714b5556687563`。
未知调用重放、直接 SQL、市场下载及生产/现有业务库/备份操作为 0。

v9 只有离线观察器候选：精确核 Product404 error.code/message，并在断言前保存原 GET。
没有 inputs、其余 Root helpers、执行门禁、preflight、freeze 或模型调用，不能启动。
纯校验器 7 个动态正反例及 1 个证据顺序静态检查通过；实际 v8 404 为正例，Backend detail、空 404、错误 code/message/status 和 malformed envelope 为反例。
报告 `/tmp/byq-phase17-adr0090-f6-v8-result-test-20261001/v9-execution-plan-validator-results.json`，SHA256 `e9926997241eac0c902b1ff2307ab4c66349265256315b668732a0243eb751f6`。
失败事实、精确收尾与 v9 离线修正完成 Tester → 独立 Reviewer → Root 限定结果门禁。
这项 PASS 只覆盖所述证据/修正/清理，不是完整 F6 或 Phase17 PASS。

| 结果证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-adr0090-f6-v8-result-test-20261001/report.json` | `f8b542e5318130bed9876195e5c184c9c85237f5edd470963131da0891d23505` |
| 同目录 `scope-clarification.json` | `4329d89aeff656357e56100fc62ab5be1edcf68d69fed6ae02db2a4bd8f77459` |
| `/tmp/byq-phase17-adr0090-f6-v9-independent-review-20261001/review.json` | `b6aaf1c2a2e071cb31985c156d6e9a4f77a0040a2e6f862eea1e41b5c39a9482` |
| `/tmp/byq-phase17-adr0090-f6-v8-v9-root-result-acceptance-20261001.json` | `53d95f207d5afa395a5a58dc97b242f1a5a1efe4db4b618dc096561e39fe362d` |

Tester 原报告的 model_inputs=0 指清理新增输入，澄清 sidecar 原样保留；
真实 v8 是 1 次 foreground input、0 次 background input 与 12 次 normalized 调用。
本修正切片不再逐个修断言后重跑整链。
原逻辑会话已删除，不能把 v8 FG1 与另一会话 FG2/BG 拼成 PASS。
未来真实完整 F6 必须新会话及新鲜门禁；阶段验收仍需真实 BG、只读 UI、最终 Golden 与 hosted CI。
**F6 v8 FAIL；F6-2/BG/UI NOT_RUN；清理仅 limited PASS；Phase17 OPEN。**


## 10. F6 v9 完整观察器门禁、内容失败与有界收尾（2026-10-01）

本节记录 v9 历史状态；最新 v10 见第 11 节。产品实现仍为 `cdeeb6dbdc497133d20a4bca87a36a98b511e677`；
本次实际工程 HEAD 为 `29f6165087d697944cc4187ddba6e248e55eabaf`。
没有新增产品源码、镜像构建、行情下载、A–D 重跑或推送/合并/部署。

### 集中观察器修正与离线门禁

补齐全部 v9 inputs、Root/native/UI helpers；Product404 原始 GET 先存证再断言。
独立成功路径审查发现并集中修正两个 helper 缺陷：登录按钮改用当前 `进入`；
成功收尾保留 durable Product conversation，以原镜像的三服务 flag-off 结束空闲
Runtime，并读回同 Task 的已撤销/结算责任。允许原 Runtime 已被 Gateway 自动释放，
或仅剩精确原记录且无 active prompt；新 boot 后不声称旧 Runtime 仍健康。
失败分支仍可精确删除其无未决副作用的专用会话。成功分支和 UI 此次未真实到达。

新增 **21/21 mocked closeout 边界**与 **3 组静态检查**通过；既有 67 个观察器案例、
7 个 Product404 校验及已通过的预算组件/轮询证据按哈希复用，没有重跑。
完整 Tester → 独立 Reviewer → Root 离线门禁绑定 **41 个源码文件、16 个 helpers**、
输入合同、profile 与限额，写入时 `live_F6=NOT_RUN`：

| 离线门禁（v9 目录） | SHA256 |
| --- | --- |
| `tester-offline-gate.json` | `79b4ef0b971938834682cc2d0723d2225f23ce81867e992af6f000fb341c0bdb` |
| `reviewer-offline-gate.json` | `3523a6c334aa4a2293a393bc33aacfef202ec4067c56fbe78ab9daa5357dc262` |
| `root-offline-gate.json` | `28675bf78f74d6fc105c3fc543e292edd1e99172c3522beb4461dee4b67102ef` |

新鲜只读 preflight `7bdb4733eb9bfc06512c6212f7a19adac3a1745643bb7a34752312e0fc22bcb6` 与 frozen plan
`2350487aebdb08bf5d6589eb966bab0b7cdc45ebb62c8e70e0417c7e50c4be6e` 之后，只启动一次新会话 F6。

### 实际 FG1 内容失败与精确诊断

会话 `conversation_b147efbff8324bd79ff03d55e61aa83c`，SDK root
`42b1c34f5d824e31a05c1071659dac64`；Task `task_5d461619fedc4cb18ea9133fc8da3f21`。
Task title 精确一致，但 objective 预期 **2930** 字符，实际 **2457** 字符，为严格前缀，
缺末尾 **473** 字符。完整 runtime binding 与三次逐项 authorize/result，共七项权威
审计通过；Task、strategy draft `artifact_9b446094bfc2412597de053be9158514`、
StrategyVersion `artifact_2ad4eb2db25a4e0c98ec1b2e9269bcbf` 已持久化。

唯一原始 DSH `byq_research_task_create` 参数长度/hash 与 Backend 实际 objective
完全一致；原 compressed/decoded native hashes 已匹配。Backend 上限为 4000 字符，
未截断。本次归类 **模型工具参数遗漏 / PRODUCT_CONTENT_MISMATCH**，不能降级为
观察器错误、缩短预期内容或将不完整 Task 当作 PASS。诊断保存长度/hash/缺失尾句，
不保存原始模型输入；诊断没有新模型调用或业务写。

仅 **1 次 foreground input、12 次 normalized model calls**；raw provider HTTP
**NOT_OBSERVED**。尚无 Root 策略批准、续接 grant POST、SignalJob、Worker start、
第二轮或后台请求。后台请求 profile 限额与真实结算仍未实测。

### 有界连接保留、只读对账与精确清理

先保存失败/已完成根/审计证据，再保留原 SSE 进行 **50 次只读观察、约 50.445 秒**；
session、answer delivery、同 Task GET 均200，1 user/1 assistant、回答持久化一致，
连接仍开放。Root 对这三个精确资源 GET 对账，给出 STOP_NO_REPLAY；观察器核对
停止信号后才进入 finally 关闭连接和浏览器。hold 无已知 Job/grant，不声称这期间
做了不存在的 Job/permission GET。失败后新增 Product write/model call/未知重放为0。

Worker 未启动；无 grant POST。专用失败 session DELETE 后 GET404；保留 Task 与
两个 Artifacts，**原 durable conversation 已删除**。Task 留有 conversation_id/trace
引用，不等于还有可用原会话绑定；后续 permission GET 为原 conversation 缺失的422。
不能从这个失败会话继续 FG2，也不能把另一会话的后台结果拼成 F6 PASS。

仅原镜像 backend/gateway/runtime-adapter 三项 flag-off，镜像/挂载保持，其他十项、
五卷两网络保持；Signal/ML/Data Worker 均 stopped。再度只读确认已知 runner、SDK、
active prompts、新 generation model counter 均0；完整有界 Signal/Backtest/Training/
Prediction 目录非终态为0，Factor/Data 目录未枚举。旧 generation 的12次计数保留。
清理仅为 **FAILURE_CLEANED_NOT_F6_PASS**；v8 86 份、v9 80 份证据字节均保护。

| 结果证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-adr0090-f6-v9/f6-off-final-environment.json` | `b34c578bbbeceba61866ff87693e95ee3a8ccc496aab1f0660ad6667156c7823` |
| `/tmp/byq-phase17-adr0090-f6-v9-objective-diagnosis-20261001/diagnosis.json` | `a9bccf3aea0b3da16c98d0ef3ef8eebf70e60b5ad5aa78dedb2bd8e2e724d641` |
| `/tmp/byq-phase17-adr0090-f6-v9-protected-after-cleanup.json` | `783252e0816e512f74397a5462156811c2c5ec42dc7f42ad80050bae3c538fb4` |
| `/tmp/byq-phase17-adr0090-f6-v9-post-closeout-readonly-state-20261001.json` | `1d0d5396c4c2fc91282d2f6e0867d85892500f6a2be6471a42dec0a3eddca50e` |
| `/tmp/byq-phase17-adr0090-f6-v9-result-test-20261001/report.json` | `0fa352b4fcaaa844d9942b4fbc179a3e535a439368c8784d9175f6a38575fee0` |
| `/tmp/byq-phase17-adr0090-f6-v9-result-test-20261001/scope-clarification.json` | `edcf5d92e3ef553fb7ece4bbef722d2e5ae5ac5cb1a3d3504ab5177888515344` |
| `/tmp/byq-phase17-adr0090-f6-v9-result-independent-review-20261001/review.json` | `b72304f3afefc77c7d52199094bac32e46a7836fb1e9797a32e9f63d90aee634` |
| `/tmp/byq-phase17-adr0090-f6-v9-root-result-acceptance-20261001.json` | `20e4622c4410e21e79848bf388d5f4b7a28184c57f2164acce12b3da408d2d15` |

Tester → 独立 Reviewer → Root 结果验收只证明失败分类、实际有界只读保留与清理。
Tester 原报告关于绑定的布尔字段以独立 scope-clarification 为准，原报告不改写。
**F6 v9 FAIL_FG1_CONTENT_CLEANED；FG2/BG/UI NOT_RUN；Phase17 OPEN。**
下一步先定向改善原值表达/工具参数保真，保持完整 objective、权威审计和安全限额；
不重放未知调用、不直接重跑整链。任何后续完整 F6 仍需新会话、全包门禁与新鲜 pins。
适用 A–D 继续复用；真实 BG/只读 UI、最终 Golden、hosted CI 与仓库门禁仍必需。


## 11. F6 v10 前台通过、Root 观察器失败及离线修正（2026-10-01）

本节记录 v10 当时状态；后续账号检查及同 Job 独立完成见第 12 节。实际执行 HEAD 为 `80530544af6759db09a82fbd58e733415acb0ca4`，
产品实现仍为 `cdeeb6dbdc497133d20a4bca87a36a98b511e677`。
没有产品源码变更、镜像构建、行情下载、A–D 重跑或推送/合并/部署。

### 原值表达修正与一次实测

v10 将完整 Task 静态参数作为独立 JSON，要求从本次可信 context 补入 owner/trace；
不接受自定义 turns 覆盖。除本轮后台幂等键更新外，完整 objective 不缩短、不改写。
新增 26 个动态案例、4 组静态检查通过，既有组件、轮询和成功收尾证据按哈希复用。
Tester → 独立 Reviewer → Root 离线门禁后，重新只读核对资源、按原镜像切换三服务
F6 开关、绑定新鲜 preflight/freeze，只启动一次真实 F6。

| v10 启动门禁（`/tmp/byq-phase17-adr0090-f6-v10/`） | SHA256 |
| --- | --- |
| `tester-offline-gate.json` | `b917bba65e3c1f1cbd8aff0c423339b81fd3ef578591ccfa88c270151e4bdd87` |
| `reviewer-offline-gate.json` | `b63f4611374d2cbf5a9d8af06e759adbabb8be023ed66765adce7c9d3856126d` |
| `root-offline-gate.json` | `ccb0deea34733f949d2063da0001c73adf8cf484beb5a0ac039daabf4b627a4d` |
| `root-preflight.json` | `69fa7b041c5caee0a5a4b018479d885ee82511c6ac388b73d17f4496c3298fef` |
| `frozen-plan.json` | `592b1adab3ac8492108c82b47e259b653e8c82828a4fa466235e356cb969df19` |

原会话 `conversation_859dd3dc325042c7896badc256fe0a7f`，Task
`task_e93f82e2092c442c9b37f0988dd3e8a9`。FG1 的 title 与完整 **2931 字符**
objective 精确持久化，三项领域动作及完整七项权威审计通过。Root 阅读实际策略后
精确批准 `artifact_7137368813ac468cb04c1d21fd29361b`，批准 Artifact 为
`artifact_fef76c6c6b3649acbf0da0ea8c8dc8e6`；浏览器仅创建并读回一个 v2 grant。
FG2 的 prepare/create 两项领域动作及完整五项权威审计通过，创建唯一
`signaljob_23a2bd73b82d4df98103105f120d314a`，状态 `waiting_for_data`、attempt 0。
该 Job 的 Task/StrategyVersion/Pool 及原会话/trace 精确匹配；没有执行回测。

原 Runtime 的接续资格已核对、无活跃 prompt，但 Worker 尚未启动。Root readiness
只读 POST 使用 ISO 日期，实际 Gateway 返回 **422 / `start_date must use YYYYMMDD`**。
同范围规范日期的只读 POST 随后返回 **200 / usable / 98 sessions / missing 0**。
这证明 Root 观察器请求格式错配；缓存没有本次所指缺口。Worker attempt marker 与
PASS 信号均不存在，未绕过门禁或原地改动冻结 helper。

### 有界等待、对账与遗留项

原浏览器/SSE 在既有 Root 暂停中继续有界只读检查回答和会话，直到信号期限结束；
原错误 `ROOT_SIGNAL_TIMEOUT` 与默认 `SAFETY_OR_UNKNOWN` 字段保留。
独立因果 sidecar 将实际原因明确为 **Root 观察器 readiness 日期合同错误**，
不把原失败改成 PASS。此次是 **2 次 foreground input、21 次 normalized model calls**；
raw provider HTTP **NOT_OBSERVED**。后台 reservation 为 0、usage 为 null；
不能把未发起请求解释成结算完成，也不以两轮前台计数证明后台请求限额。

停止后 session、delivery、Task、permission、Job 的五项精确只读 GET 均200，
无未决读结果或未知写结果。只撤销一个精确 grant 并 GET 确认；Worker 始终未启动。
专用失败会话 DELETE 后 GET404；只以原镜像关闭 backend/gateway/runtime-adapter
三项 F6 开关，其他十资源、五卷两网络保持。新 Runtime active/prompt/model counter
均0；无遗留已知测试进程。Task 留有引用，但原 conversation 已删除，后续 permission
GET 为原绑定不可用的422，不能声称旧会话可接续。

**业务任务未全部清空**：owner 可见完整 SignalJob 目录有四项，本次 Job 等待，
三项历史 Job 完成。没有取消、删除或重建本次 Job。普通 Signal Worker 全局扫描，
且缺数据时可能创建 data repair；当前 owner 目录不是全局排他证明。
不得据本节直接启动 Worker、创建替代 Job 或启动新的 F6。
自动审批拒绝了全量用户目录读取，原因是超出测试授权、涉及用户数据；读取未执行。
专用隔离栈的限定账号标识/状态只读检查当时待维护者答复；后续明确授权与执行见第 12 节。

### 一次集中离线修正与限定验收

独立审查核对剩余 Worker、事件身份、后台持久化/结算、撤销与成功收尾合同，
未发现第二个已确定字段错配；真实后续路径仍未运行。Root 在独立候选中完成三处修正：
仅对 readiness 请求转换日期、断言前保存实际响应、存在其他可见非终态 Job 时拒绝
启动 Worker。冻结 v10 原件保持不变。可审查差异见
[Worker readiness 修正](evidence/phase17-f6-worker-readiness.patch)，SHA256
`3178c2c661d4a00ebc5f59c4dc772a7fe3fe44eabd840eaac8e9935b63802de3`。
候选 `/tmp/byq-phase17-f6-v10-observer-repair-20261001/root-control.py`，SHA256
`e3974f9d812d20e7f4a568a1e8151165e232d91e8ec22809b6af196a5e621314`，仅离线验收。

Tester 调用实际完整 `start_worker`，mock 外部依赖，**12/12 定向案例通过**：
规范98日成功与写入顺序、其他可见 Job 非终态拒绝、422/错范围/缺数据/异源拒绝并先存证、
pool/Job 漂移、授权余量不足300秒、Worker启动结果未知时保留单次 marker 且不重试。
首轮一个 fixture 目录权限错误保留，修正 fixture 后通过；没有真实 Product、Docker、
DB 或模型调用。这些案例不证明全局队列排他或真实 Worker/后台行为。

| 限定结果证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-f6-v10-readiness-tester-20261001/readiness-start-worker-report-v2.json` | `4ec16d4f3814ce21f38925b9cf788f73eb0bd4091227251e88060fc3781134b9` |
| `/tmp/byq-phase17-f6-v10-readiness-review-20261001/limited-result-and-repair-acceptance.json` | `06d40de147f732a21d9018e9b626639fadf954780913750f9f3cdf89c5aa1011` |
| `/tmp/byq-phase17-f6-v10-root-result-acceptance-20261001.json` | `fc4ae9dedecf992a2be23a741214743be4f6a0818b6381107f27c01ac06bb9bf` |
| `/tmp/byq-phase17-f6-v10-root-failure-classification-20261001.json` | `a60b01919bc62770019ba169d3e377c943b23d5e866799858a1ef0a7e40f0865` |
| `/tmp/byq-phase17-f6-v10-post-closeout-readonly-state-20261001.json` | `820dd73cf5b7a5d71009075482b8eb4bd7995972e545a078845ffbbbb72c6c93` |
| `/tmp/byq-phase17-adr0090-f6-v10/f6-off-final-environment.json` | `de17d4351abb8bf7352260c549f843674cf123ba19ad5fed512f776f8042721e` |
| `/tmp/byq-phase17-adr0090-f6-native-v10/RUN-F6/native-safe-evidence.json` | `3dd1d6f03240951e48287d534f9329870590ebc3e7157f1dd9b3d65e637ec6e6` |
| `/tmp/byq-phase17-adr0090-f6-v10-protected-after-closeout.json` | `05b0078775499d2ec539de62c1966fdc622b72097b916c24561d254d80fe981e` |

v10 96份、v9 80份、v8 86份私有证据字节已保护。Tester → 独立 Reviewer → Root
仅验收实际失败事实、已执行收尾和离线修正。**F6 v10 FAIL；FG1/FG2 同会话证据通过；
Worker/BG/后台限额与结算/成功只读 UI NOT_RUN；一个已知等待 Job 保留；Phase17 OPEN。**
下一步先确认全局 Worker 安全范围，处理同一遗留 Job，再完成新候选全包门禁与模型调用前
的精确只读 readiness 检查。只有这些门禁满足后才运行受影响 F6；适用 A–D 继续复用，
不拼接会话、不重放未知调用，最终 Golden/hosted CI 与仓库门禁仍必要。


## 12. 限定账号检查与同一 Job 独立完成（2026-10-01）

维护者明确允许只读检查专用隔离测试栈账号目录。执行 HEAD 为
`397b881e6d28767c73eaf733c85011e7cd5e835c`，产品源码、镜像和98日缓存保持。
精确核对13资源、loopback Product origin 和三个 F6 开关关闭后，读取
`GET /api/product/admin/users`；完整无分页目录只有 **1 个 active admin**，
仅保存账号数量、标识和状态，没有保存原目录或凭据、修改账号、操作正式或原有数据库。
刷新完整 owner SignalJob 目录：本次 Job 等待、三个历史 Job 完成；精确缓存查询仍为
usable98/missing0，原失败会话404、permission422。账号读取授权缺口已解除。

Tester 只读事实复核、独立 Reviewer 与 Root 将该新建隔离库的来源证据、仅 admin 的
完整目录、完整四 Job 目录及无并发 writer 条件一起核对。限定结论仅适用于这套
fresh schema/market-only import/受支持 API 写入历史，不是一般数据库全局 SQL 行数证明；
Worker 的全局扫描实现未改动。根据信号 Job 独立于 Agent 的现行边界，沿用既有隔离栈
Worker 操作授权，紧邻启动重新检查账号/Job/策略与池引用/98日缓存/资源状态。
保留三个 F6 开关关闭、Data/ML Worker 停止及 SDK/prompts/model counter0。

Root 先保存只读 precheck 与独占 start marker，仅执行一次 **Docker CLI start**，
有界 GET 同一个 Job。实际8次观察为 waiting→running→completed，未要求观察到瞬时 queued；
同一 `signaljob_23a2bd73b82d4df98103105f120d314a` 以 **attempt1** 完成。
完成后立即保存 stop marker 并执行一次 Docker CLI stop，Worker 现为 exited。
生成 **validated signal_snapshot** `artifact_6914ff6a40a640d6b883d397f59018e0`，
内容 SHA256 `ac8fcc75e56468faa6c673214ce87060922feeb8cc0adbff239c8efb152e9988`；
Artifact 的 Task/Workspace/trace/StrategyVersion/PoolSnapshot/Job lineage 精确对应原任务。
三个历史 Job 逐字段未变，当前完整 owner 目录四项均 completed。没有新建 Job、Agent
会话或输入，没有重新批准或授予旧 Task，也没有恢复原 DSH/Product 会话。

本次完整启动区间的日志显示仅目标98bars提升、promoted1、同 Job/Artifact完成，
无 waiting/missing/error 分支；结合 ready 条件与当前源码，限定认定**本次 Worker
已观察路径未创建 repair 请求**。未枚举全局 repair 表，不声称其为空。
原报告的 `worker_start_posts:1` 字段实际单位是 Docker CLI start，不是 Product/Job POST；
Tester 单独保存澄清，不改原报告。原始日志未另存；其三条安全投影按 LF 重建得到完整
472bytes，SHA256 精确匹配捕获的全片段 `9c0633c54e24e2ff8b1bd7ffcd5f5fabb30ed8d3ed48be9e86fe060c5283cc6e`，
后续 Root 离线重建证明不改写早先 Tester/Reviewer 关于未重算原始日志的记录。

| 结果证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-isolated-account-readonly-20261001/account-directory-readonly.json` | `2cd9581fdf5bafd9851217afb2db94d994fc554f39e19d2b36e744447fdf6f10` |
| `/tmp/byq-phase17-isolated-account-readonly-20261001/existing-job-worker-result.json` | `d6e06c75a44277eca953f51a3524adae43e7d9566d69b825d3b2bc6bf1cee13f` |
| `/tmp/byq-phase17-isolated-account-test-20261001/existing-job-worker-result-tester.json` | `5699828acf24dec580adba78fd75e03795cf88c90b2770458c358b31022a7dee` |
| `/tmp/byq-phase17-isolated-account-test-20261001/existing-job-worker-result-scope-clarification.json` | `7bd17e2909d41b24250d08a3373d4ec6f1f1074913da3572ab337456388d2be2` |
| `/tmp/byq-phase17-isolated-account-review-20261001/actual-existing-job-result-acceptance.json` | `bdd531dc0a9d06289aaaf9862d201bf0d49670d0d801089dfbc52a2332d11408` |
| `/tmp/byq-phase17-isolated-account-readonly-20261001/root-account-and-existing-job-acceptance.json` | `b280fcd03cdc49eacf376b28985cf6c821663e9b57669407189ab2033c3ff7f3` |
| `/tmp/byq-phase17-isolated-account-readonly-20261001/post-worker-resource-check.json` | `675e652f58ba9c8de7f7699a8df9ca3767d460b4a0b663d7b437882c05b86fdc` |
| `/tmp/byq-phase17-isolated-account-readonly-20261001/worker-log-segment-reconstruction.json` | `42318fcfcf8b58a161ff149391562c695de2959825662f4f91d26e6d814707d3` |

Tester 的11项证据一致性检查、独立 Reviewer 与 Root 限定结果验收通过；没有重跑
已通过测试套件或A–D。13资源身份/镜像/挂载保持，三个 F6 开关为0，Signal/Data/ML Worker
停止、无已知测试进程，当前 SDK/prompts/normalized model counter均0，96份原v10证据未变。
**通过范围仅账号检查、同一业务 Job 完成与 Artifact 持久化；原 F6 v10 FAIL 保留，
BG/请求限额与结算/成功 UI NOT_RUN，Phase17 OPEN。**
下一步准备完整修正后的观察器与模型调用前的新鲜只读门禁，再执行受影响 F6；本切片
没有新 F6、行情下载、整套环境重建、推送/远程合并/部署，最终 Golden/hosted CI 仍必要。


## 13. F6 v11 后台真实接续与失败收尾（2026-10-01）

执行 HEAD 为 `d477cf2a96c659a2527031f23b6c034aafe71316`；应用源码仍为
`cdeeb6dbdc497133d20a4bca87a36a98b511e677`，沿用相同隔离栈、镜像与98交易日缓存。
不重复 A–D、行情下载或整套环境重建。Root 是观察器唯一 writer。

### 一次性离线准备及真实执行

v11 一次性核对剩余路径，补齐 canonical YYYYMMDD、`use_case=backtest`、
required/ready98、missing0/calendar complete、精确唯一 admin 和完整 owner SignalJob
目录合同。模型调用前及 Worker 启动前均刷新只读条件。队列安全范围沿用第12节的
fresh schema/market-only import/受支持写入历史/无并发 writer 限定证据，不能扩大为
一般生产库的全局 SQL 证明。Tester **50 个唯一动态用例与3项静态检查**通过，
独立 Reviewer → Root 完成全包门禁；13/16 helper 经字节归一证明复用，
只变更 plan、Root preparation 与 control，未重复组件套件。可审查的准备差异见
[观察器准入修正](evidence/phase17-f6-observer-admission.patch)。

只执行一次新 F6：FG1 完整2931字符 objective 持久化并通过精确结构化审计；
Root 精确策略审批及一次 grant 后，FG2 在同一原会话创建唯一 waiting SignalJob，
审计通过。Root 核对原健康 Runtime、授权与队列后只启动一次 Signal Worker。

- 原会话：`conversation_ae32ba863af4457499c157dc4a9d185d`。
- Task：`task_d31ce8a8bcc14277838735b6c8a70d38`。
- Job：`signaljob_16390f1b069c4cf5801168b16af22837`，attempt1 completed。
- validated SignalSnapshot：`artifact_31b85eea8ffb4a7992a5366d8782cbd5`。
- 原健康会话自动后台 run：`b8e4e7bcfda5450e8a291f77b3f19af5`；
  reservation：`continuation_11a22041ac85403e95c6c3a41476b285`。

BG 的两个精确读动作由 Root/Agent 权威审计共同确认。**25次有界只读采样**确认
回答持久化、同一 reservation settled/completed，满足条件立即结束。
reserved1/remaining0/unconfirmed0，dispatch_attempts1；event/run/Job/Artifact lineage 一致。
这是本次原健康会话真实自动接续，不是恢复已失效 DSH 会话，也不是新会话查询。

### 安全限额与实际消耗

单次 `task-ready-read.v1` 请求使用自己的固定限额，不从历史累计预算取余额：
模型 calls/attempts16、并发1；单次/累计输入262144/4194304 bytes；单次/累计
声明输出8192/131072 tokens；单次/累计工具数据65536/1048576 bytes，工具调用16；
hard deadline180000ms。profile hash 为
`44d3e7dbb552363760516d8e5d8e0992e5ae591680badbaec8ee242485bc5df2`。

| 实际 BG 请求记录 | 数值 |
| --- | --- |
| provider attempts/calls；工具调用 | 8；7 |
| 耗时 | 17267ms |
| 累计输入；最大单次输入 | 312852；50459 bytes |
| 累计工具数据；最大单次工具数据 | 88895；17495 bytes |
| 累计声明输出上限 | 65536 tokens（不是实际输出） |
| 实际 provider input/output/cache-read | 77090 / 3639 / 66048 tokens |
| usage/source/completeness | provider_response / known |
| limit violations | `[]` |

本轮原 Adapter 进程 normalized model counter 为30、3个 SDK roots；它不是仅 BG
的8次请求，也不是全部 raw provider HTTP 数。Raw HTTP 仍 **NOT_OBSERVED**。
关闭开关后的新 Runtime counters 为0，不代表本轮未调用模型。

### Root 收尾观察器失败及精确清理

保存 stop attempt 后，`subprocess.run(check=True)` 成功返回，随后 stdout 必须等于
完整 CID 的观察器断言失败。原 stdout **未保存**；后来只读 inspect 确认精确 Worker
已 exited。CLI help 的 `--time` 弃用提示不证明原输出或确切失败原因。

Root 先保存错误、只读核对 stopped Worker、已结算请求与原健康会话，并有界保留连接。
原 Runner 随后在 `Root-revocation-pause` 产生 `ROOT_SIGNAL_TIMEOUT`。经独立限定
审查的 suffix 在执行时重新发现该错误，**在新 revoke marker/POST 之前 NO_GO**；
没有重复 stop、模型或 Job，不伪造 Root success signal，不恢复原会话。

后续独立失败流程只做精确只读对账、一次 grant revoke POST200及GET确认，保留
settled责任和usage；专用会话删除后 GET404确认不存在（未保存 DELETE HTTP status，
不宣称 DELETE 返回404）。仅三服务同镜像关闭开关，其余10资源、5卷和2网络保持；
Signal/Data/ML Worker 均停止，新 Runtime active/prompts/model counters 均0。
最新只读核对完整 owner 目录 **5个 SignalJob 均 completed**、唯一 admin、无测试
runner；原 conversation GET404，精确 permission GET422（original bound conversation
absent）。按当前合同，不能从该已删原会话补成功 UI，也不为测试改架构或恢复会话。

### Tester → 独立 Reviewer → Root 限定结果

| 私有证据（相对 `/tmp/byq-phase17-adr0090-f6-v11/`，另列绝对路径） | SHA256 |
| --- | --- |
| `offline-candidate-manifest.json` | `612241a5de95e153253ab8fd400612964fd50d52f2c7245a9ab3d8fa8f48a80b` |
| `tester-offline-gate.json` | `3f427f1eedb0900faaa190436789d681223e36efefccafdfe59e4cda12fabc0f` |
| `reviewer-offline-gate.json` | `de95bcf38a8ac80cd1f6be96cb9fd6d4bd58385ecdb248960e002ba8e9d416d2` |
| `root-offline-gate.json` | `0c30b61e9c1135d8d0f2aca5a675af291cb6415aae94bbd1b736aabcb870fb8d` |
| `frozen-plan.json` | `3bf96e873fe64da9ee2493026d1dd8668eb724e9c64f3aa2bc7f33f568f32b35` |
| `RUN-F6/background-persistence-settlement-poll.json` | `6ea121143791b59ca5ac982e05b1500158fb734f1d0f38b0321a67d94daec0da` |
| `root-control/ready-event-settlement-proof.json` | `885f6978cfee09136d06da9cd74e65723f514fcbf4c2af99a88c63dcbbc23b30` |
| `RUN-F6/error.json` | `a91c8a954c68393f958e9bdf56c4a4b4c4249bedd1ffbb52a36f70ba12d3c4ff` |
| `f6-off-final-environment.json` | `ba6ed8fd78b42ae81b89ad0ae03408e2dfa55b9cab7ce7c84e20f7dbbe8caa4c` |
| `/tmp/byq-phase17-v11-observer-tester-20261001/actual-v11-f6-and-cleanup-evidence-review.json` | `b16075a760123215253cc1f3e48651cea60cdc7c3a3be67c28c714761283584f` |
| `/tmp/byq-phase17-f6-v11-result-independent-review-20261001/review.json` | `bdb3b8a5ab33274c66831c54d292117062c4540113d12e0c92616ef4b6641989` |
| `root-actual-result-acceptance.json` | `f5d691b7f1a45fef9b3ef152cbb82283fb5fff1324c9259e9a432a1886476703` |
| `/tmp/byq-phase17-adr0090-f6-v11-protected-after-closeout.json` | `10268a6f6f51fb0f758915ad94d3a9c7f2616f2626667c0967145e7d4c68b121` |
| `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/post-closeout-readonly-state.json` | `3e92a49c419953d2f6ab46429012517e04be095613004420009d501b2c5e249b` |

128份 v11/native/门禁文件及原 v10 96份证据字节均核对保护，旧失败不改写。
**FG1/FG2/BG、独立请求限额与持久化结算实测 PASS；完整 v11 F6 仍 FAIL，
成功 UI NOT_RUN，Phase17 OPEN。** Native delta PASS 只证明具名 native 计数事实。
Tester、独立 Reviewer 与 Root 的限定 PASS 验收实际事实和失败收尾，不能替代完整 F6。

## 14. Root CLI 观察器窄修正（2026-10-01）

独立候选在 `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/`；冻结 v11 原件不变。
只修改 Root 工程观察器的 `start_worker`、`revoke_and_stop`，增加一个仅支持精确
start/stop 的 helper；没有产品源码、预算平台、恢复协调器或第二套 Harness 变更。
可审查修正见 [CLI 观察器差异](evidence/phase17-f6-worker-cli-observer.patch)。

仓库中的两份 diff 附件使用零上下文表示，避免把统一差异的空白上下文作为新文件空白
问题；私有已验收原始 patch 保持不变。离线逐hunk重建3对source/target，精确生成
相同已验收helper字节。表示等价证明在
`/tmp/byq-phase17-v11-document-candidate/zero-context-presentation-proof.json`。
本地 `2415676a` 的 staged空白检查失败原样保留；后续修正只改附件表示，未改应用或
helper，不重新运行模型、Job或已通过套件。

独占 attempt marker 先于唯一命令；stop 使用 `--timeout 0`。实际返回码、stdout、
stderr或timeout部分输出先fsync存证，再记录精确 CID/image/mount/state 的只读 inspect。
stdout不作为状态权威。非零/timeout/inspect失败或pin漂移均在成功信号或 revoke POST
前停止；即使 inspect显示预期状态，也不把未知命令改判成功，不重复执行。

Tester **13个实际函数 mocked 动态用例 + 1项调用点静态检查**通过，独立 Reviewer
与 Root **限定 offline PASS**。这些检查没有实际 Docker/模型/Product/SQL调用；
新 helper **真实 CLI NOT_RUN**，不能提升完整 v11 F6 或 UI 状态。

| 修正门禁证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/root-control.py` | `ffcfa26fdfbd4d44f89df6b9f4c20dd20a4558c5f840d82814ea929840608475` |
| `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/worker-cli-observer.patch` | `76c1866c5937bbec4086b3b38fb2f6dddc712fbd5415732479a9d162e31329fd` |
| `/tmp/byq-phase17-v11-cli-observer-tester-20261001/report.json` | `afe173384882f67871c3f201b36aeadbe9da80529a358ddc7e538d65466f570f` |
| `/tmp/byq-phase17-v11-cli-observer-review-20261001/review.json` | `487c06308ba9521859b4b96c9faf9d5a90ff99022a72cc07e41b0e2c3f1ba5d5` |
| `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/root-offline-repair-acceptance.json` | `1f8f71ab47640487340330bdb21009c56bd0ef9874eb3ef99737655d9c47ce26` |

### 独立空队列 CLI 控制实测

完成上述 offline Tester → Reviewer → Root 门禁后，Root 即时再次核对 flags0、唯一
admin、五项 completed Job、精确资源及 Runtime0，保存新 Root admission；仅做一个
新的空队列 Signal Worker start→stop。它是新控制周期，不重放原 v11 stop，也不发
Agent/模型/Grant/Job 操作。独占 marker、实际输出、状态读回均另存新目录。

实际 start/stop **各一次 returncode0**；实际 stdout 均为完整 pinned CID，stderr为空。
使用 `--timeout 0` 的本次成功结果不反推原 v11 未保存 stdout 的内容或失败原因。
精确同一 CID/image/mount 状态为 running→exited；前后五个 completed owner Job
逐对象完全相同，Runtime对象及模型计数0完全相同，三个 Worker 停止、flags0。

Tester仅依据原8份JSON确认 CLI/队列/Runtime，明确未覆盖完整资源/卷/网附件。
Root另只读补存13资源、5卷和2网络的完整 before/after清单，独立 Reviewer逐对象
核对保持。原 Tester 范围声明不改写。独立 Reviewer → Root **实际空队列控制限定
PASS**；它不是带 Job 的 Worker资格、后台接续、成功UI或完整F6重验。

| 实际控制结果证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/REAL-EMPTY-WORKER-CLI/result.json` | `6336ceb021723e48ea64fdf70f350e3e1efce1fe1d42ee149294ec35c64e0361` |
| `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/actual-cli-resource-preservation-readonly.json` | `5984c7e424f508a73deb2164a5d2a64ed61f5676abc43cef45e0937fefe4be55` |
| `/tmp/byq-phase17-v11-cli-observer-tester-20261001/actual-empty-worker-cli-result.json` | `41cd632e42a513c35549a41c8f99f09e01de7bb6fa94d9bfc4bb13487398d331` |
| `/tmp/byq-phase17-v11-cli-observer-review-20261001/actual-empty-worker-cli-acceptance.json` | `229a0da220c842e5dd1819e282b3aa7ffce61a3637ab172c7b9795e57164b402` |
| `/tmp/byq-phase17-f6-v11-closeout-repair-20261001/root-actual-empty-worker-cli-acceptance.json` | `666b2de8a74117bb778a46a5a627ff94f2d088128706fc5cdef1183b25f6975d` |

本轮受影响的 F6 只跑一次；没有再次跑整条模型链或重复 A–D。剩余验收需要先明确
成功 UI/原健康收尾的最小实测方案和最终 Golden 条件；新请求仍需新鲜完整准入，
旧调用/事件/会话不得重放或恢复。最终阶段与 hosted CI 门禁继续保留。
没有推送、远程合并、部署或正式/原有数据库、用户数据、备份操作。

## 15. F6 v12 合法 Task 授权与冻结观察器失败（2026-10-01）

在 v11 成功收尾/UI 的限定补验方案上，先完成 Tester 的 21 项定向动态用例与
1 项静态检查、独立 Reviewer、Root offline 门禁；45 个完整变更文件、16 个 helper
与输入合同被精确绑定。成功 closeout 和 UI 的用例仅是 mock/VM，不代表真实通过。
新鲜只读准入确认唯一专用 admin、原 98 交易日缓存、五个终态 SignalJob、无未决
Runtime/测试，再仅用原镜像切换三项开关，冻结并启动一次 v12。未重跑 A–D/组件，
未下载行情、重建镜像或重放旧调用。

FG1 实际创建一个新 Task 和两个 task-bound validated Strategy Artifacts；完整目标
2931 字符、策略源码和返回资源均已持久化。`byq_strategy_validate` 的授权记录为
`research_task / 本轮精确 Task`。当前 Backend 允许该可选资源绑定；但冻结的 Root
helper 与 Runner 均把此处写死为空，Root 审计门禁停止。三个成功动作与 run/owner/
actor/workspace、结果资源仍精确；这是观察器假设偏差，不能将冻结的 v12 改判通过。

Root 先另存完整权威审计；原健康 SSE 仍保持时，以最多 60 秒只读对账确认回答
`up_to_date`、逐片段已持久化、两个 validated Artifacts、无 grant、新 SignalJob、
未决 prompt 或未知写入。满足条件立即结束对账。然后写真实 `STOP_NOT_PASS` 的
负向通知，绑定 candidate/失败证据；它不是 accepted audit proof，不伪造 PASS。
原 Runner 按既有信号拒绝条件生成 `F6-1 / ASSERTION_FAILED / Root signal schema/status
mismatch`，保存原 error/SSE；这是负向通知造成的 Runner 错误，根因保存在权威证据。

本轮 normalized Runtime model-call delta **12**，raw provider HTTP **NOT_OBSERVED**。
没有 FG2、grant、SignalJob、BG 或成功 UI。随后 exact failure reconciliation 无未决
读，Worker 已停止、无 grant 可撤销；只清理本轮专用失败会话并同镜像归零三项开关。
三项开关服务的 CID 随同镜像重建而更新；其余10项资源的 CID/状态不变，
13 项镜像/挂载、5 卷、2 网络保持，新 Runtime sessions/prompts/model counter0；新计数不
抹去前述12次调用。只读记录里的 mutations0 仅指后续对账/控制，不抹去 FG1 的
Task/两个 Artifact 写入，也不抹去失败收尾专用会话 DELETE。

Tester → independent Reviewer → Root **仅接受失败事实及安全收尾**；完整 v12 F6
仍 **FAIL**，FG2/BG/UI **NOT_RUN**。原68件证据封存，旧 v10/v11 封存哈希保持。
旧 Task、事件、会话、结果或用量不能移作新实测证据。

| v12 原始/限定验收证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-adr0090-f6-v12/frozen-plan.json` | `d26966342045a069273fd75c482146dd323796dab2437f6494d9b4c7df893fb4` |
| `/tmp/byq-phase17-adr0090-f6-v12/root-control/audit-f6-1-failure-readonly.json` | `231701d9d1aa2f0f48746c9061b080b23a10f5de2eb18563c141d91392bde93d` |
| `/tmp/byq-phase17-adr0090-f6-v12/root-control/pre-rejection-readonly-reconciliation.json` | `bd39b97e9c7cf21a37342d347721621c5d22f6c7c8bf6e134b9cf4179fb07e2c` |
| `/tmp/byq-phase17-adr0090-f6-v12/root-control/pre-rejection-durable-catalog-reconciliation.json` | `de917718baeae02c5b55264482ba56d64d9c663671144185e5ff1d0936fbb9a9` |
| `/tmp/byq-phase17-adr0090-f6-v12/root-control/audit-proof-f6-1.json` | `cc3753720d9b43192048c35897bc398da40e098190f463749f7b9819449e9232` |
| `/tmp/byq-phase17-adr0090-f6-v12/RUN-F6/error.json` | `1b411277253edfda782852989773af1e2b35e4447791487f056cf33fc7e8248c` |
| `/tmp/byq-phase17-adr0090-f6-v12/f6-off-final-environment.json` | `d9b110c87a3d3179a2e509c47bdea9ce3d9eeb7efe4a31d9ce5504598cb336ca` |
| `/tmp/byq-phase17-adr0090-f6-v12-protected-after-closeout.json` | `19e3f7747032f398893d2b1e12eeb16e5dd9935fcd58c63b748e4583453b9006` |
| `/tmp/byq-phase17-v12-audit-resource-tester-20261001/assessment.json` | `7e429f2bac2de2ef091f79a2ced1d306d467586c1397a304073685d0cc397924` |
| `/tmp/byq-phase17-v12-audit-resource-independent-review-20261001/actual-failure-cleanup-review.json` | `459ff729a20650f7bb17ca79902d32fb89b79aaabc5c197cdb438bbf72225b5a` |
| `/tmp/byq-phase17-adr0090-f6-v12/root-actual-result-acceptance.json` | `c0d7e3410d87034b462a030451d9469ce96c20f891f9f9082d57d000fad7b30f` |

## 16. 审计资源观察器的定向修正（2026-10-01）

最小修正仅作用于 Root 审计和 Runner 两处：FG1 的 strategy_validate 授权资源允许
`null/null` 或 `research_task / 本轮精确 Task`；任意其他 Task、半空资源或 Artifact
绑定仍拒绝。所有其他 stage 的 action、结果资源、run/owner/actor/workspace、角色、
完整动作序列与唯一审计 ID 检查保持严格。Root 在权威结构化读回后、run/resource
断言前先 O_EXCL/fsync 保存 `OBSERVED_NOT_QUALIFIED` 完整响应；它不产生 PASS
证明或信号。产品权限、Job、DSH 和 ADR-0090 的架构边界没有变化。

Python/JS 各通过 5 个正例和16个反例（使用已有真实 v11/v12 审计样本）；另验证
一次 stub main 先存响应再拒绝坏 run，未生成 proof/signal。剩余 FG2/BG 的精确
BacktestTask 结构以3正例/5反例核对，未发现此范围内额外确定性合同阻塞。首轮
Node harness argv 接线错误、未触发候选断言的事实另存说明；正确矩阵通过不覆盖
原错误。没有模型、Product、Docker、SQL 或浏览器调用，没有重跑 A–D/完整套件。

Tester → independent Reviewer → Root **限定 offline PASS**。可审查差异见
[审计资源观察器 patch](evidence/phase17-f6-audit-resource-observer.patch)。零上下文
附件从原冻结 helper 精确重建两个已验收 candidate 字节；没有修改原 v12 helper。
新候选仍需完整剩余断言/合同一次性检查、全量源文件/helper绑定、新鲜只读准入和
独立冻结，才能做受影响实测。旧 v12 F6 FAIL 不升级；成功健康收尾/真实许可 UI、
最终 Golden/hosted CI仍需实际证据，Phase17 OPEN，Phase18未开启。

| 离线修正门禁证据 | SHA256 |
| --- | --- |
| `/tmp/byq-phase17-v12-audit-resource-repair-20261001/manifest.json` | `3c84c13f66ac5b33dcf630a7f1a9855bd79f4d04e522589357e3d529b3ba56f2` |
| `/tmp/byq-phase17-v12-audit-resource-repair-20261001/qualify-agent-audit.py` | `922b0285c001a9d31ae3be2894498f23eb9756a7cd2f6faa55a748c8cd7ad7c7` |
| `/tmp/byq-phase17-v12-audit-resource-repair-20261001/run-f6-once.mjs` | `9950c29bedb517c3fd4ad004e882e9bb6462b963e5fa88262e905f0c8782c041` |
| `/tmp/byq-phase17-v12-audit-resource-repair-20261001/audit-resource-observer.patch` | `e9f393b8d7bdbccfa57fb96351d05e29def83ae2a6a9b53a574d7759fa1f32d3` |
| `/tmp/byq-phase17-v12-audit-resource-repair-20261001/patch-reconstruction-proof.json` | `d21bc6fbcc1a41dccd4de9ebe6c1b015938d3abe3f4fece278f130d6fff512fc` |
| `/tmp/byq-phase17-v12-audit-resource-tester-20261001/report.json` | `ca6c936e3304b41f5413321ae6bcb1f634a660ff3f476eccc830f10fde5815ff` |
| `/tmp/byq-phase17-v12-audit-resource-tester-20261001/testing-harness-correction-note.json` | `028984010bce5000f7c971c515ce1a26be0196e255efcb8bbd0a47801a110470` |
| `/tmp/byq-phase17-v12-audit-resource-independent-review-20261001/candidate-review.json` | `02d1514a58fbfe6f5552618cbc16f64d263a3db82636bffcf2cdfe04231d5bd2` |
| `/tmp/byq-phase17-v12-audit-resource-repair-20261001/root-offline-repair-acceptance.json` | `8b71d7cd45cacf551afa6e4ed7b858f7edfbacc8a2bad75c2a2796fd5d8c8fea` |
