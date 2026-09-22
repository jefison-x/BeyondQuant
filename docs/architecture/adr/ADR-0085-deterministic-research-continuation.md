# ADR-0085：确定性研究编排与有界模型接续

- Status: Accepted
- Date: 2026-09-22
- Accepted: 2026-09-22（维护者明确“接受 ADR-0085 的完整决定”，并授权标为 Accepted、
  同步修订 ADR-0062/0065/0077、STATUS 与专项计划，随后按 P0→P4 每步独立 PR 实施；
  0.10.0 继续冻结。）
- Version assignment: 2026-09-22，维护者随后明确“本次稳定性修复定为0.9.1版本”。
- Decision owner: BeyondQuant maintainer
- Relates: ADR-0017、ADR-0044、ADR-0045、ADR-0051、ADR-0062、ADR-0065、ADR-0077、ADR-0079、ADR-0084
- Supersedes: ADR-0062 §4 中以自由文本恢复完整研究任务的实现方式；ADR-0077 中数据就绪后启动通用完整模型回合的实现方式；不改变其任务绑定、预算、身份、审批和 at-most-once 安全要求。
- Scope: 0.9.1 会话/长研究稳定性版本；不启动 0.10.0，不授权生产部署、正式 release/tag、付费资源、破坏性数据操作或自动批准业务动作。

## 背景

当前长研究接续把两类职责放进了同一个自由形式模型回合：

1. BYQ 可确定执行的领域状态转换，例如从 `signal_producer_job` 推导 `backtest_task_id`、读取下一动作、等待审批、执行已批准的精确动作；
2. 需要模型判断的研究工作，例如解释回测结果、比较三轮方案和提出策略修正。

数据就绪事件只给模型一段“重新读取原任务并继续”的自然语言提示。模型需要重新发现对象、重建动作顺序、寻找原幂等键并从宽泛工具集合中选择下一动作。审批接续又使用另一段自由文本提示启动新的完整模型回合。ResearchTask 的 `progress.next_action` 是任意文本，不是可执行状态机；审批、数据就绪和作业完成也没有共享同一条精确 next-action 账本。

2026-09-22 的真实失败证明，提高调用次数不能解决该结构问题。一个数据就绪接续在第 1 轮回测执行前耗尽全部 8 次模型调用。接续已收到精确 `signal_producer_job`，而 BYQ 可以无模型地推导对应的 `backtest_task_id`；但模型仍重复读取任务、拉取完整信号快照、尝试重建创建参数并启动只读子代理。完整信号快照的 MCP 返回约 15.9 MB，包含 220,803 个 frame index 项等执行数据。DSH 在下一模型请求前裁剪了该大结果，但它已经进入 harness 事件/压缩链路并触发大规模上下文处理。

同一失败还留下相互矛盾的公开事实：RuntimeSession 为 failed，continuation receipt 为 needs_attention，ResearchTask 仍为 running/backtest，最近 RuntimeGeneration ledger 仍为 starting。现有测试覆盖了账本、隔离和重启等机械属性，却没有验证一次真实复合研究能跨审批、数据就绪、三轮回测和模拟账户创建完成。

详细证据见 [harness continuation audit](../../evidence/harness-continuation-audit-20260922/README.md)。

## 决定

### 1. BYQ 持有领域执行计划，DSH 继续持有通用 Agent Loop

新增框架无关的 `research-execution-plan.v1` 领域合同。它属于 BYQ Domain Workflow，不是第二套通用 Agent harness，不保存 DSH 私有上下文、hidden reasoning、tool state 或 session journal。

每个复合 ResearchTask 最多有一个当前有效计划版本，至少包含：

- `task_id`、`plan_version`、`task_version`、owner/workspace/conversation 绑定；
- 当前 `stage`、`iteration`、`status`；
- 枚举型 `next_action`；
- 精确 resource references；
- 精确 prerequisite 和 expected postcondition；
- 所需审批的 action/resource identity；
- BYQ 生成的 idempotency key；
- 允许的最小 MCP capability 集合；
- 最近一次 durable progress identity。

计划以 task/plan version compare-and-swap 更新。旧事件、旧模型回合和旧 generation 不得推进新版本。

### 2. 按动作类型分离执行

`next_action` 分为三类：

1. **确定性领域动作**：对象推导、状态读取、等待、已批准动作提交、作业排队、状态投影和幂等核对。由 BYQ reducer/worker 按精确合同执行，不启动模型。
2. **研究判断动作**：策略草案、回测分析、轮次比较、修正建议和最终说明。才允许启动 DSH 模型回合。
3. **人工门禁动作**：需要用户审批或确认。计划进入明确 waiting 状态并投影到会话/工作流卡片；审批结果只解锁绑定的精确动作。

数据就绪、审批决定或作业完成事件首先进入同一个 BYQ reducer。Reducer 计算一个精确下一动作；只有该动作属于研究判断类时才请求 DSH。

### 3. 审批执行精确命令

