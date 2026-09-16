# 概览、操作与插件中心 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计概览/设置状态、工作区资产读取/导出、运维状态/预算、插件中心共 12 条 Gateway Product 入口。

## 源码核对

- `product_health`/`product_dashboard`/`product_data_status`/`product_settings_status`：只读概览；
  dashboard 对每个资源分别容错，失败记为 `unavailable` 而非伪造成功。
- `product_assets`/`product_assets_export`：只读聚合并生成可移植 bundle（`byq-semantic-json-v1`
  语义摘要 `manifest_sha256`），导出前对策略/回测/账户做可移植投影，剔除密钥字段。
- `product_operations_status`/`product_operations_budget_update`：要求 admin，非 admin→403；
  状态仅返回 normalized 投影（`raw_dsh_events: false`），预算更新转发原键。
- `product_plugin_center`/`product_plugin_detail`/`product_plugin_change`/`product_plugin_qualification`：
  要求 admin；读取装饰运行态（active/desired 是否一致），变更/资格为 202 写入口，原键透传。
- 写请求 5xx/网络失败→`operation_outcome_unknown`；读请求→`backend_unavailable`。

## 本批验证

- `test_plugin_center_projection.py`：插件中心运行态装饰与投影。
- 资产导出/导入校验用例（导出摘要与篡改拒绝）见 `services/gateway/tests/test_product_api.py`。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。

## 资产导入（已修复并登记）

- `product_assets_import`（1908）：源码审查曾发现随机 nonce 导致重放创建副本；已改为
  `sha256(owner|manifest_sha256)` 确定性原键，并为账户/生产器导入补原键。详见
  [ASSET-IMPORT-IDEMPOTENCY](./ASSET-IMPORT-IDEMPOTENCY.md)。

## 登记与限制

- 台账本批新增概览/操作/插件 12 条 Gateway 入口；资产导入修复后单独登记。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
