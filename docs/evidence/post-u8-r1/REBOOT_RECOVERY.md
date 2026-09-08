# Production reboot recovery — 2026-09-08/09

## Authorization and scope

After a maintainer-triggered reboot, the operator reported failed autostart and
asked to restore production, then repair persistent restart configuration and
related health checks. Maintainer replied “允许”. This authorizes this bounded
recovery/configuration repair, not another host reboot, application-image upgrade,
data deletion, model calls, main push, PR merge or DSH rollback.

Base: `bc6d7f007478361789e80dc90014ac51d4169fd3`; branch
`fix/production-reboot-readiness`, isolated worktree `reboot-readiness`.
Product Phase and U8 historical status do not advance.

## Incident and immediate recovery

Host boot: 2026-09-08 23:47:38 Asia/Shanghai. Docker was active and enabled.
PostgreSQL, Backend, MCP, Runtime Adapter, frontend and signal sandbox had restart
policy `no`, so remained exited. Three workers with `unless-stopped` repeatedly
failed while dependencies were absent. Gateway and feedback relay were running.
All image IDs matched the deployed release; inspected `OOMKilled` flags were
false. Exit 137 alone was not classified as an out-of-memory event.

Closed admission, started the original containers in dependency order, verified
health, logged in with the existing synthetic account and read the two prior
G1/G5 public answers. Both persisted. Product reads, frontend HTTP and worker
running-state checks passed; admission reopened. No model calls or new research
jobs were made. All 11 current containers then received `unless-stopped` using
Docker's persistent configuration update, without recreation or restart. Exact
before/result receipts are private under `release-20260908T152238Z`.

## Source/configuration repair

- Compose now explicitly assigns `unless-stopped` to every persistent service;
  optional feedback publisher retains its profile and is not enabled by this fix.
- Backend Docker health probes both local HTTP and a bounded read-only SQL
  `SELECT 1`; exceptions exit nonzero without printing credentials/SQL errors.
- Gateway Docker health probes local HTTP, Backend, MCP and normalized Runtime
  readiness, all bounded. Frontend probes its local page and Gateway HTTP.
- These are **container-level checks**, not a claim that the existing HTTP
  `/readyz` endpoints implement exhaustive transitive business readiness. Overall
  acceptance must require all relevant container checks plus Product reads;
  neither a single HTTP 200 nor Gateway alone proves database health.
- `depends_on` controls Compose startup, not Docker daemon boot order. Restart
  policies supply recovery during boot dependency races; unhealthy alone does
  not trigger a Docker restart. `unless-stopped` deliberately respects a manual
  stop, which operators must account for before a reboot test.

The private `reboot-recovery.compose.json` is a supplemental configuration-only
overlay, composed **after** the historical `target.compose.json`. It contains
restart policies and three health checks only. Never replace historical target,
preparation or `.15` manifests, and never deploy with unpinned default images.
Production remains the tested `.15` application images / DSH 0.1.2rc1; new `.16`
identities cover the changed repository/Compose inputs for CI, not an implicit
production runtime upgrade. Future source deployment must use its normal merge
and exact-artifact qualification gates.

## Evidence and limits

Three new tests exercise restart coverage and actual probe code with healthy,
missing-dependency, invalid JSON, Runtime-not-ready and database-failure cases.
Read-only probes passed against the exact current production images. Separate
network-none, volume-free Backend/Gateway containers returned exit 1 without
output when dependencies were absent, then were removed. A separate isolated
container using `unless-stopped` automatically restarted after a synthetic process
exit; its exact test container was removed. This is not a host reboot test.

First CI invocation was blocked by immutable `.15` input drift; no tests qualified.
New `.16` manifests preserve all historical files. The second invocation found an
existing test's broad `assertNotIn("production", serialized_manifest)` matching
the operator worktree name `production-reboot-readiness`, not a leaked resource.
It was deliberately terminated through its cleanup trap (exit 143); independent
cleanup verification passed. The worktree was renamed to `reboot-readiness`,
with no test-assertion weakening or source/inventory change. Its replacement CI
scope is `local-reboot-readiness-final-20260909`; **exit 0, all 26 checks PASS**.
Architecture 228; Backend 499 passed / one skipped / seven subtests (526.44s);
candidate 153 passed / 23 skipped and 20 real-process tests; frontend 175 unit,
20 mocked browser and nine real Product browser journeys. Restart persistence
and two-user checks passed. Independent cleanup initially ran before the exit
trap finished and found its remaining CI network; after the main process exited,
independent verification passed. No broad cleanup or production deletion occurred.

Health-check overlay installation **PASS**: drained before recreating only
Backend/Gateway/frontend with the original `.15` images. The other eight
containers retained their IDs and start times. All 11 restart policies verified.
Final installed-probe, synthetic login and read-only Product checks passed; the
two synthetic answers' IDs **and full content** matched the pre-reboot evidence.
Admission reopened. Model calls: zero. The private verification receipt records
boot ID `fa9ed650-7b3d-450c-990e-78846e5a0346`; the next actual reboot must have a
different boot ID and pass the same checks. Operations scripts passed syntax
checks; changed-document and diff hygiene checks passed. Source changes are
local to the isolated branch; no push, PR merge or main edit occurred.

A second full host reboot remains maintainer-controlled and unverified. Do not
report automatic host-boot acceptance until it actually occurs.

## Subsequent verification — 2026-09-09

The maintainer subsequently rebooted the host. Observed boot time was
2026-09-09 05:23:09 Asia/Shanghai, boot ID
`dca1f725-824b-4565-a2e9-0e23423016de`, different from the recovery boot above.
All 11 containers automatically started with their persisted restart policies;
the nine healthchecked containers were healthy. The read-only synthetic
persistence verification passed without paid calls or research replay.
This supersedes only the preceding pending-second-reboot status, not its history.

The later F7 postdeployment repair request explicitly authorizes development,
push/merge and production redeployment. Its independent `.17` identity and
pending release evidence are tracked in [provider routing repair](PROVIDER_ROUTING_REPAIR.md).
