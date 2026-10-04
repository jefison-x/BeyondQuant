# ADR-0097 ACP judgment provider gate: fixed-source route audit

Status: **design evidence only**. The `/acp-root/run` entry remains an
unconditional 503. No provider, Product, or paid-model request was made by
this audit.

## Fixed candidate and native controls

The source checkout is the clean official `dsh-v0.2.0-rc.2` commit
`639ed015397290b3745d163aafe02ffee4aa3f84`. DSH has per-request output
limits, provider retry policies, tool concurrency, and delegation depth. The
dedicated judgment profile now sets `maxRetries: 0` on its seven configured
routes and disables the account route and the two independently retrying
compaction listeners. These controls do **not** measure a BYQ research stage's
total provider calls, serialized input/tool bytes, actual billable output,
deadline, or an unknown response across process loss. ACP `usage_update`
measures context occupancy rather than provider usage.

## Selected-route feasibility probe

A keyless, offline fixed-source `--dump-config` probe applied one extra private
overlay after the current dedicated profile for each of its seven route names.
All seven composed successfully. For `deepseek-official`, the overlay disabled
`llm-pi-ai` and set the DeepSeek Messages base URL to a loopback proxy. For
each OpenCode route, it disabled `llm-deepseek` and replaced the entire
`llm-pi-ai.providers` dictionary with exactly the selected route and a loopback
base URL. The checked `llm-deepseek`, `llm-pi-ai` and
`llm-deepseek-account` rows showed only the selected provider enabled in each
case. This is **PASS for offline composition only**; no ACP process or
provider request was sent through the overlay.

Reproduce from the BYQ worktree with host PyYAML and the clean fixed source:

```sh
python3 docs/evidence/dsh-acp-upgrade/probe-selected-routes.py \
  /tmp/byq-dsh-acp-rc2-source \
  "$PWD/plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-research-judgment.patch.yml"
```

The script SHA-256 is
`66c83abbf5a67155b9d1e613e75f53f1340a618b599444c2a0dfc00f6dd66c4d`.
It checks `--dump-config` exit status, the selected loopback URL, exact single
pi-ai route or disabled pi-ai, disabled DeepSeek for OpenCode selection, and
the disabled account/compaction recovery rows.
All seven rows printed `PASS (offline composition only)` on 2026-10-04.
The temporary overlays and dumps are discarded after each run; the checked
inputs and assertions are retained in the script.

| Selected protocol | Candidate local base URL | Upstream origin/path to preserve |
| --- | --- | --- |
| DeepSeek Messages | `http://127.0.0.1:<port>/anthropic` | `https://api.deepseek.com/anthropic/v1/messages` |
| OpenCode Go Responses, Chat | `http://127.0.0.1:<port>/v1` | `https://opencode.ai/zen/go/v1/{responses,chat/completions}` |
| OpenCode Zen Responses, Chat | `http://127.0.0.1:<port>/v1` | `https://opencode.ai/zen/v1/{responses,chat/completions}` |
| OpenCode Go/Zen Messages | `http://127.0.0.1:<port>` | Pinned SDK appends `/v1/messages?beta=true`; upstream targets are the documented `https://opencode.ai/zen/go/v1/messages` and `https://opencode.ai/zen/v1/messages`. |

The fixed DeepSeek adapter appends `/v1/messages` to a Messages API root. The
fixed pi-ai OpenAI routes append protocol-specific paths to their configured
base URL. A loopback-only fake-server probe of the pinned Anthropic SDK used by pi-ai
confirmed that a Messages base ending `/zen/go/v1` sends
`POST /zen/go/v1/v1/messages?beta=true`, with `x-api-key` and
`anthropic-version` headers. Its script is
`docs/evidence/dsh-acp-upgrade/probe-opencode-messages-path.mjs`, SHA-256
`1a14112ee2ed80f9a09e58feda5ef7f67a938dfbfd3878d2e0ee99d1c7de8fd5`.
It checks the detached official source HEAD, the old and corrected paths, and
the protocol headers against a loopback fake server. Run it with:

```sh
node docs/evidence/dsh-acp-upgrade/probe-opencode-messages-path.mjs \
  /tmp/byq-dsh-acp-rc2-source
```

The dedicated profile now removes the final `/v1` from its two Messages base
URLs. [OpenCode Go](https://opencode.ai/docs/go/) and
[OpenCode Zen](https://opencode.ai/docs/zen/) document the target
`/v1/messages` endpoints. The same probe captured corrected local requests at
`POST /zen/go/v1/messages?beta=true` and
`POST /zen/v1/messages?beta=true`, each with `x-api-key` and
`anthropic-version` and without `Authorization`. This is an SDK-to-local-fake
provider check, not an ACP process or BYQ proxy check. A private overlay can
narrow the route, but its source, selected model,
loopback endpoint, provider credential and final loaded graph must be bound
to the exact admitted call before prompt dispatch. The static profile alone
does not do this. The ACP model-selection option can change routes, so merely
setting a default model is insufficient.

## Current BYQ proxy gaps

The retained judgment `RequestGateProxy` is **not** a qualified ACP gate:

1. It uses a single upstream, follows redirects in judgment mode, and does
   not latch an incomplete provider response as unknown before a later call.
2. It forwards only `authorization`, `content-type`, and `accept`. Messages
   requests need protocol-specific `x-api-key`, `anthropic-version`, and
   possibly `anthropic-beta`; they cannot authenticate correctly through the
   current header filter.
3. Its actual-usage parser expects OpenAI Chat fields. Responses and Messages
   have different usage fields and streamed event forms. A missing or partial
   usage receipt must stay unknown rather than be treated as zero.
4. The existing three-call judgment budget was measured for the retained
   root-child-root SDK composition. A dedicated ACP root needs a new named,
   measured stage profile, including total calls, attempts, bytes, output,
   concurrency and a tool-idle watchdog. A hard cap may stop early, but it
   cannot be called Product qualification without running that path.
5. DeepSeek Files and pi-ai model discovery have additional HTTP paths. The
   dedicated mode must prove they are unreachable for this bounded text task
   or deny them at the proxy before external dispatch. The final process
   network boundary must prevent bypass of the selected loopback endpoint.
6. Write a durable provider-attempt marker **before** the first outbound
   request, bound to the exact task/call/root, route and private gate journal.
   A crash or lost response after that marker leaves the attempt unknown on
   restart; neither a new proxy nor a resumed ACP process may replay it or
   release the root until exact evidence resolves it. The existing prompt-wide
   may-have-dispatched marker prevents prompt replay but is not a per-provider
   attempt/usage receipt.

Implement a private per-invocation last-layer profile, then a protocol-aware
BYQ provider proxy with exact upstream/path/header allowlists and durable
unknown-outcome stop. Validate all seven routes against a local fake provider,
including lost and partial responses, before considering a separately
authorized paid call. Keep `/acp-root/run` at 503 until Backend result/terminal
ACK and Product qualification gates also pass.
