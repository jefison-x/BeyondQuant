# ADR-0087：确定性模拟账户审批与创建（研究闭环收口）

- Status: **Accepted**
- Date: 2026-09-25
- Accepted: 2026-09-25（维护者明确接受模拟账户进入研究闭环的第一种架构方案：
  由 BYQ 确定性 plan/approval/action 执行，模型只能提出“建议进入模拟验证”，
  不能创建账户、选择账户 identity、批准、生成幂等键或执行交易。）
- Decision owner: BeyondQuant maintainer
- Relates: ADR-0085（P4-B）、ADR-0086、ADR-0021（Paper Trading）、ADR-0044/0051（审批与对话接续）
- Scope: 仅 0.9.1 的 P4-B 研究闭环收口。不授权真实账户、充值、订单、持仓/成交变更、
  生产部署、canary、tag/release、付费资源、0.10.0 或 Phase 100 恢复；不增加 Product DSH
  的 Engineering/source/Git/DB 权限，也不给 DSH/MCP 写 paper account 的能力。

## 背景

ADR-0085 P4-B 的正常三轮研究主链已真实观察到，但 `paper-account` 行是 required/gating 的
**BLOCKED/false**：现有闭合 plan/approval 合同没有 paper-account gate 或 approval action，
MCP 也没有 paper-account 写工具。此前由驱动直接经 Product API 创建账户，缺少精确 plan/approval
绑定，因此 P4-B scoped verdict 只能 `all_pass=false`。

维护者 2026-09-25 接受第一种架构方案：模拟账户进入研究闭环必须走 BYQ 确定性 plan/approval/action。

## 决定

### 1. 研究闭环以确定性账户门收口

`final_selection` 提交后，BYQ 确定性状态机**不得直接假定研究闭环完成**，而是进入具名等待
`waiting_for_paper_account_approval`；审批通过后进入 `ready_to_create_paper_account`；
确定性创建成功并完成 CAS 后，plan 与 ResearchTask 才转 `completed`。新增动作、阶段、
前置/后置条件、资源种类和 approval action 全部进入现有闭合 plan/action 引擎，**不建旁路**。

### 2. 模型只能提出建议

模型仍只能提交有界 `research-proposal.v1`（`final_selection` 的 `select_iteration`）。
模型**不能**创建账户、选择账户 identity/名称/现金、批准、生成幂等键、决定 routing/recovery，
也不获得任何写 MCP。账户参数与身份由 BYQ 服务端从已持久化 task/plan/final-selection/policy
defaults 派生；客户端或任意调用方不得选择或覆盖这些字段。

### 3. Approval 精确绑定 plan command

`request_plan_approval` 在 `waiting_for_paper_account_approval` 铸造精确绑定 owner/workspace、
ResearchTask、`plan_version`/`task_version`、plan action `paper_account_create`、
resource kind/id（`research_task`/`task_id`）、BYQ 计算的 `params_digest` 和 BYQ 铸造的
`plan_idempotency_key` 的 `agent_approvals` 行。stale/wrong/denied/missing/reused-different-payload
一律 fail closed；审批决定仍由人工经既有 Product API 边界完成，模型或 MCP 不得批准。

### 4. 经现有 Product API 边界执行确定性创建

审批通过后，plan 进入 `ready_to_create_paper_account`。BYQ 受信 seam 提供只读的
`paper_account_create_parameters`（派生 name/cash/idempotency key/params digest/plan binding），
受信消费者经**现有** Product API `POST /api/product/paper/accounts` 边界创建账户，复用
`PaperTradingStore` 的 owner/workspace/idempotency/audit 能力。Backend **不反向调用 Gateway**，
MCP/DSH **不写** paper account。账户创建动作**不**创建订单、持仓或成交。

### 5. 确定性 CAS 提交 receipt 并收口

创建成功后，受信 seam `apply_deterministic_action_result` 校验账户属于该 task 的
owner/workspace，把 `paper_account` reference 与 receipt 经既有 plan CAS 原子提交，并使
plan 与 ResearchTask `completed`。失败保持可解释 pending/`needs_attention`，不得让模型重新
推导 next_action。

### 6. 幂等、重放与并发

精确 replay（同一 account/idempotency key）返回同一账户与 receipt，provider/model 调用为 0；
并发 replay、进程重试和重复审批不得生成第二个账户（依赖既有 plan CAS、
`paper_accounts(owner,name)` 唯一约束与 `PaperTradingStore` idempotency/audit）。

## 验收标准

1. 合法审批闭环：plan `final_selection → waiting_for_paper_account_approval →
   ready_to_create_paper_account → completed`，且 ResearchTask `completed`。
2. missing/wrong/stale/denied approval、错误 owner/workspace、params digest/idempotency
   mismatch 一律 fail closed，不创建账户、不推进 plan。
3. 相同 replay 返回同一账户/receipt；并发 replay 与重复审批不产生第二账户。
4. 创建成功但提交响应丢失后，重放同一 account 得到同一 receipt，plan 收敛一次。
5. 账户创建不产生任何 order/position/fill。
6. 确定性段 provider/model 调用为 0；模型只提交有界 proposal。
7. 真实隔离非生产旅程证据包含精确 approval object、plan binding、创建 receipt、
   相同 replay 与对象唯一性。

## 后果与回滚

- 研究闭环增加一个确定性的账户门和一次受信 Product API 创建，不新增第二 harness、
  session store 或 DSH 权限。
- `paper-account` 行只有在全部原始观察满足时才能为 true；P4-B scoped verdict 才能
  `all_pass=true`，且**不**代表整体 P4/P4-C/P4-D 通过。
- 回滚：将 plan 停在 `waiting_for_paper_account_approval`/`needs_attention` 并保留全部账户、
  审计与回执；不删除已创建账户，不自动重试。

## 非授权

本 ADR **不**授权真实券商账户、入金/充值、订单、持仓或成交变更、生产部署、生产 canary、
付费 API、tag/release、0.10.0 或 Phase 100 恢复，也不授予 Product DSH Engineering 权限。
