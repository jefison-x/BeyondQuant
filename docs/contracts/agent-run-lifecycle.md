# AgentRun 单轮持久收尾（ADR-0062）

本合同只关联 BYQ AgentRun，不复制 DSH workflow，也不转换 ResearchTask、Approval 或业务 Job 状态。

## 可信关联来源

官方 0.1.2rc1 的 `tool/call` 通知包含 JSON 字符串 arguments。本地 scripted Provider + 官方进程
已核对 `mcp__byq__byq_agent_run_start` 的原 idempotency_key。兼容层仅提取这个能力的有界注册键，
不向 Gateway 或浏览器传输原始 arguments。其他能力、无效 JSON、非字符串键不产生绑定。

Runtime 使用已捕获的 ActiveRun、可信 owner/workspace/actor/trace/session/process generation
计算 `agent-run-registration.v1` SHA-256 摘要。规范化 `agent.run.registration` 只含
`agent-run-registration-observed.v1`、本轮 run_id 和摘要；每轮最多128个不同摘要，重复不增加事件。
迟到回调及无法关联的 child 不能注册到当前轮。摘要不是授权 token，也不是业务执行成功证据。

## 持久合同

Backend Store 的 `agent-run-lifecycle.v1` 接收精确32位 root_run_id、正整数 sequence、封闭 outcome；
active 注册必须带64位 registration_fingerprint，终态不能同时新增注册。
owner/workspace/session/trace 由可信调用方单独传入，不能由模型或该 payload 覆盖。

- `agent_runtime_turns` 保存 active/completed/failed/cancelled/interrupted 及第一份 terminal_sequence。
- `agent_runtime_registrations` 将原注册摘要只绑定到一个 root；不能重绑另一轮。
- `agent_runs` 的可空 root_run_id/摘要不对历史记录猜测回填。
- 开启可信 `require_runtime_binding` 时，注册尚未关联只返回 pending_binding；不能授权领域动作或创建审批。
- 终态、晚到注册、AgentRun 更新及审计在一个事务中处理。终态先到、注册或实际 AgentRun 后到，均不重新 active。
- 同进程另一轮不受影响；父子已知绑定必须属于同轮，迟到的跨轮 child 失败关闭。
- 同一终态重放无重复审计；矛盾终态拒绝覆盖原证据。业务审批结果和执行状态保持独立。

锁顺序为 root → registration digest；start_run 只锁 registration digest → 原 owner/key，不反向锁 root。
这使并发插入和终态更新不遗留 active 行。注入审计失败时，根终态和 AgentRun 同步回滚。

## 当前接入限制

已实现并验证 Store 合同和 Runtime 来源投影，尚未启用 Product API 的强制 pending_binding 路径。
`require_runtime_binding` 不是公开模型参数；现有请求路径不因这个组件提交而被静默切换。
Gateway 的可靠消费、持久 ack/重放、Backend 可信接收端、MCP 精确 pending 回执查询仍待接通。
不得向 Product/模型开放“任意关闭 AgentRun”工具来绕过这一步。

Adapter 整体崩溃而未产生终态、用户/工作区禁用后的收尾、以及历史无绑定记录仍需独立验证；
当前 workspace write trigger 要求 active owner，不能将禁用后的终态清理假定为已解决。
缺失绑定或回执不得靠同会话最新对象、当前进程下所有历史记录或时间猜测。

此组件通过不等于 R4/F10 全部完成，不授权生产部署、历史研究续跑或模型训练。
