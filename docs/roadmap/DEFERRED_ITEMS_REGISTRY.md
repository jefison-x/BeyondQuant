# BeyondQuant Deferred Items Registry (D-Items)

Status: **Active** — companion to `IMPLEMENTATION_PLAN.md` and
`COMMUNITY_FULL_PARITY_PLAN.md` (Phase 32–40).

This registry is the single authoritative inventory of work that was **explicitly
skipped, blocked, or conditionally deferred** during a phase, so it can be
re-picked-up automatically once its precondition becomes true. It exists because
"known remaining" notes were previously scattered across parity matrices, gap
audits, and Chrome evidence files — easy to lose across phase boundaries and
agent sessions.

## Scope

- Entries here are **conditional** (blocked on an ADR, a decision, a
  prerequisite phase, or a signal source) — NOT the normal planned scope of
  upcoming phases (that lives in `IMPLEMENTATION_PLAN.md` /
  `COMMUNITY_FULL_PARITY_PLAN.md`).
- A phase MUST NOT be declared complete while a registry entry with
  `Phase: <that phase>` is still `OPEN`. Marking completion with an open
  conditional entry is a fake-completion violation (AGENTS rule 40).

## State machine

```
BLOCKED ──(precondition met)──► READY ──(scheduled)──► IN_PROGRESS ──► CLOSED
  │                                                      │
  └──(precondition dropped / intentionally won't do)──► DROPPED
```

- `BLOCKED`: precondition not met (e.g. required ADR still Proposed).
- `READY`: precondition met, no work started (e.g. ADR just Accepted).
- `IN_PROGRESS`: scheduled into a worktree / Draft PR.
- `CLOSED`: implemented, tested, merged, with evidence recorded.
- `DROPPED`: explicitly abandoned with rationale (requires a comment, never silent).

## Trigger checkpoints (how "condition is suitable" gets detected)

1. **ADR status change** — the primary trigger. When any of
   ADR-0017 / ADR-0018 / ADR-0019 transitions from `Proposed` to `Accepted`,
   the ADR review MUST run the dependency query below and move every
   `BLOCKED` entry whose precondition names that ADR to `READY`.
2. **Phase closeout** — before a phase is marked complete in `STATUS.md`,
   walk this registry: any entry with `Phase: <this phase>` still `OPEN` blocks
   completion; any `READY` entry should be scheduled into the next worktree.
3. **STATUS.md update** — every STATUS update references this registry and
   lists `OPEN` conditional entries so deferred work stays visible.
4. **Draft PR body** — a phase PR's "Known limitations" MUST reference the
   registry IDs it does not cover, so deferred work is not silently absorbed.

## Entries

