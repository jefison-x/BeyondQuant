# H4 内容去重 Artifact 的原键回执

2026-09-13，Accepted ADR-0062 的持久原身份恢复；不推进 Product Phase。

相同版本内容原先返回已有 Artifact，但新的 idempotency_key 未持久关联，按该键读取为 unknown。
同时内容去重可能绕过同键变更请求冲突。修复前真实 API 测试已复现。

新增 artifact_submission_receipts，仅保存 task、key、规范请求哈希、Artifact外键。
入口封闭为 strategy_version、ml_strategy_version、signal_snapshot；ML沿用原纠错事务连接。
不含队列/执行器/模型权限。复用 Artifact 原键锁及独立内容锁，2秒等待上限。
首次版本仍保存原 Artifact；相同内容的新键原子记录回执，精确重试读原回执；变化输入拒绝。
原键 GET 在 Artifact 未匹配时查询该回执，继续 owner/workspace/task 隔离。
普通 Artifact/Factor 不能占用已经登记的策略键。不同 experiment 不静默复用另一个实验的版本。

前向DDL使用现有 schema bootstrap。历史Artifact保留；没有记录过的历史第二提交键无法回填，仍未知。
新增表依赖原任务与Artifact外键，不改变旧Artifact ID、内容或领域状态。
本轮没有生产迁移；发布前仍须新schema检查，不能以代码存在声称部署。

策略API/ResearchStore/持久watch/Factor共33项通过；补并发后策略API6项再次通过。
覆盖原键回读、Store重开、输入变化、外用户拒绝、普通Artifact占键拒绝、并发同键/异键复用。
其他 typed producers 尚需逐项审计，不将策略去重修复等同于完整F2。

扩展三入口后策略/ML/回测API、持久纠错及因子42项通过。ML版本和信号快照的新键复用均增加真实API精确回读断言。
普通Artifact/Factor键碰撞10项定向通过，原始业务权限及受限纠错保持。
