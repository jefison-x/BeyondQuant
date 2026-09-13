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

## 1005 版本真实数据库反例

使用既有隔离 PostgreSQL 测试库、当前 Backend 源码及真实 TestClient 请求，分别测试205/1005版本与versions/backtest-count两个投影：2通过、2失败（4.10秒）。1005版本时历史仅1000条，统计version_count也仅1000；当前夹具没有回测job，尚未把回测job少算作为实际复现结论。

扩展反例暂保留在本地未提交测试中，未推送失败候选。修复须让历史分页可达全部版本、统计与列表分页解耦，并贯通Gateway/Product页面；单纯将LIMIT调大不能解决正确性。`.105` 远端CI 34750787778 仍in_progress，与此新增反例不是同一源码候选。

## 分页与独立聚合修复进行中

新增 strategy_version_page：单SQL快照返回有界版本页及total，按created_at/artifact_id稳定排序，支持offset；新增 strategy_counts：按owner过滤全部策略版本，联结同owner/workspace回测后计算总数，by_version单独分页。两个Backend入口及Product Gateway转发limit/offset，Product策略页面每页50条，迟到请求不覆盖新页面。未提升原1000响应上限。

真实PostgreSQL完整strategy_api 19项通过（15.79秒）；随后增强实际回测测试：完成回测的版本置于第1001位，总数仍为1，第二页返回原版本计数1，其他owner为0，定向1项通过（2.55秒）。Gateway分页/身份转发1项通过；前端16项定向测试含逆序响应，vue-tsc与Vite构建通过。先误调用不存在的typecheck脚本，随后使用项目build脚本实际完成类型检查，不能把前一次失败算通过。

当前实现尚未提交/推送，真实浏览器验收、完整组件CI、台账差异核对与独立构建身份待完成；H4/H5仍未关闭。

真实Chromium验收已通过（1项，2.0秒）：持久测试用户登录，经Gateway/Product API读取1005版本总数和第一页50条；页面实际点击第21页，收到offset=1000的最后5条并显示synthetic-1，无pageerror。仅显式合成规模夹具，不冒充H5研究结果。三台隔离测试应用已挂载当前工作树源码，保留依赖镜像不是新镜像构建资格。

复核源码差异：Backend仅替换两个未登记投影handler，Research/Backtest仅新增专用页/计数方法；Gateway仅修改对应两个未登记投影转发。其他已登记handler和公共方法未改，据此更新相关整文件依赖指纹，不增加114/560审计完成数量。

`.107` 后续完整验证：前端66文件/210项单元测试全部通过（17.31秒）；Gateway Product API模块77项全部通过（0.87秒）；构建指纹check通过。浏览器夹具按原owner、专用task、synthetic标识与1005个精确生成ID在隔离测试库事务删除，核对任务下剩余artifact为零后删除专用task；未清理其他H5数据或访问生产。

`.107` 已本地提交df5e899；后续1c85feb仅记录固定合成幂等标识的精确历史扫描误报，57提交重新扫描无泄漏。远端`.105` 34750787778仍在运行Backend检查；未将旧候选CI当作`.107`通过，也未推送打断。

`.108`远端34751690317的frontend作业103709233929失败：唯一失败为app.spec.ts策略详情mocked UI用例；旧mock只匹配无查询参数versions路径，新limit=50&offset=0请求未命中，落到未启动Gateway而ECONNREFUSED。仅更新mock精确分页路径，不改产品逻辑或页面断言。完整模拟浏览器重跑20通过、17按资格跳过（1.3分钟），策略详情用例通过；不把跳过的真实服务测试计为通过。原远端失败保留，修复需新CI。

## 统计短查询锁等待

Research版本页已走现有有界事务，但Backtest统计仍继承普通_fetch_one。真实进程锁与PostgreSQL ACCESS EXCLUSIVE锁两个反例均复现等待持锁者4秒释放才返回200，未遵循短查询等待界限。仅strategy_counts改用既有bounded_metadata_transaction，保留SQL、返回合同与回测执行路径。两类锁冲突现在返回安全503，锁释放后同接口恢复200；完整strategy_api21项通过（27.48秒）。公共函数定义2秒进程/数据库锁等待、5秒语句期限，本轮直接验证的是锁冲突及恢复，不冒充所有慢SQL情形测试。
