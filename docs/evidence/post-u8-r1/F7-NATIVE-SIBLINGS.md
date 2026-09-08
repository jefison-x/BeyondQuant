# F7 原生兄弟子 Agent 准入验证

2026-09-08，隔离 scope `post-u8-f7-native-20260908-11`，post-u8.11 构建。
candidate manifest：`sha256:e1a39b40630f925ba1963d319390271ce30aa02e1f4f40595d14c3c5920a0a36`。
Backend/Gateway/MCP/Runtime/PostgreSQL 五服务及独立本地 Provider；Docker 网络
`Internal=true` 已核对。没有前端、Data/ML/Signal Worker、付费模型或生产访问。

## 已通过场景

真实 Product 登录创建会话，官方 DSH 根先注册 `quant_orchestrator`、建立合成研究任务；
再依次调用两个官方策略或 ML delegate。每个 child 独立注册同角色、同 parent 的 AgentRun。
第一个 child 提交无效 schema 并结束输出；第二个换 AgentRun/幂等键提交同一失败输入。

- `byq_strategy_validate`：`ci-f7-native-strategy`，会话
  `conversation_67e5f09e7c904a70ad73943813b85a03`。
- `byq_ml_strategy_create`：`ci-f7-native-ml`，会话
  `conversation_c9905f2878aa40c6ab6ea2b58e91d825`。
- 每场景恰好 9 次本地请求：根 4、第一 child 3、第二 child 2。第二 child 的重复失败输入
  导致真实根进程 `domain-correction-stopped`，没有第 10 次请求或根 `session.result`。
- 每 owner 两份私有证据，来自两个不同 AgentRun、同一根、同一 input hash；仅一份
  `correctable_failure` claim，`repair_used=false`，没有重复执行或消耗新的修正额度。
- 每场景三个根绑定授权 AgentRun 最终 failed、无 active 残留；研究任务仍 planned，制品为零。
  公开活动按最终 identity 聚合为两个 completed、两个 failed，没有 started 残留。
- 重启且等待测试 Backend/Gateway 健康后，只查询原两会话：上述数据库状态、失败记录和
  公开活动仍一致；Provider 累计仍为 18，未调用新模型或重新执行领域动作。

这是原生连续兄弟子 Agent 场景，不冒称并行子 Agent、全部撤销/迟到 HTTP 矩阵或
自然语言模型遵循证据。脚本 Provider 只发固定合成输出，不能代替付费模型语义验收。

## 保留的失败及澄清

首次策略场景脚本退出 1：断言错误地要求第一个 child 的 BYQ AgentRun 为 completed。
现有 `agent-run-lifecycle.v1` 仅以根终态收尾根绑定授权记录；child 输出结束不是研究或
领域成功证明，该 child 实际只报告了校验失败。公开 activity 已正确保留其 completed，
三个授权记录则随失败根关闭。修正的是测试语义，不是删除业务失败或改动生命周期实现。
策略场景没有重新运行：先只读复核原持久结果，再执行 ML 场景。随后重启只读验证通过。

脚本：[Provider](f7-native-provider.py)、[真实 Product 驱动](f7-native-probe.py)。
后者 `F7_RESUME_AFTER_STRATEGY=1` 仅用于首次断言修正后的原记录复核，
`F7_VERIFY_RESTART=1` 不创建用户/回合。新测试库正常运行不需前者。

本轮 Compose 报告 Runtime image identity：
`sha256:7409d46d7978be3f78e8c11ea521af0925503a8961e747666207a630563d84fb`；
Backend：`sha256:6438274c0ba003501bb972ebe040c5b916b6493a5d77279a26426554842bd3c0`。
不与 `.10` 镜像混用或覆盖旧清单。尚未新一轮全 CI、推送、合并或部署。

## 工具发出前禁用身份

同一 `.11` 测试栈接入独立本地受限 Provider；旧 Provider 先断开网络，未改变应用实现。
根先完成 AgentRun 注册、任务创建，第三次模型请求暂停在返回合法策略工具参数之前。
驱动确认根/AgentRun 均 active、claim/artifact 均零后，经测试 Backend 管理接口禁用
本次刚创建的合成用户，确认 disabled 才释放响应。两工具分别验证：

- `ci-f7-revoke-strategy`，会话 `conversation_9b3a9f96094340d0a97cc7f15cee7029`；
- `ci-f7-revoke-ml`，会话 `conversation_c9fd1cefd0c64076a402aa09de0881ff`。

各 4 次本地请求后根和 AgentRun 为 completed，任务仍 planned，claim/artifact 均零；
根模型最后仅声明身份已撤销、未完成研究。此 completed 仅为模型回合结束，不是任务完成。
新 Product 回合被 401/403 拒绝，没有第 5 次请求。两场景累计 8 次本地请求，未运行训练。
这是“身份禁用先提交、工具后发出”的真实 HTTP/DSH/MCP 顺序，不冒称覆盖已执行事务
中途撤销或跨服务瞬时取消。

脚本：[Provider](f7-revoke-provider.py)、[驱动](f7-revoke-probe.py)。Provider 将
`f7-native-provider.py` 只读挂载为 `/probe/helpers.py` 复用合成流/字段解析；
`PYTHONPATH=/app:/probe`，其余依赖来自 `.11` Backend 镜像。没有修改 SDK 或 Provider 代理。

最终按精确作用域清理 7 个测试容器、4 个临时卷、1 个网络和 4 个镜像标签；
清理及独立 verify-only 均通过。合成数据未备份，可由脚本重建；生产、Community、
历史报告和私有备份未修改。测试脚本保留，应用历史构建清单不删除。
