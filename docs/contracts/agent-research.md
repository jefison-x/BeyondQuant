# Quant Research Agent Contract — Phase 13

## 所有权

DSH 负责通用 role composition、skill loading、subagent lifecycle 和 delegation transport。BYQ 负责 role catalogue、domain authorization、human approval state、business audit records 和 evidence promotion rules。

Product DSH 仅从经过认证的 Gateway 路径接收 session-scoped context header。MCP service 将该 context 转发给 Backend；model 永远不提供也不接收 product bearer token。Backend 会拒绝与 trusted context 不一致的 body identity。

## Roles

版本化 catalogue 由 `byq_agent_roles` 暴露，目前包含：

- `quant_orchestrator`：协调 hand-offs 和 consequential decisions；
- `market_researcher`：提供 normalized market evidence；
- `factor_researcher`：提供可复现的 point-in-time factors；
- `strategy_researcher`：提供 validated strategy artifacts，不负责 approval 或 execution；
- `backtest_analyst`：执行已授权的 deterministic backtest review。

每个 role 声明允许的 MCP tools、delegate targets、需要 approval 的 actions 和 evidence kinds。DSH `toolFilter` 镜像 child allowlist 以供查看；BYQ authorization 仍是权威，并通过 `byq_agent_authorize` 检查。

## Run 与审计 contract

`byq_agent_run_start` 创建 owner-scoped `agent_run`，关联：

```text
owner_principal, actor_principal, role_id/version,
trace_id, session_id, dsh_run_id, parent_run_id
```

对 Product sessions，`owner_principal` 是已认证的持久用户，`actor_principal` 是 session-scoped `byq-product-agent-<session_id>` service identity。二者必须保持不同，使 owner 能执行真正的人工 review，同时不允许发起请求的 DSH actor 自我批准。

Run identity 与 audit detail 均有界。DSH event types、prompts、raw session logs、credentials 和 storage paths 永不作为 business records 存储。`byq_agent_audit` 记录 action、outcome、resource identity 和有界 JSON detail summary。`byq_agent_audit_get` 返回 owner-scoped audit view。

## Approval

被归类为 consequential 的 actions 返回 `approval_required`。Agent 可用 `byq_agent_approval_request` 创建 pending approval；trusted human actor 通过 `byq_agent_approval_decide` 决定。发起 actor 不能自我批准。`approved`/`rejected` 与后续 `execution_outcome` 是不同字段：approval 只授权尝试，不表示 domain action 已成功。

## 稳定性

Backend storage 是实现细节。Agent-to-domain 调用使用 BeyondQuant MCP；frontend consumers 使用 BYQ audit/trace contracts，而不是 DSH schemas。
