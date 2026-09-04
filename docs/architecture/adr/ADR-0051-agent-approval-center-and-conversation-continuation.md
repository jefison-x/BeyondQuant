# ADR-0051：Agent 审批中心与原会话可靠续接

- Status: Accepted
- Date: 2026-09-04
- Accepted: 2026-09-04
- Decision scope: Phase 91 Product Agent 审批入口、资源绑定、会话续接与业务页操作语义
- Related: ADR-0009、ADR-0018、ADR-0024、ADR-0031、ADR-0033、ADR-0043、ADR-0044、ADR-0046、ADR-0050

## 背景

当前 Product 同时存在三种相互混淆的交互：小巴在会话中发起受控操作，用户到具体业务页寻找“批准”按钮；
策略和模型研究页把领域审批当成显式工作流步骤；全局审批铃铛虽可记录 Agent decision，却不会可靠地回到原会话
继续执行。用户因此需要在会话、业务页和审批中心之间往返，且一次审批可能只改变 Agent approval 状态，没有
形成准确的 Strategy/ML domain approval 或后续执行。

只读 Community 的 `GlobalApprovalCenter.vue`、`ApprovalManagementPanel.vue` 与 `AgentView.vue` 证明了集中收件箱、
角标、focus/visibility 刷新和本地化动作摘要的 UX 价值，分类为 `PORT_UX`。其“批准并立即执行”、raw arguments、
direct Agent API 和在会话抽屉内重复审批的实现分类为 `REPLACE`/`DROP`；它不能替代 BYQ 的 Product API、
WorkflowTrace、domain invariant 或 durable conversation。

## 决策

1. 全局审批中心是 Product 中唯一呈现 Agent 人工“批准/拒绝”控件的位置。股票池、策略、模型研究、回测等业务页
   不再提供审批按钮；它们只保留用户亲自发起的创建、开始、取消、归档、停用和删除等业务操作。
2. 用户在业务页亲自点击“开始训练/开始回测”等操作时，Product 先明确确认，再由 Backend 在同一可信 actor 下按
   既有领域 invariant 记录必要的 domain approval，然后继续业务流程。这不是 Agent approval，也不进入铃铛收件箱。
3. Agent approval 与 Strategy/ML domain approval 保持两个状态机。Agent approval 只表达某个 Agent run 对一个精确
   action/resource 的人工授权；批准后小巴必须经 BeyondQuant MCP 使用该 approval ID，重新读取权威状态并物化对应
   domain approval。DSH 不直接访问 PostgreSQL，也不绕过 MCP。
4. 新建 Agent approval 可绑定成对的 `resource_type/resource_id`。需要物化 domain approval 的动作必须校验 owner、
   actor、原 runtime session、action、resource type/id、human reviewer 和 authorized outcome 全部一致；一个宽泛或来自
   其他会话的 approval 不能授权当前资源。
5. Agent approval decision 持久化独立的 continuation 状态：`not_requested -> queued -> submitting -> submitted|failed`。
   Gateway 取得原 runtime session 对应的公开 durable conversation，使用服务端固定 continuation instruction 续接同一
   会话；该 instruction 不是伪造的用户消息，不写入用户对话历史，也不向 Browser 暴露 runtime identity。
6. continuation prompt 使用 approval ID 派生的 runtime idempotency key。响应丢失时重试返回原 run ID，不重复执行；
   `submitting` lease 超过 30 秒可重新认领。前端只按持久状态延迟重试，不使用固定“六次”等调用次数上限；离开页面时
   停止本地定时器，重新进入含 approval deep link 的原会话可继续恢复。
7. 审批列表由 Backend owner/status 过滤并分页，Gateway 只投影 allowlist 字段和公开 conversation identity。同一页中
   相同 runtime session 的 conversation lookup 去重。Header 在 SSE 产生审批卡、focus、visibility 和 15 秒低频轮询时
   更新实时待办角标；只查询 pending page，不下载全部历史。
8. 审批铃铛仅在有待办时显示高注意力数字角标。会话活动角标只统计仍在运行/等待审批的活动，并使用中性灰色；已完成
   历史不占用角标，避免和真正待处理审批竞争注意力。
9. Browser 始终只访问 Gateway/Product API；frontend 不依赖 raw DSH event。Runtime Adapter 的 prompt idempotency 是
   通用传输可靠性能力，不承载 BYQ 业务授权或 domain invariant。

## 验收

- 组件测试证明业务页不存在审批按钮，策略回测与 ML 训练由直接业务动作完成必要的内部领域记录；
- Backend 测试证明资源/会话/owner/actor 精确绑定、决策者隔离、分页、pending count 和 continuation 状态转换；
- Runtime 测试证明同一 idempotency key 在运行中和完成后都返回同一 run，内容变化则拒绝；
- Gateway 测试证明 approval projection 不泄漏 runtime session，decision 回原 conversation，失败可恢复且不重复 prompt；
- MCP/role/skill 测试证明 ML strategy approval 只能在全局人工批准后物化，Agent 不再要求用户打开业务页审批；
- 真实 Product API 和 Chrome desktop/mobile review 证明铃铛、审批、回原会话、灰色活动角标、same-origin Network 和空
  Console；审批列表首屏不得加载全部历史或大对象。

## 拒绝的替代方案

- 在每个业务页复制审批按钮：入口分散且把 Agent 授权与用户主动操作混为一谈。
- approval decision 直接在 Gateway 执行业务命令：跳过小巴的权威状态复查、工具审计和对话解释。
- 让 DSH 直接写数据库或调用 Backend：违反 MCP 和 Product/Domain 边界。
- 把 continuation 写成用户消息：伪造用户意图并污染 durable conversation。
- 使用固定重试次数或内存-only callback：繁忙会话或进程重启后会无辜停止。
- 复制 Community raw arguments/“批准并执行”：暴露内部 schema 且无法证明精确领域授权。

## 回滚

先关闭自动 continuation 和前端 deep-link retry，保留 approval decision、resource binding、domain artifacts 与审计为只读；
再恢复为“审批完成后提示用户回原会话”的降级体验。不得删除已决 approval、重写 reviewer、清除 domain approval 或
重新开放 DSH/Browser 直连。业务页仍保持无 Agent 审批按钮；若必须恢复独立领域操作，只能恢复用户主动业务动作，不能
重新引入分散的 Agent approval 控件。
