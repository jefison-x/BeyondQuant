# Ordinary Product ACP integration — 2026-10-05

This record supersedes the “actual Gateway/Product API browser and model
flows = NOT_RUN” row of
[WORKSPACE-SLOT-CONVERGENCE.md](WORKSPACE-SLOT-CONVERGENCE.md) for the
ordinary one-slot path only. It does not qualify the dedicated research
judgment entry, F6 continuation, two-user capacity, paid provider behavior,
default ACP promotion, CI, merge, release or deployment. Historical FAIL and
NOT_RUN rows are preserved.

## Scope and identities

- Isolated branch `codex/dsh-acp-upgrade`, worktree
  `/home/jefison/.codex/worktrees/dsh-acp-upgrade/BeyondQuant`.
  Retained base `b8a24f6dd89429aff012d1aeecc11cd83859c1d4`; new local commit
  `6d8530a2` (no push, no PR, no merge, no deploy).
- Fixed official DSH candidate `dsh-v0.2.0-rc.2` /
  `639ed015397290b3745d163aafe02ffee4aa3f84`; not changed, forked or retagged.
- Isolated Compose project `byq-acp-iso` from `compose.yml` +
  `compose.dev.yml` + `compose.dsh-acp-rc2-candidate.yml`, synthetic secrets,
  loopback ports `18000/18080/18100/18300/18400`, product workspace
  `workspace_61cb03c8f1a84072997aaa706ada281e`. The running `beyondquant-*`
  stack, its volumes, networks, credentials and users were never touched.

| Input | Identity |
| --- | --- |
| Candidate Adapter image (final tested) | `byq-runtime-adapter-acp:qualification-20261005-slot-fix7` = `sha256:e6220d077926f128ecbd0c8d2bc25a77635a0c47ef1135c6bebad1492e32cee9` (supersedes fix4/fix5/fix6) |
| Candidate product runner image (final tested) | `byq-acp-product-runner:qualification-20261005-fix4` = `sha256:a64b6dce92207af1deb416780ed50729dfa7f24804e6b2002f3dad223511bb5a` (supersedes fix2/fix3) |
| Isolated Backend (current source) | `sha256:11ec92c381dd9e0a1a5b2b411e9366132c7dd23118458a49f20592f92b3cacd2` |
| Isolated Gateway (current source) | `sha256:719834a643146f28cab15ce5b328708b8b7f48c11b3c82154b37d0e810101f9c` |
| Isolated MCP (current source) | `sha256:ad1d30db4b05b5db6e1108bd9ddd8c9ea08c8d7c287e3c87fe386c9c8addca40` |
| Unchanged judgment runner reference | `byq-acp-judgment-runner:qualification-20261005-final` = `sha256:297130a5c383...` |
| `services/acp_product_runner/server.py` source and image | `bb6435dd59200d5f90b487c38aa4f005e8a7505883c5366637f6f89accbc06b6` (read back from `byq-acp-product-runner` fix4; supersedes `cb5472ec…` from fix3) |
| `services/runtime-adapter/app/runtime.py` source and image | `722bf2d1c90ba03749273f7c378bb1bf7f090c9e524b12aa7edd868d1b546cc1` (read back from Adapter fix7; supersedes the earlier `bc0f4fc3…`) |
| `services/runtime-adapter/app/acp_product_slot_client.py` source and image | `f4cb84fc5a9c87a9a4f04a088b29d47060562e60a1389dc7641a13c572c1e3b2` (read back) |
| `plugins/dsh-byq/runtime/byq-acp-mcp-identity.js` source and image | `3e1eaae43319d28d3d908cc55d8cc22eebf9943d49f6645235ef7f8140530ea4` (read back; see stale-image finding) |
| `compose.dsh-acp-rc2-candidate.yml` | `ffe6614bfd98504c32c6658f49b2c77b95bb40430d92884c6e8110f52652747f` |

## Capability / gap / minimal repair / verification

| Area | Prior state | Gap found | Minimal repair | Verification |
| --- | --- | --- | --- | --- |
| Adapter group admission | Code called Backend but Compose never passed the token | Adapter refused every ACP prompt before the slot (`503 runtime_authority_unavailable`) | Added `BYQ_RUNTIME_AUTHORITY_TOKEN` to the candidate Adapter environment | Turn reached group admission; Backend `/agent-admission` 200 `can_start:true` |
| Runner child environment | Runner exported the root in its own env but rebuilt the child env | DSH lacked `BYQ_DSH_RUNTIME_ROOT`; `byq-acp-mcp-identity` failed `BYQ_ACP_AGENT_IDENTITY_UNAVAILABLE`; root binding marker never written | Runner now sets `BYQ_DSH_RUNTIME_ROOT` from its own fixed runtime root | Marker `.byq-acp-root-binding.json` written with exact native root id/cwd |
| Adapter recovery bindings | Written to a shared parent outside the group volume | `PermissionError` and non-persistent bindings after Adapter restart | Bindings now live inside the configured group's mounted session volume; read resolution searches exact session files and fails closed if ambiguous | Binding file persisted across Adapter restart with `native_session_close_confirmed:true`, `cleanup_unconfirmed:false` |
| Adapter image plugin freshness | Adapter image baked `7496ae5a...` (2026-10-04) while worktree/runner baked `3e1eaae4...` | Adapter-local DSH identity failure; convergence “source/image match” claim did not cover this file | Canonical Adapter rebuild baked the current plugin | Readback matches worktree |

The stale plugin did not affect the runner-hosted ordinary slot path once the
runtime-root fix was applied, but the image-identity claim is corrected here.

## Product integration ledger (no paid calls)

All turns used a deliberately invalid DeepSeek key
(`sk-invalid-...`) registered through the real Product settings API. A
provider authentication rejection is not billable.

