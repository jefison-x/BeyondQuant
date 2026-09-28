# Phase 7 dead persistence deletion evidence (2026-09-28)

## Boundary

This slice removes old Adapter disk mechanisms that had no callers in the
current Product runtime. The selected `.238` image no longer contains
`app/containment.py` or `app/executor_identity.py`. The old operator
`takeover_executor_epoch.py` and its test are removed. Two uncalled
continuation-settlement disk helpers are removed; live budget validation,
guard patch construction and guard reading remain.

The current Adapter's in-process generation fence, exact Backend
boot/authority check, and business `outcome_unknown` handling remain.
Historical D15 qualification still targets its separate old candidate image;
it is not a qualification of the selected `.238` image. The current release
identity still contains an unused `runtime_executor` subrecord; this slice
does not change the DSH release-identity contract.

## Historical evidence

The 0.9 containment observer now verifies historical Adapter source against
the exact Git blob at
`d4c6a9e34f531d27dd0e94804be6ed0aa6f9fde3`. Historical digests must
equal that pinned blob; current-file fallback is removed for those paths.
The step-safety design tests read the same pinned source for old Adapter
implementation claims. Neither old evidence nor its verdict was rewritten.

## Verification

- Historical evidence suites: 45 passed. Architecture: 74 passed.
  Build/retirement tests: 12 passed. Selected `.238` manifest check and
  `git diff --check`: PASS.
- A disposable `.238` Adapter image built successfully. Its embedded build
  identity was `dsh-0.1.5rc1-post-u8.238`; both removed modules were absent.
- In that image, five affected Adapter test files passed with 95 passed,
  10 skipped under the tests' session-process mode. The run used no network,
  a read-only container filesystem and a read-only test mount. The image was
  removed after verification.

The host Python lacked `httpx`, so Adapter tests were executed in the
declared-dependency image. No Compose services, database, user data, backup,
push, merge or deployment were changed by this slice.

## Gate scope

This evidence qualifies removal of disconnected disk persistence source.
It does not claim completion of Phase 7 as a whole or authorize Phase 8.
