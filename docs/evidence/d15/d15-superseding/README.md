# Named D15 superseding assessment (ADR-0084 gate reclassification)

- Assessment id: `d15-superseding-assessment.v1`
- Decision: **SUPERSEDING_ASSESSMENT_ESTABLISHED**
- Date: 2026-09-22
- Base: dynamic `origin/main` `8a4e4fe41771a25c472fa24195aedccf3f53a6a8` (contains PR #354)
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm `0.1.5-rc.1`
- Branch / worktree: `codex/v090-d15-superseding-assessment`

This is a **named, machine-readable, fail-able** superseding assessment. Under
Accepted ADR-0084 the historical D15-G verdict no longer globally blocks 0.9.x
closeout, candidate compatibility, the bounded R3 scope or unrelated roadmap
work; the current required gate is **BYQ session failure containment and business
recovery**. This assessment references the historical D15-4/D15-5/D15-G verdicts
**without rewriting them**, truthfully reclassifies the gate scope for the
actually adopted range, and never reports native independent child resume as
implemented.

It does **not** execute the final 0.9 closeout, does not deploy, does not create
or move a tag/release, does not resume Phase 100 and does not start 0.10.

## Read this first

| artifact | what it is |
| --- | --- |
| [`assessment-input.v1.json`](assessment-input.v1.json) | the superseding assessment report: claimed decision, the 11 required component statuses, the bounded R3 scope and the adopted-scope description |
| [`provenance.v1.json`](provenance.v1.json) | sha256 + introducing commit for every reused source evidence file |
| [`verdict.v1.json`](verdict.v1.json) | fail-able observer output: independently derived decision, `format_valid`, `honest`, `established`, `derived_r3_permitted_scope`, exit 0 |
| [`negative-controls.v1.json`](negative-controls.v1.json) | selfcheck: known-good fixture establishes; 21 controls all rejected (19 defect-targeting) |
| contract + observer | `scripts/d15/superseding_assessment/{contract.v1.json,observer.py,build_provenance.py}` |

## Derived result (evidence-driven, not presupposed)

| component | derived | source |
| --- | --- | --- |
| `historical_d15_g` | `NO_GO_PRESERVED` | committed D15-G verdict + capability matrix (four atomic blockers, un-rewritten) |
| `replacement_gate_business_recovery` | `PASS` | merged business-recovery implementation + real isolated acceptance 9/9 + containment/classification + zero cleanup, production untouched |
| `coherent_dsh_default_upgrade` | `PASS` | coherent `0.1.5-rc.1` pairing, readiness `matched`, `0.1.2rc1` rollback baseline preserved, no production deployment claimed |
| `b1_subagent_child_crash` | `BLOCKED_EXTERNAL` | rc.2/alpha.2 provider qualification (no out-of-process `prepareContinuable` provider) + D15-4 |
| `b2_subagent_byq_adapter_restart` | `BLOCKED_EXTERNAL` | B2 candidate probe (no committed BYQ composition child-rebind surface) + D15-4 |
| `b3_terminal_adapter_restart` | `PASS_CANDIDATE` | B3 candidate verdict (candidate/qualification layer only) |
| `b4_terminal_dsh_runtime_restart` | `PASS_CANDIDATE` | B4 candidate verdict + current overlay (historical D15-5 unchanged) |
| `native_independent_child_resume` | `NOT_IMPLEMENTED` | B1/B2 remain external blockers; no implementation claim survives |
| `candidate_compatibility_actual_scope` | `PASS` | replacement gate + coherent upgrade + B3/B4 candidate PASS (B1/B2 do not gate this scope, ADR-0084 §3) |
| `candidate_promotion_actual_scope` | `REPO_DEFAULT_PROMOTED` | repository default selector only; production deployment/release/tag remain separate and are not claimed |
| `r3_resume` | `NO` | native independent child recovery is unimplemented and historical D15-G remains `NO_GO` |

`r3_permitted_scope = [safe_failure, observation, cleanup, new_generation_recovery]`
— the bounded thin-supervisor scope from ADR-0084 §3; a full R3 unfreeze is a
separate decision and is **not** granted here.

## The fail-able observer

The observer re-derives each component, the bounded R3 scope and the decision
from raw evidence and separates `format_valid` (artifact + provenance) from
`honest` (claimed equals derived) and `established` (every required component
equals its ADR-0084-consistent expected truth). It exits non-zero when an
assessment overclaims, for example:

1. reports a `BLOCKED_EXTERNAL` capability as `PASS` / native child resume as
   `IMPLEMENTED`;
2. claims the replacement gate or the coherent upgrade `PASS` while the source
   evidence does not;
3. rewrites the historical D15-G verdict into `GO`/`PASS`;
4. claims `r3_resume = YES` or widens/drops the bounded R3 scope;
5. claims a production deployment/release/tag;
6. declares its own verdict/coverage/established fields;
7. relies on missing, unreadable or hash-mismatched source evidence (fails closed
   to `MISSING`, never a default pass).

`negative-controls.v1.json` records 21 controls, all rejected; **19 are
defect-targeting** (the reconstructed pre-fix result-trusting algorithm passed
them). The known-good fixture establishes, proving the gate is not simply
always-fail.

## Boundaries (unchanged)

- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
  `BLOCKED_EXTERNAL`; historical D15-4/D15-5/D15-G verdicts and files are
  referenced, never rewritten.
- Native independent child resume is **not** implemented.
- `R3_RESUME = NO`; the R3 scope is bounded only.
- Promotion is the **repository default** only; no production deployment, release
  or tag; Phase 100 is not resumed; 0.10 is not started; this PR does not execute
  the final 0.9 closeout.

## Build identity sync

The assessment adds build inputs (`scripts/`, `tests/`, `services/runtime-adapter`),
so the build identity advances `dsh-0.1.5rc1-post-u8.200 -> post-u8.201`.
`scripts/dsh/build_revision.py`, `Dockerfile.post-u8-candidate` and
`scripts/v090/dsh_default_upgrade/verify.py` are synced; the promoted release
descriptor `config/dsh/releases/dsh-0.1.5rc1.json`, the generated
`config/dsh/generated/deployment.identity.json`, the new
`config/dsh/builds/dsh-0.1.5rc1-post-u8.201.json` manifest and the
`default-upgrade.v1.json` digest entries for the changed build-identity files are
refreshed (digest-only, causally required). The `.200` manifest and every
historical D15 evidence file are preserved.

## Reproduce

```bash
python3 scripts/d15/superseding_assessment/build_provenance.py \
    --out docs/evidence/d15/d15-superseding/provenance.v1.json   # create-only
python3 scripts/d15/superseding_assessment/observer.py \
    --assessment docs/evidence/d15/d15-superseding/assessment-input.v1.json \
    --provenance docs/evidence/d15/d15-superseding/provenance.v1.json \
    --out docs/evidence/d15/d15-superseding/verdict.v1.json
python3 scripts/d15/superseding_assessment/observer.py --selfcheck \
    --out docs/evidence/d15/d15-superseding/negative-controls.v1.json
```

The observer and its evidence are asserted by
`tests/test_v090_d15_superseding_assessment.py`.
