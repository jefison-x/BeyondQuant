# Phase 17 — Residual simplification and final Golden acceptance

Status: **OPEN**. Development is authorized by the maintainer's next-step
instruction after Phase 16 merged. This record distinguishes source slices
from the final Golden and repository gates; it makes no final fidelity claim.

## Entry and boundaries

Observed clean base: `ff6756be3e7bf6cb6d3213c6dcd9bf016ecb9545` (Phase 16 PR
#379 merge). Branch `codex/clean-break-phase17`, isolated worktree
`/home/jefison/projects/.byq-worktrees/clean-break-phase17`; worktree verification
passed. STATUS and README route Phase 17 while retaining historical markers.

The Phase 15 model-call budget is exhausted. No Phase 17 Product model/provider
call has been made. Ordinary business databases, backups and Community storage
remain outside scope. Phase 17 push/PR, merge, deployment and release require
their own authorization; prior phase grants are not reused.

## Finite ownership audit

The audit follows the Phase 7 exit classification and Phase 10 Adapter/Gateway
qualification. Dispositions use actual callers and behavior rather than names.

| Residual item | Caller and actual owner | Phase 17 disposition |
|---|---|---|
| Gateway generic `LifecycleDelivery` fallback | Only tests instantiate it without public-answer/private-evidence options. Production `main.py` selects those two modes explicitly. | DELETE unused lifecycle projection, ledger, status and receipt branches; require exactly one current delivery mode. |
| Adapter terminal evidence, Gateway collector and Backend exact root close | `main.py::_collect_trace` calls `_send_agent_lifecycle`; Adapter retains the exact evidence until Backend close and same-boot ACK. BYQ owns domain-call authority. | KEEP the verified evidence → atomic close → exact ACK chain, its retry and boot fences. It does not resume an Agent. |
| Adapter `RuntimeSession`, `ActiveRun`, generation and child watchdog | Current process/prompt correlation, idempotency, cleanup barrier and bounded child inactivity checks. DSH owns Agent reasoning/execution. | KEEP required transport/process safety while pinned DSH has no qualified equivalent; no cross-process session/child recovery claim. |
| Adapter bounded history and Gateway `TraceStore` | Same-boot live SSE replay versus durable normalized user projection. Neither is an Agent recovery executor. | KEEP their distinct contracts; history and projection are not interchangeable. |
| MCP Web evidence caller identity compatibility | Current plugin callers omit producer fields; MCP previously accepted optional caller claims matching deployment identity. Backend validates stored provenance. | DELETE model-input producer fields and reject any caller-supplied identity; inject the trusted deployment identity and KEEP Backend recognition policy. |
| Legacy ResearchTask plan adoption | Repository search finds only two historical store-test callers. Classifier is used only by adoption and its pure test; `legacy_reason` has no readers. | Proposed DELETE of adoption/classification, empty migration mapping and fresh-DDL/writer/fixture references is approval-blocked; no Backend/schema edit or DB operation applied. |
| Current ResearchTask plan and action receipts | Current reducers and approvals use stage CAS, parameter digests, exact action binding and durable outcome reconciliation. `plan_at_stage` is used by current trusted domain fixtures. | KEEP domain transitions, factory and authoritative business receipts. |
| Optional F6 Agent prompt dispatch | `TaskContinuationDelivery.tick` invokes Gateway consumption when the three service executor flags are enabled. Backend derives task-bound grants/intents and unknown-outcome settlement; Gateway submits a DSH prompt. | OPEN qualification/cutover candidate. Default-off is not dead-code evidence; this is not the pending business action executor accepted in Phase 7. Keep its business authority facts while qualifying the dispatch separately. |
| Plugin Center desired policy and qualification | Live admin Product API records exact registry version, desired enable/assignment policy, qualification and admin audit; DSH owns actual runtime. Desired `awaiting_generation` is distinct from active composition. | KEEP minimal registry/policy/basic qualification/audit and truthful desired-versus-active projection under ADR-006. Deployment request/result endpoints require separate contract qualification before trimming extra governance. |
| Jobs, workers, Artifact lineage and domain facts | Independent Backtest/Data/CPU ML workers own compute; BYQ stores Job identity, approval, lineage and unknown outcomes. | KEEP; do not put compute in an Agent or delete authoritative financial/approval/audit facts. |
| Product profiles and Engineering separation | Product MCP/domain catalog and pinned profiles retain separate privileges; dev tools remain disabled for Product DSH. | KEEP qualified separation. No application-source write or direct business DB access is added. |

### Remaining qualification boundaries

The optional F6 path is live when explicitly enabled, despite Compose defaults
of zero. It claims a task-bound reservation and writes `outcome_unknown` before
submitting the DSH prompt; exact receipts reconcile execution and budget without
refunding unknown outcomes. These are required safety facts, but they do not
prove that Gateway-owned automatic Agent dispatch is an accepted pending-action
executor. Phase 7's pending-action cutover explicitly excluded DSH continuation.
Current receipt-only `research-receipts` reconciliation observes domain
submissions; continuation budget reconciliation occurs inside the enabled
consumer. They must not be conflated. Qualify or cut over this residual owner
before overall Phase 17 close; no scope exception is inferred here.

Plugin Center remains a current admin API over read-only image registry and BYQ
desired policy/audit. It does not install code or write application source.
Deployment input/result endpoints require an Engineering deployment token;
bounded repository search finds definitions/tests but no deployment-lane caller,
which does not prove absence of external callers. Historical ADR-0040 does not
authorize expanding governance. Preserve the live Product policy interface and
qualify any extra deployment-state simplification against ADR-006 first.

The internal Adapter DELETE-session alias is an additional candidate, not a
proven safe deletion: Gateway uses canonical POST `/release`, but compatibility
callers and its test disposition require qualification before removal. It is
not silently counted as retired. This audit does not authorize a table/volume
DROP, historic data migration or generic runtime rewrite.

## Gateway slice

Removed only the unused generic lifecycle branch from
`services/gateway/app/agent_lifecycle_delivery.py`. Public answer and private
MCP evidence delivery retain their durable budgets, ordering and identity.
Production terminal collection remains the sole lifecycle sender. Constructor
negative tests detect the removed mode; the old test-only generic ledger fixture
is retired while live same-boot session rehydration coverage remains.

Independent Tester: **PASS**, 29 tests across `test_answer_delivery.py`,
`test_domain_call_delivery.py`, `test_agent_lifecycle_delivery.py` and
`test_session_rehydration.py`. Existing image `byq-dev-ea551690f4-gateway` was
used with `--pull=never --network none`, current code/contracts read-only, no
secrets/data volumes and no Product service. One Starlette deprecation warning.
This proves focused local boundaries, not real Product Golden acceptance.

Independent Reviewer found an additional opt-in synthetic wire test using the
removed generic ledger. The corrected test now uses the actual collector and
exact terminal close/ACK chain, asserts one Backend close and same-boot identical
ACK retry after synthetic response loss, and no lifecycle ledger. Its syntax and
diff checks pass. Actual opt-in execution is **NOT_RUN**: it needs a qualified
disposable Backend/MCP/authority fixture. Paid mode remains separately gated and
unrun. Independent slice review and broader local identity checks passed as recorded below.

## MCP slice

Removed optional `plugin_id`/`plugin_version` from the strict model-input search
schema and reject their presence in the trusted binder even when values match.
Canonical persisted producer identity remains injected from deployment policy.

Worker and independent Tester **PASS**: `npm run build`,
`node dist/tests/research-test.js` and
`node dist/tests/domain-server-wire-test.js`. Existing MCP image with
`--pull=never --network none`, read-only current src/tests/tsconfig and ephemeral
build output. Real MCP transport uses a loopback synthetic Backend. The tests
verify absent schema fields, matching/forged claims rejected before any Backend
write, canonical injection and original idempotency key. Actual service/DB
`contract-test.ts` integration is **NOT_RUN** locally. Independent slice review passed.

## Approval-blocked source slice

Automatic approval review rejected the Backend legacy removal twice, citing
possible compatibility break and lack of authorization for that exact scope.
No workaround was used. The temporarily accepted contract-function deletion
was restored so current Backend imports remain valid. Only a domain-factory
comment clarification remains. The precise user request is pending: remove
unreachable adoption/classification and `legacy_reason` references in source,
fresh CREATE TABLE DDL and tests, with no ALTER/DROP or existing DB operation.

## Build identity and remaining gates

Source changes require a new immutable `.273` selected manifest. Published
`.272` manifest and Dockerfile remain byte-for-byte unchanged. SDK/runtime,
release descriptor and dependency locks remain pinned. Selectors are prepared;
manifest generated after source writers became ready:
`sha256:029eadcb55f4ed5a784d7eb3d5c87150d85e43e5abfd17240606db15ff2fe9a9`.
This is the current source-slice identity, not a final Golden execution receipt.
A later source deletion will require its own new immutable revision.

Independent final local Tester **PASS**: `dev-check --base ff6756be` syntax
14 files, six Markdown documents, three Clean Break governance tests,
74 normative architecture tests, current-build three/build-revision four/retirement
five tests, selected `.273` and frozen `.272` identity, and diff checks. A real
initial whitespace failure in this document was fixed and only the failed checks
rerun. The offline existing Runtime image verified default wire skip (three
skipped) and separately gated paid case (one skipped, two deselected); no test
body ran. Actual opt-in integration and real MCP Backend/DB contract stay NOT_RUN.

Independent Sol Reviewer: **Functional PASS / Tests PASS / Clean Break
Architecture PASS for this interim source slice**. Root: **PASS for Gateway/MCP
removal, corrected optional test source and immutable build selection only**.
Remaining residual qualification, approval-blocked legacy removal, final live
Golden and repository gates remain OPEN. This checkpoint does not start a later
phase or authorize push/merge/deployment. Hosted CI remains a separate gate.

## Final Golden execution plan

[Verification policy](verification-gates.md) explicitly requires A–F after the
last Phase 17 deletion. Phase 16's accepted evidence reuse does not satisfy
this new milestone. Pin the execution source commit, selected manifest hash,
image IDs, scoped resources and per-flow manifests before execution.

Prepare a fresh Phase 17 disposable stack from templates and committed source.
Review exact `dev-clean --dry-run` resources before cleanup; perform
`dev-clean → dev-init → dev-start → dev-seed → dev-test` and then connected
Product/browser/Worker journeys. Existing Phase 15 resources and ordinary
business/backup resources are not cleanup targets. Preserve the validated
TuShare 98-session market window (2024-01-02–2024-05-31): qualify a bounded
canonical market-data export/import through the Data Plane without old database,
session, Job or Artifact restoration. Any provider refresh beyond required real
TuShare qualification must be separately scoped; do not redownload the window.

- A/E: fresh Task, real TuShare/Web research, bounded multi-turn/delegated DSH
  research, source/Artifact/normalized browser projection; populated scoped
  Runtime/Workspace reset, reseed and rerun A.
- B: Agent-initiated A/B BacktestJobs with parameter revision, one optimization
  Job and browser comparison Artifact; preserve exact approval/idempotency.
- C: one exactly approved Agent-initiated CPU TrainingJob, real independent
  Worker stop/restart, natural lease reclaim of the same Job and validated
  Feature/Model Artifacts. GPU execution/checkpoint are N/A under ADR-0089.
- D: Agent-created Job survives old session deletion and a new authorized Agent
  reads the same Job/Artifact without duplicate execution. No DSH restart or
  child rebind claim.

The runnable plan, accurate new model-turn/delegation/provider budget and exact
resource identities require review and new bounded authorization before external
calls. Final Golden tests remain **NOT_RUN**, not PASS. Phase 17 stays OPEN until
that milestone, exact-head required CI and repository gates complete.
