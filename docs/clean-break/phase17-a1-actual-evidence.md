# Phase 17 — Actual A1 and conversation-binding repair

Status: **`.280` A1 COMPLETED / BINDING VERIFIED; Phase 17 OPEN**. This records
two separately authorized one-shot foreground runs, not final Golden acceptance. Source repair
and actual execution have separate identities and gates.

## Authorization and actual execution

The maintainer granted target-only use of the existing DeepSeek key, necessary
Runtime recreation and new pins, then **one** foreground run on
`deepseek-official` / `deepseek-v4-flash`. No delegation, TuShare/market download,
input replay or provider fallback was authorized. Intended Web use was one
search/query; native limits were five uses and four queries per use. The lack
of a raw model-request hard cap was disclosed before the grant.

The exact scope is `byq-dev-dd33416d94`, with Workspace
`workspace_af43ba7a82524108ba11d4695613aafc`. Actual app/source commit:
`6a2a391fb6a6ccd2493944d9a19df27fa64b2b71`; selected build
`dsh-0.1.5rc1-post-u8.278`, manifest
`sha256:8c9eeb1569643054a67e71e31ecab10d843035050de944b638b1485cd83afe3e`.
The SDK/runtime-bin stayed at 0.1.5rc1 and the root-scoped profile at 0.1.2rc1.
The model key was copied only into ignored target configuration and never
printed. Only Runtime was recreated, without rebuilding its image; the other
12 container identities/states were unchanged. Data/ML Workers stayed stopped,
TuShare credentials absent and F6 disabled.

Private evidence root: `/tmp/byq-phase17-278`, mode 0700; files are private.
The fresh `a1-runtime-preflight.json` has SHA-256
`73e3f9e1c3cc88128087dccd1a2e488ba2112de8f19944479d8fbd9316361d00`.
It verified no configured user model binding and the official default route,
exact Runtime/image/embedded manifest, owner, Workspace and fresh pool/snapshot.
Initial read-only preflight mistakes (unsupported list limit 1000 and an
incorrect expectation of an empty virtual model-binding list) remain preserved;
no Agent session or turn was created by either failure. The corrected preflight
and narrow driver read-limit correction passed Tester, Reviewer and Root.

The granted input content SHA-256 was
`09f95a7b8766bff355d139f6b0834d7c609f7a0336c40b78eba776037184bcfd`.
The executed driver SHA-256 was
`c841197de2b6233a5bc7b0d39f6bcc099536bc66731ceb503e9788bf9dd775c6`.
A checked wrapper and exclusive attempt files allowed one submission only.
They are local safeguards; the Product session/turn API has no caller-key or
server-side deduplication contract. Unknown outcomes allow only read-only
reconciliation. The grant is now **spent**, regardless of acceptance failure.

| Actual identity | Value |
|---|---|
| Conversation | `conversation_6e05f478f4b241cdb442e3fce26a4938` |
| Trace | `byq-trace-f09440ec8a574b3eb738881fb45964b0` |
| Foreground run | `663093c5be9d4522a07737c9e55f4805` |
| Native root session | `session-303dc40d790f453d9e01d9b2905d496f` |
| New Task | `task_67e9796f11ae47b6b2148b473d69f5bc` |
| New Artifact | `artifact_bcc47e170b334c40914bf33110641f79` |

The turn received `202 Accepted` at 2026-09-30 09:59:52.590 UTC. The same run
reached `session.result`, finish reason `completed`, at 10:01:34.962986 UTC.
The captured workflow contains 23 events and one terminal session result.
No second input was submitted.

## Persistence, browser and native observations

Read-only Product checks returned 200 for the same conversation, answer delivery,
Task and Artifact. The user and nonempty assistant messages are durable;
answer delivery is `up_to_date`, with zero pending/exhausted/rejected events.
The browser rendered the actual answer in Agent and the new Task in Research
Center through Frontend/Gateway Product routes, with zero blocked foreign-origin
requests and zero model inputs from these inspections. Seed objects are present
but are not counted as research acceptance.

