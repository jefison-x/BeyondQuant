# Phase 0–6 gate record

## Phase 7 lifecycle ownership cutover review (2026-09-28)

Gateway now sends lifecycle evidence from its live Adapter event collector only;
the old lifecycle delivery worker and public status route are removed. Its
same-boot reconnect uses capped backoff and stops on release or boot change.
Adapter reaps released sessions after exact domain-call and terminal receipts,
while exact ACK response-loss retries remain idempotent. Selected build `.236`
binds this worktree; `.233`–`.235` are frozen intermediate candidates.

**Tester:** PASS — Gateway 284/284, Adapter root lifecycle 10/10,
architecture/build 86/86, three named reconnect/ACK/boot-fence regressions
3/3, and `git diff --check`. Containers used cached images, disabled
networking, and mounted the worktree read-only. **Independent Sol Reviewer:**
Functional PASS / Tests PASS / Clean Break Architecture FAIL. The Adapter still
writes and reads `LifecycleJournal` and exposes `/recover-evidence`; automatic
approval review twice rejected deletion of that path because it could remove
cross-process authorization and `outcome_unknown` protections. **Root gate:**
FAIL for the ownership cutover and Phase 7 overall. Phase 8 remains CLOSED.
No database, existing data, backup, production service, push or merge changed.

## Phase 7 Gateway carrier retirement gate (2026-09-28)

[Bounded evidence](phase7-gateway-carrier-retirement.md) removes the historical
Gateway recovery-carrier module and live import. An old carrier stops after
exact original receipt reconciliation, before dispatch or prompt; ordinary
first dispatch remains. Historical evidence reads its pinned source from Git.
Focused Gateway image tests passed 31/31, historical unittest 12/12 and
observer self-check passed. Selected `.232` freezes changed source; `.231`
remains immutable.

**Tester:** PASS — historical unittest 12/12, current/frozen build tests 12/12,
architecture 74/74, historical observer self-check with 25/25 negative
controls, syntax and diff checks. Root's isolated Gateway image run passed
31/31. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS after direct staged-diff, historical-source, receipt and
build review. **Root acceptance:** PASS for Gateway carrier retirement only.
The live Adapter journal, Gateway lifecycle delivery and Backend authority
fence remain; Phase 7 overall OPEN and Phase 8 CLOSED.

## Phase 7 Product MCP unknown-claim evidence gate (2026-09-27)

[Bounded evidence](phase7-product-mcp-unknown-claim-evidence.md) follows a real
Gateway Product turn and four Product MCP calls to one durable `executing`
strategy-validation claim. A test-only Backend callback exception produces
non-retryable `outcome_unknown`; Adapter PID-1 loss and a fresh boot leave the
old root/run revoked, that exact claim unchanged, zero artifacts and zero MCP
replay. The disposable stack and its images/credentials were removed. Selected
`.231` embeds its exact build identity; `.230` is frozen.

**Tester:** PASS — 12 focused build/retirement tests, 74 architecture tests,
syntax, shell and diff checks, selected `.231` and frozen `.230`. Root's
disposable Product MCP integration probe and separate `.231` image identity
check passed. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after direct staged-diff, contract, fixture,
build and evidence inspection. **Root acceptance:** PASS for this bounded
unknown-claim/Adapter-loss proof only. The injected exception does not prove
arbitrary power loss or external side-effect rollback; live journal, Gateway
lifecycle delivery and Backend authority fences remain. Phase 7 overall OPEN;
Phase 8 CLOSED.

## Phase 7 late domain-proof regression gate (2026-09-27)

[Bounded evidence](phase7-late-domain-proof-evidence.md) restores inert late
proof ingestion for exact existing-claim `unknown` receipts while new claims
and domain writes still require active root authority. Fresh isolated
PostgreSQL tests passed 47/47; current build/architecture tests passed 86/86.
Selected `.230` and frozen `.229` checks passed; disposable resources were
removed.

**Tester:** PASS for staged whitespace, syntax, docs, selected/frozen build
checks and 86 focused build/architecture tests; Root's disposable PostgreSQL
run passed 47/47. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after direct staged-diff and authority review.
**Root acceptance:** PASS for inert late evidence and exact existing-claim
reconciliation only. New claims and writes still require active authority.
The final cutover and post-deletion `outcome_unknown` proof remain unaccepted.
Phase 7 overall stays OPEN; Phase 8 stays CLOSED.

## Phase 7 executable recovery-carrier retirement gate (2026-09-27)

