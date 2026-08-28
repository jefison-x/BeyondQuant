# ADR-0040：Plugin Center 策略请求与部署控制面边界

- Status: Accepted
- Date: 2026-08-28
- Decision scope: Phase 65 Plugin Center、Product policy/qualification request、generated composition 与 active runtime identity

## Context

ADR-0038 已将 DSH 官方插件的资格、风险、Agent assignment 和 deterministic Cordis composition
固定为 BYQ-owned、Git-managed contract。Phase 65 需要让管理员看见并变更这些状态，但 Browser、
Gateway、Backend 和 Product DSH 均不得获得 npm、shell、Git、source write、Docker socket、process
control 或 running-runtime mutation 权限。只更新数据库却显示“已启用”同样是不真实的。

## Decision

### 四个权威状态互不替代

| State | Authority | Meaning |
| --- | --- | --- |
| Registered / qualified ceiling | Git-managed registry/evidence | 唯一可请求的 package/version/capability/Agent 上限 |
| Desired Product policy | PostgreSQL policy + append-only request/audit | 管理员希望下次正常部署采用的 enabled set/assignment |
| Generated / validated target | trusted deployment lane immutable build evidence | builder 与 exact lock gates 已生成 target hash |
| Active runtime | Runtime Adapter normalized readiness | 当前进程实际加载的 profile/hash/plugin IDs |

只有 Runtime Adapter readiness 与 target identity 匹配时，UI 才显示 `ACTIVE`。HTTP `202` 只表示
request 已持久化/验证，绝不表示插件已运行。

### Product Plane 只拥有有界请求和投影

Gateway `/api/product/plugins*` 是唯一 browser boundary。mutation 必须有 durable admin session、
actor、reason、expected policy version 和 idempotency key。Backend 只能：

- 从 image 内只读 Git registry 构造 secret-free Catalog/Detail；
- 拒绝 unknown package/version/Agent、unqualified、HIGH/PROHIBITED 和 capability escalation；
- 原子更新 desired policy，并持久化 `validated → awaiting_generation` request；
- 排队 exact registered version 的 Qualification Request；
- 保留 append-only audit。

Backend 不生成/写 Cordis、不调用 npm/Git/Docker、不重启 Runtime Adapter。Gateway 只组合 Backend
projection 与 Runtime Adapter normalized identity，不转发 raw Cordis、registry、lockfile、DSH event、
secret 或内部路径。

### 正常部署由 trusted deployment lane 所有

CI/operator-owned deployment lane 是 Product Plane 外唯一允许推进
`awaiting_generation → generated/validated → deploying → active|failed|rolled_back` 的 owner。它必须：

1. 读取一个已验证 request 的 canonical policy snapshot；
2. 使用与 image 同 Git revision 的 Phase 63 builder、registry、manifest 和 lockfile；
3. 在隔离 build workspace 生成 composition/identity，执行 qualification、architecture、contract、
   runtime initialize 和 secret-negative gates；
4. 构建 immutable image并按正常 deploy/restart 发布；
5. 对比 Runtime Adapter readiness 的 exact target profile/hash/plugin IDs；
6. 失败时保留/恢复上一 immutable image和 active identity，并记录 bounded result。

本 Phase 不把该 lane 伪装成 Marketplace installer，也不给 Product service 部署凭据。仓库 CI 和
operator compose/release 是当前 trusted owner；未来常驻自动化需新的 ADR 扩权。

### Qualification、credential 与 authorization

Qualification Request 只能引用 registry 中 exact version；初始为 `queued`，成功不会自动 enable
或升级 baseline。Browser 只看到 credential required/configured boolean；secret、environment、raw
error/log/evidence path 不进入 API、audit、WorkflowTrace 或 identity。Plugin assignment 只是 generic
tool capability；owner/workspace/role/domain authorization 仍由 BYQ MCP/Backend 决定。

## Consequences

- 管理员可以区分 desired、generated、deploying 与 active，不会被 request acceptance 误导。
- Product stack 没有 online install、runtime self-modification 或部署权限。
- Registry 是 qualification ceiling；PostgreSQL desired policy 不是 arbitrary package registry。
- deployment lane 不可用时请求诚实停在 `awaiting_generation`，旧 active composition 不变。

## Rejected alternatives

- Browser/Backend 执行 npm、写 YAML/source/Git 或控制 Docker。
- 数据库更新后立即伪报 active。
- 使用 DSH extensions/self-modification 或 arbitrary package/version/URL/Cordis input。
- 用 DSH approval 替代 admin RBAC/deployment gate。
