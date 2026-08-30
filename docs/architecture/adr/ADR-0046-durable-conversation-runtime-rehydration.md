# ADR-0046：Durable Conversation Runtime Rehydration

- Status: Accepted
- Date: 2026-08-30
- Decision scope: Phase 81 Product conversation lifecycle and WorkflowTrace failure projection
- Related: ADR-0003、ADR-0024、ADR-0033

## 背景

Phase 80 后的真实生产会话证明：首轮完成并经过有界 idle release 后，Gateway 会用稳定的
BYQ runtime session identity 重建 DSH process。准确固定的 DSH `0.1.1-rc.1` JSON-RPC
carrier 在 `session/prompt` 中调用 `ctx.agents.create`，没有公开 persisted-session resume
operation；同一 identity 已有 append-only session log 时，下一轮会在模型调用前立即以
`turn/end: error` 结束。当前 Runtime Adapter 又把该 raw reason 降级成
`turn.completed: completed`，之后只给 Browser `model-run-failed`，导致 Product 错误文案错误
建议用户修改问题。

该问题不是 Domain、MCP、数据准备或模型输入问题。修复不得 fork DSH、patch 官方
JSON-RPC protocol、长期保留无界 idle process，或让 Gateway/Browser 读取 raw DSH log。

## 决策

1. 稳定的 BYQ session/trace identity 与每个 DSH process generation 的私有 session identity
   分离。fresh conversation 首代可以共用 identity；当 normalized WorkflowTrace 已有 sequence
   时，重建 process 必须使用新的 `resume-<uuid>` 私有 identity 和独立 session directory。
2. Gateway 只从 BYQ durable Product conversation catalog 投影已经完成、用户可见的
   `user`/`assistant` 消息。未得到 assistant answer 的尾部 user turn 不进入恢复上下文，避免
   retry 时重复注入。
3. `conversation-rehydration.v1` 最多保留最近 20 条消息、单条 6,000 字符、总计 24,000
   字符。Gateway 从最近消息向前取完整有界窗口；Runtime Adapter 再次严格验证字段、角色与
   上限。raw DSH event、tool argument、reasoning、credential、domain private state 均不得进入。
4. 新 generation 的第一次 prompt 将该公开历史作为明确标记的只读对话上下文，并把当前
   user message 标为优先输入。它恢复 Product conversation semantics，不声称恢复 DSH
   hidden state、tool cache、subagent 或未完成操作。
5. failed/interrupted runtime 的显式 resume 同样创建新的私有 generation，并由 Gateway
   重新提供当前 durable conversation context。对 ready runtime 的幂等 resume 只刷新待用
   context，不创建第二 process。
6. DSH `turn/end.reason.kind=error` 必须安全映射为 BYQ `failed`，未知 reason 也 fail closed，
   不得伪装为 completed。Browser 文案明确运行故障与用户问题表述无关。
7. Product Browser 仍只使用 Gateway/Product API；Gateway 不 import DSH SDK、不解析 raw
   event、不读 DSH persistence。Runtime Adapter 继续是唯一 SDK/process/normalization owner。

## 未选择方案

- 不修改或 fork `@deepseek-ai/dsh-sdk-jsonrpc-server` 增加私有 resume method；这会违反
  exact-pin 和不 fork DSH 边界。
- 不无限延长 idle process 生命周期；这不能真正修复 restart/deploy，并会产生无界内存占用。
- 不直接读取或转换 DSH JSONL 为 Browser/Product history；raw DSH schema 不是 BYQ Contract。
- 不把旧 Community Agent runtime、PydanticAI 或 workflow persistence 重新引入。

## 验收

- Runtime contract 证明已有 sequence 使用新的私有 generation，公开 identity 不变。
- Gateway contract 证明只发送 bounded completed public turns，并丢弃未回答的尾部 user turn。
- 首轮完成 → idle release → reopen → contextual follow-up 通过真实 Compose/Product API/Chrome。
- DSH error reason 投影为 failed，Frontend 不再要求用户调整问题。
- cleanup、owner/workspace、MCP-only domain、secret/raw-event boundary 和现有 cancellation tests
  保持绿色。
