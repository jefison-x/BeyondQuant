# Quant Research Agent Contract — Phase 13

## 所有权

DSH 负责通用 role composition、skill loading、subagent lifecycle 和 delegation transport。BYQ 负责 role catalogue、domain authorization、human approval state、business audit records 和 evidence promotion rules。

Product DSH 仅从经过认证的 Gateway 路径接收 session-scoped context header。MCP service 将该 context 转发给 Backend；model 永远不提供也不接收 product bearer token。Backend 会拒绝与 trusted context 不一致的 body identity。

## Roles

版本化 catalogue 由 `byq_agent_roles` 暴露，目前包含：

- `quant_orchestrator`（v1.2.0）：协调 hand-offs 和 consequential decisions；当用户明确要求时，
  可经 BeyondQuant MCP list/get/create 当前 owner/workspace 的 custom Stock Pool；
- `market_researcher`（v1.2.0）：提供 normalized market evidence 和冻结的候选列表，
  不创建或修改股票池；
- `factor_researcher`：提供可复现的 point-in-time factors；
- `strategy_researcher`（v1.2.0）：可创建其校验所需的 owner-scoped ResearchTask，并提供
  validated strategy artifacts；不负责 task transition、Stock Pool 写入、approval 或 execution；
- `backtest_analyst`：执行已授权的 deterministic backtest review。

每个 role 声明允许的 MCP tools、delegate targets、需要 approval 的 actions 和 evidence kinds。DSH `toolFilter` 镜像 child allowlist 以供查看；BYQ authorization 仍是权威，并通过 `byq_agent_authorize` 检查。

Phase 58 的 Stock Pool 权限是封闭集合：协调角色只有 `byq_pool_list`、
`byq_pool_get`、`byq_pool_create`；snapshot、lifecycle、delete、index/dynamic
writer 均不在 Agent 权限内。用户明确要求创建 custom pool 时不增加第二次审批，
但 Agent 必须先授权、使用 trusted owner/workspace context 调用 MCP，并记录真实 domain
结果。禁止通过切换 role、猜测内部 ID 或扩大候选范围绕过拒绝。

Strategy 生成只有一个 Backend 权威合同：脚本定义且只定义一个同步输出入口——
`CustomStrategy.generate_signals(self, data, parameters)` 或
`CustomStrategy.generate_target_weights(self, data, portfolio_state, parameters)`。
MCP schema 同时保留可选的 `data_requirements`。遇到 BYQ 422 时只使用安全、有界的
校验摘要修正一次；第二次同类校验失败即停止并向用户说明，不猜测 task state、role 或
内部 Artifact ID。

Phase 59 只为 `quant_orchestrator` 和 `market_researcher` 增加
`byq_market_valuation`、`byq_market_fundamentals`。估值请求必须使用一个精确交易日；
基本面请求必须使用 point-in-time as-of date，并在回答中保留报告期、公告日和次日生效日。
两个工具只读取 BYQ 已持久化数据，不代表 Provider refresh。只有
`coverage.usable=true` 才能用于排名或选择；否则必须保留 null/missing，说明缺口并建议
Data Center 同步，不得用 later report、模型记忆或外部数字填充。

Phase 64 将 `market_researcher` 升级为 v1.4.0，并增加 search-only `web_search` 与专用
`byq_web_evidence_create`。搜索只补充当前公开背景、解释和候选发现；采用来源必须保留 URL、
title、publisher、published/retrieved time、tier、query 和 research as-of。PRIMARY 优先，
SECONDARY 交叉验证，AUXILIARY 只能提供线索。未来/未知发布时间不能支持 historical claim；
因果结论没有 PRIMARY 时必须说“现有证据无法建立原因”。

Factor、Strategy、Backtest role 不拥有 Web Search 或 Web Evidence promotion。Coordinator 因
qualified rc.1 root seam 可见搜索工具，但必须把专业搜索委派给 Market Research，且不能将结果
传为 deterministic input。网页结果只有在用户明确要求保存时才通过专用 MCP 晋升到现有
Artifact；不得通过 generic Artifact payload 绕过 `web-research-evidence.v1` validator。
Web evidence 422 只向 Agent 暴露固定枚举的安全校验码，不回显原始输入或内部错误；同一保存
动作最多修正一次，第二次失败必须停止并记录真实 failure。

Authorization 的 `action` 必须是随后调用的精确 MCP tool name，不允许使用
`market_daily.read` 等自创别名。每个不同的已授权 domain action 都分别记录真实 success/failure；
不得把 authorization 误述成执行成功，也不得声称不存在的审计记录。普通用户回答只描述
“正在读取数据 / 保存股票池 / 校验策略”等产品动作，不暴露 role ID、skill loading、MCP
tool name、validator/runtime/worker 名称或内部 Artifact ID。

Strategy 的固定动作顺序为：若没有 task，先 authorize → create → audit
`byq_research_task_create`；然后 authorize → validate → audit
`byq_strategy_validate`；最后 authorize → create version → audit
`byq_strategy_version_create`。后一个动作的 authorization 不得覆盖前一个 prerequisite。

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
