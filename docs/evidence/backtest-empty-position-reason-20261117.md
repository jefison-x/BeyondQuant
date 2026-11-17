# 无持仓卖出原因码修复与测试验收（2026-11-17）

本轮是已授权投研体验维护，起点9d90b4a8，源码提交98e423b0。
复用原隔离工作树，不推进Phase 18，不推送/合并/发布生产。
只处理总清单R14，不重跑已通过的研究、补数、信号生成或策略审批。

## 原因与最小修复

services/backend/app/backtest.py原先在sellable<=0时一律返回t_plus_one，
将“没有持仓”误写成“持有但无前一交易日可卖份额”。
新增4行：先汇总该证券持仓，held<=0返回no_position，
详情为no position is held for this symbol；正持仓继续原available/T+1分支。
成交、次日开盘、费用、税、持仓计算及审批/Job/Artifact规则未修改。

4参数回归覆盖首次空仓卖出、卖尽后再次卖出，分别启用/关闭a_share_rules：
修前4 FAIL，修后加既有native_engine/analysis选择共9 PASS（15 deselected）。
分析汇总的blocked_reason_counts正确为no_position:1。
测试无网络、源码只读挂载、无产品数据卷，schema reset=0，未连接任何数据库。
dev-check --base 9d90b4a8与diff检查通过；独立部署准入Functional/Tests/Architecture PASS。
这不是对同日买卖T+1全部分支的新验收。

宿主pytest首次因缺SQLAlchemy未收集测试，日志保留，随后复用既有含依赖Backend镜像。
工作树校验初次使用默认工程根目录不匹配；明确配置当前Codex工作树根后通过，
没有重置、另建或迁移工作树。未为这些采集问题发模型或业务请求。

## 仅测试部署

启动前backtest队列只有1个completed，其余状态为0。
逐文件核对既有Backend回测模块与起点Git一致，从精确现有基底仅COPY该单文件；
派生的测试镜像不是正式清洁Release Images：

| 目标 | 新测试镜像ID |
|---|---|
| Backend | sha256:bb3841a27829aa7b5d5f205cab1d920b2abb9abee30a83ac5207380426717a4d |
| backtest-worker | sha256:f07e7171b3a1fe0646021dbbf7a8ec97ec51b703b33e890d579ec1fc3268fcfd |

镜像及运行容器模块SHA256均为5f62f08fc01da2902b70ca5a81fdfeb245945801b07b830cc56717acd3192a17。
Compose仅这两个image字段变化，以no-deps/no-build/pull never/wait更新且healthy。
前后快照：生产17项ID/image/start/health/mounts精确一致；
测试14项中其余12项精确不变，所有挂载保留。全部running，13项healthy，
原Data Worker无Docker healthcheck。用户原浏览器页、身份、历史、数据卷均保留。

## 同一冻结输入的新旧Product对照

只通过真实Gateway/Product API创建一个新回测：
backtest_36f402b37252460eb4d0de18e96eed45，completed，attempt=1。
沿用原Task、批准版本artifact_ecb6eeea833f453f85b2de87b8be7f53、
审批artifact_b62d90c9b256403782f76716e749c7d8、三股池原snapshot及
Signal Snapshot artifact_a2b6f6611841438f9dd8a13019ba5eb1；使用新的任务幂等键。
无模型调用、补数、重建池/策略/信号或新审批。

新旧manifest逐字段完全相等，ID均为
fc49e969c4f1f8a5eb07c22eae644d836c06c5d333dca57d07788fc5d04d3422。
完整结果只差新job_id、1条blocked reason/detail、对应1条log reason_code；
其他字段完全一致，包括5笔成交、佣金税费、每日现金/持仓/收益及基准。
工商2026-11-10无持仓卖出正确为no_position；分析汇总同步为no_position:1。
期末资产仍100183.315，累计收益0.183315%，原3股48交易日输入保留。

新结果Artifact artifact_6cc3a5453b894108bcdcd288c4546bcf，
对象25250字节，SHA256 e1947c289a64080a3fe9248f1f3195948439a53423ed77ffc2b14617713408a5，
规范JSON字节及哈希与持久化引用相等。
旧backtest_2f8d1d5186f64c9085b90aa6b87655f3的Product结果与原始回执完全相等，
没有重算或改写旧原因码。

真实浏览器：新结果no_position及详情、刷新持久化、5笔成交通过；
再开旧结果仍为t_plus_one，确认历史保留。只读验收Product写请求0、错误0，
截图new-reason-browser.png人工查看。
独立最终复审：Functional PASS、Tests/Product PASS、Clean Break Architecture/限定部署PASS，无阻断。
Root对R14具名样本PASS并关闭；不扩展为实际T+1分支或策略有效性验收。

私有证据：
/home/jefison/.local/state/byq-maintenance/research-candidate-20261109/backtest-reason-20261117/。
关键回执为regression-before-image.log、regression-after-image.log、
backtest-submission/terminal/result/manifest/analysis/result-artifact.json、
new-old-comparison.json、browser-result.json、deployment-preservation.json。
正式CI、完整组件套件、清洁全构建、Release Images、推送/PR/合并及生产部署NOT_RUN。