The driver's original `a1_user_message_count=0` is a checker false negative.
Backend Catalog collapses whitespace using `" ".join(value.split())`; the saved
turn body equals the raw authorized input, and the persisted/replayed user
message equals its normalized form (SHA prefix `438e157e`, length 556). Original
receipts and reports were not rewritten. The immediate terminal read preceded
assistant persistence; later read-only checks confirm delivery completed.

The new `web_research_evidence` Artifact is draft. Its content SHA-256 is
`0566aeb604b0c21fd3a7dc1d26753530bb8a268b8eb06f64c39bb129d5a4544a`.
It has seven unique HTTPS sources and lineage to the new Task, existing fresh
pool `stock_pool_ba455d1da20c435a8b6ab3c233c5d8a4`, and frozen snapshot
`stock_pool_snapshot_48f5fdb0812f50ff82b66f1d5bd86ae8c7dc5b826d201426e95728fe649915de`.
Publication dates are unknown and claims remain `UNESTABLISHED`; these are
research notes, not authoritative market data or independently qualified facts.

Root saved the exact current Native V3 compressed file once, then performed
bounded offline libzstd decoding and emitted only allowlisted metadata/counts.
Compressed SHA-256:
`3c846f1fc3dc0bf0c03253b9e29c13d44fb71275d10b73fb0bfa3efe17a54436`.
The 111 native JSONL records show one root turn, context provider/model
`deepseek-official` / `deepseek-v4-flash`, one `web_search` call with one query,
and one `byq_market_daily` read of `000001.SZ`, 20240102–20240531. There are zero
native delegate calls; target path inventory contains one root directory and
one Native session file. This is local execution evidence, not raw provider
HTTP request logging or a server-side guarantee about every network attempt.

Two Web-record tool calls occurred inside that same run, using the same key.
The first was rejected by MCP input validation because `content.usage_policy`
was missing; it did not reach the Backend factory. The second supplied it and
succeeded. Both supplied seven HTTP sources. This was not a second Root input
or another Web search; a local-file URL in search results was excluded from the
saved source set. The failure was not caused by that URL.

Runtime cumulative normalized usage reports 14 model calls, matching 14 native
usage-bearing assistant messages. This is **not** a raw model HTTP request
count; no before-run usage snapshot was measured. Native context confirms the
selected execution route; it does not expose raw request headers or prove an
exact network endpoint/request count. At observation, active sessions/prompts
were zero under one-process-per-root-turn ownership. The durable Product
conversation remains; physical-process survival or reattachment is not claimed.

Evidence files include `a1-run-evidence/*`,
`a1-product-persistence-readback.json`, `a1-browser-agent-evidence.json`,
`a1-browser-research-evidence.json`, `a1-runtime-post-observation.json`,
`a1-native-structural-inventory.json` and `a1-native-safe-execution.json`.
The earlier 31-check canonical cache validation is reused without a new source
read, import, SQL validation rerun or download. Its scoped completeness is not global.

## Real acceptance defect and repair boundary

The Task has `conversation_id=null`. Its handoff is
`blocked / conversation_binding_missing`, and the browser asks to associate the
original research conversation. A1 therefore does **not** pass the connected
Task/conversation handoff gate.

The Product Web-record endpoint forwarded trusted owner/trace, but its atomic
Task factory bypassed the canonical Task session-to-conversation validation.
Trusted runtime session ID already suffices; no new caller-supplied conversation
field or header is needed. The repair passes full trusted Workspace context,
uses the same Backend-owned validation in the factory transaction, and inserts
the mapped conversation ID. Existing Task replay requires that same binding;
NULL or other-conversation rows cannot be retroactively rebound. Non-Product
stateless calls retain their explicit unbound contract. No existing A1 Task was
modified to simulate an Agent success.

