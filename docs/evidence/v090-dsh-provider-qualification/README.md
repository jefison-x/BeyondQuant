# Independent DSH provider-qualification monitoring slice (`v090-dsh-provider-qualification`)

- Status: **monitoring/qualification only — rc.2 and alpha.2 both BLOCKED (external);
  no dependency upgrade, no production change, no D15/R3 status change.**
- Date: 2026-09-21
- Base: dynamic `origin/main` (`ff12669374a98ab71dad4c0c38a377f590926bef`)
- Worktree/branch: `codex/v090-dsh-provider-qualification`
- ADR: [ADR-0082](../../architecture/adr/ADR-0082-dsh-continuable-child-resume.md)
  (Accepted, modified: Option 1 chosen, Option 2 rejected; **not implemented**)
- Owner node: `d15-4-child-provider-remediation` (pre-gate)
- Contract: `scripts/d15/provider_qualification/contract.v1.json`
- Upstream requirements package: [upstream-requirement.md](upstream-requirement.md)

This slice is an **independent maintenance / dependency-qualification** task. It does
**not** advance a Product Phase, does not implement ADR-0082 Option 1 (upstream DSH
work), does not build a BYQ provider, child-resume bridge or second session store,
does not upgrade the dependency, does not switch the production selector/default, and
does not deploy/tag/release. B1 `subagent-child-crash`, B2
`subagent-byq-adapter-restart`, D15-G (`NO_GO`) and R3 (`R3_RESUME = NO`) are
**unchanged**.

## The one question

Would a future DSH release unblock the ADR-0082 Option 1 blocker — i.e. does the
release contain an actually registerable **out-of-process** provider implementing
`SubagentProvider.prepareContinuable`, whose child runs in an independent OS process
and can be rediscovered by a new generation via a durable mailbox + cross-process
lease protocol after the parent/provider process is SIGKILLed?

## Answer: no for both examined releases

A real native probe boots the real `@deepseek-ai/cordis` context + real
`SubagentRuntime` from an isolated installation of each examined release, registers
the real published providers, and calls the real
`SubagentRuntime.prepareContinuable` gate:

| release | channel | Python pairing | `spawn`/`fork` (in-process) | `acp`/`codex`/`claude-code`/`dsh-sdk` (out-of-process) | verdict |
| --- | --- | --- | --- | --- | --- |
| `0.1.5-rc.2` | `next` | none | gate PASS | `UNSUPPORTED_CAPABILITY` | **BLOCKED** |
| `0.1.6-alpha.2` | `alpha` | none | gate PASS | `UNSUPPORTED_CAPABILITY` | **BLOCKED** |

Both releases export the out-of-process **one-shot helpers**
(`out-of-process.d.ts`, `subprocessRunHandle`, `NO_START_CAPABILITIES`,
`settleRunResult`, `resolveChildCwd`, …). **Helper presence is not the capability**:
the helpers build a one-shot `SubagentRun`, not a continuable child. Both releases
also state the same deferred-work limitation:

> **Process-local residency** — the Activation inbox and ownership graph do not
> coordinate two harness processes; concurrent access to one persistence store needs
> a durable mailbox and cross-process lease protocol.

Neither release has a matching PyPI `deepseek-harness-sdk` /
`deepseek-harness-runtime-bin` (`0.1.5rc2` / `0.1.6a2` are unpublished), so neither is
a coherent pairing for a production adoption.

## Artifacts

| artifact | what it is |
| --- | --- |
| `provenance.rc2.v1.json` / `provenance.alpha2.v1.json` | npm dist-tags, publish time, root integrity, full resolved closure (594 / 650 packages) + canonical digest, subagent-provider closure detail, PyPI pairing check |
| `capability-inventory.rc2.v1.json` / `.alpha2.v1.json` | real native provider records + real gate results, declared limitations, out-of-process helper symbols, absent cross-process qualification |
| `verdict.rc2.v1.json` / `verdict.alpha2.v1.json` | fail-able per-version observer verdict: `format_valid=true`, `all_pass=false`, `result=BLOCKED`, `external_blocked=true`, `exit_code=1` |
| `external-blocked.rc2.v1.json` / `.alpha2.v1.json` | machine-readable external BLOCKED record and the upstream Option 1 requirement |
| `negative-controls.v1.json` | 33 observer controls, all non-zero for the fixed gate (31 defect-targeting vs the reconstructed result-only gate), including a fake provider, an in-process provider, a one-shot provider, no mailbox, double lease and duplicate settlement |
| `upstream-requirement.md` | minimal interface contract, lifecycle/security invariants, reproducible B1/B2 scenarios and upstream acceptance checklist |

## Explicit qualification switch

The native probe is **not** part of the daily CI profile. It runs only when the
explicit switch is set:

```bash
BYQ_DSH_PROVIDER_QUALIFICATION=1 \
  scripts/d15/provider_qualification/run_provider_qualification.sh 0.1.5-rc.2 rc2 next
```

Running it when the capability is absent **stably outputs BLOCKED with exit code 1**.
The switch keeps daily CI free of a permanent red result while still making the
absence of the capability fail-closed when a human/qualification run asks.

## Reproduce (offline observer / switch-gated native probe)

```bash
python3 scripts/d15/provider_qualification/provider_qualification_observer.py \
    --selfcheck --out /tmp/negatives.json
python3 scripts/d15/provider_qualification/provider_qualification_observer.py \
    --inventory docs/evidence/v090-dsh-provider-qualification/capability-inventory.rc2.v1.json \
    --out /tmp/verdict.json --blocked-out /tmp/blocked.json    # exits 1: BLOCKED
```

## Isolation and non-claims

- No DSH fork/patch; no upstream issue or PR is filed by this repository slice.
- No BYQ provider / child-resume bridge / second session store / generic harness.
- No production selector/default upgrade; `dsh-0.1.2rc1` remains the default.
- No dependency upgrade, deployment, tag or release.
- No D15-G re-run, no R3 unfreeze (`R3_RESUME = NO`), no Phase 100 / `#338` work.
- The probe is keyless and makes no LLM call; it is capability evidence, not LLM
  quality evidence.
