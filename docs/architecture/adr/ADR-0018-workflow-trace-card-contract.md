# ADR-0018: Structured WorkflowTrace Cards and Normalization Boundary

- Status: Accepted
- Date: 2026-08-22
- Decision scope: Phase 36 Agent workbench projection and interaction boundary
- Related: ADR-0003, ADR-0009, ADR-0012, ADR-0014
- Contract: `docs/contracts/workflow-trace-cards.md`

## Context

The Community Agent workbench renders conversation-adjacent strategy drafts,
stock candidates, optimization plans, backtest context, approval state,
progress steps, and page-aware assistant affordances. Those surfaces are useful
product evidence, but Community message objects, Agent APIs, approval runtime,
and event schemas are not a compatible integration boundary for BYQ.

The current Runtime Adapter normalization collapses DSH notifications to a
small `WorkflowTraceEvent` envelope. Public assistant messages retain only a
byte count, unknown events become `session.progress`, and there is no bounded
card schema. Passing more of the DSH object through would couple the frontend
to rc.6 wire types and could let model-produced fields impersonate BYQ
artifacts, approvals, execution outcomes, or authorized actions.

Phase 36 therefore needs both a structured presentation contract and a firm
normalization/authority boundary. The contract must preserve ordered replay,
owner isolation, approval semantics, payload bounds, and DSH replaceability.

## Decision

### 1. Preserve the WorkflowTrace envelope

Structured cards remain ordinary append-only `WorkflowTraceEvent` records:

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

The envelope, contiguous sequence allocation, SSE replay, and identical-retry
rules remain authoritative. No second event bus or frontend DSH client is
introduced. `source` may additionally be `byq-domain` only when Gateway has
replaced candidate fields with an owner-scoped Domain projection.

### 2. Adopt five versioned card kinds

The initial kinds are:

- `agent.card.strategy_draft`
- `agent.card.stock_candidates`
- `agent.card.optimization`
- `agent.card.backtest_context`
- `agent.card.approval`

Every card uses `schema_version = "workflow-card.v1"`, a BYQ-allocated stable
`card_id`, a positive `revision`, `authority` (`proposal` or `domain`), and an
exact allow-listed payload for its kind. Unknown fields are rejected rather
than retained. The normative shapes, enums, identifier rules, and size limits
are defined in `docs/contracts/workflow-trace-cards.md`.

Cards are immutable snapshots. A later state is a new trace event with the
same `card_id` and a greater revision. The frontend may fold to the latest
revision for display, while replay retains the complete ordered history.
Conflicting or decreasing revisions are rejected.

### 3. Separate proposal data from Domain authority

Runtime Adapter is the only component allowed to inspect DSH notifications.
It extracts a card candidate through exact field allow-lists, assigns bounded
BYQ identity, and discards the raw notification, tool call internals, unknown
keys, arbitrary links, and executable request data.

DSH/model content can produce only `authority = "proposal"`. It cannot assert
that an artifact is validated, an approval is pending/approved, a backtest
completed, an operation executed, or an owner has access. Candidate references
such as `artifact_id`, `job_id`, `pool_id`, and `approval_id` are untrusted
until resolved.

Gateway owns the second projection step. Any card that claims Domain state,
and every `backtest_context` or `approval` card, must be re-read through the
owner-scoped BYQ Domain/Product boundary using the authenticated session
principal. Gateway replaces display fields with that projection and emits
`authority = "domain"`, `source = "byq-domain"`. A missing, cross-owner,
stale, malformed, or forbidden reference becomes a bounded
`session.progress` projection at the same sequence; raw rejection details do
not cross to the browser.

Principal, bearer/session token, MCP headers, provider credentials, and DSH
authorization data never appear in a card.

### 4. Cards are not commands

A card contains no URL, HTTP method, headers, arbitrary route, tool name,
tool arguments, or mutation body. It cannot grant approval or represent
approval as execution success.

