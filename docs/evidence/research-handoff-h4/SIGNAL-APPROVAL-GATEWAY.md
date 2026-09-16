# 信号、因子与审批 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计信号快照、信号生产者、因子、Agent 审批共 9 条 Gateway Product 入口。

## 源码核对

- `product_signal_snapshots`（1087）/`product_factors`（1208）：只读 `/v1/research/artifacts`
  后按 `kind` 过滤投影为 `signal_snapshot`/`factor_result`，不创建对象。
- `product_signal_producer_list`（1112）/`get`（1122）：只读有界分页/单作业；
  `product_signal_producer_create`（1101，202）转发原键由 Backend 去重排队。
- `product_approval_get`（1218）/`product_approvals`（1230）：只读，经 `_product_approval_projection`
  仅保留允许字段解析 `conversation_id`，列表复用会话缓存。
- `product_approval_decision`（1255）：转发决策后按 `continuation_status` 触发 H3 续接投递；
  `product_approval_continue`（1276）要求已决策（未决策 409 `approval_not_decided`），否则触发续接。
- 全部入口经 `_product_principal`+`_trusted_agent_headers`；写请求 5xx/网络→`operation_outcome_unknown`，
  读请求→`backend_unavailable`，Backend 4xx→`product_domain_rejected`。

## 本批验证

- `test_product_approval_decision_forwards_owner_headers`：决策转发 owner 头与续接投递参数。
- `test_product_business_proxy_routes_forward_owner_context`：信号生产者创建/读取的 owner/actor 转发。
- `services/backend/tests/test_handoff_continuation.py`、`test_research_continuation.py`：H3 续接闭环。
- H3 本地验收见 [research-handoff-h3/AUDIT.md](../research-handoff-h3/AUDIT.md)。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。

## 登记与限制

- 台账新增信号/因子/审批 9 条 Gateway 入口。
- 仅登记这 9 条；Backend 对应入口、其他 Gateway 族、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
