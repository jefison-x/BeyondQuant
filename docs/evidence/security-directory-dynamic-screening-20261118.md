# 证券目录时点与动态选股真实验收（2026-11-18）

任务起点f473a34d，复用research-experience隔离工作树。用户继续授权测试环境体验维护；
生产不动。本轮没有修改功能源码、镜像、Compose或权限，不推进Phase 18。
复用既有数据准备、可信Data Worker、动态池Job和Product API，不新增Worker或harness。

## 已证实的原因

测试目录最新snapshot为securitysnapshot_11881223becf8c5508278a4d5b4146a2：
Tushare/stock_basic，5922条规范证券，L5579/P0/D343，另1条隔离记录，
retrieved_at=2026-11-14T20:53:07.306082Z，即上海11月15日。
但本轮开始时最新已验证开市日、行情和估值均只到11月13日。

stock_pool_producer._evaluate_dynamic_inputs先取requested_as_of前已验证开市日effective，
再选上海retrieved_at日期<=effective的证券目录。因此11月13日只能使用
securitysnapshot_03a35b1052cf5dccef5fe5e9aa92c234（10月14日取得、2行）。
这不是分页丢数据，也不能靠把最新目录倒填为历史数据修复。
保持防前视逻辑，复用11月15日真实目录，未重新请求stock_basic或改快照日期。

## 仅补两个已结束交易日

当时上海11月18日09:16，明确不准备当天未完成行情。
通过测试管理员Product API提交datarepair_81f27730c35a4245af8a8173def21ba9，
范围600036.SH/601398.SH/000001.SZ、20261116–20261117、research、无附加财务要求。
3银行scope用于限定研究就绪要求；既有Worker按交易日抓取全市场，不表示仅逐股请求。
准备completed，Product readiness从unavailable变usable：
2开市日、6 ready、missing0、calendar_complete=true。

| 交易日 | 实存原始日线 | 实存daily_basic | 完整性核对 |
|---|---:|---:|---|
| 20261116 | 5572 | 5572 | 日历开市；session/basic凭证row_count与实存相同 |
| 20261117 | 5573 | 5573 | 日历开市；session/basic凭证row_count与实存相同 |

日线data_source均为Tushare；daily_basic凭证provider=tushare、endpoint=daily_basic，
原始来源、请求指纹、完整性hash和实际数量保存在coverage-and-independent-screen.json。
自动全市场调度enabled=false保持不变，仅执行此显式准备。
没有模型、策略、信号生成、回测或额外证券目录同步。

## 真实覆盖与独立筛选

11月18日请求的有效交易日为11月17日，使用11月15日目录。
该日期有效成员5579只，与当日basic交集5572只；筛选所需四个数值字段同时非空且有限的3334只。
缺值计数可重叠：pe_ttm 1728、pb 66、dv_ttm 1846、total_mv 7。
不能把这些值补成0，也不能凭3股就绪或提供方全市场日快照宣称所有证券的所有字段齐备。

真实浏览器表单无需编辑代码/JSON，使用四条件：
行业精确“银行”、PE_TTM<=20、PB<=2、近12个月股息率>=3%，总市值降序前5、
等权、手动刷新、创建后激活。未填写净利润同比，不声称验证全市场财务筛选。

独立读取42家银行真实字段，按浏览器实际四条件计算36家合格，市值前5为：
工商银行601398.SH、农业银行601288.SH、中国银行601988.SH、
招商银行600036.SH、交通银行601328.SH。与真实浏览器预览同序、每只权重0.2。
预先API定位样本多一个PE>0条件；确认42家银行PE均正值后，
仍单独按实际浏览器四条件重新计算，不把不同请求当逐字同题。
预览返回authoritative=false，预览不是冻结成分名单。

## 唯一创建、物化与回读

真实页面点击“创建并生成快照”一次，HTTP成功回执先保存；
创建后由已有Data Worker独立物化，没有另建执行器或直接写数据库：

- 名称：体验验收_银行估值分红筛选_20261118。
- pool：stock_pool_643d90799f8e483b85255c11a730d2fb。
- run：stock_pool_run_cc6e1476f468452fbdf0178cbad3e7bf，succeeded、attempt=1。
- snapshot：stock_pool_snapshot_543781630fe0bd6f35eaf2f660de92b424acdcb4f20b7e7d4b828879fe7710e4，v1、5成员。
- rule fingerprint：92827932ed3267d55f0acfab2c701906345b68ec426f051677f6b029549e6177。
- run input hash：a123f17f33c906054c1b2a8de545a005bb8d49190a508ca57be1b0b9fada6318。

物化输入manifest去掉额外固定rule_fingerprint后与浏览器预览manifest逐字段相等；
rule、定义指纹、run hash、snapshot provenance精确绑定。成员按证券代码规范排序，
与市值排序预览集合相同；5只各20%，合计100%。cadence=manual，不自动重复刷新此池。
Product成员页返回真实中文名，刷新后同snapshot/成员/权重仍在。
C账号读取此私人池404；平台目录可读不等于私人池跨账号可读。

同一浏览器实际四条件显式请求20261113，仍使用旧2行snapshot，结果0成员。
没有把11月15日目录放进11月13日，也没有改历史成员名单。
历史日期缺目录这个限制仍保留，不将“当前场景通过”扩大为历史目录已补齐。

browser-result.json记录成功创建一次、0 Product错误；保存/回读批只有1个Product写请求。
此前失败保留：/state路径404；ranking误传数组422；行业input被当成父节点；
可选requested_as_of未发送，却被采集断言当成必填。均发生在建池前，未发模型或创建池。
每次停止受影响批并核对实际接口/DOM；复用成功预览回执后只续保存与回读，
没有因采集失败再准备数据或重复建池。请求日期省略时Backend实际归一为20261118，
这属于预期默认行为，不计成产品日期失败。
screening-rule-browser.png与persisted-members-browser.png已人工查看；
表单截图不作为预览数量可见性的截图证明，实际预览数量依据同页面HTTP200回包。

## 限定验收与剩余范围

独立Reviewer：Functional PASS、Tests/Product PASS、Clean Break Architecture PASS，
限本次四条件、手动池、20261117有效日；Root同范围PASS。
O09的此具名筛选→创建→物化→刷新回读场景可关闭，不代表任意筛选/历史/自动刷新均验收。

生产17项与测试14项容器的ID/image/StartedAt/health/mounts前后精确相等；
没有镜像变更、重启、清理、密钥迁移。数据中心最新证券snapshot及retrieved_at均原样保留。
测试池、原有历史、身份、卷和用户原浏览器页面保留。

仍未完成：11月13日及更早的真实完整证券目录；全市场全部财务字段；
其他筛选组合/自动刷新；模型训练日期推荐、拼音、扫描PDF/OCR及原观察池研究整链的未验分支。
没有运行模型质量复测或性能A/B，不将本次运维数据补齐当成研究推理性能优化。
无功能码改动，因此不机械重跑组件套件；远端CI、Release Images、推送/PR/合并和生产发布NOT_RUN。

私有证据根目录：
/home/jefison/.local/state/byq-maintenance/research-candidate-20261109/security-directory-20261118/。
关键回执：directory-audit-before、preparation-submission/terminal、readiness-before/after、
coverage-and-independent-screen、browser-preview、browser-rule-independent-check、
pool-submission、pool-materializations-terminal、pool-detail、persistence-lineage-check、
browser-rule-history-check、browser-result及environment-preservation.json。