| Gate | Result | Evidence and boundary |
| --- | --- | --- |
| Isolated environment | PASS | Compose config validated; current-source Backend/Gateway/MCP built; all eight core containers healthy; no production resource touched. |
| Real request chain | PASS | Browser-equivalent Product API login → conversation create → message persist → Adapter prompt 202 → runner ACP → provider. |
| Official DSH ACP initialize/new | PASS | `initialize` protocolVersion 1; `session/new` returned native session id and model config options. |
| Root binding marker | PASS | `.byq-acp-root-binding.json` schema `byq-acp-root-binding.v1`, exact native root id and cwd, mode 0600. |
| Provider boundary reached | PASS, fault injection | Manual ACP driver with the real isolated tokens returned `turn failed: Authentication Fails, Your api key: ****0000 is invalid` in 0.28 s. |
| Exact terminal settlement and slot release | PASS | `terminal-evidence` then `terminal-receipt` 200; runner retained no DSH child; next input admitted. |
| End session rejects input | PASS | `DELETE` returned `deleted`; next turn rejected 404; binding retained `closed:true`. |
| Unconfigured workspace fails closed | PASS | Adapter session create for an unbound workspace returned 503; no slot borrowed. |
| Adapter restart persistence | PASS, partial | Binding persisted in the group volume; new boot correctly differs from Backend authority until Gateway re-adoption. |
| A. Normal multi-turn context continuity | NOT_RUN | Requires a valid model to produce a first answer; failed turns only prove fail-closed settlement. |
| B. Stop then continue | NOT_RUN | Requires an in-flight model turn; no paid call. |
| C. End session | PASS, bounded | Public end/delete rejection proven; no leaked process observed. |
| D. Restart / connection loss | PARTIAL | Binding and startup-fence persistence proven; genuine in-flight crash recovery NOT_RUN. |
| E. Two-user resource-group isolation | NOT_RUN | Candidate overlay statically defines one group; a second group needs a separate statically bound slot service (accepted future capacity), not present. |
| F. Late request / exact ACK | PARTIAL | Exact provider-failure terminal ACK and release proven; delayed old-root MCP ingress and ACK/cleanup loss injection NOT_RUN. |
| G. Dedicated judgment `/acp-root/run` | FAIL, implementation gap | Adapter returns 503 `research judgment entry is disabled` (no `BYQ_RUNTIME_JUDGMENT_TOKEN`); the route also carries the unconditional `research_judgment_acp_lifecycle_unqualified` gate. Not wired; no wiring added. |
| H. F6 background continuation | FAIL, implementation gap | `RuntimeAdapter.continuation_qualified` still requires SDK/runtime `0.1.5rc1`, so ACP disables continuation. ACP F6 NOT_RUN; SDK rollback path unchanged. |
| Real paid model acceptance | NOT_RUN | No budget authorization in this task; see plan below. |
| Browser acceptance | NOT_RUN | Frontend was not started; the ordinary model path is not yet capable of a successful answer, and the user requires real-browser verification. |
| Two-user, delegate, late-ingress, crash-window, judgment terminal ACK | NOT_RUN | Existing blockers unchanged. |

### Preserved failures

1. First recreated Adapter ran in the main repository by shell cwd error; the
   candidate overlay file does not exist there. No service changed; corrected
   with explicit worktree execution.
2. With the runtime-root fix but synthetic MCP tokens, DSH `session/new`
   returned `-32603 mcp-client(byq): initial connection or tool synchronization
   failed`; no marker. Real isolated tokens produced the marker.
3. Before the binding fix, a real turn returned `502 prompt_outcome_unknown`
   and left one leaked Node DSH child occupying the single slot
   (`/opt/dsh-runtime/apps/cli/bin.js --profile acp`, tombstone
   `2773b558...used`). The leak was cleared by exact container restart and is
   the reason binding persistence and slot release are now verified.
4. The global `mcp-byq-discovery` client still logs a non-fatal HTTP 403
   (“discovery credential only permits tool listing”); the signed per-Agent
   client works and the turn proceeds. Tool-bearing real-model acceptance must
   confirm the discovery degradation does not hide the product tool catalog.

## External calls, budget, secrets, cleanup

- External model calls: **zero billable**. One deliberately invalid credential
  produced a provider authentication rejection only.
- Credentials: synthetic isolated secrets only; protected production
  configuration was never opened, copied or printed. The invalid provider key
  and all service tokens are synthetic.
- Budget/usage: no provider usage or billing is available because no request
  authenticated. No numbers are estimated.
- Cleanup recorded separately below; all isolated resources are namespaced
  `byq-acp-iso-*` and enumerable with the Compose project.

## SDK rollback path

Keep `0.1.5rc1` images and protected configuration exactly as recorded in
[BASELINE.md](BASELINE.md). Roll back by selecting the existing SDK
Dockerfile/env and the old session volume; **do not** mount or convert
`dsh-v0.2.0-rc.2-acp` native state. ACP native sessions are not an SDK
migration format. On rollback, reconstruct only from verified completed public
BYQ history after exact Backend root closure; never replay a pending or unknown
prompt. The new group-volume binding location is candidate-only and additive;
no live data is migrated by this change.

## Remaining blockers

1. **Implementation gap**: `/acp-root/run` (ADR-0097 judgment lifecycle) has no
   trusted Adapter→Backend result/close/terminal wiring; the route stays 503.
2. **Implementation gap**: ACP F6 continuation is gated to the `0.1.5rc1` SDK
   pair; requires a separate accepted decision and qualification.
3. **Non-fatal platform finding**: `mcp-byq-discovery` gets 403 on non-listing
   negotiation; needs root-cause confirmation before declaring tool visibility
   qualified.
4. **Deployment-config gap**: a second resource group requires another
   statically bound slot service (sockets, secret, volume); the accepted
   simplification covers one group only.
5. **Paid-model gate**: real answer continuity, stop/continue, delegates,
   browser acceptance and usage accounting need the approved plan below.
6. **Decision needed from maintainer**: whether to invest in the two open
   implementation gaps above, and whether to authorize the paid plan.

## Independent test and review

