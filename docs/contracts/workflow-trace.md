# WorkflowTrace Envelope Contract

## Purpose

Define the framework-neutral BYQ envelope, ordering, persistence, and replay
contract established by Phase 7. Structured Phase 36 projections are defined
by [the WorkflowTrace card contract](workflow-trace-cards.md) under ADR-0018;
they extend this envelope without exposing DSH event schemas.

## Ownership

The contract is owned by the BYQ Gateway and Quant Domain Plane. DSH events are an input, not the public contract.

## Non-goals

- This document does not duplicate the structured card payload schemas.
- It does not expose DSH internal event types to the frontend.
- It does not make DSH session persistence BYQ business state.

## Envelope

The adapter emits the BYQ-owned `WorkflowTraceEvent` from
`packages/contracts/workflow_trace.py` with:

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

The payload is deliberately semantic. `source` is `dsh` or
`runtime-adapter`, with `byq-domain` reserved for a Gateway-hydrated,
owner-scoped Domain projection as specified by ADR-0018. Raw DSH
notifications, runtime event objects, and DSH-specific persistence records do
not cross into Gateway or frontend boundaries. Runtime Adapter allocates one
contiguous sequence per BYQ session.

The first product-turn semantic kinds include:

- `session.ready`, `session.started`, `session.status`, `session.progress`;
- `agent.output.delta`, `turn.completed`, `session.result`;
- `session.cancelled`, `session.resuming`, `session.resumed`;
- `session.result.discarded`, `session.failed`, and `session.closed`.

ADR-0018 additionally defines five `agent.card.*` projections,
`agent.activity`, and bounded public `agent.output.delta` fragments. Those
events remain ordinary envelopes in the same ordered stream. Cards are view
models, never commands; Domain-backed fields require owner-scoped Gateway
hydration.

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

The frontend MUST depend on the BYQ WorkflowTrace contracts rather than DSH
internal schemas. Future DSH replacement or upgrade SHOULD NOT require
frontend workflow reconstruction.
