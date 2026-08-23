# Phase 41 Community Frontend Checklist

Reference inspected read-only on 2026-08-23:
`/home/jefison/projects/BeyondQuant-community/frontend`.

| Reference surface | Evidence observed | Decision |
|---|---|---|
| `components/layout/AppSidebar.vue` | Recent titled sessions with open/pin/rename/delete interaction | `PORT_UX`; replace API/state and simplify to ADR-0024 single-level navigation |
| `components/layout/AppBottomNav.vue` | Mobile recent-session access | `PORT_UX`; refactor into the new navigation drawer |
| `views/AgentView.vue` | Conversation-first history restore and actionable result flow | `REFERENCE_ONLY` + `PORT_UX`; replace Agent APIs/events with Product API and normalized WorkflowTrace |
| `components/layout/UserSettingsMenu.vue` | Bottom user account/settings entry | `PORT_COMPONENT` + `PORT_UX`; use durable BYQ session/RBAC |
| `App.vue`, `store/modules/app.js` | Light/dark theme class behavior | `PORT_UX`; replace local-only store with `ui-preferences.v1` and semantic tokens |
| `styles/byq-theme.css` | Compact neutral surfaces, shared variables and responsive rules | `PORT_STYLE`; redesign palette and prohibit page-local themes |
| `OpsLayout.vue`, `OpsSidebar.vue` | Protected two-column operations navigation | `PORT_LAYOUT`; embed in route-backed System Settings dialog |
| Profile/Models/Assets/Agent Policy views | Personal settings grouping | `PORT_UX`; retain current BYQ Product API implementations |

Explicitly not reused:

- Community authentication/token storage;
- `/agent-api`, raw Agent/SSE schemas, PydanticAI/Hermes assumptions;
- direct Backend/provider/storage calls;
- Community runtime/session persistence or ownership model;
- BaoStock, AKShare, VectorBT or provider/plugin selectors;
- application code copied from the Community repository.