No independent Tester or Reviewer role was available in this local session.
The focused tests were run by the writer (Root-equivalent) against the rebuilt
images; browser, real-model and independent verification remain NOT_RUN. These
results must be handed back to Codex Root and an independent Reviewer before
any promotion.

## Proposed minimal real-model acceptance plan (awaiting budget approval)

| Item | Proposal |
| --- | --- |
| Provider/model | Existing BYQ-bound OpenCode route only after the registered credential is confirmed; provider/model/credential version read back from Backend, never overridden by the request. |
| Request cap | ≤ 4 model requests total. |
| Output cap | ≤ 256 output tokens per request. |
| Cost cap | Smallest available paid unit; hard stop if unit pricing cannot be confirmed. |
| Data scope | Synthetic prompt text only; no user, market, strategy or production data. |
| Scenarios | (1) one normal answer; (2) one second turn proving native session reuse and no duplicated input; (3) one permission-scoped read-only MCP tool call; (4) stop/continue with exact cancellation settlement. |
| Stop rule | Any unknown charge, retry ambiguity or provider error stops the run; no automatic retry or model switch. |
| Evidence | Exact answer, usage/billing if provided (otherwise explicitly UNKNOWN), tool call, Backend terminal ACK, no leaked process, slot release. |

Execution requires explicit confirmation of provider, model, request/output/cost
caps and the credential version. Until then every paid item stays NOT_RUN.

## Second pass — 2026-10-05 (free work + paid readiness)

### Evidence correction

The prior slice conflated two different probes. They are now separated:

- **Manual ACP driver provider-auth probe** (`/tmp/byq-acp-iso/driver_dsh.py`,
  run keyless through the real isolated tokens with an invalid DeepSeek key).
  It proves the ACP composition reaches the provider and that an
  authentication rejection is classified `turn failed` in 0.28 s. It is **not**
  a real-model or Product acceptance.
- **Real Product chain** (Gateway → Product API → Backend → Adapter → runner →
  official DSH ACP). It proves routing, admission, native session creation,
  root-binding marker, terminal ACK and slot release. It still did not produce
  a model answer, so it is not real-model acceptance either.

### New PASS

| Gate | Result | Evidence |
| --- | --- | --- |
| `mcp-byq-discovery` 403 root cause | PASS | `@modelcontextprotocol/client` 2.0.0 negotiates with a `server/discover` probe; the discovery allowlist rejected it 403. Reproduced: `initialize` 200, `server/discover` 403, `tools/list` 200. |
| Discovery fix, no privilege expansion | PASS | Allowed `server/discover` (protocol capabilities only); execution tool `byq_health` still 403. Commit `e9569272`; MCP image `sha256:a547c6001a6777736a0362d951281083736eb3fe8a803fb5d03bf512386a4063`; `acp-auth-test` and `acp-bridge-test` PASS. DSH stderr no longer lists `mcp-byq-discovery` failure. |
| Late/foreign old-root MCP request denial (real MCP→Backend chain) | PASS | Correctly signed Product token for (a) a forged unknown root and (b) a real closed terminal root both return `acp_ingress_observation_unavailable` before any business handler. An old or foreign root cannot borrow a new root's permissions. |
| Unauthorized owner rejected | PASS | Backend workspace-agent-admission: owner `admin` 200 `can_start:true`; `intruder_user` 401 “runtime lifecycle workspace does not match its owner”. |
| Binding cross-group fail-closed | PASS | With two configured groups and no explicit workspace, `_acp_binding_path` raises `SessionConflict`; an explicit workspace resolves to that group's volume. |
| Real browser flow (invalid-key model, no billing) | PASS, bounded | Playwright-managed Chromium through the frontend: login, new conversation, send turn (`POST …/turns -> 202`), run-failure rendered, history persisted after reload, session delete 200. Ended-session input is rejected at the Product API (404); the UI starts a new conversation instead. Screenshots and `browser-evidence.json` under `/tmp/byq-acp-iso/`. |

### Paid readiness (no paid call made)

| Item | Observed |
| --- | --- |
| Credential source | Local OpenCode saved credential `opencode-go` (key never printed). |
| BYQ registration | credential `cred_096cfac5e8954abf9e0518d4cfcbf53a` v1, profile `profile_291550f88da64f7f800353d1f1594e57` (`deepseek-v4-flash`), binding `byq-product` v2. |
| Resolved route | Backend resolver returns `provider=opencode-go-chat`, `model=deepseek-v4-flash`, api_key present (len only). |
| Route compatibility | `deepseek-v4.1-flash` is not in BYQ's static catalogue and was rejected 422; the supported route is `opencode-go-chat`/`deepseek-v4-flash`. |
| ≤256 output cap | **Not enforceable** in the ordinary ACP path: `_select_route` does not apply `max_tokens`; the fixed profile sets `maxTokens: 4096`. 256 remains a target, not a hard cap. |

### Proposed paid cap (confirmation required)

Provider `opencode-go`, model `deepseek-v4-flash`, isolated synthetic prompts,
**≤ 6 actual provider requests total** across the whole acceptance, **≤ 4096
output tokens/request** (the effective enforced ceiling; 256 not enforceable),
**cost cap ≤ US$0.05 total**, no retries and no model switch, stop on any
usage/charge ambiguity. Scenarios: one normal answer, one second turn proving
native reuse and no duplicated context, one permission-scoped read-only tool
call, one stop/continue. On confirmation I execute this exact plan; until then
every paid item stays NOT_RUN.

### Still NOT_RUN

Normal multi-turn native reuse, stop/continue, tool-bearing acceptance,
delegate identity/tool/terminal proof, two configured-group isolation
(unconfigured group is fail-closed), and all paid items.

## Third pass — real model (authorized, cap US$1)

### Route fix required to reach the model

