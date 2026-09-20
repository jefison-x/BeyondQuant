# D15-3 — Native session resume qualification

Status: **PASS (native session resume only). No subagent/fork continuity
(D15-4), persistent terminal (D15-5) or Go/No-Go (D15-G) claim. Production
default remains `dsh-0.1.2rc1`; `R3_RESUME = NO`.**

- Raw observations: [`native-resume-observations.v1.json`](native-resume-observations.v1.json)
- Classified results: [`native-resume-results.v1.json`](native-resume-results.v1.json)
- Harness: [`../../../../scripts/d15/harness/native_resume_harness.mjs`](../../../../scripts/d15/harness/native_resume_harness.mjs)
  (+ `native_resume_worker.mjs`, `native_resume_common.mjs`)
- Classification: [`../../../../scripts/d15/native_resume_qualification.py`](../../../../scripts/d15/native_resume_qualification.py)
  over `packages/contracts/runtime_continuity.py::classify_generation_transition`

## Question

For a BYQ AgentSession whose old runtime generation disappears, can a **NEW
generation resume the SAME persisted DSH session natively**, instead of creating
a new DSH session and replaying BYQ conversation context?

## Harness design

The harness drives the **real DSH 0.1.5-rc.1 session-persistence seam** on a real
Cordis context, using only documented entry points — nothing is invented:

- `SessionPersistence.create(header)` / `SessionPersistence.open(id, access)`
  returning a `SessionHandle` (`@deepseek-ai/dsh-session-persistence`);
- `SessionHandle.read/append/flush/close` (`flush()` is the only durability
  barrier; `append` is best-effort);
- the shipped JSONL backend
  (`@deepseek-ai/dsh-session-persistence-jsonl`) whose cross-process
  `SessionWriteLease` is a non-blocking `flock(2)` on `session.lock`
  (contention → `SessionAlreadyOwnedError`; the kernel releases it on process
  death);
- `readColdSessionLog` (`@deepseek-ai/dsh-session-query`) for a cold,
  ownership-free read that folds an interrupted final turn with synthetic
  closers without writing back.

**One OS process == one runtime generation.** The orchestrator spawns
`native_resume_worker.mjs`; a new worker process opening the same session id is a
genuine cross-process native resume, and a `SIGKILL` of a holder exercises real
lease release on process death.

The harness records raw observations; the framework-neutral BYQ classifier maps
them onto the unchanged public continuity contract. No DSH event/session schema
is exposed publicly.

## Results

| # | failure row | generation | run lost | DSH session persisted | native resume | public continuity | native_resume_used | byq_fallback_used |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Browser disconnect | survives | no | yes | available | `reattached` | false | false |
| 2 | Frontend restart | survives | no | yes | available | `reattached` | false | false |
| 3 | Gateway restart | survives | no | yes | available | `reattached` | false | false |
| 4 | Adapter restart | replaced | no | yes | **yes (same id, contiguous)** | `rehydrated` | **true** | false |
| 5 | DSH crash | replaced | **yes** | yes | **yes (same id, interrupted turn preserved)** | `interrupted` | **true** | false |
| 6 | RuntimeGeneration replacement | replaced | no | yes | **yes (same id, contiguous)** | `rehydrated` | **true** | false |
| 7 | Host reboot | replaced | no | yes | **yes (same id, lease released)** | `rehydrated` | **true** | false |
| 8 | executor takeover | replaced | no | yes | **yes after fencing (same id)** | `rehydrated` | **true** | false |
| C | native-unavailable control | replaced | no | **no** | **no** | `rehydrated` | false | **true** |

Summary from `native-resume-results.v1.json`:
`failure_row_count=8, reattached=3, rehydrated=4, interrupted=1, fresh=0,
native_resume_available_count=8, native_resume_same_session_id_count=8,
native_resume_sequence_contiguous_count=8, byq_fallback_count=0,
native_resume_viable=true, native_unavailable_control_uses_byq_fallback=true`.

## What was real vs simulated (per row)

