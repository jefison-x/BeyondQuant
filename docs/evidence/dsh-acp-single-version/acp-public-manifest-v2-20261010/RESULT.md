# External release manifest v2: bounded source qualification

## Scope and decision

2026-10-10, existing isolated `codex/dsh-acp-single-version` worktree, HEAD
`2d5810973240c5d7692569319c2b5ab337ae2082` plus preserved working changes.
Backups preceded edits. No reset, build, container start, Docker load/push,
provider call, F6 rerun, commit, PR, publication or deployment occurred.

The previous external `byq-release.v1` name had been retained while its shape
changed from the HEAD baseline's 13 services / seven top-level keys to 17
services / nine keys with ACP topology and DSH identity. The current operator
already rejected the historical shape. This slice fixes the version contract:
`images.PUBLIC_MANIFEST_V2` is `byq-release.v2`, publication emits it and the
operator accepts only that current strict shape. Both per-role and explicitly
selected single-image topologies use v2. The internal
`byq-release-images.v1/v2` and DSH identity schemas are unchanged.

Old seven-key / 13-service v1, current 17-service manifests mislabeled v1,
and unknown versions fail before SBOM reading, GitHub/attestation/API calls,
Docker operations or operator output. Signed historical manifests are not
relabeled, upgraded or granted ACP fields. Actual historical signed-artifact
operation compatibility remains **OPEN / NOT_RUN**.

## Verification

| Gate | Result | Evidence and boundary |
| --- | --- | --- |
| Independent final focused release module | PASS, limited | 53 methods + 23 subtests covered: 51 methods passed in restricted-PATH attempts, then only two affected methods passed with normal PATH. Source hashes match; compile/diff pass. Not a single green module invocation or hosted CI. |
| Independent Reviewer | PASS, limited | Functional, Tests and Clean Break Architecture review; no P1/P2 in the exact frozen slice. |
| Root | PASS, limited | Three source files, runbook, current architecture evidence reconciliation and scoped verification only. |
| Current-source architecture coverage before v2 | LOCAL COVERAGE ONLY | [Original discovery + exact failure recheck](../acp-current-architecture-20261010/RESULT.md): first run FAIL, 19 rechecks PASS, same source; combined 1000 passed / 11 skipped. Not a single green Full run. |
| Current image / three-role boot / F6 | REUSED | [Existing current-image checkpoint](../acp-unified-retry-and-f6-20261010/RESULT.md); release scripts/tests/docs do not change image runtime inputs. |
| Adopting-commit architecture / Full CI | NOT_RUN | Existing dirty-worktree evidence does not close ADR-0110 criterion 2 or 6. |
| Hosted Docker export, registry manifest/config/SBOM/attestation | NOT_RUN | No real publication or cross-daemon load in this slice. |
| Default topology adoption / production deployment | NOT_RUN | Default route remains per-role; development does not grant adoption or deployment. |

The Worker first ran 53 tests + 23 subtests on an earlier test checkpoint. Root
then found that the old-13 fixture still retained the two new top-level fields.
The fixture was corrected to the actual historical seven-key shape and gained
an explicit no-SBOM-call assertion. Worker ran only the selected new case
(1 test + 2 subtests). Independent Tester's constrained PATH hid bash, then cat,
causing classifier startup failures; hiding Docker skipped the configuration-only
case. Those failed attempts remain failed. Root clarified that normal shell
tools and static `docker compose config` are allowed and requested only the
two affected cases be rechecked, without repeating 51 passing cases. Earlier
results remain checkpoint evidence rather than final-source proof.

## Consumer audit and remaining work

Live workflows delegate to the release scripts: `release-images.yml` exports
and publishes; `promote-images.yml` invokes `manifest.py promote`. They contain
no separate schema literal requiring a version edit. The 0.9 final-closeout
observer scans only v1 in its historical scope; it is not called by current
release/CI consumers and must not be used as a current release detector.
Frozen 0.9 contracts, tests and snapshots are unchanged. ADR-0070 and Accepted
ADR-0110 already govern provenance and the topology; no new privilege,
architecture exception or generic migration runtime was introduced.

Remaining gates: an authorized adopting source checkpoint and exact-head PR/
Full CI; actual hosted Docker store/archive behavior; trusted-main publication
with shared registry digest, config/platform, SBOM and attestation readback;
historical signed-release operation assessment where needed; and separately
authorized default-route adoption / deployment. Overall adoption/release is
**NOT_READY**. No image rebuild or repeated accepted F6 is justified by this
schema-only correction.

## Receipts

`artifacts/source-before.json`, `artifacts/source-after.json` and
`artifacts/implementation-diff.txt` bind the exact slice. `artifacts/tester/`
and `artifacts/reviewer/` retain independent results. `artifacts/root-decision.json`
records the bounded Root decision. `artifacts/SHA256SUMS.json` inventories small
receipts; raw large image archives are not duplicated.