The OpenCode Go API rejects a chat request without an `x-opencode-session`
header (`400 MissingSessionID`). The Adapter already derives the stable
`BYQ_PROVIDER_SESSION_ID` for exactly this. Commit `eff70361` adds it as a
route header on the three `opencode-go-*` routes, updates the composition
identity hash (`d53c45f3…`) and the runner image assertion. Verified with a
1-token direct call: no header 400, with header 200 + usage. Rebuilt images:
runner `sha256:67950caf1334…`, Adapter `sha256:c96edc5b71b0…`.

### Results

| Gate | Result | Evidence |
| --- | --- | --- |
| Turn 1 normal answer (real model) | PASS | Product chain returned the exact assistant answer `ACP-OK-1` for the prompt “reply with exactly this token”. Route `opencode-go-chat`/`deepseek-v4-flash`, provider 200. |
| Turn 2 native session reuse (ADR-0096) | FAIL | After the exact terminal ACK and terminal receipt, the second root's `session/resume` returns `-32603 Internal error: session "<id>" is already owned by an active write handle`; the Adapter surfaces 500 and the Gateway 502. Reproduced directly against the fixed DSH: the previous root's write handle is still held, so the new process cannot resume. Binding ends `cleanup_unconfirmed: true`. |
| Provider usage / cost | PARTIAL | The 1-token header probe returned usage (input 32 / output 1). Turn 1's actual provider request count and usage are not surfaced by the Product events and are UNKNOWN. Failed attempts (`400 MissingSessionID`, `409`) produced no output. See “Cost accounting (exact)” — no billing evidence is available, so total spend is not asserted. |
| Real browser real-model flow | NOT_RUN | Blocked by the reuse defect for multi-turn; single-turn browser was not separately run. |

### Stop boundary and minimal decision

The ordinary single-turn path is accepted to the provider. The
**normal-completion native reuse path (ADR-0096) is not working**: the prior
DSH process's session write handle survives the signed EXIT, so the fresh
process cannot `session/resume`. Per the stop rules this is recorded at that
exact boundary; no speculative fix was applied.

Decision needed: either authorize a focused fix of the normal-completion
close/lock-release so the previous DSH process truly releases the native
session before the next root resumes, or fall back to the ADR-0093
fresh-native mapping per root (public completed history only) and defer reuse.
Until then, multi-turn continuity, stop/continue, tool-bearing acceptance,
delegate proof and browser real-model acceptance remain NOT_RUN.

## Fourth pass — reuse root cause and minimal fix (option 1)

The maintainer selected option 1: confirm the root cause before fixing. The
prior “active write handle” wording is superseded; it described a leftover
process, not the normal path.

### Hypotheses resolved with a keyless two-root probe

`/tmp/byq-acp-iso/probe_lock.py` ran root A (ACP `session/new` → `session/close`
→ transport close → CANCEL → signed EXIT cleanup=proven) then root B (new
process, same leaf, `session/resume`):

| Hypothesis | Verdict | Evidence |
| --- | --- | --- |
| Old process still alive | NOT the cause | After root A close the runner held no DSH child; the signed `EXIT(code=0, reason=cancelled, cleanup=proven)` was received. |
| Close/EXIT ordering wrong | NOT the cause | The exact close → CANCEL → EXIT → cleanup sequence ran and root B resumed. |
| Duplicate open of the same session | NOT the cause | No second `session/new`; the adapter requests one `session/resume` with the exact native id. |
| Persistent lock after exit | NOT the cause (lock present) | `sessions/<id>/session.lock` persists, but root B resumed successfully with it present. |

**Confirmed root cause (BYQ Adapter bug, not DSH):** the pinned ACP SDK
`ResumeSessionResponse` schema defines only `modes`/`configOptions`/`_meta`
(no `sessionId`), and fixed official DSH rc.2 `resumeSession` returns
`{ configOptions }`. The Adapter's `resume_session` required
`result["sessionId"]` through `_session_id`, so a valid resume raised
`AcpTransportError` → HTTP 500 → Gateway 502.

Attribution of the earlier `cleanup_unconfirmed: true`: that binding was the
Adapter session `byq-session-0139ee2cda9145dbade0825d9d25a776`, root
`c0a758d0a46040c59c07f2fd28ffa50d` (the successful Turn-1 root); it was written
during the failed Turn-2 resume attempt, not by a failed close.

### Fix and verification

- Commit `794d90e3`: `resume_session` uses the exact requested native id when
  the official response omits `sessionId`; an echoed id must still match. The
  on-disk root-binding marker check (`_verify_root_binding`) and
  `_select_route` are unchanged, so no gate is weakened. Adapter image
  `sha256:0f212f8047f0be51d43f6d8e8a9c8e611f40050e7e05458052bad02d070cdb5f`
  (fix6).
- Keyless compat probe (`probe_compat_resume.py`) over the real runner: root A
  create/close then root B `resume_session` returned the exact native id and
  verified the marker. PASS.
- Real Product recovery (authorized): Turn 1 answer `ACP-OK-1`; Turn 2 reuse
  accepted 202 and answered `ACP-OK-1`, `SAME_NATIVE=true`,
  `DIFFERENT_ROOT=true`, both bindings `native_session_close_confirmed:true`,
  `cleanup_unconfirmed:false`. PASS.

Provider usage: this recovery submitted 2 user turns (Turn 1 + Turn 2); the
per-turn actual provider request count and usage are not surfaced by the Product
events and are UNKNOWN. See “Cost accounting (exact)”.

Duplication check: the Adapter's reuse path sends only the new input
(`effective_content = content` when `reuse_native`); the raw native-log
occurrence count is NOT_RUN because no zstd tooling is available locally. The
second answer correctly recalled the first token.

Still NOT_RUN: stop/continue, tool-bearing acceptance, delegate identity/tool/
terminal proof, two configured-group isolation, browser real-model acceptance.

## Fifth pass — read-only tool and stop/continue (real model)