| row | real | simulated |
| --- | --- | --- |
| Browser disconnect | surviving in-process generation (live handle); append + flush after disconnect; independent read handle observes the log | browser WebSocket/HTTP transport drop (no browser in this isolated harness) |
| Frontend restart | concurrent read handle over the same session while the writer holds the lease; writer continues the sequence | frontend SPA reload |
| Gateway restart | `readColdSessionLog` cold read of the durable log; writer continues the persisted sequence | gateway process restart |
| Adapter restart | graceful handle close releases the lease; fresh backend `open(id, "write")` resumes the same session; append + flush | adapter process restart (fresh Cordis backend instance = new generation) |
| DSH crash | `flush` persisted an open turn; `SIGKILL` of the holder releases the kernel `flock`; new generation reads the interrupted turn; `readColdSessionLog` adds 2 synthetic closers | abrupt DSH process death mid-run |
| RuntimeGeneration replacement | generation-1 materializes and exits; generation-2 (new worker process) resumes the same durable identity | explicit generation rotation |
| Host reboot | durable log survives process death; kernel releases the lease (no stale lease); new generation resumes | host reboot (all processes killed without cleanup) |
| executor takeover | live writer fenced with `SessionAlreadyOwnedError`; after death the new executor takes over natively | executor identity rotation |
| control | a session that never reached the `flush()` barrier is invisible to `stat`/`open`; the refused open fabricates nothing | crash before the durability barrier |

No browser, frontend, gateway or adapter service runs in this isolated harness;
those rows model the transport/lifecycle fault and exercise the runtime/DSH
boundary that actually determines resumability. The process/host rows are real
cross-process operations.

## Proof boundary (what D15-3 does and does not prove)

**Proven here.** A new OS process can natively reopen the same persisted DSH
session through the real 0.1.5-rc.1 persistence seam, with the same session id, a
preserved event log and a contiguous sequence, including across a real `SIGKILL`
(lease released by the kernel) and a genuinely separate generation process.

**Not proven here.** No browser, frontend, Gateway or BYQ runtime-adapter service
is started or restarted; the corresponding rows model the transport/lifecycle
fault and exercise the runtime/DSH boundary only. D15-3 therefore does not
demonstrate, end to end, that after a real process/host fault:

- the original AgentSession goal is preserved and resumed (not silently lost);
- a domain action is executed at most once (no duplicate side effect);
- a previously granted approval is still valid for the resumed turn;
- the final result remains traceable to the originating run/session.

Those semantic guarantees require a **real isolated runtime qualification** that
runs the BYQ services and asserts persistence and domain behavior. That run is a
required next step; it is not claimed by D15-3 and must not be inferred from the
`reattached`/`rehydrated`/`interrupted` labels alone.

## Native resume viability and R3

**Native session resume is viable for every persisted failure-matrix row**:
all eight rows show the same session id, a preserved event log and a contiguous
sequence after a new generation opened the session natively (8/8). The only
non-resumable case is a session that crashed **before** the `SessionHandle.flush()`
durability barrier — a session that never materialized never existed — and there
BYQ conversation fallback is required (proven by the control).

Conclusion: **R3 should NOT re-implement native session resume.** The 0.1.5
`SessionPersistence`/`SessionHandle`/`SessionWriteLease` seam already provides
same-session native resume across adapter restart, DSH crash, generation
replacement, host reboot and executor takeover, with truthful interrupted-run
reporting. Re-implementing it would duplicate the native runtime and violate the
"no second generic agent harness" rule. This does **not** unfreeze R3: the R3
freeze stands and `R3_RESUME` stays **NO** until D15-G completes.

What R3 still legitimately owns after D15: generation health, executor epoch
fencing, invoking native attach/resume, **falling back to BYQ conversation
rehydration when native resume is unavailable**, lifecycle observation and
resource cleanup.

## Contract

The public framework-neutral continuity vocabulary is unchanged
(`fresh | reattached | rehydrated | interrupted`, `runtime-continuity.v1`). The
native-vs-fallback mechanism is recorded only in internal, evidence-only
diagnostics (`native_resume_used`, `byq_fallback_used`,
`previous_generation_state`, `native_session_present`), which are not projected
to any public/browser contract. The DSH session id never becomes the BYQ
AgentSession identity: the classifier takes no identity and the evidence keeps
`native_session_present` as a boolean only.

## Build revision

D15-3 adds `scripts/`, `tests/`, evidence and `packages/contracts` code, all part
of the BYQ build-input inventory, so the production build revision advances
`post-u8.148` → `post-u8.149` (rebuild identity only: no selector,
`compose.yml`, `deployment.json`, immutable release registry or 0.1.2
artifact/evidence change and no deployment).
