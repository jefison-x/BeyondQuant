# Contracts

本目录保留给 framework-neutral BYQ integration contracts。
`WorkflowTraceEvent` 是 Phase 6 最小 internal envelope。DSH notifications
在 Runtime Adapter boundary 转换；任何 DSH internal event schema 都不得提升为
Gateway/frontend contract。

Typed envelope factory 见 [`workflow_trace.py`](workflow_trace.py)。
公共回答的封闭术语投影与内部 token 检查见
[`public_projection.py`](public_projection.py)。该投影只改变 Product 标签，不改变领域
证据或数值。

普通会话执行参数及其无上限缺省语义见
[`agent_execution_options.py`](agent_execution_options.py)。它们是用户级会话配置，
不构成续接许可或审批。
