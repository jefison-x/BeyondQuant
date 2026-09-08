# 私有领域调用证据与纠错准入

依据 [ADR-0066](../architecture/adr/ADR-0066-domain-validation-call-admission.md) 和
[ADR-0067](../architecture/adr/ADR-0067-root-scoped-runtime-call-identity.md)。
本合同描述隔离实现，不代表全部资格通过或生产部署；当前证据见
[F7 纠错台账](../evidence/post-u8-r1/F7-CORRECTION-LEDGER.md)。

## 范围与身份

仅覆盖 `byq_strategy_validate`、`byq_ml_strategy_create`。每个根回合拥有独立官方进程、
generation 和可信 root header。模型提供的 root、最新 active run、时间接近均不是授权证据。
Adapter 仅观察当前进程、当前回合和已验证 child 归属的官方调用；Backend 再核对注册、
角色、原任务、会话目录、用户及工作区。普通用户直接操作仍走原 Product 身份和审批路径。

`domain-call-observed.v1` 为封闭对象：`schema_version`、`sequence`、`root_run_id`、
`generation`、`call_id`、`action`、`task_id`、`agent_run_id`、`idempotency_key`、
`request_sha256`、`input_sha256`。不包含原始参数。私有序号与公开 WorkflowTrace 序号独立。
原始 JSON 必须完整、无重复键、无非法 Unicode、无非有限数值；结构上限为 8192 节点、
24 层、256 KiB，数值范围不超过 JavaScript 安全整数范围。不可证明的输入不得产生凭证。

双方使用共享 Python 合同进行类型化规范摘要；可信 trace 覆盖模型 trace，数字统一 IEEE-754
值而非 JSON 拼写。request 摘要包含完整有效请求；input 摘要仅排除 AgentRun 和幂等键，
因此换 child 或 key 不构成输入修正。摘要不是权限令牌，不得公开给模型或浏览器。

## 私有投递

Runtime `POST /internal/runtime/sessions/{session_id}/domain-call-evidence` 接收封闭的
`trace_id`、`owner`、`workspace_id`、`after_sequence` 上下文，返回
`domain-call-page.v1`：`schema_version`、`events`、`more`、`idle`。
每会话最多 1024 份证据，日志仍受 8 MiB 上限约束。日志 v3 保留精确终态 ACK；
v1/v2 仅在原摘要校验成功后增加空私有列表，不从历史文本生成调用证明。

Gateway 复用持久投递基础设施，但保存独立 `.domain-calls.json` 账本；不写入公开 trace、
SSE 或回答。先持久化发送次数，再发送，每份最多 8 次、24 小时；坏页、缺序号、未知字段
以及回执不匹配均不能推进确认。空闲页只有在目标序号已持久确认后才能停止读取；公开 trace
变化只是唤醒信号，不是调用证据。私有证据送达不得自动执行模型或领域请求。

Backend `POST /internal/domain-call-evidence/{conversation_id}` 仅接受可信目录消费者，
校验 owner/workspace/session/trace 后保存证据与精确 `domain-call-receipt.v1`。
回执包含 `schema_version`、`sequence`、`root_run_id`、`event_sha256`；重复事件重放
原回执，序号内容冲突拒绝。关闭后的晚到证据只收尾，不重新激活任务或 AgentRun。

## 准入与停止

准入先持久认领，再以 CAS 进入 executing；领域写入与成功回执同事务。崩溃、存储异常、
丢失结果保持 unknown 和已占用预算，不自动退款，不以新 key 绕过。仅明确的领域校验拒绝
计作可修复失败；普通异常不推定为可修复。

正常首次成功的不同操作不扣修正额度。首次校验失败后，同 root/task/action 最多允许一次
不同输入修正；相同失败输入、第二次失败、换 key/child、重启均不得重置额度。身份撤销、
任务取消或根终态阻止新执行；精确旧成功回执可以核对但不再写领域对象。

缺证据返回封闭的 `425 call_evidence_pending`，不执行领域操作。MCP 仅对此种明确未执行
结果最多重送 4 次，等待 250/500/1000/2000 毫秒，仍受外层超时约束；超时、409、5xx
及不匹配的 425 不重试。API 成功继续返回既有领域结果，不暴露内部 claim 能力。

ML 领域校验的 correctable_failure 可附带 `validation`：只允许由 BYQ
MLValidationError 白名单投影得到的 `ml-validation-problem.v1`，包含封闭字段路径、
类别及固定修正指引，不保存异常文本、输入值或动态允许值。它随失败回执持久保存，
精确重放返回原提示；历史无提示回执保持不变，不据此重新执行。
MCP 单独白名单投影该提示，native-stop admission 标记仍只含原有状态/原因/stop；
提示不能改变第二次失败停止或预算耗尽决定，unknown/blocked 不携带校验提示。
普通策略对应 `strategy-validation-problem.v1`，字段限定 strategy 及其公开 schema 字段，
类别限定类型/长度/格式/未知字段/不支持值/凭据字段禁止/静态校验失败等封闭枚举。
静态错误仅报告 strategy.script + static_validation_failed，不保存源码、导入名或异常文本。
无法分类的 StrategyValidationError 降为 strategy + invalid_strategy；不从异常字符串猜字段。

SDK schema 拒绝通过私有 `/internal/domain-validation/schema-rejection` 接入同一台账；
SDK 仍执行原校验。需要停止时保留原错误，并增加封闭 BYQ admission 标记，仍为 tool error。
Adapter 验证官方调用归属及标记后关闭其所属官方进程，使用规范化失败码向用户说明；
缺引用、保留上限和纠错停止分别为 `domain-call-reference-unproven`、
`domain-call-retention-bound`、`domain-correction-stopped`，不提示无条件直接重试。

这不等于研究目标完成，也不构成 F6 全模型调用费用硬上限。禁止后台主动续接、生产迁移
或清空历史失败记录来绕过任何未通过的门禁。
