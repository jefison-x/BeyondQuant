# Backtest 原请求键核对

维护切片，Product Phase 97 不变；依据 ADR-0062/0025。Community 源码检查按 ADR-0068 免除。

## 范围与行为

- 新增 Backend GET `/v1/research/backtests/reconcile`，验证可信 active owner/workspace 及原 ResearchTask 归属。
- 复用现有 task_id/idempotency_key 唯一映射，SQL 同时约束 owner/workspace，仅先取 job_id 再取现有摘要。
- confirmed 表示已找到原提交，独立于 queued/running/completed/failed/cancelled；未找到或核对时记录被删除为 outcome_unknown。
- 不扫描列表、不重放创建、不执行准备/审批/Worker，不加载原行情输入及结果对象引用。存储故障返回安全 503。
- MCP 扩展既有 byq_backtest_get，兼容 job_id 读取，新增原 task_id/key 互斥选择；异常/不匹配回执不确认为成功。
- 无数据库迁移、依赖新增或 Product UI 变更。本切片不含高层 backtest-task 提交、持久登记/watch、自动轮询或下游续接，F2 保持未完成。

## 定向验证

- 实现前 1 FAILED/7 PASS：原路径被动态 job_id 路由接收，422 invalid identifier。
- 最终新增 8 项回归与现有 Backtest API 合计 15 PASS，11.69 秒。
- 覆盖未提交→迟到提交、原 task/key 精确匹配、连接重建、新 Python 进程读取相同摘要、异主/错工作区/禁用/匿名身份及非法 selector。
- 新进程测试证明不依赖内存回执缓存，不冒称正在提交时强杀服务的崩溃演练。
- create/list/full-input/validation/Worker 替换为失败断言；并发删除注入仍 unknown，存储异常 503 不泄露内部信息。
- MCP 编译与 Backtest 合同通过：Unicode 编码、互斥身份、未知/已确认、传输/JSON/HTTP/错 key/task/job 及旧 ID 兼容。
- 隔离探针为内部网络、tmpfs PostgreSQL、只读源码挂载和合成用户，无生产/Community/付费模型调用。

## 完整验证

- 独立 `.21` 基线/候选清单最终 check 均 PASS；历史 `.20` 及以前清单不改写。
- CI scope `post-u8-backtest-receipts-20260909`：退出 0，26/26 检查通过。
- 架构 228；Backend 531 PASS/1 SKIP/7 subtests PASS，512.87 秒；Gateway 202 PASS。
- Runtime 基线 149 PASS/35 SKIP；候选 158 PASS/26 SKIP；真实候选进程 23 PASS。
- 完整 MCP 合同、Frontend 176、模拟浏览器 20 和真实 Product API 浏览器 9 项通过。
- 完整 smoke、重启持久化、双用户隔离及 Product coherence 全部通过。
- 既有框架弃用与浏览器警告按日志保留；明确跳过项不计通过。
- 探针及全 CI 资源分别独立清理核验 PASS；仅可重建合成数据，无生产备份或变更。
- 本地脱敏日志 `.ci-artifacts/backtest-receipts/LOCAL-CI.log`（忽略、不提交），SHA-256：
  `97f9c55993fc703e83afe37145c57ad2494b6be55fa0286c3e166dc08884cd9e`。
- 文档/diff 检查通过，本地提交范围；未 push、无 PR/远端 CI、未 merge 或部署。

本批关闭 Backtest job 创建回执缺少原 task/key 只读核对入口的问题。
下一项优先检查高层 backtest-task 创建（信号准备组件）的原键核对，再继续持久登记、
预算约束的持久等待及自动续接；F2 和全接口审计保持未完成。
