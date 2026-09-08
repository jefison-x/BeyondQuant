# F7 持久安全诊断与实际修正链路（2026-09-08）

状态：本切片及最终 `.15` 整栈验证通过，F7 具名范围已完成，见[最终矩阵](F7-ACCEPTANCE-MATRIX.md)。
维护者最新指令：完全整改 F7 后再推送合并。此前本地提交保留，本批仍未推送。

## 确认缺陷与修复

普通/ML 领域校验错误在 Agent 准入事务中被转成通用 DomainValidationRejected，
导致已有或可安全分类的字段诊断丢失。两个真实 Backend API 失败测试分别以
`KeyError: validation` 复现；不是以生产事故未知的原始 422 原因为依据。

现在仅接受 BYQ 的 MLValidationError / StrategyValidationError 类型，并重新经白名单
投影后保存字段、类别和固定指引。禁止任意诊断 dict、原异常文本、输入值或策略源码入库。
普通策略静态失败用 strategy.script + static_validation_failed，不输出导入名。
回执与预算一起持久保存；历史无提示回执保持不变，重放不重新校验或补写旧回执。
MCP 将诊断与 native-stop 标记分开，第二次修正失败仍 stop=true，提示明确停止。
人类原有操作路径、权限检查、严格 MCP schema、一次修正预算及 unknown 不退款保持不变。

## 定向验证与保留失败

- ML 失败优先测试 1 FAIL / 20 deselected；修复后相关 33 PASS / 24.92 秒。
- 普通策略失败优先测试 1 FAIL / 21 deselected；修复后相关 45 PASS / 29.38 秒。
- 最终 Backend 七文件联合 84 PASS / 62.05 秒；各轮一个 Starlette/AnyIO 弃用 warning。
- MCP 初次测试 tmpfs 输出权限失败；仅给测试输出 tmpfs 正确权限后编译通过。
  随后误启动全 npm test 因缺整栈 BYQ_MCP_TOKEN 配置中止，不能记为全量通过。
  普通策略新增提示初次编译另有 TS2345，修正已检查对象的类型标注后通过。
- 最终 MCP 五组：ML、普通策略、admission、官方 schema observation、实际 SDK server wire
  均通过；包含恶意字段/消息不外泄、原生停止标记不携带诊断、二次失败仍停止。
- 宿主 architecture 子目录 107 PASS；完整 CI 的 architecture/shared 组合 225 PASS。

依赖载体测试使用当前只读源码和 tmpfs 输出，不冒称新镜像认证。
每轮隔离 PostgreSQL 均以精确 scope 清理验证；无付费调用或生产数据。

## .15 官方进程跨服务验证

隔离 scope `post-u8-diagnostic-20260908-15`，真实 Gateway/MCP/Backend/PostgreSQL 与
官方 .15 Runtime，非转发合成 Provider，internal 网络；不启动训练或研究 Worker。
Runtime 镜像 `sha256:b2b7a7395a9fd97f2b28060e49add70fb9068cf754078ecc4d1198fb7435fa76`。

失败修正：[Provider](f7-diagnostic-provider.py)、[驱动](f7-diagnostic-probe.py)。
普通策略用 schema 合法但静态非法脚本，ML 用格式合法但日历不存在的日期。
第一轮安全字段提示确实进入模型请求；修正为另一错误后 native stop，分别四次本地请求，
总八次；每场景两个 correctable_failure claim，原因为 domain_validation_failed / correction_failed，
保存原安全字段，零 Artifact。根和 AgentRun 均 failed，公开事件含规范化停止原因，
无 session.result、私有摘要或测试源码。Backend/Gateway 重启后同样状态只读复核通过。

- 普通策略：`conversation_79117b3ef37244ff82ce6c4dae51ab68`。
- ML：`conversation_756a8be5c26140c89fbd4b542dcb2caf`。

成功修正：[Provider](f7-repair-success-provider.py)、[驱动](f7-repair-success-probe.py)。
两个场景第一轮同样得到领域拒绝，下一轮改为合法输入；各五次本地请求，总十次；
各一个失败回执、一个 succeeded 回执和一个 Artifact，根/AgentRun completed，
公开 session.result 仅声明校验完成，未批准、未训练、未回测。

- 普通策略：`conversation_5ce9cae10e1348669e05001869399212`。
- ML：`conversation_b9ce98c045684af3b1604f531cf1e437`。

撤销补测：[严格合法夹具](f7-valid-revoke-provider.py) 与既有 [驱动](f7-revoke-probe.py)。
修正普通策略缺 trace_id 的历史夹具缺陷，ML 保持其不接受 trace_id 的 schema。
用户禁用提交后再释放合法工具参数，两场景各四次本地请求，零 claim、零 Artifact、
任务 planned，新 Product 回合 401/403；模型 completed 不等于研究完成。

- 普通策略：`conversation_ce978c15e3e84d75820b7591d849fdac`。
- ML：`conversation_f6971bfd6bf542f3b9bde559f7c69fda`。

以上是脚本 Provider 的确定性资格，不是付费模型的自然语言自主研究评测。
探针 scope 已完成 `CI cleanup verified: post-u8-diagnostic-20260908-15`，
对应合成容器、数据库卷、网络和镜像标签已移除，可由夹具重建；最终 CI scope 不受影响。
`.14` 真实断连结果及原失败保留于 [跨服务记录](F7-CROSS-SERVICE-LOSS.md)。
生产、Community、历史 release 和私有备份不改，F6 仍关闭、数据扩容暂缓。

## 源身份与交付门禁

新增 immutable `.15`，不改写 `.14` 或更早 manifests。
Candidate：`sha256:effc3793a2ba8497303a14a7c988c36e8ddca421c40ac269202319c0fc7151db`。
Compatibility：`sha256:9b1562b4a7651da2123515f7b5f200997ebf758a591ae410da1069b61b38a1a4`。
完整本地 CI scope `post-u8-f7-final-20260908-15`：26/26 PASS、退出0；独立
cleanup verify-only 返回 `CI cleanup verified`，该 scope 合成资源已清理，可由夹具重建。
Backend 499 PASS / 1 skipped / 7 subtests（581.71 秒），Gateway 202 PASS，
兼容 Runtime 144 PASS / 32 skipped，实际 candidate 153 PASS / 23 skipped（14.70 秒），
真实进程/子 Agent 20 PASS（29.91 秒），MCP 全套 PASS，Frontend 175 PASS，
mocked 浏览器20 PASS、真实 Product9 PASS；重启持久化和双用户隔离均通过。
所有跳过与弃用/构建 warning 保留，不计为测试成功或无警告。
old/new 20-cycle 生命周期测试零 lingering_threads、零 retained_sessions；candidate 中位数
0.993034 秒、峰值 RSS 283.738 MiB，兼容中位数0.670217 秒、峰值210.824 MiB；
这是初始化/释放基准，不是生产模型端到端延迟或前述根切换性能的同一种测量。
新增证据文档在全 CI 计划启动后补充，另行执行全部变更 Markdown 检查，不重跑无关业务测试。
F7 全项核对通过后进入已授权交付；远端 CI 未通过前不合并，合并不授权生产部署。
