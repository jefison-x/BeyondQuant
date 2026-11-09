# Research data path — bounded optimization (2026-11-08)

## Scope and authority

Maintainer request: “好的，按你的这个思路，看看可否优化一下我们的数据获取路径。”
This is bounded maintenance in the existing isolated
`codex/research-experience-20261107` worktree, based on
`2cf7735117fd8f691465d5273dbb436d4937a7ad`. It does not advance Product Phase,
authorize production deployment, or qualify a new external MCP capability.

## Verified data paths

- `services/mcp/src/market-data.ts` calls Backend persisted research reads.
  `byq_market_session_context`, `byq_market_daily`, `byq_market_valuation` and
  `byq_market_fundamentals` do not refresh a live provider.
- `services/backend/app/data_provider.py:TushareProvider` already implements
  Tushare API access, with bounded normalization, provenance and provider errors.
- `services/backend/app/provider_runtime.py` resolves the active system
  credential first, then the configured environment fallback. Engineering
  inspection inside the running Backend confirmed `environment` for this probe;
  no credential was exported or written to the evidence.
- `byq_data_demand_create` currently needs a frozen stock-pool/date scope or an
  index snapshot request. A lightweight single-stock, missing-fields preparation
  request does not yet exist. This slice does not extend its authority or schema.

The retained [latency evidence](research-experience-20261107.md) measured
557.730 seconds for one research turn: model requests 383.456 seconds, web search
142.362 seconds, web fetch 26.201 seconds. Six BYQ market-data reads totaled
0.382 seconds. This supports reducing unnecessary research work; it does not
establish a database bottleneck or a general response-time baseline.

## Official Tushare comparison

