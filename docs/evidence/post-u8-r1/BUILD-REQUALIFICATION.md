# Post-U8 independent build requalification

Date: 2026-09-08. Status: IN_PROGRESS; not release-ready, merged or deployed.

## Authority and immutable history

The maintainer approved independent build identity/requalification, push to
`jefison-x/BeyondQuant`, and a Draft PR only. See the scoped extension to
[ADR-0061](../../architecture/adr/ADR-0061-u6-independent-build-identity.md).
No paid model call, production operation, historical research replay or market
data expansion is part of this build check.

Historical descriptors, generated identities, U6/U7 Dockerfiles/manifests and
qualification reports are unchanged. Both archived descriptor/input inventories
were verified using exact Git blobs, with replacement objects disabled:

| Release | Historical source commit |
| --- | --- |
| dsh-0.1.1rc1 | ce6493f006d9b857f38d81306bbccfcff1a8fbe4 |
| dsh-0.1.2rc1 | 243f8ed6487301eae7a9062357d7060896fedf6f |

`release.py check` still rejects current source drift against the old descriptor.
The explicit `check --historical-inputs` checks archived blobs and current generated
release metadata. It cannot qualify a current image. CI separately checks both
new build manifests before building, with no stale-image fallback.

## First build identities — NOT QUALIFIED

| Build | Manifest SHA-256 | Bound inputs |
| --- | --- | --- |
| dsh-0.1.1rc1-post-u8.1 | 4dd9dc8f41ca3becf57067db714aa6b40d0188d7bdf10cd779eaddc462409f37 | 437 |
| dsh-0.1.2rc1-post-u8.1 | 044697c76607448e0cd0283d236e1a22366faec011415895e4c5dd15c384d25e | 440 |

New explicit Dockerfiles embed the corresponding exact manifest. No existing
manifest is refreshed. The production selector and production Dockerfiles are
not changed by the CI build selection.

## Verification

- Historical verification: new negative tests cover missing Git history,
  descriptor rewriting, corrupt archived source and escaping paths. Current
  default validation remains strict, and historical mode rejects disabling checks.
- Release/history suite: 13 tests passed.
- Complete repository architecture/governance unittest discovery: 212 tests
  passed in 7.324 seconds, including old-image build-failure protection and
  unchanged historical qualification failure assertions.
- Initial full discovery failed: a newly added lifecycle contract used pytest
  functions under the unittest runner, and candidate offline-cleanup failed before
  reaching its intended test due to historical source drift. Lifecycle tests now
  use unittest with all assertions retained. The cleanup unit test supplies
  independently verified archived release metadata; the production preparer
  remains strict. These are real failures, not skipped or reclassified passes.
- Full keyless isolated CI started with scope `post-u8-qual-20260908-1`.
  Sanitized local log: `.ci-artifacts/post-u8-qual-20260908-1.log`.
  Review found that the inherited inventory omitted changed data/ML workers.
  The trial was deliberately cancelled via its own TERM handler; it is not PASS.
  Revision `.1` is retained unqualified. A new revision must include worker and
  supporting runtime inputs before full certification. Cleanup verification is
  still pending at this checkpoint.

## Not implied

No historical QUALIFIED report is copied to the new image. F6 cumulative-budget
enforcement, F7 persistent correction limits, remaining S3 historical demand/cache
proof and complete research semantic journeys remain open. U8 is still
`CLOSED_EARLY_REMEDIATION_REQUIRED`, not a completed 24-hour observation.
