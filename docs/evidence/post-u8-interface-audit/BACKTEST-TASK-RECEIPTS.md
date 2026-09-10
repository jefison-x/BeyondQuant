# 高层 Backtest Task 创建回执

维护切片，Product Phase 97 不变，依据 ADR-0044/0062/0025；Community 原实现检查按 ADR-0068 免除。

## 范围

新增 `/v1/research/backtest-tasks/reconcile`，验证原 ResearchTask 归属及可信 active owner/workspace，
精确读取 signal_producer_jobs 原 owner/workspace/task/key，仅查询 job_id/status 两列。
确认后返回闭合回执（派生 backtest_task_id、signal_producer_job_id、signal_status），再通过原 ID 读取完整状态。
没有匹配为 outcome_unknown，不代表不存在/失败或授权重提；存储故障返回安全 503。

信号组件沿用原 owner/workspace 幂等命名空间，task_id 是附加防护，不新建 task-scoped 命名空间。
高层 facade 和直接 signal-producer/jobs 都可创建该组件；回执不推断创建入口，
也不证明 job 后的 pool-reference 写入完成。派生 ID 沿用现有映射，不建第二套任务表。

MCP 扩展现有 byq_backtest_task_get，互斥选择最终 ID 或原 task/key；普通和 ML-derived ID 读取保持兼容。
原键路径仅信号任务，不把 ML prediction key 误认为 signal key。核对不加载完整输入、
重新准备/补数、检查当前审批、计算完整 facade、创建/认领任务或执行策略。

仍待整改：创建前 readiness/repair、副作用与幂等认领顺序、并发创建、pool-reference 原子性、
持久登记/watch、预算和自动续接；本批不关闭完整 F2。无 Product UI、依赖或数据库 schema 变更。

## 定向验证

- 初始原接口缺失：1 FAILED/7 PASS，原键路径落入动态 ID 路由并返回 422。
- 实现首轮发现缺失 ID 映射导入，修正后定向通过；未冻结失败源码为合格构建。
- 最终新增 9 项回归，连同 facade 和 SignalProducer 测试合计 16 PASS，10.83 秒。
- 真实高层/直接组件创建两条路径、未提交→迟到提交、原 task/key、Store 重建和新 Python 进程读相同持久 job。
- 原任务/用户/工作区、禁用/匿名隔离、非法 selector、存储故障验证通过。新进程读取不等同于提交中强杀演练。
- 将 create/get/list/claim、prepare/repair、approval/full facade 替换为失败断言，证明核对只读路径无这些副作用。
- MCP 编译及合同通过：Unicode key、未知/确认、互斥身份、传输/JSON/HTTP/错误映射、字段投影和普通/ML ID 兼容。
- 探针只用内部网络、tmpfs PostgreSQL、只读源码挂载和合成数据；无生产/Community/付费模型访问。

## 完整验证

首轮独立 `.22`：CI 25 PASS/1 FAIL，Backend 540 PASS/1 SKIP/7 subtests PASS，
MCP、9 项真实浏览器及重启/双用户检查通过。候选真实进程 22 PASS/1 FAIL：
`test_go_routing_headers_on_official_protocol_and_permanent_rejection[opencode-go-responses-gpt-5.6-luna]`
读取 `failures[-1]` 时列表为空。实际请求、路由头、永久拒绝不重试断言都已通过，
故不是“没有发出请求”。此前临时进度描述已纠正。

Runtime 的 `_run_prompt` 持 record.lock 清空 active_run、设置 FAILED 并同步 `_emit`；
测试原先在锁外轮询 active_run，可观察状态与 history 之间的中间状态。
修正测试用同一锁确认终态，保留 20 秒截止及全部原断言，并补明确的事件非空断言；
不改 Runtime 生产逻辑、不扩大超时或忽略失败。`.22` 为失败资格记录，不标记认证通过。

首轮已退出 1，作用域资源独立清理 PASS；原日志保留于
`.ci-artifacts/backtest-task-receipts/LOCAL-CI.log`，SHA-256：
`26f502bd2eaad8962c41546a42f29f6fff5ab9d2fc3ea3f36a42d82dbbfbbed6`。
历史 `.22` 及以前清单不改写；测试同步修正使用新的 `.23`。

## 最终独立验证

- `.23` 基线/候选清单最终 check PASS；完整 CI scope `post-u8-backtest-task-receipts-23-20260909` 退出 0，26/26 通过。
- 架构 228；Backend 540 PASS/1 SKIP/7 subtests PASS（518.73 秒）；Gateway 202 PASS。
- Runtime 基线 149 PASS/35 SKIP；候选 158 PASS/26 SKIP；真实候选进程 23 PASS，包括原失败路由拒绝场景。
- 新旧生命周期、完整 MCP 合同、Frontend 176、模拟浏览器 20、真实 Product API 浏览器 9 项通过。
- 全栈 smoke、重启持久化、双用户隔离和 Product coherence 通过。
- 既有弃用/浏览器警告保留，跳过不计通过；首轮 `.22` 的失败与未执行生命周期 benchmark 不冒充通过。
- 探针、首轮与最终 CI 资源分别独立清理核验 PASS；无生产/Community/付费模型访问。
- 最终本地脱敏日志 `.ci-artifacts/backtest-task-receipts/LOCAL-CI-23.log`（忽略、不提交），SHA-256：
  `030307afb699637e89a9bbd6f612ebd87a9a8895668cad3f8848f34110e9d117`。
- 本地验证与提交；未 push、无 PR/远端 CI、未 merge 或部署。

本批关闭高层信号派生回测任务的原键读取缺口，并修正验收中发现的测试同步竞态。
下一项优先处理创建前准备/补数与幂等认领顺序，以及 pool-reference 与 job 持久化原子性；
持久等待、预算和自动续接仍待后续具名整改，F2 不关闭。
