# D15-4 native subagent / fork continuity qualification

- Status: **PARTIAL / BLOCKED — not a full D15-4 pass, no D15-G pass, no full-D15
  claim.** Seven scenarios PASS (six required + one supporting child-run fault);
  two required scenarios are **BLOCKED**; host reboot is **NOT_RUN**.
- Date: 2026-09-20 (review-fix revision v2)
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm
  `0.1.5-rc.1`
- Build revision: `post-u8.166` (rebuild identity only; no selector/deployment change)
- Provider: scripted keyless (non-real-LLM)
- Scope: subagent/fork continuity only. D15-5, D15-G and R3 are **not** in this
  batch. `R3_RESUME = NO`.

## Read this first

| artifact | what it is |
| --- | --- |
| `native-observations.v2.json` | raw real observations of the native harness (current) |
| `verdict.v2.json` | fail-able observer verdict: `all_pass=false`, six required PASS + one supporting PASS + two required BLOCKED |
| `negative-controls.v2.json` | 28 fail-closed controls (27 defect-targeting: pre-fix gate passes, fixed gate fails) |
| `reachability.v1.json` | real inspection of the committed BYQ composition vs the candidate tool implementation |
| `routing.v1.json` | real `ctx.tools.execute` routing trial (foreground vs continuable vs out-of-process) and the wiring/process-boundary impact |
| `scenarios/*.v2.json` | one file per scenario |
| `*.v1.json`, `scenarios/*.v1.json` | the original reviewed evidence, preserved unchanged (not overwritten) |

**No D15-4 completion is claimed.** The observer exits non-zero because two
required scenarios are BLOCKED; this is intentional and truthful.

### Review-fix revision v2 (2026-09-20)

1. **child-crash / BYQ adapter-restart are still required and never removed.**
   Both stay in `required_scenarios` and are emitted as named **BLOCKED** with
   concrete reasons. A new *supporting* (optional, non-gating) scenario
   `child-run-fault` records a real independent child-run fault (the child's
   model stream fails while the parent process stays alive): the settlement is
   truthful ("failed before it finished"), the child id is retained and the child
   is natively resumable in a later OS process. The owning-process SIGKILL is
   recorded only as native executor evidence (`parent-crash`) and is **not** used
   as the child fault or the BYQ adapter recovery.
2. **fork-lineage is exact.** `inheritedEventCount` must equal the parent's
   balanced completed-turn prefix cut (`last turn/end seq + 1`, observed cut
   `10 → 11`); the **full parent event-log hash and length** are equal
   before/after; the child log is sequence-contiguous. New controls
   `fork-inherited-off-by-one`, `fork-inherited-zero`, `fork-parent-payload-drift`,
   `fork-parent-length-mismatch`, `fork-child-sequence-gap` all fail the fixed
   gate while the pre-fix result-only gate passes.
3. **Real temp cleanup.** Every temp root (main roots and each negative root) is
   removed in a `finally`, including worker exception/timeout paths, and the
   `cleanup` / `root_cleaned` evidence records removal. The unsupported claim
   that a native rejection proves a nonexistent pre-fix gate is removed; the only
   pre-fix comparison is the observer's real reconstructed legacy algorithm.

## What is real vs scripted

Real, isolated native runtime: the candidate `@deepseek-ai/dsh-agent-loop` +
`@deepseek-ai/dsh-session-persistence-jsonl` + `@deepseek-ai/dsh-subagent` +
`dsh-subagent-spawn-in-process` + `dsh-subagent-fork-in-process` are booted with
a real JSONL session store and **one OS process per generation**. The harness
drives the real native seam (`startContinuable`, `Activation`, `authorizeLineage`,
`listChildren`, `sendMessage` cold resume, fork prefix). Scripted and explicitly
**not** real-LLM-quality: a keyless in-process adapter (`llm.real_llm_quality=false`).

It is evidence-only: no BYQ subagent persistence layer, no second generic agent
harness, no R3 behaviour. The production composition, selector and deployment are
untouched.

## Reachability (the known gap, probed for real)

`reachability.v1.json` reads the committed sources:

- `plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml` composes
  `@deepseek-ai/dsh-subagent` + `dsh-subagent-spawn-in-process` and **5**
  `byq_delegate_*` tools, **all with `enableRunInBackground: false`**.
- The installed candidate `@deepseek-ai/dsh-tool-subagent@0.1.5-rc.1` calls
  `ctx.subagents.startContinuable()` **only** on the background+continuable
  branch; it calls `subagents.start()` on the foreground path.
- `services/runtime-adapter/app/compat/dsh_015.py` still inherits the 0.1.2
  observation contract.

Therefore:

