# D15-5 persistent-terminal (PTY) qualification

- Status: **PARTIAL / BLOCKED — not a full D15-5 pass, no D15-G pass, no full-D15
  claim.** Four client-side fault rows PASS (page refresh, browser disconnect,
  frontend restart, gateway restart). Two restart rows that require the DSH
  runtime process to survive are **BLOCKED**. Host reboot is **NOT_RUN**.
- Date: 2026-09-20
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm
  `0.1.5-rc.1`
- Provider: none (no model call; `llm.class = not-applicable`)
- Scope: persistent terminal only. D15-4 is independent; D15-G and R3 are **not**
  in this batch. `R3_RESUME = NO`.

## Read this first

| artifact | what it is |
| --- | --- |
| `native-terminal-observations.v1.json` | raw real observations of the native terminal harness + evidence-only BYQ attachment gate |
| `verdict.v1.json` | fail-able observer verdict: `all_pass=false`, `format_valid=true`, four required rows PASS, two required rows BLOCKED |
| `negative-controls.v1.json` | 24 fail-closed controls (23 defect-targeting: pre-fix gate passes, fixed gate fails) |
| `interface-probe.v1.json` | real inspection of the committed BYQ wiring vs the candidate native terminal closure |
| `scenarios/*.v1.json` | one file per fault row and per cross-check |

**No D15-5 completion is claimed.** The observer exits non-zero because two
required restart rows are BLOCKED; this is intentional and truthful.

## The four-way distinction (explicit)

The qualification never collapses these four different things:

| dimension | meaning | owner |
| --- | --- | --- |
| `pty_process` | the real external shell/PTY process exists (`/proc/<pid>` alive) | DSH |
| `attachment` | a BYQ-owned attachment record exists and is live | BYQ |
| `io_rebind` | a client OS process can re-bind I/O to the same terminal | BYQ gate + DSH |
| `terminal_identity` | attachment id / session id / pty pid are stable across a rebind | BYQ + DSH |

The `pty-attachment-separation` cross-check proves they are independent: a real
`bwrap` shell pid exists, the attachment is a registry-minted record distinct from
the pid, the PTY is reachable only through the attachment, dropping the
attachment leaves the PTY alive while rebind is rejected (`ATTACHMENT_DETACHED`),
and killing the session ends the PTY.

Ownership boundary (ADR-0081 §5): **BYQ owns `TerminalAttachment`
identity/state/authorization/reconnect; DSH owns PTY/shell/I/O.** No PTY runtime
is built. Terminal lifetime never defines conversation or durable-job lifetime.

## What is real vs scripted

Real, isolated native runtime: the candidate `@deepseek-ai/dsh-terminal`
owner-scoped `TerminalSessionService` + the `@deepseek-ai/dsh-terminal-bash`
`shell` backend (`bwrap` sandbox, `--die-with-parent`) are booted inside a real
**runtime OS process**. Every client action is a genuinely separate **client OS
process** over a Unix socket. No model is called (`not-applicable`).

The BYQ attachment gate in the runtime is **evidence-only**: it mints attachment
ids, holds state, authorizes reconnects and fences stale generation/epoch. It
owns no PTY/shell/I/O and is not wired into production. It is the model of the
BYQ-owned semantics; the framework-neutral contract lives in
`packages/contracts/terminal_attachment.py` and is unit-tested.

## Per-row results (real observations)

| fault row | result | pty_process | attachment | io_rebind | terminal_identity | note |
| --- | --- | --- | --- | --- | --- | --- |
| page refresh | **PASS** | present | present | ok | stable | fresh client process rebinds same attachment/PTY |
| browser disconnect | **PASS** | present | present | ok | stable | runtime untouched; later client rebinds |
| frontend restart | **PASS** | present | present | ok | stable | frontend restart is a client restart |
| gateway restart | **PASS** | present | present | ok | stable | new gateway/client OS process rebinds the attachment |
| adapter restart | **BLOCKED** | absent | absent | rejected | lost | adapter abort kills the DSH runtime; native sessions are process-local and no BYQ wiring rehydrates them |
| DSH runtime restart | **BLOCKED** | absent | absent | rejected | lost | a restarted DSH runtime is a new process; native sessions do not survive it |
| host reboot | **NOT_RUN** | unknown | unknown | unknown | unknown | rebooting the host is not authorized and is not a process/container restart |

The restart rows record real rejection evidence (`rebindError`), the old pid's
liveness and the new runtime's empty session list. They are **never** a fabricated
reattach.

## Unique-marker cross-process command test (real)

1. Client OS process **C1** opens the PTY and runs `echo D15_5_MARK_ONE_<random>`;
   the marker output line appears exactly once.
2. A different client OS process runs `echo D15_5_MARK_TWO_<random>`; its send
   delta contains the second marker exactly once and the **first marker zero
   times** (no replay), while retained scrollback contains each marker exactly
   once (no loss).
