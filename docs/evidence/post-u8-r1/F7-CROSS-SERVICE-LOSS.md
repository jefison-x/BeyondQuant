# F7 ML 迟到请求与真实 MCP 断连（2026-09-08）

状态：以下具名跨服务探针通过，F7 仍开放；不得据此部署或推送合并。
维护者本轮明确要求完全整改 F7 后再推送合并，本工作树保持本地开发。

隔离 scope `post-u8-ml-late-http-20260908-14`，空合成数据库、internal 网络、
非转发脚本 Provider，无付费调用、无训练或 Worker、无生产用户。
实际 Runtime 镜像 `sha256:f26ef2167ec8667b297b8584a15a11929fc9e7354877a57af3c84e64be811c40`，
使用 `.14` candidate 源身份，未覆盖后续新增应用修改。

## ML 迟到请求

[Provider](f7-ml-late-http-provider.py) 与 [驱动](f7-ml-late-http-probe.py)：
公开会话 `conversation_7818a72c897042039543f0251d816770`，两个实际官方根进程不同
root/generation；第一根 failed，第二根 Product hard cancel 后 cancelled。
旧 body 换 root、换 root/generation、旧 key 改输入均返回 call_evidence_pending，
只读权威快照不变。精确旧/新失败回执可重放，3 份证据、3 个 claim、零 Artifact、
8 次本地 Provider 请求。Backend/Gateway 重启并健康后再次回放通过，上述计数不变。
与此前普通策略测试一致，这是重建相同语义 HTTP，不是延迟原 socket。

## 真实连接中断

[Provider](f7-loss-provider.py) 与 [驱动](f7-loss-probe.py)：
根注册并创建唯一合成任务后，第三个模型响应暂停。Engineering 在该隔离数据库对
artifacts 获取有界 SHARE 锁，释放有效工具响应；通过 pg_blocking_pids 确认 Backend
写入实际等待该锁，才由主机驱动 SIGKILL 此 scope 的 MCP 容器。
探针确认 MCP TCP 不可连接后回滚测试锁事务，Backend 完成领域提交。
重启 MCP、健康后，经真实 MCP HTTP 精确重放两次，只返回原 Artifact，
单一 succeeded claim 不变，响应不含私有身份/摘要。

- 普通策略 `ci-f7-loss-strategyvalid`：FAULT_READY → COMMIT_AFTER_DISCONNECT → PASS。
- ML 策略 `ci-f7-loss-mlqualified`：同样顺序通过。
- 两根最终 completed：只代表脚本模型结束，不代表研究任务完成；脚本回答明确表示
  传输结果未知、不能宣称完成或自动重试。

测试证明连接中断不等于写入失败，不使用测试修改后的 Backend 或 SDK。
这不是全部网络故障位置、长时间停机或真实模型语义的等价覆盖。
主机驱动暂存于 `/tmp/byq-f7-race-probe.xlTbla/loss-run.sh`，目标固定为本 scope。

## 保留失败与证据更正

普通策略首轮未触发锁等待：夹具漏传公开工具必填 trace_id，被 schema 拒绝。
补上后普通策略通过；ML 首轮则因错误共用该字段，被 ML 严格 schema 拒绝。
按各工具合同分别构造后，使用新合成用户验证通过；两次失败均未执行 SIGKILL，
不改 schema、不删除原失败记录或将其计入通过。
此前 f7-revoke-provider.py 同样给普通策略漏传 trace_id；其历史“身份禁用后零写入”
事实保留，但不能再据此宣称普通策略合法领域请求的撤销资格已充分证明，需独立补测。

按精确 scope 完成清理，返回 `CI cleanup verified: post-u8-ml-late-http-20260908-14`；
合成容器、卷、网络及镜像标签已移除，可重建，生产和私有备份不变。

## 新发现

源码复核发现 Agent 路径把 MLValidationError 转为通用 DomainValidationRejected，
持久回执丢失已有安全字段与类别提示；人类路径仍有 ml-validation-problem.v1。
正在新增失败测试并修复，不能将当前 F7 记为完成。
