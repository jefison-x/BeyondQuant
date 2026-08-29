# ADR-0033：Product Agent 公共回答与活动投影

- Status: Accepted
- Date: 2026-08-26
- Accepted: 2026-08-26
- Decision scope: Phase 60 public answer/activity projection
- Related: ADR-0003、ADR-0009、ADR-0018、ADR-0024、ADR-0032

## 背景

Phase 59 的真实浏览器旅程证明估值与基本面数据合同可信，但公开对话混入了英文
`Data retrieved` 前言、authorize/audit 执行叙述和 raw coverage/field keys。活动抽屉还
展示英文 phase/state。Domain 数据、工具授权和审计均正确；问题来自 Product projection
把 DSH 每个模型步骤的文字都视为最终回答，以及公开活动保留了内部控制能力。

固定 DSH `0.1.1-rc.1` 的事件合同提供可靠边界：每次 provider step 产生一条完整
`assistant/message`；带 `tool-call` content block 的消息是工具步骤，无 tool-call 的文本
消息才是该轮最终回答。该结构信号比基于自然语言猜测“思考过程”更稳定，也不需要修改或
fork DSH。

只读 Community 审计表明其 `AgentThinking` 将 tool name、control contract 和 reasoning
标签直接显示给用户。可复用的是“在回答旁提供可折叠公开进度”的 UX，不可复用 raw Agent
event、tool identifier、内部 API、PydanticAI/Hermes runtime 或执行状态模型。

## 决策

### 1. 最终回答使用结构边界，不使用文本猜测

Runtime Adapter 继续是唯一读取 raw DSH notification 的组件。它只将不含 `tool-call`
block 的 text-only `assistant/message` 投影为 `agent.output.delta`。同一步中即使存在 text，
只要还包含 tool call，整段文字均视为内部执行叙述，不进入 Browser、Gateway persistence
或 conversation replay。

Reasoning block、tool arguments/results、provider object、prompt、stack trace 和 raw event
仍全部丢弃。不得实现 chain-of-thought classifier、第二 Agent harness 或基于中英文关键词
推断 model reasoning。

### 2. 公共术语是封闭的 Product projection

Framework-neutral Contract 维护一个封闭的研究字段标签表，将
`coverage.usable=false`、`coverage_unverified`、`pe_ttm`、`debt_to_assets` 等当前已接受
字段转换为普通投资者可理解的中文标签。转换不改变 symbol、日期、报告期、数值、正负号、
null、缺失原因或排名结论。

Runtime Adapter 在 UTF-8 fragment split 前执行转换。Gateway 在 persistence/streaming 前
再次执行相同幂等转换，并对仍存在的 `byq_*`/`mcp__*`、raw `coverage.*`、DSH、MCP、
WorkflowTrace、Artifact ID token fail closed 为同 sequence 的 `session.progress`。Gateway
不修饰或重算 Domain result。

### 3. Activity 只呈现用户有价值的领域进度

`byq_agent_context`、role catalogue、run start、authorize 和 audit 等控制动作仍真实执行、
持久化审计，但不生成公开 activity。Unknown tool 也不生成 generic“调用受控能力”噪声。
只有 allow-listed domain capability 产生已本地化 label，例如“读取估值数据”“校验策略”或
“分析回测证据”。`workflow-activity.v1` 的 optional raw capability field 不再由 Adapter
发出；既有 replay event 仍兼容。

Frontend 将 closed phase/state enums 映射为中文用户标签，不直接显示 `select`、
`completed` 等 Contract token。Activity 仍按 `activity_id` fold started/completed，保持
有界、可重放、无 hidden reasoning。

2026-08-29 maintenance clarification：`workflow-activity.v1` 可附加 Adapter-owned 的
`agent_label`、`plugin_label`、`skill_label`，但只能由实际观察到的 allow-listed capability
映射为中文 Product label。该信息用于解释“由谁、通过哪类受控能力执行”，不是 raw DSH
tool/package/role identity，也不证明未发生的 Skill/插件调用；tool argument/result、控制动作
和 hidden reasoning 仍保持不可见。

### 4. DSH skill 明确一次性最终回答协议

BYQ role skill 与相关 persona 要求：tool step 只发 tool call，不写授权、审计、选择工具或
过渡前言；工具工作完成后只输出一次 text-only 用户回答；研究答案使用投资术语而非 raw
coverage/provider field key。这是 UX 约束，不替代 Backend authorization、audit、data
completeness 或 point-in-time invariant。

### 5. 保留用户有价值的失败与时点信息

投影不得删除数据日期、报告期、公告/生效日期、来源、缺失 symbol/field、失败原因、同步
建议、风险限制或“不可比较”结论。Domain 返回缺失时仍必须诚实说明并指向 Data Center；
不得用清理内部术语为由把失败伪装成成功或填充数据。

## 验收

- Adapter contract test：带 tool call 的英文/中文执行叙述不产生 answer event；最终回答
  保留日期、数值、负号和缺失事实；reasoning/tool data 不泄漏。
- Gateway contract test：raw research keys 被本地化；未知内部 token 同 sequence fail
  closed，且不持久化原文。
- Activity contract/frontend test：authorize/audit/unknown tool 不公开；估值/基本面等领域
  活动可见；phase/state 中文化且无 raw capability。
- Skill/runtime smoke：composition 无 coding/source-write 扩权，工具仍逐动作授权和审计。
- 真实 Product browser：连续价格→估值→基本面缺失旅程不再显示 Phase 59 泄漏，回答与
  persisted data 一致，Console 无异常，Network 仅 same-origin Product API。

## 非目标

- 不改变 Domain result、MCP schema、role permission、Approval、数据同步或 Backtest；
- 不暴露或生成 hidden reasoning；
- 不添加通用 content-moderation/translation/model gateway；
- 不迁移 Community Agent runtime、message store 或 `AgentThinking` tool-name surface；
- 不授权 release、tag、production publication 或 Phase 61。

## 后果与回滚

Product conversation 只保存最终用户回答和有意义的领域进度，内部审计仍可在受控 Operations
surface 查询。回滚可恢复旧 Adapter activity/answer projector 和 frontend label renderer；
Domain 数据、DSH sessions、audit rows 与已持久化 WorkflowTrace 不改写、不删除。

## Acceptance record

维护者已授权按现有路线图自动执行 Phase 60。本 ADR 接受上述最小 projection hardening；
它不改变 v1.0 release gate，也不创建后续 Product Phase。
