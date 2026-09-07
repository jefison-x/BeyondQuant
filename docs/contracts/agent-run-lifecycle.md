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

## 跨服务消费与回执

Gateway 在启动采集器前固定会话目录身份，在现有 WorkflowTrace 卷保存专用投递账本。
启动时独立扫描已登记会话，不要求用户重新打开会话，不依赖 Runtime 仍存活。
先持久化规范化 trace，再扫描入账；两步之间崩溃可从 trace 恢复。不读取 DSH 日志。
账本使用原子替换、文件及目录fsync、跨进程文件锁；不新增领域数据库或通用任务队列。
扫描每次最多处理256条新事件，每会话每次最多发送16条。未变化的历史不反复重读/落盘。

只有当前session/trace、runtime-adapter来源、带精确root的注册与终态可消费；空闲关闭无root时忽略。
同root首个终态为权威，软取消后的重复/丢弃结果不覆盖它；迟到注册仍须送达并按原终态关闭。
Backend内部 `POST /internal/agent-lifecycle/{conversation_id}` 重新核对目录owner/workspace/session/trace，
只接受可信Gateway目录消费者，未向Browser或MCP开放收尾写工具。Agent-to-Domain仍经MCP。
`agent_runtime_receipts` 与状态/审计同事务提交，按owner/workspace/session/sequence唯一保存
`agent-run-lifecycle-receipt.v1`，含原root/sequence及规范事件SHA-256；序号内容冲突拒绝覆盖。
Gateway只确认完整匹配的回执。响应丢失、损坏或写ack前崩溃，均保留原事件重投；Backend幂等重放。

每份事件最多8次发送、首次入账起24小时截止；退避依次为2/5/15/60/300/900/3600秒。
次数和下一次时间在请求前持久化，重启不得重置；超限保留exhausted，不伪造成功或重新发起模型/业务动作。
一份事件耗尽不阻止其他root终态投递。只读Product接口
`GET /v1/agent/sessions/{conversation_id}/lifecycle-delivery` 显示pending、exhausted和invalid计数，
不返回注册摘要/原始参数。`up_to_date`只表示投递账本跟上当前trace，不代表研究目标完成。
损坏账本显示unavailable；超限显示attention_required。当前不提供自动重置预算或人工重投写接口。

可信Product DSH actor（`byq-product-agent-{session_id}`）的运行注册启用强制pending_binding。
这个actor来自进程可信header，不可用模型参数覆盖；既有非Product内部调用保留兼容路径。
MCP `byq_agent_run_start` 对pending最多额外查询3次（250/500/750ms等待），不重复POST。
显式 `receipt_only=true` 使用原role_id/idempotency_key做一次GET；Backend精确核对owner、workspace、
actor、session、trace和generation。旧generation或其他身份查询返回404，不借此授权新写入。
pending/unknown不能审批或执行领域动作；新回合不得复用已终态AgentRun。

## 保留的异常边界

按 ADR-0063，禁用 user/workspace/membership 后，可信内部消费者仍可关闭精确匹配的既有 root
及其已绑定 AgentRun，并原子追加对应审计/回执。持久 personal owner/membership 关系仍必须
存在且完全匹配；验证事务锁定身份行，避免检查与禁用交错。不能创建 root、补绑定或创建 run。
普通 API、MCP 注册/授权及研究续接仍要求 active 身份。数据库例外只允许匹配终态 root 的
既有 run 修改 status/version/updated_at，以及精确匹配的 runtime_turn_binding 审计 INSERT。
没有通用绕过标志，不临时启用账号，不修改业务任务/审批。重复终态回执不会重复追加审计。

Adapter 整体崩溃而未产生终态、以及历史无绑定记录仍需独立验证；
缺失绑定或回执不得靠同会话最新对象、当前进程下所有历史记录或时间猜测。
收尾是异步最终一致性，不承诺终态发生瞬间Backend即已更新；所有模型入口的跨轮收尾
确认屏障仍属独立流程整改。不能将持久投递实现解释为这些故障窗口已全部消除。

本合同覆盖有精确规范化注册/终态的跨服务投递、收尾和回执。不等于上述无终态事故、R4/F10
全部需求或独立发布认证完成，不授权生产部署、历史研究续跑或模型训练。
