# ADR-0018: Structured WorkflowTrace Card Contract

- Status: Proposed
- Date: 2026-08-18
- Decision scope: Phase 36 Agent workbench structured card projection
- Related: ADR-0003, ADR-0012

## Context

The Community Agent workbench renders structured cards for strategy drafts,
stock candidates, optimization suggestions, and backtest context. The current
Runtime Adapter normalization (`services/runtime-adapter/app/normalization.py`)
collapses DSH events to coarse `WorkflowTraceEvent`s: `assistant/message`
emits only a text-byte count and unknown events become `session.progress`.
The framework-neutral envelope already supports arbitrary JSON payloads, but
no card schema or extraction rule exists, so the frontend cannot render
Community-level cards.

## Decision

1. Define a minimal BYQ card contract on top of the existing
   `WorkflowTraceEvent` envelope (`packages/contracts/workflow_trace.py`).
   Cards are normal events with a reserved `kind` and a schema-validated
   `payload`.
2. The initial card kinds are:
   - `agent.card.strategy_draft`
   - `agent.card.stock_candidates`
   - `agent.card.optimization`
   - `agent.card.backtest_context`
   - `agent.card.approval`
3. Each card payload is BYQ-owned and framework-neutral. Example minimal
   fields:
   - strategy_draft: `{artifact_id?, name, source, content_snippet}`
   - stock_candidates: `{items: [{symbol, name?, reason?}]}`
   - optimization: `{strategy_artifact_id?, suggestion, metrics?}`
   - backtest_context: `{job_id, status, metrics?}`
   - approval: `{approval_id, action, decision}`
4. The Runtime Adapter is the only component that extracts card fields from
   DSH notifications. Extraction is allow-list based: only the curated fields
   above cross the Gateway boundary. Raw DSH payloads, tool call internals,
   and unrelated event fields are discarded.
5. The Gateway persists and streams only the validated BYQ card envelopes.
   The frontend renders cards from the BYQ schema and never imports DSH wire
   types.
6. Unknown or non-card DSH events continue to degrade to the existing bounded
   `session.progress` / text-delta projections.

## Consequences

- Frontend gains Community-level structured cards without coupling to DSH.
- The normalization module grows a curated extraction layer with contract
  tests per card kind.
- DSH upgrades only require updating the extraction layer; frontend and
  Gateway contracts remain stable.
- Cards that need richer data later can add fields through a contract change,
  not through raw passthrough.

## Rejected alternatives

- Passing raw DSH event payloads to the frontend: violates ADR-0003 and
  ARCHITECTURE.md section G.
- Rendering cards from normalized text only: loses the structured workflow
  the Community UX depends on.
- Building a second event bus: the existing WorkflowTrace envelope already
  satisfies the ordering and identity requirements.

## Rollback

Remove the card kinds and extraction layer; the adapter returns to the
text-delta / session.progress projection. No storage migration is required.
