# 研究、观察池与比较接续验收（2026-11-18，阶段一具名验收完成）

起点ebf32096，复用现有隔离工作树、测试账号与数据。生产不动。
目标顺序：个股研究 → 仅一个新custom观察池 → 从该冻结池入口继续比较。
原计划3个产品回合；发现具名质量缺陷后，仅增加一次同题纠正，改为最多4个受理回合，
最多1个新池；不发联网研究/补数/训练/策略/信号/回测或真实交易。

## 首轮：数值与日期通过，整答质量FAIL

真实浏览器新建conversation_949dae655fa84d89b6218fd39532daa4，
root d364e76ce1e74d58ab8182b8e7d9485b，30.247452秒，9模型请求均200，
3次市场查询、工具错误0，completed/closed、unknown=0。
真实CMB收盘43.45、前收43.40、PE_TTM7.1675、PB0.9271、
dv_ttm4.6398与dv_ratio4.603，日期20261117，均与实际回执一致。

但答复把单股字段完整与5573个数据集行数泛化成全市场估值齐备；
另将dv_ttm解释为已实施分红折算，工具未给计算与实施依据。
独立Reviewer判整答质量FAIL，不以数值或30秒抵销。原答案/回执保留。

## 99aa4907估值证据范围修复

只为现有估值只读返回增加evidence_scope/股息field_semantics，
明确范围外未查、数据集行数不是全市场非空字段数；
股息具体计算依据、分红期次和实施状态未核实，非支付率。
保留coverage.complete原先“该日数据集快照存在”的含义，新增complete_scope；
usable_scope明确只检查请求证券与字段。数值、NULL、权限、PIT与Provider路径不变。

新纯逻辑回归修前3FAIL→修后3PASS，schema reset0；
MCP既有适配器定向编译/透传测试PASS（无MCP源码改动），
现有市场研究架构测试1PASS、dev-check PASS，独立部署准入PASS。
宿主MCP依赖缺失、现有TS7参数及pytest只读临时目录等采集失败均保留，
停批核对后用既有镜像/原配置和直接unittest简化执行，未因此发产品模型。

仅测试Backend更新为sha256:630b76c6e0bd210ffdfa86c00798a27ff8f9b73bfe615ede88c7df586081425b，
只COPY market_readiness.py，文件hash e7a91c567ede83ea147888bf4be65f684962000f79844c8dcfddf855443370a0。
不是正式清洁Release Images。两个10月21日撤权未确认旧根逐字段原样保留，
未恢复/结算/重放，不因其旧status=active而假称它们已结束。

## 同题纠正：目标两处已纠正，保留文字问题

同一会话、完全相同问题，root96775e3f65484d3f91fec85acd6bd239，
24.188961秒、6模型200、3市场查询无错、completed/closed、unknown=0；
新元数据真实进入tool结果，原生答案经既有术语投影与持久化答案一致。
不再把5573行当全市场字段齐备，股息公式/实施状态明确未核实。

另保留两处：返回日线区间与实际请求到11月18日的范围混写；
末段“股价略低于43.40元的前收水平之上小幅收涨”语病，
虽然表格43.45>43.40、+.05/.12%正确。这不算无条件整答质量PASS，
计划在保存前明确要求纠正，最终比较仍须独立核对。

## 保存阶段：409，暂停写入验收并定位

同会话下一条明确要求先纠正文字、随后只创建一个两股custom观察池的请求，
返回HTTP409 “runtime session is not available for this operation”，无run_id。
未按无run_id直接推断没有副作用，正依据会话根/Admission/Tool/原创建名只读对账；
不重发、不另建会话或替代池，也不触碰历史unknown。
GET会话为status=unknown，containment=completed/submission=not_performed；
历史仍在，末尾出现root967…的session.reattached事件。
具体私有拒绝原因与代码落点尚待核对，不猜测根因。

当时O13尚未通过；观察池创建、冻结版本传递及后续比较NOT_RUN/待处理，
模型日期推荐等下一项尚未实施，只有独立只读预查。

私有证据：
/home/jefison/.local/state/byq-maintenance/research-candidate-20261109/observation-journey-20261118/，
含stock-research、stock-research-corrected、save-pool以及限定构建/测试/部署回执。
原失败日志、会话、身份、数据卷和用户原浏览器页面保留。

## 409只读对账与源码调查（继续）

