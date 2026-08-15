# Quant Research Agent Contract — Phase 13

## Ownership

DSH owns generic role composition, skill loading, subagent lifecycle, and
delegation transport. BYQ owns the role catalogue, domain authorization,
human approval state, business audit records, and evidence promotion rules.

The Product DSH receives only a session-scoped context header from the
authenticated Gateway path. The MCP service forwards that context to Backend;
the model never supplies or receives a product bearer token. Backend rejects a
body identity that disagrees with the trusted context.

## Roles

The versioned catalogue is exposed by `byq_agent_roles` and currently contains:

- `quant_orchestrator`: coordinates hand-offs and consequential decisions;
- `market_researcher`: normalized market evidence;
- `factor_researcher`: reproducible point-in-time factors;
- `strategy_researcher`: validated strategy artifacts, without approval or execution;
- `backtest_analyst`: authorized deterministic backtest review.

Each role declares its allowed MCP tools, delegate targets, approval-required
actions, and evidence kinds. DSH `toolFilter` mirrors the child allowlist for
visibility; BYQ authorization remains authoritative and is checked through
`byq_agent_authorize`.

## Run and audit contract

`byq_agent_run_start` creates an owner-scoped `agent_run` correlated with:

```text
owner_principal, actor_principal, role_id/version,
trace_id, session_id, dsh_run_id, parent_run_id
```

Run identity and audit detail are bounded. DSH event types, prompts, raw
session logs, credentials, and storage paths are never stored as business
records. `byq_agent_audit` records action, outcome, resource identity, and a
bounded JSON detail summary. `byq_agent_audit_get` returns an owner-scoped
audit view.

## Approval

Actions classified as consequential return `approval_required`. The agent may
create a pending approval with `byq_agent_approval_request`; a trusted human
actor decides it through `byq_agent_approval_decide`. The initiating actor
cannot self-approve. `approved`/`rejected` and the later `execution_outcome`
are separate fields: approval authorizes an attempt and does not claim that
the domain action succeeded.

## Stability

Backend storage remains an implementation detail. Agent-to-domain calls use
BeyondQuant MCP, and frontend consumers use BYQ audit/trace contracts rather
than DSH schemas.
