# Post-U8 independent build requalification

Date: 2026-09-08. Status: KEYLESS_CI_VERIFIED; not release-ready, merged or deployed.

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
  supporting runtime inputs before full certification. The process exited 143;
  independent `cleanup-resources.sh --scope=post-u8-qual-20260908-1 --verify-only`
  confirmed no scoped containers, image tags, volumes or networks remain.

## Second build identities — FAILED integration

| Build | Manifest SHA-256 | Bound inputs |
| --- | --- | --- |
| dsh-0.1.1rc1-post-u8.2 | 52ac2740e59668d1417053b155067f38a4d48e9e0de290642e72bc548f0abbcc | 537 |
| dsh-0.1.2rc1-post-u8.2 | 92960468c2212b6b45a6371c9997f17dbc80b27077ea0192b446f3e6d51efccf | 539 |

The second revision additionally binds all worker sources, signal sandbox,
PostgreSQL initialization, engineering/acceptance scripts, repository tests and
CI/browser configuration. Regression assertions require these inputs and reject
missing or modified worker entries. The first revision is retained unchanged.

Full isolated CI (`post-u8-qual-20260908-2`) finished with **24 passed, 2 failed**.
Backend: 421 passed/1 skipped/7 subtests, 459.70 seconds; Gateway: 175 passed;
Runtime regular: 117 passed/14 skipped; candidate real process/delegates: 12 passed.
Both lifecycle benchmarks completed 20 cycles with zero lingering threads and
retained sessions. MCP complete suite, frontend build and 54 files/172 unit tests
passed. Restart/two-user Product checks passed. The two failures were:

1. Keyless Product prompt: expected 503, received 502 `prompt_outcome_unknown`.
   Gateway treated Runtime's known credential pre-admission failure as an unknown
   server outcome. New exact `prompt-rejection.v1` binds session/message/content
   digest; only this closed receipt retains 503. Ordinary/forged/mismatched server
   failures remain unknown. Approval continuation uses the same distinction.
   Runtime checks accepted idempotent receipts before credential rejection, so
   later credential loss cannot negate prior acceptance.
2. Real stock-pool browser test: creation succeeded, but its locator expected the
   old English `current` after the UI adopted Chinese `已就绪`. The assertion now
   checks the readiness row, without relaxing creation or persistence assertions.

The new Gateway counterexample first failed (1 failed/6 passed); initial full
Gateway regression after the fix passed 182 tests. Additional integer-false and
approval-continuation cases were then added. No paid API was used to bypass the
keyless failure. Independent cleanup verification confirmed zero `.2` resources.
Logs and browser traces remain in `.ci-artifacts/post-u8-qual-20260908-2*` locally.
This image is not certified; the fixes require a new immutable build revision.

## Third build identities — local keyless CI VERIFIED

| Build | Manifest SHA-256 | Bound inputs |
| --- | --- | --- |
| dsh-0.1.1rc1-post-u8.3 | 4162c8d16c1672831fe160d8b86f06cfbd8938e214b20c2109f04c28c969001b | 539 |
| dsh-0.1.2rc1-post-u8.3 | 070df99a554521c26afed72fe541b1c234efbeecba00da72f0f3099407530ede | 541 |

Gateway full regression including exact/forged rejection and approval-continuation
cases: 183 passed, 1.68 seconds. Repository architecture/governance: 214 passed,
10.325 seconds. The isolated rejection-test image was removed and its scope
`post-u8-rejection-20260908` independently verified clean.

Full keyless CI `post-u8-qual-20260908-3` completed with exit 0 and **26/26 checks
passed**. Backend 421 passed/1 skipped/7 subtests (458.74 seconds), Gateway 183
passed, Runtime regular 119 passed/14 skipped, candidate real-process/delegates
12 passed, MCP complete suite, frontend build and 172 unit tests passed. Browser
results: 20 mocked journeys and 9 real Product API journeys passed. Both previous
integration failures passed on the new revision. Runtime lifecycle loops,
restart persistence, feedback boundaries and two-user Product coherence passed.

Both Runtime images were run without network and read-only to verify their exact
embedded manifest hashes and installed SDK/runtime-bin versions. Source inputs
match commit `ca82e19ce46f64accf9b54553be6d8c452f839c8`; local CI began before
that commit was made, so this is inventory-bound local evidence, not a claim that
the run began on a clean commit. Remote exact-head CI is a separate gate.

Independent `cleanup-resources.sh --scope=post-u8-qual-20260908-3 --verify-only`
passed after CI exit. The run's containers, image tags, volumes and networks are
gone; synthetic test data is rebuildable and was not backed up. Production and
Community data were untouched. The [keyless build receipt](keyless-build-receipt.json)
records all 12 image IDs, both exact build identities, benchmark samples and hashes
of the three retained sanitized logs. Deprecation and transient dev-server
ResizeObserver warnings are retained, not silently removed from the log.

## Not implied

No historical QUALIFIED report is copied to the new image. F6 cumulative-budget
enforcement, F7 persistent correction limits, remaining S3 historical demand/cache
proof and complete research semantic journeys remain open. U8 is still
`CLOSED_EARLY_REMEDIATION_REQUIRED`, not a completed 24-hour observation.