带服务器时间戳的日志确认：02:41:12.829与13.142两次binding GET；
13.170与13.402恢复POST200，13.447另一个恢复POST409，
公开turns于13.448返回409，没有到Adapter prompt入口。
只读DB精确核对同session仅原两条completed/closed unknown0的根，
admin/workspace原4个池（包括软删除记录）仍在，目标新命名池不存在。
因此可以证明这次保存未进入新的Agent执行、没有产生池；失败请求保留待安全重试。

Gateway本地registry仅保护dict，cache miss后昂贵恢复没有single-flight，
恢复结束后才add并处理collision。并发请求可带同一旧binding/tail进入恢复。
具体现场私有异常不可追溯：Runtime将SessionConflict折叠成通用409，
Gateway再次折叠，服务器日志不含请求游标/原Python异常。
“旧游标在boundary ACK后不再匹配”是时间线与源码相符的推断，
不是已取得的现场私有拒绝原因。当前正在现有测试夹具中做离线并发回归；
不重发真实recover来探测，不放宽Runtime的精确游标或settlement校验。

## 阶段一最终结果（额度恢复后补记）

a65d45a4只为普通_product_session入口增加按owner/workspace/conversation的临时恢复门，
等待后重查registry、boot和workspace，异常/最后等待者退出即清理。
不改显式observer/force恢复、Runtime游标/结算fence、DSH或权限。
并发回归修前1FAIL（重复进入restore），修后整个恢复文件19PASS，
dev-check及独立Functional/Tests/Architecture准入通过。
只更新测试Gateway为sha256:ca8e1e05f89a3f666beeff52c958b1ac43a7ec688531c867c2a00844224c8634；
模块hash ec597275d11875fa40f001a23a72bd2fa09314bda275dde35a7057f9d2df103a。

经DB证明409保存未入场后，在原CID仅重试同一保存问题一次：
root d233f5c556654e25a2c469337f8e9f1f，27.228540秒、7模型200，
completed/closed unknown0。明确纠正43.45高于43.40、上涨0.05，
并区分请求到11月18日与实际返回到17日。
实际pool_create恰1次、pool_get1次；一次authorize 403拒绝原文保留，
不把此回合说成工具0错，后续受控保存与读回成功。

唯一新custom池stock_pool_f08180ec7fde4cd6ae6cbe7d17cf4d68，
名称体验验收_研究接续观察池_20261118，snapshot
stock_pool_snapshot_37ea30ae6d661255bbe6740b39a5409b8c6f46eea49cdf68c9b2ad3a5fde396d，
v1，招商/工商两成员weight均null、未设权重；effective_trade_date=null，
描述11月17日仅为研究基准日，未伪造历史入池或保存估值到成员字段。
真实创建回执和Product读回精确一致，没有替代池或额外任务/策略/回测。

真实页面成员中文名、未设置权重及刷新通过；池入口打开new空timeline，
草稿带精确池和snapshot，不自动发送。显式发送后新CID
conversation_76217ed1ba9343b3821d0e2dfd924427，root b989b62e2dc54e8e93c8c3f7824bf1db，
28.227678秒、10模型200、工具错0、completed/closed unknown0，
pool_get1、当日日线2、估值1、业务写0。
CMB/ICBC同日收盘43.45/9.06、PE7.1675/8.4025、PB.9271/.8061、
TTM股息率4.6398/3.532；PE相对差14.698%、PB差15.0105%、股息差1.1078个百分点，
独立重算一致。最终回答明确5573仅存储行数，股息公式/期次/实施未核实，
不推导财务因果、行业排名或无权重组合收益。
末句“准备数据补更多成员”略含糊（准备数据不等于添加池成员），列非阻断文案项；
保存答复技术标识较多也不算全站普通用户文案已验完。

独立Reviewer的Functional/Product/Architecture限定PASS；
Root最终库存确认生产17项精确不变，测试14中仅Backend/Gateway改变、
其余12与全部挂载保留；13healthy、原Data Worker无healthcheck但running。
两条10月21日unknown前后逐字段相等。Root同范围PASS，O13此具名流程可关闭。
首轮FAIL、中间文字错误、未受理409、授权拒绝全部保留，不普遍保证后续生成。
本轮4个受理回合共32个模型请求；409未增加模型/根/池。没有新补数/训练/策略/回测/交易。

后续按序进入模型日期推荐；正式CI、Release Images、推送/合并/生产发布仍NOT_RUN。