The source repair has a new `.280` candidate identity. The actual `.278` execution evidence
is preserved; `.280` had no live Agent acceptance at the source gate. The target was still `.278`
at the source gate; its subsequent preparation update is recorded below.
The unexecuted `.279` candidate was frozen after new tests exposed a fixture
contract error: generated source IDs were supplied where candidate source
indexes are required. The initial 11-passed/4-failed result included four early-rejection
false positives and is not the binding gate. The fixture and exact error-detail
assertions were corrected; all eight new cases then passed. Seven unaffected
existing cases passed on the first run and are reused. `.279` was never built
or installed on the target. Selected `.280` manifest:
`sha256:828b58684ae05f50f5e74995352ef30bc16295ce0740c44020426ca2f1c0d947`.
Focused source tests and independent review are tracked separately below.

## Gates and remaining work

- Actual A1 evidence: independent Tester and Reviewer verified submission,
  normalized input, persistence, browser objects, scoped cache and native
  provider/tool observations. Root accepts this partial evidence; full A1
  handoff remains BLOCKED. No retrospective A1 PASS is issued.
- Binding repair: independent Tester verified eight final new identity/replay
  cases and seven unaffected Web-record/concurrency/canonical-binding cases
  in a fresh temporary `byq_domain_test` on an internal network and tmpfs.
  The existing target and source databases were not test fixtures. Candidate
  `.280` identity gate passed 13/13 (current build 3, revision 4, retirement 5,
  changed architecture selector 1). Exact temporary resources were removed,
  and the existing target still matched its 13 latest container/image pins.
  Independent Reviewer: **Functional PASS / Tests PASS / Clean Break Architecture
  PASS**. Root: **SOURCE SLICE PASS**, limited to this repair and identity.
  `.280` live Agent qualification was pending at that checkpoint.
- Later A inputs, B–F, enabled F6, new TuShare qualification, actual CPU Worker
  restart, populated reset, exact-head hosted CI and repository gates remain
  pending. No later model/provider permission is inferred from this spent grant.
- No Phase 17 push, PR, merge, deployment or release was performed or authorized.

## `.280` target preparation after the source gate

Root committed the qualified source at
`afe529aa5ad264d5932ef14a7b354ca09cb37e2e`. The independently reviewed private
`prepare-280-target.py` (SHA-256
`0e368e5de7875e68c4f3fd23f9bcc6293223fd3197b6491c75a0c4218ebd469d`)
was hash checked by the launcher and executed once in the exact existing fresh
target scope. Only Backend and Runtime were built and recreated with
`--no-deps`; no DB restore, manual Task binding, source export/import, download
or model input ran. The unexecuted `.279` candidate was not built.

New Backend container:
`e7c4f718fe97fa7cc36c947357e7303df8c0443e5e0caa5105b61f06d3b17c49`,
image `sha256:40303cf15b471d4e2260d73fb07e5adb76e43b1ed2a2bff8d8e57785a92994b5`.
New Runtime container:
`a7f7e72d8c2671a7cd3b4cba92be63173a5005f001e5279387038d82ddcc9b80`,
image `sha256:4fca5f56734683f418a085bbfb815ce436232ec31e3069854f682d0a7e8ce545`.
Actual Backend main/research/test file hashes match selected `.280` inputs;
Runtime embeds the exact `.280` manifest. Other 11 service IDs/images/states and
all mounts, five volume names and two network names match the pre-operation
pins. Data/ML remain stopped, TuShare absent, F6 disabled and the existing model
key configured. The prior Runtime had active/prompts 0 and cumulative usage 14;
the new Runtime has active/prompts/usage 0. This is a process replacement and
counter reset, not an Agent continuation claim or a measured A1 usage delta.

