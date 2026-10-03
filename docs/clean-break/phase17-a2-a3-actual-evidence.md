# Phase 17 — Actual connected follow-up and delegation

Status: **Golden A local PASS — research, multi-turn, delegation and browser**.
Tester → independent Reviewer → Root actual gates passed. Phase 17 remains
OPEN. This record uses the existing isolated `.280` stack and the already
qualified real Web Artifact/98-session TuShare cache; no source export, import,
market download or repository-wide test suite was repeated.

## Scope and pins

Branch `codex/clean-break-phase17`; pre-record HEAD
`94e22086cdbff15d0d691ee94d6f7cc28bb70090`. Application source
`afe529aa5ad264d5932ef14a7b354ca09cb37e2e`, build
`dsh-0.1.5rc1-post-u8.280`, manifest
`sha256:828b58684ae05f50f5e74995352ef30bc16295ce0740c44020426ca2f1c0d947`.
The unchanged 13-container target is `byq-dev-dd33416d94`, Workspace
`workspace_af43ba7a82524108ba11d4695613aafc`. Data and ML Workers stayed
stopped, TuShare credentials absent, F6 disabled. External test model calls
use the maintainer's 2026-09-30 continuing authorization; Product/domain
approvals and production/database boundaries remain separate.

## Preserved observer failures

1. The original A1 conversation was not reattached: a read-only Runtime check
   returned `qualified=false, reason=session_missing` after idle release. The
   planned old-conversation A2/A3 sent zero inputs and is **NOT_RUN**.
2. `/tmp/byq-phase17-280-connected` created an empty new conversation but sent
   zero turns. Its pre-input check incorrectly rejected an empty delivery
   projection with `state=pending` and all counters zero.
3. `/tmp/byq-phase17-280-connected-v2` actually completed START and A2 in
   `conversation_32c2e8109fb74e4db73e3c6dfb617744`, with new bound Task
   `task_16acfd96f1564c28b296fd29cfb41e0d`. A2 root
   `c79d900735bf4fec8d852c0e2e849b4d` completed, but the observer incorrectly
   expected one assistant record per turn. The answer was correctly projected
   and split into persisted WorkflowTrace sequences 34/35, 8,190/1,191 UTF-8
   bytes within the 8,192-byte contract. Independent offline qualification
   matches the actual public projection and splitter; no duplicate user input
   or domain write occurred. A3 was not sent. The frozen failure is preserved.
4. The original Native collector only scanned `session-*`; later live turns
   use `root-*`. A separate read-only collector captured the omitted A2 file
   without overwriting any prior result.

The new v3 uses fresh START/A3 domain keys and dynamically checks every answer
fragment by workflow sequence/content, nontruncation and UTF-8 byte bound. It
retains each turn's unique normalized user input, returned run ID, current-run
start/result, delivery `up_to_date`, bound Task and continuously open SSE.

## Actual three-turn journey

Private evidence: `/tmp/byq-phase17-280-connected-v3/FLOW`, mode 0700/0600.
Frozen runner SHA-256
`b38de73523b23cb057b196cda5cdda68aa070d83139f8841f472e88d7ac1a477`;
input SHA-256
`7cc5bddc8978d6c128c02860a1ddc70b089d31eee47b9534d6566bc21e0d456a`.
Tester → independent Reviewer → Root **PLAN PASS** preceded the sole launch.

Conversation `conversation_e6cffd5f798f43dc820d50296a2a1f31`, trace
`byq-trace-7023bc664eaf47c5bfb139f198bad78b`, internal Runtime session
`byq-session-9e57cf3107e94cdabc05d7909e25e625`.

| Turn | Accepted root run | Current terminal sequence | Actual outcome |
|---|---|---:|---|
| START | `672883fcc5ae47788648a76c4e449fdf` | 20 | Read existing real A1 Artifact and 98 cached sessions; created one new bound main Task. No Web/child. |
| A2 | `b56ffdf5801545fa84eb34e01cddd885` | 34 | Same live conversation/Task follow-up, same original evidence. No Web/child/write. |
| A3 | `b5070f2527ac46b591560937baf86156` | 55 | One actual market-research delegation, one child Web query, atomic new child Task/Artifact; parent read both and rediscovered them. |

