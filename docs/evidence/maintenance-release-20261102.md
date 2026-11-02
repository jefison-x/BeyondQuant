# Phase 17 maintenance release/deployment reconciliation — 2026-11-02

Status: **PASS within the recorded maintenance, trusted-image and six-service
pre-release deployment scope.** This is a reconciliation of retained receipts,
not a new test run, deployment, version tag or formal v1.0 release.

## Source, authorization and independent gates

- Maintenance [PR #421](https://github.com/jefison-x/BeyondQuant/pull/421): tested
  head `b298e85916370dd81399a64bba141d055cc098b8`.
- Squash result `82e1551e5af5de76a5688e8868d08767306985e7`: its source tree equals
  the tested head. Branch ancestry alone would misclassify this squash delivery.
- [Exact-head PR CI](https://github.com/jefison-x/BeyondQuant/actions/runs/41372139236):
  all 12 checks/jobs passed, including all eight planned component/integration lanes.
- GitHub rejected enabling auto-merge because the PR was CLEAN. The maintainer
  then explicitly allowed direct squash of this PR's tested head. This was a
  one-time exception; no direct main push, admin bypass or rule change occurred.
- The maintainer's all-steps authorization covered this release and deployment.
  It does not confer standing authority for future releases or historical PRs.
- [Trusted-main Release Images](https://github.com/jefison-x/BeyondQuant/actions/runs/41374500297):
  qualification and publication passed on the squash source, with migration
  classification `forward-compatible`. No separate standalone Full was dispatched.

## Results and evidence boundaries

| Gate | Retained result |
| --- | --- |
| Local feedback/Runner/partial usage | PASS under the [maintenance scope](feedback-runner-maintenance-20261102.md); Runner 20 tests |
| Candidate real Product browser | PASS through Gateway with durable identities; 8 known receipts, 2,030,103 tokens, 44 provider attempts |
| Trusted manifest | PASS: 17-service structure, DSH identity and ACP binding, 15 distinct SBOM checksum checks |
| Manifest signature/attestation | PASS: CLI exit 0; repository, Release Images signer workflow, main ref and exact source digest constrained |
| Operating deployment | PASS: Backend, Gateway, Frontend, Runtime Adapter, Product Runner and Judgment Runner replaced and healthy |
| Unaffected operating services | PASS: the other 11 container IDs/images unchanged |
| Operating browser | PASS: normal login/logout, same durable identity, user-wide options API and 15 loaded inputs, partial usage refresh and desktop/mobile display |
| Existing operating conversation read | NOT_RUN: the authorized pre-deployment catalog was already empty |
| Operating real Agent/Job/F6 execution | NOT_RUN; F6 master flags remain 0 on Backend/Gateway/Runtime |
| Test environment/page preservation | PASS under retained before/after inventories; six acceptance services healthy and original three IAB tab IDs/URLs retained |
| Final independent Sol review | PASS within release/deployment/retention scope, including the signature/SBOM receipt addendum |

The signed manifest SHA-256 is
`048748f9b76f8dfdef63a11812ef9fe9b81c3c251288724edcec0c6fdcd9bd5c`.
The attestation subject equals this digest. This document reuses the recorded
verification; it does not claim a fresh signature/network verification.

Operating data remained one user and zero conversations/messages/ResearchTasks,
with the original password-change timestamp. The user execution-options table
was added without resetting that identity or manufacturing conversation samples.
The operating usage display reports no known receipts, not zero global usage.
Test-stack usage and real F6 evidence are distinct from this operating stack.

## Preservation and limits

Encrypted logical PostgreSQL and seven session/control/trace-volume backups were
retained, with full decryption and catalog-readability checks passed. Existing
images and configuration were preserved for rollback. A restore/load drill was
**NOT_RUN**; readability does not establish a completed restoration. No automatic
database restore occurred. The retained test ledger digest, five-Task count and
password timestamp were unchanged. The test worktree and built frontend assets
remain required by two read-only test mounts.

The original failed credential, empty-catalog and hidden-input assertions remain
recorded. Corrected bounded readbacks do not rewrite those failures. Hub acceptance
is maintainer-confirmed; no new formal Hub replay was performed. Ordinary Product
Root and research Judgment usage remain uncovered, with no billing claim.

The evidence root is `.ci-artifacts/maintenance-release-20261102/` in the retained
worktree: `RESULT.md`, `final-release-deployment-review.md`,
`manifest-sbom-verification.json`, `manifest-signature-summary.json`,
`manifest-attestation-verification.json` and the operating/test retention readbacks.
The protected operator receipt and backups remain outside Git. These paths locate
the existing local evidence; the linked GitHub runs identify the hosted evidence.
No credentials, raw user receipts or private backup contents are copied here.

[Phase 17 final acceptance](../clean-break/phase17-final-acceptance-20261102.md)
remains the product phase verdict. These operations do not establish complete
product parity, universal Agent recovery, a formal v1.0 release or Phase 18 work.
