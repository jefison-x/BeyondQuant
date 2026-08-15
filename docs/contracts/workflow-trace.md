# WorkflowTrace Contract — Phase 7 Product Turn

## Purpose

Define the framework-neutral BYQ contract for the first authenticated Product
Agent turn. The contract remains deliberately small; later domain phases may
add artifact, approval, backtest, experiment, and repair semantics without
exposing DSH event schemas.

## Ownership

The contract is owned by the BYQ Gateway and Quant Domain Plane. DSH events are an input, not the public contract.

## Non-goals

- This document does not define the full quant-domain workflow schema.
- It does not expose DSH internal event types to the frontend.
- It does not make DSH session persistence BYQ business state.

## Envelope

The adapter emits the BYQ-owned `WorkflowTraceEvent` from
`packages/contracts/workflow_trace.py` with:

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

The payload is deliberately minimal and semantic. `source` is limited to
`dsh` and `runtime-adapter`; raw DSH notifications, runtime event objects, and
DSH-specific persistence records do not cross into Gateway or frontend
boundaries. Runtime Adapter allocates one contiguous sequence per BYQ session.

The first product-turn semantic kinds include:

- `session.ready`, `session.started`, `session.status`, `session.progress`;
- `agent.output.delta`, `turn.completed`, `session.result`;
- `session.cancelled`, `session.resuming`, `session.resumed`;
- `session.result.discarded`, `session.failed`, and `session.closed`.

Run correlation belongs in the semantic payload (for example, `run_id`), not
in DSH-specific fields. Authentication subjects are Gateway session metadata,
not trace payload data.

## Persistence and replay

Gateway appends normalized envelopes to a BYQ-owned per-session trace stream.
An event is accepted only when its sequence is the next contiguous sequence or
an identical retry of the most recent event. Product SSE clients receive
`id: <sequence>` and may send `Last-Event-ID` to replay events after a
disconnect. A BYQ trace remains distinct from DSH's durable session log.

## Stability guarantee

The frontend MUST depend on the BYQ WorkflowTrace contract rather than DSH internal schemas. Future DSH replacement or upgrade SHOULD NOT require frontend workflow reconstruction.