[Bounded evidence](phase7-carrier-retirement-build229-evidence.md) removes
Backend/Adapter recovery allocation and re-admission while keeping legacy rows
fail-closed at the domain-call and Gateway boundaries. Original reservation
reconciliation and unknown-outcome liability remain. Disposable Gateway 30/30,
Backend target 8/8, Adapter 12/12, historical evidence 24/24, and current build
and architecture 86/86 passed. Selected `.229` image identity and frozen `.228`
were verified; the disposable project was removed.

**Tester:** PASS for staged whitespace, syntax, docs, selected/frozen build
checks, 24 historical tests and 86 build/architecture tests; the recorded
Compose target runs passed Gateway 30/30, Backend 8/8, Adapter 12/12.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS for this bounded slice after direct staged-diff, boundary,
historical evidence and build-identity review. **Root acceptance:** PASS for
retirement of executable recovery-carrier paths and legacy-row rejection only.
The broader Backend run's unrelated active-root expectation failure remains
recorded; no full Backend suite PASS is claimed. The retained dead positive
contract helpers and final journal/authority cutover remain Phase 7 work.
Phase 7 overall stays OPEN; Phase 8 stays CLOSED.

## Phase 7 no-replay and build-identity repair gate (2026-09-27)

[Bounded evidence](phase7-no-replay-build227-evidence.md) removes Gateway's
automatic lost-reservation Agent prompt replay, preserves exact original
receipt/charge reconciliation and ordinary first dispatch, and creates immutable
selected build `.227` without rewriting `.226`. Isolated Gateway tests passed
30/30; 13 focused build tests and a disposable `.227` image/embedded-ID check
passed. Both test projects and temporary credentials were cleaned.

**Tester:** PASS for staged whitespace, local syntax, docs, 86 focused
root tests, and current/frozen build checks. Host Gateway/Backend tests lacked
FastAPI/SQLAlchemy; Root's isolated Gateway Compose run passed 30/30.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS for this bounded slice after inspecting the staged diff and
build identities. **Root acceptance:** PASS for no automatic lost-turn replay
and immutable `.227` selection only. Remaining Backend/Adapter recovery carrier
and final authority-fence deletion are not accepted by this gate. Phase 7
overall stays OPEN; Phase 8 stays CLOSED.

## Phase 7 overall acceptance attempt (2026-09-27)

**Reviewed HEAD:** `f418f0e3` on `clean-break/runtime-simplification`.
This is an overall phase gate, separate from the bounded slice PASS records below.
The review was read-only; no database, container, volume, backup or Product
service was changed, and no Phase 8 work began.

**Functional: FAIL for phase completion.** The accepted removal scope is not
finished. Adapter still owns `RuntimeSession`/`ActiveRun`/generation and a
session map (`services/runtime-adapter/app/runtime.py`), with a live v4
`LifecycleJournal`; Gateway still owns lifecycle recovery and durable delivery
(`services/gateway/app/main.py`, `agent_lifecycle_delivery.py`); Backend still
stores generic `agent_runtime_turns`/registration/receipt state
(`services/backend/app/agent_research.py`). Gateway's lost-reservation recovery
carrier also still has a path that submits a prompt and needs an explicit
ADR-002 disposition. The journal → Gateway → Backend path is currently a
business-call authorization fence, so none of these live pieces may be deleted
without the same-slice replacement and outcome-safety proof required by
[the authority cutover contract](phase7-authority-cutover.md).

**Tests: FAIL for overall gate.** Bounded live evidence passes Adapter death and
Product MCP silence, Gateway-only restart with an active root, and normal
`completed` exact close after a lost response. It does not test the final
post-deletion boundary or `outcome_unknown` after that cutover. The independent
Tester ran the historical archive contract (3/3 PASS) and docs check (127
changed Markdown files PASS). Current selected build revision `.226` failed
`tests/test_current_build_revision.py` (2 pass, 1 error): its manifest omits
11 Phase 7 evidence/fixture inputs and hashes drift for Backend main, the
Backend rotation test, and the MCP domain wire test. The independent Sol
Reviewer reproduced selected-build drift; local CI checks this identity before
image build. Branch-wide `git diff --check origin/main...HEAD` and
`dev-check.py --base origin/main` also fail on an inherited trailing blank line
in `services/backend/tests/test_research_plan_approval_contract.py:57`.
Focused Gateway host tests were NOT_RUN because FastAPI is unavailable in the
host environment; no full Docker or database test was rerun for this review.

