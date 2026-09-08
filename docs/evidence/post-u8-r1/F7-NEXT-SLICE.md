# F7 后续实现入口核查（2026-09-08）

状态：设计核查，尚未实现。不得据此关闭 F7。

当前安全接入门禁：同 generation 两根回合的真实 HTTP 探针确认缺少可独立关联的根身份。
[ADR-0067](../../architecture/adr/ADR-0067-root-scoped-runtime-call-identity.md) 提出根回合隔离方案，
待接受。已有摘要合同为未接入原型，不是可信执行许可；不能跳过该门禁直接部署 Backend 计数器。

接受后的首轮实测见 [官方调用观察资格切片](F7-CALL-OBSERVATION.md)：7 项观察探针通过，
Runtime 132 passed/7 skipped；构建身份漂移导致架构检查未全绿，仍未完成持久准入。

后续核查：仅传入 AgentRun 引用不足以证明当前调用的根归属。下述实现计划必须结合
[ADR-0066](../../architecture/adr/ADR-0066-domain-validation-call-admission.md)
的逐调用可信证明；维护者于 2026-09-08 批准该决策，先隔离资格验证再实施。
接受不代表工具观察、schema 拒绝覆盖或持久准入已通过，不将 AgentRun 引用本身当作调用凭证。

## 已有能力与缺口

- `services/backend/app/agent_research.py` 已有 `agent_runtime_turns`、
  `agent_runtime_registrations` 和 `agent_runs.root_run_id`。可信注册观察可将 AgentRun
  绑定到 Adapter 所见根回合；应复用，不能按 SDK generation 新建第二回合账本。
- `services/mcp/src/server.ts` 的 `trustedBackendFetcher` 传播 owner/workspace/actor/
  session/trace/process generation，但策略校验/ML 创建参数尚未要求精确 AgentRun。
  不能把同进程中“最新 active run”或 model 自报 root_run_id 当作该调用的可信归属。
- `AgentResearchStore.authorize` 校验 run 的 owner/actor、session/generation 和角色，
  但独立授权调用不等于下一 HTTP mutation 的已绑定一次性请求身份。
- `ml-research.ts` 的 `repair_limit: 1`、`strategy.ts` 的安全错误反馈只是提示；
  不能代替 Backend 对并发、重启、换幂等键和换子 Agent 的持久限制。

## 下一批测试先行范围

1. 沿现有 MCP → Backend 策略/ML 请求传入可核查 AgentRun 引用，Backend 校验既有
   trusted registration、root、owner/workspace/session、task 与精确动作。缺绑定时拒绝
   Agent mutation；普通用户 Product 操作不能被错误计入 Agent 纠错预算。
2. 在 BYQ 领域侧以根回合 + 原任务 + 动作作为不可通过换 idempotency_key/child 重置的
   修正范围，记录规范输入 hash、请求身份及封闭结果，不保存 raw 异常或凭据。
3. 先持久认领再校验；相同请求只重放原结果，相同 key 不同输入拒绝。首次失败允许一次
   明确修正，重复无进展或预算耗尽明确阻断。未知结果先查原回执，不能视为可再提交。
4. 并发重复、事务回滚、结果写入前后崩溃、重启、旧终态 run、跨 owner/任务、同根换
   child、下一用户回合及正常 UI 请求分别给失败反例；safe error 和界面状态不能说成成功。

实施保持 ADR-0031/0062、MCP-only 与 Product/Engineering 隔离。若发现现有可信注册无法
证明请求归属，应先记录具体 seam 缺口与决策，不以“实现了计数器”冒充 F7 完成。
本核查未调用模型、未改 Backend/MCP 或生产数据，不授权历史研究续跑。
