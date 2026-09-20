# D15-4 candidate-specific BYQ → native `startContinuable` wiring

- Status: **PARTIAL — the candidate-specific wiring, product-semantics and
  new-OS-process cold resume are real and PASS; the BYQ adapter-restart
  reachability of a delegated child is BLOCKED, so D15-4 remains BLOCKED.**
- Date: 2026-09-20
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm `0.1.5-rc.1`
- Build revision: `post-u8.169` (rebuild identity only; no selector/deployment change)
- Provider: scripted keyless (non-real-LLM)
- Scope: candidate-specific continuable wiring only. D15-5, D15-G and R3 are
  **not** in this batch. `R3_RESUME = NO`. Independent child-process capability
  stays **BLOCKED**; no provider and no R3 behaviour were added.

## What was implemented (candidate-specific, reversible)

The committed `byq_delegate_*` tools stay on the production foreground path.
A **separate** candidate profile is generated from the exact same source
composition and template:

| artifact | production (unchanged) | candidate-specific |
| --- | --- | --- |
| profile | `plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml` | `plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/byq-product.patch.yml` |
| delegate routing | `provider: spawn`, `backgroundMode: one-shot`, `enableRunInBackground: false` | `provider: spawn`, `backgroundMode: continuable`, `enableRunInBackground: true` |
| image | `Dockerfile.post-u8-candidate` (production) | `Dockerfile.dsh-0.1.5rc1-continuable-candidate` |

The only generated differences are the five delegate `enableRunInBackground` /
`backgroundMode` keys; the delegate `toolFilter` allow-lists and the
fail-closed MCP boundary are byte-identical to the production profile
(`continuable-wiring.v1.json`). `config/dsh/deployment.json`, `compose.yml` and
the production selector `dsh-0.1.2rc1` are unchanged; the production patch still
regenerates cleanly (`scripts/dsh/candidate_profile.py check`).

## Product-semantics contract (real observations, `native-runtime-isolated`)

The real candidate stack (`@deepseek-ai/dsh-agent-loop` + JSONL persistence +
`@deepseek-ai/dsh-subagent` + in-process `spawn` provider +
`@deepseek-ai/dsh-tool-subagent`) with a scripted keyless adapter drives the
actual `byq_delegate_*` tool through `ctx.tools.execute`, one OS process per
generation:

| item | result | observation |
| --- | --- | --- |
| delegate result shape | **PASS** | all five delegates return `{kind: continuable, subagentId}`; `startContinuable` is reached once; `provider: spawn` preserved |
| child-id persistence | **PASS** | the `subagentId` is a durable child session with descriptor v3 `mode=continuable`, `header.parentSession` = the live parent, `origin=subagent` |
| settlement exactly once | **PASS** | one `subagent-settled` delivery per completed child turn; no duplicate on durable re-read |
| lease/observation → original goal | **PASS** | the child is linked to the exact delegation call id and the original parent goal identity; `listChildren` exposes the continuable child |
| no orphan after parent end | **PASS** | after the parent ends, `unsettledChildCount = 0` and the settled child remains addressable |
| **adapter-restart cold resume** | **PASS** | a genuinely new OS process (generation A SIGKILL → generation B) cold-resumes the **same** child: contiguous log, exactly one settlement for the resumed turn, no duplicate |
| child-only crash | **BLOCKED** | the only continuable providers are in-process; a child cannot be independently SIGKILLed while the parent lives. This is a **different** capability from the adapter-restart row and was not faked |
| BYQ compose adapter restart | **BLOCKED** | see below |

**Cold resume is tested separately and PASSES.** The adapter-restart analogue
(new OS process over the same durable store) resumes the same child; this is not
inferred from the in-process provider.

## Real isolated adapter restart (`continuable-adapter-restart.v1.json`)

The **committed** candidate image `byq-d15-4-continuable-candidate:local`
(`--network none`, user `byq`, keyless synthetic MCP + scripted SSE provider)
runs the real `RuntimeAdapter` over two OS-process generations:

- **Generation A PASS**: a real `byq_delegate_market_research` call returns the
  continuable shape, the durable child session v3 is written under the DSH home
  and `subagent.started` is emitted.
- **Generation B BLOCKED**: a fresh isolated adapter process exposes only the
  ROOT `resume_session` operation; the byte-identical 0.1.2 Python SDK exposes
  no child/subagent/continuable operation. There is **no committed BYQ surface**
  that reaches, messages or cold-resumes the persisted continuable child, so a
  BYQ adapter restart cannot rebind it — even though the child session file
  persists with the same id. The owning-process (adapter) restart is explicitly
  **not** a child-only SIGKILL.

Because the decisive question (a BYQ surface that resumes the child) is
identical at the adapter/SDK boundary, this trial runs the real adapter + real
bundled runtime in the committed isolated image rather than the full Gateway
compose stack; the broader D15-3R compose-stack adapter restart is retained
separately. `scope_note` in the evidence records this.

## Fail-able observer

`observer.py --selfcheck` → `negative-controls.v1.json`: 25 controls, all
non-zero for the fixed gate, and all 25 are defect-targeting (the reconstructed
pre-fix result-only gate passed while the fixed gate failed). Controls include
`result-kind-foreground`, `duplicate-settlement`, `same-os-process`,
`cold-resume-duplicate-settlement`, `compose-no-byq-surface`,
`required-blocked`, `required-missing`, `fault-not-applied`, `false-llm-quality`,
`candidate-mismatch`, `negative-not-rejected` and `self-declared-coverage`.

The committed verdict (`verdict.v1.json`) has `format_valid=true`,
`wiring_ok=true`, `all_pass=false`, with `child-crash` and
`byq-compose-adapter-restart` required-**BLOCKED** and gating. **No D15-4 pass,
no D15-G pass and no full-D15 claim.**

## Reproduce

```bash
python3 scripts/dsh/candidate_profile.py check
python3 scripts/dsh/candidate_profile.py check-continuable
python3 scripts/d15/subagent/continuable_wiring_observer.py --wiring \
    --out docs/evidence/d15/d15-4/continuable/continuable-wiring.v1.json
cd scripts/d15/subagent
node continuable_wiring_probe.mjs run \
    --out ../../../docs/evidence/d15/d15-4/continuable/continuable-observations.v1.json
python3 continuable_wiring_observer.py --selfcheck \
    --out ../../../docs/evidence/d15/d15-4/continuable/negative-controls.v1.json
python3 continuable_wiring_observer.py \
    --observations ../../../docs/evidence/d15/d15-4/continuable/continuable-observations.v1.json \
    --out ../../../docs/evidence/d15/d15-4/continuable/verdict.v1.json   # exits 1: two required BLOCKED
```

## Architecture exception (not implemented)

Wiring the delegate onto `startContinuable` is a candidate composition/profile
change and is **not** an architecture exception. Making BYQ able to **rebind a
continuable child across an adapter restart** would require either a new
out-of-process continuable provider or a new BYQ→native child-resume bridge —
both are boundary changes (new provider/second continuity runtime) that are out
of scope for this PR and conflict with the no-second-harness / R3-freeze rules.
They are recorded as an **ADR DRAFT** for review in
`docs/architecture/adr/ADR-DRAFT-dsh-continuable-child-resume.md` and were
**not implemented**.

## Explicit non-claims

- **No D15-4 pass. No D15-5 pass. No D15-G pass. No full-D15 claim.**
- `R3_RESUME = NO`; R3 remains frozen. No provider was added.
- Independent child-process capability remains **BLOCKED**.
- The provider is scripted/keyless: not real-LLM-quality evidence.
- Production selector `dsh-0.1.2rc1`, `compose.yml` and `deployment.json` are
  unchanged; the candidate remains isolated.
