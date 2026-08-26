# Phase 52 Community frontend classification

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

The Community repository was inspected read-only before implementation. Its
components are UX evidence only; BYQ Product API and ADR-0025 remain
authoritative.

| Community evidence | Classification | Phase 52 decision |
|---|---|---|
| `frontend/src/components/layout/UserSettingsMenu.vue` | `PORT_UX` / `REFACTOR` | Retain the bottom account affordance, but replace Community's username/personal-mode copy with the bounded durable personal-workspace projection. |
| `frontend/src/views/UserProfileView.vue` | `REFERENCE_ONLY` | Profile stays user-scoped; no workspace or team controls belong in profile. |
| `frontend/src/views/UserAssetsView.vue` | `PORT_LAYOUT` / `PORT_UX` / `REPLACE` | Retain asset summary and transfer orientation; replace Community workspace bootstrap/API assumptions with BYQ Gateway Product API, digested bundles, and trusted destination scope. |
| `frontend/src/components/layout/AppLayout.vue` | `PORT_LAYOUT` | Preserve responsive shell composition; ADR-0024's sidebar/mobile drawer remains the implemented layout. |
| Community workspace bootstrap/import calls | `REPLACE` | No Community API/runtime/storage path is used. Browser calls same-origin Gateway/Product API only. |
| Team, organization, invitation, membership and switching concepts | `DROP` for Phase 52 | Not present in the selected personal-workspace product and not implied by the future team seam. |

Result: all corresponding Community features are classified. No legacy code,
runtime, API, or storage implementation was copied.
