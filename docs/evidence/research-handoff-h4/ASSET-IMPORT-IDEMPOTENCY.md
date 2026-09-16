# 工作区资产导入可重放幂等

2026-09-16，本地维护；Product Phase 97 不变。
修复并关闭 H4 最后一条 `product_assets_import`。

## 问题

导入原用每次请求随机的 nonce 生成 task/子项原键；相同 bundle 因丢回执重放会创建新副本。
指数/动态池导入的后端入口不接受原键（精确字段校验）。

## 修复

- Gateway 以 `sha256(owner|manifest_sha256)[:16]` 派生**确定性** `import_nonce`：同一请求体重放
  产生相同的 task/草稿/版本/回测归档/自建池原键，由 Backend 去重返回原对象。
- 模拟账户导入补充确定性 `idempotency_key`（Backend 另有 bundle_sha256 兜底）。
- 后端 `import_inactive_definition` 接受可选 `idempotency_key`，复用既有
  `stock_pool_producer_idempotency` 回执：同键同输入返回原池，同键异输入冲突，缺键保留原恢复语义。

## 验证

- Backend 真实 PostgreSQL：`services/backend/tests/test_stock_pool_producer.py`
  新增 `test_producer_import_retry_reuses_original_pool_and_rejects_conflicting_input`，6 项通过。
- Gateway 隔离容器：`services/gateway/tests/test_product_api.py`
  新增 `test_product_asset_import_reuses_stable_keys_on_retry`，80 项通过。
- `check-reliability-review.py`：`errors=[]`、`unreviewed=0`。

## 限制

- 前端未加入显式防双击；重放安全由确定性原键保证。已提交新源码候选，远端完整 CI 待跑。
- 未调用真实模型、未执行生产任务。
