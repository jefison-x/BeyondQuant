# ADR-0002：初始可运行 Service Topology

## 状态

Accepted for Phase 5.

## 背景

Phase 5 为 BeyondQuant 建立最小可运行的物理主干。这是架构 bootstrap，不是产品或
legacy business feature 的迁移。该主干必须证明 service reachability 和 Agent Plane
到 Quant Domain Plane 的 MCP 边界，同时保持 Product 与 Engineering Plane privilege
分离。

## 决策

Phase 5 建立以下初始物理 runtime topology：

```text
gateway        (independent service skeleton)

dsh runtime
  ↓ outbound MCP Streamable HTTP
beyondquant-mcp
  ↓ HTTP
byq-backend
```

可运行 service 为 `gateway`、`dsh`、`mcp` 和 `backend`。

Phase 5 有意不实现：

- frontend
- PostgreSQL
- Redis
- backtest-worker
- data-worker
- engineering-dsh

只有在有必要提供明确 ownership README 时，才可预留这些组件的目录。不得仅为使仓库
看起来完整而创建 placeholder implementation。

初始技术选择：

| Component | Choice |
| --- | --- |
| Gateway | Python + FastAPI |
| Backend | Python + FastAPI |
| MCP | Node.js / TypeScript with the current official MCP TypeScript SDK |
| DSH runtime | Node.js 24 + `@deepseek-ai/dsh@0.1.0-rc.6` |
| dsh-byq | DSH configuration bundle/plugin |

Gateway 只暴露自身 health 和 bootstrap readiness；它不探测、依赖或暴露 DSH Web
URL。本 ADR 不实现也不定义面向应用的 Gateway-to-DSH transport。

`dsh` 依赖健康的 `mcp`，`mcp` 依赖健康的 `backend`。Gateway 独立启动，因为其与
DSH 的 runtime integration 被明确延后。

## DSH Runtime 基线

Phase 5 deployment baseline 是以下准确 npm artifact：

```text
@deepseek-ai/dsh@0.1.0-rc.6
```

package source 是发布自以下地址的 official npm package：

```text
https://github.com/deepseek-ai/deepseek-harness
```

npm metadata 将其标识为 `apps/cli` package。已发布 artifact 的 version 是
`0.1.0-rc.6`，integrity 为
`sha512-brpZfED7ieRa2PQ5tUxMhHrM1pb2CmKFVM/f6yMULBDMicahk+Z2OsHgTwTDnoiZm23Ftu9rQz0NN4pflaoJcg==`。
registry 未提供 `gitHead` 或 `engines`，因此将这些字段记录为 unavailable，而不是
推断其值。

相关 MCP client 由 dsh-byq bundle 以准确依赖
`@deepseek-ai/dsh-mcp-client@0.1.0-rc.6` 安装。其 official package metadata 指向同一
upstream repository 中的 `packages/mcp/mcp-client`。

Developer Preview 发布期间，official GitHub `master` package metadata 与已发布 npm
artifact 可能暂时不同。BYQ deployment 只使用经过验证并锁定的 npm artifact，绝不
使用 `latest`、`^`、`~` 或未经审查地跟随 `master`。

## DSH Web Trust Boundary

DeepSeek Harness `0.1.0-rc.6` 有意拒绝将 Web application bind 到 `0.0.0.0`，因为
Web/API surface 包含在缺少适当 application trust boundary 时不得通过网络暴露的能力。

因此 BeyondQuant SHALL NOT 使用 DSH Web 作为 Gateway-to-Runtime production
interface。Phase 5 只将绑定于 container-local `127.0.0.1` 的 DSH Web 用作 bootstrap
和 runtime verification surface。DSH container 不发布 host port，且不允许 proxy、
redirect、host network 或其他安全绕过。

## Product Agent Capability Boundary

Product DSH 不继承或暴露随附的 coding-capable DSH preset。BYQ 持有明确的 Product
preset roster，其根仅为 bundle 控制的 `presets` 目录。`byq-product` 是默认 preset，
且 `includeUserRoot` 为 `false`，因此用户编写或 Engineering Plane 的 preset root
不能进入 Product roster。

Product preset composition 不包含 bash、terminal、filesystem mutation、edit、write、
`str_replace_editor`、Git write、Codex 或 subagent coding capability。Engineering-
capable preset 只属于 Engineering Plane。

## 后果

- BYQ 在实现领域功能前已具备可独立运行的 Gateway、Backend 和 MCP service skeleton。
- DSH 继续是轻量 runtime，不获得 BeyondQuant source mount、Docker socket、Git
  credential 或 Codex authentication。
- `byq_health` 是第一个 MCP Contract，用于证明 MCP-to-Backend routing。
- DSH 验证 outbound DSH-to-MCP 边界，但不把 Web surface 作为 Product API。
- Product DSH 与 Engineering DSH 使用独立 capability roster；Product DSH 只暴露
  BYQ 控制的 `byq-product` preset。
- DSH baseline 只有在 compatibility gate 和 contract test 通过后才能升级。
- PostgreSQL、Redis、Strategy、Factor、Backtest、Tushare、User 和 Agent Session
  行为均不在范围内。

## 考虑过的替代方案

- 保留 `0.1.0-rc.5`：拒绝，因为所需 npm artifact 已无法安装。
- 使用 `latest` 或 semver range：拒绝，因为 DSH 是快速变化的 preview dependency，
  而准确 pin 是架构要求。
- 重写 MCP protocol 或 fork DSH：被仓库架构规则拒绝。

## 回滚与后续

通过 branch/release 回滚到此前仓库 revision。DSH upgrade 需要新的 compatibility
validation 和明确的 dependency change。面向应用的 Gateway-to-DSH transport 仍未
决策，延后到 Phase 6。Phase 6 在引入 session、chat 或 Runtime Adapter 前必须建立
新 ADR。
