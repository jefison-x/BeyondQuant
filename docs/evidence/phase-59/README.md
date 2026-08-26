# Phase 59 acceptance evidence

Date: 2026-08-26

## Environment

- Repository: `jefison-x/BeyondQuant`
- Base: `origin/main` at `cd44c204bbf83742f7fe08912c807796e5002117`
- Branch: `phase/59-agent-market-research-read-path`
- Product URL: `http://127.0.0.1`
- Browser: real Chrome through Chrome DevTools MCP
- Runtime: DSH SDK/runtime `0.1.1rc1` / npm `0.1.1-rc.1`
- Provider provenance in persisted rows: Tushare

ADR-0032 bounds Phase 59 to read-only, persisted point-in-time valuation and
reported financial evidence. It does not authorize provider calls, automatic
sync, arbitrary fields, pool writes or Phase 60 public-projection changes.

## Implemented contract

1. `byq_market_valuation` reads at most 20 canonical A-share symbols for one
   exact session and a closed ADR-0030 field list.
2. `byq_market_fundamentals` reads the latest report with
   `effective_date <= as_of_date`, where effective date remains the conservative
   day after announcement.
3. Both responses retain hashes, completeness, missing symbols/reports and
   `coverage.usable`. They never call Tushare or fill a missing value.
4. Only `quant_orchestrator` and `market_researcher` v1.2.0 gain the two reads.
   Existing write, approval, execution and provider boundaries do not change.

## Automated verification

- Architecture: `50 passed`.
- Focused Backend: initial `14 passed`, corrected cross-phase `12 passed`, and
  final null/missing-field coverage regression `16 passed`.
- Complete PostgreSQL-backed Backend: final `166 passed, 1 skipped` in `104.36s`.
- Runtime Adapter/DSH compatibility: `29 passed` in a clean credential-free
  container. Running the same fixture inside the configured Product container
  intentionally invalidates its no-credential premise and is not the accepted run.
- MCP TypeScript image build passed.
- Complete live MCP suite passed health, contract/tools-list, market, research,
  factor, strategy, Stock Pool, Paper Trading, Backtest, Agent, learning and
  WorkflowCard tests.
- `git diff --check` passed during implementation checks.

The first full Backend run found one stale Phase 58 assertion expecting
`quant_orchestrator` v1.1.0. Phase 59 intentionally upgrades that role to v1.2.0;
the explicit regression expectation was updated, then the focused and complete
suites passed. No product invariant was weakened.

## Persisted data ground truth

The product PostgreSQL database reported exact `market_daily_basic`
completeness through `20260825` with 5,546 rows. Read-only ground truth for the
accepted comparison was:

| Symbol | Trade date | PE TTM | PB | Dividend TTM |
|---|---:|---:|---:|---:|
| `600036.SH` | `20260825` | 6.6083 | 0.8797 | 5.1038 |
| `601166.SH` | `20260825` | 4.9204 | 0.4595 | 5.9156 |

`market_financial_indicator_completeness` contained zero rows. This was retained
as real missing-data evidence rather than inserting a test fixture into the
product database.

## Real Product Agent journey

- Conversation: `conversation_ec2e5493d8774329948fec9106249880`
- Runtime trace: `byq-trace-d00fb82710344c5993ddbe7f58b7ebee`
- Agent run: `agent_run_edd6215e6bdb41babbb7fd893071f1de`
- Role: `market_researcher` v1.2.0

First turn compared `600036.SH` and `601166.SH` through 2026-08-25 using five
daily sessions plus exact-date PE TTM, PB and dividend yield. The answer matched
the persisted values after display rounding, correctly found China Merchants
Bank stronger over five sessions and Industrial Bank cheaper on PE/PB with a
higher dividend yield, and stated the price and valuation cutoff.

The same conversation then requested ROE, net-profit growth and debt-to-assets.
The tool returned zero rows, `coverage.usable=false`, and both symbols as
`coverage_unverified`. The answer refused to rank or infer quality, did not use
general knowledge or another source, and recommended synchronizing and
validating the financial dataset in Data Center before retrying the same
point-in-time date.

Persisted audit order:

```text
byq_market_daily        authorized → success → success (one bounded call per symbol)
byq_market_valuation    authorized → success
byq_market_fundamentals authorized → success (honest unavailable coverage result)
```

There was no denied action, 4xx/5xx storm, provider call from the Browser, direct
database access by DSH, or fabricated financial value.

## Browser technical evidence and Phase 60 hand-off

- Console: no messages.
- Network: same-origin Product routes only; turn submissions returned 202 and
  session/workflow reads returned 200/201. No Browser request targeted Backend,
  MCP, DSH, PostgreSQL or Tushare.
- A Chrome viewport screenshot was captured during acceptance. The DevTools MCP
  filesystem policy rejected repository-path persistence, so the image was not
  added as a repository artifact; DOM, Network, Console, conversation/run/trace
  identities and database hashes are retained here.

The data behavior passed Phase 59, but the public answer exposed internal
execution narration such as an English “Data retrieved” preface, authorization/
audit mechanics and raw `coverage.usable`/field names. This is not fixed in
Phase 59 because ADR-0032 explicitly stops at the Phase 60 projection boundary.
It is recorded as the primary real-browser input for Phase 60.

## Acceptance result

Phase 59 is accepted. A normal user can obtain verified exact-date valuation,
see the effective data date, and receive an honest actionable response when
fundamentals are absent. The Agent does not silently substitute a later report,
external source or inferred value. Public-language cleanup remains Phase 60.
