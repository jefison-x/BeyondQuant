# Agent 停止后恢复旧会话及终态重连问题

状态：**修复候选已实现；隔离真实 DSH 正常释放与硬取消的终态历史浏览器检查各 1/1 通过。原生产双均线历史案例未重放，尚未部署。**

记录日期：2026-10-03。以下诊断和原始计划记录修复前的只读观察；当前候选实现
及隔离验证见[发布后整改需求文档](post-release-fix-requirements.md)。脚本化 provider
驱动的真实 DSH 终态已通过隔离验收；双均线原生产历史案例未在候选代码上重放，
未部署或阶段收口。

## 现象与身份

受影响会话标题为“今天南京天气？”。停止后继续发送出现 runtime 报错，
查看该历史会话时事件流反复返回 409。

- Conversation：`conversation_f3c800e02315495b9516221450760eba`
- Runtime session：`byq-session-a13a311ca34d484aac1f7bd571f9de7f`
- Trace：`byq-trace-a47048e477c842e2b9f3b858cacf99e1`
- 取消的 root run：`ff67d96d014f482a95a92355f997a57f`
- 诊断源码/已部署 main：`4359b23ebc957194a90ea7b760f7c0bd89c3401a`

## 已确认事实

以下时间为北京时间，2026-10-03：

| 时间 | 权威记录或服务日志 |
|---|---|
| 14:09:16 | 第一轮天气回答完成，规范化 trace 为 `session.result`。 |
| 14:10:21 | 下一轮 root 开始。 |
| 14:10:27 | 取消请求成功；trace sequence 20 为 `session.cancelled`，`mode=hard`，`resume=new-agent-session-after-interrupted`。 |
| 14:10:27 | 紧随取消的旧会话恢复请求返回 409。 |
| 14:11:03 / 14:11:05 / 14:11:50 | 对旧会话的后续发送返回 409。 |
| 14:12:26 | trace sequence 21 为 `session.closed`，`reason=released`。 |
| 14:28–14:29 | 历史会话事件订阅及 attach-live-only 重复返回 409。 |

Backend `agent_runtime_turns` 中该 root 为 `cancelled`、authority 为 `closed`。
该会话没有 `session.failed` 事件。诊断时 Adapter ready、发布身份匹配、模型凭据
已配置；另一个“看看这两天美股怎么样？”会话有四个完成的 root。
这些证据支持停止后的状态处理缺陷，没有表明全局 Runtime 或模型凭据失效。

## 根因与受影响边界

1. [`AgentView.vue`](../../apps/frontend/src/views/AgentView.vue) 的
   `stopCurrentRun` 在硬取消成功后立即调用 `resumeSession`（基线行 444–445）。
   硬取消已经结束原 Agent 进程；Adapter `resume_session` 按当前合同拒绝恢复
   interrupted 会话。该拒绝符合合同，前端操作序列不符合合同。
2. 同文件 `maintainStream`（基线行 174–183）只把 401/403/404/410 当成终止错误，
   没有识别 `agent_session_interrupted`，因此对永久失效会话持续重连。
3. [`api/agent.ts`](../../apps/frontend/src/api/agent.ts) 的事件流错误没有保留结构化
   Product 错误码；一般 JSON 错误也未完整保留该错误码。修复不能将所有 409
   一律作为终态，须区分会话中断与可恢复的忙碌等冲突。
4. Gateway 的历史消息读取不要求恢复原 runtime，但事件订阅会尝试
   attach-live-only。后续需核对历史查看与活动订阅的边界，避免为查看历史而恢复
   已结束会话或循环发送无效订阅。

相关服务源码：[`runtime.py`](../../services/runtime-adapter/app/runtime.py) 的
`cancel_session` / `resume_session` / `attach_live_session`，以及
[`Gateway main.py`](../../services/gateway/app/main.py) 的
`_restore_product_session` / `_raise_agent_session_interrupted` / workflow events 路由。

## 原始最小修复与验收范围（当前进展见整改需求文档）

- 停止成功后正确结束本轮界面状态，给出新建 Agent 会话的明确入口/提示，避免
  自动恢复已结束的原 DSH 会话。
- 保留并识别 Product 结构化错误码；终态结束重连，可恢复错误仍按有界策略处理。
- 历史消息继续可读；旧请求不自动重放。业务 Job 独立保留，新授权会话按同一
  `job_id` 查询 Job / Artifact。
