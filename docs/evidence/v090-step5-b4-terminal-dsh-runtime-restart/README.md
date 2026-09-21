# 0.9 strict-order step-5 slice 4 — `terminal-dsh-runtime-restart` (`d15-5-candidate-attachment-layer`)

- Status: **PASS (candidate/qualification layer)** — the BYQ attachment layer
  truthfully records native-state loss as `lost` across a **real DSH runtime
  OS-process restart**, never fabricates a reattach, reconciles a **surviving
  PTY with no attachment** as `lost`, and proves terminal lifetime does not
  define conversation or durable-job lifetime.
- Date: 2026-09-21
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm
  `0.1.5-rc.1`
- ADR: [ADR-0083](../../architecture/adr/ADR-0083-terminal-attachment-boundary.md)
  (Accepted 2026-09-21; candidate-specific and reversible, **not** productionized)
- Owner node: `d15-5-candidate-attachment-layer` (pre-gate; never post-GO R4)
- G-split strict internal order: B2 (executed, BLOCKED-external) → B3
  (`terminal-adapter-restart`, PASS) → **B4 `terminal-dsh-runtime-restart` (this slice)**

This slice does not re-run D15-G and does not start R3/R4/R5/R6. It adds **no**
production wiring, no BYQ PTY runtime, no DSH fork or patch and no second
generic harness or second session store.

## The one question

After generation A establishes a real native persistent terminal plus a durable
BYQ `TerminalAttachment`, is the **DSH runtime OS process truly terminated and
restarted**, and does generation B reconcile the durable attachment and record
native-state loss truthfully (`lost`/`interrupted`) — never fabricating a
reattach? When a **surviving PTY has no attachment**, is it reconciled as `lost`
and never silently reused? Does terminal lifetime stay independent from
conversation and durable-job lifetime?

## Answer: yes — and the honest loss is distinguishable from "not implemented"

The probe (`scripts/d15/terminal/dsh_runtime_restart_harness.mjs`) runs inside
the real native DSH 0.1.5-rc.1 closure. It **reuses the committed B3 native
runtime role** (`adapter_restart_harness.mjs runtime`), which owns the real
`@deepseek-ai/dsh-terminal` + `@deepseek-ai/dsh-terminal-bash` PTY/shell/IO. The
B4 adapter owns only the durable `TerminalAttachment` record (same
`byq-terminal-attachment-store.v1` schema and authorization gate as B3) plus the
orphan reconcile; each client action is a separate OS process.

| scenario | result | real observation |
| --- | --- | --- |
| `dsh-runtime-restart-terminal-lost` | **PASS** | generation A echoes a unique marker through a real PTY; the **DSH runtime OS process is SIGKILLed** and a **genuinely fresh OS process** starts as runtime generation B (different runtime pid, generation `1→2`, old PTY pid dead, 0 sessions in the new runtime). A fresh adapter generation B reloads the same durable attachment, validates owner/generation/epoch, sees the native state gone and returns `lost` (`NATIVE_SESSION_UNAVAILABLE`) with no returned session/pid and no identity claim; a retry returns the same loss. |
| `surviving-pty-without-attachment-lost` | **PASS** | the real PTY **survives** while the BYQ durable attachment record is lost. A fresh adapter generation B reconciles native sessions against attachments, detects the surviving PTY as an **orphan**, classifies it `lost`, rejects an orphan-reuse attempt (`ORPHAN_NOT_REUSABLE`) and the stale attachment id (`UNKNOWN_ATTACHMENT`), and never creates an attachment for the orphan. Cleanup kills the orphan PTY (0 orphans). |

### BYQ-owned vs DSH-owned (ADR-0083 boundary)

| owned by BYQ (bounded) | owned by DSH |
| --- | --- |
| BYQ-minted `byq-att-…` attachment id (never a DSH session id or pid) | PTY process |
| owner principal + authorization | shell |
| runtime generation, executor epoch | terminal I/O |
| attachment state (`attached`/`reattached`/`lost`/`detached`) | native session lifecycle |
| orphan reconcile + audit linkage + durable store | — |

### Terminal lifetime independence

The durable BYQ `conversation` and `durable_job` identities (stored alongside the
attachment, minted by BYQ) remain **`active`** and unchanged after both the DSH
runtime restart and the orphan loss. Terminal lifetime never defines conversation
or durable-job lifetime; a terminal-driven conversation/job termination fails the
verdict.

## Reuse and the not-implemented / label-only distinction

