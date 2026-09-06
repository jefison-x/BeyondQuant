# U7 exact-image readiness — PREDEPLOYMENT VERIFIED

Deployment decision: NOT DEPLOYED. Final updated PR CI/merge, private artifact
preparation, ingress closure/drain, final backups and actual production checks
remain operator gates. U8 has NOT STARTED; Product Phase 97 is unchanged.

## Exact artifacts and qualification boundary

Both immutable U7.3 manifests validate current bound sources. Local full CI
`local-u7-recheck-artifacts-20260906` passed all 26 checks and cleanup. The retained
seven-image archive and exact local image IDs are in [retained artifacts](retained-artifacts.json).
These are local image IDs, not remote registry digests. The original B0 recovery
archive is separate from the qualified R1 rollback set.

| Installed projection | SHA-256 |
|---|---|
| Target policy | `76f417b50e554df14ffaeef024cc35fe2e9d77e6c90484ea88301e5ed0228b65` |
| Compatible rollback policy | `adb790c4f8fb059f73041507253a2da41088ce44b2f7e59052e0cc81376e24de` |
| Target Product plugin registry | `58c4b0dfec675efd2f4657afc742cb2c7c0bf7758ddc8eed12146a3b17647270` |
| Target deployment identity | `c488f1bc4123159e87b0641b2f6a0ded8714478d0d809cf37ccc7de134b84084` |

The raw rehearsal receipts compare these actual installed files byte-for-byte
against source and bind them to the retained images/manifests at each switch.
This independently qualifies the changed U7 policy/registry; the historical U6
v2 report's candidate-policy hash is NOT presented as the promoted-policy hash.
Historical releases, reports, failing assertions and U7.1/U7.2 inputs remain intact.

## Acceptance evidence and retained failures

- [CI result](CI_RESULT.md): complete keyless/integration suite, paired 20+20
  genuine lifecycle measurements. RSS is an explicit bounded-carrier exception
  (2.5118 MiB over the unchanged reference formula), NOT a threshold PASS; U8 must
  still inspect long-term behavior and actual capacity.
- [Chrome review](CHROME_REVIEW.md) and [Community checklist](COMMUNITY_FEATURE_CHECKLIST.md):
  actual desktop/mobile maintenance input retention, global approval continuation,
  final answers and Product plugin identity/blocked-capability review.
- [Core receipt](promoted-rehearsal.failed-g3.raw.json): passing G1/G2, real
  old→new→old G6/G5 continuation, one fake-Hub receipt/zero publication, unchanged
  independent containers/domain objects, namespace separation and actual restore.
  Its overall result remains FAIL because its later G3 failed.
- [Clarified G3 receipt](g3-clarified-g4-report-failure.raw.json): authorized new
  prompt revision, one strategy approval, two necessary artifacts, authoritative
  progress, one bounded continuation retry, zero training/prediction. Its overall
  result remains FAIL because subsequent G4 report construction failed.
- [Final G4 receipt](g4-evidence-rollback.raw.json): fixed original G4, exactly one
  URL-bearing research-only artifact; actual coordinated R1 rollback reads the
  identical artifact list and recognizes the new producer; no database rewind.
  Overall result and cleanup PASS.
- [Semantic review](MODEL_REVIEW.md) records the original G3 coverage gap,
  explicit maintainer clarification, independent successful components and G4
  report bug. No failed aggregate run is relabeled PASS, and no synthetic sample
  is claimed as production traffic or three independent repetitions.

## Production handoff

See [production preflight](PRODUCTION_PREFLIGHT.md) and [execution](EXECUTION.md)
for exact authority, restored old production, private B0 images/configuration,
logical backup and actual isolated 105-table restore proof. Retain backups/images
at least seven days AND until maintainer stable confirmation; no automatic deletion.

`production_prepare.py` prepares only private checksummed images and three explicit
five-service overlays. It does not deploy. `production_session_backup.py` refuses
active/restarting or wrong writers/volumes, mounts ONLY DSH/WorkflowTrace volumes
read-only in network-none disposable utilities and never mounts PostgreSQL.
Production stop/switch requires verified drained state and the merged clean main.
All deploy commands must retain `--no-deps --no-build --pull never` and the exact
service allowlist. Do not use the private backup directory as a general container
mount, restore production DB, or rebuild during rollback.
