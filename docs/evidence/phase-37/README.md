# Phase 37 — My Space depth evidence

Date: 2026-08-22

## Reference and classification

The read-only Community baseline was inspected at commit
`58dd99dad9757e1feb53bfc0af7d54faf7bd52ac`. The inspected surfaces were
`UserModelsView.vue`, `UserModelSettingsPanel.vue`, `UserAssetsView.vue`, and
`UserAgentPolicyView.vue`. Community source, persistence, provider URLs,
runtime schemas, and identifiers were not copied or modified.

| Community element | Decision | BYQ result |
|---|---|---|
| Credential cards and model profiles | `PORT_LAYOUT` / `PORT_UX` / `REPLACE` | Owner-scoped write-only credentials, separate profiles, masked reads, optimistic versions, revoke, and metadata-only audit |
| Per-Agent model selection | `PORT_UX` / `REFACTOR` | Explicit Product Agent profile binding; private Backend-to-Runtime resolution |
| Strategy/backtest asset transfer | `PORT_UX` / `REFACTOR` | Canonical digested `byq-workspace-assets-v2` bundle with validation, new owner-safe IDs, and an itemized import report |
| Agent policy presets and rule table | `PORT_UX` / `REFACTOR` | Durable ordered rule CRUD, atomic presets, effective auto-deny, and platform-approval precedence |
| Community APIs, SQL schema, provider catalogue, PydanticAI/Hermes runtime | `REFERENCE_ONLY` / `REPLACE` | BYQ Product API, Backend ownership, and DSH Runtime Adapter boundaries |
| BaoStock, AKShare, and VectorBT paths | `DROP` | No dependency, adapter, fallback, row, or compatibility path introduced |

## Community-derived feature checklist

- [x] A user can create, replace, disable, re-enable, and revoke a model
      credential without any read path returning its secret or envelope.
- [x] Credentials and model profiles are separate owner-scoped resources;
      only reviewed DeepSeek catalogue models may be selected.
- [x] The Product Agent has an explicit personal-profile/system-default state,
      and revoked credentials cannot silently fall back through that binding.
- [x] Runtime resolution is private and fail-closed; the secret exists only in
      the child SDK environment and never enters Gateway, MCP, browser data,
      logs, readiness, object representations, or WorkflowTrace.
- [x] Workspace asset export/import uses a versioned manifest and item
      digests. Strategies are revalidated into new current-owner drafts and
      versions; backtests become honest read-only research archives; Stock
      Pools and Paper accounts use their canonical domain import paths.
- [x] Imported resources receive new identities and the import report states
      counts, warnings, and that the source owner was not reused.
- [x] Agent policy provides atomic `全部人工确认` and `禁止 Agent 发起回测`
      presets plus ordered rule create/edit/delete and change history.
- [x] Personal auto-approve never bypasses a platform/manual approval gate;
      personal auto-deny is effective before execution.
- [x] Browser traffic uses same-origin Gateway/Product API routes only; there
      are no direct Backend, MCP, DSH, PostgreSQL, Redis, Tushare, or provider
      requests.

## Chrome DevTools MCP evidence

- [`01-model-settings.png`](01-model-settings.png) — a real owner-scoped
  credential, masked value, profile, Agent binding, and metadata-only audit.
- [`02-agent-policy.png`](02-agent-policy.png) — platform-precedence notice,
  presets, an effective `byq_backtest_run` auto-deny rule, preferences, and
  rule audit.
- [`03-assets-import.png`](03-assets-import.png) — real v2 export/import result
  represented by new-ID Stock Pool rows in the owner asset index.

Chrome DevTools MCP reviewed all three production-built pages against the
isolated real Product API stack. The persistent screenshots were captured by
the same no-mock golden flow after the MCP review. Network inspection showed
only the page origin and `/api/product/...` requests. There were no console
warnings or errors and no HTTP 5xx responses. The initial unauthenticated
`/api/auth/me` 401 before login is the expected session bootstrap behavior.

## Contract and test evidence

- Backend tests cover AES-256-GCM envelope/AAD integrity, key-ring validation
  and rewrap, owner isolation, idempotency, masked reads, revoke behavior,
  audit metadata, profiles/bindings, policy presets/rules, and private
  resolution without secret echo.
- Runtime Adapter tests cover owner-bound private resolution, keyless
  bootstrap compatibility, fail-closed resolver errors, and secret exclusion
  from public runtime state.
- Gateway tests cover Product API projection, asset digest validation,
  owner-safe import semantics, full Stock Pool hydration, archive honesty,
  and policy/model routing.
- Frontend unit/build tests cover the typed API and all three workspaces. The
  real browser suite exercises credential/profile/binding creation, an
  effective policy rule, v2 export/import, SPA navigation, and same-origin/no-
  5xx assertions.
- Final local CI passed architecture, Backend, Gateway, Runtime Adapter, MCP,
  frontend unit/build/audit, mocked navigation, full compose smoke, and all
  three real Product API browser journeys.