- 先完成硬取消、终态订阅、暂时忙碌、普通断线重连的定向合同测试，再验证受影响
  的真实 Gateway/Product API 浏览器流程；按 Tester → 独立 Reviewer → Root 验收。
  不因本问题默认重跑有效 A–D/F6、完整环境或行情下载。

临时处理：新建会话并给出新的明确指令；旧消息保留。如涉及已有业务 Job，先按
准确 Job ID 查询，不自动重放结果未知的业务请求。

## 原始只读证据

原始记录保留在宿主私有目录 `/tmp/byq-live-runtime-error-readonly-20261003/`：

- `receipt.json`：会话元数据、权威 root 状态、Adapter 状态及有界日志。
- `cancel-lifecycle-receipt.json`：21 个规范化 trace 事件的计数及生命周期摘录，
  硬取消与 released 的精确字段如上。
- `runtime-adapter-redacted.log`：SHA-256
  `2ae1bd977f496aee9296c2f11ce21e2c94225f42428987a89eddc70dc026084a`。
- `backend-redacted.log`：SHA-256
  `d97310a25da1636efde682218f8e603bc24245e0217d3d5d0cdfc811a8c1c9e6`。

完整日志、用户消息和凭据不纳入此文档。脱敏日志对包含 `task-` 的路由片段存在
过度遮盖，不能据此推断路由损坏；本问题的取消、恢复及 events 状态和规范化
生命周期证据不依赖该片段。`/tmp` 不是长期归档；本文保存了修复所需的关键事实。

## 补充实际案例：双均线研究会话正常释放后重连

2026-10-03 维护者要求核对“建立一个双均线研究策略，同步近三年的数据，完成回测分析。”
是否为同一问题。本次只读观察确认：**复现同一终态重连缺陷，但未复现硬取消后
立即 resume 的触发路径。** 后续 R1 验收必须覆盖正常释放与硬取消两种场景。

- Conversation：`conversation_366894ff6c1f46399523e33d364e637f`
- Runtime session：`byq-session-ba36364386604467a49e8caa18c9f6bc`
- Trace：`byq-trace-64b85a3e9bce43c590dd742cab420c15`
- Root：`22f9e37b5fd84a518ca588fdb16eb551`、`064a7434ccbd44e791dc2adbf2fa051a`。
- Backend 两个 root 都为 `completed`，authority 为 `closed`；规范化 trace 有两次
  `session.result`，没有 `session.cancelled` 或 `session.failed`。
- 北京时间 15:09:36、15:11:02 两轮正常完成；15:12:38 `session.closed`，
  `reason=released`，Adapter release 请求返回 200。
- 保存的有界 Gateway 日志窗口中，该 conversation 的 events 有 304 次 409，
  时间为 15:15:51 至 15:20:44。这个窗口不是完整日志，不将首条记录冒称首次失败。
  同期历史会话 GET 返回 200，说明消息可读与 live subscription 失效需分别处理。
- 观察时 Adapter ready、发布身份匹配，活动 prompt 为 0。没有触发新模型、
  Job、数据同步、取消、release 或浏览器连接；日志中的动作来自已有产品使用。

### 数据阻塞是另一项事实

该研究 Task `task_a54e5d2918c54d458f176f968a5100d8` 的持久 progress 为 `blocked`，
原因为缺证券主数据。Agent 最近回答在 15:11:02 完成；实际主数据随后于 15:12:28
建成快照、15:12:32 同步 Job 完成。因此不能用后来存在的主数据推断早先回答不实。

此次只读检查时，证券主数据有 5910 条、日线有 16677 条；这是后续新增数据，
不能继续沿用早先空库结论，也不能据总行数宣称目标股票池近三年已就绪。
Task 仍保存原阻塞状态；需要在后续明确用户指令及权限下重新核对目标范围与
任务状态。本次没有重放同步/回测或承诺自动推进。

私有只读证据：`/tmp/byq-live-ma-session-readonly-20261003-072031/` 中的
`receipt.json`、`activity-log-receipt.json`、`data-execution-receipt.json` 和
`data-timing-receipt.json`。初版只读查询器误用 audit 的不存在列 `session_id`，
在 SELECT 阶段失败；失败版本保留，改用权威 run_id 后完成读取。该观察器错误
不代表产品故障，未写入数据库或重放任何业务操作。

原始只读诊断时修复尚未执行；旧会话关闭后不得通过恢复 DSH 私有上下文来迁就前端。
