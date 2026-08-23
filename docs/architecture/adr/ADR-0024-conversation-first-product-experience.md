# ADR-0024: Conversation-First Product Experience and Durable Conversation Catalog

- Status: Accepted
- Date: 2026-08-23
- Accepted: 2026-08-23
- Decision scope: Post-Phase 40 Product shell, conversation catalog, settings
  surfaces, and user appearance preferences
- Related: ADR-0003, ADR-0012, ADR-0014, ADR-0018, ADR-0022

## Context

Phase 40 completed the current Community feature-parity program, but the
resulting Product UI still exposes the implementation history as many grouped
navigation entries, a separate operations shell, and a three-column Agent
workbench. The maintainer has explicitly postponed the v1.0 release-candidate
review and selected a conversation-first product direction: a ChatGPT-like
two-column shell with Xiaoba as the default workspace, four primary domain
destinations, recent conversation titles, a bottom user menu, and a unified
settings experience.

The current Product API lists only live Product sessions with `session_id` and
`trace_id`. The frontend renders shortened identifiers and holds the active
conversation messages in client state. That is insufficient for durable
titles, history restore, archive/search, restart recovery, or owner-safe
conversation management. DSH owns raw session persistence and runtime events,
but those are not a stable Product catalog and must not become a browser
contract.

The read-only Community frontend proves useful conversation-history, user-menu,
theme-class, and operations-navigation interactions. Its authentication,
Agent APIs, raw event assumptions, state stores, and direct service contracts
remain incompatible with BYQ and are reference-only.

## Decision

1. The authenticated Product shell becomes conversation-first. Its desktop
   layout is one collapsible primary sidebar plus one main workspace. Xiaoba is
   the default route. The only primary business entries are New Research
   Conversation, Stock Pool, Strategy, Backtest, and Conversation History.
2. BYQ Backend owns a durable, owner-scoped Product conversation catalog.
   Catalog metadata includes a stable conversation/session reference, title,
   owner, lifecycle state, creation/update times, last-message preview, and
   optional pin/archive state. DSH continues to own raw runtime Session logs;
   its persistence is correlation evidence, not the Product catalog.
3. Conversation replay reaches the browser only through Gateway/Product API
   projections composed from BYQ-owned conversation metadata and normalized
   WorkflowTrace/message projections. The frontend must not read DSH files,
   raw DSH events, Runtime Adapter internals, or MCP directly.
4. Initial titles use a deterministic bounded fallback derived from the first
   user turn. A later model-generated refinement may update the title through a
   BYQ-owned bounded write, but failure never blocks conversation creation and
   model output never supplies owner or lifecycle authority.
5. The current Agent three-column layout is replaced by a conversation canvas.
   Workflow cards remain in the message flow. Activities and execution context
   move to bounded drawers/disclosures; approvals remain available through
   normalized cards and the global approval inbox.
6. Personal Profile, Assets, Model Configuration, and Agent Policy move behind
   the bottom user menu. Paper Trading remains a real Product capability and
   becomes an explicit Asset Management subsection rather than disappearing.
   Research/approval lineage remains reachable from cards, asset detail, and
   the approval center.
7. Administrator operations move into a large route-backed System Settings
   dialog with its own two-column navigation. Existing Product API RBAC remains
   authoritative. A normal user neither sees the entry nor gains access by
   navigating directly to a settings route.
8. Appearance is a durable, user-scoped BYQ preference with a versioned public
   contract. The initial contract supports `color_mode` (`system`, `light`,
   `dark`) and a closed accent palette. Backend is authoritative; a bounded
   browser cache may be used only to avoid first-paint theme flash.
9. All frontend colors use semantic design tokens. Accent selection never
   changes success, warning, error, approval, or destructive-action meaning.
   Pages, charts, dialogs, drawers, Element Plus overrides, Workflow cards,
   and mobile surfaces must not define independent visual themes.
10. Existing deep links remain valid through route preservation or explicit
    redirects. Dialog presentation must not remove refresh, browser history,
    audit, or direct-link behavior.

## Product information architecture

```text
Primary sidebar
├── New Research Conversation
├── Stock Pool
├── Strategy
├── Backtest
├── Conversation History
│   └── recent owner-scoped conversation titles
└── User menu
    ├── Personalization
    ├── Asset Management
    │   └── Paper Trading
    ├── Model Configuration
    ├── Agent Policy
    └── System Settings (admin only)
```

## Consequences

- The Product becomes easier to understand without removing existing domain
  depth.
- A new Backend/Product API conversation catalog is required before history
  can be claimed complete.
- The frontend shell, settings container, and core workspaces can evolve
  independently because their data continues to cross Product API contracts.
- The appearance contract creates a small persistent schema and a global
  design-token migration, but prevents per-page theme drift.
- The v1.0 RC gate remains closed until the post-Phase 41 experience program
  and a new real-browser golden journey are complete.

## Rejected alternatives

- Keep the grouped dashboard-first navigation: preserves implementation
  history but conflicts with the selected conversation-first product model.
- Use DSH session files as browser history: couples Product state to runtime
  persistence and leaks an unstable framework boundary.
- Store titles and themes only in localStorage: loses durable multi-device
  identity and violates Product completion rules.
- Copy the Community Agent/session store: reintroduces incompatible APIs and
  runtime coupling.
- Allow arbitrary user-entered colors: makes contrast, charts, semantic states,
  and consistent cross-page review unbounded.
- Put Cloud tenant UI into this redesign: tenancy remains a separate later
  architecture program; the shell only preserves a future workspace-switcher
  seam.

## Migration and rollback

The implementation proceeds in isolated Phases 42-48. Existing routes remain
available until their replacement is proven. Conversation-catalog migrations
must preserve existing runtime sessions as unclaimed correlation evidence and
must not silently assign unverifiable history. Each phase can roll back its
frontend container or route mapping without altering completed domain assets.
Disabling new appearance settings returns every user to the default light
emerald token set without deleting stored preferences.

## Acceptance record

The maintainer accepted the conversation-first layout, user-menu consolidation,
large two-column System Settings dialog, durable titled history, and global
theme requirement on 2026-08-23. Acceptance does not authorize raw DSH browser
contracts, removal of existing capabilities, fake conversation history, or
premature v1.0 release.