### D-0001 — Phase 32 Backtest create wizard
- Phase: 32
- Status: `CLOSED`
- Precondition: ADR-0017 (`signal_snapshot` artifact) accepted.
- Triggered: 2026-08-18 (ADR-0017 transitioned to Accepted).
- Closed: 2026-08-18 (PR #82 merged).
- Content: browser create-backtest wizard (Community `BacktestView.vue`,
  classified `PORT_UX`) selecting a validated StrategyVersion + matching
  `signal_snapshot` + execution parameters, submitting through Product API.
- Acceptance: wizard creates a backtest job from a validated strategy + signal
  snapshot; no signal generation in browser or DSH; Chrome DevTools MCP
  evidence + contract tests.
- Evidence: `COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md` §Phase 32 create
  wizard review (job `backtest_4f64f70c81c146c296874da762cb5d7a`); six
  backend contract tests; full local CI green; self-hosted PR CI green.

### D-0002 — Signal producer (strategy source → signal_snapshot)
- Phase: 40 (transferred from Phase 32 during Phase 32 closeout; deliberately
  out of scope of ADR-0017 decision 3)
- Status: `BLOCKED`
- Precondition: a dedicated signal-producer ADR (sandbox + determinism +
  provider access) is planned and accepted. Until then only the keyless
  fixture/import path can create snapshots.
- Content: BYQ-owned computation boundary that executes a validated strategy
  over the frozen universe/bars to derive the `signal_snapshot`. Without it,
  a newly written strategy cannot reach a backtest in one flow.
- Acceptance: producer ADR accepted; producer worker/import path produces
  content-addressed, secret-free snapshots; DSH never executes strategy
  source.
- Rationale: this is the reason Phase 32 wizard alone does NOT deliver the
  user end-to-end strategy→backtest journey.

### D-0003 — Backtest result-object GC periodic sweep (optional hardening)
- Phase: 40 (transferred from Phase 32 as optional hardening)
- Status: `BLOCKED`
- Precondition: measured orphan accumulation in `BYQ_BACKTEST_OBJECT_ROOT`
  demonstrates that the Phase 32 best-effort delete (PR #77) is insufficient.
- Content: a periodic sweep that removes result objects not referenced by any
  `backtest_jobs.result_reference_json` (best-effort delete can leave orphans
  after concurrent deletes or GC failures).
- Acceptance: sweep deletes only unreferenced objects; never deletes a
  referenced/tampered object; runs idempotently; covered by tests.

### D-0009 — Phase 33 strategy draft supersede visibility (optional hardening)
- Phase: 40 (transferred from Phase 33 during Phase 33 closeout)
- Status: `READY`
- Precondition: none (follow-up hardening recorded in PR #85).
- Content: the strategy list still renders soft-superseded (deleted) drafts
  with status `superseded`; there is no filter or hide-by-default for them.
  Add a status filter / "已删除" view so deletion is visually distinguishable,
  while keeping the immutable soft-supersede semantics.
- Acceptance: superseded drafts are distinguishable and can be hidden/shown;
  delete remains a soft-supersede transition; list projection contract tests;
  Chrome evidence if UI is touched.
- Evidence of origin: Phase 33 Chrome MCP review observed the deleted draft
  row remaining in the list after 删除草稿; PR #85 Known limitations.

### D-0010 — Phase 33 version-history projection bound (hardening)
- Phase: 40 (transferred from Phase 33 during Phase 33 closeout)
- Status: `READY`
- Precondition: none (follow-up hardening recorded in PR #85).
- Content: `/v1/research/strategies/{id}/versions` and
  `/v1/research/strategies/{id}/backtest-count` reuse the 200-newest artifact
  projection (`list_artifacts`), so owners with more than 200 artifacts can
  miss older versions/counts. Replace with a direct store query filtered by
  kind + content `strategy_id`.
- Acceptance: projections query PostgreSQL directly for the owner scope,
  are complete beyond 200 artifacts, and keep the same response contract;
  contract tests cover the projection boundary.

### D-0011 — Phase 33 StrategyView component-level tests (quality follow-up)
- Phase: 40 (transferred from Phase 33 during Phase 33 closeout)
- Status: `READY`
- Precondition: none (quality gap recorded in PR #85).
- Content: StrategyView has API-client, backend, Gateway, and MCP tests plus
  Chrome browser evidence, but no Vitest component-level tests for the view
  itself (draft save/delete flows, version-history rendering, read-only state,
  stats projection).
- Acceptance: view-level tests cover save/delete, version history, read-only
  mode, and backtest-count stats; they run in the standard frontend CI check.

### D-0012 — Phase 33 Community deep strategy profile fields (future depth)
- Phase: 40 (final parity closure candidate; out of Phase 33 scope)
- Status: `READY`
- Precondition: Phase 40 shared-component/parity closure planning.
- Content: Community `StrategyView.vue` profile depth — description,
  parameters, parameter_schema, and status enable/disable fields, plus the
  non-artifact strategy CRUD model — was intentionally not replicated in
  Phase 33 (BYQ keeps strategy code as auditable artifacts).
- Acceptance: decision recorded for each field (REUSE/REFACTOR/REPLACE/DROP);
  any replicated field works through Product API with validation/approval
  semantics preserved.

### D-0005 — Phase 36 Agent workbench structured cards
- Phase: 36
- Status: `CLOSED` (2026-08-22)
- Precondition: ADR-0018 (WorkflowTrace card contract) accepted. **Satisfied
  2026-08-22.** Phase 36 owns its required Agent-specific components; Phase
  40 may generalize them later.
- Content: strategy-draft / stock-candidates / optimization / backtest-context
  / approval cards in the conversation; assistant drawer; thinking panel.
- Acceptance: cards appear and are actionable; raw DSH payloads never cross
  the Gateway; Chrome evidence. **Satisfied:** the ADR-0018 contract is
  enforced end to end and real Product API desktop/mobile evidence is stored
  under `docs/evidence/phase-36/`.

### D-0006 — Phase 37 My Space model/asset/agent-policy depth
- Phase: 37
- Status: `CLOSED` (2026-08-22)
- Precondition: ADR-0019 (encrypted credential store) accepted. **Satisfied
  2026-08-22.** Phase 37 owns its required model-settings component; Phase 40
  may generalize it later.
- Content: model credential CRUD + Agent binding (never echoed), strategy /
  backtest re-import, agent policy presets/rule CRUD.
- Acceptance: credentials writable and masked; re-import real; rules CRUD
  effective; Chrome evidence. **Satisfied:** audited encrypted credentials and
  private resolution, canonical owner-safe asset v2 re-import, effective
  presets/rules and real Product API browser evidence are stored under
  `docs/evidence/phase-37/`.

### D-0007 — Phase 38 Operations workbenches
- Phase: 38
- Status: `CLOSED` (2026-08-22)
- Precondition: ADR-0019 + ADR-0022 accepted. **Satisfied 2026-08-22.** Phase
  38 owns the operations-specific components required for acceptance; Phase
  40 may generalize proven components later. Cache = PostgreSQL market-data
  cache status only (no Redis); budget = normalized DSH model-call token
  accounting.
- Content: database/PostgreSQL-cache/model/agent/budget/runtime/graph/access
  workbenches + data-source/sync surfaces; no placeholders.
- Acceptance: read-only projections real; write ops RBAC + audit; Chrome
  evidence. **Satisfied:** nine Product API workbenches, normalized DSH usage,
  audited monitoring thresholds, desktop/mobile Chrome evidence, and full
  local CI are recorded under `docs/evidence/phase-38/`.

### D-0008 — Phase 39 Data Center / Data Sync depth
- Phase: 39
- Status: `READY`
- Precondition: ADR-0019. **Satisfied 2026-08-22.**
- Content: Tushare-only data-source CRUD, test connection, sync jobs, coverage
  audit.
- Acceptance: configure Tushare source, trigger sync, view coverage/job status;
  Chrome evidence.

## Dependency quick-reference (ADR → blocked entries)

| Decision | Status | Unblocks |
|---|---|---|
| ADR-0017 (`signal_snapshot`) | Accepted (2026-08-18) | D-0001 |
| Signal-producer ADR (future) | not written | D-0002 |
| ADR-0018 (WorkflowTrace cards) | Accepted (2026-08-22) | D-0005 (`CLOSED`) |
| ADR-0019 (encrypted credentials) | Accepted (2026-08-22) | D-0006/D-0007 (`CLOSED`), D-0008 (`READY`) |
| ADR-0022 (Phase 38 component ownership) | Accepted (2026-08-22) | D-0007 (`CLOSED`) |
| Phase 40 shared components | planned | Later generalization for D-0005/D-0006/D-0007; not a prerequisite |

## Maintenance rules

- New skipped/blocked items found during any phase MUST be added here in the
  same PR that records the limitation (one entry per conditional work item).
- During phase closeout, an `OPEN` entry whose precondition is genuinely out
  of current-phase scope may have its `Phase` advanced to a later phase; the
  transfer MUST be recorded in the closeout PR and must never silently drop
  the work. A phase is complete with an `OPEN` entry only if that entry was
  explicitly transferred (recorded) or is `DROPPED` with rationale.
- Do NOT use this registry as a general backlog; normal upcoming phase scope
  stays in the phase plans.
- Update the `Dependency quick-reference` whenever a relevant ADR is
  proposed/accepted.
