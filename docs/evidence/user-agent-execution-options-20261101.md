# User Agent execution options — 2026-11-01

Maintenance under the maintainer's explicit user-level settings direction and
the [ADR-0111 amendment](../architecture/adr/ADR-0111-automatic-continuation-execution-parameters.md).
Product Phase 17 remains OPEN. No official F6 provider qualification is claimed.

## Result and feature checklist

Application source: `8a7cf7541f31dd065f88b7bd01c3ebd1ca8bab68`, isolated branch
`codex/user-agent-runtime-settings`. Later test/document changes do not alter
the running application source. Independent Sol review and Root accept this
user-settings slice; this is local test-environment acceptance, not hosted CI.

| Feature | Result and evidence boundary |
| --- | --- |
| User-owned configuration | PASS: one user-ID/FK row with CAS; new and existing conversations read the same user configuration for subsequent execution. Backend database tests and Runtime source/contract checks. |
| Personal settings placement | PASS: `/user/agent-policy`, no conversation selector or administrator requirement; removed from system management. Ordinary durable-user browser login at desktop/mobile widths. |
| Persistence and user isolation | PASS: two new test-owned ordinary accounts, actual Gateway/Product API save, reload, independent peer read and exact-revision restoration. No fake login, local persistence or model/Job input. |
| Authorization and unknown outcomes | PASS: human/cookie/same-site/service gates, Runtime bearer read-only, token-misconfiguration rejection, inactive-user rejection, CAS conflict and no automatic PUT replay. |
| Existing executions and history | PASS: submitted/reserved execution snapshots remain immutable; old conversation settings are not promoted or consulted. Old write endpoints retired. |
| Workspace reset | PASS in isolated PostgreSQL: user configuration preserved; legacy conversation rows follow their existing archive rule. No reset was performed against the retained shared test database. |

Validation: Backend14, Gateway1, Runtime58, synthetic F6 contracts105,
lockfile-installed Frontend67, Frontend build, mocked desktop/mobile2,
architecture73 and real Product settings desktop/mobile2 passed. Original
failed attempts and the first Backend collection limitation remain in
`.ci-artifacts/user-agent-runtime-settings-20261101/`; they are not relabeled.
The real browser case was renamed after the successful run to distinguish
user-settings acceptance from real background F6; its behavior is unchanged.

Four necessary local test roles were updated from retained image bases.
Eight changed-source/build-file digests match running containers. Original
Runner/MCP container IDs, shared volumes, original admin identity and the
current browser page were retained; old four application containers remain
stopped with restart disabled. Test DB encrypted backup:701152 bytes,
SHA256 `c38578e87e4bb4b6a19618a7b5c523ff05f156cbc6292f2a9535fd987dc462e8`.
Key and test credentials remain private outside Git. Restore testing NOT_RUN.

Hosted branch CI, push/PR, merge, trusted release and operating-stack deployment
are NOT_RUN. Current-ACP real background F6 remains a separate open gate;
settings browser checks and synthetic F6 do not close it.
