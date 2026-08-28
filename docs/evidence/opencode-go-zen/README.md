# OpenCode Go/Zen provider evidence

Date: 2026-08-28

## Community classification

The complete read-only Community `UserModelSettingsPanel.vue` was inspected.
Provider-first UX and credential/profile/binding grouping are `PORT_UX`;
arbitrary Base URL, free-form model ID, local/OpenAI-compatible provider,
Community persistence and legacy runtime are `DROP` / `REFERENCE_ONLY`.

## Contract and runtime checks

- `@deepseek-ai/dsh-llm-pi-ai@0.1.1-rc.1` and its dependency closure install
  successfully from the exact package lock.
- The plugin's public `Config` schema parsed the actual Product composition and
  resolved six routes in the expected protocol order: Responses, Chat
  Completions and Messages for both Go and Zen.
- Backend catalogue tests: 2 passed.
- Backend PostgreSQL credential/profile/binding tests: 7 passed against an
  isolated PostgreSQL 16 database.
- Runtime Adapter tests: 41 passed.
- Gateway Product API tests: 42 passed.
- Frontend Vitest: 95 passed; TypeScript production build passed.

## Chrome review

System Google Chrome ran the mocked Product browser flow
`my space pages render profile, models, assets, and agent policy` successfully.
The flow opened 模型配置, selected OpenCode Go in 添加凭据, verified the
`OpenCode Go API Key` write-only field and the provider-aware default label,
then continued through the remaining My Space pages. Network mocks target only
same-origin `/api/product/*` routes; no browser request reaches Backend, DSH,
MCP or an OpenCode endpoint directly.
