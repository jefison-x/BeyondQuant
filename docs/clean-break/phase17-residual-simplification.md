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
| Legacy ResearchTask plan adoption | Repository search finds only two historical store-test callers. Classifier is used only by adoption and its pure test; `legacy_reason` has no readers. | DELETE applied under the maintainer's precise source authorization: adoption/classification, empty migration mapping and fresh-DDL/writer/fixture references. Current domain factory/transitions remain; focused fresh-schema Tester → independent Reviewer → Root PASS for this slice. |
| Current ResearchTask plan and action receipts | Current reducers and approvals use stage CAS, parameter digests, exact action binding and durable outcome reconciliation. `plan_at_stage` is used by current trusted domain fixtures. | KEEP domain transitions, factory and authoritative business receipts. |
| Optional F6 Agent prompt dispatch | Trusted task events and a user grant produce an exact bounded input to an existing healthy DSH session. BYQ owns task authority/receipts; DSH owns reasoning. | Conditional KEEP under ADR-002/003/006, with focused contract qualification in this slice. No inferred failed-turn recovery, process recreation or unknown-outcome replay. Actual enabled Product/model execution remains OPEN. |
| Plugin Center desired policy and qualification | Live admin Product API records exact registry version, desired enable/assignment policy, qualification and admin audit; DSH owns actual runtime. Desired `awaiting_generation` is distinct from active composition. | KEEP minimal registry/policy/basic qualification/audit and truthful desired-versus-active projection under ADR-006. Engineering input/result endpoints retain service-token gates. Remove the current-policy fallback for missing immutable snapshots; qualification input carries no mutable policy. Focused contract qualification is recorded below. |
| Jobs, workers, Artifact lineage and domain facts | Independent Backtest/Data/CPU ML workers own compute; BYQ stores Job identity, approval, lineage and unknown outcomes. | KEEP; do not put compute in an Agent or delete authoritative financial/approval/audit facts. |
| Product profiles and Engineering separation | Product MCP/domain catalog and pinned profiles retain separate privileges; dev tools remain disabled for Product DSH. | KEEP qualified separation. No application-source write or direct business DB access is added. |

### Remaining qualification boundaries

Independent Sol design review finds the F6 path compatible with ADR-002/003/006
only as a trusted, task-bound new input to the same healthy DSH process. It must
bind owner/workspace/task/conversation, deduplicate exact Job/Artifact events,
respect grant/revocation/expiry/budget and individual action approval, persist
unknown outcome before dispatch, and never reconstruct a lost Agent process or
replay an interrupted turn. Phase 7's pending business action cutover did not
qualify F6. Default-off does not prove dead code or acceptance.

`_restore_product_session` uses `attach_live_only=True`; a lost process becomes
`agent_session_interrupted`, not a newly created runtime. The new eligible-path
test exercises that real Gateway branch through mocked transport boundaries.
Gateway now rejects a reservation with a different owner/workspace/task/ID before
attaching an observer or accessing Adapter receipts. Receipt-only
`research-receipts` reconciliation and enabled continuation budget reconciliation
remain distinct. Focused offline contracts do not qualify actual enabled DSH
model execution.

Plugin Center remains a current admin API over read-only registry and BYQ desired
policy/qualification/audit. Engineering-token input/result endpoints read exact
request facts and record bounded results; they do not install code, mutate a
running DSH or write application source. Input validation also checks the current
pinned registry/Agent allowlists. A future registry change can therefore make an
old handoff fail closed with 503; this is not historical-registry compatibility. Repository search found no deployment
lane caller, which is not proof of external absence. Desired-versus-active state
is retained; actual deployment lane execution is NOT_RUN here. The old missing
snapshot fallback is removed, with qualification kept as an independent exact
version request rather than inferred current policy.

The internal Adapter DELETE-session alias was a forwarding wrapper with no
repository production caller; Gateway uses canonical POST `/release`. It is
removed with a regression detecting the old DELETE 200 response, while canonical
release/error behavior remains covered. This audit does not authorize any
existing table/volume deletion or historic data restoration.

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

## Legacy adoption source slice

Pre-slice rollback checkpoint: `5260d3e6`. Automatic approval review had rejected
this removal twice under the previous general development grant. The maintainer
then explicitly authorized: “移除不可达的旧计划采纳/分类路径，以及 legacy_reason
在新建表 DDL、源码和测试中的引用。” The source patch was accepted with that
precise grant; the earlier rejections remain historical, not a current blocker.

