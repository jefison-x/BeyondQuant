# ML 研究 Backend 接口

2026-09-16，本地维护；Product Phase 97 不变。
审计 Backend `/v1/research/ml/**` 20 条领域接口：能力/选项/研究/工作区、策略建版/审批、
训练提交登记/创建/核对/列表/取消、预测创建/列表/详情/行。

## 源码核对

- 全部入口用 `_required_agent_context(request, include_workspace=True)` 解析可信 owner/workspace，
  不接受 payload 覆盖；跨 owner/workspace 或跨 task 的对象一律 `ResearchNotFound`。
- 训练创建（`create_ml_training_run`）要求 validated `ml_strategy_version` 且已有**人类批准**，
  冻结股票池快照/成员指纹/数据需求分区后 `ml_training_store.create_waiting`（原键去重），
  返回 202；4xx 且原键合法时 `reject_receipt_watch` 显式拒绝原回执，避免残留未知。
- 训练提交登记/核对（`register_ml_training_submission`/`get_ml_training_submission`/
  `get_ml_training_run_by_idempotency`）以原键在 owner/workspace 内只读核对，不跨工作区暴露。
- 预测创建（`create_ml_prediction_run`）要求 validated 模型/bundle + 已批准 ML 策略，
  校验专家/regime/feature 血统、训练数据 provenance（ready_input_sha256）并显式冻结
  `initial_capital`/`lot_size` 后 `ml_prediction_store.create`（原键去重），返回 202。
- 取消/读取为领域状态转换，按 owner/workspace 过滤。

## 本批验证

- Backend 测试：`test_ml_api.py`、`test_ml_training.py`、`test_ml_prediction.py`、
  `test_ml_strategy.py`、`test_ml_validation.py`、`test_ml_validation_boundaries.py`、
  `test_ml_regime.py`。
- Gateway 侧同族入口见 [ML-RESEARCH-GATEWAY](./ML-RESEARCH-GATEWAY.md)、
  [ML-STUDY-GATEWAY](./ML-STUDY-GATEWAY.md)。

## 登记与限制

- 台账新增 ML Backend 20 条领域接口。
- 仅登记这些；其余 Backend 族、MCP 工具、Worker/Sandbox、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
