# H5 真实三轮研究验收记录

2026-09-16/17，本地维护；Product Phase 97 不变。真实付费模型、隔离栈、合成数据。

## 结果（独立校验器）

`tests/dsh_upgrade/h5_research_contract.py` 的 `verify_completion` 在隔离栈内实际持久对象上通过：

- scenario：`h5-three-backtests.v1`，owner `h5-research-user`，任务 `task_578676601acb42a29c8f27398d4bebff`
- 三轮回测均 completed、同一冻结快照、三个不同策略版本：
  - `backtest_1309fb035b37490a82d9048a58d4a978`（+3.350237%，选优）
  - `backtest_4b244de3751c41aca4628eeadce31401`（+1.257846%）
  - `backtest_bd366d47089941f78c2ca7adf7756e54`（0.000000%）
- 报告 `artifact_a962c78f66c341ccba804b047e8196cc`（`research_report`，validated），候选与三 job 精确一致，`selected_job_id` 为最高收益
- 模拟账户 `paper_account_ca43edc3ddaf4248a02dd28ad9a4fdb6`（active，绑定原冻结池与快照）
- 原任务 completed 且保留报告为完成证据

## 本轮修复（使真实三轮回合可完成）

1. **领域调用证据绑定**（驱动/夹具）：种子任务必须绑定到模型 Product 会话，否则
   `consume_domain_call_evidence` 拒绝，准入停在 `call_evidence_pending`。
2. **审批续接**（`services/gateway/app/main.py`）：runtime 对瞬时新根竞争返回 409 时按有界退避重试，
   且复用原 `idempotency_key`；新增 `_transient_root_conflict` 与测试。此前续接被判永久失败。
3. **续接顺序合同**：批准续接指令与 `byq_backtest_task_get` 说明明确——已获批但从未提交的动作必须
   用原键执行一次；原键查询只用于找回“响应未观测”的执行，不能用于推断未执行动作已发生。
4. **策略执行合同**（`plugins/dsh-byq/skills/byq-strategy-researcher/SKILL.md`）：写明
   `(symbol, trade_date)` 索引、输出 `{symbol: Series(-1/0/1)}`，并说明
   `generate_target_weights` 当前执行 profile 不支持。
5. **合成数据夹具**：交易日历覆盖每个自然日、`market_session_supplement_completeness`、
   `market_daily_status`、`market_adjustment_factors`，并修正 `market_daily_bars.pre_close`
   与前一交易日收盘一致（此前导致 `prev_close is inconsistent`）。

## 限制

- 合成数据、合成用户、固定提示；不代表生产数据或生产发布。
- 隔离栈为本地临时 override（模型网络启用、注入 DEEPSEEK_API_KEY）；仓库内 h5 候选栈仍保持
  `execution-authorized=false`。
- 构建版本推进至 `dsh-0.1.2rc1-post-u8.115`；远端完整 CI 待新候选验证。