| Gate | Result | Evidence |
| --- | --- | --- |
| Read-only business tool call | PASS | Turn prompt asked for a single `byq_health` call; the Backend logged `POST /internal/acp/tool-ingress-observe 200` and `/tool-ingress-settle 200` during the turn and the answer was `ok`. Tool identity is inferred from the prompt (the ingress body is not logged). |
| Stop then continue, soft cancel | PASS | `POST /cancel {mode:soft}` returned `cancelling`; the next turn was accepted 202 and answered `AFTER-SOFT`. Events show `session.result.discarded` for the interrupted run, then a fresh `session.started`/`session.result`; the interrupted input was not replayed. |
| Stop, hard cancel | PASS, fail-closed | `{mode:hard}` returned `interrupted`; the session enters `interrupted` containment and a further turn returns 409 `cannot accept a prompt in state interrupted`. `POST /resume` returns the accepted product message `agent_session_interrupted` (“start a new Agent session … query durable Jobs by job_id”). This is the Accepted interruption-containment behavior, not a defect. |
| Delegate identity/tool/terminal | NOT_RUN | Requires a delegation-inducing real turn; the historical fixed-source child-evidence projection FAIL remains, so this is not qualified by root reuse or by the tool call above. |
| Two configured-group isolation | NOT_RUN | Unconfigured-group fail-closed remains PASS; a second static slot was not added. |

Provider usage this pass: 4 user turns submitted (tool turn, hard-stop turn,
soft-stop turn, soft continue). Actual provider request counts and usage are not
surfaced by the Product events and are UNKNOWN. See “Cost accounting (exact)”.

Remaining NOT_RUN: delegate identity/tool/terminal proof, two configured-group
isolation, browser real-model acceptance, ACP F6 and the dedicated judgment
`/acp-root/run`.

## Sixth pass — two-group isolation, delegation boundary, browser real model

### Two configured groups (isolated env only)

A test-only override (`/tmp/byq-acp-iso/override-twogroup.yml`, never committed)
added a second static slot: second workspace `workspace_0c790a0f…` (user
`isouser`), separate control socket `/run/byq-acp-product-runner-b/control.sock`,
separate control secret and separate session/state/control volumes. Verified
keylessly:

| Check | Result | Evidence |
| --- | --- | --- |
| Distinct slots/secrets/volumes | PASS | Rendered config and two distinct sockets; registry refuses two workspaces sharing a control secret. |
| Cross-group slot borrow | PASS (rejected) | A workspace-1 scope signed for runner-b's secret returns signed reject `workspace_mismatch`. |
| Same-group busy | PASS | With a workspace-1 lease held, `get_available_binding(ws1)` raises `ProductSlotBusy`; `get_available_binding(ws2)` succeeds. |
| Independent execution | PASS | A root held on group 1 did not block a second root starting on group 2; both started and closed. |
| Cross-user history isolation | PASS | `isouser` lists only its own conversations and reading the admin conversation returns 404. |

Not separately run: concurrent real-model turns for both users (would need a
second paid credential binding); the slot-isolation mechanism and API isolation
are proven above.

### Delegation identity/tool/terminal

FAIL / implementation gap. One real delegation turn invoked
`byq_delegate_market_research`; a subagent was created and attempted
`byq_agent_context`, which the Backend rejected with
`acp_ingress_observation_unavailable`. The isolated database shows no
`agent_acp_native_agent_registrations` row for the child, no child
`agent_acp_tool_ingress_observations` row, and no `agent_runs` row with a
parent. Child identity, business-tool proof and terminal evidence are
therefore NOT qualified; this matches the historical ADR-0094 child-evidence
blocker. The root's own `byq_health` observation is the only ingress row.

### Browser real-model acceptance

PASS, bounded. Playwright-managed Chromium through the frontend (Gateway/
Product API): the assistant rendered the real model answer `BROWSER-OK` for a
synthetic prompt. Caveat: the UI restored the most recent conversation, so the
answer was appended there rather than a brand-new conversation; no new
`POST /v1/agent/sessions` occurred. Credit for the browser real-model gate,
with that boundary recorded.

Provider usage this pass: 2 user turns submitted (delegation turn + browser
turn). Actual provider request counts and usage are UNKNOWN from the Product
events. See “Cost accounting (exact)”.

Remaining NOT_RUN: delegation identity/tool/terminal, concurrent two-user
real-model turns, ACP F6 and the dedicated judgment `/acp-root/run`.

## Seventh pass — delegation blocker root cause and fix

The sixth-pass delegation FAIL is superseded. Root cause confirmed:

`POST /v1/agents/runs` (ACP branch) built `request_payload` from the context
returned with `include_workspace=True`, which contains `workspace_id`, but
`agent_store.start_run` rejects `workspace_id` as an unknown field. Every ACP
Product `byq_agent_run_start` therefore returned `422 agent_request_invalid`,
so no root AgentRun was bound; non-bootstrap domain tool ingress and every
delegation were blocked (the earlier `byq_health` read-only pass worked only
because it is a bootstrap tool that needs no binding).

Free reproduction against the Backend with an exact ACP registration request:

| Before fix | After fix |
| --- | --- |
| `422 {"detail":"agent run request has unknown fields: workspace_id"}` | `409 {"detail":"ACP root is not yet registered by Backend"}` (the expected next check for an unadmitted synthetic root) |

Fix commit `042aeb93`: exclude `workspace_id` from the payload merge; it is an
authorization-boundary value passed separately as `trusted_workspace`. Backend
image `byq-acp-iso-backend-v2` =
`sha256:a736f623f56eca042b8d1029f1b9be1d29398ad70fa7121681983f2e45462556`.

Real delegation re-run (authorized): the coordinator registered
(`origin=root depth=0`, `status=bound`) and the market-research subagent
registered with the exact native parent (`origin=subagent depth=1`,
`native_parent_session_id = root`, `status=bound`). The subagent's
`byq_agent_context` ingress settled, and the child AgentRun
(`agent_run_5b69f7…`) is parented to the root AgentRun (`agent_run_a3dcca…`);
the model reported the child run id and workspace id. Delegation identity,
tool-call proof and terminal evidence are therefore PASS for this bounded turn.