The [official MCP configuration page](https://tushare.pro/document/1?doc_id=463)
documents a remote endpoint with a token in its path and configuration obtained
from the account's MCP Server page. No third-party MCP package was installed.

Two bounded initialization probes used the documented endpoint shape: first the
local existing `.env` credential, then the actual Backend credential resolution.
Both returned HTTP 401. The Backend probe completed in 129 ms with the fixed
response `{"error":"missing_token"}`. Redirect following was disabled and no
secret-bearing URL was printed. Initialization did not succeed: tools/list,
MCP data calls, tool coverage and transport/session compatibility are **NOT_RUN**.
No repeated credential guessing or alternate authentication probe was attempted.
This response does not establish an invalid token or insufficient data rights;
the current account-generated MCP configuration still needs confirmation.

Three read-only HTTPS API probes used that Backend-resolved token, without
model calls, synchronization, persistence, configuration changes or jobs:

| API | Bounded request | Result | Elapsed |
| --- | --- | --- | --- |
| daily_basic | 600036.SH, trade_date 20261106, five selected fields | HTTP 200, code 0, one row | 236 ms |
| fina_indicator | 600036.SH, period 20251231, five selected fields | HTTP 200, code 0, one row | 140 ms |
| dividend | 600036.SH, end_date 20251231, five selected fields | HTTP 200, code 0, two rows | 133 ms |

The dividend response included proposal and implementation records; these are
not two additive payouts. The probes establish access to these exact samples,
not full API entitlement, financial-report correctness or general latency.
API versus MCP data-speed comparison remains **NOT_RUN** because MCP did not
initialize. The upstream data was not imported into BYQ research or backtests.

## Candidate behavior change

Only the current ACP Product profile, its matching hashes and the two Product
research skills change:

1. For stock research summaries/comparisons, preserve an explicit historical
   as-of; check session context when a current/latest cutoff or exchange-session
   determination is needed. Obtain needed durable BYQ fields before delegating
   public-background research.
2. Reuse applicable evidence only for matching symbols, fields and as-of scope;
   updated-data requests check the cutoff again. Each new read retains its own
   authorization and audit.
3. Delegate the remaining public questions with compact values, dates,
   provenance and explicit coverage gaps. Evidence does not transfer authority;
   child AgentRun binding is unchanged.
4. Request a compact sourced handoff for a brief summary, avoid duplicate reads
   and a second full report, and stop when requested topics are supported or
   explicitly unresolved. Conflicts and missing provenance still need checking.
5. Missing persisted metrics remain gaps. No implicit refresh, automatic data
   demand, provider credential access or webpage substitution is introduced.

No tools, privileges, model settings, generic runtime mechanisms, historical
profiles, database schema, provider implementation or running containers change.
The profile instructions guide model behavior; they are not a deterministic
scheduler or a measured guarantee of faster research.

## Validation

- PASS: existing ACP profile/version/build and plugin-registry contracts:
  `python3 -m pytest -q tests/architecture/test_acp_authoritative_version.py
  tests/architecture/test_dsh_authoritative_version.py
  tests/architecture/test_dsh_authoritative_build.py
  tests/test_dsh_plugin_registry.py` — 37 passed, 20 subtests passed.
- PASS: scoped `python3 scripts/ci/dev-check.py --base
  2cf7735117fd8f691465d5273dbb436d4937a7ad` syntax checks; component tests and
  remote CI remain separate gates. `git diff --check` passed.
- Independent source review found no blocker. Its suggestion to avoid an
  unnecessary current-cutoff lookup for fixed historical queries was applied
  consistently to both personas and skills; the 37 tests and 20 subtests passed
  again after that adjustment.
- NOT_RUN: candidate image build, candidate Product/browser research,
  end-to-end latency comparison, MCP tool/data qualification, hosted PR CI.
- No push, PR, merge, release or deployment. Existing test/production
  environments, pages, credentials and data are retained.

## Retained test deployment and paired result (2026-11-09)

After ADR-0117 exact historical recovery, the same question was submitted once
per profile through the existing test Gateway with unchanged user/model/search
credential version and execution options. Baseline 316.582s versus candidate
264.778s (16.36% shorter); model calls 33→29 and model time 235.156→141.937s.
Search calls remained 10 and their time increased 68.433→114.029s. This supports
less generation work in this pair, not faster database reads or a production SLA.

Quality is not accepted: the candidate changed a source URL during the child
handoff and left the official dividend denominator unresolved (33.9% calculated
using total attributable profit versus official 35.34% using ordinary-shareholder
profit). Local market data is absent in both runs; public-source coverage differs.
Keep the candidate in test only. Exact IDs, timing method, primary-source checks
and remaining issues are in [the experience evidence](research-experience-20261107.md).

## Source fidelity and dividend basis repair (2026-11-09)

Maintainer explicitly authorized fixing the two retained quality defects, updating
only the retained test environment, and rerunning the identical question;
production must not change. Starting head: `cd9f97f6`.

The current Product coordinator/market-research personas and their skills now
require a compact source list copied from actual web results, with exact URLs,
report periods and supporting excerpts. The coordinator preserves those URLs
and checks claim support against the handoff. Dividend research must distinguish
cash dividend, payout ratio and yield; period, units, distribution status and
ordinary-shareholder profit must agree. A ratio conflict triggers a focused
primary dividend-table/notes check. Failed retrieval remains a verification gap;
third-party summaries are attributed to their actual source, never silently
promoted to company disclosure. No company-specific values are hardcoded.

This is a research-instruction repair, not a deterministic URL validator or a
new runtime harness. Tool privileges, provider/model settings and persisted
market data are unchanged. The independent reviewer accepted the boundary and
requested the source-attribution clarification, which was applied. Existing
profile/version/build/plugin contracts passed: 37 tests, 20 subtests. Actual
same-question quality/latency remains NOT_RUN until the candidate run below.


### Candidate deployment and first quality run

Source commit `624c8829`, unified ACP candidate
`sha256:0d87206caf37eb0a849c1444e7bb56ed5db5b0b91c4039b635a14ee5c3b73249`.
The four changed image files were read back and hashed against source. Only
`runtime-adapter`, `acp-product-runner`, `acp-product-runner-secondary`, and
`acp-judgment-runner` changed image in the retained operator Compose; all became
healthy. No current authorized root or running domain job was present before
deployment; two October 21 revoked/unconfirmed records were preserved. Production
17 container IDs, image IDs and start times matched the saved pre-update inventory.

The original question SHA256 remains
`20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7`;
model/search settings and execution options matched the retained baseline exactly.
First run: `conversation_70dec1ce04dc47acaa09dba020619a9c`, root
`1274bf9d61c24dbe914768a8b1584eb6`. It was soft-cancelled via the Product API
at 861.189s of Backend root lifetime (cancelled/closed, unknown business claims 0).
This is **not a completed-answer latency**. The final generation was interrupted;
no research answer reached the conversation. Its one cancelled provider request
has unknown usage; 29 other model requests returned HTTP 200.

The child handoff did complete shortly before cancellation: all 7 handoff URLs
occur verbatim in actual web_search/web_fetch results (delegate outputs excluded
from the provenance corpus). Its dividend section correctly identifies CNY 50.843 billion / CNY 143.874 billion = 35.34%, using
ordinary-shareholder profit. The source table is in CNY millions:
50,843 / 143,874 = 35.34%. This agrees with the official 2025 annual
report, printed pages 100 and 248. The model used a full announcement reproduction
and labelled the publisher; original-host retrieval was not universally available.
Child-handoff checks PASS; final-answer quality remains NOT_RUN for this sample.

Latency **FAIL**: one two-query risk-section search lasted **604.706s** before
returning `tool call timed out after 60000ms`. All searches totalled 687.481s;
model-request intervals 165.810s (includes the cancelled request), web fetch
3.410s, other tools 2.434s. The DSH base composition enables timeout-policy and
the search provider receives a cancellation signal. Source inspection shows
cooperative cancellation waits for the downstream promise; batch search waits
for all requests. No BYQ configuration omission was found. Which downstream
operation delayed settling is unproven; do not label the cause simply network,
a missing plugin, or the new research instructions. No DSH fork or new timeout
harness was added.

After confirmed cancellation/closure, one fresh same-version, identical-question
retest was started to finish final-answer acceptance. It does not erase this
failure or establish a latency SLA. No further blind retries are authorized by
this evidence record.

### Completed same-question retest and acceptance limits

Retest conversation `conversation_68c587f8655a419887bb7a8909acdc56`, root
`72168b1413e6415e92ab82e8f659bc83`: completed/closed with zero unknown business
claims. Backend UTC 2026-11-09 02:15:34.013951 → 02:19:51.928129,
**257.914178s**. All 30 model calls returned HTTP 200; model-request interval
union 185.801s, 6 searches 58.341s, 8 fetches 5.719s, local tools 4.468s,
unattributed gaps 3.585s, no cross-category overlap. Output tokens 24,783.
This is a single completed sample, not a stable latency guarantee. The previous
264.778s candidate and 316.582s baseline remain separate samples; research
coverage differs, so neither a same-quality speedup nor an SLA is established.

Targeted checks **PASS in this completed sample**:

- All four final citation URLs occur verbatim in actual web_search/web_fetch
  results; child handoffs are not used to establish web provenance.
- Concatenating the two saved assistant segments without separators reproduces
  the native final text exactly (4,581 characters). An initial inspection joined
  them with a newline and falsely suggested a broken URL. That inspection
  artefact is corrected, not attributed to Product transport. AgentView's live
  and replay paths concatenate same-run text without separators.
- The final answer identifies annual dividend 508.43亿元, ordinary-shareholder
  profit 1,438.74亿元 and 35.34%; it distinguishes payout ratio from price-based
  dividend yield, annual/interim amounts and total attributable profit. The
  dividend denominator agrees with the [official 2025 annual report](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20260327/e1efc81f-7ad9-41b7-9b02-5db202026930.pdf),
  pages 100 and 248. The report explicitly lists preferred-share and perpetual
  distributions; the answer's statement that its retrieved text lacked that
  separate list describes its limited retrieval, not absence from the report.

Overall quality **FAIL / not accepted**: before delegation, the coordinator
set research as-of to 2026-03-30 even though the user asked for current research
and never requested that historical cutoff. It conflated the test market-data
calendar cutoff with the public research as-of. The child followed that wrong
instruction, excluded later material, and the final answer used FY2025 instead
of available 2026Q3 financials and described the annual dividend as still
proposed. Thus correct arithmetic and faithful URLs do not make this an adequate
current research conclusion. No fixed date or company-specific figure was added
to product instructions to game the benchmark. This date-selection defect and
the native search cancellation delay remain open, alongside absent local CMB
market data and unverified data-center navigation. No further model reruns were
performed in this repair slice.

Validation scope: real test Gateway/Product API with durable user login; no
fresh browser-rendering acceptance is claimed. The current user page was left
untouched. Four ACP services remain on the candidate; all ten test containers
are healthy. Final production inventory again matched all 17 pre-update
container IDs/images/start times. No production change, push, PR, merge or
remote CI. Private raw evidence and both cancelled/completed test conversations
remain retained under the existing research-candidate-20261109 evidence folder.
