# Conversation Rehydration Contract

`conversation-rehydration.v1` 是 Gateway 与 Runtime Adapter 之间的内部、framework-neutral
Product 对话恢复合同。它只在一个 released/restarted DSH process 的新 generation 第一次
处理 prompt 时使用。

```json
{
  "conversation_context": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

约束：

- role 仅为 `user` 或 `assistant`；字段必须精确为 `role`、`content`。
- 最多 20 条；单条最多 6,000 字符；总计最多 24,000 字符。
- 只包含 BYQ Product catalog 中已持久化、用户可见且已完成的对话。
- 尾部未回答 user turn、WorkflowTrace、DSH event、reasoning、tool payload、credential 和
  Domain private state 不得进入。
- Stable BYQ session/trace identity 不变；DSH generation identity 永不投影到 Browser。
- 该合同恢复语言上下文，不恢复或伪造 tool execution、approval、subagent、cache 或 hidden
  runtime state。Domain state 必须重新经 BYQ MCP 查询。

超过边界的 Runtime request 返回 validation failure；Gateway 正常投影会从最近 completed turn
向前截取到合同上限，因此普通长对话不会依赖 DSH raw persistence。

