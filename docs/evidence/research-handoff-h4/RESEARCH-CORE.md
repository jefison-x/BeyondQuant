# 研究核心 Backend 写入口

2026-09-16，本地维护；Product Phase 97 不变。
审计研究核心剩余 8 条 Backend 写入口：任务创建与状态转换、续接许可创建/撤销、实验创建/转换、
制品创建/转换。

## 源码核对

- 全部入口经 `_required_agent_context`（多数 `include_workspace=True`）解析可信 owner/workspace，
  不接受 payload 冒用 owner。
- `create_research_task`：payload owner 必须等于可信 owner；`create_experiment`/`create_artifact`
  先校验所属 task 归属；`create_artifact` 对 `PRODUCER_OWNED_ARTIFACT_KINDS` 返回 403，
  强制走具名领域生产者，避免绕过类型化合同。
- `transition_*` 经 `_research_transition`：按原键幂等转换，校验实体 owner 与合法状态机；
  未知回执不伪装成功。
- `create/revoke_research_continuation_permission`：续接许可与撤销按原键/原 grant_version 处理，
  撤销要求精确版本（乐观并发），不自动扩展旧许可。

## 本批验证

- Backend 测试：`test_research.py`、`test_research_api.py`、`test_research_continuation.py`、
  `test_handoff_continuation.py`、`test_continuation_budget_ledger.py`。
- 交接/续接验收见 [research-handoff-h2](../research-handoff-h2/AUDIT.md)、
  [research-handoff-h3](../research-handoff-h3/AUDIT.md)。

## 登记与限制

- 台账新增研究核心 8 条写入口；其余 Backend 族、MCP 工具、Worker/Sandbox、人工面与 H5 不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