复合 ResearchTask 中的 approval 必须绑定 plan version、action、resource、参数摘要和 BYQ 生成的幂等键。批准后执行该精确命令或把计划原子推进为 executable；不得再启动“审批已通过，请重新理解并执行”的通用模型回合。

每项高影响动作仍分别审批。本文不扩大授权，也不把策略批准视为回测、模拟账户或其他动作的授权。

不属于复合 ResearchTask 的兼容审批可以暂时保留旧接续路径，但必须与新计划账本隔离，不能推进计划型任务。

### 4. 数据就绪携带可执行身份

`signal_producer_job completed + validated signal_snapshot` 事件必须直接携带或由 Backend 推导：

- `backtest_task_id`；
- `phase` 和枚举型 `next_action`；
- snapshot/artifact/strategy/pool/experiment 精确引用；
- approval requirement；
- expected postcondition。

当前 `signaljob_<hex>` 到 `backtesttask_<hex>` 的确定性关系由 BYQ 代码执行，模型不再猜测或重建创建参数。

### 5. Product Agent 不读取执行级大快照

Backend/Worker 继续保存完整不可变 signal snapshot 作为回测输入。Product Agent 的 MCP `byq_signal_snapshot_get` 改为有界安全投影，最多返回 64 KiB 序列化内容，并只包含：

- identity、hash、status、lineage；
- 日期范围、universe/benchmark 标识和数量；
- signal/corporate-action/bar 数量；
- execution 参数摘要；
- readiness 和完整性摘要；
- 必要的有限诊断样本。

它不得返回完整 `bars_frame`、逐日 benchmark、逐标索引、完整信号或 corporate-action 行。完整执行输入仅供可信 Backend/Worker 消费。若研究分析需要结果，使用已有有界 `byq_backtest_analysis_get`。

### 6. 模型接续使用最小接口和进展栅栏

研究判断回合只暴露：

- 当前 `research-execution-plan.v1` 的有界投影；
- 当前分析所需的有界结果摘要；
- 本阶段允许的最小只读工具；
- 一个用于提交 proposal/analysis/decision 的领域命令。

不默认重放完整公开会话，也不暴露宽泛的研究创建、执行、审批和子代理工具集合。需要原始目标时由计划保存规范化 objective/constraints。

每个模型响应后检查 `plan_version` 或 durable progress identity：

- 有合法进展：提交并结束该回合；
- 无进展、重复同一读取或重复同一动作：第一次即停止为 `needs_attention/no_durable_progress`；
- 不允许用连续 8 次模型调用充当进展检测机制。

正常研究判断阶段目标上限为 2 次模型调用：一次产生工具/提交动作，一次形成最终受限结果。确有证据时可按具名阶段提高，但预算是安全上限，不是编排算法。

### 7. 统一接续事件和状态收敛

approval、data-ready、backtest-completed、user-resume 和 recovery 进入同一 task continuation ledger，绑定 task/plan/event version。一个 task 同时最多有一个 admitted continuation。

所有终态必须原子收敛：

- continuation budget/guard 失败时，ResearchTask progress 转为 `needs_attention`，记录结构化 reason 和 event identity；
- Product conversation 保留 active 是允许的，但必须显示最近 task/run failure，不能把 active 等同于任务正常运行；
- RuntimeSession 终态产生时立即关闭对应 RuntimeGeneration ledger，记录 `completed`、`failed`、`interrupted` 或 `closed` 和 `ended_at`；
- 恢复只能重试当前精确 plan action，不创建新 task、不替换对象、不重新发明幂等键。

建议的 waiting/terminal stage 至少包括 `waiting_for_approval`、`waiting_for_data`、`waiting_for_job`、`waiting_for_agent`、`needs_attention` 和 `completed`，并由合同验证合法转换，不能只依赖任意文本。

### 8. 预算区分预留与实际使用

继续保留每次调用的保守额度预留和硬调用上限。对用户、任务和运维投影同时记录：

- `reserved_token_ceiling`；
- DSH/provider 可证明的 `actual_input_tokens`、`cache_read_tokens`、`output_tokens`；
- `model_call_count`；
- `tool_payload_bytes` 和被裁剪量。

不得把 8 次调用的保守上限 8,454,144 token 描述为模型实际消耗。权限 UI 使用阶段数/最大模型调用数和成本估算表达，不要求普通用户理解 1,048,576 token 的内部 guard 单位。

### 9. 复合任务权限必须在对话中显式建立

当 Product chat 创建需要跨异步事件继续的复合任务时，立即在原对话展示一个有界 continuation permission 卡片，说明预计阶段、最大模型调用数、有效期和仍需逐动作审批的项目。用户确认后把 grant 绑定 task/plan。

没有 grant 时，系统必须明确说明只会完成当前同步回合并在数据/作业就绪时通知用户；不得承诺自动完成三轮研究。ADR-0077 的 grantless data-ready 例外仅允许 reducer 做确定性推进和通知；不得启动通用完整模型回合。

