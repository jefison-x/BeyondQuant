# Phase 58 acceptance evidence

> 本文记录 Phase 58 Agent Domain Action Contract 的实现、真实 Product 验收与边界证据。
> 中文负责说明和结论；文件名、命令、字段、状态码、测试计数及原始标识保持英文原样。

Date: 2026-08-26

## Environment and scope

- Repository: `jefison-x/BeyondQuant`
- Base: `origin/main` at `94f621579b9cbca7a7475c500731974e8001aa0b`
- Branch/worktree: `phase/58-agent-domain-contract` /
  `/home/jefison/projects/.byq-worktrees/phase58-agent-domain-contract`
- Product URL: `http://127.0.0.1`
- Runtime: DSH SDK/runtime `0.1.1rc1` / npm `0.1.1-rc.1`
- Browser: real Chrome through Chrome DevTools MCP
- Data provider observed in the journey: normalized Tushare `daily`, latest valid
  trade date `20260825`

ADR-0031 bounds this phase to Agent Stock Pool list/get/create, the exact
StrategyDraft input contract, safe validation repair and the prerequisite
ResearchTask flow. Phase 59 valuation/fundamental capability and Phase 60 public
projection refactors were not started.

## Implemented contract corrections

1. `quant_orchestrator` v1.1.0 can list/get/create owner-scoped custom Stock
   Pools. Market research remains evidence-only; pool snapshot/lifecycle/delete,
   index/dynamic writers, approval and execution remain denied.
2. `strategy_researcher` v1.2.0 gains only `byq_research_task_create`, because a
   planned owner-scoped ResearchTask is the required prerequisite for validation.
   It still cannot transition tasks, write pools, approve or execute.
3. MCP and Backend now publish one `CustomStrategy` contract and the same closed
   `data_requirements` fields. The MCP success fixture is a genuinely valid
   strategy rather than `class CustomStrategy: pass`.
4. A Backend round-trip defect was fixed: omitting optional `description` no
   longer validates a draft and then fails version creation because the
   normalized empty description was rejected.
5. BYQ 422 detail is projected only when it is a bounded, printable string and
   contains no credential-shaped value or storage path. The stable error code is
   retained and the repair limit is one.
6. DSH role/market/strategy skills now require exact MCP action names, a fixed
   task-create → validate → version-create sequence, distinct authorization and
   audit records, signed-value/card cross-checks, and ordinary product language
   in public answers.

## Automated verification

- Architecture: `49 passed` (`python3 -m unittest discover -s tests -p 'test_*.py'`).
- Complete PostgreSQL-backed Backend: `161 passed, 1 skipped` in `102.85s`.
- Phase 58 focused Backend/contract run: `16 passed` in `9.81s`.
- Runtime Adapter/DSH compatibility: `29 passed`.
- MCP TypeScript build passed. The complete live MCP suite passed initialize,
  `tools/list`, health, market, research, factor, strategy, Stock Pool, paper,
  backtest, Agent, learning and WorkflowCard tests. The focused strategy schema,
  valid script and safe-error translation test also passed.
- `git diff --check` passed.

Existing Playwright CRUD and real Product API smoke coverage was inspected and
not mechanically repeated because Phase 58 did not change frontend code. New
model-driven behavior was instead verified through a real Chrome journey plus
deterministic Backend/MCP contracts.

## Real Product journeys

### Baseline discovery and immediate corrections

Conversation `conversation_6f54f0d6d22845fa9943bb3e9f053ea7`, trace
`byq-trace-fa67e85ea41c415d8cea0bc5f3a716fa`, first proved that the new pool
capability could create `Phase58 银行候选` from the prior two-stock candidate
context with no copied ID. It also exposed three remaining issues before final
acceptance: one invented authorization alias (`market_daily.read`), public role/
skill/runtime narration, and a claim that validation was audited when only
version creation had a result audit. The skills and contracts were tightened
before the final journey.

### Research to real Stock Pool

Conversation `conversation_3b086c0d94bb484cacdec5d0fd3b038e`, trace
`byq-trace-176a68a44eb0440cb196265b2683eb81`, used real normalized daily bars for
`600036.SH` and `601166.SH`, reported the `2026-08-25` cutoff and preserved all
signed returns. It then created the equal-weight custom pool `Phase58 复验银行池`.

The audit contains exactly the distinct successful actions:

```text
quant_orchestrator 1.1.0  byq_market_daily  authorized → success
quant_orchestrator 1.1.0  byq_pool_create   authorized → success
```

There was no denied action, no internal ID request and no public role/tool
narration. The Product Stock Pool page displayed the new pool, two members,
`v1`, the evidence date and 50/50 weights.

### Planned task to validated strategy version

Conversation `conversation_484a73fb1f0241bd9df217dd493d2b82`, trace
`byq-trace-29bbc1c05176456780309ebd72bf21fd`, started from a fresh conversation
and used `strategy_researcher` v1.2.0. The persisted audit proves the exact order:

```text
byq_research_task_create     authorized → success
byq_strategy_validate       authorized → success  (repairs_used=0)
byq_strategy_version_create authorized → success  (repairs_used=1)
```

Validation succeeded on the first exact `CustomStrategy` payload. The first
version-create request returned one bounded 422 identifier error at
`2026-08-26T05:17:14Z`; one informed correction returned 201 at
`2026-08-26T05:17:16Z`. There was no second failure, state/role guessing or ID
request. The final answer accurately disclosed the one correction in ordinary
language and did not expose role IDs, MCP tools, Artifact IDs, validator names,
workers or runtime details.

## Browser technical evidence

- Chrome DOM, click, fill, navigation, history, asynchronous activity, Console,
  Network and screenshots were exercised against the real Product.
- The accepted journeys used same-origin browser routes. Turn submission returned
  202 and page/Product reads returned 200; the Browser did not call Backend, MCP,
  DSH, PostgreSQL or Tushare directly.
- No Console error, warning or issue was observed in the completed journey.
- Backend logs show the single expected 422 → 201 repair above and no 500+.
- One optional `/internal/credentials/model-resolution` 404 was observed at new
  conversation bootstrap; the configured fallback model completed the journey.
  This pre-existing optional-binding behavior did not alter Phase 58 domain
  results and is not treated as Phase 58 completion evidence.
- Chrome DevTools screenshot capture intermittently waited after writing the PNG;
  DOM/Network/Console inspection remained stable. The successfully written files
  are retained below.

Screenshots:

- `browser/agent-pool-created.png` — baseline pool creation and the public-language
  issue found before the final refinement.
- `browser/stock-pool-visible.png` — persisted pool visible through Product API.
- `browser/final-v12-strategy.png` — final ordinary-language strategy result and
  WorkflowCard after v1.2.0 authorization repair.

## Acceptance result

Phase 58 is accepted. A normal user can move from researched candidates to a
real owner-scoped custom Stock Pool and then to a validated, immutable strategy
version without copying internal IDs. The final tested traces contain no denied
actions, no 403/422 storm, no cross-owner leakage and no unsupported domain
mutation. Product remains Beta; no release, tag, merge or Phase 59/60 work was
performed.
