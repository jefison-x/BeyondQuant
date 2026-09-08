# F7 有效成果提交、取消与回执丢失（2026-09-08）

状态：Backend 边界定向验证通过；不是 F7 全项完成或生产认证。

独立工作树 `post-u8-domain-receipt-races`，分支 `test/post-u8-domain-receipt-races`。
本批仅增加测试与独立构建身份，不修改业务实现、生产选择器或 DSH。

## 覆盖

在真实隔离 PostgreSQL 上对 `byq_strategy_validate` 和 `byq_ml_strategy_create`
的实际 Backend ASGI 路由各新增三个用例：

- 取消先到：即使已有调用证据，有效请求仍返回 409，零 Artifact、零 claim。
- 提交后回复丢失：在 ASGI response.start 发送前注入异常，确认 201 对应的事务已经
  提交而调用者未收到回复；随后根取消，精确重放两次返回原成果，独立数据库客户端也
  读取到相同持久回执，始终只有一个 Artifact 和一个 claim，根仍 cancelled。
- 提交与取消重叠：真实领域操作写入后、事务提交前暂停，另一个数据库连接同时投递
  根取消。只读查询 `pg_stat_activity` 和 `pg_blocking_pids` 确认真正出现 advisory 锁等待，
  不以线程启动时间或 sleep 推断竞争。释放事务后，成果和 succeeded 回执一起提交，
  取消随后完成；原成果可重放，根不重新激活。

探针有 15 秒暂停上限、5 秒锁等待观察上限和 finally 释放；不使用生产数据库锁。
沿用已有合成凭证 fixture，不声称是官方 DSH 实际投递的凭证。
这是 Backend ASGI/数据库测试，不是实际 MCP socket 断连、Gateway 取消 HTTP、
服务进程重启或权限撤销的跨服务联合资格测试。独立数据库客户端不等于服务重启。

## 实际结果

`services/backend/tests/test_domain_correction_admission.py`：第一轮新增四用例后
18 PASS / 15.43 秒；补齐两项并发竞争后 20 PASS / 17.12 秒。
各轮均有一个 Starlette/AnyIO DeprecationWarning，未将 warning 记作零。
随后联合调用凭证、AgentRun 生命周期、普通策略和 ML 策略五个测试文件回归：
69 PASS / 47.93 秒，仍为一个同类 warning；第三轮 scope 清理也已验证完成。
另有 12 项交付规则测试通过（0.892 秒）。
本批未发现新的业务实现缺陷，增加的是此前缺失的可重复回归证据。

使用既存 Backend 镜像仅作为依赖载体，挂载当前 Backend、测试和 packages 只读源码；
数据库为新建 tmpfs `byq_domain_test`，网络 internal，无生产数据、无模型请求、无训练。
这不认证新镜像。前两轮 scope `post-u8-receipt-races-20260908` 均完成
`CI cleanup verified`；合成容器、数据库和网络已清理，可由测试夹具重新生成。

## 独立源身份

新增 immutable `post-u8.14`，不改写 `.13` 或更早 manifests。

- Compatibility：`sha256:60dc64ca6fc45d34bf0f86ab31e9e4a71800fbd740940fa6eb7b51c9fc5e0a12`
- Candidate：`sha256:97c387698711af72f45f5b9c0704c288b0697b791c2d1bebf552ba2aef215b4d`

两份源绑定检查与 `git diff --check` 通过。不将源绑定等同于镜像/运行时认证。
后续仍需 ML 实际 MCP 迟到/取消矩阵、跨服务未知回执和全研究流程审计。
F6 保持关闭，S3 不扩大数据集，未经单独授权不部署生产。
