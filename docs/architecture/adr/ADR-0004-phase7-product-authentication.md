# ADR-0004：Phase 7 Product Agent Authentication 与 Secret Boundary

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 7 authenticated Product Agent turn
- Supersedes: unauthenticated Phase 6 internal-only prototype boundary

## 背景

Phase 6 建立了私有 Gateway → Runtime Adapter seam。其 endpoint 信任私有 Compose
network，明确不承担 user authentication。Phase 7 需要一次经过认证的 Product Agent
turn，同时分离 user credential、model/provider credential、DSH persistence 和 BYQ
WorkflowTrace ownership。

Phase 7 topology 中没有 identity provider 或 user database。更大的 identity system
会使 Phase 超出首次 Product turn 的范围，且无法在当前仓库中通过 contract test。

## 决策

1. `/v1/agent` 和 `/v1/workflows` 下的 Product Agent endpoint 要求 opaque
   `Authorization: Bearer` token；它配置为仅 Gateway 持有的 `BYQ_PRODUCT_TOKEN`
   secret，并使用 constant-time comparison。该 token 在本 Phase 映射到配置的
   `BYQ_PRODUCT_PRINCIPAL` subject。
2. Gateway 生成 session 和 trace identifier，将已认证 principal 记录为 session
   owner，并对其他 principal 的 session 返回 404。token 绝不转发给 DSH、MCP、
   Runtime Adapter 或 WorkflowTrace payload。
3. `DEEPSEEK_API_KEY` 只配置在 Runtime Adapter。Adapter 只把它传入由自身持有的
   official SDK child environment。readiness detail、lifecycle response、exception
   text、log 和 normalized trace event 均不得包含它。缺少 provider secret 时，
   Product turn 必须 fail closed，并返回通用 503。
4. Phase 6 的 `/internal/runtime` endpoint 保持私有 compatibility seam。它不是面向
   用户的 authentication surface；未部署 ADR-0003 要求的 service-identity 机制前，
   不得暴露到私有 service network 之外。
5. Gateway 持有 append-only normalized WorkflowTrace store。它只持久化 BYQ
   envelope，强制每个 session 的连续 sequence number，并支持通过 `Last-Event-ID`
   replay。DSH session log 仍属于 Agent Plane state，不复制到 BYQ trace store。

## 后果

- CI 和无密钥环境无需嵌入 model credential，即可测试 authentication、lifecycle、
  secret absence、normalization、ordering 和 cleanup。
- 真实的 model-keyed turn 需要 operator 提供 `DEEPSEEK_API_KEY`；缺失属于明确的
  环境限制，而不是用 fake provider 替代。
- 单一 opaque token 是有意限定于 Phase 7 的 bootstrap policy。multi-user identity
  provider、token rotation、revocation 和 cross-instance session ownership 需要后续 ADR。
- Gateway trace store 是 Phase 7 append-only filesystem Contract。未来持久化 BYQ
  service 可以替换其 storage，但必须保留 envelope 和 replay semantics。

## 拒绝的替代方案

- 通过 Gateway 传递 `DEEPSEEK_API_KEY` 会扩大 secret boundary，使 Gateway compromise
  能暴露 model provider。
- 将 DSH session token 或 raw DSH session log 视为 user identity，会混淆 Agent Plane
  persistence 与 BYQ authentication。
- 让 Product Agent endpoint 保持 unauthenticated，无法满足 Phase 7 authenticated-turn
  验收标准。
- 将 model credential 放入 WorkflowTrace payload 或 error，会让 product client 可观察
  到 secret 泄漏。
