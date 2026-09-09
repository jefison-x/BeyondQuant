# 信号任务提交认领与引用原子性

维护切片，Product Phase 97 不变，依据 ADR-0062/0025；Community 原实现检查继续按 ADR-0068 免除。
本次自动审批拒绝主仓库 fetch + fast-forward 命令，认为缺少主线更新授权；命令未执行。
继续使用已存在且已验证的隔离工作树及其基线，不声称本轮重新同步主线。

## 行为

两条创建入口（signal-producer/jobs、backtest-tasks）进入同一领域提交认领方法。
新增可空 submission_hash，基于原命令、owner/workspace 和创建用途，排除 trace/readiness/repair。
原键事务 advisory lock 串行认领；相同命令直接读原记录，变化命令/用途及无命令摘要旧记录返回 409。
保持共享 owner/workspace 命名空间，用途作为冲突判据，不能用直接信号创建绕过 facade 创建审批。
摘要不公开，原 trace、冻结 requirement/preparation 及历史记录保持。旧记录仍可按原键只读核对。

首次认领在事务内验证/冻结有界领域输入、原证券目录成员及必要审批；昂贵行情 assess 和补数不在 HTTP 路径运行。
waiting_for_data job、股票池引用和命令摘要在同一事务提交；引用失败连同 job 回滚。
新提交初始 readiness 为 unknown，已有 Worker 在提交后评估并请求缺失数据，完整输入才 promote。
Worker 扫描只接受 active personal owner/workspace/membership；补数 retry_terminal=False，不因轮询重启终态请求。
不引入新队列或 harness，不进行历史数据迁移、旧引用回填、生产或付费模型调用。

## 定向证据

- 实现前 5 FAILED：HTTP 先 assess、引用失败遗留 job、并发重复准备。
- 最终新增 9 项回归与前序 facade/SignalProducer 测试共 25 PASS，17.14 秒。
- 两条创建入口、Store 重建/更换投递 trace 的同键复用、命令变化早冲突；引用写入之后注入异常，两表同时回滚且无补数。
- 三个独立 Store/数据库连接并发，仅执行一次准备、保存一个 job 和引用。
- Worker 在 job 提交后首次创建 repair，重复扫描保持同一 repair，failed 终态不重启；禁用用户无 assess/repair。
- 旧记录缺失 submission_hash 写重试冲突但原键 GET 仍 confirmed；创建用途变化在准备前冲突。
- 探针使用内部网络、tmpfs PostgreSQL 和只读源码挂载，仅合成用户与数据。

## 完整验证

- 独立 `.24` 基线/候选清单最终 check 均 PASS；历史 `.23` 及以前清单不改写。
- 完整 CI scope `post-u8-signal-submission-20260910`：退出 0，26/26 检查通过。
- 架构 228；Backend 549 PASS/1 SKIP/7 subtests PASS，521.96 秒；Gateway 202 PASS。
- Runtime 基线 149 PASS/35 SKIP；候选 158 PASS/26 SKIP；真实候选进程 23 PASS。
- 新旧生命周期、完整 MCP 合同、Frontend 176、模拟浏览器 20、真实 Product API 浏览器 9 项通过。
- 全栈 smoke、重启持久化、双用户隔离及 Product coherence 通过。
- 既有弃用及浏览器警告按日志保留，明确跳过不计通过。
- 探针和全 CI 资源分别独立核验清理 PASS；源码/契约/文档检查通过。
- 本地脱敏日志 `.ci-artifacts/signal-submission/LOCAL-CI.log`（忽略、不提交），SHA-256：
  `4d0bdbe22fffac92ed8232b457b49b875630cc2b224015abf2d0f67d2bcc1ec6`。
- 本地提交与验证；无 push/PR/远端 CI/merge/部署。主工作区未因被拒的同步命令而修改。

剩余边界：现有等待轮询的持久预算/退避、完成通知及下游自动续接仍待具名整改；
已有旧引用不自动回填，已失败修复不自动重新授权。F2 与全接口审计不关闭。
