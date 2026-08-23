# Phase 42 Community Frontend Checklist

Read-only references inspected before implementation:
`/home/jefison/projects/BeyondQuant-community/frontend`.

| Reference surface | Classification | Phase 42 decision |
|---|---|---|
| `components/layout/AppSidebar.vue` | `PORT_LAYOUT` + `PORT_UX` | Keep the compact conversation/history rhythm, but replace grouped navigation with ADR-0024's flat BYQ routes. |
| `components/layout/AppBottomNav.vue` | `PORT_UX` | Replace the bottom popover with an accessible modal drawer; no Community API/state is reused. |
| `components/layout/UserSettingsMenu.vue` | `PORT_COMPONENT` + `PORT_UX` | Preserve the bottom account trigger and relocate real BYQ destinations behind it using durable auth/RBAC. |
| `views/AgentView.vue` session history | `REFERENCE_ONLY` | Show only current Product sessions with honest identifier fallbacks; titles, rename, pin, archive and search wait for Phase 43's catalog. |
| theme classes and `styles/byq-theme.css` | `PORT_STYLE` | Use existing global BYQ semantic tokens; durable appearance selection remains Phase 44. |
| operations navigation | `PORT_LAYOUT` | Preserve admin deep links and an admin-only System Settings entry; the route-backed dialog is Phase 45. |

Not reused: Community authentication, stores, Agent APIs/SSE schemas, runtime
persistence, direct service access, or any source code. The Community
repository remained unmodified.
