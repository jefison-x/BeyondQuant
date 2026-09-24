# ADR-0086：单次研究请求的分层预算（修订 ADR-0085 §6/§8）

- Status: **Accepted**（维护者 2026-09-24 明确取消 ADR-0085 §6 固定“最多 2 次”模型调用上限，并授权按本决定修改现行门禁）
- Date: 2026-09-24
- Maintainer scope correction: 2026-09-24，明确取消“后台研究跨进程恢复后仍须沿用同一份持久业务预算”的拟议要求。
- Relates: ADR-0085 §6/§8、ADR-0084 §6、ADR-0082
- Scope: 仅研究判断请求的模型预算单位、限额和中断语义。本决定取代 ADR-0085 §6
  的固定两次模型调用目标及其验收项，并修订 §8 中研究判断预算的解释；不改已有
  `research_tasks.continuation_budget` 账本，不授权生产预算逻辑变更、deploy、
  release/tag、付费资源或 Phase 100/0.10。现有实现中的固定门禁必须另行整改、
  验证后才能宣称符合本 ADR；接受决定本身不构成运行时验收通过。

> 预算约束一次具名、有界的研究判断请求，而非整个 ResearchTask 跨进程共享的持久
> 业务额度。一个研究判断请求可以包含多个真实 provider 调用；每次 provider 调用
> 还必须满足独立的输入、输出和工具数据上限。不能仅把固定 2 改为 3，也不能取消
> 硬上限。已中断且未证明终结的请求不得因进程重启而自动重发模型调用。

## 背景（已观察到的事实）

1. 当前有界研究判断回合经 `DshBoundedTurnRunner` 的专用只读 composition，观察到
   **3 个真实 provider 请求**（root `tool_call` → child `closed_result` → root
   `final_text`）。Adapter 的 `research_judgment.py:321-335` 在回合完成后、结果提交前
   才校验计数；它阻止越限结果提交，**不能阻止第 3 个请求已经发生**。
2. `research_judgment_stage_calls.call_index` 计数的是一个 `(task, plan_version,
   stage)` 的准入研究回合，不是 provider 请求数。现有合同默认最多 2 次准入；
   Adapter 对 `strategy_draft`、`backtest_analysis` 具名允许 3 次 provider 请求，
   其余阶段默认 2 次。三个计数不得混用。
3. legacy continuation 的 `byq-continuation-budget.js` 在 `llm/stream` 的
   `next()` 前检查 root 与 child，并记录保守额度；专用研究判断 composition **未加载**
   该 guard。`research_tasks.continuation_budget` 是另一个已存在的 continuation
   账本，不等于研究判断请求额度。本 ADR 不删除或重置它。
4. 研究判断目前缺少覆盖每次 root/child provider 调用的请求前硬门禁；仅在
   Adapter 构建 harness 前检查一次，也不能约束 harness 内后续调用。真实用量与
   预留上限仍需分别显示，不能把上限冒充消耗。

## 决定

### 1. 明确两个请求层次

- **研究判断请求**：由 BYQ 准入的一个具名、受限的阶段判断 attempt。其限额按该
  阶段和实际所需 DSH 路径配置，包括本次 attempt 的 provider 调用次数与运行时间。
  不设置跨进程、跨 attempt 或跨整项 ResearchTask 的持久业务预算。
- **Provider 调用**：研究判断请求内 root 或 child 发往模型的每次实际调用。每次
  都限制完整模型可见输入（含已渲染上下文）、输出 token 和工具响应 payload；
  工具侧有界投影继续先于模型调用生效。
- 已有 Backend stage-call 准入计数、continuation 账本、服务商账户级限流和用量
  统计保持各自语义，不作为上述两层计数的替身。历史 P3 的
  `model_call_limit=2` 若实际计数 stage-call 准入，实施时必须更名或准确说明，
  不得冒称它限制真实 provider 请求。旧 stage-call 计数保留作精确身份、幂等和审计；
  若固定两次累计值会拒绝旧 attempt 已受信终结后由用户明确发起的**新请求**，
  应移除此跨 attempt 固定预算门禁，同时维持 one-active、CAS、首次无进展即停止。