Normal durable login and four read-only Gateway/Product GETs verified the same
Workspace, original unbound A1 Task with `conversation_binding_missing`, identical
Artifact hash/content/lineage and unchanged pool snapshot. These are preservation
checks; they do not prove a new Agent used the repaired factory. No populated
Workspace reset or reseed ran. Current Gateway/Frontend origins remain
`http://127.0.0.1:32867` / `http://127.0.0.1:32866`; verify live pins at admission.

Private fresh pins and results: `/tmp/byq-phase17-280/environment.json`,
`target-prepare-attempt.json`, `build.log`, `recreate.log`,
`product-preservation.json`. Independent Tester **TARGETPREPARATION PASS**
verified exact live identities, source/manifest hashes, state and preservation.
Independent Reviewer **Functional PASS / Tests PASS / Clean Break Architecture
PASS**; Root **TARGET PREPARATION PASS**, limited to this two-service update and
preservation. At that checkpoint, no `.280` foreground grant or input existed;
the original `.278` A1 remained HANDOFF BLOCKED.

The subsequent proposal was **one additional foreground A1 input**
on this `.280` source/build, official Flash, a fresh Product conversation and new
Task/Artifact/key. It must verify original-conversation discovery and handoff,
using the existing exact pool/snapshot and 98-session cache. Intended Web use is
one search/query; native five-use/four-query limits and no raw model-request hard
cap remain disclosed. Delegation, market download, F6, provider fallback and
automatic input replay remain excluded. Fresh route/subject/runtime preflight
and a new exact one-shot grant are required before submission; the spent `.278`
grant cannot admit it. This proposal does not authorize any later Golden input.


## Actual `.280` A1: new-conversation binding qualification

The maintainer replied **“好的继续”** to the one-additional-input proposal.
This authorized exactly one fresh foreground run on official Flash, the existing
98-session cache/pool/snapshot and one intended Web query. It excluded delegation,
market download, F6, provider fallback, input replay and source/ordinary/Community
DB access. Native Web limits remained 5 uses × 4 queries; raw model HTTP calls
had no hard cap. The old `.278` grant was not reused. The new grant is now spent.

The selected app/source is `afe529aa5ad264d5932ef14a7b354ca09cb37e2e`, build
`dsh-0.1.5rc1-post-u8.280`, manifest
`sha256:828b58684ae05f50f5e74995352ef30bc16295ce0740c44020426ca2f1c0d947`.
The pre-send branch head `d29ab6e80268ccbecd58ca88f883875fd104e347` had only docs
changes after that source commit. No service was recreated during this run.
Fresh admission passed Tester → independent Reviewer → Root before submission.
Private preflight SHA `ff4fad3fad30db9dd8bc55a9321ab63449ce0ffd36fcd5ed1095020c2b9d2e1d`,
grant SHA `7f9af32fcb8c554370e1e7845ff3fa800782c9049060ee96a4d92ca185fd50e0`,
input-content SHA `490362c26259d5b83c31158de00c4fae678b27b62619760b45911098385535d7`,
and runner SHA `b8b0595cb0e3ac5fb97af24f5c2e392ea50bb534f5aca7a5e3f0f1c48a155447`
are linked in the new private grant. Exclusive attempt markers preceded the sole
session/turn submission; API caller-key deduplication is still not claimed.

| Actual `.280` identity | Value |
|---|---|
| Conversation | `conversation_b31ebeedbc814b9da09be44b2a28ae2b` |
| Trace | `byq-trace-1f605d321d4a4db6a7099c1d7cdc9753` |
| Foreground run | `a093e7e7fc744ec7ab21237993aa6d28` |
| Native root session | `session-0f4bcdf7023a4cd79192f4a2f7d2d1fd` |
| New Task | `task_a1f4260a30ba4ac79a062f4358ed390b` |
| New Artifact | `artifact_78ca187f18ed4f0880e84201e3231c14` |
| Web record key | `phase17-280-a1-web-20260930-01` |

