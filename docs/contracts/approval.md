# Approval Contract

## Purpose

Define the future BYQ contract for business approvals required before consequential domain actions.

## Ownership

BYQ owns approval identity, policy, authorization, audit, state transitions, and business idempotency.

## Phase 13 shape

The Phase 13 `agent_approvals` contract records a bounded `run_id`, owner and
initiating actor, consequential action, reason, `pending`/`approved`/`rejected`
decision state, reviewer identity, rationale, and a separate
`execution_outcome`. The initiating actor cannot self-approve. All records are
owner-scoped and reached through the normalized BeyondQuant MCP tools.

## Non-goals

- It does not replace generic DSH human interaction.
- It does not permit an agent to self-approve a consequential business action.

## Stability guarantee

Approval semantics MUST remain a BYQ domain contract. DSH may request or display approval, but it MUST NOT own business approval state.