Removed `adopt_legacy_execution_plan`, `_legacy_stage_hint`, empty
`LEGACY_MIGRATABLE_STAGES`, `classify_legacy_task`, two adoption store tests,
one classifier test and the adoption-only fixture helper. Removed
`legacy_reason` from fresh `CREATE TABLE IF NOT EXISTS` source, the current
plan INSERT/five NULL assignments and three judgment/continuation SQL fixtures.
Repository search outside documentation/historical manifests finds no remaining
runtime/source/test references to the removed names. No route called adoption.

`plan_at_stage` remains for current domain fixtures. Current new-plan creation,
stage/CAS transitions, task/workspace authorization, exact approval bindings,
parameter digest, one-current-plan and durable idempotency/unknown-outcome
contracts are unchanged. There is no source ALTER/DROP migration, existing-table
inspection or archived-data input. Existing databases and backups are untouched.

Worker checks: 22 pure contract tests PASS in the existing Backend image with
network disabled, current source read-only and database URL empty; zero schema
resets/store bootstraps. Ten changed files parse and diff checks PASS.
Independent Tester **PASS**: six named suites (`test_research_execution_plan_contract`,
`test_research_execution_plan_store`, `test_research_judgment`,
`test_research_judgment_api`, `test_research_continuation_ledger`,
`test_research_plan_continuation`) ran **75 passed** with one Starlette deprecation
warning. This covers all changed current writers, exact approval/owner boundaries,
CAS/concurrent creation, durable replay, rollback and action reconciliation.

Only the newly created `byq_domain_test` PostgreSQL container on internal network
`byq-phase17-legacy-5260d3e6` was used: tmpfs database, current source/tests/packages
read-only, no existing volume, .env, host port or provider/model. Its standard
fixture performed 53 disposable-schema resets. A read-only `information_schema`
check confirmed the current plan table exists and `legacy_reason` count is zero.
After cleanup, scoped containers, the exact network and labeled volumes were
absent. No existing database or market resources were read or changed.

The same independent Tester passed 12 current/frozen build/selection tests,
74 normative architecture tests, `dev-check --base 5260d3e6` syntax (18 files),
two Markdown checks and diff checks. Independent Sol Reviewer: **Functional PASS / Tests PASS / Clean Break
Architecture PASS for this precise source slice**. Root: **PASS**. The actual
15-column/15-value current INSERT, all five UPDATE sites, removed-reference
closure and retained factory/CAS/approval/receipt contracts were inspected. This
local gate does not imply hosted CI or real Golden PASS.

## Build identity and remaining gates

The initial source checkpoint selected immutable `.273`. Published `.272`
manifest and Dockerfile remained byte-for-byte unchanged. SDK/runtime, release
descriptor and dependency locks remained pinned. Its manifest hash is:
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
Remaining residual qualification, legacy slice gates, final live
Golden and repository gates remain OPEN. This checkpoint does not start a later
phase or authorize push/merge/deployment. Hosted CI remains a separate gate.

### Current legacy-slice build

The subsequent authorized deletion selects new immutable `.274`, generated
only after source writers became ready:
`sha256:cf7f85fbf62219c58df2c9903164699891ec737f4b0c137d773c7adf26715b7b`.
Checkpoint `.273` manifest and Dockerfile remain frozen byte-for-byte. Current
Compose/dev/CI and selection-test references point to `.274`; its Dockerfile
changes only the embedded manifest path. No SDK/runtime/dependency update or
live service restart is performed. Local selected/frozen identity and Tester → independent Sol Reviewer → Root
gate passed for this exact legacy source slice. Phase 17 overall remains OPEN.

## Residual contract source slice

Rollback checkpoint: `33ed9829`. Changes are limited to the unused Adapter
DELETE alias, the Gateway reservation identity fence, and Plugin Center exact
Engineering input. Canonical release, current Product permission/policy routes,
request admission, Engineering token and result transitions remain authoritative.
There is no schema migration, provider/model call or existing database access.

Automatic approval review rejected trimming newly added request/registry checks
twice. No rejected patch was applied. The independent Reviewer accepted retaining
the stricter bounded reader checks as the safe alternative for this pinned
registry. Original service-token, request admission and result transition guards
remain unchanged; no approval exception or security relaxation is claimed.

