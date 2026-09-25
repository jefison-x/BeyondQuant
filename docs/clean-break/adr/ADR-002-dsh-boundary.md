# ADR-002 — DSH runtime boundary

- Status: Proposed

## Decision

DSH is the only Product Agent harness. BYQ's DSH adapter translates the supported DSH API to framework-neutral BYQ contracts: start, resume, cancel, input, status and bounded event projection as available in the qualified DSH version. It may own a transport client and transient correlation map; it does not own a generic session manager, generation ledger, executor lease, child lifecycle, checkpoint, replay or recovery coordinator. A DSH upgrade should primarily change this adapter and its contract tests.

BYQ MCP remains the stable Agent-to-Domain boundary. MCP exposes domain commands and bounded read models, not Redis, queue, GPU node, process, table or filesystem internals. Browser requests use Product API. Product runtime and development agents/tools are isolated. If DSH lacks a required generic continuity feature, record the limitation and qualify a DSH version; do not recreate the harness in BYQ.

## Acceptance

Contract tests cover the actual qualified DSH API, error/cancel behavior and event normalization. No BYQ Agent session/child-run recovery store remains. Business `outcome_unknown` and financial side-effect safeguards remain enforceable independently of DSH session state.
