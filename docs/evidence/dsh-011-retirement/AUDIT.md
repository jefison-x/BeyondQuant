# DSH 0.1.1rc1 retirement and MCP Hono qualification

## Scope and authorization

The maintainer accepted retiring old-version support after reviewing PR #269,
#270 and #271: “好的就这样处理。” Accepted ADR-0069 records the exact scope.
This maintenance retires daily old-runtime installation/build/execution, preserves
historical images/backups/evidence, handles the three dependency PRs and qualifies
MCP Hono 4.13.7. It does not deploy production or advance Product Phase 97.

## Changes

- Daily Compose/CI and Runtime Adapter defaults use official 0.1.2rc1 only.
  Selecting 0.1.1rc1 at the application entry point is rejected.
- Old npm manifest/lock files are byte-preserved `.archive` provenance fixtures,
  outside installable npm manifests and dependency update discovery. Original
  hashes are checked against the exact pre-retirement Git source.
- Old SDK compatibility implementation moved out of application code into historical
  test fixtures; no old SDK is installed or executed by routine CI.
- New current build identity is independent; old manifests are not rewritten.
  Archived build verification cannot generate a new old-release build.
- The historical U7 overlay helper rejects current-only receipts, so the current
  runtime cannot be mislabeled as a 0.1.1 rollback image.
- Current-runtime lifecycle, real MCP/delegate, F6 budget/chain and Product browser
  tests remain. Helper JavaScript tests use the scoped MCP Node image.
- MCP Hono is pinned directly at 4.13.7, satisfying the SDK's peer requirement.
  No DSH upstream version, package binary or Product permissions change.

## Dependency provenance

PR #269 changes current MCP Hono; #270/#271 target only the retired npm closure.
Official metadata: Hono 4.13.7, MIT, npm tarball
`https://registry.npmjs.org/hono/-/hono-4.13.7.tgz`, integrity
`sha512-c8/gF9ac8Y78/agExVocyLevgR+JlpNB444Py0FSX8pJoPdYUfUzRcXtYEYGwt6l19qIlVZPN5Mfsw9jFShmQQ==`.
Metadata matches the resolved lock; clean image `npm ci` verifies integrity.
[Official release notes](https://github.com/honojs/hono/releases/tag/v4.13.7).
This dependency update does not assert that every upstream advisory was reachable
through BYQ. It does not patch the separately bundled DSH executable's dependencies.

## Verification record

- Initial `.31` checks exposed current-file assumptions in historical verification;
  those failures were retained and fixed by separating metadata validation from
  exact archived Git input verification.
- `.32`: 231 architecture/governance tests passed; image build succeeded. Full CI
  was intentionally cancelled (exit 143) during Backend regression to add the
  historical overlay guard. It is not a full-CI PASS.
- `.33`: 232 architecture/governance tests passed; local and remote full CI were
  intentionally cancelled to migrate the remaining smoke/browser assertions
  from the retired SDK to the supported SDK. Not a full-CI PASS.
- `.34`: full local CI 30 PASS / 1 FAIL. The smoke used the correct current
  web-evidence producer, but its MCP contract invocation still defaulted to
  expecting the retired producer. The explicit smoke expectation is corrected
  to 0.1.2-rc.1; historical provenance tests remain separate. F6 chain and all
  13 real Product API browser cases passed in this run.
- `.35`: current-only build qualification submitted in
  [PR #273](https://github.com/jefison-x/BeyondQuant/pull/273). Final local CI,
  remote exact-head checks, cleanup and delivery results are recorded on that PR;
  this source record does not infer success from creating a manifest or opening a PR.

## Boundaries

Historical descriptions and test fixtures remain readable; they are not supported
runtime targets. Old release-bound Dockerfiles require their historical Git tree
and are not current build recipes. Emergency use of archived images remains a
separately authorized operator action. Existing production `.30` remains unchanged.
F2 remainder, S3, full interface audit and U8 observation remain independent work.
