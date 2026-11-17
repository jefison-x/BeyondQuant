# 真实数据、研究与策略回测旅程（2026-11-16）

本轮为91ecf2ff之后的明确维护/验收任务，不推进Phase 18，只授权测试。
生产不动，原测试身份、历史失败、卷和用户当前页面保留。
本记录随具名证据更新，未完成步骤不以单元测试或空回测替代。

## 数据准备与复查：所选范围PASS

Community指定缓存目录不存在，无对应PG容器，也无可证明的逻辑缓存；
未使用Clean Break旧Product归档作为数据或fixture。复用测试库已验证的11月13日数据，
仅对缺失交易日走既有可信Data Worker。管理员密钥已按先前授权配置，本轮未读/复制密钥。

普通C账号在准备面板输入600036.SH、601398.SH、000001.SZ，20260901–20261113，
未选择附加估值/财务字段。普通写403、管理员审核确认后200，回执
datarepair_c15db2961789471aa0558f945e8f09eb。Worker按既有合同按交易日同步市场数据，
标的列表限定研究范围，不表示Provider只逐只请求。自动全市场调度保持关闭。

74自然日日历完整，48开市日，所选3股144股票交易日就绪、missing=0。
Product research与backtest（含000300.SH基准）readiness均usable；
准备completed。原三股池的日期参考从每股1行变为48行，20260901–20261113。
该reference仍不是一般模型训练就绪证明；未据48根行情推荐训练窗口。
不声称历史证券目录、所有上市股票或任意日期都已覆盖。

## 必需执行组件与可运行示例

测试原11服务缺signal-sandbox/signal-worker/backtest-worker。本轮只新增这3项与专用
internal网络，沙箱无DB/provider/model凭据、无宿主端口/卷，非root、只读rootfs、
临时目录与资源限额；Signal Worker仅产品网+专网，Backtest Worker仅产品网+既有对象卷。
启动前signal队列8 completed、其它状态0，backtest空，未抢占未决旧任务。
实际运行边界回读healthy，UID分别10002/10003/10001，无模型/数据源密钥。

沙箱复用不可变镜像49bb51…，runner/server/依赖声明/bars_frame四源哈希与当前源码一致；
Worker以测试Backend7e47…派生，只COPY现有两个worker入口，镜像578be7…，脚本哈希通过。
此为已有域Job/Worker部署，不是第二harness，不替代正式清洁镜像资格。

ffd634cc将空均线模板改为5/20日均线交叉示例，参数同步Schema且拒绝小数/字符串/bool。
动量骨架仍未实现，但已明确命名并说明空信号。StrategyView 11项及类型/build通过。
实际页面提取同一模板，在隔离沙箱对144根真实原始bar检查：4个非零信号、前20日零、
前30日与全窗口前缀一致、非法参数拒绝。此烟测不替代Product复权冻结输入与成交验收。

## 新对话竞态：离线复现与真实浏览器限定PASS

旧C会话conversation_2fa…是20261021的unknown记录；首次提交503，消息/事件未增加，
没有重放/恢复/结算。随后点新对话仍503，目录没有新conversation，不能称新会话被拒。
源码与deferred回归确认：历史replay pending时new watcher被initialized=false忽略，
及catalog pending时mount再次初始化会清新草稿。

a0a2d4d0仅改AgentView代次保护，两个回归修前FAIL修后PASS，
完整38spec/类型/diff通过，独立架构/功能准入PASS，只更新测试前端。
真实C浏览器新对话为干净timeline、草稿保留、不自动发送。
C没有模型配置，正向研究整链改用已有配置A，未复制凭据，不称C整链通过。

## 本地研究与任务保存：A限定PASS

真实浏览器新建conversation_a4977d3bb95e45fdbbf616c10fc7a5ba，
确认创建回包session_id与发送路径相同，HTTP202 accepted=true。
采集曾误期待200而断言失败，保存已受理run后只读观察，没有重新发模型。
root 7bc3af6a207d480ab537a7118dd8bcd1 completed/closed、unknown=0，
52.137301秒，21模型请求均200，工具错误0；3次日线、1次估值、1次会话、
1次Task create及对应6次authorize/audit，无Web搜索、策略/回测或更多补数。

