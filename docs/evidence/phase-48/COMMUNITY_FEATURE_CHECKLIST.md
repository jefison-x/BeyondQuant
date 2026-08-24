# Phase 48 Community feature checklist

Community source was inspected read-only. Existing BYQ contracts and prior
phase classifications remain authoritative.

| Capability | Community evidence | BYQ location / disposition | Result |
|---|---|---|---|
| Primary research entry | Agent workbench and sidebar | Default `/agent`, single-level sidebar, Xiaoba timeline | PASS |
| Conversation history | Recent session list and restore UX | Durable owner-scoped catalog, rename/pin/archive/restore | PASS |
| Stock Pool management | Catalog, create/detail, snapshots | `/stock-pool`, immutable memberships and references | PASS |
| Strategy management | Editor, validation and history | `/strategy`, draft/version/approval/signal lineage | PASS |
| Backtest management | Wizard, compare and deep result tabs | `/backtest`, deterministic result and eight evidence tabs | PASS |
| Profile | Nickname, preferences, default prompt | `/user/profile`, durable Product profile | PASS |
| Appearance | Community theme toggle | `/user/appearance`, versioned mode plus closed accent palette (`REPLACE`) | PASS |
| Assets | Resource lists and transfer | `/user/assets`, digested owner-safe v2 bundle | PASS |
| Models | Credential/profile/binding groups | `/user/models`, encrypted write-only credential boundary | PASS |
| Agent policy | Personal rules and approvals | `/user/agent-policy` and `/user/research` | PASS |
| Paper Trading | Account and settlement workspace | `/user/paper-trading`, exact BYQ ledger semantics | PASS |
| Data management | Source, sync, cache and coverage | Admin System Settings data sections, Tushare/PostgreSQL only | PASS |
| Operations | Database/runtime/graph/access workbenches | Admin System Settings bounded `operations.v1` projections | PASS |
| Responsive composition | Desktop/mobile Community layouts | BYQ desktop sidebar, tablet workspace and mobile drawers/selectors | PASS |
| Raw Community APIs/runtime/storage | Legacy implementation detail | `REFERENCE_ONLY` / `DROP` / `REPLACE`; never browser-accessible | PASS |
| BaoStock, AKShare, VectorBT, PydanticAI, Hermes | Legacy technology paths | `DROP`; absent from implementation and journey | PASS |

Every Product capability above is either present through BYQ Product API or
explicitly replaced/dropped by an accepted boundary. There is no unexplained
`PARTIAL` or `MISSING` item.