## 验收标准

1. 数据就绪事件在零模型调用下投影出精确 `backtest_task_id`、phase 和 next action。
2. 已批准的精确确定性动作在零模型调用下提交；未批准动作稳定停在 `waiting_for_approval`。
3. Product Agent MCP 的 signal snapshot 返回不超过 64 KiB，且不含完整 bars/frame/benchmark/corporate-action 行。
4. 每个模型研究阶段默认不超过 2 次模型调用；无 durable progress 在第一次检查后停止。
5. 同一 event 重放、Gateway/Backend/Adapter/Worker 重启和迟到终态不会重复写业务对象。
6. RuntimeSession、RuntimeGeneration、continuation receipt、ResearchTask progress 和 Product projection 对完成/失败/中断事实一致。
7. 真实 Product API + DSH 旅程完成：创建复合任务 → continuation grant → 策略审批 → 数据就绪 → 回测执行审批 → 完成/分析/修正三轮 → 选择最优 → 模拟账户审批/创建 → task completed。
8. 上述旅程在每个异步交接点注入一次组件重启；验证任务/object identity、幂等、预算和用户可见状态。
9. 无 grant 版本必须如实停在通知/等待状态，不产生“会自动完成”的虚假承诺。
10. 生产 canary 使用隔离 owner/workspace/stock-pool，不把原始行情或完整执行快照发送给模型，并记录精确 model-call/tool-payload 证据。

## 迁移顺序

### P0：止损与事实一致性

- 将 MCP signal snapshot 改为有界安全投影；
- data-ready event 直接携带精确 backtest task identity/next action；
- budget exhaustion 原子更新 ResearchTask needs_attention；
- Runtime terminal 立即关闭 generation ledger；
- 修正 UI 的额度解释和“自动完成”承诺；
- 暂停旧 grantless 通用模型 data-ready continuation，只保留确定性推进与通知。

### P1：执行计划合同

新增 schema、持久计划、CAS、合法 stage/action 转换、事件 reducer 和最小 Product 投影。先覆盖普通策略三轮回测链路，不扩展 ML、实盘或 0.10 数据能力。

### P2：审批和事件统一

把计划型 approval/data-ready/backtest-completed/user-resume/recovery 迁入统一账本；保留兼容路径但禁止其推进计划型任务。

### P3：有界研究判断回合

增加最小 DSH composition/MCP surface、阶段输入摘要、proposal commit 和 no-progress fence。DSH 仍提供 Agent Loop、session、compaction 和 generic guards。

### P4：真实旅程、故障矩阵和 canary

执行完整三轮研究 E2E、各交接点故障注入、成本/负载上限和隔离 canary。全部通过后才恢复“后台自动完成复合研究”的产品声明。

每个 P0–P4 使用独立 worktree/branch/PR；前一项合并后再开始下一项。P0–P4 共同组成 0.9.1
稳定性版本，不推进 0.10.0。0.9.1 的正式部署、tag/release 和发布清单仍是独立维护者决定。

## 后果与取舍

- 增加一个 BYQ 领域执行计划和 reducer，但它只保存领域状态，不重复 DSH 通用 harness，符合 ARCHITECTURE 的 Workflow 分工。
- 更多确定性转换不再消耗模型调用，延迟、成本和故障面显著下降。
- 模型失误不再决定审批顺序、对象 identity 和幂等键；研究判断仍由模型完成。
- 现有自由文本 progress 需要兼容迁移。无法唯一映射的旧任务进入 needs_attention，由用户确认，不能猜测。
- 旧 MCP 完整 snapshot 行为对 Product Agent 构成有意收窄；可信 Backend/Worker 内部读取不受影响。

## 备选方案

- **继续增加 8 次以上调用或 token 上限**：拒绝。真实失败表明调用被用于对象重发现、重复读取和子代理调查，增加上限只放大成本。
- **只优化提示词**：拒绝。提示已经包含精确 signal job，但缺少机器可执行 next action 和 plan state；提示词不能替代领域状态机。
- **让 DSH 新增 BYQ 专用工作流**：拒绝。量化领域不变量、审批和业务幂等属于 BYQ；DSH 应保持 domain-agnostic。
- **由 BYQ 实现第二套通用 Agent harness/session store**：拒绝。本文只增加领域计划/reducer，并继续使用 DSH Agent Loop。
- **把完整 snapshot 交给更大上下文模型**：拒绝。完整 snapshot 是执行输入，不是研究对话输入；有界分析摘要足够且更安全。

## 回滚

P0 可回滚到通知-only，保持任务暂停并要求用户主动继续；不得恢复无界 snapshot MCP 返回。P1–P3 可按 task plan version feature flag 逐任务启用，回滚时让在途计划进入 needs_attention 并保留全部业务对象、审批、回执和审计。任何重新启用旧自由文本自动接续的决定需要新的 Accepted ADR 和真实 E2E 证据。
