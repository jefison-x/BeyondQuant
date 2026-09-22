# 0.9 final development closeout (machine-readable, fail-able)

- Assessment id: `v090-final-closeout.v1`
- Decision: **`V090_DEVELOPMENT_CLOSEOUT_COMPLETE`**
- Date: 2026-09-22
- Base: dynamic `origin/main` `561fe924aa799680360b442a8be0c915fa028b3a` (contains PR #355)
- Branch / worktree: `codex/v090-final-closeout`

This is the **independent final 0.9 development closeout**. It verifies every
0.9 development-required item from the original merged evidence and its hashes
and declares `V090_DEVELOPMENT_CLOSEOUT_COMPLETE` only when all of them equal
their evidence-derived expected truth and every boundary constraint holds.

It does **not** deploy, does **not** create or move any tag/release, does
**not** resume Phase 100, does **not** start 0.10 and does **not** automatically
start R3. The repository default DSH `0.1.5-rc.1` is **not** a production
deployment; the formal 0.9.0 release manifest gate remains separate and open.

## Read this first

| artifact | what it is |
| --- | --- |
| [`assessment-input.v1.json`](assessment-input.v1.json) | the closeout report: claimed decision, the 15 required item statuses, the scoped limitations, the boundary constraints and the open formal release gate |
| [`provenance.v1.json`](provenance.v1.json) | sha256 + introducing commit for every reused source evidence file |
| [`verdict.v1.json`](verdict.v1.json) | fail-able observer output: independently derived decision, `format_valid`, `honest`, `complete`, `all_pass`, exit 0 |
| [`negative-controls.v1.json`](negative-controls.v1.json) | selfcheck: known-good fixture completes; 29 controls all rejected (28 defect-targeting) |
| [`interface-audit.v1.json`](interface-audit.v1.json) | the committed live fail-closed full-interface auditor output at this commit |
| contract + observer | `scripts/v090/final_closeout/{contract.v1.json,observer.py,build_provenance.py}` |

## Derived closeout matrix

| required item | derived | evidence |
| --- | --- | --- |
| `closeout_audit` | `COMPLETE` | committed 0.9 gap ledger + acceptance matrix (historical snapshots) |
| `f2_unknown_result_reconciliation` | `COVERED` | named F2 slices + live interface auditor `complete=true` (its only recorded open reason was the stale H4 ledger) |
| `full_interface_audit` | `COMPLETE` | live auditor `discovered = reviewed = verified = 569`, `missing = stale = fake_pass = 0` |
| `composite_research_fault_regression` | `PASS_AS_SCOPED` | frozen v2 matrix: journey PASS, 13 gating rows PASS, exactly the four contract-fixed non-gating rows honestly BLOCKED |
| `adr_0082_0083_decision` | `RECORDED_ACCEPTED` | maintainer decision record (ADR-0082 modified accept, ADR-0083 as proposed, no GitHub approval, `implementation=none`) |
| `containment_business_recovery_gate` | `PASS` | re-derived by the D15 superseding observer with provenance verification: real isolated acceptance 9/9 |
| `coherent_dsh_default_upgrade` | `PASS` | coherent `0.1.5-rc.1` pairing, readiness matched, `0.1.2rc1` rollback preserved, no production deployment claimed |
| `d15_superseding_assessment` | `ESTABLISHED` | committed named D15 superseding assessment |
| `historical_d15_g` | `NO_GO_PRESERVED` | committed D15-G verdict, four atomic blockers, not rewritten, not re-run |
| `b1_subagent_child_crash` | `BLOCKED_EXTERNAL` | no out-of-process continuable provider; scoped limitation only |
| `b2_subagent_byq_adapter_restart` | `BLOCKED_EXTERNAL` | no committed BYQ composition child-rebind surface; scoped limitation only |
| `b3_terminal_adapter_restart` | `PASS_CANDIDATE` | candidate/qualification-layer minimal `TerminalAttachment` lifecycle |
| `b4_terminal_dsh_runtime_restart` | `PASS_CANDIDATE` | candidate/qualification-layer truthful `lost` across a real DSH runtime restart |
| `native_independent_child_resume` | `NOT_IMPLEMENTED` | B1/B2 remain external blockers; no implementation claim |
| `r3_resume` | `NO` | R3 stays frozen; only the bounded thin-supervisor scope is permitted |

B1/B2 are `BLOCKED_EXTERNAL` and, per ADR-0084 section 3, **only limit native
independent child resume**. They are recorded scoped limitations, not hidden
blockers, and they do not gate the development closeout, candidate
compatibility, the repository-default promotion or the bounded R3 scope.

## Boundary constraints (machine-checked)

| constraint | value |
| --- | --- |
| `repository_default_release` | `dsh-0.1.5rc1` |
| `rollback_candidate` | `dsh-0.1.2rc1` |
| `production_deployment` | `none` |
| `release_or_tag_created` | `false` (no `byq-release.v1` manifest committed) |
| `phase_100_resumed` | `false` (`byq:phase-100-p100-c=paused-not-delivery` retained) |
| `zero_ten_started` | `false` |
| `r3_resume` | `NO` |
| `b1_b2_downgraded` | `false` |
| `next_state` | `maintainer-testing-and-0.9x-window` |
| `build_revision` | `dsh-0.1.5rc1-post-u8.203` |

## Formal release gate (separate, open)

The formal 0.9.0 release manifest (source SHA, trusted-main full CI,
all-service digests, actual composition, migration classification, SBOM,
backup, rollback, independent release acceptance, attestation) remains
`OPEN_NOT_ATTEMPTED`. It is a release gate, not a development-closeout gate, and
is not satisfied or attempted here.

## The fail-able observer

The observer re-derives every required item from raw evidence — re-running the
D15 superseding derivation (with provenance verification) for the D15 family,
re-running the fail-closed full-interface auditor on the current tree, and
checking the composite/composite-matrix, the ADR decision record and the
constraints — and separates `format_valid` from `honest` and `complete`. It
exits non-zero when the closeout overclaims, for example:

1. reports a `BLOCKED_EXTERNAL` item as `PASS` / native child resume as
   `IMPLEMENTED` / `r3_resume=YES`;
2. claims a production deployment, release or tag, a Phase 100 resume or a 0.10
   start;
3. claims the full-interface audit complete while the live auditor is incomplete
   or diverges from the committed snapshot;
4. claims the superseding assessment established while the re-run derivation is
   not established, or rewrites the historical D15-G;
5. declares its own verdict/coverage/established fields;
6. relies on missing, unreadable or hash-mismatched evidence (fails closed to
   `MISSING`, never a default pass);
7. hides a scoped limitation or fabricates a wrong next state/build revision.

`negative-controls.v1.json` records 29 controls, all rejected; **28 are
defect-targeting** (the reconstructed pre-fix result-trusting algorithm passed
them). The known-good fixture completes, proving the gate is not simply
always-fail.

## Reproduce

```bash
python3 scripts/ci/check-reliability-review.py \
    > docs/evidence/v090-final-closeout/interface-audit.v1.json
python3 scripts/v090/final_closeout/build_provenance.py \
    --out docs/evidence/v090-final-closeout/provenance.v1.json   # create-only
python3 scripts/v090/final_closeout/observer.py \
    --assessment docs/evidence/v090-final-closeout/assessment-input.v1.json \
    --provenance docs/evidence/v090-final-closeout/provenance.v1.json \
    --out docs/evidence/v090-final-closeout/verdict.v1.json
python3 scripts/v090/final_closeout/observer.py --selfcheck \
    --out docs/evidence/v090-final-closeout/negative-controls.v1.json
```

The observer and its evidence are asserted by `tests/test_v090_final_closeout.py`.

## Next state (not an automatic action)

The next state is the **maintainer testing and 0.9.x minor feature
addition/optimization window**. 0.10 and Phase 100 resume remain unauthorized
hard stops; R3 is not automatically started.

## Build identity sync

This batch adds build inputs (`scripts/`, `tests/`), so the build identity
advances `dsh-0.1.5rc1-post-u8.202 -> post-u8.203`. `scripts/dsh/build_revision.py`,
`Dockerfile.post-u8-candidate`, `scripts/v090/dsh_default_upgrade/verify.py`, the
promoted release descriptor, the generated `deployment.identity.json` and the
`default-upgrade.v1.json` digest entries are synced (digest-only where causally
required). The `.202` manifest and every historical evidence file are preserved.
