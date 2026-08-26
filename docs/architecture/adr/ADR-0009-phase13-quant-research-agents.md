# ADR-0009：Phase 13 Quant Research Agent Boundary

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 13 Product/Agent/Quant Domain integration
- Supersedes: 仅替代 Phase 13 Approval Contract placeholder

## 背景

Phase 9-12 建立了 BYQ-owned Research Entity、Factor、Strategy Artifact 和确定性
Backtest job。Phase 13 需要专业 quant research role，但不能重建通用 Agent Harness，
也不能把 domain authority 移入 DSH。Community audit 提供有用的 role/tool allowlist、
delegation、Approval 和 audit invariant；其 Agent Service persistence、runtime coupling
和 direct business API 不兼容 BYQ。

## 决策

1. DSH 提供通用 role mechanism：现有 Product preset、filesystem Skill、official
   `dsh-subagent` seam、official `dsh-subagent-spawn-in-process` provider，以及带明确 child
   `toolFilter` allowlist 的 `dsh-tool-subagent` instance。BYQ 不创建第二个 Agent Loop、
   Workflow engine 或 runtime。
2. BYQ 持有 versioned role catalogue，包含五个 role：orchestrator、market researcher、
   factor researcher、strategy researcher 和 backtest analyst。Role definition 包含允许的
   MCP capability、delegation target、需要 Approval 的 action 和 evidence kind。
3. Gateway 在 session create 时将 authenticated Product principal 传给 private Runtime
   Adapter。Adapter 只将 owner、actor、trace、session 和稳定 DSH correlation value 放入
   DSH-owned MCP client header；绝不传 Product bearer token 或 model credential。
4. MCP 提取 request header 并转发给 Backend。Backend 将 Agent run、Approval 和 audit
   record 绑定到 trusted context；identity mismatch 时 fail closed。Agent argument 不能
   覆盖 trusted context。
5. Backend 在 BYQ domain storage 中持久化 `agent_runs`、有界 `agent_audit` event 和
   `agent_approvals`。DSH run/session identifier 是 correlation metadata，不是 BYQ
   business state machine。
6. Consequential action 需要 pending BYQ Approval；发起 actor 不能 self-approve。
   Approval state 与后续 execution outcome 保持分离，且二者均可审计。

## 后果

- 专业 child 只获得其 role 所需 MCP tool；Product composition 中 recursion 限制为一层。
- Role Contract 可通过 normalized MCP result 和 BYQ audit view 观察，不暴露 DSH
  internal event schema。
- Phase 9-12 invariant 继续具有权威性；本 Phase 不增加 source execution、live trading、
  DSH database access 或未经 review 的 evidence promotion。
- 因 rc.6 MCP composition 不暴露 dynamic per-call header，使用稳定 DSH session 作为
  per-session correlation value；后续 ADR 可以增加 per-turn signed correlation carrier。

## 拒绝的替代方案

- 复制 Community Agent Service role、SQL repository 或 PydanticAI/Hermes runtime：违反
  当前 ownership 和 runtime 决策。
- 构建 BYQ orchestration loop：重复 DSH 通用能力。
- 信任 model 提供的 owner/actor field：允许 cross-owner audit 和 Approval access。
- 将 Approval 视为 execution success：丢失 failure 和 retry evidence。
- 给予 Product DSH 直接 PostgreSQL/SQLite、provider、filesystem 或 source access：违反
  架构边界。

## 退出证据

Phase 13 test 覆盖 role allowlist、delegation target、trusted context binding、owner
isolation、self-approval rejection、独立 execution outcome、audit view、MCP context
translation、DSH configuration，以及 Product DSH 不具备 source/engineering capability。
