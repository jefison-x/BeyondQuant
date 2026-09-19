# DSH 0.1.5-rc.1 Native Continuity Upgrade and Qualification (Stage D15)

Status: **D15-0 done, D15-1 candidate built/started/probed, D15-2 session V3
migration PASS, D15-3..D15-G not started**
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
| D15-2 | Session V3 Migration Qualification | **PASS** |
| D15-3 | Native Session Resume Qualification | planned |
| D15-4 | Subagent/Fork Continuity Qualification | planned |
| D15-5 | Persistent Terminal Qualification | planned |
| D15-G | Architecture Go/No-Go | planned |

## 3. D15-2 — Session V3 migration (PASS)

Fixtures: [`docs/evidence/d15/fixtures/sessions/index.v1.json`](../evidence/d15/fixtures/sessions/index.v1.json)
(specification: [`fixtures/manifest.v1.json`](../evidence/d15/fixtures/manifest.v1.json)).

Flow per fixture: `0.1.2 historical → migration → V3 → read → resume → append →
close → reopen`.

Result (2026-09-19): **PASS.** 9/9 fixtures completed every stage, 0 blockers,
`all_post_migration_stages_pass=true`; 8 migrated (one real v0 store produced by
the isolated 0.1.2-rc.1 runtime, the rest deterministic released-v2 artifacts)
and one already-current v3 child. The migrated store is **not downgradable** by
`0.1.2-rc.1` (9/9 recorded). Fail-closed: future-version, unclassified-event,
malformed-header and refused-surface cases all surface the documented refusal
and are never converted to a fresh session.

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

Evidence: [`docs/evidence/d15/d15-2/`](../evidence/d15/d15-2/README.md)
(`migration-results.v1.json`, `fail-closed.v1.json`). Harness:
`scripts/d15/harness/migration_harness.mjs`. D15-2 adds test/evidence/docs under
the build-input inventory, so per repository rules the production build revision
advances `post-u8.147` -> `post-u8.148` (no selector/deployment change).

## 4. D15-3 — Native session resume

Exercise every failure-matrix row (Browser disconnect / Frontend restart /
Gateway restart / Adapter restart / DSH crash / RuntimeGeneration replacement /
Host reboot / executor takeover) and classify:

- `reattached` — live in-process generation reused;
- `rehydrated via native DSH resume` — 0.1.5 session handle opened and loop
  resumed natively;
- `rehydrated via BYQ fallback` — native resume unavailable, existing
  conversation-rehydration contract used;
- `interrupted` — run terminated and truthfully marked.

Internal diagnostic/evidence fields (e.g. `native_resume_used`,
`byq_fallback_used`, `previous_generation_state`) may be added, but the public
framework-neutral `fresh/reattached/rehydrated/interrupted` contract must not
change and the DSH session id must never become the BYQ `AgentSession` identity.

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