Provider usage this pass: 2 user turns submitted (one failed pre-fix
delegation, one successful post-fix delegation). Actual provider request counts
and usage are UNKNOWN. See “Cost accounting (exact)”.

### Concurrent two-user real model (E completeness)

PASS. With both groups configured and a model binding on each user: admin
(workspace 1) started a long turn while `isouser` (workspace 2) submitted a
turn 0.6 s later; the second user's turn was accepted and answered `USER2-OK`
while workspace 1 was still busy, proving independent group execution. A second
admin turn submitted while workspace 1 was busy returned 409 (same-group busy
rejected), and the same turn was accepted 202 once the first turn completed
(retriable). Both users' conversations remained isolated (owner-scoped).

Provider usage: 3 user turns submitted (two concurrent turns, one retry). Actual
provider request counts and usage are UNKNOWN. See “Cost accounting (exact)”.

## Eighth pass — same-model independent auxiliary sessions

Two fresh-context sessions on the same model were run: one auxiliary
verification and one static code review. They received only the task scope,
Accepted ADRs, exact HEAD `dab9b04c`, and evidence paths — not the implementer's
conclusions. Both were restricted to read-only inspection and FREE targeted
tests; no implementation changes, no paid calls, no full suite. **These are
explicitly auxiliary and do NOT satisfy the repository's official Tester /
Reviewer gate.**

Auxiliary verification (free, executable):

- Reproduced the adapter focused suite 29/29 (source mounted read-only, network
  disabled), MCP `acp-auth-test`/`acp-bridge-test`, and the runner
  `test_server.py` 8/8 in an adapter image as root (see limitation below).
- Reproduced the free keyless probes against an isolated `byq-acp-iso` stack:
  `probe_compat_resume` RESUME_OK, `probe_busy` same-group busy/other-group
  available, `probe_iso` cross-group `workspace_mismatch` + duplicate-secret
  refusal + independent execution. Stack torn down; production untouched.
- Independently checked the ACP SDK `ResumeSessionResponse` schema (no
  `sessionId`) and DSH `resumeSession` response.
- Verified worktree↔image sha256 for the changed files and the profile/identity
  hash chain.

Auxiliary code review (static, no docker): **no P1 found.** It judged the
concrete fixes targeted and not gate-weakening (terminal ACK, cleanup receipt,
root-binding marker, tenancy, per-Agent MCP, child env filtering all retained;
no new harness/scheduler/allocator). Open findings to hand to Root:

1. P2 — this document/`CURRENT-QUALIFICATION.md` recorded stale candidate-input
   hashes and stale “final tested” image tags. Corrected in the same commit as
   this section.
2. P2 — the resume fix (`_resumed_session_id`) has no in-repo regression test;
   the existing fixture models the old wrong contract (returns `sessionId`).
   Recommend adding a keyless compatibility test with an omitted-`sessionId`
   resume reply plus a mismatched-echo negative.
3. P2 — defense-in-depth: `_read_acp_binding` finds a binding across groups and
   validates `cwd` against the binding's own `workspace_id`, but does not assert
   the file's containing group equals that `workspace_id`. Recommend comparing
   the resolved path to `_acp_binding_path(session_id, value["workspace_id"])`.
4. P3 — with ≥2 groups and no on-disk binding, recovery now returns 409
   (`workspace is ambiguous`) instead of 404; fail-closed and harmless, worth a
   deliberate test/note.
5. P3 — the diff contains no test changes; the multi-group binding logic and
   `configured_workspaces()` are unverified by committed tests.
6. Info — the runner focused tests cannot run in the named runner image (its
   entrypoint runs `server.py` and it has no pytest); the auxiliary verifier ran
   them as root in the adapter image instead.
7. Info — judgment `_ACP_JUDGMENT_ALLOWED_ENV` does not list
   `BYQ_PROVIDER_SESSION_ID`; `/acp-root/run` is disabled so this is currently
   unreachable, but reconcile before enabling judgment.
8. Info — `x-opencode-session` is stable across BYQ roots by design; whether the
   provider uses it for server-side context carry-over needs explicit proof.

Open ADR observations from the review: ADR-0096 reuse and ADR-0094 child
evidence remain bounded observations, not full ADR qualification; ADR-0100
required-evidence items 1–3 remain NOT_RUN. Materials are handed back to Codex
Root for the formal Tester/Reviewer gate. No push, PR, merge or deploy.
## Ninth pass — review fixes, exception record, and cost accounting

### Special-project process exception (ADR-0101 drafted)

The maintainer explicitly authorized this special project to fill the Tester and
Reviewer roles with **new independent same-model OpenCode sessions**, with the
main session as Root, instead of the Clean Break `gpt-6-luna`/max Tester and
`gpt-6-sol`/medium Reviewer. The exception is scoped to the DSH ACP special
project only and is drafted as [ADR-0101](../../architecture/adr/ADR-0101-dsh-acp-special-project-same-model-review.md)
(Proposed). Same model is not same-session self-review: the implementer changes
code, the Tester verifies behaviour, the Reviewer inspects the diff, and Root
concludes; neither reviewer modifies implementation. No push/PR/merge/deploy.

### Review-driven fixes

1. **Resume regression tests (keyless).** The compatibility fake now models the
   official `ResumeSessionResponse` (no `sessionId`) on `session/resume`, so the
   existing lifecycle test exercises the fixed path; a new unit test checks
   `_resumed_session_id` (absent → expected, match → expected, conflict → raise,
   non-dict → raise) and a new integration test proves a conflicting echoed
   `sessionId` is rejected. `_verify_root_binding`, the native-id match and the
   durable root marker remain enforced.
2. **Binding group membership.** `_read_acp_binding` now asserts the located
   file path equals `_acp_binding_path(session_id, binding.workspace_id)`, so a
   binding physically written in another group's volume is rejected. Focused
   tests cover explicit-workspace resolution, cross-group ambiguity fail-closed,
   and a wrong-group file.
