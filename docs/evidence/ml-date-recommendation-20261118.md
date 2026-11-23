# 模型日期建议整改与测试（2026-11-18）

起点abdf395e，源码492aaaaf；复用现有隔离工作树、账号、股票池与数据。
属于已授权体验维护，不推进Phase 18，不推送/合并或部署生产。
只更新测试Backend/Gateway/Frontend；保留原页面、数据卷、身份、历史失败及unknown。

## 实现与边界

为默认单模型入门（compatible/v1）添加只读日期建议。选池后按可信owner/workspace、
active/current snapshot及计算后版本重查取数；仍保留原日期参考聚合的Tushare语义。
不采用group coverage SQL优化，避免既有UPDATE路径投影维护差异扩大范围。

完整公共观察区间超过401自然日或50,000成员-交易日单元即inspection_limit，
不悄悄裁取最近历史。检查完整自然日日历、canonical readiness与逐股逐开市日panel，
复用原feature builder核对训练/验证标签各留在自己的split，以及最低样本20/5/1。
reference_only=true，引用层continuous_history_verified/training_readiness_verified仍false。
嵌套recommendation仅对该窗口给连续性和最低样本标志，training_quality_verified始终false。
Unavailable保持recommended_dates=null并明确原因；不生成Artifact、Study、Job或训练。
滚动验证和市场状态模式不套用此建议。

前端从selected_pool_data_reference读取建议；只在精确池/版本/auth/horizon匹配、
日期有效且两项核验标志均true时显示采用按钮。显式点击才填六日期，已有日期先确认；
请求加载、切换周期或方案不自动覆盖。样本单位是“条样本”，不是交易日。
无建议仍允许手动规划，实际训练继续走原准备与审批。

## 本地验证

- 现有Backend纯逻辑模块2PASS，schema_resets=0、store_bootstraps=0。
  50sessions、3股票、h5夹具经原builder得30/9/21条；缺日历/缺bar/单股样本不足均拒绝。
- Gateway可选周期与可信身份透传1PASS；未传周期保持旧URL，h21返回422。
- Frontend22PASS，含嵌套合同、显式采用、模式/核验标志、池/版本/horizon/auth/关闭竞态；
  build含vue-tsc通过。Root复用最终构建，未机械重复。
- ML架构边界2PASS；dev-check --base abdf395e和diff-check PASS。
- Backend数据库API/路由合同本地NOT_RUN，正式受影响CI仍required。
  宿主缺sqlalchemy；现有镜像收集test_ml_api时main启动连默认PG而失败，原日志保留。
  停止该批后只将新增纯测试搬至既有不导入main的test_ml_training模块，没有另起PG、
  stub存储或第二套harness。真实Product运行补验不冒充数据库CI。

独立Sol源码审查：Functional、Tests限定、Clean Break Architecture准入PASS，
只允许测试三组件；Root随后执行下列真实验收。

## 测试部署

源码492aaaaf；基于原受测镜像只复制三个Backend模块、一个Gateway模块及已构建Frontend dist。
构建前原模块与abdf395e一致，新模块/静态入口hash核对通过。测试镜像：
- Backend fa326b2ebecb1e45fb3e6555a837413ff194225584403bd63079c26ed183a9d5；
- Gateway 3bba4ef1ee79007016d7d6160bc46aaf18d4d0146a673f27a634e882a761e806；
- Frontend 6100c04251388133f55935099c083d42cbe697bf723ef53415a2daef560639d8。

原Compose已私有留档，只替换三image字段；--no-deps --no-build --pull never --wait通过。
三个目标healthy。这些是限定本地测试增量，不是正式Release Images资格。

## 真实Product与浏览器阴性PASS

复用三股池stock_pool_944367de0d5f49fbad35c36a574d181d及其原snapshot，
三成员各50条日线，公共观察区间20260901–20261117；14–15日历记录缺失。
h5返回unavailable/calendar_incomplete、counts=null、六日期为null，
引用及嵌套核验标志均保持未验证。
真实浏览器选择此池后显示缺日历原因、采用按钮不出现、六日期空白，Product写0。
非法h0/h21均422，C账号读A池404，规范但不存在pool ID404；
无pool请求保持旧shape，不在顶层暴露recommendation。

