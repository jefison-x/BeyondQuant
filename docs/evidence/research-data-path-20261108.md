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
