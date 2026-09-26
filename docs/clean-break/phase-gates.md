# Phase 0–6 gate record

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