The frontend maps a validated card kind to a fixed BYQ-owned interaction. It
must fetch the latest owner-scoped resource before a consequential action and
then use the existing Product API, validation, idempotency, optimistic
concurrency, and Approval contracts. Proposal-card actions may open a draft or
request flow; they never directly mutate business state. An approval decision
always targets the current BYQ approval resource, and execution outcome remains
separate.

### 5. Normalize public answer and activity, not hidden reasoning

Phase 36 also upgrades two non-card projections needed by the workbench:

- `agent.output.delta` carries only public assistant answer text in bounded,
  ordered fragments. The adapter deduplicates cumulative DSH message updates.
- `agent.activity` carries a curated public phase, state, label, and optional
  BYQ capability name for progress visualization.

Hidden chain-of-thought, system/developer prompts, model provider objects,
token-level reasoning, tool arguments, raw tool results, stack traces, and DSH
message objects are never projected. Community `AgentThinking` is therefore
classified as public operational progress UX, not permission to expose model
reasoning.

### 6. Enforce bounds and fail closed

All payloads must be finite JSON and pass exact schemas before persistence.
The initial limits include a 64 KiB serialized event payload, 8 KiB answer
fragments, 50 stock candidates, 20 optimization changes, bounded strings and
metric keys, at most 32 cards and 256 activity events per turn, and no
credential-shaped fields. Oversized public text is split when safe; excess
structured activity is coalesced into a bounded progress/truncation event.
Invalid cards degrade safely and never fall back to raw passthrough.

Gateway persists and streams only validated BYQ envelopes. Frontend types are
discriminated BYQ unions and do not import DSH SDK/wire types.

### 7. Phase ownership

Phase 36 owns the Agent-specific card renderers, `AgentThinking`-equivalent
public activity component, approval presentation, and assistant drawer needed
for its exit criteria. Phase 40 may extract/generalize those proven components
for other pages, but it is not a prerequisite for Phase 36; this removes the
previous circular roadmap dependency.

## Consequences

- Community-level structured interaction is possible without trusting
  Community or DSH schemas.
- Runtime Adapter gains a curated candidate extractor; Gateway gains schema
  validation, owner-scoped hydration, revision checks, and fail-closed
  degradation.
- Domain-backed status remains authoritative even when a model emits stale or
  invented identifiers.
- The workbench can show public progress without exposing hidden reasoning.
- DSH upgrades are isolated to the adapter extractor and its compatibility
  tests. Card consumers remain stable across runtime changes.
- Richer fields or new kinds require a reviewed contract/ADR update; raw JSON
  escape hatches are prohibited.

## Required Phase 36 evidence

- contract tests for every accepted and rejected card shape, bounds, finite
  metrics, revision rules, and unknown-field rejection;
- adapter tests proving raw notification/tool/reasoning fields are discarded;
- Gateway tests for owner-scoped hydration, cross-owner failure, stale/missing
  references, safe degradation, ordered replay, and no authority promotion;
- frontend tests for discriminated rendering, revision folding, fixed Product
  actions, public activity, reconnect replay, empty/error/truncated states;
- secret-boundary tests and a real Product API browser journey with Chrome MCP
  network/console evidence;
- Community feature checklist and migration classification before code work.

## Rejected alternatives

- Pass raw DSH payloads or Community message objects to the frontend: violates
  ADR-0003 and `ARCHITECTURE.md` section G.
- Let DSH emit authoritative approval/artifact/backtest state: crosses the
  Agent/Domain authority boundary and owner isolation.
- Put executable actions in cards: creates a model-controlled Product API and
  approval bypass surface.
- Render hidden chain-of-thought as “thinking”: exposes runtime internals and
  creates an unstable, unsafe product contract.
- Render all structure from plain text: loses deterministic validation,
  accessibility, and actionable domain references.
- Build a second event bus: duplicates WorkflowTrace ordering and replay.
- Block Phase 36 on Phase 40: creates a circular phase dependency; Phase 36
  must first prove its specific components before later generalization.

## Rollback

Disable the five card renderers and candidate/hydration projectors. Existing
card events remain valid append-only evidence and can render as generic trace
items; no business-data or DSH-session migration is required. Public answer
and activity events can fall back to the existing coarse progress view without
exposing raw payloads.
