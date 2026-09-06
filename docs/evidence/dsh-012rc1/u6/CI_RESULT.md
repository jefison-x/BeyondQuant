# Final retained-artifact CI result excerpt

Scope: `local-u6-artifacts-20260906`; image-producing commit
`25ded009dd1decc019e012ac47c0645b9621a2ca`. This is a selected result-line
excerpt, not the complete stdout or raw dialogue. Final shell exit: 0; cleanup
verification: PASS. Later operator/probe tests are recorded separately.

```text
{"build_id": "dsh-0.1.1rc1-u6.3", "manifest_hash": "sha256:bc84ddeff4851d90541008a5baf0507840f374cd160bc2b16853b882a6837c1f", "status": "PASS"}
{"build_id": "dsh-0.1.2rc1-u6.3", "manifest_hash": "sha256:c76bff7fd0dd4189c02cddf77777d1812a98bf74bd07e630308d8622868bf0a6", "status": "PASS"}
==> build: selected run-scoped images (cache allowed, stale fallback forbidden)
==> hygiene: git diff --check
    [PASS] git diff --check
==> docs: changed Markdown links and structure
docs check passed: 7 changed Markdown file(s)
    [PASS] docs checks
==> architecture: unittest
Ran 175 tests in 2.426s
OK
{"build_id": "dsh-0.1.2rc1-u6.3", "manifest_hash": "sha256:c76bff7fd0dd4189c02cddf77777d1812a98bf74bd07e630308d8622868bf0a6", "status": "PASS"}
    [PASS] architecture tests
==> backend: pytest against clean postgres
==> postgres: creating clean CI instance (byq-ci-postgres-local-u6-artifacts-20260906)
331 passed, 1 skipped, 1 warning, 7 subtests passed in 328.26s (0:05:28)
    [PASS] backend tests
6 passed in 1.12s
    [PASS] feedback publisher fake-GitHub tests
2 passed in 0.07s
    [PASS] feedback hub relay tests
==> central feedback hub: Cloudflare workerd tests and deploy dry-run
 Test Files  1 passed (1)
      Tests  15 passed (15)
    [PASS] Cloudflare feedback hub tests and bundles
==> gateway: pytest (mocked backend)
91 passed, 1 warning in 1.26s
    [PASS] gateway tests
==> runtime-adapter: pytest
77 passed, 2 skipped, 3 warnings in 0.78s
    [PASS] runtime-adapter tests
==> runtime-adapter: real 0.1.2rc1 candidate qualification
==> backend: starting live MCP contract dependency (byq-ci-backend-local-u6-artifacts-20260906)
7 passed in 11.63s
    [PASS] candidate real-process, five delegates and old/new lifecycle benchmarks
==> mcp: npm test (tsc build + in-container server + contract tests)
    [PASS] mcp tests
==> frontend: npm ci + build + vitest (locked local node toolchain)
    [PASS] frontend locked install
    [PASS] frontend build
 Test Files  51 passed (51)
      Tests  150 passed (150)
    [PASS] frontend unit tests
    [PASS] frontend dependency audit
  20 passed (1.1m)
    [PASS] frontend mocked UI e2e
==> smoke: isolated full compose stack
    [PASS] full smoke
    [PASS] unconfigured non-root feedback publisher
    [PASS] Phase 67 validated index fixture
    [PASS] Phase 70 multi-index catalogue fixture
    [PASS] Phase 68 dynamic inputs fixture
    [PASS] Phase 74 LightGBM fixture
  9 passed (51.3s)
    [PASS] real Product API browser smoke
  "status": "passed",
  "status": "passed",
    [PASS] Phase 74 restart persistence and two-user isolation
  "status": "passed",
  "status": "passed",
    [PASS] Phase 90 feedback restart persistence and two-user isolation
  "status": "passed"
    [PASS] Phase 48 no-mock two-user Product coherence
{"stage": "u6-artifacts-retained", "scope": "local-u6-artifacts-20260906", "image_count": 7, "archive": {"name": "images.tar", "bytes": 461490176, "sha256": "sha256:c50628332acd52441647e3baba083f5f4b8a206f98a65a1b19d38c8eac781c5a"}}
Local CI: all 26 checks passed
```
