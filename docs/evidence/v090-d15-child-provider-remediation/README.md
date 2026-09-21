# 0.9 strict-order step-5 slice 1 — `subagent-child-crash` (`d15-4-child-provider-remediation`)

- Status: **BLOCKED — external dependency; no PASS, no D15-G pass, no R3 unfreeze.**
- Date: 2026-09-21
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm `0.1.5-rc.1`
- ADR: [ADR-0082](../../architecture/adr/ADR-0082-dsh-continuable-child-resume.md)
  (Accepted 2026-09-21; Option 1 chosen, Option 2 rejected; **not implemented**)
- Owner node: `d15-4-child-provider-remediation` (pre-gate; never post-GO R6)

This is the FIRST and ONLY slice of 0.9 strict-order step 5. It does not start
`subagent-byq-adapter-restart`, the terminal slices, D15-G, or R3.

## The one question

Does the actual DSH `0.1.5-rc.1` candidate contain an **out-of-process continuable
provider** that (a) implements `SubagentProvider.prepareContinuable`, (b) can have
its child **independently killed/restarted**, and (c) has a **native resume
surface**?

## Answer: no

The real native capability gate answers it. `scripts/d15/subagent/child_provider_discovery.mjs`
boots the real candidate cordis context + real `SubagentRuntime`, registers the
real candidate providers, and calls the real `SubagentRuntime.prepareContinuable` gate
for each:

| provider | package | boundary | `prepareContinuable` | native gate result |
| --- | --- | --- | --- | --- |
| spawn | `@deepseek-ai/dsh-subagent-spawn-in-process` | in-process | present | accepted (`{}`) |
| fork | `@deepseek-ai/dsh-subagent-fork-in-process` | in-process | present | accepted (`{}`) |
| acp | `@deepseek-ai/dsh-subagent-acp` | out-of-process | **absent** | `UNSUPPORTED_CAPABILITY` |
| codex | `@deepseek-ai/dsh-subagent-codex` | out-of-process | **absent** | `UNSUPPORTED_CAPABILITY` |
| claude-code | `@deepseek-ai/dsh-subagent-claude-code` | out-of-process | **absent** | `UNSUPPORTED_CAPABILITY` |
| dsh-sdk (not bundled) | `@deepseek-ai/dsh-subagent-dsh-sdk` | out-of-process | **absent** | `UNSUPPORTED_CAPABILITY` |

The **only** continuable providers are in-process (`spawn`, `fork`), so a
continuable child shares the executor OS process and cannot be independently
SIGKILLed while the parent stays alive. No out-of-process continuable provider
exists → `subagent-child-crash` remains **BLOCKED** and is an **external
dependency** on future upstream DSH work (ADR-0082 Option 1).

The source-level scan of the candidate archive agrees: only
`subagent-spawn-in-process` and `subagent-fork-in-process` contain
`prepareContinuable`; the out-of-process providers do not.

## Algorithmic capacity boundary

An **independent child-crash qualification was deliberately not performed**: there
is no out-of-process continuable child to SIGKILL, and the substitutions are
forbidden. Recorded as `child_crash_qualification: null` with a reason.

Forbidden substitutions (never used):

- a BYQ child-resume bridge (ADR-0082 Option 2, **rejected**);
- a same-process in-process provider as a stand-in;
- an owning-process SIGKILL as a "child crash";
- a label-only PASS without a real out-of-process provider.

## Artifacts

| artifact | what it is |
| --- | --- |
| `capability-discovery.v1.json` | real read-only runtime discovery + candidate archive provenance + source scan |
| `verdict.v1.json` | fail-able observer verdict over the discovery: `all_pass=false`, `result=BLOCKED`, `external_blocked=true` |
| `external-blocked.v1.json` | machine-readable external BLOCKED record and the maintainer gate-order decision required |
| `negative-controls.v1.json` | 21 focused fail-closed controls; 19 defect-targeting vs the reconstructed result-only gate |

## Maintainer gate-order decision required

A strict serial step-5 order cannot be both honest and executable while B1 is an
external blocker. The maintainer must choose one of the gate-order options
recorded in
[DSH-015RC1-CLOSEOUT-SLICES.md](../v090-closeout/DSH-015RC1-CLOSEOUT-SLICES.md#gate-order-options):

`G-keep` · `G-split` · `G-reorder` · `G-reclassify`

Until then the blocker stays BLOCKED, `R3_RESUME = NO`, and D15/R3 stay frozen.

## Reproduce

```bash
cd scripts/d15/subagent
npm ci --no-audit --no-fund --legacy-peer-deps
node child_provider_discovery.mjs run --out ../../../docs/evidence/v090-d15-child-provider-remediation/capability-discovery.v1.json
python3 child_provider_remediation_observer.py --selfcheck \
    --out ../../../docs/evidence/v090-d15-child-provider-remediation/negative-controls.v1.json
python3 child_provider_remediation_observer.py \
    --discovery ../../../docs/evidence/v090-d15-child-provider-remediation/capability-discovery.v1.json \
    --out ../../../docs/evidence/v090-d15-child-provider-remediation/verdict.v1.json \
    --blocked-out ../../../docs/evidence/v090-d15-child-provider-remediation/external-blocked.v1.json   # exits 1: BLOCKED
```

To additionally verify candidate-archive provenance and the upstream source scan,
pass `--source-archive <DeepSeek-Harness-183f08e9c6dde7e36cd2318eaee70b0da08fb35e.tar.gz>`.

## Isolation and non-claims

- **No DSH fork or patch.** The probe registers real upstream packages and reads
  the real native gate.
- **No production change**: selector `dsh-0.1.2rc1`, `compose.yml`,
  `deployment.json` untouched; no deploy/tag/release.
- **No D15-G re-run, no R3/R4/R5/R6, no downstream step-5 slice.**
- `R3_RESUME = NO`; independent child-process capability remains BLOCKED.
