# U5 G6 isolation remediation — 2026-09-06

This supplements, and does not erase, the confirmed historical external delivery
in VALIDATION.md. The production Hub record was not modified. No production
deployment, default switch, publisher execution or GitHub Issue creation occurred
during this remediation.

## Closed test stack

`tests/dsh_upgrade/live_stack.py` generates a standalone closed Compose manifest,
without inheriting the deployment Compose or its environment. Eight explicit
services use unique `byq-u5-*` networks, images and volumes. Only the frontend
publishes loopback port 18210. Only Runtime receives the individually read model
credential; all other credentials and identities are synthetic. No production
database, Tushare credential or Hub/publisher credential is loaded.

Backend, MCP, Gateway, PostgreSQL, relay and fake Hub use an internal Docker
network. Runtime additionally has a model network; frontend has an ingress
network. The relay destination is fixed to `http://fake-hub:8800`. The fake Hub
has neither an outbound client nor a publisher, stores only receipt/hash metadata,
validates snapshot hashes and deduplicates delivery. Its counters are read within
its container, not through an exposed host port.

Before login, before each automatic approval and after completion, preflight
checks the closed manifest and actual healthy services, network attachments and
internal flags, credential fields, volumes, privileges and exact loopback ports.
Seven regression tests include production-environment poisoning, manifest mutation,
actual container drift, literal-only credential parsing, sink idempotency and
cleanup on startup/probe failure. The `run` entry point holds the heavy lock for
startup, the bounded G6 journey and finally-cleanup. The observed browser review
used explicit `up`/probe/`down` diagnostic controls; the new orchestration is
covered by deterministic failure-injection tests, not an additional paid rerun.

The first remediation startup had healthy internal services but Docker did not
actually publish ports on an internal-only network. The probe failed before login
or any model request. This scope was removed. The frontend-only ingress network
and in-container counter access corrected the setup; there was no model reroll.

## Real relay results

| Release | Scope | Approval / feedback / fake receipt | Continuation retries |
|---|---|---|---|
| 0.1.1rc1 | byq-u5-g6-old-rerun-20260906 | 1 / 1 / 1 | 1 |
| 0.1.2rc1 | byq-u5-g6-new-20260906 | 1 / 1 / 1 | 0 |

Both fake Hubs observed one intake attempt, one unique received snapshot and zero
publications. Other Product object counts remained zero. Exact bounded outputs
are in `g6-isolated-old.json` and `g6-isolated-candidate.json`.

The candidate deliberately waited 120 seconds before approval so Chrome MCP could
inspect the pending UI. Therefore its 132.986-second elapsed time and lack of a
continuation retry are NOT a paired performance/reliability improvement claim
against the immediate-approval baseline (43.796 seconds, one retry). The original
matched lifecycle benchmarks remain the performance evidence.

Post-run candidate preflight passed with Runtime local image identity
`sha256:c7c374ce01725c54e92fe7445f0680513715d8c324a0d3122426e8408d2e1d5e`
and frontend identity
`sha256:0628612e054113f509b92a0724529ac888fe98b958865386b256fff0a2c60b9f`.
These are local immutable image identities, not registry digests.

Both scopes were removed after evidence capture, each including eight containers,
four synthetic data volumes and three networks. Cleanup commands exited zero;
synthetic data volumes are deleted, not recoverable from these scopes. No
production resources were removed. Final keyless validation remains in progress
before regenerating qualification.

## Candidate Chrome MCP review and Community classification

The MCP browser used isolated context `byq-u5-candidate-review`, local URL
`http://127.0.0.1:18210`, and the synthetic durable `u5-admin` account. This was not
the user's authenticated Cloudflare browser. Product source was unchanged.

Community reference inspected: AgentView composer and GlobalApprovalCenter
template, with the existing Phase 65/91/92 feature classifications. Approval
badge/inbox, conversation attribution and responsive interactions are PORT_UX;
coupled approve-and-execute/raw backend/private runtime access remain DROP.
Plugin Center is REPLACE/PORT_LAYOUT, not a Community runtime installer port.

| Feature | Candidate observation |
|---|---|
| Durable login and Xiaoba | Login through Gateway succeeded; existing synthetic conversation and real model progress appeared. |
| Pending approval | Desktop 1440×1000 and mobile 390×844 showed one global inbox item, feedback title/context and approve/reject controls. |
| Approval completion | Probe approved through Product API; browser badge returned to no pending items and the normalized card changed to approved/authorized. Public continuation confirmed one submission. |
| Mobile layout | Screenshot visually inspected; approval drawer x=31.203125, width=358.796875, right=390; document width=viewport width=390. |
| Plugin identity | SDK/runtime-bin 0.1.2rc1, byq-product-candidate, composition e584cee23c7e39ffaaf7d4c583d4762556032b4d4d173285c14c038d98ec6f98, desired/active consistent. |
| Plugin boundaries | Three qualified/enabled, two blocked; visible page states governance-only operations, no runtime install or secrets. Mobile switches table to cards. |
| Settings selector | Accessibility snapshot omitted options, but visual screenshot and DOM inspection showed all 14 options; selecting the observed system overview option navigated successfully. Not an empty menu. |
| Network boundary | Observed fetch/XHR used only same-origin Gateway auth, Product API, public agent sessions and normalized workflow events. Initial unauthenticated me returned expected 401; subsequent requests returned 200. No Backend/MCP/DSH/DB direct browser request observed. |
| Console | No error/warn messages at Plugin Center review. |

Screenshots were inspected inline. Saving them directly in the isolated worktree
was rejected by the browser tool's workspace-root restriction; no saved screenshot
artifact is claimed. This text records the actual review, not automated browser
test counts masquerading as Chrome MCP evidence. The approval action itself was
the fixed probe's Product API action, not a claimed manual browser click.

Known limitations: product disclosure text correctly describes the normal official
Hub workflow even in this test fixture; infrastructure preflight and fake receipt
counters, not generated model prose, establish the actual test destination.