One `202 Accepted` arrived at **11:37:54.637 UTC** on 2026-09-30. The same run
reached `session.result` / `completed` at **11:39:25.100402 UTC**, with 23 workflow
events. The runner matched exactly one normalized user message. Its immediate
terminal read preceded assistant persistence; later Product reads show one user
and one nonempty assistant, delivery `up_to_date`, and zero pending/exhausted/
rejected events. There was no second input or observation timeout.

Product GETs returned 200 for this conversation, Task and Artifact. The Task's
`conversation_id` equals the new conversation. Native `byq_agent_context` changed
from `none_bound` before save to `available` with exactly this Task afterward.
The handoff is **`needs_permission` / `permission_missing`**, rather than
`conversation_binding_missing`. This is expected without a continuation grant;
no F6 grant or automatic research dispatch was requested to turn it into ready.
The old unbound `.278` Task was not modified or retrospectively qualified.

The draft `web_research_evidence` Artifact has eight unique HTTPS sources,
three `UNESTABLISHED` claims and unknown publication dates. Content SHA:
`5cc9c48eb314a12209597f1783ec2a3234cde90305d7640962f8b82b9943c2aa`.
Lineage identifies the new Task and the same existing pool/frozen snapshot.
These are dated research notes, not independently established facts.

The exact current Native file has compressed SHA
`fdceb5709044a7ef577fd2ec358ac2b99327aeb72060e1e55054f655a8af6883`.
Its 89 records show one root turn, official Flash context, one Web Search/one
query, one successful Web-record tool call, two research GETs and two context
calls. There are no delegate calls or child session files. The retained old root
file is excluded from current-run counts. Cached market read is exactly
`000001.SZ` / `20240102–20240531`, 98 rows, verified calendar, no missing sessions,
`persisted_byq`, `live_provider_called=false`. Native authorization actions only
cover session context, cached market read and Web-record creation. No market
synchronization, jobs or continuation-permission writes occurred.
Runtime active/prompts returned to zero. Its normalized `model_calls` changed
**0 → 9**, matching nine usage-bearing Native assistant messages. This measured
normalized delta is not raw model HTTP request count, which remains NOT_OBSERVED.
Data/ML stayed stopped; TuShare absent and F6 disabled throughout.

Real browser checks rendered this new answer in Agent and the new Task in
Research Center through Frontend/Gateway Product routes. The final read-only
browser collection made 130 requests, zero blocked foreign origins and zero
model inputs. Two earlier read-only attempts timed out on the old “本轮结果”
label and `networkidle` while SSE remained open. Their Product records are
preserved; the final collector waited for the actual new Task in assistant and
Research DOM. No model input was replayed in response to either checker timeout.

Private evidence: `/tmp/byq-phase17-280/a1-run-evidence/`,
`a1-native-{file-inventory,structural-inventory,safe-execution,binding-coverage}.json`,
`a1-native-session.v3.jsonl.zstd`, `a1-runtime-after.json`,
`v3-a1-product-persistence-readback.json`, `v3-a1-browser-{agent,research}-evidence.json`
and `v3-a1-{agent,research}-browser.png`. Direct Product readback SHA:
`5c3643696daf39028705686ffdf389a9c8d8b96667f93715a136928545aa2dbe`.

Actual-result independent Tester **PASS**; independent Reviewer **Functional /
Tests / Clean Break Architecture PASS**; Root **BOUNDED A1 / BINDING REPAIR PASS**.
These gates cover the sole actual input, normalized receipt/delivery, source/model
identity, cache/Web limits, new Task binding/discovery, Artifact lineage, browser
and this four-document evidence update. Private metadata was tightened to 0600
without changing bytes. This bounded run verifies A1 research persistence and the
repaired conversation binding. It
does not qualify F6, A2/A3, all Golden A, B–F, hosted CI or Phase 17 completion.
No prior regression suites, source export/import or market download were repeated.
