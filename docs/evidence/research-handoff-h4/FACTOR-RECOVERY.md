# H4 因子提交恢复

2026-09-13，Accepted ADR-0062 的原键恢复维护；Product Phase 97 不变。

原实现先计算再进入 Artifact 幂等锁，同键成功重试及并发会重复计算。
现在复用 research-artifact 原锁，在同一事务核对归属、规范化输入与既有结果。
既有 factor_result 的 input_manifest 必须一致，并继续调用 Artifact 的原请求哈希校验，
保留 experiment、trace、lineage 等变化冲突。首次计算与 Artifact 保存共享事务；
同键锁等待上限2秒，等待超时按现有未知结果处理，不自动重放。没有外部计算副作用、
新队列、表或 Worker；进程中止且事务未提交时仍可重算，不能称为持久计算作业或 exactly-once。

MCP 对成功回执核对原 task_id、Artifact类型/ID及输入manifest一致性。
丢回执/畸形结果时返回原键 Artifact 只读核对指引，不自动再次 POST。
不回传原始输入或私有错误；401/403明确拒绝。复用已有 byq_research_get，无新工具。

修复前同键不重复计算断言失败。修复后 Backend 因子API、领域计算、输入归属26项通过；
包括3连接并发只计算一次、Store重建、重排等价输入、变更输入/trace冲突、插入后异常原子回滚。
MCP build、factor-research、write-outcome通过；4类丢失/错误成功回执均只发一次请求并保留原核对身份。
所有数据合成，临时 PostgreSQL 内部网络；未访问生产或真实模型。
仍需跨服务进程终止/丢响应组合及完整F7资格，不以本切片关闭整个H4。
