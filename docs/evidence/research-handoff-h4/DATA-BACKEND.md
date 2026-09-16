# 数据 Backend 接口

2026-09-16，本地维护；Product Phase 97 不变。
审计 Backend 数据领域 27 条接口：行情读取、只读研究数据、数据中心状态/覆盖/就绪/证券目录、
同步自动化与作业、Tushare 凭据与连接测试、Agent 数据需求与上下文。

## 源码核对

- 管理写入口（自动化、同步作业、证券主数据、Tushare 凭据/测试）经 `_require_data_admin`
  要求可信 `x-byq-actor-role=admin`，非 admin 403；数据需求/上下文用 `_required_agent_context`。
- Tushare 凭据创建前 `assert_tushare_create_allowed`，更新/撤销校验 purpose/provider 及
  `expected_version`/`request_id`，按 `_credential_call` 原键回执恢复（见凭据证据）。
- `data-center/status` 校验 view（非法 422），按角色裁剪活动明细；`secrets_exposed=false`，
  不返回明文密钥；coverage 驱动 migration/quality。
- `data/research/*` 为只读持久数据读取（Agent 研究不触发 Provider 调用），字段白名单，非法 422、
  存储不可用 503；`data/daily` 为内部数据服务，Provider 错误映射 503/429/502 并附 provenance。
- 数据需求（`/v1/agent/data-demands*`）按原键冻结计划、可只读核对；通知/上下文只读。

## 本批验证

- Backend 测试：`test_data_api.py`、`test_data_provider.py`、`test_data_sync.py`、
  `test_data_demand.py`、`test_data_demand_recovery.py`、`test_market_data.py`、
  `test_market_readiness.py`、`test_market_migration.py`、`test_security_master.py`、
  `test_index_snapshot_demand.py`、`test_bounded_metadata_transaction.py`。
- 恢复证据见 [DATA-DEMAND-RECOVERY](./DATA-DEMAND-RECOVERY.md)、
  [CREDENTIAL-RECOVERY](./CREDENTIAL-RECOVERY.md)、[CREDENTIAL-TIMEOUTS](./CREDENTIAL-TIMEOUTS.md)、
  [INDEX-REPAIR-CACHE](./INDEX-REPAIR-CACHE.md)。

## 登记与限制

- 台账新增数据 Backend 27 条接口。
- 其余 Backend 族、MCP 工具、Worker/Sandbox、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
