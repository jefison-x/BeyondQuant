# Historical SDK 322 closure review

**Functional: limited PASS. Tests: limited PASS. Clean Break Architecture: limited PASS.** I reviewed only the three frozen files against `/tmp/acp-historical-sdk322-backup-20261010`; I did not run tests or Docker.

`build_revision.py:23-24` removes the untracked 323 registration while retaining the exact frozen 322 hash. `selected_build_id()` at lines 184–193 now selects frozen 322 for the historical `dsh-0.1.5rc1` tooling; it does not qualify current ACP source. The tests compare frozen stored bytes against a current-tree render and require them to differ. The 322 manifest and Dockerfile hashes are `ee97823…` and `dc87eeb…` respectively.

The three changed files are absent from the unified image's 91 captured build inputs, and the current ACP resolver and release paths do not call `build_revision`. No current runtime capability or Product privilege was added. The frozen v090 upgrade verification and its tests remain relevant because they check old promotion snapshots; this narrow correction does not exclude them.

The [independent Tester receipt](/tmp/acp-historical-sdk322-test-20261010/result.json) records seven focused tests passed in 1.35 seconds, plus compile and `git diff --check` exits of 0. All three source hashes and frozen 322 artifact bytes matched before and after; the four untracked 323/324 candidate files retained their hashes and `?? <path>` statuses. The retained [initial calculation](/tmp/acp-historical-sdk322-test-20261010/result-initial-calculation.json) marked candidate stability false only because its summary predicate compared each full porcelain status with the literal `??`. The final receipt corrected that calculation from the same captured data without rerunning tests or changing the qualification condition.

Minor test hygiene: [test_current_build_revision.py](/home/jefison/projects/.byq-worktrees/dsh-acp-single-version/tests/test_current_build_revision.py:278) repeats the same `COPY` assertion at lines 278–283. The following exact Dockerfile hash assertion still provides the intended byte-level guard.
