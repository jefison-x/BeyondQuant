# F6 default-on configuration maintenance — 2026-11-02

Status: **PASS for local default/opt-out contracts and the two-environment
configuration activation.** New hosted PR CI, merge, image publication and a new
operating real-model F6 chain are **NOT_RUN**. Phase 18 remains NOT_STARTED.

## Authority and minimal change

The maintainer explicitly requested both operating and development-test
environments default to F6 enabled, preserve user disable, existing data,
environment and current page, and not advance Phase 18. This implements the
already accepted defaults in [ADR-0111](../architecture/adr/ADR-0111-automatic-continuation-execution-parameters.md)
and keeps [ADR-0116](../architecture/adr/ADR-0116-official-deepseek-f6-qualification.md)
provider/profile qualification and actual-test scope unchanged.

`compose.yml` now defaults `BYQ_F6_EXECUTOR_ENABLED` to 1 consistently for Backend,
Gateway and Runtime Adapter; `.env.example` documents 1 and explicit operator
disable with 0. User-owned `auto_continue` still defaults true, while an existing
false setting blocks new automatic reservations across that user's sessions.
No user option is overwritten. CI's explicit flag 0 isolation remains unchanged.
There are no application-code, schema, provider or approval changes.

## Local validation

The new real merged-Compose interpolation case first failed because Backend
rendered 0 when the expected default was 1. After the fix the full Compose
module passed **4 tests**, including consistent default 1 and explicit override 0.
Its environment is synthetic and does not inherit host secrets.

An existing Backend image ran **9 tests** in the new isolated database
`byq_domain_test_f6_defaults_20261102`, on the retained test PostgreSQL instance.
Coverage includes typed/default options, durable user-scoped settings/API access,
automatic v3 reservation, user-disable blocking new reservations, and old
pending/unknown receipts blocking without mutation. Existing Product databases
were not reset. These are local database/contract tests, not model or browser
acceptance. `make dev-check` and `git diff --check` passed. Independent Sol review
passed source correctness, tests and Clean Break/authorization scope, reusing
Root's test execution rather than repeating it.

## Operating activation and preservation

The operating stack originally persisted flag 0 in its three private env files;
changing the repository fallback alone would not enable it. A new private
`enable-f6.compose.json` adds only flag 1 to the three services. Comparing complete
rendered configurations in memory proved that the only effective differences
were those three values. No resolved secrets were printed or stored.

The existing pinned Backend, Gateway and unified ACP image digests from the
[trusted release](maintenance-release-20261102.md) were reused. Gateway entry was
closed, then the live Runtime confirmed zero sessions/prompts and no held,
awaiting-ACK or awaiting-cleanup slots before the three-service update. Compose
used `--no-deps --no-build --pull never --wait`; all three returned healthy with
flag 1. Development-test already persisted flag 1 on all three healthy services
and was not restarted. No image was built, pulled, published or promoted.

Four existing operating Gateway context carriers required exact read-only
reconciliation. Each has valid owner/workspace tenancy but no durable conversation,
task, reservation or receipt watch. Backend peek returns waiting before claim or
model dispatch; receipt reconciliation fails on the absent conversation before
watch mutation. Their context file hashes remain unchanged; no cancel fence,
quarantine, migration or replay was introduced. Restoring old business data would
require a fresh reconciliation; this conclusion is limited to the current data.

After activation both environments read back **1/1/1** on Backend/Gateway/Runtime.
The other **93 containers** retained ID, image, health and mounts. Existing Product
users, execution-option rows, conversations and ResearchTasks retained their row
counts and content hashes in both databases. Volumes, networks and the original
env/release/rollback files are unchanged. Runtime is idle with matched release
identity and no held or awaiting slots. Neither frontend was replaced; no browser
navigation, reload or closure was performed.

## Persistent operator configuration and limits

Private evidence and the new overlay live under
`/home/jefison/.local/state/byq-maintenance/f6-default-on-20261102/`.
`operator-command.json` records the full enable and rollback Compose chains.
Future operating updates must use the active full config-file list, including
this override, or the recorded enable command. The original two-file chain and
private env files retain flag 0 as the intentional rollback baseline.

`RESULT.json`, `rendered-config-diff.json`, `runtime-entry-closed.json`,
`product-data-before.json`, `product-data-after.json`, `containers-before.json`,
`containers-after.json` and `user-opt-out-backend-tests.log` retain the actual
verification. The existing qualified real F6 evidence is reused only at its
original test scope; configuration activation is not a new operating real F6 pass.
Repository push/PR/merge remain separate from this explicitly authorized
configuration operation; source changes are initially handed off locally.
