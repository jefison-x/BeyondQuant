# Phase 17 — continuation 预算与 F6 观察器审计

Status: **审计/最小方案；预算边界改变尚未实施；F6 实测暂停**。
本记录使用当前 Clean Break ADR-001–006/ADR-0088；历史 ADR-0086 不作为现行规范。
[ADR-0090](../architecture/adr/ADR-0090-continuation-request-limits.md) 是待维护者明确接受的方案。

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

## 4. 实际修改、测试和剩余门禁

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


## 6. 本轮 Tester → 独立 Reviewer → Root 限定验收

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
