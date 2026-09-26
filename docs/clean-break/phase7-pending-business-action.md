# Phase 7 slice 4 candidate — explicit ResearchTask business action

Status: design gate PASS; schema choice and implementation gate pending. No schema or runtime cutover has begun.

## Ownership decision

`research_continuation_events` currently stores both event provenance and mutable `admitted`/`pending`/`claimed`/`settled` state, alongside terminal `advanced`/`needs_attention` outcomes. Its database uniqueness and task/plan CAS enforce real BYQ domain invariants, while its name and generic continuation adapters make an event appear to own current state. The Clean Break target is an explicit ResearchTask business action or Job record as current truth. An event may notify clients or enter the audit log, but it must not be the checkpoint, execution owner or replay authority.

The current production caller records an exact, plan-bound approval decision. Tests exercise the other event adapters, triggers, and claim/settle entry points; historical P4 scripts additionally exercise approval, data-ready and backtest adapters. None has an identified Product event API consumer. This does not make their safety semantics disposable. Approval binding, owner/workspace isolation, request digest, stable action identity, one open action per task, and plan/task version CAS must survive in the replacement contract.

The live `decide_agent_approval` handoff commits the approval decision first, then catches and logs every continuation-ledger failure. The replacement must persist an unresolved action tied to the exact approval ID and implement deterministic reconciliation until the plan CAS succeeds. A crash between approval commit and action registration must be recoverable from BYQ approval facts; a successful response must not imply the plan advanced when it did not.

## Cutover boundary

Replace the event-as-state table and private ledger API in one bounded cutover, with no old-to-new bridge or old data migration. The new database baseline is disposable development data. Server-side facts from the exact Approval or Job determine action, resource, parameters and digest; callers cannot self-declare them. A repeated action identity returns the same durable result only when its canonical request body and source digest still match; a changed source or body conflicts. A task may have at most one open business action, enforced by the database and transaction lock. Settling an action requires the same trusted owner/claimant and a verified BYQ result; an unknown external or financial outcome remains unresolved.

An action whose next step requires model judgment, including `draft_strategy` or review, is **waiting for Agent**. It is not claimable by a deterministic Worker and cannot be reported as recovered, consumed or successful merely because a receipt was stored. A deterministic Job action settles only against its exact terminal Job record and verified Artifact or postcondition. An unknown external or financial result retains the unresolved slot. `user_resume` and generic runtime `recovery` do not schedule or reconstruct a DSH turn in BYQ. A lost Agent run ID cannot become a business action ID: the current recovery trigger depends on `agent_runtime_turns`, which Phase 7 intends to remove. Only an independently authoritative BYQ business fact may create a business action; Agent continuation waits for a separately qualified DSH contract. Existing `continuation_budget` and Agent dispatch receipts are outside this slice and are not certified or replaced by it.

## Required acceptance before implementation

1. Inventory every production caller, Product route, schema object and test that reads or writes the old ledger, including `workspace_tenancy.py` table registration and consistency checks. Prove the replacement of each live caller in the same slice; remove historical-only adapters from the current runtime rather than retaining a compatibility shim.
2. Specify the minimal new record and statuses using BYQ business terms. Keep action/Job identity stable and preserve exact task, workspace, plan and task-version binding.
3. Add tests for approval pre-binding, crash-between-commits reconciliation by exact approval ID, visible unresolved handoff, late/version-stale input, duplicate identity, changed-source/body replay conflict, concurrent one-open invariant, claimant ownership, owner/workspace isolation and unknown outcome. Include a negative test that Agent reasoning actions cannot be Worker-claimed or auto-settled, and require exact Job/Artifact proof for deterministic settlement.
4. Review the schema and actual diff against ADR-001/003/005, the current Product API, Audit/Event rules, DSH ownership and the Functional Fidelity Matrix. Do not count historical P4 tests as proof of the new contract.
5. Run the affected Backend and integration suites, current build/release/H4 checks, independent Sol Reviewer and Root gate. Phase 8 remains closed until this and other Phase 7 live-runtime slices are accepted.

## Open design question

Choose between a task-owned pending-action row and a small business-action table only after checking the transaction and authorization call graph. Do not introduce a generic workflow engine, universal command bus, second Agent session manager or event replay store. If the current DSH API gap prevents a faithful same-slice cutover of any live Product behavior, return NO-GO with the exact missing contract instead of weakening the tests.

## Design review

Read-only Explorer found a conditional GO for BYQ business-state replacement without DSH attach/resume/status, but no authorization to simulate Agent continuation. Static Tester verified the sole production ledger caller, schema/tenancy references and acceptance checks. Independent Sol Reviewer returned Functional PASS / Clean Break Architecture PASS for this design after the approval handoff, lost-run trigger, action-specific settlement, source/body replay and tenancy gaps were made explicit. Root accepts **design PASS only**; code, tests and the Phase 7 slice gate remain pending.
