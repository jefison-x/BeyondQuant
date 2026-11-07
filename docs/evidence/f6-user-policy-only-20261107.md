# F6 内建能力与用户级自动接续 — 2026-11-07

## 授权与范围

维护者明确要求移除 `BYQ_F6_EXECUTOR_ENABLED`，让 F6 成为默认能力，仅保留
用户级自动接续启停设置；保留未结算执行保护、数据、原会话、页面及历史回执，
不推进 Phase 18。决策记录于 [ADR-0111 修订](../architecture/adr/ADR-0111-automatic-continuation-execution-parameters.md)。
本轮为隔离工作树中的维护实现，基于 fetched `origin/main`；push/PR、合并、
发布和运行栈部署尚未执行。

## 变更

- Backend、Gateway、Runtime 不再读取该变量；Compose、环境模板和当前 CI
  夹具不再设置或要求该变量。遗留值 `0` 不再禁用新实现的 F6。
- Gateway 注册会话消费者默认启动，统一复用现有准入链路；取消 fence、
  原回执核对和持久未知责任先于消费。保留仅核对 v3 回执的辅助路径。
- 用户 `auto_continue=false` 继续阻止新的自动接续预留；已有预留保持其快照，
  不通过本修改撤销、重放或重写旧请求。原任务/owner/workspace、route/profile
  资格、显式数值限制、去重、终态 ACK 与清理检查不变。
- 独立审查确认当前 Backend `/peek` 只投影 v3 自动意图，不会因消费者启动而
  把历史 v1/v2 许可变成新的自动 claim 路径。

## 本地验证

复用已验证镜像中的测试依赖，仅读挂载当前源码；Gateway/Runtime 单测无外网，
Backend 使用独立 internal 网络和临时 `byq_domain_test` PostgreSQL，未接应用卷或网络。

| 验证 | 结果与边界 |
| --- | --- |
| Gateway 接续消费者 | PASS，106 项；覆盖默认启动、遗留 0、取消 fence、回执及未知结果 |
| Backend 接续/通知/回传 | PASS，67 个不同用例；原批 50 PASS，17 个失败用例修正前提后补验收 PASS |
| Runtime 资格/槽位/恢复 | PASS，95 个不同用例；首次 94 PASS，新增 profile 断言修正后资格文件 24 PASS，未重复其他有效项 |
| 显式隔离 DSH 请求语义批 | NOT_RUN，6 项因既有 `BYQ_BUDGET_SEMANTICS_TEST` 门禁跳过；不声称本轮真实 DSH/F6 验收 |
| CI、发行夹具、凭据制品定向合同 | 首批 64 PASS、19 subtests；补修专用入口后相关文件 13 PASS、17 subtests |
| Compose 合同 | PASS，4 项、9 subtests；无变量及遗留 0/1 均不向三角色暴露独立开关 |
| 语法、shell、文档链接与 diff | PASS，使用现有 dev-check、check-docs 和 diff 检查 |
| 独立 Sol 审查 | 最终 Functional / Tests / Clean Break Architecture PASS |
| 新提交 hosted CI、镜像构建、部署与真实 Product/浏览器链 | NOT_RUN，保留为后续交付门禁 |

首次失败证据保留：新增 Runtime 测试曾错误扩大官方路线的旧 profile 资格，已修正
断言并保持原资格不变；临时 PostgreSQL 的 256 MiB 限制触发 OOM，另两项旧开关
状态断言需更新。停止受影响批、保存日志，仅调整该临时库到 1 GiB 并补跑失败项，
`oom_kill` 未再增加。独立审查发现 CI 专用入口仍要求旧变量，已删除该单独检查，
新增无变量/0/1 可到达夹具加载、其他错误 scope/profile 仍拒绝的回归。

私有原始日志位于 `~/.local/state/byq-maintenance/f6-user-policy-only-20261107`，
包括初始失败、补验收、测试库资源诊断及保留性记录；不把本地替身证据冒充产品验收。

## 保留与运行状态

临时单测容器和 internal 网络已按确切标签、ID 清理，没有创建持久数据卷。
与前次收尾的加密快照核对，原有 27 个运行应用容器及镜像 ID 全部保持不变。
本轮未对应用数据库、用户设置、原会话、历史回执或浏览器页面执行写操作，模型调用为 0。
运行栈继续使用此前已部署镜像和历史启用参数；本地源码完成不代表运行环境已移除开关。
