# Phase 17 — Actual A1 and conversation-binding repair

Status: **A1 EXECUTED / HANDOFF BLOCKED; Phase 17 OPEN**. This records one
explicitly authorized foreground run, not final Golden acceptance. Source repair
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

The source repair has a new `.280` candidate identity. The running `.278` target
and its execution evidence are preserved; `.280` has no live Agent acceptance.
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
  `.280` live Agent qualification remains pending.
- Later A inputs, B–F, enabled F6, new TuShare qualification, actual CPU Worker
  restart, populated reset, exact-head hosted CI and repository gates remain
  pending. No later model/provider permission is inferred from this spent grant.
- No Phase 17 push, PR, merge, deployment or release was performed or authorized.
