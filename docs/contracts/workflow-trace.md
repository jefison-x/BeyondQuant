# WorkflowTrace Contract — Phase 6 Minimum Envelope

## Purpose

Define a future framework-neutral BYQ contract for representing agent, tool,
artifact, approval, backtest, experiment, error, repair, and completion
progress to product clients. Phase 6 defines only the minimum internal event
envelope; the full product schema belongs to Phase 7.

## Ownership

The contract is owned by the BYQ Gateway and Quant Domain Plane. DSH events are an input, not the public contract.

## Non-goals

- This document does not define a complete product schema.
- It does not expose DSH internal event types to the frontend.
- It does not define transport, storage, or UI implementation.

## Phase 6 envelope

The adapter emits the BYQ-owned `WorkflowTraceEvent` from
`packages/contracts/workflow_trace.py` with:

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

The payload is deliberately minimal and semantic. Raw DSH notifications,
runtime event objects, and DSH-specific persistence records do not cross into
Gateway or frontend boundaries.

## Stability guarantee

The frontend MUST depend on the BYQ WorkflowTrace contract rather than DSH internal schemas. Future DSH replacement or upgrade SHOULD NOT require frontend workflow reconstruction.
