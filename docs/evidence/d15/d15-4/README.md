# D15-4 native subagent / fork continuity qualification

- Status: **PARTIAL / BLOCKED — not a full D15-4 pass, no D15-G pass, no full-D15
  claim.** Six required scenarios PASS in a real native runtime; two required
  scenarios are **BLOCKED**; host reboot is **NOT_RUN**.
- Date: 2026-09-20
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm
  `0.1.5-rc.1`
- Build revision: `post-u8.165` (rebuild identity only; no selector/deployment change)
- Provider: scripted keyless (non-real-LLM)
- Scope: subagent/fork continuity only. D15-5, D15-G and R3 are **not** in this
  batch. `R3_RESUME = NO`.

## Read this first

| artifact | what it is |
| --- | --- |
| `native-observations.v1.json` | raw real observations of the native harness |
| `verdict.v1.json` | fail-able observer verdict: `all_pass=false`, six PASS + two required BLOCKED |
| `negative-controls.v1.json` | 23 fail-closed controls (22 defect-targeting: pre-fix gate passes, fixed gate fails) |
| `reachability.v1.json` | real inspection of the committed BYQ composition vs the candidate tool implementation |
| `scenarios/*.v1.json` | one file per scenario |

**No D15-4 completion is claimed.** The observer exits non-zero because two
required scenarios are BLOCKED; this is intentional and truthful.

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

## Per-item results (real observations)

| item | result | real observation |
| --- | --- | --- |
| parent/child identity | **PASS** | root `d15-4-parent` vs child `3f0b3112-78b5-4599-9b6d-b097527b8ca9`; `header.parentSession=d15-4-parent`, `origin=subagent`; `listChildren` shows `mode=continuable` |
| continuable descriptor | **PASS** | persisted `subagent/descriptor` `{version:3, mode:continuable, provider:spawn}` before the first turn |
| cold resume | **PASS** | a genuinely new OS process resumed the same child `3f0b3112-…-7b8ca9`, contiguous sequence, `newSettlements=1` |
| fork lineage | **PASS** | fork `e9b82dd6-ca37-47d5-b205-ed0ad84ca410`, `isSeeded=true`, `inheritedEventCount=11`, parent log unchanged |
| inheritance | **PASS** | descriptor `agentProvider/model=mock`, `agentReasoningEffort=max`, persona persisted; child reapplied `reasoningEffort=max` on cold resume |
| parent crash | **PASS** | SIGKILL of the owning process; parent identity survived; child `1d6bf3b9-…-ebab1d0e1bd4` retained and natively resumed; one settlement |
| child crash | **BLOCKED** | in-process children share the executor process; a child-only SIGKILL is not isolatable. Smallest option: out-of-process child provider or the D15-3R `dsh-process-interruption` compose pattern |
| byq adapter restart (container) | **BLOCKED** | BYQ composition does not reach `startContinuable`; no committed BYQ path cold-resumes a continuable child. Not to be confused with the process `parent-crash` above |
| host reboot | **NOT_RUN** | rebooting the maintainer host is not authorized and is **not** a container/adapter restart |

## Negatives (each must fail)

Runtime negatives (native seam, all rejected):

| negative | error |
| --- | --- |
| non-direct parent | `UNAUTHORIZED` — "belongs to another parent session" |
| stale parent | `UNAUTHORIZED` |
| unmaterialized cold resume | `NOT_RESUMABLE` |
| depth exceeds `maxDepth` | `SubagentDepthError` "depth 2 exceeds maxDepth 1" |
| child claims root identity | `DUPLICATE_CHILD` "subagent d15-4-parent already exists" |
| out-of-filter tool | `tools.restrict() names unknown global tool` |

Observer negatives (`negative-controls.v1.json`): 23 controls, all non-zero for
the fixed observer. **22 are defect-targeting**: the reconstructed pre-fix
result-only gate reported `all_pass=true` while the fixed adjudicator returned
false — including `required-blocked-fixture-pre-fix-passes` (required
`NOT_RUN`/`BLOCKED` did not gate PASS), `duplicate-settlement`,
`fork-inherited-off-by-one-zero`, `false-assertion-same-child-id`,
`reasoning-drift`, `negative-not-rejected`, `non-native-evidence-class`,
`llm-claims-real-quality` and `self-declared-coverage`.

## Isolation, cleanup, reproduce

The harness uses `mkdtemp` roots and removes them; `runtime_root_cleaned=true`.
No production stack, Community repository or selector was touched.

```bash
cd scripts/d15/subagent
npm ci --no-audit --no-fund --legacy-peer-deps
node native_subagent_harness.mjs run --out ../../../docs/evidence/d15/d15-4/native-observations.v1.json
node reachability_probe.mjs --out ../../../docs/evidence/d15/d15-4/reachability.v1.json
python3 observer.py --selfcheck --out ../../../docs/evidence/d15/d15-4/negative-controls.v1.json
python3 observer.py --observations ../../../docs/evidence/d15/d15-4/native-observations.v1.json \
    --out ../../../docs/evidence/d15/d15-4/verdict.v1.json   # exits 1: two required BLOCKED
```

## Explicit non-claims

- **No D15-4 pass. No D15-5 pass. No D15-G pass. No full-D15 claim.**
- `R3_RESUME = NO`; R3 remains frozen.
- Host reboot `NOT_RUN`; container/adapter restart is a distinct item.
- The provider is scripted/keyless: not real-LLM-quality evidence.
- Production default selector `dsh-0.1.2rc1`, `compose.yml` and `deployment.json`
  are unchanged; the candidate remains isolated.
