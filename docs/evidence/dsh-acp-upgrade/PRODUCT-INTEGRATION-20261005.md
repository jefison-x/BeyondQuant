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
| Candidate Adapter image (final tested) | `byq-runtime-adapter-acp:qualification-20261005-slot-fix4` = `sha256:b746add44785d866d7433fc2a8df840cab7a0e816d29bd94658f1f845db781cd` |
| Candidate product runner image (final tested) | `byq-acp-product-runner:qualification-20261005-fix2` = `sha256:b275a9efb1e77b7709fc877ee996390be7cd9540a7626d7141c6dc6b62ee8beb` |
| Isolated Backend (current source) | `sha256:11ec92c381dd9e0a1a5b2b411e9366132c7dd23118458a49f20592f92b3cacd2` |
| Isolated Gateway (current source) | `sha256:719834a643146f28cab15ce5b328708b8b7f48c11b3c82154b37d0e810101f9c` |
| Isolated MCP (current source) | `sha256:ad1d30db4b05b5db6e1108bd9ddd8c9ea08c8d7c287e3c87fe386c9c8addca40` |
| Unchanged judgment runner reference | `byq-acp-judgment-runner:qualification-20261005-final` = `sha256:297130a5c383...` |
| `services/acp_product_runner/server.py` source and image | `cb5472ecace41c7d8476515ed1d8ccf099418dbe1cb59f0466091e8f046583d8` (read back from image) |
| `services/runtime-adapter/app/runtime.py` source and image | `bc0f4fc32334725eb5e26550164ff992edf64cddab910ccc8052d75cebf9aa8c` (read back) |
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