The scope probe (`scope-probe.v1.json`) records
`reuses_b3_native_runtime_role=true`, `reuses_b3_attachment_store_schema=true` and
`second_generic_harness=false`. The fail-able observer
(`scripts/d15/terminal/dsh_runtime_restart_observer.py`) derives every assertion
from raw pids, generations, counters and identifiers; it never trusts a
self-declared `identityStable`/`assertions_ok`. A correct honest `lost` only
passes when:

- generation A really produced a live native PTY with a marker and a durable
  BYQ-minted attachment;
- the DSH runtime OS process was **genuinely** restarted (different runtime pid,
  advanced generation, old PTY pid dead);
- the orphan scenario proves a **genuinely surviving PTY** with no attachment,
  classified `lost` and never reused.

`--selfcheck` produces `negative-controls.v1.json`: 48 controls, all non-zero for
the fixed gate, 45 defect-targeting (the reconstructed pre-fix result-trusting
gate passed while the fixed gate failed). Controls include `runtime-not-restarted`,
`runtime-generation-not-advanced`, `lost-without-native-failure`, `fake-reattach-accepted`,
`label-only-pass-positive`, `not-implemented-label-pass`,
`conversation-terminated-on-terminal-loss`, `orphan-reused`,
`orphan-adopted-as-attachment`, `orphan-cleanup-left-alive`, `permission-bypass`,
`stale-not-fenced` and `orphan-dimensions-hide-surviving-pty`.

## Additional acceptance (real)

| check | result | real observation |
| --- | --- | --- |
| owner principal | **PASS** | `UNAUTHORIZED_PRINCIPAL` in both worlds |
| runtime generation | **PASS** | runtime OS pid changed, generation `1→2`, old PTY dead, new runtime has 0 sessions |
| executor-epoch fencing | **PASS** | `STALE_GENERATION` / `STALE_EPOCH` in both worlds |
| idempotent retry | **PASS** | repeated reattach returns the same loss; orphan reconcile idempotent; close twice is a no-op |
| wrong terminal / foreign session | **PASS** | unknown attachment `UNKNOWN_ATTACHMENT`; foreign owner send/read `FOREIGN_SESSION`; unknown terminal `NO_SESSION` |
| cleanup no orphans | **PASS** | runtime shutdown 0 orphans; orphan cleanup kills the surviving PTY (0 sessions after) |
| terminal lifetime independence | **PASS** | conversation/durable-job `active` and unchanged after terminal loss |
| browser/frontend raw DSH schema | **PASS** | `scope-probe.v1.json`: frontend raw-schema refs `0`; runtime-adapter persistent-terminal routes `0` (only AgentRun `terminal-receipt`) |
| no R4 productization | **PASS** | production selector `dsh-0.1.2rc1` unchanged; no product surface added |

## Artifacts

| artifact | what it is |
| --- | --- |
| `native-observations.v1.json` | real per-scenario observations for both worlds |
| `verdict.v1.json` | fail-able observer verdict: `all_pass=true`, `format_valid=true`, exit 0 |
| `negative-controls.v1.json` | 48 fail-closed controls (45 defect-targeting) |
| `scope-probe.v1.json` | candidate-layer confinement, B3 reuse, product-surface absence, browser raw-schema check, selector unchanged |
| `provenance.v1.json` | artifact sha256, isolation and environment facts |
| `current-overlay.v1.json` | explicit distinction between the historical D15-5/D15-G committed snapshot and the B4 current overlay |

## Reproduce

```bash
cd scripts/d15/terminal
npm ci --no-audit --no-fund --legacy-peer-deps
bash run_dsh_runtime_restart_probe.sh ../../../docs/evidence/v090-step5-b4-terminal-dsh-runtime-restart
```

The native packages are installed only from the committed `package.json`/lock; the
harness touches no production stack and creates no release/tag.

## Isolation and non-claims

- **No DSH fork or patch** and no production change: selector `dsh-0.1.2rc1`,
  `compose.yml` and `deployment.json` are untouched; no deployment/tag/release.
- **No R4 productization**, no production wiring, no BYQ PTY runtime, no second
  generic harness/session store. The B3 native runtime role and the minimal
  `TerminalAttachment` store schema are reused.
- The provider is not called: `llm.class = not-applicable`.
- Historical D15-5 and D15-G evidence are **not rewritten**; D15-G stays `NO_GO`
  (not re-run). B1 stays a mandatory external blocker; B2 stays BLOCKED-external.
- `R3_RESUME = NO`; R3 remains frozen; **0.9 is not closed**.
- After this slice the G-split internal order is complete (B2/B3/B4); D15-G must
  not be re-run while B1 is BLOCKED.
