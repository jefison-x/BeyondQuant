# Conversation-First Frontend Experience Plan

Status: **ACTIVE — Phase 41 baseline accepted**

This plan replaces the immediate v1.0 release-candidate review with a bounded
Product experience program. It does not reopen completed domain semantics and
does not authorize a second frontend/backend/runtime boundary. ADR-0024 is the
normative experience and conversation ownership decision.

## Invariants for every phase

- Browser traffic uses Gateway/Product API only.
- DSH owns generic Agent runtime; BYQ owns Product conversation metadata,
  domain state, authorization, audit, and normalized projections.
- Existing Product capabilities must be relocated deliberately, not removed by
  navigation simplification.
- Community is inspected read-only and classified before each matching surface
  is changed.
- All UI uses semantic design tokens. No page-specific brand theme is allowed.
- Each phase uses one isolated worktree/branch/PR, CI-green squash auto-merge
  under ADR-0015, post-merge Compose rebuild, login smoke, and real-browser
  desktop/mobile evidence where UI changes.
- Completing a phase does not declare v1.0 ready. Only Phase 48 may reopen a
  separate human release-candidate review.

## Global experience target

```text
Desktop
┌──────────────────────┬──────────────────────────────────────┐
│ New conversation     │ current conversation / workspace     │
│ Stock Pool           │                                      │
│ Strategy             │ Xiaoba is the default                │
│ Backtest             │                                      │
│ Conversation History │ cards, approvals, domain deep links  │
│ recent titles        │                                      │
│                      │                                      │
│ user menu            │ composer / workspace actions         │
└──────────────────────┴──────────────────────────────────────┘
```

## Theme contract

The closed initial preference values are:

```json
{
  "schema_version": "ui-preferences.v1",
  "color_mode": "system",
  "accent_theme": "emerald"
}
```

Allowed accent themes are `emerald`, `ocean`, `indigo`, `amber`, and
`graphite`. Semantic status colors are invariant. Backend persistence is the
source of truth; pre-mount cache is non-authoritative and contains no identity
or secret.

## Phase 42 — Conversation-first Product shell

Replace the grouped navigation and large route header with the single-level
sidebar, compact workspace toolbar, default Xiaoba route, recent-session
section, bottom user trigger, and mobile navigation drawer. Preserve or
redirect every existing route and provide an explicit destination for Paper
Trading, research/approval lineage, assets, personal models/policy, Data
Center, status, and Operations. Use the default semantic theme tokens; do not
claim durable titled history yet.

Acceptance: desktop/mobile navigation, keyboard/focus behavior, route
preservation, auth/admin visibility, and current Product API flows pass real
browser review.

## Phase 43 — Durable conversation catalog and Xiaoba workspace (`COMPLETE`)

Implement ADR-0024's owner-scoped Backend catalog and Product API projections;
deterministic first-turn titles; rename, pin, archive, bounded pagination and
search; restart-safe message/card replay; and the centered conversation canvas
with activity/context drawers. Existing DSH session persistence remains
private correlation state.

Acceptance: Compose restart recovery, two-user isolation, title lifecycle,
history switching without message/trace crossover, normalized-only replay,
and desktop/mobile real-browser journeys pass.

## Phase 44 — User center and durable appearance (`COMPLETE`)

Move Profile, Assets, Models, Agent Policy, and Paper Trading entry points into
the user menu and user-center surfaces. Add the versioned durable appearance
contract, system/light/dark modes, five reviewed accent themes, live preview,
pre-mount restoration, and cross-device persistence.

Acceptance: write-only credential behavior, asset transfer, policy precedence,
Paper Trading reachability, theme persistence, contrast, and owner isolation
remain real through Product API.

## Phase 45 — Route-backed System Settings dialog (`COMPLETE`)

Embed System Overview, Data, Sources, Cache, Database, platform Models, Agents,
Budget, Runtime, Workflow diagnostics, Access and Audit in a large two-column
dialog/full-screen mobile surface. Retain route history/deep links and all
ADR-0022 RBAC/audit/destructive-action limits.

Acceptance: every existing operations surface remains reachable, admin-only,
bounded, refreshable and browser-verified without direct internal APIs.

## Phase 46 — Core management workspace redesign (`NEXT`)

Unify Stock Pool, Strategy and Backtest into consistent catalog/detail
workspaces. Preserve immutable snapshots, version/approval/signal lineage,
complete backtest results and direct Workflow-card navigation. Apply the
global theme to every table, editor, chart, dialog and mobile card.

Acceptance: no domain feature regression; the conversation-to-pool/strategy/
backtest journey and return links pass with real Product data.

## Phase 47 — Interaction, responsive and accessibility closure

Standardize loading/empty/error/success/disabled states, search/filter/
pagination, unsaved-change protection, dates/numbers/status labels, responsive
tables/cards/settings, keyboard navigation, focus management, reduced motion,
and theme-aware chart palettes.

Acceptance: the full color-mode/accent matrix passes contrast and responsive
review; Lighthouse accessibility target is 100 unless a documented external
blocker is accepted.

## Phase 48 — Product coherence and golden journey

Run a fresh no-mock, two-user Compose journey across login, conversation,
candidate pool, strategy, approval, signal, backtest, history restore, assets,
models, appearance and administrator settings. Reconcile all relocated
Community capabilities, record desktop/tablet/mobile Chrome evidence, and
publish remaining Product gaps.

Acceptance: no unexplained missing capability, raw internal-browser boundary,
fake state, owner crossover, or theme inconsistency. Completion reopens but
does not automatically pass the human v1.0 release-candidate review.

## Post-merge preview contract

After every phase merges, synchronize `main`, preserve existing volumes, and
run the latest stack with the frontend on `0.0.0.0:80` and Gateway on
`127.0.0.1:8100`. Verify container health, homepage HTTP 200, durable login,
the phase journey, and the LAN address before handing the running build to the
maintainer for validation.
