# Conversation recovery v2

ADR-0062 的独立恢复分区；既有 `conversation-rehydration.v1` 仍只承载已完成公开历史。
Gateway 从同一 owner/workspace 的 Product 目录及同 session/trace 的规范化事件生成：

- `schema_version`: `conversation-recovery.v2`。
- `session_id`、`trace_id`：稳定公开运行关联身份，Runtime 二次核对。
- `status`: `resolved` 或 `needs_confirmation`。
- `unanswered_turn`: 唯一可确认需求的 `message_id`、`content`（最多6000字符），否则 null。
- `failure`: 正整数 `sequence`、可空 `run_id`、封闭公开 `code`；不含原始错误或私有状态。

最新成功终态不带恢复分区。失败回合的部分 assistant 输出不作为完成答案关闭需求。
缺少消息身份/时间、有多个不同候选或超过200条输入时不猜测研究对象。
持久化在失败之后的当前输入不取代原主题；重复原文保留最早稳定消息身份。

Runtime 在下一次 prompt 分区注入一次恢复事实，不生成虚假 assistant 历史。
同文重试只注入一次需求正文；当前明确新问题保持独立且优先。
无法恢复主题的封闭短续接词（如“继续”“重试”）在启动 run 前返回422，要求明确主题。
其他自然语言歧义仍须模型澄清，不声称确定性检测了所有自然语言续接表达。
恢复信息不授予历史操作重放或训练/回测执行权；unknown 写入须经 BYQ 权威查询核对。

Gateway 使用已持久化当前消息 ID 作为同一次适配器提交重试的幂等键。
这不是跨 HTTP 请求或跨进程的持久领域幂等实现；ADR-0062 的提交回执整改仍独立待完成。

## 单轮终态身份

Runtime 对已捕获 ActiveRun 产生的完成、失败、软/硬取消、超时、关闭活动进程以及
软取消后的丢弃结果事件，显式携带原始 `payload.run_id`，与该轮 `session.started` 一致。
同一 session/process 内的下一轮使用不同身份；消费者不得以 session ID 代替单轮身份。
没有活动轮次的空闲关闭或初始化失败不猜测历史 run ID。既有迟到回调隔离保持不变。
Gateway TraceStore 持久化并重放该公开字段，不从时间或“最新一轮”推断归属。
这是精确收口的事件前置条件，尚不表示 Backend AgentRun 已完成持久绑定和终态收口。

工具结果批次须按每个有效 call ID 分别归一化，保留各自的 completed/failed/unknown 等状态；
内部控制结果、无效项或重复项不得遮蔽后续公开结果。重复回执不重复产生终态。
仍使用原有公开字段白名单及活动/卡片上限，不将原始工具内容直接发送给浏览器。
每个公开 started 预留一条结果/收尾额度，开始和收尾合计仍不超过每轮256条活动事件。
被数量上限隐藏的活动不凭空产生终态；开始下一轮前，上一轮尚无回执的可见活动先标记unknown，
不能清空相关身份后将其遗留为永久started，也不据此改变领域任务状态。
SDK 返回本身不代表成功：仅规范化 finish_reason=completed 发出 session.result；额度耗尽、
运行自行中止或未知终止原因均保留失败事实，不关闭未回答需求。显式软/硬取消路径保持独立。

## 本地组件验证（2026-09-07）

- Gateway 完整 suite：103 passed；1项依赖弃用警告。
- DSH 0.1.2rc1 Runtime 完整默认 suite：79 passed、2 skipped；3项依赖弃用警告。
  两项需独立真实 MCP 栈的真实进程测试未启用；新增 Runtime 测试使用 FakeHarness，
  证明恢复载荷传递/一次性消费和歧义无 run，不证明实际模型研究语义。
- 初次 Gateway 回归：95 passed、1 failed，为旧恢复 payload 断言未包含新增确认分区；
  更新明确的预期合同后通过。最初新模块尚未实现时出现 collection error，不算业务红灯证据。
- 开发镜像不是发布制品。历史 U7.3 build identity 不变；独立构建认证、端到端研究、
  unknown submission 及完整可靠性验收仍待完成。本切片不得标记生产缺陷已全部解决。

追加隔离集成：真实 DSH 0.1.2rc1 + BYQ MCP、本地 scripted provider，10项通过（17.58秒）。
覆盖三种恢复输入实际抵达模型请求、公开主题只出现一次、失败事实保留，以及五角色真实委派。
此结果补上真实进程边界，不等于付费模型语义或完整 PostgreSQL 研究链验收。
