# Post-U8 Agent 可靠性修复需求

状态：**PLANNED — 等待 U8 完成并合并后实施**  
类型：独立 maintenance package，不是 U9，不推进 Product Phase 97。  
建议分支：`fix/agent-reliability-post-u8`；必须从 U8 合并后的最新 `origin/main` 创建隔离工作树。

登记范围：第 1–11 节为 R1–R5 会话可靠性包；第 12 节登记独立的 S1–S3 指数股票池修复包。
两包均等待 U8 完成并合并，分别验收；R1–R5 的完成不表示 S1–S3 已完成。

## 1. 来源与处置决定

U8 生产观察发现一个完整的同会话故障链：专项研究子 Agent 在仍有工作的情况下达到固定
180 秒 wall-clock 上限；运行失败提示随后在下一轮开始后从 UI 时间线消失；用户以简短“继续”
恢复时，Gateway 丢弃了上一轮未回答的主题，新 DSH generation 因缺少 subject-bearing context
而读取同 owner/workspace 中不相关的既有对象。超时后，关联的持久 Agent run 仍停留在
`active`。没有发现跨 owner/workspace 读取，亦没有在该事故窗口创建 Artifact、训练、预测或回测。

维护者决定：U8 继续完成真实 24 小时观察和诚实收尾；本文件所列改造不在 U8 运行代码中实施，
待 U8 PR 合并后作为一个独立、统一的可靠性修复包执行。U8 不得声称这些缺陷已经修复，也不得
用零容器告警代替语义正确性结论。本处置只授权记录需求和实施顺序；不授权新的生产部署、
release/tag、数据库修复、删除历史会话或使用真实生产对话做模型评测。

## 2. 修复目标

1. 每一轮失败在公开会话时间线中保持可见，即使后续轮次已开始或完成。
2. 失败后“继续 / 重试 / 接着做”保留上一轮未回答主题，同时不重复提交已执行的写操作。
3. 子 Agent 超时从固定 wall-clock 误杀改为“可信活动续租 + 不可续租硬上限”。
4. 超时、取消、失败和迟到结果在 Runtime、WorkflowTrace 与 BYQ 持久 Agent run 间收敛到同一终态。
5. 用户每 60 秒得到诚实、无需模型生成的等待状态；系统心跳不能伪装成实际进展。
6. 不扩大 Product DSH 权限，不暴露 hidden reasoning/raw DSH events，不增加第二套 Agent harness。

## 3. R1 — 持久的逐轮失败时间线

当前 UI 从所有事件折叠出一个“最新运行状态”；后续 `session.started` / `session.result` 会让之前的
`session.failed` 提示消失。修复后：

- 每个 `session.failed`、`session.cancelled` 和丢弃结果必须成为可重放的逐轮 timeline outcome；
- outcome 显示时间、公开错误类别和“后续已继续”等状态，不冒充助手答案；
- outcome 不写入 Product assistant message，也不进入模型对话上下文；
- 刷新、重新登录、Gateway/Runtime 重启和后续成功轮次后仍可见；
- 若仅凭序列无法无歧义关联，扩展 BYQ WorkflowTrace public contract，给终态带稳定 `run_id`；
- raw DSH error、stack、工具参数、推理和密钥不得进入浏览器投影。

## 4. R2 — 未回答主题的显式恢复合同

不得继续把末尾 unanswered user message 静默删除。建立 framework-neutral 的失败轮次上下文：

- Gateway 从 BYQ 持久 conversation + WorkflowTrace 精确识别最近失败且未回答的 user turn；
- 恢复载荷区分 `completed_history`、`unanswered_turn`、`failure_run_id` 与当前用户消息；
- Runtime 生成的新 model-visible input 必须将未回答主题与当前消息分区，并声明当前消息优先；
- “继续 / 重试 / 接着做”等短续接承接 `unanswered_turn`；完全不同的新问题不得被旧主题绑架；
- 当前消息与未回答消息完全相同时只执行一次，使用稳定 retry/idempotency identity；
- 已确认但 outcome unknown 的写操作必须先查 BYQ 权威状态，不得因恢复自动重放；
- 任何过长、缺失或冲突的上下文 fail closed，并要求用户确认主题，不能猜测工作区对象；
- 不读取 DSH 私有历史来重建 Product 上下文，仍以 BYQ 公开消息和规范化 WorkflowTrace 为权威。

## 5. R3 — 进度感知的分层看门狗

初始默认参数作为资格测试基线；只有测量证据和明确配置变更才能调整：

