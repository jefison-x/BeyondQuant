# 会话、回合与内部运行时 Gateway 入口

2026-09-16，本地维护；Product Phase 97 不变。
审计 `services/gateway/app/main.py` 19 条入口：存活/就绪、产品会话 CRUD、回合/续播/取消、
工作流 SSE，以及私有运行时兼容 seam。

## 源码核对

- `healthz`/`readyz` 为公开存活/就绪，仅报告服务与认证/runtime 配置状态，不暴露内部 schema。
- 产品会话入口经 `_trusted_request_identity` 派生 owner/workspace；会话创建/回合提交受
  `require_chat_admission` 维护门禁。创建时先建 runtime 会话再建持久 conversation，
  catalog 失败会 release 运行时进程，不泄漏。
- `submit_product_turn`（1254，202）：先快照恢复上下文，再持久化消息；用持久化 `message_id`
  作 prompt 原键；运行时丢失(404)重建后同键重发；≥500 结果未确认时读取适配器原键回执，
  无回执返回 `prompt_outcome_unknown`，不重复发送。
- `resume`/`cancel`/`delete`：resume 丢失运行时后重建；cancel 支持 hard/soft；delete 先 release
  运行时（404 容忍）再删持久会话与 trace。
- `product_workflow_events`（1388）：SSE 仅推送 normalized `workflow-trace` 信封（不含原始 DSH 事件），
  支持 `Last-Event-ID` 续播、心跳与空闲释放；长连接为有意设计。
- `/internal/runtime/*` 为私有兼容 seam（内部网络），不承载产品浏览器流量，也不让 DSH schema 越界。

## 本批验证

- `test_chat_admission.py`、`test_task_continuation_delivery.py`、`test_agent_lifecycle_delivery.py`、
  `test_answer_delivery.py`、`test_conversation_recovery.py`、`test_trace_store.py`。
- H1–H3 交接/续接本地验收见 [research-handoff-h2](../research-handoff-h2/AUDIT.md)、
  [research-handoff-h3](../research-handoff-h3/AUDIT.md) 与 [agent-stream-recovery](../agent-stream-recovery)。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。

## 登记与限制

- 台账新增会话/回合/内部运行时 19 条 Gateway 入口。
- 仅登记这些；Backend/DSH 内部入口、其他族、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
