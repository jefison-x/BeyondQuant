# ADR-0061: U6 independent BYQ build identity

- Status: Accepted
- Date: 2026-09-06
- Scope: U6 operational build revision and requalification; no production deployment
- Acceptance: Maintainer explicitly authorized: “允许保留历史 release 描述、报告及失败测试不变，为 U6 新增独立构建身份并重新认证”.
- Related: ADR-0058, ADR-0059

## Decision

Keep historical release descriptors, generated release identities, U5 reports and
their failure assertions unchanged. Preserve the release-bound Dockerfiles and
candidate overlay as historical build inputs; rebuilding them requires their
matching historical Git tree, not current U6 application sources.

Add explicit U6 Dockerfiles and immutable build-revision manifests. Each revision
references the unchanged upstream release descriptor by hash and binds the
current BYQ build inputs separately. The old release remains the default; selecting
a BYQ operational build does not promote the candidate or grant plugin authority.
There is still one upstream release descriptor per release and no second agent
harness, Product control plane or automatic production upgrade.

Check both layers: release metadata and historical bound inputs remain valid;
the selected U6 build independently verifies its complete current source inventory
and hashes. Missing, extra, mismatched or cross-release build inputs fail closed.
Images embed the exact build manifest; operator evidence binds its hash to the
actual image ID. Do not rewrite a historical descriptor to make current code pass.

U6 qualification binds both baseline/candidate build manifest hashes in addition
to release/profile/policy/Git/image identities. Historical U5 evidence is historical
only and cannot satisfy U6 release readiness. Retain withdrawn-report failure
checks; add negative tests for build drift and reuse of old evidence.

Re-run affected builds, CI and isolated acceptance flows against these explicit
artifacts. Do not copy U5 QUALIFIED onto the U6 image. Production deployment,
default release promotion and observation remain separate authorization gates.

## Post-U8 scoped extension (2026-09-08)

The maintainer explicitly approved retaining historical records unchanged, adding
an independent Post-U8 build identity and requalifying the repair branch, then
pushing it to `jefison-x/BeyondQuant` and creating a Draft PR. This authorization
does **not** include merge, production deployment, release/tag creation, or
resuming historical research. Product Phase 97 and the deployed DSH version are
unchanged.

Apply the same two-layer verification to new `post-u8` operational revisions for
the compatibility baseline and current runtime. Historical descriptors, U6/U7
manifests, Dockerfiles and reports remain immutable. Verify historical inputs
against their exact archived Git source and current inputs against a new complete
manifest; missing history or current-source drift must fail closed. Historical
qualification is not qualification of the new image. Report incomplete Post-U8
business acceptance separately from build and deterministic test results.

## Retirement amendment (ADR-0069, 2026-09-10)

The maintainer accepted retiring the 0.1.1rc1 maintenance lane. New Post-U8 builds
are generated for 0.1.2rc1 only. Previous dual-build records remain immutable;
retired manifests are verified against their exact historical Git source and
never certify current application inputs.
