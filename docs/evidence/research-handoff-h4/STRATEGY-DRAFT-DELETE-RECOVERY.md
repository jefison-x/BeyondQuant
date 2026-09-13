# 策略草稿删除原回执恢复

真实数据库 HTTP 验收复现：首次删除返回200，重新打开 ResearchStore 后重试返回422“already superseded”。原删除转换已持久化，入口状态检查使原回执不可达。

候选删除重复的状态预检查，仍由既有 research.transition 在行锁内先查原键回执，再验证状态转换。原对象、原固定键和软删除语义不变；先核对owner再检查kind，其他owner仍404。
测试要求重启后JSON与首次相同，superseded转换计数仍为1；不通过创建新键或重置状态恢复。
本候选尚未更新构建身份或推送，不代表草稿保存/全部接口已验收。

完整策略API11项通过（9.82秒），包含重启后原回执相等、转换只有一条及跨owner拒绝。复核main.py仅此未登记handler改变，已有台账整文件哈希更新但完成数量保持114/560。

## MCP 原对象只读核对候选

Backend恢复之外，MCP此前未知删除仅给通用提示，没有携带原对象定位。现在仅在outcome_unknown且原ID为canonical Artifact时附byq_research_get(entity_type=artifact,entity_id=原ID)，要求读取原草稿状态，不从列表缺项推断删除。
新增断连、503、坏JSON、null、array五场景均只有一次删除请求；策略翻译、通用写结果矩阵（9写族/5未知模式/6拒绝/8读族）及实际MCP工厂测试通过，编译通过。
仅核对指引，不自动读取或重发，不据此宣布删除成功。该MCP增量尚未生成新构建身份或推送。

`.101` 推送头04cf2b4被GitHub确认但没有PR检查记录；已按既有CI授权触发现有workflow_dispatch/full。
运行34749941635精确head为04cf2b4901f3003610a21eddf1f4f94eaff6c9ce，最近状态queued；不将旧失败或新排队当作通过。

复核MCP差异仅删除结果包装，策略版本转发及共享requestStrategy未改；现有版本接口台账依赖哈希同步，不新增全部草稿接口完成结论。`.101` 完整远端CI 34749941635 已确认in_progress，尚未通过。
