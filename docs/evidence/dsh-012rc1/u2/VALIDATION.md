# U2 Web evidence producer provenance

Status: VERIFIED locally; GitHub checks and merge must be confirmed separately. Date: 2026-09-06.
Worktree: /home/jefison/projects/.byq-worktrees/dsh-u2-evidence-provenance.
Branch: refactor/dsh-u2-evidence-provenance.
Observed base: cffab34d547a1ffaae827560fced3fabda335bee (after environment PR #252).

## Authorization and scope

The maintainer authorized development, pushing and merging in the Windows remote
development session. Existing U1-U8 sequencing and ADR-0015/0059 checks apply.
Production deployment and default release promotion are outside this task.

Default DSH remains Python 0.1.1rc1 / npm 0.1.1-rc.1. Candidate policies do not
qualify or activate DSH 0.1.2rc1. Product Phase 97 is unchanged.

## Implementation and boundaries

- Generate bounded read-only policies from the existing release descriptors,
  deployment identity and qualified plugin registry. Backend/MCP consume only
  the safe projection; neither imports DSH nor reads raw Cordis.
- MCP supplies its active producer when commands omit internal provenance.
  Matching legacy fields remain accepted; a caller cannot select another
  recognized version or an unknown version.
- Policy consumers require the entire active producer record to match a
  recognized record, including release and attestation identity. A qualified
  policy rejects candidate entries.
- The persisted web-research-evidence.v1 schema, source/claim/time/usage rules,
  content hashes, owner isolation and atomic save remain unchanged.
- Candidate policy supports old/new evidence writes only in an explicitly
  isolated candidate context. Withdrawing it rejects new candidate writes;
  historical artifacts remain readable with unchanged content and hash.
- CI mounts both policy fixtures outside the backend source bind mount, avoiding empty host placeholders.
  Real MCP write tests provision a real user/workspace in the isolated CI DB.
- The architecture source scan excludes installed node_modules and Python
  bytecode, while continuing to inspect all BYQ application files, including
  untracked files. Third-party SDK install documentation is not application
  online-install behavior.

Community research evidence tests and research ledger contracts were inspected
read-only and classified REFERENCE_ONLY in the migration inventory. No Community
implementation was copied or changed.

## T08-T11 evidence

| Requirement | Evidence and layer |
|---|---|
| T08 immutable evidence | Backend validation checks byte/hash stability (L0); API history read compares stored content/hash before and after candidate withdrawal (L2). |
| T09 trusted producer | Python/TypeScript policy integrity and forged/cross-instance producer rejection (L0/L1); live MCP save injects the current version without model input, accepts matching legacy input, rejects forged versions and preserves idempotency (L2). |
| T10 rolling policies | Real PostgreSQL API saves old and candidate evidence under candidate policy, then withdraws it; both remain owner-scoped and readable while candidate writes fail (L2). |
| T11 domain invariants | Full backend web-evidence/API and Agent suites preserve temporal/source/usage and owner boundaries; injected artifact failure verifies transaction rollback after task insertion (L0/L2). |

Three policy integrity assertions were observed failing before their correction.
The first integration run exposed command-fixture and workspace-fixture mistakes;
both were corrected without weakening the production validation boundary.

## Validation runs

1. Full changed-component local CI:
   `scripts/ci/local-ci.sh --base=origin/main --with-e2e --auto-smoke`.
   Scope `local-3280621`; sanitized log:
   `/tmp/byq-dsh-u2-verification/local-ci-stable.log`.
   24 checks passed; smoke initially failed because its new MCP write test lacked
   a real workspace. All component suites passed: architecture 139, backend 331
   (1 skipped, 7 subtests), Gateway 86, Runtime Adapter 67, complete MCP suite,
   frontend 148 unit tests, 20 mocked browser tests and 9 real browser tests.
   The existing backend skip is retained, not counted as passing.

2. After adding the same real workspace fixture to the smoke entry point:
   `scripts/ci/local-ci.sh --base=origin/main --only=architecture,mcp --with-smoke`.
   Scope `local-3320814`; sanitized log:
   `/tmp/byq-dsh-u2-verification/integration-final.log`.
   Exit 0; all 13 checks passed, including full MCP, full Compose smoke,
   9 real Product API browser tests, Phase 74/90 restart persistence and
   two-user isolation, and Phase 48 no-mock Product coherence.
   Production code was unchanged between these two runs.

3. Final evidence/status documentation and its phase assertion are checked
   again with the docs/architecture lane before commit.

Earlier diagnostic runs exposed fixture/response-parser mistakes. One run was
interrupted after editing its executing CI script disrupted shell sequencing;
it is not treated as final evidence. Final runs kept executable source fixed.
All final scoped containers/networks/volumes were removed. Existing
`beyondquant-*` services retained their prior uptime and health.

No remote CI or merge result is claimed in this pre-PR record. Verify the PR
head, required checks and merge from GitHub rather than inferring them here.

## Limits

These tests use synthetic research evidence and real isolated services/storage.
The unchanged old DSH lifecycle is exercised by the keyless Compose smoke.
No live-provider search or paid model evaluation was run. Candidate policy tests
do not prove the new DSH runtime has been adapted or qualified; that remains U4/U5.
No production services or domain data were deployed or migrated.
