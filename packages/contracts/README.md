# Contracts

本目录保留给 framework-neutral BYQ integration contracts。
`WorkflowTraceEvent` 是 Phase 6 最小 internal envelope。DSH notifications
在 Runtime Adapter boundary 转换；任何 DSH internal event schema 都不得提升为
Gateway/frontend contract。

Typed envelope factory 见 [`workflow_trace.py`](workflow_trace.py)。
