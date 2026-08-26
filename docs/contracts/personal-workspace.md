# Personal Workspace Contract（`personal-workspace.v1`）

本 contract 固定 ADR-0025 接受的 tenancy boundary。它是 BYQ Product/domain contract，而不是 raw browser header 或 DSH event schema。Browser 继续只使用 same-origin Gateway/Product API routes。

## Trusted context

认证普通 browser request 后，Gateway 与 Backend 解析一个 normalized context：

```json
{
  "contract": "personal-workspace.v1",
  "workspace_id": "workspace_<opaque-id>",
  "workspace_kind": "personal",
  "membership_role": "owner",
  "owner_user_id": "user_<opaque-id>",
  "actor_user_id": "user_<opaque-id>",
  "actor_principal": "durable-auth-subject",
  "request_id": "request-correlation-id"
}
```

Values 来自 durable authentication 和 authoritative membership records。Browser bodies、query parameters、imported manifests、model output、MCP arguments 和 raw runtime events 不能覆盖它们。Private service propagation 可使用 deployment-trusted headers 或后续 signed service token，但每个 ingress 都剥离对应 public headers，Backend 验证 membership，不只信任 identity text。

初始封闭值：

- `workspace_kind`：`personal`
- `membership_role`：`owner`
- 每个 durable user 一个 active personal workspace

增加 team/member roles 或多个 active workspaces 需要后续 ADR，以及新的兼容 contract version 或明确 additive fields。

## Resource scope matrix

| Scope | Resources | Authorization source |
|---|---|---|
| User | user profile、authentication sessions、UI appearance、personal model credentials/profiles/bindings、personal Agent policy | authenticated durable `user_id` |
| Workspace | Product conversations/messages；research tasks、experiments、artifacts/transitions；Agent runs、approvals/domain audit；stock pools、immutable snapshots/references；artifact 表示的 strategies/versions；signal-producer jobs；backtest jobs/results/references；paper accounts、positions、orders、fills、controls、ledger、snapshots/transfers；learning-loop resources；portable workspace bundles | trusted `workspace_id` 加 valid membership |
| Platform | canonical securities、calendars/market bars；data-source ingestion/coverage state；platform credentials/fallback model configuration；operations budgets、monitoring、access administration/deployment audit | explicit platform RBAC/service policy |
| Engineering | engineering tasks、source-changing engineering runs 和 Engineering Plane audit | Engineering Plane identity 与 ADR-0011；绝不使用 Product workspace membership |

描述 workspace operation 的 audit rows 同时携带 `workspace_id` 和 actor identity。Platform/Engineering audit rows 不因 user 发起 authorized administrative action 而获得虚假的 personal workspace。

## Relationship rules

- Contract migration 后，每个 workspace-owned root row 都有 `workspace_id NOT NULL`。
- Child rows 为有界 queries/audits 显式携带相同 `workspace_id`，或通过 enforced parent foreign-key path 继承；不得跨 workspace。
- Workspace uniqueness/idempotency 至少按 `(workspace_id, key)`。
- Domain references 创建前及 dereference 时均验证 source/target workspace 相等。
- Platform dataset references 仍是 platform references，不改变 resource scope。
- Creator/actor fields 是 audit facts，不替代 authorization。

## Public projection

Browser 只可接收有界 orientation projection：

```json
{
  "contract": "personal-workspace.v1",
  "workspace_id": "workspace_<opaque-id>",
  "kind": "personal",
  "display_name": "个人工作区",
  "role": "owner"
}
```

其中不含 membership-management action、internal trust header、其他用户的 database identifier、raw DSH state、entitlement、billing 或 secret。Server 仍在每次 request 独立解析 authorization。

## Failure semantics

- Missing/invalid login 仍返回 `401`。
- 已认证但无有效 personal membership 的 request fail closed。
- Resolved workspace 外的 resource 返回 not found，除非更窄的 accepted contract 明确要求 non-enumerating denial。
- Write、lineage edge、approval、bundle 或 idempotency replay 中的 workspace mismatch 是 conflict/validation failure，绝不回退到 `owner_principal`。
