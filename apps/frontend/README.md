# BeyondQuant Frontend

这是 Vue Product Plane UI。Browser requests 必须经过 Gateway Product API；
frontend 不得直接调用 Backend、MCP、DSH、PostgreSQL、Redis 或 market
provider，也不得直接依赖 DSH internal event schemas。

## 确定性 setup

使用已提交的 lockfile：

```bash
npm ci
npm run build
npm run test
```

## Browser tests

- `npm run test:e2e:mocked` 启动 Vite 并运行快速 mocked UI/navigation
  regression tests；它可以 intercept Product API requests，不属于 release
  acceptance evidence。
- `npm run test:e2e:real` 连接 `BYQ_REAL_BASE_URL`（默认
  `http://127.0.0.1:18080`），不拦截 request，并针对真实 Compose
  frontend/Gateway/Backend/PostgreSQL stack 运行。

Real smoke 当前证明 durable login 和 owner-scoped Stock Pool write/read flow。
它有意不称为完整 golden journey：strategy-source → `signal_snapshot`
仍是 D-0002，且进入 v1.0 RC gate 前仍需 multi-user isolation coverage。
