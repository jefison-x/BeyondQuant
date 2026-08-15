# WorkflowTrace Contract Placeholder

## Purpose

Define a future framework-neutral BYQ contract for representing agent, tool, artifact, approval, backtest, experiment, error, repair, and completion progress to product clients.

## Ownership

The contract is owned by the BYQ Gateway and Quant Domain Plane. DSH events are an input, not the public contract.

## Non-goals

- This document does not define a complete schema.
- It does not expose DSH internal event types to the frontend.
- It does not define transport, storage, or UI implementation.

## Stability guarantee

The frontend MUST depend on the BYQ WorkflowTrace contract rather than DSH internal schemas. Future DSH replacement or upgrade SHOULD NOT require frontend workflow reconstruction.
