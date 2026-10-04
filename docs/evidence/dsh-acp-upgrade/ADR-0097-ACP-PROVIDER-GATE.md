# ADR-0097 ACP judgment provider gate: fixed-source route audit

Status: **isolated route/proxy slice only; outbound gate unqualified**. The
`/acp-root/run` entry remains an unconditional 503. No provider, Product, or
paid-model request was made by this audit.

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
`f3e410058d648ed449bbdbac813ec2c64e43491c7368b8cd1130c096fb723590`.
It checks `--dump-config` exit status, the selected loopback URL, exact single
pi-ai route or disabled pi-ai, disabled DeepSeek for OpenCode selection, and
the disabled account/compaction recovery rows.
All seven rows printed `PASS (offline composition only)` on 2026-10-04.
The temporary overlays and dumps are discarded after each run; the checked
inputs and assertions are retained in the script.
The current script uses the candidate's `private_provider_overlay` builder,
so the seven loaded rows now check exactly one selected pi-ai route and model
or DeepSeek alone, the loopback base URL and zero native retries. The
`DshAcpCompatibility` process launcher accepts this last-layer file only for
the explicit judgment-root mode and rechecks its private file permissions and
exact selected route/model/base at build and start. This is keyless config
loading, not a running ACP provider call or proof of network confinement.

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

The unwired `research_judgment_acp_provider_routes.py` helper now maps only
these seven names to exact local request targets and upstream URLs. Before a
request could be forwarded, it compares the request model and credential to
caller-supplied trusted values, checks the declared output ceiling, and
rejects duplicate JSON fields, ambiguous/mixed credentials, Files,
discovery, altered paths and currently unqualified `anthropic-beta` features,
and returns only protocol-specific credential
headers. Its focused offline tests also check that BYQ headers are not returned
for forwarding. This is **PASS for pure admission only**. The helper itself
holds no listener, attempt counter, parser or journal; the unwired candidate
proxy and control journal below provide those separate responsibilities. No
DSH request has passed through them. The caller has not yet been wired to Backend admission
or the trusted credential resolver. The selected model, secret and final loaded
route still need an exact binding to the admitted Backend call at process start.

## Durable attempt and local proxy slice

The ACP judgment control journal now fsyncs a per-provider-attempt marker before
outbound I/O. It binds the marker to the existing task/call/root journal,
selected route, request digest, declared output and bounded request bytes.
A missing or incomplete terminal, transport loss, non-200 response, deadline,
partial actual usage or excess output remains `unknown`; it blocks another
provider attempt and the stage result. A result with zero provider receipts is
also rejected. The journal serializes calls, caps total calls, input bytes,
declared output and elapsed time, and charges the whole serialized request as
a conservative upper bound for tool payload bytes. It stores no provider key or
request body. This is an invocation-local safety record, not a persistent
business budget across research attempts.

The new unwired loopback proxy selects one of the seven fixed routes. It
rejects other paths, duplicate/ambiguous headers, altered credentials and
oversized request bodies before dispatch; forwards only route-approved headers
to a fixed HTTPS URL; disables redirects and environment proxy routing; and
buffers at most 8 MiB of provider SSE under the request deadline. It parses
terminal and actual usage before forwarding, then fsyncs completion after
the local response write/flush. This does not prove DSH application receipt
or consumption. A dispatch lock makes the next request wait for that durable
settlement; close waits for any in-flight dispatch. The local fake-transport
tests exercised all seven exact paths and headers, an unknown lost response,
two consecutive calls, and close ordering. These are **synthetic loopback
facts**, not real `_send_https`, DSH process, credential or Product acceptance.

The proxy constructor still receives model, credential and limits from its
caller. The private last-layer profile is generated and loaded offline, but
it is not bound to trusted Backend admission or the running proxy yet. The
loopback port is not isolated from unrelated local processes.
Actual HTTPS redirect, partial-body, size and deadline negatives remain
NOT_RUN. The real transport's DNS lookup is not covered by urllib's socket
timeout; a blocked lookup could make `close()` wait on the dispatch lock without
a bounded end. Process-level termination and a blocking-resolution negative
must be proven before connecting this proxy to ACP. The seven synthetic
Messages fixtures explicitly report zero cache
read/write; omitted cache fields remain unknown pending fixed-provider stream
qualification. Therefore the outbound budget and unknown-result gate remains
**FAIL / NOT_RUN for integration**, and `/acp-root/run` stays 503.

## Stream terminal and usage slice

All seven pinned adapter routes request streaming responses. The unwired
`research_judgment_acp_provider_usage.py` parser consumes a bounded, complete
SSE body and keeps terminal state separate from provider-reported token fields.
Chat requires `[DONE]` plus `stop`, `end` or a tool-call finish reason;
Responses requires `response.completed` with `status: completed`; Messages
requires `message_start`, a supported `message_delta` stop reason and
`message_stop`. Limit/error reasons and incomplete streams do not prove a
completed provider response. Missing or malformed usage remains `unknown`, not
zero. Anthropic's cumulative `message_delta.usage` replaces earlier values;
cache-read and cache-write facts remain separate. For Chat and Responses, the
provider's total prompt/input count includes cached input; this parser subtracts
validated cache-read and cache-write counts to match the pinned pi-ai SDK's
disjoint input fields. An impossible cache count makes the receipt unknown.
Messages reports disjoint input and cache counts and is mapped directly.
The Chat `[DONE]` and final
frame-delimiter requirements are conservative: the pinned SDK may accept a
stream that this helper rejects. Such a route needs local provider-stream proof
before enablement; the helper must never loosen terminal evidence by inference.

This is **PASS for isolated parser contracts only**. The retained production
proxy does not call the parser; the new unwired candidate proxy does so in
local synthetic tests. Actual HTTPS status, complete socket read, redirect,
declared-output comparison, response-size enforcement before buffering,
durable attempt marker and unknown-outcome stop remain separate integration
gates. Parser `output_proven` alone cannot authorize another request, a business
result or terminal ACK.

## Current BYQ proxy gaps

The retained judgment `RequestGateProxy` is **not** a qualified ACP gate:

1. It uses a single upstream, follows redirects in judgment mode, and does
   not latch an incomplete provider response as unknown before a later call.
2. It forwards only `authorization`, `content-type`, and `accept`. Messages
   requests need protocol-specific `x-api-key`, `anthropic-version`, and
   possibly `anthropic-beta`; they cannot authenticate correctly through the
   current header filter. The pure admission helper rejects any beta feature
   until the selected models' exact fixed-source requests are qualified.
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

Bind the private per-invocation last-layer profile and protocol-aware BYQ
provider proxy to the exact Backend admission, then prove real ACP process
routing, network confinement and unknown-outcome behavior. Keep
`/acp-root/run` at 503 until Backend result/terminal ACK and Product
qualification gates also pass.