| 时钟 | 默认值 | 是否续期 | 语义 |
|---|---:|---|---|
| UI 等待心跳 | 60 秒 | 不适用 | BYQ 自动显示“仍在处理”和最后可信活动距今时长 |
| 子 Agent inactivity lease | 180 秒 | 是 | 同一 child/run 的可信新活动续期；连续三个 UI 周期无活动才超时 |
| 单子 Agent hard cap | 600 秒 | 否 | 即使持续活动也不能无限占用 |
| 根回合 hard cap | 900 秒 | 否 | 覆盖全部 child 与父 Agent 收口；必须为父级总结保留时间 |

可信续租信号必须来自同一 child session / subagent run，且事件序号单调前进：

- DSH `subagent.started` / `subagent.finished`；
- child `step/start`、`step/end`、有效 assistant stream activity；
- child tool call/result 及具名工具自己的受限进度事件；
- 其他由 0.1.2 SDK 官方 `session.event` 明确提供、经 compatibility seam allowlist 的执行活动。

以下不得续租：BYQ 60 秒 UI 心跳、进程仍存活、父 Agent 的无关事件、重复/倒序事件、单纯状态轮询、
Product 客户端刷新，以及未经关联的任意子会话活动。不得把 hidden reasoning 内容公开；只使用其
“发生了新的可信事件”这一布尔/时间事实。

实现必须将当前 `active_subagent_calls: call_id -> started_at` 提升为每 child/run 独立状态，至少包含
`started_at`、`last_activity_at`、parent、child identity 和硬截止时间。若官方通知不能将并行 tool call
与 child 无歧义关联，应在 BYQ compatibility contract 中补足关联或限制并行委派；不能把一个 child
的活动错误续租给另一个卡死 child。

模型首 token、长工具调用和等待审批应使用明确状态/操作上限。等待人工审批不占用活跃模型回合；
需要更长执行的研究转成 BYQ durable job，而不是无限续租聊天进程。提高超时常量本身不构成修复。

## 6. R4 — 生命周期收敛与迟到事件

- inactivity/hard timeout 必须先标记精确 failure cause，再取消 child、关闭 owned harness/process；
- 关联 Workflow activity 必须从 `started/progress` 收敛为 `failed/cancelled`；
- 关联 BYQ `agent_runs` 必须从 `active` 转为显式 timeout/failure 终态并保留审计；
- 超时后的迟到 child result 不得写公开答案、更新对象或把 run 改回成功；
- resume 创建的新 private generation 不得写旧 generation；旧/新 owned process 必须可证明收口；
- 重复 timeout/cancel/late-result 处理必须幂等；transport outcome unknown 时读取 BYQ 权威状态；
- 不直接访问 DSH 侧 PostgreSQL，不让 DSH 写 BYQ business data，所有 domain transition 仍经 MCP/Backend。

## 7. R5 — 用户可见进度与诚实语义

每 60 秒的展示由 BYQ 时钟生成，建议包含：当前公开步骤、累计用时、最后一次可信活动距今时间。
它只能表达“系统仍在等待/观察”，不能声称已经完成新步骤。真实 activity 仍由规范化
WorkflowTrace 驱动。超时后展示明确类别：无进度超时、单 child 硬上限、根回合硬上限、模型/工具失败。

若下一条消息是模糊续接而系统无法唯一识别未回答主题，应要求一次主题确认，禁止自行选择“最近的”
ML study、Backtest、Strategy 或其他工作区对象。金融结果必须绑定明确对象 identity 后再回答。

## 8. 验收矩阵

### Keyless deterministic contract tests

1. child 在 59/119/179 秒产生可信活动：180 秒 inactivity lease 逐次续期。
2. 只有 UI heartbeat 或 process-alive：不得续期，180 秒失败。
3. 父 Agent 活动或另一个 child 活动：不得给目标 child 续期。
4. child 持续活动超过 600 秒：仍命中 child hard cap；根回合 900 秒同理。
5. 正常 `subagent.finished` 在截止边界与 timeout 竞争：只能有一个终态。
6. cancel、timeout、迟到 result 重复到达：公开答案/Domain mutation 至多一次且终态不反转。
7. 超时后 Runtime process、watchdog/thread、child map 和旧 generation writer 均收口。
8. BYQ `agent_runs`、公开 activity 和 Runtime terminal cause 一致；不留 stale `active`。
9. failed first turn + “继续”仍携带原主题；不得选择不相关工作区对象。
10. failed first turn + 完全相同重试不会重复 user message 或已确认 mutation。
11. failed turn + 明确新主题只执行新主题；模糊且多候选时要求确认。
12. 后续成功轮次、刷新和重启后，旧失败 outcome 仍显示且不进入模型 transcript。
13. Browser payload 不含 raw event、reasoning、tool args、credentials 或私有 child identity。

### Qualification and Product evidence

