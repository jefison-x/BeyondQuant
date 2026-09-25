# ADR-002 — DSH runtime boundary

- Status: Accepted under ADR-0088 (2026-09-25)
- Acceptance: maintainer's explicit sole-harness and thin-adapter specification, recorded by [ADR-0088](../../architecture/adr/ADR-0088-clean-break-baseline-activation.md).

## Decision

DSH is the only Product Agent harness. BYQ's DSH adapter translates the supported DSH API to framework-neutral BYQ contracts: start, resume, cancel, input, status and bounded event projection as available in the qualified DSH version. It may own a transport client and transient correlation map; it does not own a generic session manager, generation ledger, executor lease, child lifecycle, checkpoint, replay or recovery coordinator. A DSH upgrade should primarily change this adapter and its contract tests.

BYQ MCP remains the stable Agent-to-Domain boundary. MCP exposes domain commands and bounded read models, not Redis, queue, GPU node, process, table or filesystem internals. Browser requests use Product API. Product runtime and development agents/tools are isolated. If DSH lacks a required generic continuity feature, record the limitation and qualify a DSH version; do not recreate the harness in BYQ.

For the Phase 7 Gateway cutover, the public `/v1/agent/*` and `/v1/workflows/*` Product API paths are the only browser-facing conversation/trace routes. Gateway MUST remove exactly its old pass-through `GET /internal/runtime/health`, `POST /internal/runtime/sessions`, `POST /internal/runtime/sessions/{id}/prompt|cancel|release`, and `GET /internal/workflows/{id}/events` handlers. Gateway may still call the Runtime Adapter's internal API as a service client until the adapter itself is simplified in a separately qualified slice; removing Gateway pass-through does not delete the Adapter transport or make raw DSH schemas public. The old ADR-0004 requirement to retain that Gateway compatibility seam is superseded by ADR-0088 and this decision.

## Acceptance

Contract tests cover the actual qualified DSH API, error/cancel behavior and event normalization. No BYQ Agent session/child-run recovery store remains. Business `outcome_unknown` and financial side-effect safeguards remain enforceable independently of DSH session state.

## Alternative and consequence

A BYQ recovery bridge or forked DSH would duplicate the harness and is rejected. Unsupported native DSH continuity remains an explicit feature limitation until qualified upstream support exists.
