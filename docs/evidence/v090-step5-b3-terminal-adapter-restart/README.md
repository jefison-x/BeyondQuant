# 0.9 strict-order step-5 slice 3 — `terminal-adapter-restart` (`d15-5-candidate-attachment-layer`)

- Status: **PASS (candidate/qualification layer)** — the minimal BYQ
  `TerminalAttachment` lifecycle required by ADR-0083 is implemented and verified
  against the real native DSH 0.1.5-rc.1 persistent terminal.
- Date: 2026-09-21
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm
  `0.1.5-rc.1`
- ADR: [ADR-0083](../../architecture/adr/ADR-0083-terminal-attachment-boundary.md)
  (Accepted 2026-09-21; candidate-specific and reversible, **not** productionized)
- Owner node: `d15-5-candidate-attachment-layer` (pre-gate; never post-GO R4)
- G-split strict internal order: B2 (executed, BLOCKED-external) →
  **B3 `terminal-adapter-restart` (this slice)** → `terminal-dsh-runtime-restart`
  (**not started**)

This slice does not start `terminal-dsh-runtime-restart` (B4), D15-G re-run or
R3/R4/R5/R6. It adds **no** production wiring, no BYQ PTY runtime, no DSH fork or
patch, no second generic harness and no second session store.

## The one question

After a real generation A establishes a native persistent terminal plus a durable
BYQ attachment, can a **fresh BYQ adapter OS process** authorize and
generation-validate the **same** attachment, rebind the same terminal when the
native state is still reachable, and — when the adapter restart genuinely loses
the process-local native state — deterministically report `lost`/`interrupted`
instead of fabricating a reattach?

## Answer: yes — and the honest loss is distinguishable from "not implemented"

The probe (`scripts/d15/terminal/adapter_restart_harness.mjs`) runs inside the
real native DSH 0.1.5-rc.1 closure. One OS process hosts the native
`ctx.terminals` PTY service + `@deepseek-ai/dsh-terminal-bash` `shell` backend;
another OS process is the BYQ adapter that owns only the durable
`TerminalAttachment` record; each client action is a separate OS process.

| scenario | result | real observation |
| --- | --- | --- |
| `adapter-restart-native-survives` | **PASS** | a fresh adapter generation B reloads the durable attachment (same BYQ-minted id) and rebinds the SAME native session / PTY pid; the second marker is sent once, the send delta omits the first marker, and scrollback holds each marker once (no replay, no loss) |
| `adapter-restart-native-lost` | **PASS** | the committed topology takes the native runtime down with the adapter restart; a fresh adapter reloads the same durable attachment, validates owner/generation/epoch, sees the old pid dead and the native session gone and returns `lost` with `NATIVE_SESSION_UNAVAILABLE`, rejecting a fake reattach |

### BYQ-owned vs DSH-owned (ADR-0083 boundary)

| owned by BYQ (bounded) | owned by DSH |
| --- | --- |
| BYQ-minted `byq-att-…` attachment id (never a DSH session id or pid) | PTY process |
| owner principal + authorization | shell |
| runtime generation, executor epoch | terminal I/O |
| attachment state (`attached`/`reattached`/`lost`/`detached`) | native session lifecycle |
| audit linkage + durable store | — |

The adapter calls only the native owner-scoped `ctx.terminals` seam through the
runtime; it owns no PTY/shell/IO and never persists or fabricates the native PTY.
The slice is confined to `scripts/d15/terminal/` (see `scope-probe.v1.json`).

## The not-implemented / label-only distinction (fail-able observer)

`scripts/d15/terminal/adapter_restart_observer.py` derives every assertion from raw
identifiers/counters; it never trusts a self-declared `identityStable`/`assertions_ok`.
A correct honest `lost`/`interrupted` only passes when:

- the durable BYQ attachment is real (BYQ-minted, persisted, reloaded with the same
  id by a **fresh** adapter OS process), and
- the **positive** branch really rebinds that durable attachment to the SAME native
  session/PTY with no replay and no loss (so a not-implemented `lost` cannot pass), and
- the lost branch proves a real native failure (old pid dead, native session absent,
  a specific rebind error) and rejects a fake reattach.

`--selfcheck` produces `negative-controls.v1.json`: 32 controls, all non-zero for
the fixed gate, 29 defect-targeting (the reconstructed pre-fix result-trusting gate
passed while the fixed gate failed). Controls include `label-only-pass-positive`,
`not-implemented-label-pass`, `not-implemented-positive-missing`,
`lost-without-native-failure`, `lost-status-not-lost`, `fake-reattach-accepted` and
`durable-not-loaded`.

## Additional acceptance (real)

| check | result | real observation |
| --- | --- | --- |
| foreign principal | **PASS** | `UNAUTHORIZED_PRINCIPAL` |
| foreign owner send/read | **PASS** | `FOREIGN_SESSION` |
| stale generation / epoch | **PASS** | `STALE_GENERATION` / `STALE_EPOCH`, current token still rebinds |
| wrong terminal | **PASS** | unknown attachment `UNKNOWN_ATTACHMENT`; unknown session `NO_SESSION` |
| idempotent transitions | **PASS** | repeated reattach returns the same identity with one native session; close twice is a no-op |
| cleanup no orphans | **PASS** | close ends the PTY; runtime shutdown leaves 0 orphans |
| browser/frontend raw DSH schema | **PASS** | `scope-probe.v1.json`: frontend raw-schema refs `0`; runtime-adapter persistent-terminal routes `0` (only AgentRun `terminal-receipt`) |
| no R4 productization | **PASS** | production selector `dsh-0.1.2rc1` unchanged; no product surface added |

## Artifacts

| artifact | what it is |
| --- | --- |
| `native-observations.v1.json` | real per-scenario observations for both branches |
| `verdict.v1.json` | fail-able observer verdict: `all_pass=true`, `format_valid=true`, exit 0 |
| `negative-controls.v1.json` | 32 fail-closed controls (29 defect-targeting) |
| `scope-probe.v1.json` | candidate-layer confinement, product-surface absence, browser raw-schema check, selector unchanged |
| `provenance.v1.json` | artifact sha256, isolation and environment facts |

## Reproduce

```bash
cd scripts/d15/terminal
npm ci --no-audit --no-fund --legacy-peer-deps
bash run_adapter_restart_probe.sh ../../../docs/evidence/v090-step5-b3-terminal-adapter-restart
```

The native packages are installed only from the committed `package.json`/lock; the
harness touches no production stack and creates no release/tag.

## Isolation and non-claims

- **No DSH fork or patch** and no production change: selector `dsh-0.1.2rc1`,
  `compose.yml` and `deployment.json` are untouched; no deployment/tag/release.
- **No R4 productization**, no production wiring, no BYQ PTY runtime, no second
  generic harness/session store.
- The provider is not called: `llm.class = not-applicable`; this is
  terminal-attachment-continuity evidence, not model-quality evidence.
- Historical D15-5 and D15-G evidence are **not rewritten**; D15-G stays `NO_GO`
  (`terminal-adapter-restart` remains a named blocker until a D15-G re-run, which is
  not authorized here). B1 stays a mandatory external blocker; B2 stays BLOCKED-external.
- `R3_RESUME = NO`; R3 remains frozen; **0.9 is not closed**.
- Next in the G-split strict internal order: `terminal-dsh-runtime-restart` (B4),
  **not started here**.
