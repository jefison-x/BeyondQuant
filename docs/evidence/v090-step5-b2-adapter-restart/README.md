# 0.9 strict-order step-5 slice 2 — `subagent-byq-adapter-restart` (`d15-4-candidate-composition-hookup`)

- Status: **BLOCKED — external dependency; no PASS, no D15-G pass, no R3 unfreeze.**
- Date: 2026-09-21
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm `0.1.5-rc.1`
- ADR: [ADR-0082](../../architecture/adr/ADR-0082-dsh-continuable-child-resume.md)
  (Accepted 2026-09-21; **Option 1 chosen, Option 2 rejected**; not implemented)
- Owner node: `d15-4-candidate-composition-hookup` (pre-gate; never post-GO R6)
- G-split strict internal order: this is the **first** internal item, after the
  external B1 `subagent-child-crash` was kept a mandatory external blocker.

This slice does not start `terminal-adapter-restart`, `terminal-dsh-runtime-restart`,
D15-G, or R3. It adds **no** BYQ child-resume bridge, no second generic harness, no
second session store and no production change.

## The one question

After a real generation A produces and persists a continuable child through the
committed BYQ candidate composition, can a **fresh BYQ runtime-adapter OS process
rebind the SAME child** and continue messages through a committed **BYQ composition
surface**, with exactly-once settlement?

## Answer: no — BLOCKED, external

The real isolated probe (`byq_adapter_restart_probe.py`, image
`byq-d15-4-continuable-candidate:local`, id
`sha256:21bc000e…43aa5eb`, `--network none`, keyless scripted provider) runs
generation A and generation B as **separate OS processes in separate containers**
sharing one durable session root:

| item | result | real observation |
| --- | --- | --- |
| generation A reaches real `startContinuable` | **PASS** | the real `byq_delegate_market_research` returns `{kind: continuable, subagentId}`; `subagent.started` links the child to the root (`childSessionId`/`parentSessionId`) |
| generation A persists the child linked to the delegation/goal | **PASS** | child id `1a91b95f-…` persists under the DSH session root; exactly one `started_child_count`; delegation call id captured |
| generation B is a fresh OS process / container | **PASS** | different container hostname and process namespace; same durable store |
| a committed BYQ composition surface can rebind the child | **BLOCKED** | `child_rebind_candidates = []`; the adapter exposes only the root `resume_session`; the committed composition **forbids** `send_message`/`list_agents`/`subagent` |
| same-child rebind / message delivery | **BLOCKED** | no surface; `resume_session(child_id)` fails closed (`KeyError: unknown BYQ session`) |
| exactly-once settlement on a resumed turn | **BLOCKED** | not reachable because no rebind surface exists |
| owner/generation/epoch fail-closed | **BLOCKED** | no rebind surface to fence |
| no extra child / no second session store | **PASS** | one child; a single DSH session store (`byq-lifecycle-evidence` + root store) |
| cleanup, no orphans | **PASS** | in-process child leaves no OS process |

The committed **BYQ composition surface** is the decisive boundary. The isolation
identity (`plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/byq-product.identity.json`)
declares `forbidden_tools` including `subagent`, `subagent_fork`, `send_message` and
`list_agents`, so the composition itself disables every native child messaging
operation. The runtime-adapter public surface is root-only (`resume_session`,
`submit_prompt`, `create_session`, …); the byte-identical 0.1.5 Python SDK exposes no
child/subagent/continuable operation. There is therefore **no committed BYQ
composition surface that reaches, messages or cold-resumes the persisted continuable
child** — even though the child session file persists with the same id.

Per ADR-0082, the honest resolution is the future upstream **Option 1** (an
out-of-process DSH provider implementing `SubagentProvider.prepareContinuable`); the
BYQ **Option 2** child-resume bridge is **rejected** and is not built here.

## Algorithmic capacity boundary / forbidden substitutions (never used)