Runtime alias Worker RED: old DELETE returned 200 (`1 failed, 4 passed`);
GREEN and independent Tester: **5 passed**, including exact POST session/response
and KeyError 404 / SessionConflict 409. Three existing framework deprecations.
Gateway new identity tests RED: four misbound reservations were not rejected
before observer access; after the guard, independent Tester: **40 passed** in
`test_task_continuation_delivery.py` and `test_business_recovery.py`. This includes
waiting/no Runtime input, unqualified executor/no claim, lost process/live-only
attachment, exact reconciliation and no unknown-outcome redispatch.

Both runs used existing pinned images with `--pull=never --network none`, current
source/tests/packages read-only and tmpfs `/tmp`, without secrets, provider calls
or persistent volumes.

Independent Backend Tester: **65 passed**, one Starlette deprecation. Selection:
`test_research_continuation`, `test_continuation_budget_ledger`, three selected
handoff cases (no registered executor; durable receipt/revocation; approval versus
action execution), both `test_continuation_notifications` tests,
`test_continuation_scope`, two selected data-ready cases (grantless deterministic
notification; foreign owner/conversation), and `test_plugin_center_api`.
The prior-passed `test_research_continuation_ledger` suite was not repeated.
Tests prove current task/root/owner/workspace authority, grant/expiry/revocation,
unknown liabilities, same-event once-only behavior, and background inability to
approve or expand goals. They do not exercise an actual enabled DSH model turn.

Plugin contracts cover current disable/enable/assign producer snapshots, a later
Product policy change, missing/corrupt schema/version/types and a valid-format
wrong hash, qualification `policy: null`, both internal HTTP token gates and
invalid result transitions/replay. They record no actual build/deployment lane
execution or online installation.

Exactly one new tmpfs Postgres container/network was used:
`byq-phase17-qualification-33ed9829`, database `byq_domain_test`, internal network,
no host port, bind or persistent volume. Existing Backend/Postgres image IDs:
`sha256:2bba02f59f032894143fd4894cbf4ed1a9c569faa1ae6815b71c993a05104806` /
`sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`.
The test hook counted 65 disposable-schema resets and 256 store bootstraps.
After exact cleanup, scope-labeled containers/networks/volumes were absent.
No existing database, market data, backup or Community resource was touched.

All writers finished before selecting immutable `.275`, manifest:
`sha256:c1ce46ac6ce876a0b2f4aeb1988d6381c8ab09bbf63b0458299eb847f4f5ff28`.
Frozen `.274` manifest and Dockerfile hashes remain
`sha256:cf7f85fbf62219c58df2c9903164699891ec737f4b0c137d773c7adf26715b7b` and
`sha256:5bab015079049079ea530cfbad27155311742486ade8eca99bf2c8cd64c78343`.
Independent selected/frozen identity checks **PASS** (current build 3, revision 4,
retirement 5), normative architecture **74 passed**, `dev-check --base 33ed9829`
**PASS** (14 syntax files), changed Markdown (two files) and diff checks **PASS**.
Independent Sol Reviewer: **Functional PASS / Tests PASS / Clean Break
Architecture PASS** for this bounded source slice. Root: **PASS**. The stricter
reader is accepted with its documented registry-evolution limitation. No generic
Agent harness or runtime deployment owner was introduced.

Hosted CI, final Golden A–F, actual enabled F6 model execution and real Engineering
deployment lane execution remain NOT_RUN. Phase 17 overall remains **OPEN**.

## Unused data-ready producer slice

Rollback checkpoint: `ff0a73fa`. Exact source search and route inspection found
no production, test or dynamic caller of `reserve_data_ready_budget`. Removed
only that 49-line method and its dedicated `DATA_READY_TURN_TIMEOUT_SECONDS`.
Current grantless deterministic notification and explicit user-granted
`reserve_continuation_budget` remain. No existing ledger or liability was changed.

Independent Tester **PASS**: zero source/test references; AST comparison against
the rollback checkpoint proves every other Backend function is identical.
Current/revision/retirement identity checks (3/4/5), the one changed normative
selector test, `dev-check --base ff0a73fa` (nine syntax files) and diff **PASS**.
The earlier 40/65/74 suites were not repeated; no DB/Docker/provider/model ran.
Independent Sol Reviewer: **Functional PASS / Tests PASS / Clean Break
Architecture PASS** for this exact dead-code slice. Root: **PASS**.

