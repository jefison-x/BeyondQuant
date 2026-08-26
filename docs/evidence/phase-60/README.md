# Phase 60 acceptance evidence

Date: 2026-08-26

## Environment

- Repository: `jefison-x/BeyondQuant`
- Base: `origin/main` at `8993ffac72ad38fbcd5d8ec596d452dad4730d4c`
- Branch: `phase/60-public-answer-projection`
- Product URL: `http://127.0.0.1`
- Browser: real Chrome through Chrome DevTools MCP
- Runtime: DSH SDK/runtime `0.1.1rc1` / npm `0.1.1-rc.1`
- Data provenance: persisted Tushare-normalized BYQ rows; Phase 60 made no
  Provider call and did not mutate market data.

ADR-0033 bounds this phase to public answer/activity projection. Domain values,
MCP schemas, role permissions, approval, synchronization and Backtest semantics
remain unchanged.

## Implemented contract

1. Runtime Adapter projects only text-only final DSH assistant messages. Any
   assistant step containing a tool call is operational and cannot become a
   public answer fragment.
2. Runtime Adapter and Gateway share an idempotent closed terminology mapper.
   Accepted valuation/fundamental and coverage terms are localized without
   changing symbols, dates, values, signs or missing facts. Gateway fails closed
   when a known internal token remains.
3. Public activity includes only allow-listed domain work. Agent context, role
   lookup, run start, authorization, audit and unknown tools remain operationally
   real but are not shown to ordinary users. New activities omit raw capability
   identifiers.
4. Turn and tool activities close with stable activity IDs. The frontend renders
   closed phase/state values as Chinese product labels.
5. DSH role skills require tool-only intermediate steps, one final user answer,
   and evidence-bound security-specific claims. They must not explain valuation
   differences with unqueried profitability, asset quality, growth or risk data.

## Automated verification

- Architecture suite: `50 passed` after advancing the stable completed-phase marker.
- Runtime Adapter normalization/compatibility: `34 passed` against the mounted
  final source and role skills.
- Gateway workflow projection: `58 passed` against the mounted final source and
  shared contracts.
- Frontend unit suite: `33 files, 80 tests passed` with the precise lockfile
  Vitest version.
- Frontend `vue-tsc` plus production Vite build passed.
- Path-aware local CI passed all 8 applicable checks: diff, architecture,
  Gateway, Runtime Adapter, locked frontend install, production build, 80 unit
  tests and dependency audit (zero vulnerabilities). GitHub checks remain the
  final PR merge gate.

The first browser comparison correctly returned stored values but inferred that
招商银行's valuation premium reflected higher return on equity and asset quality,
although those fields had not been queried and were unavailable in the database.
The role evidence rule was tightened before acceptance. A second browser run then
explicitly stated that the cause could not be established. A separate activity
regression found “理解请求” stuck in progress; stable turn activity IDs and a
terminal activity event fixed it before the final runs below.

## Real browser journeys

### No-tool public capability answer

- Conversation: `conversation_085d268dc244405c84904370091c237b`
- Prompt asked for one sentence without data tools or internal terminology.
- The final answer described market data, factor research, strategy design,
  Backtest analysis and iteration entirely in user-facing Chinese. It contained
  no DSH/MCP, orchestration, governance, authorization or audit vocabulary.
- Public activity contained only `理解请求 / 理解需求 / 已完成`.

### Persisted valuation tool journey

- Conversation: `conversation_db0331ef29aa4ab4bf4e652eb0ff697a`
- Prompt queried only PE TTM, PB and dividend yield TTM for `600036.SH` and
  `601166.SH` on `2026-08-25`.
- Displayed values matched persisted Phase 59 evidence after rounding:

| Symbol | PE TTM | PB | Dividend TTM |
|---|---:|---:|---:|
| `600036.SH` | 6.61 | 0.88 | 5.10% |
| `601166.SH` | 4.92 | 0.46 | 5.92% |

- The answer correctly limited the conclusion to the three queried measures and
  explicitly said the reason for the valuation difference could not be judged
  without profitability, asset-quality and growth evidence.
- No intermediate “data retrieved”, authorization/audit narration, raw
  `coverage.usable`, field key, capability ID or Artifact/WorkflowTrace token was
  displayed.
- Public activity contained only `读取估值数据 / 研究数据 / 已完成` and
  `理解请求 / 理解需求 / 已完成`.

## Browser technical evidence

- Final Console: no messages.
- Final Network: same-origin Product routes only. Login/session/workflow reads
  returned 200, session creation returned 201, and turns returned 202. There were
  no 4xx/5xx responses and no Browser request to Backend, MCP, DSH, PostgreSQL or
  Tushare.
- Screenshots:
  - [`final-public-answer.png`](screenshots/final-public-answer.png)
  - [`final-no-tool-activity.png`](screenshots/final-no-tool-activity.png)
  - [`final-tool-activity.png`](screenshots/final-tool-activity.png)

During candidate deployment, one Compose invocation omitted the established
`-p beyondquant` project name and created three duplicate candidate containers;
the duplicate Gateway could not bind port 8100. Those exact duplicate containers
were removed without volumes or data changes, and the accepted candidate was
rebuilt in the existing `beyondquant` project. This was a deployment-tooling
correction, not a product runtime failure.

The first local CI invocation also exposed a pre-existing runner bug: mocked
Gateway/Runtime checks referenced a PostgreSQL network that those checks never
create, and a prior root container had left the generated frontend dependency
directory root-owned. The network dependency was removed from those isolated
mocked checks, generated-file ownership was repaired, and the complete applicable
local gate then passed. No Product contract was weakened.

## Community and boundary evidence

The Community frontend/runtime inspection and classification are recorded in
[`COMMUNITY_CHECKLIST.md`](COMMUNITY_CHECKLIST.md). Community source, database,
cache, credentials, runtime and Git history remained read-only. Phase 60 did not
add PydanticAI, Hermes, a second harness, direct DSH database access, direct
Browser domain access, or application-source write access.

## Acceptance result

Phase 60 is accepted. Ordinary users now see one evidence-bound final answer and
localized, terminal domain progress while internal execution and audit mechanics
remain behind the Product boundary. Meaningful dates, values, missing-data facts
and recovery guidance are preserved. No later Product Phase is defined by the
current roadmap; release, tag and production publication remain separate human
decisions.
