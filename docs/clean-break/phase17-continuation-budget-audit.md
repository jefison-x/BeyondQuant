# Phase 17 — continuation 预算与 F6 观察器审计

Status: **ADR-0090 已实施并通过限定离线门禁；F6 v8 在授权后观察器合同断言失败并已清理；F6-2/BG/UI NOT_RUN，Phase 17 OPEN**。
本记录使用当前 Clean Break ADR-001–006/ADR-0088；历史 ADR-0086 不作为现行规范。
[ADR-0090](../architecture/adr/ADR-0090-continuation-request-limits.md) 已于 2026-10-01 获维护者“明确接受”。以下第 1–6 节保留接受前限定验收的事实边界；当前实施及实测状态见第 9 节。

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

本节是最新状态；前面“实施中／尚未验收／NOT_RUN”段落保留其记录时的历史边界。
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

本节取代第 8 节的“下一步”作为当前状态；历史失败及门禁不改写。
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