**Clean Break Architecture: FAIL for phase completion.** The live generic
session/journal/replay ownership is still present, although bounded boot
rotation and exact close paths exist. The independently qualified transient
`ChildLease` watchdog is allowed by ADR-002 and is not a blocker. No current
authorization bypass was demonstrated; the blocker is that the current safety
fence has not yet been replaced and removed.

**Independent Sol Reviewer:** Functional FAIL / Tests FAIL / Clean Break
Architecture FAIL after direct code, ADR, contract, evidence and selected-build
inspection. **Root acceptance:** **NO PASS for Phase 7 overall**. Phase 7 stays
OPEN and Phase 8 stays CLOSED. Next, repair current build identity/branch gate,
resolve the lost-reservation replay disposition, complete the business-authority
cutover with unknown-outcome and concurrent-claim proof, then delete the
remaining generic Adapter/Gateway/Backend runtime owners in bounded slices and
repeat this overall gate. Prior slice PASS records remain valid only for their
stated boundaries.

## Phase 7 normal terminal close lost-response gate (2026-09-27)

[Live evidence](phase7-terminal-close-lost-response-evidence.md) exercises a fresh
six-service disposable Compose project through Product API, real Product MCP,
DSH and the Backend. A test-only private proxy forwarded the first exact root
close to Backend, received its 200 receipt, then dropped the Gateway response.
Backend root and fingerprint-bound AgentRun were already closed while Adapter
had no terminal ACK, Gateway retained one pending event, and a same-session
prompt was blocked with 409. A test-gated retry returned 503 without Backend
forwarding; after host release, an identical retry received the original
Backend receipt, Adapter journal acquired that ACK, and Gateway delivery became
`up_to_date`. The provider made no duplicate request. Six containers and all
project volumes, networks, images and temporary credentials were cleaned.

**Tester:** bounded PASS after direct six-file review, syntax/AST,
`dev-check`, docs and diff checks; the initial counter-label defect was fixed
and rechecked. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after direct interface, ADR, fixture, evidence
and incremental counter-label review. The reviewer did not rerun Docker; the
live Compose run and scoped teardown were performed by Root. **Root acceptance:**
**PASS for this normal terminal lost-response evidence slice only**. Phase 7
overall is OPEN; Phase 8 is CLOSED.

## Phase 7 active-root Gateway-only restart gate (2026-09-27)

[Live evidence](phase7-gateway-active-root-restart-evidence.md) uses a fresh,
scoped five-service Compose project. A durable test user starts a Product API
turn; real DSH calls Product MCP `byq_agent_run_start`; the Backend holds one
active root and one fingerprint-bound active AgentRun. The scripted model then
blocks. Restarting Gateway alone preserves the Adapter boot, Backend authority
epoch, root and AgentRun. The competing Product turn is rejected at Adapter
prompt admission with 409, and authenticated model request count stays 2→2.
The test project, volumes, network, images and temporary credentials were
cleaned; no Product runtime source or schema was changed.

**Tester:** bounded PASS for syntax, fail-closed runner preflight, staged diff
and evidence consistency; Docker was run by Root, not independently by Tester.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS after inspecting the actual final diff, schema, Compose,
credential boundary and ADR alignment. **Root acceptance:** **PASS for this
active-root restart evidence slice only**. Unknown-outcome roots, exact terminal
close, lost-response retry and old journal/replay removal remain open. Phase 7
overall is OPEN; Phase 8 is CLOSED.

## Phase 7 remaining authority cutover design gate (2026-09-27)

[Candidate contract](phase7-authority-cutover.md) traces the still-live Adapter
journal → Gateway lifecycle delivery → Backend root authority path. The first
candidate used a fresh per-call Adapter proof; Tester and independent Sol
Reviewer passed that **design-only** boundary, and Root accepted its safety
constraints in commit `811b12c9`. A subsequent supported-topology audit found
a simpler Compose-scoped alternative: Adapter is PID 1 in a private PID
namespace, so a killed container has no surviving DSH caller. The candidate
document now specifies this alternative, requires real container death proof,
Gateway-only restart behavior, Backend revocation-before-new-turn and exact
normal terminal close. **Tester:** revised design/static PASS (`check-docs.py
--base HEAD`, diff checks and effective Compose resolution). **Independent Sol
Reviewer:** Functional PASS / Tests PASS for design only / Clean Break
Architecture PASS after actual ADR, Compose, Dockerfile and credential-boundary
review. **Root acceptance:** PASS for the revised design boundary only. Phase 7
overall and Phase 8 remain closed; the current exact-root authorization fence
stays until the revised implementation passes its full gate.