An **adapter-restart rebind qualification was deliberately not performed**: there is
no BYQ composition surface to perform it, and these substitutions are forbidden:

- a BYQ child-resume bridge (ADR-0082 Option 2, **rejected**);
- an in-process child as a stand-in;
- presenting the root `resume_session` as a child rebind;
- a same-OS-process generation as a "fresh adapter";
- an owning-process restart as a child rebind;
- a mock or a label-only PASS.

`generation_b.status` is `BLOCKED` with the real fail-closed attempts recorded.

## Fail-able observer

`byq_adapter_restart_observer.py --selfcheck` →
`negative-controls.v1.json`: 27 controls, all non-zero for the fixed gate, 25 of them
defect-targeting (the reconstructed pre-fix result-trusting gate passed while the
fixed gate failed). Controls include `label-only-claim`, `no-rebind-candidates`,
`same-os-process`, `same-container-not-fresh`, `no-child-persistence`,
`child-not-linked-to-goal`, `extra-child-created`, `second-session-store`,
`orphan-left-behind`, `duplicate-settlement-on-resume`, `rebind-without-message-id`,
`fencing-not-fail-closed`, `stale-epoch-rebind-accepted`,
`composition-forbids-but-claims-surface`, `generation-a-no-startContinuable`,
`production-selector-changed`, `fork-or-patch-of-dsh`, `forbidden-substitution-bridge`
and `no-substitutions-recorded`.

The committed verdict (`verdict.v1.json`) has `format_valid=true`, `all_pass=false`,
`external_blocked=true`, exit 1, with the primary blocked reason
“no committed BYQ composition surface can rebind the persisted continuable child”.

## Artifacts

| artifact | what it is |
| --- | --- |
| `composition-restart.v1.json` | assembled observation: generation A + generation B + process identity + composition identity |
| `generation-a.v1.json` / `generation-b.v1.json` | the raw per-generation records |
| `probe-provenance.v1.json` | image id, probe/observer/contract/composition sha256, isolation and candidate provenance |
| `verdict.v1.json` | fail-able observer verdict over the observation: `all_pass=false`, `result=BLOCKED`, `external_blocked=true` |
| `external-blocked.v1.json` | machine-readable external BLOCKED record and the upstream DSH Option 1 requirement |
| `negative-controls.v1.json` | 27 focused fail-closed controls; 25 defect-targeting vs the reconstructed result-trusting gate |

## Reproduce

```bash
scripts/d15/subagent/run_byq_adapter_restart_probe.sh /tmp/b2-out
python3 scripts/d15/subagent/byq_adapter_restart_observer.py --selfcheck \
    --out docs/evidence/v090-step5-b2-adapter-restart/negative-controls.v1.json
python3 scripts/d15/subagent/byq_adapter_restart_observer.py \
    --observation /tmp/b2-out/composition-restart.v1.json \
    --out /tmp/b2-out/verdict.v1.json --blocked-out /tmp/b2-out/external-blocked.v1.json   # exits 1
```

The observer is gated and deterministic; the native probe requires Docker with the
isolated candidate image built from the committed candidate Dockerfile.

## Isolation and non-claims

- **No DSH fork or patch.** The probe runs the real committed candidate image and the
  real adapter/SDK/bundled runtime; it only mounts its own evidence-only probe.
- **No production change**: selector `dsh-0.1.2rc1`, `compose.yml` and
  `deployment.json` are untouched; `--network none`; no deployment/tag/release.
- **No ADR-0082 Option 2 implementation**, no second session store, no second generic
  harness, no child-resume bridge.
- The provider is scripted/keyless: not real-LLM-quality evidence.
- **No D15-G re-run, no R3/R4/R5/R6, no downstream step-5 slice.**
- `R3_RESUME = NO`; independent child-process capability remains BLOCKED.
- Next in the G-split strict internal order: `terminal-adapter-restart`
  (owner `d15-5-candidate-attachment-layer`). **Not started here.**
