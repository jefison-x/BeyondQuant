# Phase 7 isolated Compose authority evidence

Status: local candidate evidence, **Phase 7 gate remains open**. No push, merge,
deployment, or operation on an existing database, user data, or backup occurred.

## Scope and isolation

- Source base: `599c9e84` (`clean-break/runtime-simplification`). The three
  verified code/test corrections were committed as `94e9db06`. Test date:
  2026-09-27 (Asia/Shanghai).
- Disposable Compose project: `byq-p7-706de598c8`. The explicit env/override
  files were created under `/tmp/byq-p7-authority-dfitk6yj` with generated
  throwaway credentials. Compose config showed unique project-prefixed volumes
  and networks, no published Gateway port, and `restart: "no"` for the five
  selected services. `BYQ_POSTGRES_VOLUME_EXTERNAL=false`.
- Services: Postgres, Backend, Product MCP, Runtime Adapter, Gateway. The
  resolved Adapter Dockerfile was
  `services/runtime-adapter/Dockerfile.post-u8-226-candidate`; the container
  reported build ID `dsh-0.1.5rc1-post-u8.226`. Docker reported private/default
  PID namespace, user `byq`, restart policy `no`; `/proc/1` was
  `python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8400`.
- The Backend test connection targeted only `byq_domain_test` inside the
  disposable project Postgres. Product-stack synthetic rows targeted only its
  separate disposable `byq_domain`. No pre-existing Docker container was
  running before this project was started.
- After testing, exact-project `docker compose down --volumes --remove-orphans`
  removed all five containers, four created named volumes and the project
  network. Filtered Docker checks found zero remaining project containers,
  volumes and networks. The four uniquely tagged project images were also
  removed; shared base images and unrelated resources were retained.
  The `/tmp` test env/override directory with throwaway credentials was removed.

## Executed checks

| Check | Result | Evidence and limit |
|---|---|---|
| Four service image builds | PASS | Backend, MCP, Adapter and Gateway built from the isolated branch. MCP initially failed TypeScript inference in a test; an explicit `number` annotation fixed it, and rebuild passed. |
| PostgreSQL authority and API tests | PASS | `tests/test_runtime_authority_rotation.py` plus `tests/test_runtime_authority_api.py`: 6 passed. Covers claim/rotation serialization, active and pending revocation, unknown executing claim, exact terminal retry, malformed/stale boot, and human decision. Initial run exposed stale test context and a real approval route `workspace_id` bug; both were fixed before the passing rerun. |
| Pinned DSH foreground delegate qualification | PASS | Existing `test_dsh015_foreground_child_process.py` ran in a disposable one-off container from the pinned Adapter image with the test directory mounted read-only: 3 passed. It uses loopback synthetic MCP/provider and does not replace the live Compose PID 1 kill check. |
| Real pending-action approval regression | PASS | `test_approval_decision_and_action_roll_back_together` and `test_human_approval_decision_advances_the_plan_through_the_business_action` ran against the same disposable test DB: 2 passed. This closes the reviewer's narrower concern about a mocked decision path. |
| Adapter SIGKILL with no active DSH turn | PASS | Adapter stopped under `restart: "no"`; Gateway `/agent-readyz` returned 503. After Adapter restart, boot changed and Backend authority epoch advanced 1→2. Gateway-only restart preserved that boot and epoch and returned 200. This check alone does not prove child process death. |
| Live pinned foreground child, Adapter PID 1 SIGKILL | PASS with limit | A test-only Python PID 1 ran the normal Adapter app and pinned DSH SDK in the disposable Compose Adapter. Its scripted loopback provider held the real foreground child after a `subagent.started` notification; DSH MCP initialize/tools-list traffic was observed. `docker top` showed PID 1 plus the pinned `deepseek-harness-sdk-runtime` process. After Adapter SIGKILL, Docker exit code was 137, both recorded host PIDs disappeared, and Gateway `/agent-readyz` returned 503. The normal Adapter was restored and Gateway/Backend boot matched at epoch 6. The synthetic MCP endpoint lived inside the killed container, so this does **not** independently prove absence of a late request at Product MCP. |
| Vertical revocation with synthetic active authority | PASS | Synthetic active root, active AgentRun and pending AgentRun were inserted only in the disposable product DB. After Adapter SIGKILL/restart and Gateway boot sync, all three had `authority_revoked_unconfirmed`; the boot ID changed. These rows were synthetic, not an actual DSH turn. |
| Backend outage admission | PASS | While the disposable Backend container was stopped, Gateway `/agent-readyz` returned 503; after Backend restart it returned 200. |
| Local syntax gate | PASS | `python3 scripts/ci/dev-check.py --base 599c9e84`: local syntax PASS; component tests NOT_RUN by that script; remote CI REQUIRED. `git diff --check` passed. |

## Still required for the Phase 7 gate

- Complete the live child boundary with an independently observed Product MCP
  call/counter that stays unchanged after Adapter PID 1 death. The loopback
  child probe above proves the pinned child and process death, but the loopback
  MCP server dies with Adapter and cannot observe a late Product MCP request.
- Prove same-boot Gateway-only restart while a real root remains active/unknown,
  plus exact normal terminal close and lost-response retry in the live path.
- Remove the generic Adapter journal and Gateway lifecycle replay/delivery only
  after their replacement vertical path passes. Inspect final diff/schema and
  run Tester → independent Sol Reviewer → Root acceptance. No Phase 7 PASS or
  Phase 8 resource cleanup is asserted here.

## Review and gate

The independent Sol Reviewer found the bounded source fixes and test-only
child probe consistent with the Clean Break boundary. The child probe records
failure in a daemon thread, so the host check must require the exact
`BLOCKED_CHILD_LIVE` marker; this run did. The still-live Product MCP counter,
active-root Gateway restart, terminal/retry path and legacy code deletion remain
open. **Root gate: Phase 7 OPEN; Phase 8 not started.**