具名阶段的上限须由实测调用路径与成本证据确定，并在合同/配置中明确。当前观察到的
root→child→root 是 3 次 provider 调用，但不能把 3 当作全部 DSH 工作的全局常数。

### 2. 每次调用前拦截；不新增持久业务预算

- 每个研究判断请求启动前检查其具名限额；每次 provider 调用都必须经过同一
  `llm/stream` 或等价的受支持请求前 hook，**root 与 child 均覆盖**。在发出请求
  之前检查本次 attempt 的剩余额度；超过次数、输入、输出、工具 payload 或
  时间上限则不发出该次调用。Adapter 启动前的一次检查不能代替此 hook。
- 本草案**不要求**把研究判断预算作为 `research_tasks` 的持久业务账本，也不
  要求跨组件重启沿用同一余额、补记旧额度或按 task/stage 累计扣费。实现可保存
  用量/失败回执供审计；审计记录不是下一次请求的额度权威。
- 本次请求一旦进程中断或调用结果不明，**不得自动重新运行同一未决模型
  attempt**。保留既有 stage-call identity、plan CAS、幂等和迟到结果隔离；只有
  受信的终结/恢复判定证明旧 attempt 不再运行后，才能由**明确的用户操作**发起
  一个**新的**有界研究判断请求，使用新请求自己的限额；原有后台自动授权不
  触发故障重试。若不能
  证明旧 owner 已终结，保持未决/`needs_attention`，不得假报恢复成功。
- 上述规则只约束模型判断；已获批准的确定性工作流动作仍依原 plan/event 合同
  恢复，不需要模型重新推导 identity、审批或 next action。

### 3. 上限与实际用量分开

- 配置的 `max_*` 是安全上限，不是实际消耗。正常结束时分别记录可证明的
  provider 调用数、input/cache/output tokens、工具 payload 字节和耗时。
- 观测缺失时实际用量为 `unknown`，不可填入上限数值冒充实耗；不得因为记录
  缺失就免费重试同一未决 attempt。超限或无法安全判定时按原有
  `needs_attention`/结构化 reason 收敛，不提交越限判断结果。

### 4. 保留进展栅栏

首次无 durable progress（`plan_version` 或 durable progress identity 未变）
仍立即进入 `needs_attention/no_durable_progress`。模型调用次数上限是防止成本和
循环失控的最后一道栅栏，不是决定下一业务动作的编排算法。

## 验收标准

1. 具名研究判断请求声明 provider 调用次数与耗时上限；每次 provider 调用声明
   完整输入、输出 token 与工具响应上限，巨量输入在发出模型请求前被拒绝。
2. 请求前 hook 覆盖同一 attempt 的 root、child 和后续 root；超过本次请求额度
   时不发出下一次调用。仅有事后校验或 Adapter 启动前检查不算通过。
3. 进程中断后同一未决 attempt 不被自动重发；迟到结果、重复提交和新请求仍由
   既有 plan/stage-call identity 与 CAS 隔离。**不测试、不要求持久业务余额
   跨进程结转。**
4. 上限与可证明实耗分开显示；缺失实耗标为 `unknown`，不得冒充零消耗或免费重试。
5. 首次无 durable progress 立即停止；隔离实测和负控覆盖 root/child 路径、
   越限阻断、进程中断与重复请求。

## 后果与实施顺序

本决定降低了跨进程业务预算账本的复杂度，但明确放弃“模型判断在进程故障后
无人工介入自动接着跑”的承诺。若旧 attempt 是否终结无法证明，就暂停该判断；
不得通过重启刷新额度来制造无限自动重试。已有 continuation 账本、安全审批和
确定性工作流恢复保持不变。

实施本 ADR 时，先定义请求级合同及各具名阶段限额，再复用 DSH 受支持的
`llm/stream` 拦截点或等价 provider 边界实现 root/child 请求前门禁，最后补
用量投影、隔离实测与可失败负控。若受支持边界不能逐次拦截，保持 P4 的相关
验收行未通过，不以事后计数或放宽常数替代。在请求前硬门禁、隔离实测与对应合同验收完成前，`round-analysis`、
`rounds-2-3`、`final-selection` 仍不得宣称通过；历史 `CONTRACT_CONFLICT` 观察不得改写。