## 唯一补日历请求失败：阳性仍NOT_RUN

仅提交一次原Product准备接口，范围三股20261113–20261117。
request_id=datarepair_6b8b0ceeba2248a58fedc31e74c825da，
08:30:42UTC queued，08:30:44UTC claimed后失败，内部只记录ProviderUnavailable。

一次同参数、8秒上限、无重试的只读传输诊断复现：
api.tushare.pro HTTP200、业务码50101、data不存在；
供应商消息明确其上游地址连接被拒绝。
这是当前同参数诊断回执，不声称保留了首次失败的完整供应商响应。
没有更换凭据、绕路取数、猜测日历、合成数据或重试准备记录。

因此：真实“补齐→available推荐→显式采用”阳性NOT_RUN/外部数据阻断。
O10整体尚不能关闭；纯夹具阳性与前端单元通过不能替代真实阳性。
待该日历请求恢复正常后，复查原failed记录并通过正常Product重试流程继续验收，
不另造需求或删失败。

## 最终保护与结论

最终库存生产17项逐字段精确不变；测试14中仅Backend/Gateway/Frontend三目标改变，
其它11项和全部挂载保留，13healthy、既有Data Worker无healthcheck但running。
150条原行情hash、50个session jobs的状态/attempts、0个data_sync jobs、
研究任务/Artifact计数、0个ML训练与预测以及关闭的自动调度均保持不变。
只新增1条失败repair，日历未改变。两条10月21日撤权unknown完整记录前后相等，
未恢复、重放或结算。

独立复核：阴性流程限定PASS，阳性NOT_RUN，架构与环境保护PASS。
Root同范围接受，保留当前测试环境；不以外部失败或单元测试冒称O10整体完成。
模型调用0、新研究/Study/训练/预测/回测0，故本轮不产生研究耗时比较结论。

私有证据目录：
/home/jefison/.local/state/byq-maintenance/research-candidate-20261109/ml-date-recommendation-20261118/。
含scope、前后库存/数据hash/unknown、三镜像hash、测试与部署日志、
真实API错误/缺日历响应、浏览器截图/写入计数、唯一准备失败和供应商诊断。
采集/构建错误也保留或记录：dist被根dockerignore排除后仅改为dist构建上下文；
无效missing-pool ID本应422，改用规范32hex后404；页面两个同名新建入口造成严格选择器失败，
核对后限定首入口。上述均不产生产品执行或模型调用。
生产发布、正式远端CI和Release Images保持NOT_RUN。


## 11月22日恢复复验

北京时间15:37，测试Worker使用现有凭据向Tushare官方HTTPS发出同参数只读查询，
HTTP 200、业务码0、0.344秒，返回11月13至17日各一条，14、15日均标记休市。
随后经正常Product入口重试原失败准备记录一次。受理ID保持不变，
测试Worker按现有配置处理，15:38:02完成。11月18日失败回执继续保留。
Product就绪检查返回完整日历、3个交易日、9个就绪数据单元、0缺项。

同一三股池及原冻结版本，5日预测周期返回建议和30/9/21条训练、验证、预测样本。
建议分别为9月1日至10月27日、10月28日至11月6日、11月9日至17日。
20日预测周期返回样本不足。真实浏览器在显式点击“采用建议日期”前六个日期为空，
点击后和API返回一致。切换20日周期保留原值并撤下采用入口，
切到滚动训练验证显示手工填写提示。浏览器Product写入为0。

只读对账显示原150条日线的摘要哈希与11月18日一致，50个全市场日同步任务状态、
次数和时间戳一致。准备记录总数、研究任务、制品、训练及预测计数均一致。
该测试池的O10正反例通过，可以关闭默认单模型日期建议的具名验收。
真实训练、模型质量和正式发布按原边界另计。

私有目录新增 preparation-retry-20261122.json、
preparation-retry-terminal-20261122.json、options-after-retry-20261122.json、
browser-adopt-after-retry-20261122.json及截图、data-state-after-retry-20261122.json。
