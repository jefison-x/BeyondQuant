# Dependency security remediation — 2026-09-05

## Scope

This maintenance change resolves all 16 Dependabot alerts that were open on
`main` after source publication. The alerts collapse to four dependency
upgrades; no Product capability, DSH release, database schema, production
configuration, or deployment path changes.

| Dependency | Previous | Remediated | Alert coverage |
| --- | --- | --- | --- |
| `cryptography` | 45.0.6 | 50.0.1 | #1–#3 and #5, #7–#9 (4 high, 2 medium, 1 low) |
| `setuptools` | 80.9.0 | 83.0.0 | #6, #11, #13, #16 (medium) |
| `pytest` | 8.4.1 | 9.0.3 | #4, #10, #12 (medium) |
| `qs` | 6.15.3 | 6.16.0 | #14–#15 (medium) |

The Backend and Feedback Publisher `cryptography` declarations are aligned so
the Docker-only publisher pin cannot silently remain vulnerable. All four
Python build-system pins and all three test pins are aligned. Generated legal
dependency inventories and the prominent third-party notice were refreshed.

## Verification

- PyPI and npm registry metadata confirmed every chosen version exists and is
  compatible with the repository's declared Python/Node ranges.
- `npm audit --omit=dev`: 0 vulnerabilities for the updated DSH runtime lock.
- Architecture/governance: 125 tests passed, including three dependency
  security regression tests.
- Risk-selected local CI: all 25 checks passed using run-scoped images built
  from this commit.
  - Backend: 327 passed, 1 skipped, 7 subtests passed.
  - Feedback Publisher: 6 passed; Feedback Hub Relay: 2 passed.
  - Cloudflare Hub: typecheck, 15 Vitest tests, 4 deploy tests, two dry-runs.
  - Gateway: 86 passed.
  - Runtime Adapter: 3 Node tests and 66 Python tests passed; DSH remains
    `0.1.1rc1`.
  - MCP: complete TypeScript contract suite passed.
  - Frontend: build, 148 unit tests, 20 mocked browser tests and 9 real Product
    API browser tests passed; dependency audit reported 0 vulnerabilities.
  - Full Compose smoke, ML restart persistence, feedback restart persistence,
    owner isolation and Product coherence passed.
- Scoped cleanup: `security-upgrade-local-1` resources verified at zero.
- `python3 scripts/ci/license-inventory.py --check` and `git diff --check`
  passed.

The GitHub Dependabot alert state is rechecked after merge because alerts are
evaluated against the default branch, not an unmerged feature branch.