独立重算首日前收盘到末日价格变化：招商40.12→42.93为7.00%，
工商8.07→8.85为9.67%，平安11.72→12.07为2.99%；末日PE/PB/dv_ttm与原表一致。
报告区分不含分红再投资的价格变化、TTM股息率和未核实方案。
Tushare的pre_close定义为除权昨收价，已核[官方daily说明](https://tushare.pro/document/2?doc_id=27)，
不凭价差猜具体派息金额或再投资收益。

Task task_4ff375fe65c54dff8f56ed2e000e5665，名称真实行情验收_三银行均线_20261116，
GETtask-options确认planned。只登记计划，不声称策略/回测已完成。
独立Reviewer与Root对本数据/研究范围限定PASS。

## 策略保存期间发现的阻断（历史失败保留，后续已修复）

真实验证201保存draft artifact_f8b81bcad6e744e4a3d5ab2e6e1c2574，
策略RealBankMA20261116，属于上述新Task；没有重复提交。
随后validateDraft刷新目录却默认选中11月1日旧version，editor消失；
另createVersion路径会留在旧draft。已暂停审批，未误批旧资源。
后续按返回Artifact ID精确回选并GET详情核对；修复与最终结果见下节。

私有证据根目录：
/home/jefison/.local/state/byq-maintenance/research-candidate-20261109/coverage-journey-20261116/。
采集定位/工作目录/状态码断言失败日志保留，均不算Product通过。
正式CI、清洁全构建、Release Images、推送合并及生产部署NOT_RUN。

## 精确策略选择修复与审批：PASS

8a606bc4修复validateDraft/createVersion目录刷新后选错资源：使用返回Artifact ID，
目录尚未包含时以返回对象定位，再GET详情核对ID。两个deferred回归修前FAIL修后PASS，
StrategyView全部13项、类型与build通过，独立Functional/Architecture PASS。
只更新测试Frontend为sha256:795d9aee2d46ea89e778e61ee588728d659824118ff8033ce8105a3d0d065364。
没有重复验证或创建草稿。

现有draft f8b81…冻结为artifact_ecb6eeea833f453f85b2de87b8be7f53。
真实浏览器确认选中新版本后，请求approval_request_ca1717721f804deea9b2884ed29ad6d3，
测试管理员通过业务审批界面显式批准精确版本，形成artifact_b62d90c9b256403782f76716e749c7d8。
这不是代码合并审核，也不是生产部署授权；审批本身没有启动Job。
后续作业由浏览器明确点击生成信号、创建回测。

## 真实信号与回测：具名完整旅程PASS

研究52.137301秒 → 保存planned Task → 可运行均线模板 → 验证草稿 →
冻结精确版本 → 测试审批 → 原三股池精确快照 → 冻结输入与信号 → 回测 →
指标/明细/完整清单 → 刷新后持久化，已通过真实Gateway/Product API及浏览器完成。
复用已有观察池，没有重复创建池；不把本轮“研究→已有池回测”扩称
“从零新增观察池→再次联网研究”整链验收。策略使用可运行模板及默认参数，
没有验证任意自然语言自动生成策略。

- Signal Job：signaljob_4ed40d1cab6c4b70a72a5d4484b64e86，completed，attempt=1。
  创建到完成0.958078秒，Worker执行0.563623秒；144根bar、3股、48交易日。
- Signal Artifact：artifact_a2b6f6611841438f9dd8a13019ba5eb1。
  原池snapshot 273e…9b42、策略ecb6…7f53、Task 4ff3…5665精确绑定。
  冻结输入SHA256为0c00a08fb7904366da105efa9292949bf4420a57f7bd6225c2ac66e082605b58。
- Backtest Job：backtest_2f8d1d5186f64c9085b90aa6b87655f3，completed，attempt=1，
  创建到完成1.038883秒；结果artifact_8a8d04d02bb047b78d266ea869afb512。
- 输入manifest fc49e969c4f1f8a5eb07c22eae644d836c06c5d333dca57d07788fc5d04d3422；
  结果对象25245字节，SHA256 f18ec5481c5acd7b10646c0dfac257b52071158647e046051dab03c0580d75d0。
  Product结果规范JSON的实际字节数及哈希与持久化引用完全一致。

实际策略消费冻结复权research frame，执行使用冻结原始行情。独立用窗口求和重算，
6个非零信号逐条一致，前20日没有信号：
平安/招商10月9日买，平安10月21日卖、11月2日买，工商11月9日卖、11月12日买。
原始bar隔离烟测4个信号不代表本次复权结果，未混用两种证据。
列存frame与manifest行排序不同；按日期+证券规范排列后144行逐字段完全相等。

5笔成交都在下一交易日原始开盘价执行，每笔100股：
平安10月12日11.62买、10月22日11.41卖、11月3日11.56买；
招商10月12日41.56买；工商11月13日8.65买。
工商11月10日卖被拦截，原因码t_plus_one、详情no prior-session lot is sellable；
实际当时没有持仓，不能据此声称已验同日买入再卖的T+1分支。
佣金0.0003、卖出税0.001、滑点0、初始资金100000、最大持股10为冻结示例假设，
不是对当前券商收费或法定税率的核实。卖出税1.141、卖出佣金0.3423，
该笔含买卖费用已实现损益-22.8319，独立核算一致。

期末资产100183.315，累计收益0.183315%，最大回撤0.1532528%，
000300.SH基准收益-12.90594212%。基准按同窗首日收盘归一，48点完整；
收益、期末现金+持仓、最大回撤和基准独立重算通过。
此100股示例大部分资金未投入，不据短窗结果判断策略有效性；
本次没有持仓公司行动，不冒称分红到账分支或全部撮合规则通过。

真实页面交易明细5行、拦截原因、每日明细、技术详情精确版本、显式加载完整输入均通过。
刷新后指标与同一Job保持；此只读验收Product写请求0、Product错误0。
截图backtest-result-browser.png已人工查看。
凭证independent-signal-backtest-check.json、backtest-browser-result.json及上述具名回包保留。

## 环境保留、限制与剩余项

最终对比两份JSON快照：生产17容器的ID/image/StartedAt/health/mounts精确相同。
测试原11项中10项精确不变，只有Frontend更新，全部原挂载保留；
新增3个必要执行服务。14项running，其中13项healthy，
原Data Worker未定义Docker healthcheck，不能说14项均healthy；
其真实准备Job完成已另验。自动全市场调度仍关闭。

保留采集错误：首次用不存在的python命令未执行任何操作；冻结行未排序比较失败后
只读核对为排序差异；快照初次混用tuple/list及假设每项有healthcheck均已停止受影响检查，
核对保存JSON和真实定义后纠正。未据采集错误重发模型、补数、审批或回测。

O09历史证券目录覆盖、O12拼音、R08扫描/OCR及复杂表格仍未关闭。
O10三股真实连续覆盖已补齐，但48交易日不足以证明一般训练三窗口可用，
自动日期推荐仍未实现。R06本轮证明所选长窗准备及后续新研究；
不替代“同一旧会话跨多字段恢复”的所有分支。
C普通账号没有模型配置，本轮其新对话与权限引导通过，完整正向整链仅A通过。
正式CI、清洁全构建、Release Images、远端推送/PR/合并、生产部署仍NOT_RUN。
测试服务、原页面、身份、旧unknown历史和数据卷保留。

## 2026-11-17 独立复审与Root验收

额度恢复后仅补证，未重跑真实研究、补数、审批或回测。复读快照确认两套环境与11月16日最终库存一致。
独立Reviewer：Functional限定PASS、Tests真实Product/独立算术/浏览器PASS、Clean Break Architecture PASS。
Root对上述具名旅程限定PASS，保留无持仓卖单原因码语义缺陷及全部未验范围。
最终独立复审明确：该原因码缺陷不影响本次收益/持久化计算，未要求扩大部署。