3. The session id, pid and attachment id are identical across all client OS
   processes (`identityStable = true`).

## Permissions, wrong terminal, fencing, cleanup (real)

| check | result | real observation |
| --- | --- | --- |
| permission boundary | **PASS** | foreign owner send/read rejected `FOREIGN_SESSION`; foreign principal rejected `UNAUTHORIZED_PRINCIPAL` |
| wrong terminal rejected | **PASS** | unknown session id rejected `NO_SESSION` and does not reach the real PTY |
| stale generation fenced | **PASS** | stale generation `STALE_GENERATION`, stale epoch `STALE_EPOCH`; current token still valid |
| cleanup no orphans | **PASS** | session kill ends the PTY; all recorded pids dead; runtime shutdown orphans `0` |

## Interface probes and the named BLOCKED (the known gap)

`interface-probe.v1.json` reads the committed BYQ composition/profile, the
runtime-adapter, the D15 compat boundary and the candidate closure:

| interface | status |
| --- | --- |
| native `@deepseek-ai/dsh-terminal` PTY service | REACHABLE_IN_CANDIDATE_CLOSURE |
| native `shell` backend (`dsh-terminal-bash`) | REACHABLE_IN_CANDIDATE_CLOSURE |
| persistent terminal tools | BUNDLED_NOT_COMPOSED_BY_BYQ |
| BYQ composition terminal service/backend/tool | NOT_COMPOSED (`tool-bash`/`tool-pwsh` still disabled) |
| BYQ persistent-terminal/PTY product surface | **ABSENT** (the only route, `terminal-receipt`, is AgentRun terminal-state evidence, not a PTY surface) |
| BYQ TerminalAttachment persistence | **ABSENT** |
| cross-process terminal reattach | **BLOCKED** |

Native sessions are documented **process-local** ("do not survive a harness
restart"), so `adapter-restart` and `dsh-runtime-restart` cannot be rebound
without a BYQ attachment layer. Exposing and persisting that layer is a real
architecture boundary change; it is recorded as the **Proposed, unimplemented**
[ADR-0083](../../../architecture/adr/ADR-0083-terminal-attachment-boundary.md)
and was **not** implemented. D15-5 therefore stays **PARTIAL/BLOCKED**.

## Negatives (each must fail)

Observer controls (`negative-controls.v1.json`): 24 controls, all non-zero for the
fixed observer. **23 are defect-targeting**: the reconstructed pre-fix
result-only gate reported `all_pass=true` while the fixed adjudicator returned
false — including `required-blocked-fixture-pre-fix-passes`,
`missing-required-row`, `required-blocked`, `required-not-run`,
`fabricated-reattach-session-drift`, `fabricated-reattach-pid-drift`,
`fabricated-reattach-attachment-drift`, `false-identity-claim`,
`fault-not-applied`, `missing-dimension`, `dimension-contradicts-reattach`,
`marker-replayed`, `marker-lost`, `permission-bypass`, `wrong-terminal-accepted`,
`stale-not-fenced`, `orphan-left`, `negative-not-rejected`,
`candidate-mismatch`, `non-native-evidence-class`, `llm-claims-real-quality`,
`pass-without-observation`, `self-declared-coverage`.

Runtime negatives (all rejected): foreign-owner send/read, unknown terminal,
foreign principal, stale generation, stale epoch.

## Isolation, cleanup, reproduce

The harness creates a `mkdtemp` root, runs one runtime OS process per generation
and separate client OS processes, and removes every temp root in a `finally`.
`native-terminal-observations.v1.json` records `cleanup.temp_root_removed=true`.
No production stack, Community repository or selector was touched.

```bash
cd scripts/d15/terminal
npm ci --no-audit --no-fund --legacy-peer-deps
node native_terminal_harness.mjs run --out ../../../docs/evidence/d15/d15-5/native-terminal-observations.v1.json
node interface_probe.mjs --out ../../../docs/evidence/d15/d15-5/interface-probe.v1.json
python3 observer.py --selfcheck --out ../../../docs/evidence/d15/d15-5/negative-controls.v1.json
python3 observer.py --observations ../../../docs/evidence/d15/d15-5/native-terminal-observations.v1.json \
    --out ../../../docs/evidence/d15/d15-5/verdict.v1.json   # exits 1: two required BLOCKED
```

## Explicit non-claims

- **No D15-5 pass. No D15-G pass. No full-D15 claim.**
- `R3_RESUME = NO`; R3 remains frozen.
- Host reboot `NOT_RUN`; container/process restart is a distinct item and both
  restart rows remain BLOCKED in this batch.
- No model was called: this is terminal-continuity evidence, not model-quality
  evidence.
- Production default selector `dsh-0.1.2rc1`, `compose.yml` and `deployment.json`
  are unchanged; the candidate remains isolated.
