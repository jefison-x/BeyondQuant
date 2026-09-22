# DSH 0.1.5-rc.1 Native Continuity Upgrade and Qualification (Stage D15)

## Current superseding decision — ADR-0084（2026-09-21）

The status block and D15 evidence below preserve their historical qualification facts. ADR-0084
changes gate scope without rewriting them:

- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
  `BLOCKED_EXTERNAL`; they do not become PASS or optional native capabilities.
- B3 `terminal-adapter-restart` and B4 `terminal-dsh-runtime-restart` have later
  candidate/qualification-layer PASS overlays; the committed D15-5/D15-G snapshots remain
  immutable.
- Historical D15-G remains `NO_GO`, but B1/B2 no longer globally block 0.9 closeout, candidate
  compatibility, the bounded R3 failure-containment scope, or unrelated roadmap work.
- The next required slice is BYQ session failure containment and business recovery. It must
  record lost execution as `interrupted`, fence stale generations and late results, preserve
  durable business identity/receipts, retry only safe idempotent work, and pause unknown side
  effects. It must not claim that an unavailable child was resumed.
- After that slice, create a new named D15 superseding assessment. Do not rerun merely to replace
  the old label, do not overwrite old evidence, and do not wait for the upstream provider before
  continuing work that does not depend on native independent-child recovery.

### Named D15 superseding assessment (established 2026-09-22)

The named superseding assessment is now established in
`codex/v090-d15-superseding-assessment` (evidence `docs/evidence/d15/d15-superseding/`;
fail-able observer `scripts/d15/superseding_assessment/observer.py`). It references the
historical D15-4/D15-5/D15-G verdicts without rewriting them and independently derives:

- historical D15-G `NO_GO_PRESERVED` (the committed NO_GO and its four atomic blockers are
  unchanged);
- the ADR-0084 replacement gate **BYQ session failure containment and business recovery**
  `PASS` (real isolated acceptance 9/9, containment/classification, cleanup zero, production
  untouched);
- the coherent DSH `0.1.5-rc.1` repository default upgrade `PASS` (readiness matched, 0.1.2rc1
  rollback preserved, no production deployment claimed);
- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` `BLOCKED_EXTERNAL`;
  B3/B4 candidate-layer `PASS_CANDIDATE`; native independent child resume `NOT_IMPLEMENTED`;
- candidate compatibility for the **actually adopted scope** `PASS` and promotion
  `REPO_DEFAULT_PROMOTED` (repository default only; production deployment/release/tag remain
  separate);
- the bounded R3 scope `[safe_failure, observation, cleanup, new_generation_recovery]` with
  `R3_RESUME = NO`.

This does not rerun D15-G, does not deploy, does not create a tag/release, does not resume
Phase 100 and does not start 0.10. Because the assessment adds build inputs (and the
follow-up authority-table consistency fix adds a governance test), the identity advanced
`post-u8.200 -> post-u8.201 -> post-u8.202`.

### Independent final 0.9 development closeout (complete 2026-09-22)

The independent final 0.9 development closeout is now complete
(`V090_DEVELOPMENT_CLOSEOUT_COMPLETE`), derived by the machine-readable, fail-able matrix in
`docs/evidence/v090-final-closeout/` (observer `scripts/v090/final_closeout/observer.py`).
It independently re-derives every required 0.9 development item from the original merged
evidence and hashes: the ADR-0084 replacement gate (BYQ session failure containment and
business recovery) PASS, the coherent DSH `0.1.5-rc.1` repository default upgrade PASS, the
named D15 superseding assessment ESTABLISHED, B1/B2 `BLOCKED_EXTERNAL` (only limiting native
independent child resume), B3/B4 candidate-layer `PASS_CANDIDATE`, historical D15-G
`NO_GO_PRESERVED`, native independent child resume `NOT_IMPLEMENTED` and `R3_RESUME = NO`.
The development closeout does **not** deploy, does **not** create or move a tag/release, does
**not** resume Phase 100 and does **not** start 0.10; the repository default DSH `0.1.5-rc.1`
is **not** a production deployment and the formal 0.9.0 release manifest gate remains open.

The next state is the **maintainer testing and 0.9.x minor feature addition/optimization
window**; `R3_RESUME` stays `NO` until a separate explicit step. Because this batch adds build
inputs (`scripts/`, `tests/`), the identity advances `post-u8.202 -> post-u8.203`; the
named-review fact-consistency fix (stale top current-state marker removal and `维护（当前）`
attribution correction) advances it again `post-u8.203 -> post-u8.204`.

`R3_RESUME` remains `NO`: this assessment only establishes the **bounded permitted R3
scope** (safe failure, observation, cleanup, new generation recovery). Actually starting or
implementing R3 requires a subsequent explicit step, and the final 0.9 closeout does not
automatically start R3. ADR-0084 does not automatically switch the production selector or
authorize deployment/release/tag.

Status: **D15-0 done, D15-1 candidate built/started/probed, D15-2 session V3
migration PASS (format layer only), D15-3 native persistence-layer session
resume PASS, D15-3R real isolated BYQ runtime-continuity qualification PASS
(scripted keyless provider; service-boundary, not real-LLM-quality), D15-4
PARTIAL/BLOCKED (native subagent/fork seam qualified in an evidence-only
harness; child-crash and BYQ adapter-restart required items BLOCKED; host reboot
NOT_RUN), plus a candidate-specific continuable-wiring investigation (product
semantics PASS in an isolated native harness and real isolated candidate image;
BYQ adapter-restart child rebind still BLOCKED), D15-5 persistent-terminal (PTY)
PARTIAL/BLOCKED (real isolated native terminal seam; page-refresh,
browser-disconnect, frontend-restart and gateway-restart PASS; adapter-restart
and DSH-runtime-restart required items BLOCKED; host reboot NOT_RUN — see §6),
D15-G architecture Go/No-Go **NO_GO (NOT-PASS)**: a fail-able decision contract
and observer derive the verdict from the committed D15-2..D15-5 evidence and
reject partial-PASS aggregation; the four atomic required items child-crash, BYQ
adapter-restart, terminal adapter-restart and terminal DSH-runtime restart did
not pass, while host reboot stays an OPTIONAL limitation NOT_RUN. The
cross-process terminal reattach boundary is a Proposed, unimplemented ADR-0083.
`R3_RESUME = NO`.**
Relates: ADR-0079, ADR-0081, ADR-0058, ADR-0069, ADR-0003, ADR-0084
Evidence: `docs/evidence/d15/`
Target decision: [`docs/evidence/d15/target-decision.v1.json`](../evidence/d15/target-decision.v1.json)

This stage supersedes the previously planned R3 supervisor implementation as the
next Runtime Continuity step. It does **not** renumber or rewrite R0–R2. R3 is
frozen, not rolled back (ADR-0081).

## 0. Ground truth (2026-09-19)

- Production default and runtime selector: `dsh-0.1.2rc1`
  (`config/dsh/deployment.json`, `compose.yml`,
  `BYQ_DSH_COMPATIBILITY_RELEASE` default `dsh-0.1.2rc1`).
- R0/R1/R2 are landed and Accepted (ADR-0079): lifecycle model, stable executor
  lease + monotonic epoch fencing, durable `AgentSession` vs ephemeral
  `RuntimeGeneration`, continuity vocabulary `fresh/reattached/rehydrated/interrupted`.
- R3 (`codex/phase-r3-supervisor`) has **no commits** beyond the R2 merge; the
  branch points at `6f5254b` and contains no supervisor code. R3 was never
  implemented.
- Upstream: the maintainer set the qualification target to the coherent official
  pairing `dsh-v0.1.5-rc.1` / Python `0.1.5rc1` / bundled npm `0.1.5-rc.1`
  (`docs/evidence/d15/target-decision.v1.json`). The originally requested npm
  `0.1.5-rc.2` has no PyPI Python `0.1.5rc2`; `runtime-bin==0.1.5rc1` bundles npm
  `0.1.5-rc.1`, and rc.2 remains not-a-coherent-pairing.
- 0.1.5 ships native Session V3 migration, handle-based session persistence,
  cross-process write leases, continuable subagents and persistent terminal
  tooling. See `docs/evidence/d15/compatibility-ledger.v1.json`.

> **Current update (2026-09-22, default upgrade).** The retained 0.9 closeout
> step "formally upgrade the repository default dependency/selector" has been
> executed in `codex/v090-dsh-015rc1-default-upgrade`:
> `config/dsh/deployment.json` default is now `dsh-0.1.5rc1` and `dsh-0.1.2rc1`
> is the registered rollback candidate; the registered descriptor/lock,
> selector identity, production Dockerfile, dependency pins, compose default and
> build identity (`dsh-0.1.5rc1-post-u8.200`) all move to the coherent
> `0.1.5-rc.1` pairing. This is a repository-default change only: it does **not**
> deploy to production, does not create a tag/release, does not generate a D15
> superseding assessment, keeps B1/B2 `BLOCKED_EXTERNAL` and historical D15-G
> `NO_GO`, and does not start 0.10. Evidence:
> `docs/evidence/v090-dsh-015rc1-default-upgrade/`.

## 1. R3 freeze

R3 status: `PAUSED_PENDING_DSH_015_NATIVE_CONTINUITY_QUALIFICATION`.

Existing R3 code/tests/docs and framework-neutral contracts are retained. R1/R2
are not rolled back. Further implementation is paused for: self-built DSH
process-restart orchestration, self-built DSH session reconstruction, self-built
native-session-persistence substitute, self-built subagent persistence,
self-built persistent PTY/shell runtime, and anything DSH 0.1.5 covers natively.

The pause is a **prerequisite**, not an R3 failure: implementing a second
continuity runtime before qualifying the native one would duplicate state and
violate the "no second generic agent harness" rule.

## 2. Sub-stages

| id | name | state |
| --- | --- | --- |
| D15-0 | Upgrade Recon | **DONE** |
| D15-1 | Candidate Runtime Upgrade | **machinery + isolated build/start DONE** |
| D15-2 | Session V3 Migration Qualification (format layer) | **PASS** |
| D15-3 | Native Session Resume Qualification (persistence seam) | **PASS** |
| D15-3R | Real Isolated BYQ Runtime-Continuity Qualification | **PASS** (scripted keyless provider) |
| D15-4 | Subagent/Fork Continuity Qualification | **PARTIAL/BLOCKED** (native seam PASS; child-crash + BYQ adapter-restart BLOCKED; host reboot NOT_RUN) |
| D15-5 | Persistent Terminal Qualification | **PARTIAL/BLOCKED** (real native terminal seam; page-refresh/browser-disconnect/frontend-restart/gateway-restart PASS; adapter-restart + DSH runtime restart BLOCKED; host reboot NOT_RUN; see §6) |
| D15-G | Architecture Go/No-Go | **NO_GO (NOT-PASS)** (decision contract + fail-able observer; partial-PASS aggregation rejected; four atomic required blockers child-crash/BYQ-adapter-restart/terminal-adapter-restart/DSH-runtime-restart BLOCKED; host reboot OPTIONAL NOT_RUN) |

## 3. D15-2 — Session V3 migration (PASS, format layer)

Fixtures: [`docs/evidence/d15/fixtures/sessions/index.v1.json`](../evidence/d15/fixtures/sessions/index.v1.json)
(specification: [`fixtures/manifest.v1.json`](../evidence/d15/fixtures/manifest.v1.json)).

Flow per fixture: `0.1.2 historical → migration → V3 → read → resume → append →
close → reopen`.

Result (2026-09-19): **PASS at the session-format layer only.** 9/9 fixtures
completed every stage, 0 blockers, `all_post_migration_stages_pass=true`; 8
migrated (one real v0 store produced by the isolated 0.1.2-rc.1 runtime, the rest
deterministic released-v2 artifacts) and one already-current v3 child. The
migrated store is **not downgradable** by `0.1.2-rc.1` (9/9 recorded).
Fail-closed: future-version, unclassified-event, malformed-header and
refused-surface cases all surface the documented refusal and are never converted
to a fresh session.

**Scope:** `resume` is `Session.fromRestore`, `append` is hand-built events
encoded with the released v3 codec, and `close`/`reopen` are file/codec
operations. This is codec/catalog migration evidence, **not** runtime recovery:
it does not exercise a BYQ runtime process, `SessionHandle.flush()` durability,
a live `SessionWriteLease`, or AgentSession goal/approval/result continuity.
Those are deferred to the real isolated runtime qualification below.

**Verdict integrity.** `scripts/d15/harness/migration_verdict.mjs` computes an
explicit verdict over manifest conformance, explicit per-stage success
(`read`/`resume`/`append`/`close`/`reopen`), migration completion, sequence
continuity, id continuity, context preservation, append+reopen,
non-downgradability, no blockers, and every fail-closed rejection; the harness
exits non-zero unless all pass. Completeness is mandatory: the required fixture
set (count/uniqueness/no missing/extra), required stages and required rejection
cases come from the single `requirements` block in
[`acceptance-matrix.v1.json`](../evidence/d15/acceptance-matrix.v1.json); empty,
missing, duplicate, unexpected, missing-stage and missing-evidence inputs FAIL,
and required evidence is never defaulted to pass. `negative-controls.v3.json`
(17 controls) confirms the result-layer and completeness faults fail while the
pre-fix stage-only gate recorded `legacy_exit_code=0`, and records the review
repro `computeVerdict([], {cases:[one valid]})` flipping pre-fix PASS to post-fix
FAIL.

Acceptance:

1. Originals are immutable; migrated copies are written separately and the
   historical evidence is never overwritten. **PASS** (sha256 index; harness
   scratch copies).
2. Migration preserves event identity/order and terminal evidence; a failure is
   never silently treated as a new session. **PASS**.
3. Explicit downgrade feasibility is recorded; if the migrated form is not
   downgradable, that is stated rather than assumed. **PASS** (not
   downgradable).
4. `inheritedEventCount`/`isSeeded` fork prefixes survive correctly. **PASS**
   (`f-forked`: seeded cut marker seq 7 -> target inherited count 9).
5. Unknown/future format versions fail closed with the documented refusal, not
   corruption. **PASS**.
6. The verdict fails on any broken invariant, rejection case or blocker and the
   exit code reflects it; negative controls prove the pre-fix gate would have
   passed. **PASS** (`verdict.v3.json`, `negative-controls.v3.json`).
7. The verdict validates the required fixture set (count/uniqueness/no
   missing/extra), required stages and required rejection set from the single
   acceptance-matrix manifest, and fails on missing required evidence instead of
   defaulting to pass. **PASS** (17 negative controls incl. the review repro).

Evidence: [`docs/evidence/d15/d15-2/`](../evidence/d15/d15-2/README.md)
(`migration-results.v3.json`, `verdict.v3.json`, `fail-closed.v3.json`,
`negative-controls.v3.json`; the v1/v2 artifacts are preserved). Harness:
`scripts/d15/harness/migration_harness.mjs` +
`scripts/d15/harness/migration_verdict.mjs` +
`scripts/d15/harness/migration_negative_controls.mjs`. D15-2 adds
test/evidence/docs under the build-input inventory, so per repository rules the
production build revision advances `post-u8.147` -> `post-u8.148` (no
selector/deployment change).

## 4. D15-3 — Native session resume (PASS)

The isolated harness `scripts/d15/harness/native_resume_harness.mjs` drives the
real 0.1.5-rc.1 session-persistence seam (`SessionPersistence.create/open`,
`SessionHandle.read/append/flush/close`, cross-process `SessionWriteLease`
`flock`, `readColdSessionLog`) with **one OS process per runtime generation**.
`scripts/d15/native_resume_qualification.py` classifies every failure-matrix row
through `packages/contracts/runtime_continuity.py::classify_generation_transition`.

Result (2026-09-19): **PASS.** All eight failure rows show the DSH session
persisted and natively resumable with the same session id, preserved event log
and contiguous sequence:

| failure row | continuity | mechanism |
| --- | --- | --- |
| Browser disconnect | `reattached` | live generation survives |
| Frontend restart | `reattached` | live generation survives; concurrent read handle |
| Gateway restart | `reattached` | live generation survives; cold read replay |
| Adapter restart | `rehydrated` | native DSH resume (same session) |
| DSH crash | `interrupted` | lost run truthfully marked; same session natively resumable |
| RuntimeGeneration replacement | `rehydrated` | native DSH resume (same session) |
| Host reboot | `rehydrated` | native DSH resume; kernel releases the flock lease |
| executor takeover | `rehydrated` | flock fences the live writer, then native takeover |

A native-unavailable control (a session that crashed before the `flush()`
durability barrier) is correctly not resumable and requires BYQ conversation
fallback. Conclusion: **native session resume is viable; R3 must not
re-implement it** (it only owns invoking native attach/resume, epoch fencing,
the BYQ fallback when native resume is unavailable, lifecycle observation and
cleanup). The R3 freeze stands and `R3_RESUME = NO` until D15-G.

**Scope / proof boundary.** D15-3 proves native persistence-layer resumability
across a genuinely new OS process. No browser, frontend, Gateway or BYQ
runtime-adapter service is started or restarted; those rows model the
transport/lifecycle fault (the process rows are real cross-process operations).
D15-3 therefore does **not** prove BYQ runtime-level semantic recovery: original
goal preservation, domain-action at-most-once, approval validity and result
traceability remain unverified. A **real isolated runtime qualification** that
runs the BYQ services and asserts persistence plus domain behavior is a required
next step and is not claimed here.

Evidence: [`docs/evidence/d15/d15-3/`](../evidence/d15/d15-3/README.md)
(`native-resume-observations.v1.json`, `native-resume-results.v1.json`).

Internal diagnostic/evidence fields (`native_resume_used`,
`byq_fallback_used`, `previous_generation_state`, `native_session_present`) are
evidence-only: the public framework-neutral `fresh/reattached/rehydrated/
interrupted` contract is unchanged and the DSH session id never becomes the BYQ
`AgentSession` identity.

## 4b. D15-3R — Real isolated BYQ runtime continuity (PASS)

A real isolated BYQ stack (dedicated compose project `byq-d15-runtime`, dedicated
network/volumes, fresh PostgreSQL, loopback-only ports) ran the rebuilt fixed
`dsh-0.1.5rc1` candidate runtime-adapter together with the real Gateway, Backend
and MCP services. A keyless deterministic loopback provider drove the turns.

Result (2026-09-20): **PASS** for adapter/DSH process interruption+restart,
Gateway disconnect/reconnect, generation replacement, DSH child interruption and
executor takeover. Each row records before/after session, goal, approval,
action-receipts, result, adapter pid, generation and executor epoch; original
goal retained; redelivery deduplicated with one side effect; approval not
bypassed; result traceable; generation replacement produced a new generation and
executor takeover incremented the monotonic epoch `1 -> 2` with an immutable
audit and no database write.

**Proof boundary (historical D15-3R batch).** The provider is scripted and
keyless, so this is service-boundary runtime-continuity evidence and **not**
real-LLM-quality semantic evidence. Host reboot is `NOT_RUN` (a container restart
is not a host reboot). D15-4, D15-5, D15-G and R3 were not in this D15-3R batch.
This paragraph records only the historical batch scope: D15-4 was qualified
separately as PARTIAL/BLOCKED (§5b), D15-5 is PARTIAL/BLOCKED (§6), and D15-G was
subsequently executed and is **NO_GO** — see the current result in §7. The
"D15-G remains NOT_RUN" wording that appeared here described the batch at the
time and is superseded by §7.

**Review-fix revision (v2, 2026-09-20).** The observer separates `format_valid`
(the artifact is well formed) from `all_pass` (the qualification passed). A
REQUIRED scenario left `NOT_RUN`/`BLOCKED` makes the verdict non-zero while
preserving its status/reason; OPTIONAL scenarios (e.g. `host-reboot`) are
declared separately and do not gate required coverage.
`allowed_continuity`/`forbidden_continuity` come only from the trusted contract.
PASS requires real PID/generation/epoch relationships and receipt/trace linkage.
The selfcheck executes a reconstructed legacy algorithm to prove the pre-fix
behaviour rather than asserting it. The isolated stack rebuilds Backend/Gateway/
MCP from the branch (a stale production image lacked pool idempotency).

**Capture-layer revision (v3, 2026-09-20).** `capture()` no longer fabricates
evidence: missing durable journal receipt / replay error / mismatched replay run
id produce `capture_ok=false` + `capture_errors` and a scenario `FAIL`; the
approval `state`/`decided_by` are read from the persisted approval and real
REJECT + invalid-reuse deny trials are attempted with no-side-effect assertions;
`trace_contiguous` is computed from the full persisted sequence and the result is
attributed to the target run (`terminal_kind`, `attributed_message_sequence`);
`make_receipt` requires a measured `side_effect_count` and a labeled `origin`;
and manual Product actions are distinguished from Agent→MCP execution
(`agent_mcp_tool_calls=0`). **v1/v2 are retained but are not a qualification
pass.** Evidence:
[`docs/evidence/d15/d15-runtime/`](../evidence/d15/d15-runtime/README.md)
(`observations.v3.json`, `verdict.v3.json`, `negative-controls.v3.json`,
`capture-negatives.v3.json`, `stack.v3.json`, per-row `scenarios/*.v3.json`).
Harness:
`scripts/d15/runtime_continuity/{contract.v3.json,observer.py,capture_negatives.py,scripted_provider.py,run_qualification.py}`
and `tests/test_dsh_d15_runtime_{continuity,capture}.py`. The observer is
fail-able: 35 negative controls plus 5 capture-layer negatives each force a
non-zero exit while a known-good unit fixture passes.

**Scope/approval/Agent-MCP revision (v4, 2026-09-20).** The scripted provider
emits a real `mcp__byq__byq_research_task_create` tool call through the real
runtime-adapter → MCP → Backend; the adapter is restarted and the same
idempotency key re-delivered, returning the same task id with a measured
side-effect count of 1 (new required scenario `agent-mcp-domain-at-most-once`).
Approval denial now records the HTTP status/domain code and actually attempts the
protected backtest operation with the rejected approval, verifying the
authoritative backtest-job count before/after (invalid reuse 409, protected
operation 422 `product_domain_rejected`, count `0 -> 0`). Capture negatives add
`denial-from-500-timeout` and `rejected-response-but-side-effect-exists`. Docs
explicitly separate a **limited service-boundary observation pass** from a **full
original-task qualification**: v4 is the former (scripted keyless provider), not
real-LLM-quality, and v1/v2/v3 are retained history that do not constitute a
qualification pass. Evidence:
[`docs/evidence/d15/d15-runtime/`](../evidence/d15/d15-runtime/README.md)
(`observations.v4.json`, `verdict.v4.json`, `negative-controls.v4.json`,
`capture-negatives.v4.json`, `stack.v4.json`, `scenarios/*.v4.json`).

**Two-run replay + post-fault approval revision (v5, 2026-09-20).** The
Agent→MCP scenario now holds the first and second run/message separately, waits
for the second run's own tool call, terminal and attributed assistant, and
correlates both real tool responses by run id, tool_call_id and the same task id
with a measured side-effect count of 1 (the scripted provider records a real
tool-call/result history; it emitted the tool call twice). A replay synthesized
from the current task id can no longer pass. Approval trials are labelled
`pre-fault`/`post-fault`, and every recovery `after` capture actually re-requests
the invalid reuse and re-attempts the protected backtest operation after the
fault, measuring authoritative before/after counts. New capture negatives:
`agent-mcp-second-no-tool`, `agent-mcp-second-mcp-failed`,
`agent-mcp-only-first-run`. Evidence:
[`docs/evidence/d15/d15-runtime/`](../evidence/d15/d15-runtime/README.md)
(`observations.v5.json`, `verdict.v5.json`, `negative-controls.v5.json`,
`capture-negatives.v5.json`, `stack.v5.json`, `scenarios/*.v5.json`).

## 5. D15-4 — Subagent / fork continuity

Verify parent/child identity, child session persistence, continuable descriptor,
cold resume, fork lineage, model/provider, persona, reasoning effort, tool
permissions/filter, parent or child crash, adapter restart and host restart.
Native `ContinuableActivationRegistry`/`Activation` semantics own residency;
BYQ must not persist subagent conversation state itself.

## 5b. D15-4 — Native subagent / fork continuity (PARTIAL/BLOCKED)

The native continuable-subagent/fork seam was qualified against the fixed
0.1.5-rc.1 candidate in an **evidence-only** harness
(`scripts/d15/subagent/native_subagent_harness.mjs`) that boots the real
`@deepseek-ai/dsh-agent-loop` + JSONL session persistence +
`@deepseek-ai/dsh-subagent` + spawn/fork providers with one OS process per
generation and a scripted keyless adapter. Six required scenarios PASS:
parent/child identity (`d15-4-parent` vs a distinct durable child with
`header.parentSession`, `origin=subagent`), versioned `subagent/descriptor`
(mode=continuable), new-OS-process cold resume of the same child with one
settlement, seeded fork (`inheritedEventCount=11`, parent immutable),
provider/model/reasoning-effort/persona inheritance reapplied on cold resume,
and SIGKILL of the owning process with the durable parent identity and child
still natively resumable. Six runtime negatives are rejected (non-direct/stale
parent `UNAUTHORIZED`, unmaterialized `NOT_RESUMABLE`, `maxDepth`
`SubagentDepthError`, child-claims-root `DUPLICATE_CHILD`, out-of-filter tool).
The fail-able observer separates format validity from qualification and gates on
required coverage; `negative-controls.v1.json` has 23 controls (22
defect-targeting, including the pre-fix result-only gate wrongly passing a
report with required BLOCKED scenarios).

**Reachability (probed for real, `reachability.v1.json`).** The committed BYQ
composition loads all five `byq_delegate_*` tools with
`enableRunInBackground: false`, and the candidate
`@deepseek-ai/dsh-tool-subagent@0.1.5-rc.1` only calls `startContinuable()` on
the background+continuable branch, so the continuable residency/cold-resume path
is **not reached from BYQ**; `Dsh015Compatibility` still inherits the 0.1.2
observation contract. Two required scenarios are therefore **BLOCKED** with the
smallest concrete option recorded (an isolated D15 compose stack plus a
tool-aware scripted provider, without changing the production composition or
adding BYQ subagent persistence): `child-crash` (in-process children are not
isolatable for a child-only SIGKILL) and `byq-adapter-restart` (no BYQ path
drives `startContinuable`). `host-reboot` is OPTIONAL `NOT_RUN` and is never
labelled as a container restart. **No D15-4 full pass, no D15-G pass and no
full-D15 claim; `R3_RESUME = NO`.**

**Review-fix revision (v2, 2026-09-20).** `child-crash` and
`byq-adapter-restart` remain **required** and stay named **BLOCKED** (the stage is
not passed by deleting them). A real *supporting* scenario `child-run-fault` (the
child's model stream fails while the parent process stays alive) records a
truthful "failed before it finished" settlement, a retained child id and native
resumability; the owning-process SIGKILL is kept only as native executor evidence
and is not used as the child fault or BYQ adapter recovery. `fork-lineage` now
requires the **exact** inherited cut (`inheritedEventCount == last turn/end seq +
1`), **full parent-log hash and length equality** before/after and a contiguous
child log; new observer controls cover off-by-one, zero, payload drift, length
mismatch and child sequence gap. Every temp root is removed in a `finally`
(including worker exception/timeout paths) with recorded `cleanup`/`root_cleaned`
evidence, and the unsupported claim that a native rejection proves a nonexistent
pre-fix gate is removed (the only pre-fix comparison is the observer's real
reconstructed legacy algorithm).

**Routing / process-boundary investigation (2026-09-20).** A real trial
(`scripts/d15/subagent/routing_probe.mjs`, evidence `routing.v1.json`), one OS
process per trial with every trial temp root removed in a `finally` with retry
(`runtime_root_cleaned=true`), executes the candidate
`@deepseek-ai/dsh-tool-subagent` through `ctx.tools.execute`: the
committed BYQ config (`enableRunInBackground:false`, no `backgroundMode`) is
foreground (`start=1`, `startContinuable=0`); `backgroundMode:continuable` with
the in-process `spawn` provider reaches `startContinuable`; any provider without
`prepareContinuable` (models the out-of-process `dsh-sdk`/ACP/Codex/Claude Code
backends) is rejected with `does not support \`backgroundMode: continuable\``.
Only `subagent-spawn-in-process` and `subagent-fork-in-process` implement
`prepareContinuable`, so **native 0.1.5rc1 provides no independent-process
continuable child provider**; `@deepseek-ai/dsh-subagent-dsh-sdk` is published at
rc.1 but is not in the candidate bundled runtime list and also lacks
`prepareContinuable`. The BYQ hookup to `startContinuable` is a product-semantics
change (foreground result → durable background child; blast radius: composition,
delegate tool contract, runtime-adapter child-lease path, 0.1.2 compat boundary).
It exceeds this PR's qualification scope and still cannot satisfy
`child-crash`/BYQ adapter restart, so D15-4 stays `BLOCKED`; the minimal
candidate-compatible hookup is planned for an independent worktree/feature PR.
The CI contract test now accepts D15-4 `BLOCKED` **only** with named
`uncovered_items` and asserts D15-G/R3 are not opened.

Evidence: [`docs/evidence/d15/d15-4/`](../evidence/d15/d15-4/README.md)
v2 (current): `native-observations.v2.json`, `verdict.v2.json` (`all_pass=false`,
six required PASS + one supporting PASS + two required BLOCKED),
`negative-controls.v2.json` (28 controls, 27 defect-targeting),
`reachability.v1.json`, `routing.v1.json`, `scenarios/*.v2.json`; v1 is preserved
unchanged. Contract/observer:
`scripts/d15/subagent/{contract.v1.json,observer.py,reachability_probe.mjs,routing_probe.mjs}`
and `tests/test_dsh_d15_4_subagent.py`.

## 5c. D15-4 candidate-specific continuable wiring (PARTIAL; BLOCKED items gate)

The committed `byq_delegate_*` tools stay on the production foreground path. A
**separate** candidate profile
(`plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/`) is generated by
`scripts/dsh/candidate_profile.py generate-continuable` and baked only into
`services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-continuable-candidate`:
`provider: spawn`, `backgroundMode: continuable`,
`enableRunInBackground: true`. The production `dsh-0.1.2rc1` profile
(`byq-product.patch.yml`), `deployment.json`, `compose.yml` and the selector are
unchanged; the two profiles differ **only** in the five delegate routing keys and
share identical delegate tool filters and MCP boundary.

Real isolated native observations (`continuable-observations.v1.json`,
`native-runtime-isolated`, one OS process per generation) drive the actual tool
via `ctx.tools.execute` for all five same-class delegates and show: the
continuable result shape `{kind: continuable, subagentId}`, durable child-id
persistence (v3 `mode=continuable`, parent link, `origin=subagent`), exactly one
settlement per child turn with no duplicate, child lease/observation linked to the
original delegation call and goal, no orphan after the parent ends, and **new-OS-
process cold resume PASS** (same child, contiguous, one settlement). This cold
resume is **separately tested** from a child-only SIGKILL, which remains
`BLOCKED` (only in-process continuable providers). A real isolated trial of the
**committed** candidate image (`continuable-adapter-restart.v1.json`) shows
generation A PASS (the real adapter returns continuable and persists the child)
and generation B `BLOCKED`: a fresh adapter exposes only the root
`resume_session`, the byte-identical 0.1.2 Python SDK exposes no
child/subagent/continuable operation, and no committed BYQ surface rebinds the
persisted child after an adapter restart. **No provider and no R3 behaviour were
added; independent child-process capability stays BLOCKED.**

The fail-able observer `scripts/d15/subagent/continuable_wiring_observer.py`
has 25 defect-targeting controls and the committed verdict is `format_valid=true`,
`wiring_ok=true`, `all_pass=false` with `child-crash` and
`byq-compose-adapter-restart` required-`BLOCKED` and gating. Rebinding a
continuable child across a BYQ adapter restart is a real architecture boundary
change; it is recorded as the **Proposed, unimplemented**
[ADR-0082](../architecture/adr/ADR-0082-dsh-continuable-child-resume.md) and was
**not** implemented. D15-4 therefore stays `BLOCKED`; `R3_RESUME = NO`.

## 6. D15-5 — Persistent terminal

Verify page refresh, browser disconnect, frontend restart, gateway restart,
adapter restart, DSH runtime restart and host reboot, distinguishing PTY/process
existence, attachment existence, I/O rebind and stable terminal identity.
Ownership: BYQ owns `TerminalAttachment` identity/state/authorization/reconnect;
DSH owns PTY/shell/I/O. Terminal lifetime never defines conversation or durable
job lifetime.

**Result: `PARTIAL/BLOCKED`.** The real isolated native terminal seam
(`@deepseek-ai/dsh-terminal` owner-scoped `TerminalSessionService` +
`@deepseek-ai/dsh-terminal-bash` `shell` backend under `bwrap --die-with-parent`)
was driven with one runtime OS process per generation and separate client OS
processes, wrapped by an evidence-only BYQ `TerminalAttachment` gate
(identity/state/authorization/reconnect; no PTY/shell/I/O). Evidence:
`docs/evidence/d15/d15-5/`.

- Four client-side rows `PASS` (page refresh, browser disconnect, frontend
  restart, gateway restart): a different client OS process rebinds the same
  attachment/session/pid (`io_rebind=ok`, `terminal_identity=stable`).
- The unique-marker cross-process command test `PASS`es: the first marker appears
  once in the first client's viewport, zero times in the rebind send delta (no
  replay) and once in retained scrollback (no loss); the second marker appears
  once.
- `permission-boundary` (`FOREIGN_SESSION`/`UNAUTHORIZED_PRINCIPAL`),
  `wrong-terminal-rejected` (`NO_SESSION`), `stale-generation-fenced`
  (`STALE_GENERATION`/`STALE_EPOCH`) and `cleanup-no-orphans` (all pids dead,
  shutdown orphans `0`) all `PASS`. `pty-attachment-separation` proves the four
  dimensions are independent.
- `adapter-restart` and `dsh-runtime-restart` stay required `BLOCKED`: native
  sessions are documented process-local and the committed BYQ tree composes no
  terminal service and persists no `TerminalAttachment`. Real rejection evidence
  is recorded; no fabricated reattach. Host reboot is `NOT_RUN`.
- The fail-able observer (`observer.py`) separates format-valid from
  qualification-pass and exits non-zero on the two required `BLOCKED` rows; 24
  negative controls (23 defect-targeting) prove the pre-fix result-only gate
  wrongly passed. The framework-neutral vocabulary lives in
  `packages/contracts/terminal_attachment.py`.
- The cross-process reattach boundary is recorded as the **Proposed,
  unimplemented** [ADR-0083](../architecture/adr/ADR-0083-terminal-attachment-boundary.md).
  D15-G waited for D15-4 and D15-5 and is now **NO_GO**; `R3_RESUME = NO`.

## 7. D15-G — Architecture Go/No-Go (NO_GO / NOT-PASS)

Result (2026-09-20): **NO_GO (NOT-PASS).** A fail-able decision contract
(`scripts/d15/go_no_go/contract.v1.json`) and observer
(`scripts/d15/go_no_go/observer.py`) derive the verdict from the committed
D15-2..D15-5 evidence. GO is granted only when every required capability is
actually `PASS`; one required non-PASS capability forces NO_GO and must be named
as an actionable blocker. Only atomic required capabilities can be blockers;
aggregate capabilities are display-only (derived from their atomic members) and
optional capabilities are limitations that never gate GO. The observer rejects
partial-PASS aggregation into GO, a claimed status that differs from the derived
status, missing blockers, an aggregate/optional listed as a blocker, missing or
hash-mismatched source evidence and self-declared verdict/coverage fields.
`negative-controls.v1.json` records 19 controls, all rejected (18
defect-targeting: the reconstructed pre-fix result-trusting gate passed them),
while a synthetic fixture with every required capability PASS and an optional
host-reboot NOT_RUN yields an honest GO and passes.

The capability matrix (`docs/evidence/d15/d15-g/capability-matrix.v1.json`)
covers D15-2..D15-5 with per-item DSH-native result, BYQ fallback and R-series
owner, split into required-atomic, derived-aggregate and optional-limitation.
Derived required capabilities: `root-session-persistence` PASS,
`process-restart-resume` PASS, `fork-continuity` PASS, `terminal-client-reattach`
PASS; `subagent-child-crash`, `subagent-byq-adapter-restart`,
`terminal-adapter-restart` and `terminal-dsh-runtime-restart` BLOCKED. The
aggregates `subagent-resume` and `terminal-persistence` display BLOCKED because
they are derived from those atomic members. `host-reboot-resume` is an OPTIONAL
limitation NOT_RUN (matching the D15-4/D15-5 contracts) and is not a blocker.
NO_GO is decided solely by the four atomic required blockers: child-crash, BYQ
adapter-restart, terminal adapter-restart and terminal DSH-runtime restart.

A GO would not imply a production cutover; R6 completion does not imply
production cutover either. The Proposed ADR-0082/0083 remain not accepted and not
implemented, R3 stays frozen and the production selector/default are unchanged.
Evidence: `docs/evidence/d15/d15-g/`.

## 8. Roadmap reorder

`R0 → R1 → R2 → D15 → R3 → R4 → R5 → R6 → independent Production Go/No-Go`

- **R3 Thin Runtime Supervisor** (redefined): only RuntimeGeneration health;
  executor epoch/fencing; DSH native session attach/resume; native-resume
  failure fallback; lifecycle observation/reporting; resource cleanup. It is
  **not** conversation canonical history, **not** a DSH session-store
  substitute, **not** subagent persistence, **not** a terminal PTY runtime.
- **R4 TerminalAttachment** (redefined): attachment lifecycle, not a terminal
  runtime.
- **R5 DurableJob independence**: must not depend on Browser/Frontend/
  AgentSession/RuntimeGeneration/DSH process/TerminalAttachment.
- **R6 Full Runtime Continuity Qualification** (redefined).

"BYQ compatible with DSH 0.1.5-rc.1" and "Production default = DSH 0.1.5-rc.1"
are independent decisions. Neither is granted here.

## 9. D15-1 isolated build / start / probe

The coherent rc.1 candidate was built and started in isolation with no
production traffic:

- Candidate image `byq-d15-1-0.1.5rc1-candidate:local`
  (`sha256:96bf63272b988c049656d20e2390e60e21711d2c498e8c9ccf8ccd2af849371f`)
  from `services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-candidate` +
  `requirements.dsh-0.1.5rc1-candidate.lock` (exact 0.1.5rc1 wheels with hashes).
- Keyless start + scripted-provider turn + tool call observed with contiguous
  event sequence; profile/composition load with the BYQ product patch succeeded.
- Evidence: `docs/evidence/d15/d15-1/candidate-build.v1.json`,
  `docs/evidence/d15/d15-1/candidate-start-probe.v1.json`.
- Production default selector, `compose.yml`, `deployment.json`, 0.1.2 artifacts
  and all prior evidence are unchanged. Rollback remains `dsh-0.1.2rc1`.

## 10. Build revision

D15-1 adds runtime build inputs (candidate Dockerfile, candidate requirements
lock and probe). Per repository rules the production build revision advances
`post-u8.146` → `post-u8.147`; the historical `.146` and `.145` manifests and all
existing evidence are retained.

D15-2 adds test code, fixtures and evidence under `tests/` and `scripts/`, which
are part of the build-input inventory, so per repository rules the revision
advances `post-u8.147` -> `post-u8.148`. This is a rebuild identity bump only: no
selector, `compose.yml`, `deployment.json` or 0.1.2 artifact/evidence change and
no deployment.

D15-3 adds a harness under `scripts/d15/`, tests, evidence and contract code
under `packages/contracts`, all part of the build-input inventory, so the
revision advances `post-u8.148` -> `post-u8.149`. Again a rebuild identity bump
only: no selector, `compose.yml`, `deployment.json`, immutable release registry
or 0.1.2 artifact/evidence change and no deployment.

The D15-2 verdict-integrity rectification adds `migration_verdict.mjs` and
`migration_negative_controls.mjs` under `scripts/d15/`, updates
`tests/test_dsh_d15_2_migration.py` / `tests/test_dsh_d15_3_native_resume.py` and
adds v2 evidence, all build-input files, so the revision advances
`post-u8.150` -> `post-u8.151` (rebuild identity only; no selector, deployment,
immutable release registry or 0.1.2 artifact/evidence change and no deployment).

The D15-2 verdict-completeness rectification further changes build-input files
(`scripts/d15/harness/migration_verdict.mjs`,
`scripts/d15/harness/migration_negative_controls.mjs`, `tests/`), so the manifest
is regenerated. `#326` (CI-A) merged into `main` at `post-u8.154`; this branch
merged `origin/main` and bumped to the next unused id `post-u8.155` (`.151`–`.154`
are taken). The `.155` manifest is created new; no prior immutable manifest
(`.151`–`.154`) is modified and no `main` history is rewritten. Selector,
`compose.yml`, `deployment.json`, the immutable release registry and 0.1.2
artifacts/evidence are unchanged, and no deployment occurs.

D15-3R adds the runtime-continuity harness, observer, contract and tests under
`scripts/d15/` and `tests/`, which are part of the build-input inventory, so the
revision advances `post-u8.159` -> `post-u8.160` (`.158`/`.159` were already
taken by in-flight/main identities). This is a rebuild identity bump only: no
selector, `compose.yml`, `deployment.json`, immutable release registry or 0.1.2
artifact/evidence change and no deployment.

The D15-3R observer review-fix revision changes `scripts/d15/runtime_continuity/`
and `tests/` build inputs again, so the revision advances
`post-u8.160` -> `post-u8.161` (again a rebuild identity bump only; no selector,
deployment, immutable release registry or 0.1.2 artifact/evidence change and no
deployment).

The D15-3R capture-layer review-fix revision changes `scripts/d15/runtime_continuity/`
and `tests/` build inputs again, so the revision advances
`post-u8.161` -> `post-u8.162` (rebuild identity bump only; no selector,
deployment, immutable release registry or 0.1.2 artifact/evidence change and no
deployment). The D15-3R scope/approval/Agent-MCP revision changes the same build
inputs again, advancing `post-u8.162` -> `post-u8.163` (rebuild identity only).
The D15-3R two-run replay revision changes the same build inputs again,
advancing `post-u8.163` -> `post-u8.164` (rebuild identity only).

D15-4 adds `scripts/d15/subagent/` (native harness, contract, observer,
reachability probe), `tests/test_dsh_d15_4_subagent.py` and
`docs/evidence/d15/d15-4/`, all build-input files, so the revision advances
`post-u8.164` -> `post-u8.165` (rebuild identity only; no selector,
`compose.yml`, `deployment.json`, immutable release registry or 0.1.2
artifact/evidence change and no deployment).

The D15-4 review-fix revision changes the same build inputs again (harness exact
fork-cut/hash checks, child-run-fault scenario, `finally` temp cleanup; observer
fork deriver/controls; tests), so the revision advances
`post-u8.165` -> `post-u8.166` (rebuild identity only; the v1 evidence is
preserved and no selector, deployment, immutable release registry or 0.1.2
artifact/evidence changes).

The D15-4 routing/investigation revision adds `scripts/d15/subagent/routing_probe.mjs`,
updates `tests/test_dsh_d15_candidate.py` and `tests/test_dsh_d15_4_subagent.py`,
all build-input files, so the revision advances `post-u8.166` -> `post-u8.167`
(rebuild identity only; no selector, deployment, immutable release registry or
0.1.2 artifact/evidence change).

The routing-probe cleanup fix (one OS process per trial plus `finally` root
removal with retry) changes `scripts/d15/subagent/routing_probe.mjs` and
`tests/test_dsh_d15_4_subagent.py` again, so the revision advances
`post-u8.167` -> `post-u8.168` (rebuild identity only).

The D15-4 candidate-specific continuable wiring adds
`scripts/d15/subagent/{continuable_wiring_contract.v1.json,continuable_wiring_observer.py,continuable_wiring_probe.mjs}`,
`scripts/dsh/candidate_profile.py` continuable generation, the
`plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/` profile,
`services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-continuable-candidate`,
`services/runtime-adapter/tests/d15_continuable_probe.py`,
`tests/test_dsh_d15_4_continuable_wiring.py` and
`docs/evidence/d15/d15-4/continuable/`, all build-input files, so the revision
advances `post-u8.168` -> `post-u8.169` (rebuild identity only; no selector,
`compose.yml`, `deployment.json`, immutable release registry or 0.1.2
artifact/evidence change and no deployment).

D15-5 adds `scripts/d15/terminal/` (native terminal harness, acceptance contract,
fail-able observer, interface probe), `tests/test_dsh_d15_5_terminal.py`,
`packages/contracts/terminal_attachment.py` and `docs/evidence/d15/d15-5/`, all
build-input files, so the revision advances `post-u8.169` -> `post-u8.170`
(rebuild identity only; no selector, `compose.yml`, `deployment.json`, immutable
release registry or 0.1.2 artifact/evidence change and no deployment). The
Proposed ADR-0083 remains unimplemented.

D15-G adds `scripts/d15/go_no_go/` (Go/No-Go decision contract, fail-able
observer, provenance builder), `tests/test_dsh_d15_g_go_no_go.py` and
`docs/evidence/d15/d15-g/`, all build-input files, so the revision advances
`post-u8.170` -> `post-u8.171` (rebuild identity only; no selector,
`compose.yml`, `deployment.json`, immutable release registry or 0.1.2
artifact/evidence change and no deployment). The Proposed ADR-0082/0083 remain
not accepted and not implemented; `R3_RESUME = NO`.