| interface | status |
| --- | --- |
| `byq_delegate_*` foreground spawn | REACHABLE_FROM_BYQ_COMPOSITION |
| `startContinuable` / Activation registry | **NOT_REACHED_FROM_BYQ** (background disabled) |
| native continuable seam (evidence-only harness) | REACHABLE_IN_EVIDENCE_ONLY_NATIVE_HARNESS |
| fork lineage provider | REACHABLE_IN_NATIVE_HARNESS (profile patch composes it) |
| BYQ child-session projection | NOT_REACHED_FROM_BYQ |
| BYQ adapter container-restart child resume | BLOCKED (no compose-driven delegate in this batch) |

The smallest concrete option for the BYQ items is an isolated D15 compose stack
plus a tool-aware scripted provider, without changing the production composition
or adding BYQ subagent persistence. It was **not** built here.

## Native interface + wiring impact (real routing trial, `routing.v1.json`)

`routing_probe.mjs` boots the real candidate `@deepseek-ai/dsh-subagent` +
`@deepseek-ai/dsh-subagent-spawn-in-process` + `@deepseek-ai/dsh-tool-subagent`
and executes the delegation tool through `ctx.tools.execute` while counting
`start` / `startContinuable`:

| trial | tool config | result |
| --- | --- | --- |
| byq-foreground | `enableRunInBackground:false` (committed BYQ) | foreground, `start=1`, `startContinuable=0` |
| continuable-in-process | `enableRunInBackground:true` + `backgroundMode:continuable`, provider `spawn` | `{kind:continuable}`, `startContinuable=1` |
| continuable-out-of-process | same, provider without `prepareContinuable` (models dsh-sdk/acp/codex) | apply rejected: `provider "dsh-sdk-like" does not support \`backgroundMode: continuable\`` |

Available native interfaces:

- `SubagentRuntime.startContinuable` — `@deepseek-ai/dsh-subagent` (`src/index.ts:228`, `continuation.ts:102`); durable in-process continuable child.
- `SubagentProvider.prepareContinuable` — capability gate (`src/types.ts:389`); implemented **only** by `subagent-spawn-in-process` (`src/index.ts:61`) and `subagent-fork-in-process` (`src/index.ts:84`).
- `tool-subagent` routing — `resolveDelegationRun` (`src/index.ts:287-305`), gates (`:321-347`), `startContinuable` (`:525-536`).
- Out-of-process one-shot providers — `subagent/src/out-of-process.ts` (`NO_START_CAPABILITIES`); bundled `dsh-subagent-acp/-codex/-claude-code`; none implements `prepareContinuable`. `@deepseek-ai/dsh-subagent-dsh-sdk` is published at rc.1 but **not in the candidate bundled runtime list** and also has no `prepareContinuable`.

Required wiring for BYQ to reach `startContinuable`: set `backgroundMode: continuable`
and stop disabling background (`enableRunInBackground: true`) on each
`byq_delegate_*`, keeping `provider: spawn`.

- **Blast radius**: composition (5 delegate tools + profile patch); the delegate
  tool result shape changes from the foreground `SubagentResult` to
  `{kind: continuable, subagentId}`, so the Product Agent must handle a durable
  child id, later delivery and settlement; the runtime-adapter child-lease path
  (`services/runtime-adapter/app/runtime.py`) models foreground delegation; the
  compat boundary (`dsh_015.py`) still inherits 0.1.2.
- **Reversible**: the composition keys are revertible, but the result-shape and
  Product handling change is **not transparent** to current callers — it is a
  product-semantics change, not a no-op.
- **Candidate-specific**: yes; it can be applied to the isolated candidate
  profile/composition without changing `config/dsh/deployment.json`, `compose.yml`
  or the production selector `dsh-0.1.2rc1`.
- **Process boundary**: the only continuable providers in the candidate runtime
  are in-process (spawn/fork). No out-of-process provider implements
  `prepareContinuable`, so a continuable child always shares the executor process.

**Scope decision.** The BYQ→`startContinuable` hookup is a product-semantics
change (durable background child contract) that **exceeds this PR's qualification
scope**, and it still cannot satisfy `child-crash`/BYQ adapter restart because
native 0.1.5rc1 has no independent-process continuable provider. #332 therefore
stays reviewable partial evidence; the minimal candidate-compatible hookup is
planned for an independent worktree/feature PR. D15-4 stays **BLOCKED**.

## Per-item results (real observations, v2)