- Runtime Adapter、Gateway、Frontend 受影响组件完整 suite；architecture/contract tests 全绿；
- 0.1.1rc1 rollback 与 0.1.2rc1 current compatibility 均需明确测试，不能只测当前默认；
- 使用新 build identity，重新生成/绑定镜像和报告；不得修改 U7/U8 历史报告；
- 真实模型只允许既有授权范围内的合成用户、固定/经明确批准的合成提示和测试对象；
  不得发送本次生产对话、生产用户数据、真实对象内容或密钥；
- Chrome MCP 在真实 Product API 上验证 desktop/mobile：进度心跳、持久失败节点、继续承接主题、
  新主题不串线、最终答案和刷新重放；
- 故障注入验证 60/180/600/900 时钟可用虚拟单调时钟完成，CI 不以真实长 sleep 充当证据；
- 全量 local CI、required remote CI 和 ADR-0015/0059 当时仍有效的合并门禁全部通过。

## 9. 实施顺序与门禁

1. U8 先完成 24 小时观察、记录该缺陷仍未解决，并合并 U8 PR。
2. 从同步后的 `origin/main` 新建 `fix/agent-reliability-post-u8` 隔离工作树；不复用 U8 工作树。
3. 先提交失败测试和 framework-neutral contracts；评估是否需修订 ADR-0046/ADR-0018。
   若产生新的边界或例外，必须先有 Accepted ADR。
4. 实现 R1–R5 这一组紧耦合修复，不夹带新 DSH 功能或 Product Phase。
5. 新 build identity 下执行 keyless、双 release compatibility、合成模型和真实浏览器资格验证。
6. 创建独立 Draft PR，保留 U8 事故与所有失败测试历史；CI-green 后按届时有效授权/门禁处理。
7. 合并不等于部署。任何生产镜像切换、数据修复、会话删除或 release/tag 均需单独精确授权。

## 10. 明确非目标

- 不 fork/patch DeepSeek Harness，不创建第二套 generic Agent harness；
- 不要求模型每 60 秒消耗 token 主动“报平安”；
- 不把 UI heartbeat 当真实工作进度；
- 不通过单纯放大/关闭 timeout 掩盖生命周期缺陷；
- 不恢复或转换 DSH 私有 JSONL 作为 Product conversation authority；
- 不自动重跑失败研究、训练、预测、策略审批或回测；
- 不删除/改写本次生产会话、U7/U8 报告或失败证据；
- 不改变 Product DSH 权限、MCP domain boundary、数据库所有权或前端 API 边界。

## 11. 完成定义

只有 R1–R5 全部实现、上述矩阵通过、没有 stale run/process、模糊续接不再发生对象漂移、新构建已通过
完整资格验证，并在独立 PR 中保留证据时，才能将本修复包标记 `VERIFIED`。生产部署和部署后观察是
后续独立状态；没有相应授权时停在已合并/未部署，不能宣称生产已修复。

## 12. S1–S3 — 指数股票池 Agent 接入与自动更新闭环

状态：**PLANNED — 2026-09-07 追加登记，等待 U8 完成并合并后安排实施**。
建议实施分支：`fix/index-stock-pool-agent-refresh-post-u8`，使用新的隔离工作树和独立 PR。
本节是指数股票池修复包，不改变上述 R1–R5 的权限边界和完成定义，也不依赖购买更高积分账号。

### 12.1 只读诊断证据

维护者请求核查“建立中证500指数股票池”及“五年前成分”的最新会话。2026-09-07 的只读核查发现：

- 小巴回答只能创建 custom 池、指数池只能页面引导。这与
  `services/mcp/src/server.ts` 的 `byq_pool_create` 强制 `pool_type: custom`，以及
  `plugins/dsh-byq/skills/byq-product-guide/references/pools-and-strategies.md` 的限制一致。
  Backend 已有 `StockPoolProducerStore.create_index_pool`，因此是 Agent 接入缺口，不能归因于
  此次模型超时，也不能用 custom 池冒充持续跟踪指数的 index 池。
- `stock_pool_producer.py` 将指数池策略声明为 `on_validated_import`，但源码核查只找到创建和
  手动刷新入队，未找到已验证成分导入后自动触发该刷新任务的调用。
- 生产库已有沪深300 2026-08-31 的 verified 成分快照；现有 active 沪深300池的运行记录只有
  2026-08-29 的创建、手动刷新两次成功，实际使用的成分日期仍为 2026-07-31。这是自动更新
  未闭环的运行证据，不能因配置字段写着自动刷新就宣称功能完成。
- 中证500（`000905.SH`）当时仅有 2026-06-30、2026-07-31、2026-08-31 三份 verified 快照，
  每份 500 个成员；没有 2021 年成分。页面已有“截至日期”及 `requested_as_of`，Backend 也会
  选择不晚于该日期的已验证快照。小巴对页面历史日期能力的说明不完整；历史成分不足则是真实数据缺口。