Selected immutable `.276` manifest:
`sha256:e4f6a417095baca1eea5b3291329004d63c6a1639fef973fa2d9f3b4bb388400`.
Frozen `.275` manifest/Dockerfile remain
`sha256:c1ce46ac6ce876a0b2f4aeb1988d6381c8ab09bbf63b0458299eb847f4f5ff28` /
`sha256:bfd143c08c54a0a1bfc12c6d96ecaffbe73a70dd90d19870b6cf60e379b20011`.

This is not retirement of all historical data-ready model semantics. Independent
follow-up found the legacy `grant_kind=data_ready` admission branch can still
make a pre-existing reserved receipt dispatchable without an explicit grant.
That was an execution exemption, not merely a receipt reader. The next bounded
slice below closes it; exact historical reconciliation/unknown liability remains.

## Legacy implicit model-grant admission closure

Rollback checkpoint: `de4f4195`. A persisted `grant_kind=data_ready` receipt now
always returns `unsupported_model_grant` at the shared Backend admission gate.
Pending intents, dispatch claims and continuation tool authority all use that
gate. A later explicit human grant cannot reactivate the old reservation. Handoff
uses the same per-receipt gate and does not project a legacy reservation as queued;
unknown-result liabilities retain priority. Exact receipt settlement is unchanged.

Removed four unused Backend model-budget constants and four unused SDK guard
exports. Synthetic multi-call fixture arithmetic is local to the guard test;
actual SDK charging, journaling, pricing and granted allowance enforcement are
unchanged. Adapter comments and the normative ceiling check now describe the
actual guard/Adapter ceilings and 8192 per-call output cap. Current zero-token
ready notifications and explicit human-granted reservations remain qualified.

Independent Tester: the five new DB regression cases were **RED: 3 failed,
2 passed**, then **GREEN** in a focused **34 passed** selection. That selection
also covers the six receipt-ledger tests, continuation scope, notifications,
current human permissions and handoff, exactly-once ready events and explicit
budget reservations. Exact original settlement replay is accepted, conflicting
settlement is rejected, and no unknown liability is refunded. The four new
Gateway reconciliation/no-prompt cases **PASS**. Direct execution of the SDK guard
file emitted **18/18 TAP PASS**; the Node test wrapper reported only its file-level
subtest, so the direct result records the actual case count.

The only DB fixture was new `byq-phase17-permission-de4f4195`, using the previously
qualified Backend/Postgres images recorded above, `byq_domain_test`, an internal
network and tmpfs PostgreSQL storage. It had no host ports, bind mounts or named
volumes. Test hooks recorded 34 schema resets and 182 store bootstraps. Exact
container/network cleanup was verified, with scope resources absent afterward.
No existing database, backup, provider or Product model call was used.

Selected immutable `.277` manifest:
`sha256:36d14cca3d16f0eed89060630e84177fa8d9193bda3132cf66aa66320d2dfbd5`;
Dockerfile:
`sha256:ab9606267b1a056311bfb1e22f201d1a3e11da09380a2b9d6a722a151744aafd`.
Frozen `.276` manifest/Dockerfile remain
`sha256:e4f6a417095baca1eea5b3291329004d63c6a1639fef973fa2d9f3b4bb388400` /
`sha256:b986cbf6d26b8cbb93507d8e344b367a12892fbba15c85a6d6d35006413414f3`.
Independent selected/frozen identity checks **PASS** (3/4/5), both changed
normative architecture nodes **PASS**, `dev-check --base de4f4195` **PASS**
(15 syntax files), and diff **PASS**. Earlier 40/65/74 suites were not repeated.
Changed Markdown and diff checks **PASS**. Independent Sol Reviewer:
**Functional PASS / Tests PASS / Clean Break Architecture PASS** for this bounded
source slice. Root: **PASS**.
Final Golden, enabled F6 model execution and hosted CI remain **NOT_RUN**;
Phase 17 overall remains **OPEN**.

## Fresh final-Golden environment preparation

Source checkpoint `a39849a2`, selected `.277`, new scope `byq-dev-dd33416d94`.
Root completed the reviewed empty-scope cleanup/init and fresh full build/start,
minimal seed and dev-test (3 governance and 13 lifecycle cases). Both external
credentials remain empty; only the new-scope Data/ML Workers were stopped.
Gateway and real-browser durable login passed, with 38 same-origin browser
requests and zero foreign requests. Independent Tester verified all 13 image IDs,
exact container/network/volume ownership, loopback ports, current health and
stopped Workers. Private evidence pins are in
`/tmp/byq-phase17-a39849a2/environment.json` and `browser-preflight.json`.

