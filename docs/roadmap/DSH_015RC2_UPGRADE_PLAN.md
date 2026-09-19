# DSH 0.1.5 Native Continuity Upgrade and Qualification (Stage D15)

Status: **PLANNED — D15-0 done, D15-1 candidate machinery done, D15-2..D15-G not started**
Relates: ADR-0079, ADR-0081, ADR-0058, ADR-0069, ADR-0003
Evidence: `docs/evidence/d15/`

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
- Upstream: npm `@deepseek-ai/dsh-*@0.1.5-rc.2` exists, but no Python
  `0.1.5rc2`; the bundled `runtime-bin==0.1.5rc1` contains npm `0.1.5-rc.1`.
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
| D15-1 | Candidate Runtime Upgrade | **machinery DONE; live build/start pending upstream pairing** |
| D15-2 | Session V3 Migration Qualification | planned |
| D15-3 | Native Session Resume Qualification | planned |
| D15-4 | Subagent/Fork Continuity Qualification | planned |
| D15-5 | Persistent Terminal Qualification | planned |
| D15-G | Architecture Go/No-Go | planned |

## 3. D15-2 — Session V3 migration

Fixtures: `docs/evidence/d15/fixtures/manifest.v1.json` (`F-*`).

Flow per fixture: `0.1.2 historical → migration → V3 → read → resume → append →
close → reopen`.

Acceptance:

1. Originals are immutable; migrated copies are written separately and the
   historical evidence is never overwritten.
2. Migration preserves event identity/order and terminal evidence; a failure is
   never silently treated as a new session.
3. Explicit downgrade feasibility is recorded; if the migrated form is not
   downgradable, that is stated rather than assumed.
4. `inheritedEventCount`/`isSeeded` fork prefixes survive correctly.
5. Unknown/future format versions fail closed with the documented refusal, not
   corruption.

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

"BYQ compatible with DSH 0.1.5-rc.2" and "Production default = DSH 0.1.5-rc.2"
are independent decisions. Neither is granted here.

## 9. Build revision

D15 changes runtime build inputs (new candidate declaration, candidate registry
script, compatibility module/route and tests). Per repository rules the
production build revision advances `post-u8.145` → `post-u8.146`; the historical
`.145` manifest and all existing evidence are retained.