Each turn returned one 202; the continuously open stream linked the exact
current run to `completed`. Final persistence is three user inputs and three
answer fragments, all delivered `up_to_date`. There was no input replay.
START reused the independently verified A1 public evidence; it did not perform
a new search. The A3 child supplied this journey's fresh Web evidence.

Main Task: `task_187db3a0703449468c2b963b31328f2d`. Child Task:
`task_63df479bc5fe4604b044868a0ad24f21`. Both are Backend-bound to the same
new conversation. Child Web Artifact:
`artifact_f1083cb1f00d4da08fc686cf492d53a9`, SHA-256
`e1db21aba57d3bc6746e10f5e8b416e88c737d4d1ee0f51480d7ac28f13378ba`.
Its exact lineage includes child/main Tasks, original read-only Artifact
`artifact_78ca187f18ed4f0880e84201e3231c14`, pool
`stock_pool_ba455d1da20c435a8b6ab3c233c5d8a4` and frozen snapshot
`stock_pool_snapshot_48f5fdb0812f50ff82b66f1d5bd86ae8c7dc5b826d201426e95728fe649915de`.

## Native/provider and domain evidence

The corrected inventory found exactly three new depth-zero roots and one
depth-one child `128d942d-73c7-482c-a874-20e0e492d517`, stored under A3's
root directory. Every recorded provider/model is `deepseek-official` /
`deepseek-v4-flash`. A3's parent called `byq_delegate_market_research` once;
the child called real `web_search` once with one query, and successfully called
`byq_web_evidence_create` once with the new fixed key. No second child or
market download is present. Each market read is `persisted_byq` / TuShare,
98 returned rows, usable/calendar-verified coverage and `live_provider_called=false`.

The draft child Artifact has seven unique HTTP(S) sources and four
`UNESTABLISHED` claims. All publication dates are unknown; titles/snippets and
claims were not independently verified against full source texts. Its policy
is `research_only=true`, `deterministic_input=false`,
`authoritative_market_data=false`. The cache and search are real evidence of
the product flow, not proof that a single-symbol sample excludes survivorship
bias or that any unestablished claim is supported. A child Task lookup sending
`task_id`/idempotency key without required `entity_id` returned a read error; the parent subsequently
read the exact created Task/Artifact successfully. No write was replayed.

Runtime's normalized model counter was 29 → 43 (14 root messages). Native
usage-bearing assistant messages were START 7, A2 2, A3 parent 5 and child 6.
The child six are accounted separately; the Runtime delta is not a global
root-plus-child request counter. **Raw model HTTP request count is NOT_OBSERVED.**

## Browser collection and qualification limit

The frozen v3 runner reached all three completed markers and saved full Product
readback, then failed while creating a second page in an implicit Playwright
context (`Please use browser.newContext()`). Its `STOPPED_NO_REPLAY` summary
and error are preserved. This is not an automated-runner PASS.

Separate zero-input browser collection read the same persisted conversation,
main/child Tasks, child Artifact and pool through Frontend/Gateway/Product API.
Agent DOM showed the main/child Task IDs and child Artifact; the Research Task
list showed both Tasks. Its first child-Artifact locator incorrectly waited
on the Task tab and timed out. A subsequent read-only collector used the real
Research Assets tab, filtered the exact Artifact, then Entity Query → exact ID
→ View. The rendered result matches the child Task, Artifact SHA, seven
sources, full policy and lineage. Its private `child-browser-v2-qualified.json`
is PASS; no additional model input or domain write was made. Screenshots are
private mode 0600; blocked cross-origin requests are zero.

Independent Tester: **PASS**, 17/17 actual checks, no mismatches; report
`independent-actual-qualification.json`, SHA-256
`878a64f52473706d8e734b7fa60b690f1bc59dde099e7033b90b121c6455e35d`.
The separate v2 projection check passed 12/12. Independent Reviewer:
**Functional PASS / Tests PASS / Clean Break Architecture PASS**. Root:
**GOLDEN A LOCAL PASS** for this research/multi-turn/delegation/browser scope,
including full old Task/Artifact comparison (only computed `handoff.observed_at`
excluded) and unchanged pool snapshot. The original automated-runner error is
not reclassified as PASS. Enabled F6, B–F, full Phase 17, hosted CI
and repository gates are not inferred from these actual A results.
