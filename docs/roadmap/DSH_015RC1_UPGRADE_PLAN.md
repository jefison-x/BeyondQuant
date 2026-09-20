# DSH 0.1.5-rc.1 Native Continuity Upgrade and Qualification (Stage D15)

Status: **D15-0 done, D15-1 candidate built/started/probed, D15-2 session V3
migration PASS (format layer only), D15-3 native persistence-layer session
resume PASS, D15-3R real isolated BYQ runtime-continuity qualification PASS
(scripted keyless provider; service-boundary, not real-LLM-quality), D15-4..D15-G
not started. `R3_RESUME = NO`.**
Relates: ADR-0079, ADR-0081, ADR-0058, ADR-0069, ADR-0003
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
| D15-1 | Candidate Runtime Upgrade | **machinery + isolated build/start DONE; D15-2..D15-G pending** |
| D15-2 | Session V3 Migration Qualification (format layer) | **PASS** |
| D15-3 | Native Session Resume Qualification (persistence seam) | **PASS** |
| D15-3R | Real Isolated BYQ Runtime-Continuity Qualification | **PASS** (scripted keyless provider) |
| D15-4 | Subagent/Fork Continuity Qualification | planned |
| D15-5 | Persistent Terminal Qualification | planned |
| D15-G | Architecture Go/No-Go | planned |

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

**Proof boundary.** The provider is scripted and keyless, so this is
service-boundary runtime-continuity evidence and **not** real-LLM-quality
semantic evidence. Host reboot is `NOT_RUN` (a container restart is not a host
reboot). D15-4/D15-5/D15-G and R3 are not in this batch.

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

## 5. D15-4 — Subagent / fork continuity

Verify parent/child identity, child session persistence, continuable descriptor,
cold resume, fork lineage, model/provider, persona, reasoning effort, tool
permissions/filter, parent or child crash, adapter restart and host restart.
Native `ContinuableActivationRegistry`/`Activation` semantics own residency;
BYQ must not persist subagent conversation state itself.

## 6. D15-5 — Persistent terminal

Verify page refresh, browser disconnect, frontend restart, gateway restart,
adapter restart, DSH runtime restart and host reboot, distinguishing PTY/process
existence, attachment existence, I/O rebind and stable terminal identity.
Ownership: BYQ owns `TerminalAttachment` identity/state/authorization/reconnect;
DSH owns PTY/shell/I/O. Terminal lifetime never defines conversation or durable
job lifetime.

## 7. D15-G — Architecture Go/No-Go

Produce a Go/No-Go report with a capability matrix over D15-2..D15-5 and the
failure matrix. No production cutover is implied by a Go. R6 completion does not
imply production cutover either.

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
deployment).
