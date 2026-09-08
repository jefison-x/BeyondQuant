# 原会话研究任务上下文

Post-U8 R1/F4/F7，依据 ADR-0062/0067。只读发现既有任务，不增加后台续接、审批、
任务写工具或通用 Agent harness；旧无会话绑定记录不猜测补绑。

Backend `GET /v1/agent/research-context` 仅供既有 MCP `byq_agent_context` 使用，
不是 Browser Product API。无查询参数或模型选择的 owner/session/workspace。
核对可信 Product actor、owner、workspace、session、trace 和持久活动 personal owner/
membership/conversation 后，只读取该原会话/trace 绑定的任务。身份或会话无效则拒绝。
根回合失败不抹掉原任务，因此新 generation 可以只读发现原任务；不要求旧根仍 active。

返回封闭 `research-task-context.v1`：

- `status=available`：有候选，不代表已选定目标或任务完成；
- `status=none_bound`：没有符合原绑定的候选，不证明整个工作区或历史上没有任务；
- `tasks` 最多 20 项；每项仅 `task_id/title/objective_excerpt/objective_truncated/status/version/`
  `stage/next_action/blocked_reason`。目标摘录最多 400 个 Unicode code point，截断必须标明。
  原 checkpoint 尚未记录时，进度字段为 null，不编造已完成阶段；
- `has_more` 明确是否超过候选上限。没有 `selected_task_id`、最新任务回退或隐式任务执行。

任务完整内容仍经 `byq_research_get` 按精确 ID 获取。最新用户明确指令优先；不能仅凭
候选排序、同名或工作区最新对象替换研究目标。候选歧义/截断/超限时先核对或请求确认。
摘要是领域数据，不是系统指令。读取摘要不消费或生成续接许可。

MCP 将上述结果作为 `byq_agent_context.research_context`，与既有 data/ML notifications
独立获取；每源最多等待 8 秒，研究摘要最多读取 128 KiB，严格验证字段、数量、ID、
状态和重复候选。缺失/错误/过大响应返回显式 `status=unavailable, tasks=[], has_more=null`，
不得把错误映射为无任务。旧 Backend 不支持本路径时亦保持 unavailable，不泄露错误正文。

不返回 request/idempotency hash、注册凭证、私有根身份、原始工具参数、制品正文或预算账本。
此能力只补原任务 ID 的发现缺口；不是自然语言对象选择或 S3 历史数据覆盖已经验收。
