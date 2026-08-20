# BeyondQuant Frontend

Vue Product Plane UI. Browser requests go through the Gateway Product API;
the frontend must not call Backend, MCP, DSH, PostgreSQL, Redis, or a market
provider directly, and it must not depend directly on DSH internal event schemas.

## Deterministic setup

Use the committed lockfile:

```bash
npm ci
npm run build
npm run test
```

## Browser tests

- `npm run test:e2e:mocked` starts Vite and runs fast mocked UI/navigation
  regression tests. These tests may intercept Product API requests and are not
  release acceptance evidence.
- `npm run test:e2e:real` connects to `BYQ_REAL_BASE_URL` (default
  `http://127.0.0.1:18080`) and runs without request interception against a
  real Compose frontend/Gateway/Backend/PostgreSQL stack.

The real smoke currently proves durable login and an owner-scoped Stock Pool
write/read flow. It is intentionally not called the full golden journey:
strategy-source → `signal_snapshot` remains D-0002 and multi-user isolation
coverage remains required before the v1.0 RC gate.