## Phase 7 slice 10 gate — pinned foreground child process (2026-09-27)

[Slice record](phase7-live-child-process.md) adds an opt-in test against the
locked DSH 0.1.5rc1 Product composition. A real foreground child starts and
finishes; a blocked child hits its dedicated inactivity deadline or hard
cancel; each path closes the owned root process and rejects late success. No
Product runtime, DSH API, schema or status semantics changed. Current build
`.225` binds the test and CI invocation; `.224` is frozen.

**Tester:** isolated real DSH 3/3, ChildLease 6/6 and focused process cleanup
3/3 in its intended session fixture mode PASS. The initial combined cleanup
run had three fixture setup errors under root-turn mode; the corrected
session-mode run passed. Current/frozen build, 13 focused identity/CI checks,
docs, slice `dev-check` and diff checks PASS. Full Product/Backend/browser
journeys and remote CI are **NOT_RUN**. **Independent Sol Reviewer:**
Functional PASS / Tests PASS with those limits / Clean Break Architecture PASS
after direct test, CI, manifest and boundary review. **Root acceptance:**
**PASS for slice 10 only**. `ChildLease` remains the bounded, transient process
watchdog under ADR-002. Phase 7 remains open; Phase 8 remains closed.

## Phase 7 slice 9 gate — historical journal adoption and lease repair (2026-09-27)

[Slice record](phase7-journal-legacy.md) removes v1–v3 lifecycle-journal
migration, old-session lease reanchor, boot-stale archive operators and their
historical tests/runbook. The current v4 evidence journal, exact terminal ACK,
epoch write fence and Adapter → Gateway → Backend root authorization closure
remain. A missing executor epoch cannot bootstrap over any existing journal.
Current build `.224` binds the new source; `.223` is frozen. No database,
volume, container or Product API changed.

**Tester:** focused journal/executor 28/28, build identity 7/7, selected
architecture 3/3, `.223`/`.224` identity, slice `dev-check`, documentation and
diff checks PASS. Gateway lifecycle delivery 11 PASS; three host-only cases
could not import FastAPI, and focused Adapter process cleanup could not import
`deepseek_harness` on the host. The killed-Adapter → Gateway → Backend wire
journey is **NOT_RUN** because its live Backend/test environment is absent;
this is an integration limit, not a claimed PASS.
**Independent Sol Reviewer:** Functional PASS / Tests PASS with that limit /
Clean Break Architecture PASS after direct diff, caller, contract, build and
authorization-boundary review. **Root acceptance:** **PASS for slice 9 only**.
Old v1–v3 evidence must not be mounted into the fresh 0.10 environment with
active Backend roots. Phase 7 remains open; Phase 8 resource cleanup remains
closed.

## Phase 7 slice 8 gate — remove legacy terminal ACK migration (2026-09-27)

Gateway lifecycle delivery no longer scans old trace events to migrate the
pre-Clean-Break memory-only terminal ACK format, nor reports a fresh ledger as
pending solely because a migration flag is absent. Current exact Backend
receipt → Adapter terminal ACK delivery, finite retry and `outcome_unknown`
behavior remain. A fresh ledger reports `up_to_date`. The current immutable
build identity is `.223`; `.222` and earlier identities remain frozen.

**Tester:** Gateway delivery/trace 19/19 and focused Product cases 15/15 PASS;
the final fresh-ledger status assertion 1/1 PASS. Current/frozen build and 18
focused identity checks PASS; no removed production migration keys remain.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS after direct diff and exact receipt/retry review. **Root
acceptance:** **PASS for slice 8 only**. Phase 7 remains open; Phase 8 remains
closed.

## Phase 7 child watchdog disposition gate (2026-09-27)

[ADR-002](adr/ADR-002-dsh-boundary.md) and the
[ownership plan](ownership-and-deletion-plan.md) now retain the transient
`ChildLease` process watchdog under pinned DSH 0.1.5rc1. DSH executes the
child; the Adapter only validates live progress, bounds inactivity and closes
its dedicated root process on timeout. It does not persist or recover child
execution. A single root deadline cannot preserve the current long-progress
and sibling-stall behavior. This is a **KEEP qualification**, not a new runtime
implementation or approval to delete the guard.

