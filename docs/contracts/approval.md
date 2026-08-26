# Approval Contract

## 目的

定义在执行有重大影响的 domain actions 前所需 business approvals 的未来 BYQ contract。

## 所有权

BYQ 负责 approval identity、policy、authorization、audit、state transitions 和 business idempotency。

## Phase 13 结构

Phase 13 `agent_approvals` contract 记录有界 `run_id`、owner 与 initiating actor、consequential action、reason、`pending`/`approved`/`rejected` decision state、reviewer identity、rationale，以及独立的 `execution_outcome`。Initiating actor 不能自我批准。所有 records 都是 owner-scoped，并通过规范化的 BeyondQuant MCP tools 访问。

## 非目标

- 不取代通用的 DSH human interaction。
- 不允许 agent 自我批准 consequential business action。

## 稳定性保证

Approval semantics 必须保持为 BYQ domain contract。DSH 可以请求或展示 approval，但不得拥有 business approval state。
