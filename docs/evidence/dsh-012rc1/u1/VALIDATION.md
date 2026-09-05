# DSH 0.1.2rc1 U1 release identity and isolation evidence

Date: 2026-09-06 (Asia/Shanghai)

Scope: U1 engineering validation from `origin/main` commit `c936956` after PR #250 merged.
This report does not qualify the new runtime, change the default release, authorize U2, or record a
production deployment. The default remains Python `0.1.1rc1` / npm `0.1.1-rc.1`.

## Release inputs

- The closed `dsh-release.v1` schema registers only `dsh-0.1.1rc1` and `dsh-0.1.2rc1`.
- `deployment.json` selects only `dsh-0.1.1rc1`; `dsh-0.1.2rc1` is a candidate.
- Candidate SDK and Linux x86-64 runtime wheels were downloaded from exact PyPI release metadata
  and re-hashed as `24689e...0488a` and `670d8a...87d` respectively.
- The SDK metadata exact-pins `deepseek-harness-runtime-bin==0.1.2rc1`.
- Official source commit `a66e4702047846cdaa10c66c9d3df3951f5ea70d` was downloaded by exact
  commit URL. Its archive hash is `adf32f...6552`; the bundled runtime manifest hash is
  `a8cdf9...9387`.
- The generated CycloneDX 1.6 source inventory contains all 123 packages named by that manifest;
  its deterministic hash is `7e6e85...9dec`.
- The candidate Python lock contains seven exact runtime dependency packages and artifact hashes.
  An isolated Python 3.11 container installed the two verified wheels, resolved those exact seven
  packages, and `pip check` reported `No broken requirements found`.

## T01-T07

| Test | Result | Evidence |
|---|---|---|
| T01 | PASS | Exact registered PyPI artifacts, platform wheel, source commit/archive, manifest and SDK/runtime pairing were downloaded and hash-checked; unknown release has a negative test. |
| T02 | PASS | Closed top-level and carrier-specific schemas reject missing fields, unknown carrier/compatibility family, path escape, missing release and mixed Python lock. |
| T03 | PASS | Default and candidate identities are deterministic generated files; release-specific generation is byte-identical; stale-output check is read-only and fails. |
| T04 | PASS | The accepted 78-package npm closure remains exact. Tests reject mixed top-level and nested DSH prereleases and incompatible DSH peer requirements. Actual `npm ci --omit=optional --ignore-scripts` completed without force. |
| T05 | PASS (U1 scope) | Candidate wheel hashes, seven-package Python lock, 123-component source SBOM and isolated installed metadata agree; `pip check` passed. npm audit reported 0 vulnerabilities across 286 dependencies. Candidate image-installed comparison remains an explicit U4 gate after the candidate adapter/profile exists. |
| T06 | PASS | Registry validation derives the selected release version from generated deployment identity; existing qualification remains bound to the old release and was not copied to the candidate. Registry validate/build-check passed. |
| T07 | PASS | Default image reports installed SDK/runtime-bin `0.1.1rc1` with matched identity. A deliberately mismatched image carried candidate identity but installed old packages and reported `release-identity-mismatch`, never ready. An unknown identity source failed the Docker build rather than falling back. Run-scoped CI resources and temporary candidate resources were removed. |

## Regression and integration

- `python3 -m unittest tests.test_dsh_release tests.test_dsh_upgrade tests.test_dsh_plugin_registry`:
  25 tests passed in the final targeted run.
- `python3 scripts/dsh/release.py check`, Plugin Registry validate/build-check and
  `git diff --check`: passed.
- `scripts/ci/local-ci.sh --base=origin/main --only=architecture,runtime --with-smoke`:
  all 13 checks passed using run scope `local-2985011`.
- Architecture: 135 tests passed.
- Runtime Adapter: 3 Node tests and 67 Python tests passed; two existing FastAPI lifecycle
  deprecation warnings remain.
- Old runtime initialize, MCP, lifecycle, owned-child cleanup and persistent-session-volume smoke:
  passed.
- Real Product API browser smoke: 9 Playwright tests passed.
- Default Runtime image identity: `sha256:050f0878a2ee803e3d00c40136a823bebdff3b10bd309aafd995bd382cf5bca1`.
- Negative mismatch image identity: `sha256:77c58eaf6c331311f66441502add6cb5cd30e3050b1b7ce94f1046359058a21a`;
  it was deleted after the assertion.

## Boundaries and cleanup

No live-model or paid-model test ran. No Product source, business logic, tool roster, event semantics,
timeout, production configuration, database, credential or session volume was changed. No candidate
was marked QUALIFIED or Active. U2 and production switching remain unauthorized.

The run-scoped compose containers, networks, volumes and images were absent after cleanup. The
download/SBOM directory and deliberately mismatched image were deleted; only this non-secret summary
and deterministic controlled inputs remain in Git.