**Tester:** docs check PASS, architecture 198/198, pinned SDK Adapter
`test_child_lease.py` 6/6 and focused cleanup 26/26, Gateway projection 31/31,
diff check PASS. Real DSH child-timeout Product journey **NOT_RUN**.
**Independent Sol Reviewer:** Functional PASS / Tests PASS for documentation
scope / Clean Break Architecture PASS after direct diff and runtime boundary
review. **Root acceptance:** **PASS for this retention decision only**. Phase 7
remains open; Phase 8 remains closed.

## Phase 7 slice 7 gate — dead restart rebase paths (2026-09-27)

After slice 6 removed old-session rebind, `RuntimeAdapter._record_containment`
and `LifecycleJournal.rebase` had no production callers. This slice deletes
those methods, the sole-use import and the obsolete rebase test. Containment
reads, terminal receipts, `outcome_unknown` and live business recovery remain.
The current immutable build identity is `.222`; `.221` is frozen.

**Tester:** pinned DSH 0.1.5rc1 Adapter focused tests 62/62 PASS, no remaining
references to the removed methods, 18 build identity checks and current/frozen
build validation PASS. **Independent Sol Reviewer:** Functional PASS / Tests
PASS / Clean Break Architecture PASS after direct diff and business recovery
review. **Root acceptance:** **PASS for slice 7 only**. Phase 7 remains open;
Phase 8 remains closed.

## Phase 7 slice 6 gate — lost Agent session does not replay (2026-09-27)

The 0.10 interruption scope now ends the old Agent session when its Adapter
process state is lost. Gateway attaches only to a surviving in-memory Adapter
session; a lost session returns `409 agent_session_interrupted` on attempted
operations and never recreates the old ID or reposts the original prompt.
Exact prompt receipts remain readable for `outcome_unknown`, and an authorized
new Agent session may query durable BYQ Jobs by `job_id`. Live resume and
child timeout/cancellation remain in place. No terminal trace event is
fabricated from an unproven process loss. The current build identity is `.221`;
frozen `.215`–`.220` are unchanged.

**Tester:** focused Gateway 54/54 and pinned DSH 0.1.5rc1 Adapter 55/55 PASS
with read-only source mounts; 18 focused build checks, `.221` current and
frozen build identities, documentation check and diff check PASS. **Independent
Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS
after actual diff, Product identity, receipt, ADR and build review. **Root
acceptance:** **PASS for slice 6 only**. Phase 7 remains open for further
runtime simplification and live child qualification; Phase 8 remains closed.

## General development verification policy gate (2026-09-27)