3. **Multi-group missing binding contract.** With ≥2 configured groups and no
   on-disk binding the Adapter returns `SessionConflict` (409), not 404. This is
   fail-closed, reachable only in the uncommitted two-group test topology, and
   the single-group candidate is unchanged; recorded and covered by the
   ambiguity test. No public compatibility layer added.
4. **Runner test reproduction.** The named runner image cannot run pytest (its
   ENTRYPOINT runs `server.py`; no pytest/pip installed); it is a runtime image,
   not a test image. Runner `test_server.py` is therefore run in an ephemeral
   adapter image as `0:0` with the worktree mounted read-only (8/8), and this is
   recorded as source-logic verification, distinct from final-image runtime
   behaviour. The production runner image is not expanded to carry pytest.

### `x-opencode-session` semantics

`x-opencode-session` is a **provider routing header**, distinct from the BYQ MCP
root identity (`BYQ_ROOT_RUN_ID` / the signed per-Agent MCP token). It is set to
the Adapter-derived stable `BYQ_PROVIDER_SESSION_ID` (uuid5 of the BYQ public
session) so the OpenCode Go gateway can route efficiently. Whether the provider
uses it to retain server-side conversation state across BYQ roots is **NOT
confirmed** by BYQ evidence; the ACP path still restores context natively
(ADR-0096) and the fresh-native path (ADR-0093) sends only the new prompt. The
provider-side semantics remain an open gap to confirm before any claim about
provider-context carry-over; the identity strategy was not changed.

### Cost accounting (exact)

Authorized cap: US$1.00 (maintainer). No billing or usage export was available
for the Product-path calls.

- **Known actual provider requests with usage evidence:** 1 — the direct
  OpenCode Go header probe (input 32 / output 1 tokens, HTTP 200).
- **Product-path user turns submitted:** the evidence records individual turns
  across the third–seventh passes (normal answer; native-reuse second turn; tool
  turn; hard-stop, soft-stop and soft-continue; pre/post-fix delegation;
  concurrent two-user plus retry; browser). The **actual provider request count
  per turn is not observable** from the Product events and is UNKNOWN; DSH may
  issue more than one request per turn.
- **Usage / billing:** UNKNOWN for all Product-path calls; not estimated.
- **Failed attempts** (`400 MissingSessionID`, `409`, resume/prompt errors)
  produced no model output and are not billed.
- Therefore total spend is **not asserted**; the US$1 cap was the authorization
  ceiling, not a measured amount.

## Tenth pass — frozen HEAD and independent roles pending

## Root synthesis (same-model process under ADR-0101)

Independent Tester and Reviewer ran as separate same-model sessions on frozen
HEAD `b3c71bfc`, each with only scope, ADRs, HEAD and evidence paths. Both are
auxiliary under ADR-0101 and do **not** satisfy the repository's official
Tester/Reviewer gate.

- Tester: five fixes PASS (adapter resume 72/72 with the official no-`sessionId`
  reply modeled; binding group checks; runner child env; MCP discovery live
  200/403; backend payload static), plus free two-group probes. NOT_RUN: paid
  real-model, browser, delegation, judgment, F6, full CI.
- Reviewer: no P1; static-review PASS (conditional) for the ordinary single
  workspace path; gates (authorization, tenancy, terminal ACK, cleanup, marker,
  per-Agent MCP) not weakened. P2: the evidence recorded a stale `runtime.py`
  hash / final-image tag — corrected above. P3s: runner child-runtime-root
  ordering (hardened), 409-vs-404 recovery contract (tested/recorded),
  coverage-only gaps.

Post-review implementer change (affected part re-verified, not a new design):
the runner now sets `BYQ_DSH_RUNTIME_ROOT` **after** the allowlisted env merge
and forbidden pop, so a future allowlist expansion cannot redirect the fixed
launcher; a focused runner test asserts it and the forbidden authority keys are
dropped. Running `services/acp_product_runner/tests/test_server.py` → 9/9. The
post-review change touches only the runner (`byq-acp-product-runner:…-fix4`,
`bb6435dd…`); the Adapter remains `slot-fix7` (`722bf2d1…`).

### Current gate table — ordinary ACP session scope

| Gate | Verdict | Boundary |
| --- | --- | --- |
| A normal answer + second-turn native reuse, same native id, new root, no replay | PASS | Bounded real model, one configured group |
| B soft stop then continue; hard-cancel interrupted containment | PASS | Real model; hard cancel blocks resume by accepted design |
| C ended-session input rejected | PASS | Real Product API 404/UI |
| D restart persistence of binding/slot fence | PARTIAL | Persistence proven; in-flight crash recovery NOT_RUN |
| E two configured groups: distinct slots/secrets/volumes, busy reject, independent run, cross-user history isolation | PASS | Isolated test topology; committed overlay is single-group |
| F forged/old-root MCP ingress denied before business handler | PASS | Real MCP→Backend; a genuinely delayed old root after a new root starts NOT_RUN |
| Read-only tool call observed/settled | PASS | `byq_health`/`byq_agent_context` via Backend ingress |
| Delegation identity + child tool ingress + parented AgentRun | PASS | Bounded: parent ACP child `session/update` projection not proven |
| Browser real-model answer rendered via Product API | PASS | Bounded: appended to restored session |
| SDK 0.1.5rc1 rollback path retained | PASS | No ACP native state converted |
| Dedicated judgment `/acp-root/run` | FAIL, disabled (deferred) | Unchanged 503 |
| ACP F6 background continuation | FAIL, disabled (deferred) | SDK-pair gate unchanged |
| Official independent Tester/Reviewer gate; CI; PR; merge; deploy; release | NOT_RUN | Not exercised |

### Coverage boundaries and remaining gaps

- Real Product API / real model: verified by bounded isolated runs (not paid
  usage-accounted); browser real model one answer; no full multi-scenario model
  sweep.
