# 策略读取投影错误处理

逐项读取发现 strategy_version_history 和 strategy_backtest_count 绕过现有 _research_call/_backtest_call。
真实 HTTP 测试复现5项失败：两个非法标识及两个查询的研究存储异常、数量查询的回测存储异常均返回500，预期分别422/503。
候选将原查询封装进现有错误处理函数；不改查询、owner过滤或结果排序，不新增通用处理框架。

完整策略API回归同时发现旧审批测试在创建AgentRun前用Agent身份生成版本，不符合 .96 准入合同。
仅将该测试的数据准备明确为已存在的人类上下文，并断言版本201；Agent审批及原资源绑定断言保留。
此前 .96 的60项组合包含 strategy_artifact 而非完整 strategy_api，不将原通过扩展为该模块全绿；远端旧候选可能暴露此测试失败。

本候选尚未生成独立构建身份、更新台账源码哈希、提交或推送；H4全接口与H5保留。

最终本地完整 strategy_api 与版本纠错用例14项通过（12.19秒）。复核 main.py 差异只包裹两个未登记的读取handler，其他已登记handler未改；据此更新整文件哈希，不新增全接口已完成数量。

远端 .96 CI run 34749217063 已 completed/failure：Backend 唯一失败为 test_agent_strategy_approval_is_bound_to_exact_resource_and_human_decision，strategy_api.py:299 KeyError artifact；其余组件及集成通过。与本地已复现并在 .100 修正的人工夹具一致。保留失败，不对 .96 标绿；后续 .101 需新远端验证。

## 逐接口补审（尚不关闭）

`.101` 完整远端 CI 34749941635 已成功，覆盖此前夹具修正。继续复核三个未登记入口发现：
- `_required_agent_context` 先调用 resolve_context；当前 personal-workspace.v1 仅允许每用户一个个人工作区，数据库 owner_user_id UNIQUE 与 owner membership 共同约束。不能仅凭 handler 未显式比较 workspace_id 就认定存在跨工作区泄漏，也不能把该判断推广到未来多工作区合同。
- `list_strategy_versions` 默认 LIMIT 1000，版本历史和 backtest-count 都直接消费该结果；现有测试仅覆盖205版本，不能证明超过1000版本时历史完整或计数准确。需实际数据库边界反例及修复后验证，暂不把这两个入口登记 VERIFIED_OK。
- 草稿删除已有重启原回执与跨owner测试；仍需合并核对入口上下文、存储锁等待及调用者恢复证据，不能以一次测试通过代替完整逐接口审计。

以上是源码审查发现的验证缺口；规模问题尚未实际数据库复现，不作为已确认生产事故或已修复bug计数。