这些是核查时点的事实，不表示未来数据状态。实施前重新检查生产版本、覆盖和运行记录；本文件不保存
生产会话全文、用户标识、凭据或原始 Provider 数据，也不授权将生产会话发送给模型做评测。

### 12.2 S1 — 小巴创建真实指数池

- 经 BeyondQuant MCP 接入封闭指数目录、指定日期的可用性查询、指数池创建和物化结果查询；
  复用现有 Backend producer，使用 trusted owner/workspace、明确用户意图、幂等键和审计。
- 用户要求“建立中证500指数股票池”时解析 canonical index identity，检查时点数据并创建 index 池，
  返回真实持久对象及物化状态。无需用户提供 500 个代码，也不让模型生成成分清单。
- 创建入队、等待数据、物化成功必须区分；只有真实快照完成后才能声称股票池已就绪。
- 补齐 capability catalog、role/tool allowlist、产品指南和相关说明，使小巴准确了解截至日期、
  历史快照、自动跟踪及当前数据缺口；不增加任意 Provider、数据库或股票池删除权限。

### 12.3 S2 — 成分导入驱动自动刷新

- 已验证指数成分快照入库后，为匹配指数的 active producer/pool 幂等排队刷新，由现有 Data Worker
  执行。定义并测试提交与入队之间的崩溃恢复，避免数据已入库却永久漏掉刷新。
- 提供从持久状态派生的有界补偿检查，发现“源快照已更新、股票池仍旧”时补排；复用现有任务设施。
- 新有效成分生成或复用不可变股票池快照，并推进当前版本；旧历史快照导入不得使当前版本倒退。
- 重复导入、并发 Worker、重启、失败重试不重复生成语义相同快照；inactive/deleted 池不得自动激活。
- 数据中心源成分日期、股票池当前成分日期、最近刷新、等待/失败原因在 Product API/UI 中可理解。
- 历史回测、策略和训练继续引用其冻结快照，不随股票池当前版本改变。明确区分“按历史日期取一次
  冻结快照”和“创建持续跟踪指数的池”，不能让后续更新悄悄改变用户要求的历史研究对象。

### 12.4 S3 — 历史成分准备与准确说明

- 按用户明确日期查询已验证历史覆盖；“五年前”等相对时间按 BYQ 时间合同解析，并公开使用日期。
- 缺少目标时点数据时报告具体缺口，通过受授权的 BYQ 数据准备流程提出有界历史成分需求、查询进度，
  准备完成后再创建或物化；现有 data-demand 若不支持指数成分，应先扩展其封闭合同。
- 先只读检查和分类 Community 成分缓存；符合来源、单位、schema、时点和完整性要求时，遵循
  validate → logical migration → incremental refresh。无法验证的数据隔离，不重复下载已验证缓存。
- 当前成分不得回填到五年前；“五年前的一次成分池”与“五年期间随调仓变化的历史成分序列”必须区分。
  后者需完整时间序列和相应消费合同，不能用单一静态池宣称完成。

### 12.5 验收与实施门禁

1. 按仓库流程先检查 Community 对应页面、producer、缓存及测试并分类；评估 ADR-0031/0032/0041/0042/
   0045 的影响，新增 Agent 写权限、历史准备或边界变化在实现前由 Accepted ADR 明确。
2. 测试覆盖小巴创建中证500 index 池、重复请求幂等、owner/workspace 隔离、数据缺失和物化失败，
   证明不会降格成 custom 池或伪造完成。
3. 集成测试覆盖新 verified 成分导入 → 自动入队 → Worker → 新池快照；包含重复/乱序导入、
   commit 后崩溃、重启补偿、inactive/deleted、旧引用不变及当前版本不倒退。
4. 用合成历史夹具验证截至日期选择、未来数据拒绝、历史数据缺口、准备进度和恢复幂等；
   实际历史数据尚未取得时保持待验收，不用最新500只代替。
5. 真实 Product API 与 Chrome MCP desktop/mobile 验证创建、日期选择、刷新历史、源/池日期及状态；
   Browser 仅走 Gateway/Product API，Agent 仅走 MCP，Provider 仅由可信 Data Worker 调用。
6. 合成模型评测提示、Provider 访问、历史回填及生产部署按各自授权执行；此次只授权登记需求。
   不修改 U8 运行代码、历史报告或生产业务数据。
7. S1–S3 分项记录实现、验证和部署状态。仅当真实创建、自动更新、历史准备和用户说明形成闭环，
   且上述证据齐备时，才可将该包标记 `VERIFIED`；R1–R5 或 Tushare 扩展包完成不能代替本包验收。
