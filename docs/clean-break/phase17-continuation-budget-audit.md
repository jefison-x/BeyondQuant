# Phase 17 — continuation 预算与 F6 观察器审计

Status: **ADR-0090 已接受；单请求合同正在实施；F6 实测仍暂停**。
本记录使用当前 Clean Break ADR-001–006/ADR-0088；历史 ADR-0086 不作为现行规范。
[ADR-0090](../architecture/adr/ADR-0090-continuation-request-limits.md) 已于 2026-10-01 获维护者“明确接受”。以下第 1–6 节保留接受前限定验收的事实边界；当前实施进度见第 7 节。

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
