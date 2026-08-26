# ADR-0012：Phase 16 Product API / BFF

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 16 browser Product API boundary

## 背景

Phase 6-15 建立了 headless quant core。Browser frontend 必须使用稳定的 BYQ Product
API/BFF，而不是 raw Backend internal、MCP、DSH 或 WorkflowTrace schema。Gateway 已
持有 Product bearer authentication 和 WorkflowTrace projection，因此 Product API
属于 Gateway。

## 决策

1. Gateway 持有 `/api/product` 下的 browser-facing Product API/BFF。
2. BFF 使用现有 `BYQ_PRODUCT_TOKEN`/`BYQ_PRODUCT_PRINCIPAL` authentication boundary，
   并返回统一 BYQ Product error envelope。它绝不转发 MCP token、provider credential、
   DSH event schema 或 raw Backend storage exception。
3. Product resource path 在 versioned OpenAPI source
   `docs/contracts/product-api.openapi.yaml` 中定义；必须能从该 source 生成 TypeScript
   client type。
4. Phase 16 只实现证明 auth、error、pagination boundary 及 dashboard/data-status/health
   所需的 Contract-bearing BFF seam。完整 resource API 在 OpenAPI 中映射，并在后续
   Productization Phase 实现。
5. Browser request 始终沿
   `Frontend -> Gateway Product API -> Backend or Runtime Adapter -> MCP/DSH`
   的 Accepted boundary 流转。Frontend 不直接调用 Backend、MCP 或 DSH。

## 后果

- Product 与 Engineering/Agent Plane boundary 保持明确。
- Browser client 可以使用统一 typed Contract，而不耦合 DSH。
- 未来 resource endpoint 可在相同 auth/error/pagination envelope 后增加，而不改变
  browser boundary。
