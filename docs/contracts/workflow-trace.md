# WorkflowTrace Envelope Contract

## 目的

定义 Phase 7 建立的 framework-neutral BYQ envelope、ordering、persistence 和 replay contract。Phase 36 structured projections 由 ADR-0018 下的 [WorkflowTrace card contract](workflow-trace-cards.md) 定义；它们扩展此 envelope，但不暴露 DSH event schemas。

## 所有权

Contract 由 BYQ Gateway 和 Quant Domain Plane 拥有。DSH events 是 input，不是 public contract。

## 非目标

- 不重复 structured card payload schemas。
- 不向 frontend 暴露 DSH internal event types。
- 不把 DSH session persistence 视为 BYQ business state。

## Envelope

Adapter 发出 `packages/contracts/workflow_trace.py` 中 BYQ-owned `WorkflowTraceEvent`：

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

Payload 刻意保持 semantic。`source` 为 `dsh` 或 `runtime-adapter`；按 ADR-0018，`byq-domain` 保留给 Gateway-hydrated、owner-scoped Domain projection。Raw DSH notifications、runtime event objects 和 DSH-specific persistence records 不跨入 Gateway/frontend boundaries。Runtime Adapter 为每个 BYQ session 分配连续 sequence。

首批 product-turn semantic kinds 包括：

- `session.ready`、`session.started`、`session.status`、`session.progress`；
- `agent.output.delta`、`turn.completed`、`session.result`；
- `session.cancelled`、`session.resuming`、`session.resumed`；
- `session.result.discarded`、`session.failed`、`session.closed`。

ADR-0018 另定义五种 `agent.card.*` projections、`agent.activity` 和有界 public `agent.output.delta` fragments；这些仍是同一 ordered stream 中的普通 envelopes。Cards 是 view models，不是 commands；Domain-backed fields 需要 owner-scoped Gateway hydration。

Run correlation 放在 semantic payload（例如 `run_id`），不放在 DSH-specific fields。Authentication subjects 是 Gateway session metadata，不是 trace payload data。

## Persistence 与 replay

Gateway 将 normalized envelopes 追加到 BYQ-owned per-session trace stream。只有 sequence 为下一个连续值，或为最近 event 的 identical retry 时才接受。Product SSE clients 接收 `id: <sequence>`，断线后可发送 `Last-Event-ID` replay。BYQ trace 与 DSH durable session log 保持独立。

## 稳定性保证

Frontend 必须依赖 BYQ WorkflowTrace contracts，而不是 DSH internal schemas。未来替换或升级 DSH 不应要求重建 frontend workflow。