The maintainer extended risk-selected verification to all later BYQ development.
The [general workflow](../DEVELOPMENT_WORKFLOW.md#通用风险分级验证门禁)
now assigns focused local checks to each slice, complete affected-component
suites to required PR CI, and clean rebuild/Golden evidence to the relevant
phase milestone. The [CI policy](../operations/ci-policy.md) still requires
its selected checks; real UI journeys, security/financial invariants, retained
user-data safety, release Full CI and human merge/deployment gates remain.

**Tester:** `check-docs.py --base HEAD` PASS (4 Markdown files after the gate
record was added),
`dev-check.py --base HEAD` PASS (0 changed code files), `git diff --check HEAD`
PASS, architecture unittest 198/198 PASS; change classifier selected docs and
architecture only. Default branch-wide diff still finds the unrelated existing
blank line documented below. Product suites and hosted PR CI were NOT_RUN for
this documentation-only local change. **Independent Sol Reviewer:** Functional
PASS / Tests PASS for policy scope / Architecture PASS after direct diff and
ADR-0070/0088, CI, UI and data-safety review. **Root acceptance:** PASS for
the general verification-policy change only. Phase 7 remains open; this does
not authorize push, merge, deployment or historical-data deletion.

## Clean Break verification policy gate (2026-09-27)

The maintainer directed a lighter development-period gate: committed source
rollback and a rebuildable fresh Compose environment, without old user/runtime
data or cache restoration. [The verification policy](verification-gates.md)
now requires a scoped local check and focused contract evidence per slice,
retains required risk-selected hosted CI and Tester → independent Sol Reviewer
→ Root PASS, and schedules full rebuild/Golden verification after the fresh
schema baseline. This changes verification timing, not Product architecture,
financial/authorization invariants, archive requirements or merge authority.

**Tester:** changed-document links and whitespace PASS; Clean Break governance
2/2 and architecture 198/198 PASS; slice-scoped `dev-check.py --base HEAD`
PASS (no changed code files; component suites NOT_RUN). Default branch-wide
`make dev-check` finds a pre-existing trailing blank line in
`services/backend/tests/test_research_plan_approval_contract.py:57`, outside
this slice. **Independent Sol Reviewer:** Functional PASS / Tests PASS for
documentation scope / Clean Break Architecture PASS after direct diff and
ADR-0088/CI/phase-plan consistency review. **Root acceptance:** PASS for
the verification-policy change only. Phase 7 overall remains open; no runtime
code, database, container, CI workflow, PR or merge changed in this slice.

## Phase 7 slice 5 design gate — historical event/P4 archive (2026-09-27)

[Candidate design](phase7-historical-event-archive.md) passed the read-only Explorer → static Tester → independent Sol Reviewer → Root **design** gate. Before deletion, the same-slice contract test ran RED: the live ResearchTask action/approval boundary passed, all eight scoped archive paths remained, and replay READMEs lacked the pinned source pointers. The exact obsolete event contract, paired test, P4-A/B/C1 script directories and top-level harness tests are now deleted. Replay docs and the runtime-adapter test docstring pin historical source to `2f8aca4a877d01481be556236c8f56d6ad7fa290`. The post-delete contract (3/3), architecture/static/build checks (95), `.220` plus frozen `.215`–`.219`, historical release inputs, H4 (570/570; zero missing/stale/fake-pass) and diff check pass. **Tester:** isolated PostgreSQL 45/45, complete Gateway 275/275, repository unittest 868 OK (11 skipped), post-delete archive contract 3/3, `.220` and frozen `.215`–`.219`, historical release inputs, H4 570/570 (zero missing/stale/fake-pass), Compose selected Dockerfile and diff checks PASS. A real temporary worktree cleanup smoke also passed after Tester found a replay README cleanup defect and Root fixed it. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS after actual diff, frozen manifests, historical pointers and final README review. **Root acceptance:** **PASS for slice 5 only**. Phase 7 overall remains open for DSH Agent continuation and other live ownership work; Phase 8 remains closed.

## Phase 7 slice 4 gate — ResearchTask business action (2026-09-27)

The current event-state continuation ledger and its production imports are removed. A plan-bound approval and its exact ResearchTask action now commit atomically; identical decision POSTs can retry the pending action, while conflicting replays and missing actions fail closed. Product API exposes the action status without handing settlement to DSH. Historical P4 scripts and the unused event contract remain for a later bounded archival decision.

**Tester:** isolated PostgreSQL 45/45, complete Gateway 275/275, repository unittest 918 OK (11 skipped); current `.219` build, historical release inputs, H4 570/570 with zero stale/fake entries, and diff check PASS. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS after direct diff, SQL, Product projection and schema review. **Root acceptance:** **PASS for slice 4 only**. Pending actions require an identical decision POST for retry; `waiting_for_agent` and `needs_attention` remain unresolved. Phase 7 overall remains open because public DSH Agent attach/resume and child rebind contracts are absent; Phase 8 remains closed.

[Candidate design](phase7-pending-business-action.md) passes the read-only Explorer → static Tester → independent Sol Reviewer → Root **design** gate. Its approved boundary replaces event-as-state only with BYQ-owned pending business action, preserves exact approval/Job proof and unknown-outcome safety, and explicitly excludes DSH Agent continuation. A subsequent transaction/schema review selected one task-owned `research_task_actions` table with an atomic approval/action write, pending-only reconciler, stale-binding fail-closed rule and common lock order; independent Sol Reviewer marked that schema design GO. The design gate was followed by the tested slice implementation above. Phase 7 overall and Phase 8 remain closed.

## Phase 7 next live deletion qualification (2026-09-27)

After slice 3, read-only Explorer audits found no further standalone safe deletion in workflow, plugin, Backend runtime receipts or current DSH compatibility. Those paths carry live ResearchTask state, domain-call authorization, Product contracts or selected SDK/build provenance. `child_lease.py` is a live timeout and correlation guard; [its qualification record](phase7-child-lifecycle-qualification.md) is **NO-GO** for removal with locked DSH 0.1.5rc1. An official tagged-release check found that v0.1.7-rc.2 also lacks the required public Python root attach/resume/cancel/status and durable child rebind/status/cancel contract. Independent Tester verified the note and sources; independent Sol Reviewer returned Functional PASS / Tests PASS for documentation / Clean Break Architecture PASS and agreed the broader deletion remains NO-GO. Root accepts this **investigation result**, not Phase 7 completion. Phase 8 remains closed. Reopen a live deletion slice only with an exact-release DSH contract and same-slice replacement tests, or a separately bounded BYQ business-state rewrite that preserves authorization and outcome safety.

## Phase 7 slice 3 gate — standalone containment/recovery URL removal (2026-09-27)

[Slice record](phase7-gateway-containment-routes.md) binds the deletion to final candidate `1a825125`. The two standalone Gateway GET paths and OpenAPI operations are removed. Owner-scoped `GET /v1/agent/sessions/{id}` remains the Product API for normalized trace replay and fail-closed containment classification; no Adapter, Backend, DSH or financial safety path changed.

**Tester:** independent focused checks PASS (33 tests, H4 570/570, historical release, frozen `.215`–`.217` and current `.218` build, Compose, diff); its separate full run encountered read-only `.ci-artifacts` write errors and a Node worker environment failure. Root verified the final candidate in the approved offline, read-only Gateway container: **274 passed**, and ran full repository unittest with writable test artifacts: **918 tests OK, 11 skipped**. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS after directly inspecting the corrected replacement-route H4/OpenAPI entry and `.218` source binding. **Root acceptance:** **PASS for slice 3 only**. Phase 7 overall remains open; no Phase 8 cleanup, DB change, push or merge is claimed.

## Phase 7 slice 2 gate — advisory generation history removal (2026-09-27)

[Slice record](phase7-generation-ledger.md) binds the deletion to candidate commit `a2d134ed`. The file-backed generation ledger and duplicate in-memory history are removed; active generation fencing, lifecycle journal, containment and business recovery remain. Historical `dsh-0.1.5rc1` inputs are pinned to the exact pre-Clean-Break Git tree, while current source is bound by build revision `.217`.

**Tester:** independent static/build checks PASS (architecture 195, H4 572/572, historical release, `.215`/`.216`/`.217` manifests, promotion, Compose and diff); its unprivileged environment could not access Docker. Root completed the approved offline, read-only container run: Runtime Adapter **283 passed, 52 skipped**. Post-commit full repository unittest: **918 tests OK, 11 skipped**. **Independent Sol Reviewer:** Functional PASS / Clean Break Architecture PASS on actual diff, interfaces and historical release boundary; its Tests verdict was pending the Docker run, now satisfied by Root verification. **Root acceptance:** **PASS for slice 2 only**. Phase 7 overall remains in progress. This gate does not authorize Phase 8 cleanup, old database changes, push, PR readiness or merge.

## Phase 7 slice 1 gate — Gateway private proxy removal (2026-09-25)

The maintainer explicitly approved deletion of the six private Gateway pass-through routes. [Slice record](phase7-gateway-proxy.md) names their replacement Product API and exact scope. The first gate failed on old `.215` build-source drift; it remained closed while current build `.216` was added with a revision-specific Dockerfile and tracked Compose override. Frozen `.215`, original Adapter Dockerfile, DSH release descriptor and `compose.yml` stayed byte-identical. The H4 current interface ledger now has exactly the six removed routes retired and 572 surviving interfaces reviewed with zero stale/missing/fake entries.

**Tester:** PASS — Gateway 274/274 in offline read-only container; full architecture unittest 918 OK with 11 existing skips before the final Compose override; independent post-override architecture 195/195; current `.216` and frozen `.215` build checks, DSH release historical-input and promotion checks, reliability auditor, Compose default/explicit/CI resolution, shell syntax and diff check PASS. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS on actual diff, build identity, frozen sources and historical-test scope. **Root acceptance:** **PASS for slice 1 only**. Phase 7 overall is still in progress; no full-stack smoke, browser Golden Scenario, Phase 8 resource cleanup or database cleanup is claimed. The next Phase 7 slice requires its own bounded design, Tester, Reviewer and Root acceptance.

## Current activation follow-up (2026-09-25)

The planning verdict below predates [ADR-0088](../architecture/adr/ADR-0088-clean-break-baseline-activation.md). ADR-0088 records the maintainer's explicit Clean Break direction and activates the six 0.10 ADRs on this branch. Of 87 old ADRs, 82 are historical Product Core records and five retain only non-product governance/security scope. The former CLOSED verdict below is the original Phase 0–6 snapshot, not the latest activation outcome.

**Activation gate:** Tester PASS (195 architecture tests, 2 explicit Clean Break governance tests, 73 legacy governance tests, 105 changed Markdown files checked, build-revision check and `git diff --check`); independent Sol Reviewer **Functional PASS / Tests PASS / Clean Break Architecture PASS** after examining the actual diff, governance/security carve-outs and build-identity regression fix; Root **PASS** for the accepted 0.10 architecture and Phase 7 entry. Phase 7 may now perform bounded code deletion only after a same-slice public-contract/replacement test and its own Tester → Reviewer → Root gate. No Phase 7 code deletion had begun when this activation decision was recorded. Phase 8 resource/data cleanup remains CLOSED until the actual DB/resource identity and verified final archive are proven. The explicit governance test lives under `docs/clean-break/validation/` and is a named phase-gate command, not part of default `unittest discover -s tests`.

## Original Phase 0–6 planning record

Recorded 2026-09-25. The first-round read-only investigations were parallel where independent; documentation was assembled in one isolated worktree. No Phase 7 destructive work began. `PASS` below certifies the stated **planning-phase deliverable**, not Product runtime functionality or activation of a Proposed ADR.

| Phase | Tester evidence | Independent Sol Reviewer | Root acceptance |
|---|---|---|---|
| 0 — Development framework | TOML parse/role assertions PASS; 195 architecture tests PASS. Current session actually used Luna max Explorers/Tester and Sol medium Reviewer with one-writer ownership. Fresh CLI strict-config loaded files, but automatic Explorer dispatch could not be proved (first attempt: thread registration error; second: claim without spawn event). | Design PASS; automatic role routing unverified. | **PASS for merged BYQ defaults and exercised manual orchestration**; fresh-session automatic routing remains an explicit follow-up before relying on it. |
| 1 — Freeze | `HEAD`, `origin/main`, local tag and Clean Break base all `d4c6a9e34f531d27dd0e94804be6ed0aa6f9fde3`; isolated worktree script PASS. | PASS; P4 branch preserved. | **PASS**; tag local only. |
| 2 — Environment inventory | TSV internal counts/columns PASS: 3 containers, 156 image refs/150 IDs, 45 volumes, 5 networks; independent Tester could not access Docker socket. | PASS as read-only snapshot with explicit unknown DB. | **PASS for inventory**; source Docker metadata was read under approved escalation; live state can change. |
| 3 — Final archive plan | Markdown link/format checks PASS; no backup claimed. | PASS as plan; DB source/backup unknown. | **PASS for plan**, not archive execution. |
| 4 — ADR baseline | Six proposed ADR links/structure checked; architecture suite PASS. | Clean Break design PASS; acceptance and canonical supersession pending. | **PASS for proposed baseline**; no old ADR is yet retired. |
| 5 — Runtime ownership audit | Evidence paths and categories checked; no product runtime test claimed. | PASS; business safety versus generic recovery distinguished. | **PASS for audit**. |
| 6 — Deletion plan | `git diff --check`, all new-file whitespace checks and links PASS. | Functional PASS; Clean Break Architecture PASS for design. Phase 7 replacement contract detail must be checked per slice. | **PASS for reviewed plan**; Phase 7 entry remains CLOSED. |

## Verification summary

- `python3 -m unittest discover -s tests/architecture`: 195 passed.
- `python3 scripts/ci/verify-worktree.py <clean-break-worktree>`: PASS.
- TOML syntax/model/effort/concurrency checks, Markdown links, TSV counts, all-file whitespace and `git diff --check`: PASS.
- `make dev-check`: exit 0, but `files: 0`/`component_tests: NOT_RUN`. The first invocation saw untracked files; a repeat after staging also reported zero because its syntax scanner covers Python, shell and JSON, while this package contains TOML, Markdown and TSV. It is not counted as coverage of those formats.
- No Product API, browser, DSH runtime or Golden Scenario was run. No DB backup or Docker cleanup was performed.

## Original planning outcome (before ADR-0088 activation)

**Functional: PASS for Phase 0–6 planning package. Tests: PASS for focused static/architecture checks. Clean Break Architecture: PASS for proposed design. Phase 7 implementation gate: CLOSED.** It opens only after the new ADR baseline is explicitly accepted and integrated, old normative docs are superseded, each live deletion has a replacement interface and passing contract test, and the actual DB/retention state is identified before any data/environment destruction. A final verified DB archive is required before old DB volume cleanup. Human PR/merge gates continue to apply.
