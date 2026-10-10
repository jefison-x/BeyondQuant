# Current-source architecture discovery and selected failure recheck

## Scope and source identity

2026-10-10, existing isolated `codex/dsh-acp-single-version` worktree, HEAD
`2d5810973240c5d7692569319c2b5ab337ae2082` plus preserved working changes.
This addresses the architecture evidence missing after the latest runtime,
CI and release edits. It precedes the subsequent external release-manifest v2
slice; it is not an adopting-commit or hosted CI result.

All four source inventories match: **1901 files**, inventory SHA-256
`a8ba138b9e64f7bb518f453f08f4745acc3fc42b924a47b6e12b1b38c11f6fbf`.
No code edits, build, Docker mutation, provider call, network install or F6 rerun
occurred in this verification. Worktree verification passed before and after.

## Runs and retained failure history

| Run | Result | Boundary |
| --- | --- | --- |
| Current architecture discovery | **FAIL** | `python3 -m unittest discover -s tests -p 'test_*.py'`: 1011 tests, 36.991 s, 981 passed, 11 skipped, 18 errors and 1 failure. Raw failed receipt retained. |
| Exact 19-case recheck | **PASS** | 19 passed, 92.675 s, correct actual-worktree write privileges, existing dependencies, `npm_config_offline=true`; unchanged source. |
| Reconciled local case coverage | **1000 passed / 11 skipped** | Combines the two receipts; not a single green discovery or Full CI run. |
| Adopting-commit architecture / hosted CI | **NOT_RUN** | Dirty worktree case coverage does not satisfy these gates. |

The 18 errors are cleanup test fixtures attempting to write to the actual
worktree under the read-only sandbox. The remaining failure is the historical,
keyless DSH 0.1.5rc1 native-resume harness subprocess exiting without its expected
output. It passed the correctly privileged, offline selected recheck with no
source change. That recheck establishes observed success; it does not prove an
exact causal mechanism for the subprocess failure. The original run remains FAIL.

The 981 successful cases and 11 skips were not repeated. Existing current-image
and local synthetic F6 evidence was reused. Root command-invocation corrections
(`verify-worktree.py` path/required argument) were preflight invocation errors,
not product failures; the final correct worktree verification passed.

## Evidence

`artifacts/postflight-and-test-summary.json` and `artifacts/unittest.raw.txt`
retain the first run; `artifacts/failed19-rerun-result.json` and
`artifacts/failed19-rerun.raw.txt` retain the recheck. Source inventories and
preflight/verification receipts accompany both. `artifacts/reconciliation.json`
records the local boundary explicitly. Independent Reviewer and Root give **limited local coverage PASS** while
retaining the initial FAIL and the unknown D15 failure cause. This is not
a single green Full/adopting-commit result and grants no release/default
adoption/deployment approval. The review receipt is retained in the subsequent
[public-manifest v2 slice](../acp-public-manifest-v2-20261010/RESULT.md).
