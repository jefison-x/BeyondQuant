# Fresh isolated Gateway bootstrap — 2026-10-09

Root admission: PASS for login bootstrap only, not ACP Product qualification.
Fresh project: `byq-dev-c89ff732f2`; protected configuration stays under
`/tmp/byq-adr0109-qual-20261009-c89ff732f2` (directory 0700, env/cookie 0600).
No credential, cookie or raw Compose configuration is copied into this evidence.

Independent Reviewer found no startup blocker. Standard Gateway Dockerfile built
with `--network=none --pull=false` and all source steps matched the existing exact
`sha256:b40114c4aa71f0904726a74873ef672836ecf93ff1ac817cb31d007523e0b043`.
Backend is pinned to the newly verified candidate ID. All three services started
with no builds, no pulls and no implicit dependencies, against fresh volumes.
Only new-scope PostgreSQL/Backend/Gateway started; old `byq-acpf6` untouched.

Initial bootstrap stopped before seeding because this Compose version rejects
`run --no-build`. Removed that unsupported run-only flag: backend build definition
is reset and exact image is set; then the seed ran once successfully. No broad
retry or model request. Host `python` was unavailable during preparation; used
`python3`, without changing source or dependencies.

Real Gateway `/api/product/auth/login` and `/api/product/auth/me`: HTTP 200;
workspace IDs equal seeded fresh workspace. Protected environment now binds that
actual workspace. This verifies real durable cookie auth, not synthetic login.
Gateway aggregate health is expected not ready until Adapter/MCP join.

DSH/model/delegated tool/terminal ACK/actual process cleanup/browser: NOT_RUN.
External model calls: 0. No production/default promotion, push, merge or deployment.

## Independent runtime snapshot and model configuration

Tester independently confirmed exact 3 image IDs, fresh project labels and isolated
volumes/network, loopback ports, PG/Backend healthy, and old Adapter/Product runner
unchanged. Gateway Docker aggregate health currently **FAIL / unhealthy**: MCP and
Adapter are intentionally absent at this bootstrap stage. This actual observation
is preserved; successful login is not aggregate readiness PASS. Recheck only after
full candidate admission, not by weakening health checks.

Normal Gateway model credential creation: 201. Initial v4.1-flash profile creation:
422 (model absent in static catalogue). Readback confirmed credential active and no
profile: no duplicate credential write. Normal credential model discovery: 200,
exact requested v4.1-flash found, then profile creation 201 and binding update 200.
One provider model-catalog HTTP call; zero model inference calls. No model switch,
secret in evidence or credential copied from old candidate business storage.

## Full isolated candidate startup

Derived judgment-runner image: `sha256:1041f5fa002ebd24f7ff77f49fcbdad1af74c6d717f6176b52252c42b9d968cd`.
Offline build PASS; all 7 current BYQ file hashes + official commit and dependency lock
readback PASS (9/9). CLI existence checked by build RUN. No model/DSH started during
image readback, temporary readback container removed. This is a local derived
qualification candidate; clean-source release build gate is still not passed.

Independent Reviewer approved frozen startup commands conditional on this pin/readback.
Root then generated ready override exact ID/build reset and ran the frozen commands
only for the new scope. Startup exited 0, including Gateway aggregate Docker health.
Earlier unhealthy snapshot remains historical FAIL, not deleted. No consumer,
unrelated workers or model turn started. Full startup readiness does not prove
Model/Product/delegation/terminal ACK/process-cleanup acceptance.
