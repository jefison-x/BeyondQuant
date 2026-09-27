# Phase 7 — live Product root across Gateway-only restart

Status: **bounded local PASS for an active root; overall Phase 7 OPEN**.

## Scope and isolation

- Source base: `c636c7c4` on `clean-break/runtime-simplification`. Test date:
  2026-09-27 (Asia/Shanghai). No push, merge or deployment occurred.
- Disposable Compose project: `byq-p7-root-4541ff7f56`; configuration and
  generated throwaway credentials were stored only under
  `/tmp/byq-p7-gateway-vcm3tfpw`. The resolved Compose configuration had
  project-prefixed, non-external volumes and networks, a private Gateway port,
  and `restart: "no"` for all five selected services. Backend used only the
  project's new `byq_domain` PostgreSQL database.
- Services: Postgres, Backend, actual Product MCP, Adapter with pinned
  `dsh-0.1.5rc1-post-u8.226`, and Gateway. A test-only Adapter PID 1 ran the
  normal application and a loopback scripted model provider. The provider
  requested the real `byq_agent_run_start` Product MCP tool before blocking
  the next root model request. It logged no token or message content.
- A generated test account logged in through Gateway Product API and received
  its Backend-owned personal workspace. Gateway Product API created the
  conversation and accepted the root turn. This is distinct from a fixture
  calling Adapter `create_session()` directly.

## Result

The host check waited for the `ROOT_PROVIDER_BLOCKED` marker, the exact root
row in the disposable Backend database with `status='active'`,
`authority_status='active'`, the current Adapter boot ID and no terminal
sequence/digest, **and** one active `quant_orchestrator` AgentRun joined to
the same root through `agent_runtime_registrations`. The latter proves the
Product MCP registration reached the Backend and was bound to this root.
Exactly two authenticated model requests occurred before restart: the
registration tool call and the blocked follow-up. The host then restarted
**only Gateway**. Adapter's container ID,
its boot ID, and Backend's authority epoch stayed unchanged; Gateway regained
Agent readiness. The original root and AgentRun rows stayed identical. A
second turn on the same Product conversation returned **409** from the
Adapter prompt route, without creating another root or making another model
request. The normal Adapter process, Backend, Product MCP and Postgres remained
running.

```json
{"authority_status":"active","boot_unchanged":true,"competing_turn_status":409,"epoch_unchanged":true,"project":"byq-p7-root-4541ff7f56","provider_calls_unchanged":2,"result":"PASS","root_id":"76479f651be44b59866d6dfe3a5a4c86","root_status":"active"}
```

Two setup attempts were **not** counted as PASS. The first used a Product Token
without a durable user workspace and received 503 at conversation creation.
The second blocked the first model request before `byq_agent_run_start`, so no
Backend root existed. The final run used a real test user and an actual Product
MCP registration before blocking the provider. An intervening run passed the
weaker active-root checks, but did not count every provider request or assert
the AgentRun registration row; its result was superseded by the stronger final
run above.

The exact project was taken down with `--volumes --remove-orphans`; its four
project-tagged images and temporary credentials directory were removed.
Filtered Docker checks found zero remaining project containers, volumes,
networks and images. No existing database, user data or backup was touched.

## Reproduction and limit

The checked-in [Compose overlay](../../scripts/evidence/phase7-gateway-restart.compose.yml),
[provider fixture](../../services/runtime-adapter/tests/phase7_compose_gateway_root_probe.py),
and [fail-able host check](../../scripts/evidence/phase7-gateway-active-root-restart.py)
require generated disposable credentials, project-prefixed resources, the
selected base `compose.yml` and `compose.override.yml`, and only the five
services above. The host check requires an exact `byq-p7-root-<10 hex>`
project, a local project PostgreSQL URL, pinned DSH build, private Gateway,
and non-external project-prefixed volumes/networks.

This proves same-boot Gateway-only restart with one **active** Product root in
the qualified Compose topology. It does not prove an unknown-outcome root,
normal terminal close, lost-response retry, or recovery after Adapter/DSH
process loss. A rejected competing turn can still leave a saved user message;
the check asserts no second Agent root or provider request. Those remaining
paths and removal of the old Adapter journal/Gateway lifecycle replay require
separate tests and the full Phase 7 gate before Phase 8 can start.