- Synthetic/keyless probes: adapter/runner/MCP focused suites and the
  resume/binding/two-group probes.
- Truly delayed old-root request after a new root starts, in-flight crash
  recovery, delegate parent-ACP child-call projection, concurrent two-user
  reboot recovery, and all judgment/F6 items remain NOT_RUN.
- Formal role checks, promotion and production acceptance are not claimed.

### Rollback and resources

Rollback remains the retained `0.1.5rc1` images/configuration in `BASELINE.md`;
ACP native state is not an SDK migration format. Isolated project `byq-acp-iso`
is stopped with volumes/images retained; the two-group override lives only in
`/tmp`; production `beyondquant-*` was never touched. No push, PR, merge,
release or deploy was performed. Next minimal action: appoint the official
Tester/Reviewer on frozen HEAD (or accept ADR-0101 as the standing special-project
process) and decide the deferred F6/judgment scope.

## Eleventh pass — ADR-0100 boundary, cleanup and rollback evidence (free)

Ran against the isolated two-group stack; production untouched.

| ADR-0100 requirement | Result | Evidence |
| --- | --- | --- |
| Ordinary Product DSH cannot reach the judgment socket/volume/network | PASS | `docker inspect`: `acp-product-runner` joins only the product network and mounts only its product control/sessions/state; `/run/byq-acp-runner` is absent in the product runner; the judgment control dir is `root:10005` mode 0710 and the product runner has no supplementary groups. |
| Ordinary DSH child runs without the judgment control GID | PASS | Live root child had empty `Groups:`; `server.py` launches the child with `extra_groups=()`. |
| No model-controlled subprocess in the Adapter slot path | PASS | `compat/acp_slot_transport.py:74` documents no local DSH subprocess/PID; slot mode uses `SlotAcpProcess`. The only `Popen` is the judgment-only fixed provider worker (`sys.executable -m app.research_judgment_acp_provider_worker`), no shell. |
| Judgment MCP reachable but unauthorized from the product network | PASS | Product runner `fetch http://mcp-acp-judgment:8301/mcp/v1` → HTTP 401 `unauthorized` (judgment credentials required). |
| Container death terminates the active DSH child; scope not replayed | PASS | Held a keyless root on the product runner (child `node` present), `docker restart` killed the namespace → no child after restart; the durable one-shot scope tombstones remain, so the consumed scope cannot be replayed. |
| Group volumes not shared across groups | PASS | Each runner mounts only its own workspace session volume; the Adapter mounts both as the trusted authority. |
| SDK `0.1.5rc1` rollback path still valid | PASS | The retained rollback runtime-adapter reports sdk/runtime `0.1.5rc1`; `compose.yml` still selects the SDK Dockerfile and `dsh-0.1.5rc1` by default, with the ACP candidate only in the overlay; `BASELINE.md` hashes unchanged. |

Remaining NOT_RUN (need a real slow model or multi-round infrastructure): truly
delayed old-root request arriving while a new root is active, in-flight crash
recovery mid-turn, delegate parent-ACP child `session/update` projection,
concurrent two-user reboot recovery, and all judgment/F6 items.

## Twelfth pass — push, Draft PR and CI classification

Authorized `push/PR` was exercised: branch `codex/dsh-acp-upgrade` pushed to
`origin` and **Draft** PR #386 opened against `main`. No merge, ready-marking,
release or deploy. Worktree verified via `scripts/ci/verify-worktree.py`
(with `BYQ_ENGINEERING_WORKTREE_ROOT=/home/jefison/.codex/worktrees`).

CI gates fixed to reach the component lanes:

- `gitleaks` on the PR range flagged 14 synthetic ACP test/plugin constants;
  exact `commit:path:rule:line` fingerprints added to `.gitleaksignore` (no rule
  suppressed globally). Local gitleaks on the range: `no leaks found`.
- The immutable SDK build manifest drifted because the ACP changes touch shared
  adapter/backend/MCP source; minted revision `dsh-0.1.5rc1-post-u8.305`
  (`Dockerfile.post-u8-305-candidate` + manifest, `selected_build_id` updated,
  focused test updated).
- Architecture: documented the implemented `POST
  /api/product/research/tasks/{task_id}/acp-judgment/cancel-intent` route;
  corrected the `pnpm install` vs `npm install` false positive and the SDK
  guard-patch trailing-comma assertion.
- Backend reset fence: the disabled-identity terminal-cleanup allowance now
  includes the four ACP terminal columns, so exact terminal facts for an
  existing bound root still persist (18 lifecycle tests).
- Runtime-roots projection fixture updated for the ACP terminal fields.

The initially inherited failures were then fixed in a bounded pass:

1. Gateway tests: stubbed the new terminal-evidence `_adapter_get` readback and
   the boot-readiness snapshot (trace-stream replay, interrupted restore,
   continuation live-attach).
2. Architecture: bounded the product-capability ML-surface slice to the ML
   registration block; the `pnpm`/`npm` and SDK guard-patch assertions were
   corrected; the build-revision manifest was regenerated after each source
   edit (revision `post-u8.305`).
3. Backend: the reset-fence terminal-cleanup allowance now includes the four ACP
   terminal columns (18 lifecycle tests); the runtime-roots projection fixture
   was updated for the ACP fields. Verified against an ephemeral PostgreSQL:
   `test_runtime_authority_api` 5/5 and `test_agent_lifecycle_api` 23/23.
4. v0.9 evidence provenance: reconciled the recorded digests for the
   branch-changed SDK compat module and the chained d15/final-closeout records.

Local verification: the full architecture lane (`python3 -m unittest discover
-s tests -p 'test_*.py'`, 926 tests) passes; gateway 3/3; build_revision check
PASS. **Hosted PR CI result: run 37295954638 all observed checks succeeded
(PASS)** for head `2af01856`. The Draft PR #386 remains open; no ready-marking,
merge, release or deploy was performed.