| item | result | real observation |
| --- | --- | --- |
| parent/child identity | **PASS** | root `d15-4-parent` vs child `2ab32944-4162-47d4-bd81-85dbd2ed239b`; `header.parentSession=d15-4-parent`, `origin=subagent`; `listChildren` shows `mode=continuable` |
| continuable descriptor | **PASS** | persisted `subagent/descriptor` `{version:3, mode:continuable, provider:spawn}` before the first turn |
| cold resume | **PASS** | a genuinely new OS process resumed the same child, contiguous sequence, `newSettlements=1` |
| fork lineage | **PASS** | fork `76c9126b-5c1f-40be-8a60-ebf1662c4869`, `isSeeded=true`, `inheritedEventCount=11 == lastTurnEndSeq(10)+1`, parent log hash+length identical, child sequence contiguous |
| inheritance | **PASS** | descriptor `agentProvider/model=mock`, `agentReasoningEffort=max`, persona persisted; child reapplied `reasoningEffort=max` on cold resume |
| parent crash | **PASS** | SIGKILL of the owning process; parent identity survived; child `31932c7d-8266-43d8-bd10-e7a238bc5a99` retained and natively resumed; one settlement |
| child-run-fault (supporting) | **PASS** | independent child stream failure `7cb6b1ea-de33-48f2-b10b-3f4458821875`; settlement "failed before it finished"; child resumable |
| child crash | **BLOCKED** | in-process children cannot be independently SIGKILLed while the parent lives; the owning-process SIGKILL is not used here. Smallest option: out-of-process child provider or the D15-3R `dsh-process-interruption` compose pattern |
| byq adapter restart (container) | **BLOCKED** | BYQ composition does not reach `startContinuable`; no committed BYQ path cold-resumes a continuable child. Not to be confused with the process `parent-crash` above |
| host reboot | **NOT_RUN** | rebooting the maintainer host is not authorized and is **not** a container/adapter restart |

## Negatives (each must fail)

Runtime negatives (native seam, all rejected):

| negative | error | root cleaned |
| --- | --- | --- |
| non-direct parent | `UNAUTHORIZED` — "belongs to another parent session" | yes |
| stale parent | `UNAUTHORIZED` | yes |
| unmaterialized cold resume | `NOT_RESUMABLE` | yes |
| depth exceeds `maxDepth` | `SubagentDepthError` "depth 2 exceeds maxDepth 1" | yes |
| child claims root identity | `DUPLICATE_CHILD` "subagent d15-4-parent already exists" | yes |
| out-of-filter tool | `tools.restrict()` unknown global tool | yes |

Observer negatives (`negative-controls.v2.json`): 28 controls, all non-zero for
the fixed observer. **27 are defect-targeting**: the reconstructed pre-fix
result-only gate reported `all_pass=true` while the fixed adjudicator returned
false — including `required-blocked-fixture-pre-fix-passes` (required
`NOT_RUN`/`BLOCKED` did not gate PASS), `duplicate-settlement`,
`fork-inherited-off-by-one`, `fork-inherited-zero`, `fork-parent-payload-drift`,
`fork-parent-length-mismatch`, `fork-child-sequence-gap`,
`child-run-fault-fabricated-completion`, `child-run-fault-not-resumable`,
`false-assertion-same-child-id`, `reasoning-drift`, `negative-not-rejected`,
`non-native-evidence-class`, `llm-claims-real-quality` and `self-declared-coverage`.

## Isolation, cleanup, reproduce

The harness creates temp roots via `mkdtemp` and removes **every** root in a
`finally` (main roots and each negative root), including worker
exception/timeout paths. `native-observations.v2.json` records
`cleanup: [...]` with `removed: true` for all 11 roots, `runtime_root_cleaned=true`
and `root_cleaned=true` on every negative. No production stack, Community
repository or selector was touched.

```bash
cd scripts/d15/subagent
npm ci --no-audit --no-fund --legacy-peer-deps
node native_subagent_harness.mjs run --out ../../../docs/evidence/d15/d15-4/native-observations.v2.json
node reachability_probe.mjs --out ../../../docs/evidence/d15/d15-4/reachability.v1.json
node routing_probe.mjs --out ../../../docs/evidence/d15/d15-4/routing.v1.json
python3 observer.py --selfcheck --out ../../../docs/evidence/d15/d15-4/negative-controls.v2.json
python3 observer.py --observations ../../../docs/evidence/d15/d15-4/native-observations.v2.json \
    --out ../../../docs/evidence/d15/d15-4/verdict.v2.json   # exits 1: two required BLOCKED
```

## Explicit non-claims

- **No D15-4 pass. No D15-5 pass. No D15-G pass. No full-D15 claim.**
- `R3_RESUME = NO`; R3 remains frozen.
- Host reboot `NOT_RUN`; container/adapter restart is a distinct item and both
  remain BLOCKED/NOT_RUN in this batch.
- The provider is scripted/keyless: not real-LLM-quality evidence.
- Production default selector `dsh-0.1.2rc1`, `compose.yml` and `deployment.json`
  are unchanged; the candidate remains isolated.
