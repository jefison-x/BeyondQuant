# Default/CI/Release source checkpoint — 2026-10-09

## Scope and Root conclusion

Finish the current bounded configuration/CI/release-cleanup source slice, preserve all existing work, and hand off to a new conversation at the maintainer's request. This is not overall ACP qualification or production acceptance. No broad Full, current-source image rebuild, paid model call, live cleanup, push, PR, merge or deployment occurred in this checkpoint.

- Default routes/build/dev/Makefile use the canonical ACP resolver and overlay; fixed official rc.2/qualified OpenCode Go route, explicit trusted Workspace leaf, missing configuration rejects startup. Legacy SDK session data/images/rollback remain retained; online mount removed. Source review PASS; fresh onboarding NOT_RUN.
- CI/Release/manifest share 17 self-built images /18 Compose services; exporter validates captured immutable IDs before archive, receipt/SBOM/Promote match. All17 actual build/Full/export/publish NOT_RUN.
- Cleanup includes ACP judgment network and six named volumes; canonical Compose helper best-effort then exact-label fallback handles missing secrets. Exact residue fails verification. Foreign tags and any RepoDigest retain shared image IDs. KEEP_POSTGRES retains dedicated test PG resources. No real cleanup executed.
- Independent Reviewer: Functional / Clean Break Architecture bounded PASS; focused-test evidence only. Review corrected two findings: missing ACP cleanup inventory and digest-only foreign image reference protection. Both repaired and regression assertions reviewed.
- Worker prior focused results: merged Compose6/6, dev16/16, Release22/22, initialgovernance5/5; finalcleanup6/6. These are distinct runs with overlapping cases, not one combined unique count.
- Final independent Tester result recorded below after completion. Root source PASS is bounded by this narrow evidence; release/default promotion remains closed.

## Remaining qualification / failure boundaries

- The ACP background-completion Product/Worker release fixture is missing. Full intentionally blocks before export; old SDK fixture is not ACP evidence. NOT_RUN.
- Current runtime selector/privacy source is not baked into a qualified image; prior source-build image9112 has older runtime. Judgment runner and actual17-batch qualification NOT_RUN.
- Existing real cancellation/new-child core/UI PASS is retained; strict entire-root single-read trial FAIL (child+parent two reads) remains unchanged. Lost-process recovery ADR0104 remains unaccepted/paused.
- Gitleaks8.30.1 final snapshot gate **FAIL**, exit1/35 candidate findings/407 files. Candidate findings concentrate in recorded source/image hashes and test fixtures; individual triage is OPEN, no false-positive or real-secret assertion. No raw matched contents are included here. History scan NOT_RUN. This forbids claiming overall release safety PASS.

## Frozen artifacts

- Branch `codex/dsh-acp-single-version`, HEAD `2d5810973240c5d7692569319c2b5ab337ae2082` + preserved working changes. origin/main/merge-base `f753eb27157228e8d3d594203878f55ab2c7a53e`; upstream-only0/branch29.
- cleanup SHA256 `3b56a5c7dff6201e2a8c80814e742119ae69e8f6203d43b753546e99b2a1e0d0`.
- governance tests SHA256 `430177136828d939be703d9326463ec9ab4d2ce20d2f03e65d483d7ffd90acbc`.
- Worker final logs `/tmp/byq-acp-release-batch-reviewfix-repodigest-20261009/test-cleanup-focused.log` and `test-repodigest.log`.
- Private secret scan snapshot/log/report `/tmp/byq-acp-frozen-scan-20261009/`; public copy only includes rules/files/line metadata and summary. Scan covered changed/untracked source at the freeze before adding this checkpoint/handoff documentation, not all Git history or subsequent docs.
- Final `git diff --check`, source-hash freeze checks and shell syntax PASS. No source commit created.

## Final independent Tester and Root

Final frozen selected set: **28 explicit test methods PASS**, plus **9 unittest subtests PASS**, exit0. This is a bounded final combination, not the complete earlier Compose6/dev16/Release22 suites. Freeze hashes before/after matched. Exact nodes/log/receipt copied alongside this document. No daemon/container/build/pull/live cleanup/provider/model/publication path ran. Independent Reviewer corrected-cleanup/source verdict PASS. Root: **bounded source/config/cleanup checkpoint PASS; overall release NOT_READY**, with secret-scan FAIL/triage OPEN and Full/current-source images NOT_RUN.