The [final Golden runbook](phase17-final-golden-runbook.md) records exact prepared
resources, fail-closed write stages and the reviewed finite source-read proposal.
After the maintainer's exact exception, the exporter ran once in a read-only
repeatable-read transaction, ending with rollback. That one-time permission is
spent. It read no old Jobs, Artifacts, sessions, users or backups.

Independent offline qualification verified original hashes for 98 bars, status
and factor rows, all 151 calendar days and the complete security snapshot
(5,909 members plus one quarantine row). Payload hash:
`b6208258fc9725d56e2fa78b7f1c31b460d5bce9b0fd26a32178549246237eab`.
Result **QUALIFIED_PARTIAL**: original daily full-market supplemental aggregate
hashes cannot be recomputed from a single-symbol subset. Existing date-wide
supplement import would falsely mark that subset globally complete. A bounded
symbol/date proof and providerless calendar repair is in progress, with direct
RED evidence (three missing scoped-import API cases and one missing calendar API
case). Target import and Product readiness remain NOT_RUN. Model/provider budget
is not requested yet.

Tester **PREPARATION PASS** → independent Sol Reviewer **PREPARATION PASS /
SOURCE-READ PLAN PASS** → Root **PASS**, limited to environment preparation and
proposing the exact source-read exception. Final Golden, actual populated reset,
actual F6, external calls and hosted CI remain **NOT_RUN**. Phase 17 stays **OPEN**.


## Scoped Data Plane import repair — qualified source slice

Pre-slice Git checkpoint: `2d004f7f`. The once-exported single-symbol file cannot
safely use the existing full-session supplement importer: that importer owns
full-market replacement. The new
[scoped canonical import contract](../contracts/market-scoped-canonical-import.md)
keeps ownership in BYQ Data Plane and adds no Product/MCP/DSH privilege.

Changed source: Backend `market_readiness.py`, `market_automation.py`, and one
focused `test_market_scoped_data.py`. The symbol/date proof binds the original
source attestation, bundle digest and actual target factor/action hashes. It
never sets global completeness. Native full-session import invalidates that
date's scoped proofs in its own transaction. Readiness rehashes scoped rows and
includes selected proof identity in ready inputs. Calendar import verifies a
complete contiguous SSE interval and original provenance without a Provider;
existing differing rows abort rather than overwrite. Scoped import locks and
rechecks the verified target calendar in the writing transaction.

Tester evidence: direct missing-API RED for three scoped nodes and one separate
calendar node; four new nodes GREEN and five relevant readiness/lifecycle/
data-sync/provider regressions PASS. After the calendar transaction race control
was added, only the three affected scoped nodes were rerun, all PASS. Negative
controls cover unrepresented symbols, invalid hashes, conflicting rewrites,
nonempty action mutation, native full replacement, exact calendar replay and
calendar mutation between prevalidation and write.

Actual private-export compatibility also PASS in the new tmpfs-only
`byq-phase17-market-2d004f7f` test database: 98 accepted source attestations,
151 calendar days / 98 open, 98 scoped proofs and factors, zero target actions
and zero global completeness rows. Calendar dataset digest:
`792f6cfb8753f0d06f4a7229cd253a07ec29a6aa85370dba3dfbee7d47a58b9f`.
This test used read-only source-code/export mounts and no source DB or Provider.
An initial runner could not read the private export mount; the same isolated
compatibility check then passed with the proper container UID.

Independent Reviewer: **Functional PASS / Tests PASS / Clean Break Architecture
PASS**, limited to this frozen source slice. Root accepts that scope. `.277`
manifest and Dockerfile are preserved; selected new `.278` manifest:
`sha256:8c9eeb1569643054a67e71e31ecab10d843035050de944b638b1485cd83afe3e`.
Independent identity gates PASS: current build 3/3, revision 4/4, retirement
5/5 and the one changed architecture selector. Required local syntax (10
changed files), docs (three files), isolated worktree and diff checks PASS. The
temporary test Postgres/network were exactly removed; no scoped volume exists.
Fresh target rebuild/import remain separate pending evidence.
The already passed broad suites are not rerun. Final Golden, actual enabled F6,
external calls and hosted CI remain **NOT_RUN**; Phase 17 is **OPEN**.

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
